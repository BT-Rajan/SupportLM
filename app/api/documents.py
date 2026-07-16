from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.rbac import require_role
from app.db.pool import get_conn
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


@router.post("/upload", response_model=DocumentOut)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    category_id: int | None = None,
    tenant_id: int = Depends(require_role("editor")),
):
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
def set_review_state(document_id: int, req: ReviewStateIn, tenant_id: int = Depends(require_role("editor"))):
    """WBS 1.2. No restriction on which direction a transition goes
    (draft->review->published, or straight back to draft to unpublish,
    etc.) beyond the three legal values — the owner's explicit
    decision was that editor+ can move a document through every state,
    not just forward, so there's no separate reviewer/publisher role
    gate to enforce here."""
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
    return DocumentOut(**row)


@router.delete("/{document_id}")
def delete_document(document_id: int, tenant_id: int = Depends(require_role("admin"))):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM document WHERE id = %s AND tenant_id = %s", (document_id, tenant_id))
        deleted = cur.rowcount
        cur.close()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}
