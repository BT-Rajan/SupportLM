"""Per-tenant support inbox configuration (Phase 6 — 3.3).

`admin`+ floor, same as llm_config.py/prompt_versions.py's activate —
this controls where escalated customer issues actually get routed,
not a cosmetic preference.
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.rbac import require_role
from app.db.pool import get_conn

router = APIRouter(prefix="/api/tenant/support-config", tags=["support-config"])

# Same deliberately loose pattern as transcript_email.py's validator —
# rejects obvious garbage before SMTP; SMTP's own delivery/bounce is
# the real validator, not a stricter regex here.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SupportConfigIn(BaseModel):
    support_email: str


class SupportConfigOut(BaseModel):
    support_email: str


@router.get("", response_model=SupportConfigOut | None)
def get_support_config(tenant_id: int = Depends(require_role("admin"))):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT support_email FROM tenant_support_config WHERE tenant_id = %s", (tenant_id,))
        row = cur.fetchone()
        cur.close()
    return SupportConfigOut(support_email=row["support_email"]) if row else None


@router.post("", response_model=SupportConfigOut)
def set_support_config(req: SupportConfigIn, tenant_id: int = Depends(require_role("admin"))):
    if not _EMAIL_RE.match(req.support_email):
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO tenant_support_config (tenant_id, support_email) VALUES (%s, %s)
               ON DUPLICATE KEY UPDATE support_email = VALUES(support_email)""",
            (tenant_id, req.support_email),
        )
        cur.close()

    return SupportConfigOut(support_email=req.support_email)
