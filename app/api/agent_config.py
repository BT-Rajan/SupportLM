"""Agent/bot configuration endpoint (Phase 8 — 3.3, extended Phase 9 — 1.5).

Supersedes `scripts/set_tenant_branding.py` for `agent_name`/`tone`
specifically — that script remains valid for `display_name`/
`logo_url`/`accent_hex`, which stay out of this phase's scope.

Phase 9 adds `retrieval_confidence_threshold`: the cosine-similarity
floor below which retrieved KB chunks are treated as "no match" rather
than fed to the LLM as context (see app/services/chat.py). Same
admin-floor auth as agent_name/tone — this changes what the assistant
is willing to answer from, not cosmetic.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from app.core.rbac import require_role
from app.db.pool import get_conn

router = APIRouter(prefix="/api/tenant/agent-config", tags=["agent-config"])


class AgentConfigIn(BaseModel):
    agent_name: str | None = None
    tone: str | None = None
    retrieval_confidence_threshold: float | None = None

    @field_validator("retrieval_confidence_threshold")
    @classmethod
    def _validate_threshold(cls, value: float | None) -> float | None:
        # Bounds match the slider's min/max in the admin UI — validated
        # server-side too since this endpoint is reachable directly,
        # not just through that widget.
        if value is not None and not (0.0 <= value <= 1.0):
            raise ValueError("retrieval_confidence_threshold must be between 0.0 and 1.0")
        return value


class AgentConfigOut(BaseModel):
    agent_name: str | None = None
    tone: str | None = None
    retrieval_confidence_threshold: float | None = None


@router.get("", response_model=AgentConfigOut)
def get_agent_config(tenant_id: int = Depends(require_role("admin"))):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT agent_name, tone, retrieval_confidence_threshold
               FROM tenant_branding WHERE tenant_id = %s""",
            (tenant_id,),
        )
        row = cur.fetchone()
        cur.close()
    if row is None:
        return AgentConfigOut()
    return AgentConfigOut(
        agent_name=row["agent_name"],
        tone=row["tone"],
        retrieval_confidence_threshold=(
            float(row["retrieval_confidence_threshold"])
            if row["retrieval_confidence_threshold"] is not None
            else None
        ),
    )


@router.post("", response_model=AgentConfigOut)
def set_agent_config(req: AgentConfigIn, tenant_id: int = Depends(require_role("admin"))):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO tenant_branding (tenant_id, agent_name, tone, retrieval_confidence_threshold)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE agent_name = VALUES(agent_name),
                                       tone = VALUES(tone),
                                       retrieval_confidence_threshold = VALUES(retrieval_confidence_threshold)""",
            (tenant_id, req.agent_name, req.tone, req.retrieval_confidence_threshold),
        )
        cur.close()
    return AgentConfigOut(
        agent_name=req.agent_name,
        tone=req.tone,
        retrieval_confidence_threshold=req.retrieval_confidence_threshold,
    )
