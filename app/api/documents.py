from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.core.rbac import require_role, require_role_ctx
from app.db.pool import get_conn
from app.services.audit import log_audit_event
from app.services.duplicate_detection import scan_for_duplicates
from app.services.ingestion import ingest_document
from app.services.usage import enforce_document_limit
from app.services.website_sync import WebsiteSyncError, sync_all_sources

# WBS 1.3: replaces the flat resolve_tenant_for_admin-only gate (any
# linked admin, any action) with per-route minimum roles. No router-
# level `dependencies=[...]` default anymore since the routes below no
# longer share one minimum — each declares its own via require_role().
router = APIRouter(prefix="/api/documents", tags=["documents"])


class DocumentOut(BaseModel):
    id: int
    title: str
    status: str
    review_state: str
    error_message: str | None = None


class ReviewStateIn(BaseModel):
    state: str


_REVIEW_STATES = {"draft", "review", "published"}


class SyncSourceIn(BaseModel):
    url: str


class SyncSourceOut(BaseModel):
    id: int
    url: str
    document_id: int | None = None
    last_synced_at: str | None = None
    created_at: str


class SyncResult(BaseModel):
    id: int
    url: str
    status: str


class DuplicateFlagOut(BaseModel):
    id: int
    document_id_a: int
    title_a: str
    document_id_b: int
    title_b: str
    source: str
    label_a: str
    label_b: str
    similarity: float
    detected_at: str


@router.post("/upload", response_model=DocumentOut)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    request: Request,
    category_id: int | None = None,
    ctx: tuple[int, str, int | None] = Depends(require_role_ctx("editor")),
):
    tenant_id, _role, admin_id = ctx
    # Check BEFORE reading/inserting anything — a tenant at its limit
    # shouldn't have the upload partially processed first.
    enforce_document_limit(tenant_id)

    raw = (await file.read()).decode("utf-8")
    title = file.filename.rsplit(".", 1)[0]

    with get_conn() as conn:
        cur = conn.cursor()
        if category_id is not None:
            # Reject a category_id belonging to a different tenant —
            # without this check, a document could be filed under
            # another tenant's category by id-guessing.
            cur.execute("SELECT id FROM category WHERE id = %s AND tenant_id = %s", (category_id, tenant_id))
            if cur.fetchone() is None:
                cur.close()
                raise HTTPException(status_code=400, detail="Invalid category")
        cur.execute(
            """INSERT INTO document (tenant_id, category_id, title, filename, raw_markdown, status, review_state)
               VALUES (%s, %s, %s, %s, %s, 'pending', 'draft')""",
            (tenant_id, category_id, title, file.filename, raw),
        )
        document_id = cur.lastrowid
        cur.close()

    # Phase 8 — 1.2: audit the upload itself, not ingestion's later
    # success/failure — "an upload happened" is the auditable event.
    log_audit_event(tenant_id, admin_id, "upload", "document", document_id, detail=title, request=request)

    background_tasks.add_task(ingest_document, document_id)
    return DocumentOut(id=document_id, title=title, status="pending", review_state="draft")


@router.get("", response_model=list[DocumentOut])
def list_documents(tenant_id: int = Depends(require_role("viewer"))):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, status, review_state, error_message FROM document WHERE tenant_id = %s ORDER BY uploaded_at DESC",
            (tenant_id,),
        )
        rows = cur.fetchall()
        cur.close()
    return [DocumentOut(**row) for row in rows]


@router.post("/sync-sources", response_model=SyncSourceOut)
def add_sync_source(req: SyncSourceIn, tenant_id: int = Depends(require_role("editor"))):
    """WBS 2.3. `editor`+ — matches 1.0's upload floor, since adding a
    source is what eventually creates a document, same as upload."""
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM tenant_sync_source WHERE tenant_id = %s AND url = %s", (tenant_id, url))
        if cur.fetchone() is not None:
            cur.close()
            raise HTTPException(status_code=400, detail="This URL is already configured for sync.")
        cur.execute(
            "INSERT INTO tenant_sync_source (tenant_id, url) VALUES (%s, %s)",
            (tenant_id, url),
        )
        source_id = cur.lastrowid
        cur.execute(
            "SELECT id, url, document_id, last_synced_at, created_at FROM tenant_sync_source WHERE id = %s",
            (source_id,),
        )
        row = cur.fetchone()
        cur.close()
    return SyncSourceOut(
        id=row["id"], url=row["url"], document_id=row["document_id"],
        last_synced_at=str(row["last_synced_at"]) if row["last_synced_at"] else None,
        created_at=str(row["created_at"]),
    )


@router.get("/sync-sources", response_model=list[SyncSourceOut])
def list_sync_sources(tenant_id: int = Depends(require_role("viewer"))):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, url, document_id, last_synced_at, created_at FROM tenant_sync_source "
            "WHERE tenant_id = %s ORDER BY created_at DESC",
            (tenant_id,),
        )
        rows = cur.fetchall()
        cur.close()
    return [
        SyncSourceOut(
            id=row["id"], url=row["url"], document_id=row["document_id"],
            last_synced_at=str(row["last_synced_at"]) if row["last_synced_at"] else None,
            created_at=str(row["created_at"]),
        )
        for row in rows
    ]


@router.delete("/sync-sources/{source_id}")
def delete_sync_source(source_id: int, tenant_id: int = Depends(require_role("editor"))):
    """Removes the sync config only — does NOT delete the document a
    prior sync produced (that's the regular DELETE /{document_id}
    below, a separate, explicit action). Matches
    migrations/013_website_sync.sql's ON DELETE SET NULL: a document
    outliving the source that created it is the expected shape, not a
    bug to guard against here."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tenant_sync_source WHERE id = %s AND tenant_id = %s", (source_id, tenant_id))
        deleted = cur.rowcount
        cur.close()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Sync source not found")
    return {"ok": True}


@router.post("/sync-sources/sync-now", response_model=list[SyncResult])
def sync_sources_now(tenant_id: int = Depends(require_role("admin"))):
    """WBS 2.3: manual trigger only, per the owner's kickoff decision
    (docs/Phase III WBS.md) — no cron. `admin`+, not `editor`+: this
    fetches external URLs and writes documents on the caller's behalf,
    closer to upload than to a read-only action, so it sits at the
    same floor as delete_document below. Runs synchronously (not
    BackgroundTasks like upload/reindex) — an admin clicking "Sync
    now" is explicitly waiting for the result to show in the UI, not
    firing a background job; the per-source try/except in
    sync_all_sources() already keeps one slow/broken URL from blocking
    the others for long."""
    try:
        results = sync_all_sources(tenant_id)
    except WebsiteSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return [SyncResult(**r) for r in results]


@router.post("/scan-duplicates", response_model=list[DuplicateFlagOut])
def scan_duplicates(tenant_id: int = Depends(require_role("admin"))):
    """WBS 3.3: manual trigger only — same shape as 2.3's 'Sync now',
    for consistency (this cadence question was an explicit assumption
    at kickoff, not a confirmed decision — see docs/Phase III WBS.md).
    `admin`+, not `editor`+: matches sync-now's floor, since both are
    "run an expensive scan across the whole tenant" actions rather
    than routine content edits. Returns only the flags newly created
    by this run (see scan_for_duplicates()'s dedup behavior) — not
    the full unresolved list, which is what GET /duplicate-flags
    below is for."""
    new_flags = scan_for_duplicates(tenant_id)
    if not new_flags:
        return []
    return _hydrate_flags(tenant_id, [f["id"] for f in new_flags])


@router.get("/duplicate-flags", response_model=list[DuplicateFlagOut])
def list_duplicate_flags(tenant_id: int = Depends(require_role("viewer"))):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT df.id, df.document_id_a, da.title AS title_a,
                      df.document_id_b, db.title AS title_b,
                      df.source, df.label_a, df.label_b, df.similarity, df.detected_at
               FROM duplicate_flag df
               JOIN document da ON da.id = df.document_id_a
               JOIN document db ON db.id = df.document_id_b
               WHERE df.tenant_id = %s AND df.resolved_at IS NULL
               ORDER BY df.similarity DESC, df.detected_at DESC""",
            (tenant_id,),
        )
        rows = cur.fetchall()
        cur.close()
    return [DuplicateFlagOut(**{**row, "detected_at": str(row["detected_at"])}) for row in rows]


@router.post("/duplicate-flags/{flag_id}/resolve")
def resolve_duplicate_flag(flag_id: int, tenant_id: int = Depends(require_role("editor"))):
    """`editor`+ — dismissing a flag ("looked at this, it's fine") is
    a routine content-review action, same floor as 1.2's review-state
    transitions, not the admin-only floor scanning/minting requires."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM duplicate_flag WHERE id = %s AND tenant_id = %s", (flag_id, tenant_id))
        if cur.fetchone() is None:
            cur.close()
            raise HTTPException(status_code=404, detail="Duplicate flag not found")
        cur.execute(
            "UPDATE duplicate_flag SET resolved_at = NOW() WHERE id = %s AND tenant_id = %s AND resolved_at IS NULL",
            (flag_id, tenant_id),
        )
        cur.close()
    return {"ok": True}


def _hydrate_flags(tenant_id: int, flag_ids: list[int]) -> list[DuplicateFlagOut]:
    """Re-fetches freshly-inserted flags with their document titles
    joined in, for scan_duplicates()'s response — scan_for_duplicates()
    itself only returns the bare row data, not the joined titles."""
    if not flag_ids:
        return []
    placeholders = ",".join(["%s"] * len(flag_ids))
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT df.id, df.document_id_a, da.title AS title_a,
                       df.document_id_b, db.title AS title_b,
                       df.source, df.label_a, df.label_b, df.similarity, df.detected_at
                FROM duplicate_flag df
                JOIN document da ON da.id = df.document_id_a
                JOIN document db ON db.id = df.document_id_b
                WHERE df.tenant_id = %s AND df.id IN ({placeholders})
                ORDER BY df.similarity DESC""",
            (tenant_id, *flag_ids),
        )
        rows = cur.fetchall()
        cur.close()
    return [DuplicateFlagOut(**{**row, "detected_at": str(row["detected_at"])}) for row in rows]


@router.post("/{document_id}/reindex", response_model=DocumentOut)
def reindex_document(document_id: int, background_tasks: BackgroundTasks, tenant_id: int = Depends(require_role("editor"))):
    with get_conn() as conn:
        cur = conn.cursor()
        # Confirm the document belongs to this tenant BEFORE touching
        # anything. Without this, id-guessing document_id could delete
        # another tenant's document_chunk rows via the DELETE below.
        cur.execute("SELECT id FROM document WHERE id = %s AND tenant_id = %s", (document_id, tenant_id))
        if cur.fetchone() is None:
            cur.close()
            raise HTTPException(status_code=404, detail="Document not found")

        cur.execute("DELETE FROM document_chunk WHERE document_id = %s AND tenant_id = %s", (document_id, tenant_id))
        cur.execute(
            "UPDATE document SET status = 'pending', error_message = NULL WHERE id = %s AND tenant_id = %s",
            (document_id, tenant_id),
        )
        cur.execute(
            "SELECT id, title, status, review_state, error_message FROM document WHERE id = %s AND tenant_id = %s",
            (document_id, tenant_id),
        )
        row = cur.fetchone()
        cur.close()

    background_tasks.add_task(ingest_document, document_id)
    return DocumentOut(**row)


@router.post("/{document_id}/review-state", response_model=DocumentOut)
def set_review_state(
    document_id: int,
    req: ReviewStateIn,
    request: Request,
    ctx: tuple[int, str, int | None] = Depends(require_role_ctx("editor")),
):
    """WBS 1.2. No restriction on which direction a transition goes
    (draft->review->published, or straight back to draft to unpublish,
    etc.) beyond the three legal values — the owner's explicit
    decision was that editor+ can move a document through every state,
    not just forward, so there's no separate reviewer/publisher role
    gate to enforce here."""
    tenant_id, _role, admin_id = ctx
    if req.state not in _REVIEW_STATES:
        raise HTTPException(status_code=400, detail=f"Unknown review state '{req.state}'; must be one of {sorted(_REVIEW_STATES)}")

    with get_conn() as conn:
        cur = conn.cursor()
        # Confirm the document exists for this tenant BEFORE updating —
        # can't rely on the UPDATE's rowcount for this (pymysql reports
        # rows *changed*, not rows *matched*, since db/pool.py doesn't
        # set CLIENT_FOUND_ROWS; setting review_state to the value it
        # already has would update 0 rows and incorrectly 404 a
        # document that's actually right there).
        cur.execute("SELECT id FROM document WHERE id = %s AND tenant_id = %s", (document_id, tenant_id))
        if cur.fetchone() is None:
            cur.close()
            raise HTTPException(status_code=404, detail="Document not found")

        cur.execute(
            "UPDATE document SET review_state = %s WHERE id = %s AND tenant_id = %s",
            (req.state, document_id, tenant_id),
        )
        cur.execute(
            "SELECT id, title, status, review_state, error_message FROM document WHERE id = %s AND tenant_id = %s",
            (document_id, tenant_id),
        )
        row = cur.fetchone()
        cur.close()

    log_audit_event(
        tenant_id, admin_id, "edit", "document", document_id, detail=f"review_state -> {req.state}", request=request
    )
    return DocumentOut(**row)


@router.delete("/{document_id}")
def delete_document(document_id: int, request: Request, ctx: tuple[int, str, int | None] = Depends(require_role_ctx("admin"))):
    tenant_id, _role, admin_id = ctx
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT title FROM document WHERE id = %s AND tenant_id = %s", (document_id, tenant_id))
        row = cur.fetchone()
        cur.execute("DELETE FROM document WHERE id = %s AND tenant_id = %s", (document_id, tenant_id))
        deleted = cur.rowcount
        cur.close()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    log_audit_event(
        tenant_id, admin_id, "delete", "document", document_id, detail=row["title"] if row else None, request=request
    )
    return {"ok": True}
