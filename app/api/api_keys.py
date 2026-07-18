"""API key management endpoints (Phase 2 WBS 2.2).

Create/list/revoke for the `api_key` table `009_api_keys.sql` adds.
All three routes are `admin`+ — minting, viewing, and revoking
programmatic credentials are all as sensitive as the credential itself,
not just the mint step, so the whole surface sits behind the same
floor rather than list/revoke being reachable at a lower role.

Create caps the new key's role at the creating admin's own role rank
(via `require_role_ctx`, not just `require_role`) — the WBS only says
"minting is admin+ only", but an admin (rank 2) minting an `owner`
(rank 3) key would let them hand themselves owner-equivalent access
through the back door. Capping at the creator's own rank closes that
without changing what the WBS asked for: an admin can still mint an
admin-or-lower key, exactly as before.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.rbac import (
    ROLE_RANK,
    generate_api_key,
    hash_api_key,
    key_prefix_for_display,
    require_role,
    require_role_ctx,
)
from app.db.pool import get_conn

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


class ApiKeyCreate(BaseModel):
    name: str
    role: str = "viewer"


class ApiKeyCreated(BaseModel):
    id: int
    name: str
    role: str
    key_prefix: str
    api_key: str  # raw key — present only in this one response, never again


class ApiKeyOut(BaseModel):
    id: int
    name: str
    role: str
    key_prefix: str
    created_at: str
    revoked_at: str | None = None


@router.post("", response_model=ApiKeyCreated)
def create_api_key(
    req: ApiKeyCreate,
    ctx: tuple[int, str, int | None] = Depends(require_role_ctx("admin")),
):
    tenant_id, creator_role, creator_admin_id = ctx

    if req.role not in ROLE_RANK:
        raise HTTPException(status_code=400, detail=f"Unknown role '{req.role}'; must be one of {sorted(ROLE_RANK)}")
    if ROLE_RANK[req.role] > ROLE_RANK[creator_role]:
        raise HTTPException(
            status_code=400,
            detail=f"You cannot mint a key with a role higher than your own ('{creator_role}').",
        )

    raw_key = generate_api_key()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO api_key (tenant_id, name, key_prefix, key_hash, role, created_by_admin_id)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (tenant_id, req.name, key_prefix_for_display(raw_key), hash_api_key(raw_key), req.role, creator_admin_id),
        )
        key_id = cur.lastrowid
        cur.close()

    return ApiKeyCreated(
        id=key_id,
        name=req.name,
        role=req.role,
        key_prefix=key_prefix_for_display(raw_key),
        api_key=raw_key,
    )


@router.get("", response_model=list[ApiKeyOut])
def list_api_keys(tenant_id: int = Depends(require_role("admin"))):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, name, role, key_prefix, created_at, revoked_at
               FROM api_key WHERE tenant_id = %s ORDER BY created_at DESC""",
            (tenant_id,),
        )
        rows = cur.fetchall()
        cur.close()
    return [
        ApiKeyOut(
            id=row["id"],
            name=row["name"],
            role=row["role"],
            key_prefix=row["key_prefix"],
            created_at=str(row["created_at"]),
            revoked_at=str(row["revoked_at"]) if row["revoked_at"] else None,
        )
        for row in rows
    ]


@router.post("/{key_id}/revoke")
def revoke_api_key(key_id: int, tenant_id: int = Depends(require_role("admin"))):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE api_key SET revoked_at = NOW()
               WHERE id = %s AND tenant_id = %s AND revoked_at IS NULL""",
            (key_id, tenant_id),
        )
        updated = cur.rowcount
        cur.close()
    if updated == 0:
        # Either it doesn't exist for this tenant, or it's already
        # revoked — both are "nothing to do" from the caller's
        # perspective, but distinguishing them isn't worth leaking
        # which via a different status code, so both 404.
        raise HTTPException(status_code=404, detail="API key not found or already revoked")
    return {"ok": True}
