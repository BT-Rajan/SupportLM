"""Per-tenant LLM provider configuration endpoints (Phase 4 — 2.4).

`admin`+ floor for both read and write — same reasoning as api_keys.py:
this surface controls (and, on read, partially exposes) a live
credential, not just a preference toggle, so it sits at the same floor
as api-key management rather than being reachable at a lower role.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.rbac import require_role
from app.db.pool import get_conn

router = APIRouter(prefix="/api/tenant/llm-config", tags=["llm-config"])

_VALID_PROVIDERS = {"deepseek", "openai", "anthropic"}


class LlmConfigIn(BaseModel):
    provider: str
    model: str
    api_key: str | None = None  # None/omitted = fall back to the global key for this provider


class LlmConfigOut(BaseModel):
    provider: str
    model: str
    has_custom_api_key: bool  # never echoes the key itself back, configured or not


@router.get("", response_model=LlmConfigOut | None)
def get_llm_config(tenant_id: int = Depends(require_role("admin"))):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT provider, model, api_key FROM tenant_llm_config WHERE tenant_id = %s",
            (tenant_id,),
        )
        row = cur.fetchone()
        cur.close()
    if row is None:
        return None
    return LlmConfigOut(
        provider=row["provider"],
        model=row["model"],
        has_custom_api_key=bool(row["api_key"]),
    )


@router.post("", response_model=LlmConfigOut)
def set_llm_config(req: LlmConfigIn, tenant_id: int = Depends(require_role("admin"))):
    if req.provider not in _VALID_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{req.provider}'; must be one of {sorted(_VALID_PROVIDERS)}",
        )
    if not req.model.strip():
        raise HTTPException(status_code=400, detail="model is required")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO tenant_llm_config (tenant_id, provider, model, api_key)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE provider = VALUES(provider), model = VALUES(model),
                                       api_key = VALUES(api_key)""",
            (tenant_id, req.provider, req.model, req.api_key or None),
        )
        cur.close()

    return LlmConfigOut(
        provider=req.provider,
        model=req.model,
        has_custom_api_key=bool(req.api_key),
    )


@router.post("/reset")
def reset_llm_config(tenant_id: int = Depends(require_role("admin"))):
    """Deletes the tenant's override, reverting to the global default
    provider — the explicit "un-configure" action, matching the
    branding fallback's "cleared field, not an empty string treated as
    a value" pattern from Phase 1's set_tenant_branding.py."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tenant_llm_config WHERE tenant_id = %s", (tenant_id,))
        cur.close()
    return {"ok": True}
