"""Agent/bot configuration endpoint (Phase 8 — 3.3).

Supersedes `scripts/set_tenant_branding.py` for `agent_name`/`tone`
specifically — that script remains valid for `display_name`/
`logo_url`/`accent_hex`, which stay out of this phase's scope.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.rbac import require_role
from app.db.pool import get_conn

router = APIRouter(prefix="/api/tenant/agent-config", tags=["agent-config"])


class AgentConfigIn(BaseModel):
    agent_name: str | None = None
    tone: str | None = None


class AgentConfigOut(BaseModel):
    agent_name: str | None = None
    tone: str | None = None


@router.get("", response_model=AgentConfigOut)
def get_agent_config(tenant_id: int = Depends(require_role("admin"))):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT agent_name, tone FROM tenant_branding WHERE tenant_id = %s", (tenant_id,))
        row = cur.fetchone()
        cur.close()
    if row is None:
        return AgentConfigOut()
    return AgentConfigOut(agent_name=row["agent_name"], tone=row["tone"])


@router.post("", response_model=AgentConfigOut)
def set_agent_config(req: AgentConfigIn, tenant_id: int = Depends(require_role("admin"))):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO tenant_branding (tenant_id, agent_name, tone) VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE agent_name = VALUES(agent_name), tone = VALUES(tone)""",
            (tenant_id, req.agent_name, req.tone),
        )
        cur.close()
    return AgentConfigOut(agent_name=req.agent_name, tone=req.tone)
