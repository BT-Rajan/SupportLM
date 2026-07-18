import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.core.tenant_scope import resolve_tenant
from app.core.theme import resolve_theme
from app.db.pool import get_conn
from app.services.chat import ask
from app.services.escalation import EscalationError, complete_escalation
from app.services.transcript_email import TranscriptEmailError, send_transcript_email
from app.services.usage import message_limit_warning

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(resolve_tenant)])
logger = logging.getLogger("supportlm.chat")


class ChatRequest(BaseModel):
    question: str
    conversation_id: str | None = None
    language: str | None = None  # Phase 5 — 2.4: widget's selected language code, e.g. 'es'


class TranscriptRequest(BaseModel):
    conversation_id: str
    email: str


class FeedbackRequest(BaseModel):
    rating: str  # 'up' or 'down'


class EscalationRequest(BaseModel):
    email: str


@router.post("")
def post_chat(req: ChatRequest, request: Request, tenant_id: int = Depends(resolve_tenant)):
    # Phase 8 — 2.4: enforced first, before anything else runs — a
    # rejected request shouldn't still cost an embedding call or a
    # provider round-trip.
    enforce_rate_limit(tenant_id, request)
    try:
        theme = resolve_theme(tenant_id)
        result = ask(
            tenant_id,
            req.question,
            req.conversation_id,
            agent_name=theme["agent_name"],
            language=req.language,
            tone=theme["tone"],
            confidence_threshold=theme["retrieval_confidence_threshold"],
        )
        # Soft warn only — never blocks the chat, per the owner's
        # decision that message limits warn rather than reject.
        result["limit_warning"] = message_limit_warning(tenant_id)
        return result
    except httpx.HTTPStatusError as exc:
        logger.error("Chat provider HTTP error: %s", exc.response.text[:500])
        raise HTTPException(
            status_code=502,
            detail=f"Chat provider returned an error ({exc.response.status_code}): {exc.response.text[:300]}",
        )
    except httpx.RequestError as exc:
        logger.error("Could not reach chat provider: %s", exc)
        raise HTTPException(status_code=502, detail=f"Could not reach chat provider: {exc}")
    except Exception as exc:
        # Anything else (bad DeepSeek response shape, DB error, embedding
        # failure, etc.) used to propagate uncaught. Starlette then returns
        # a *plain-text* 500 body, which breaks `await res.json()` on the
        # frontend and surfaces as an opaque "Something went wrong" with no
        # way to diagnose it. Always return a JSON body here instead, and
        # log the real exception so it's actually visible server-side.
        logger.exception("Unhandled error answering chat question: %r", req.question)
        detail = (
            f"{type(exc).__name__}: {exc}"
            if settings.app_env == "development"
            else "The assistant hit an unexpected error generating a response. Please try again."
        )
        raise HTTPException(status_code=500, detail=detail)


@router.post("/transcript")
def post_transcript(req: TranscriptRequest, tenant_id: int = Depends(resolve_tenant)):
    try:
        agent_name = resolve_theme(tenant_id)["agent_name"]
        send_transcript_email(tenant_id, req.conversation_id, req.email, agent_name=agent_name)
        return {"ok": True}
    except TranscriptEmailError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{message_id}/feedback")
def post_message_feedback(message_id: int, req: FeedbackRequest, tenant_id: int = Depends(resolve_tenant)):
    if req.rating not in ("up", "down"):
        raise HTTPException(status_code=400, detail="rating must be 'up' or 'down'")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT role FROM message WHERE id = %s AND tenant_id = %s",
            (message_id, tenant_id),
        )
        row = cur.fetchone()
        if row is None:
            cur.close()
            raise HTTPException(status_code=404, detail="Message not found")
        if row["role"] != "assistant":
            cur.close()
            raise HTTPException(status_code=400, detail="Only assistant answers can be rated")

        cur.execute(
            "SELECT id FROM message_feedback WHERE message_id = %s",
            (message_id,),
        )
        if cur.fetchone() is not None:
            cur.close()
            raise HTTPException(status_code=409, detail="Feedback already submitted for this message")

        cur.execute(
            "INSERT INTO message_feedback (tenant_id, message_id, rating) VALUES (%s, %s, %s)",
            (tenant_id, message_id, req.rating),
        )
        cur.close()

    return {"ok": True}


@router.post("/{message_id}/escalate")
def post_escalate(message_id: int, req: EscalationRequest, tenant_id: int = Depends(resolve_tenant)):
    try:
        result = complete_escalation(tenant_id, message_id, req.email)
    except EscalationError as exc:
        detail = str(exc)
        if detail == "Message not found.":
            raise HTTPException(status_code=404, detail=detail)
        if detail == "A support request was already created for this conversation.":
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)

    return result
