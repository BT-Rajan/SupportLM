"""Prompt version management (Phase 4 — 3.2).

`create_version()` always inserts a new row, never overwrites — an
admin can draft/preview a new prompt without it going live, the same
"no more instant-live" spirit Phase 3 established for documents
(review before publish). Activation is a separate, explicit step.

`activate_version()` is also how rollback works: reactivating an older
version_id IS the rollback — there's no separate revert mutation on
past rows, since every version's prompt_text is immutable once created.
"""
from app.db.pool import get_conn, get_cursor


def create_version(tenant_id: int, prompt_text: str, admin_id: int | None) -> dict:
    """Version numbers come from `tenant.next_prompt_version_seq`, an
    atomic per-tenant counter (migrations/024_prompt_version_seq.sql)
    — NOT a `SELECT MAX(version_number) + 1`, which raced under
    concurrent calls, and NOT that same query with `FOR UPDATE`
    either, which fixed the race but introduced real deadlocks on a
    tenant's first version (a `FOR UPDATE` matching zero rows still
    takes a gap lock, and concurrent threads contending for the same
    empty gap can deadlock each other — confirmed directly with a
    concurrency test before this fix). A plain `UPDATE` against the
    tenant row — which always already exists — takes a definite row
    lock instead, so concurrent callers serialize cleanly rather than
    deadlocking. See the migration for the starts-at-0 reasoning."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE tenant SET next_prompt_version_seq = next_prompt_version_seq + 1 WHERE id = %s",
            (tenant_id,),
        )
        cur.execute("SELECT next_prompt_version_seq AS v FROM tenant WHERE id = %s", (tenant_id,))
        next_version = cur.fetchone()["v"]
        cur.execute(
            """INSERT INTO tenant_prompt_version (tenant_id, version_number, prompt_text, created_by_admin_id)
               VALUES (%s, %s, %s, %s)""",
            (tenant_id, next_version, prompt_text, admin_id),
        )
        version_id = cur.lastrowid
        cur.close()
    return {"id": version_id, "version_number": next_version, "prompt_text": prompt_text}


def activate_version(tenant_id: int, version_id: int) -> bool:
    """Sets this version as the tenant's active prompt. Returns False
    (does nothing) if version_id doesn't belong to this tenant — same
    cross-tenant guard pattern as every other Phase 1-3 write path
    (e.g. api_keys.py's revoke, documents.py's category_id check):
    reject by id-ownership check rather than trusting the caller's
    tenant_id/version_id pairing."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM tenant_prompt_version WHERE id = %s AND tenant_id = %s",
            (version_id, tenant_id),
        )
        if cur.fetchone() is None:
            cur.close()
            return False
        cur.execute(
            "UPDATE tenant SET active_prompt_version_id = %s WHERE id = %s",
            (version_id, tenant_id),
        )
        cur.close()
    return True


def list_versions(tenant_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT tpv.id, tpv.version_number, tpv.prompt_text, tpv.created_at,
                      tpv.id = t.active_prompt_version_id AS is_active
               FROM tenant_prompt_version tpv
               JOIN tenant t ON t.id = tpv.tenant_id
               WHERE tpv.tenant_id = %s
               ORDER BY tpv.version_number DESC""",
            (tenant_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": row["id"],
            "version_number": row["version_number"],
            "prompt_text": row["prompt_text"],
            "created_at": str(row["created_at"]),
            "is_active": bool(row["is_active"]),
        }
        for row in rows
    ]


def get_active_prompt(tenant_id: int) -> str | None:
    """The active version's prompt_text, or None if the tenant has none
    configured — caller (chat.py's ask()) falls back to its own
    hardcoded _SYSTEM_PROMPT default in that case, same fallback
    contract as 2.0's get_provider()."""
    with get_cursor() as cur:
        cur.execute(
            """SELECT tpv.prompt_text
               FROM tenant t
               JOIN tenant_prompt_version tpv ON tpv.id = t.active_prompt_version_id
               WHERE t.id = %s""",
            (tenant_id,),
        )
        row = cur.fetchone()
    return row["prompt_text"] if row else None
