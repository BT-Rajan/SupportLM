"""Per-tenant prompt versioning endpoints (Phase 4 — 3.3).

Create is `editor`+ (drafting a new prompt version doesn't make it
live — same low-risk-to-draft floor documents.py uses for uploads).
Activate is `admin`+ (this is the one action that actually changes
what every visitor's conversation sees — same floor as api_keys.py's
mint/revoke). List is `viewer`+ (read-only, no floor needed beyond
"is a member of this tenant at all").
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.rbac import require_role, require_role_ctx
from app.services.prompt_versions import activate_version, create_version, list_versions

router = APIRouter(prefix="/api/tenant/prompt-versions", tags=["prompt-versions"])


class PromptVersionCreate(BaseModel):
    prompt_text: str


class PromptVersionOut(BaseModel):
    id: int
    version_number: int
    prompt_text: str
    created_at: str | None = None
    is_active: bool | None = None


@router.post("", response_model=PromptVersionOut)
def create_prompt_version(
    req: PromptVersionCreate,
    ctx: tuple[int, str, int | None] = Depends(require_role_ctx("editor")),
):
    tenant_id, _role, admin_id = ctx
    if not req.prompt_text.strip():
        raise HTTPException(status_code=400, detail="prompt_text is required")

    result = create_version(tenant_id, req.prompt_text, admin_id)
    return PromptVersionOut(
        id=result["id"], version_number=result["version_number"], prompt_text=result["prompt_text"]
    )


@router.get("", response_model=list[PromptVersionOut])
def get_prompt_versions(tenant_id: int = Depends(require_role("viewer"))):
    return [PromptVersionOut(**v) for v in list_versions(tenant_id)]


@router.post("/{version_id}/activate")
def activate_prompt_version(version_id: int, tenant_id: int = Depends(require_role("admin"))):
    ok = activate_version(tenant_id, version_id)
    if not ok:
        # Doesn't exist, or belongs to a different tenant — both are
        # "nothing to activate" from the caller's perspective, same
        # non-distinguishing 404 as api_keys.py's revoke.
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return {"ok": True}
