import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.core.tenant_scope import resolve_tenant
from app.core.theme import resolve_theme
from app.services.chat import ask
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


@router.post("")
def post_chat(req: ChatRequest, tenant_id: int = Depends(resolve_tenant)):
    try:
        agent_name = resolve_theme(tenant_id)["agent_name"]
        result = ask(tenant_id, req.question, req.conversation_id, agent_name=agent_name, language=req.language)
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
    """4.2: anonymous, opt-in — same `resolve_tenant` (not
    `resolve_tenant_for_admin`) auth as `post_chat` above, matching
    the rest of the chat widget's auth-free surface. Every failure
    mode here (bad email, conversation not found for this tenant, no
    messages yet, SMTP not configured) is a `TranscriptEmailError`
    with a message safe to show an anonymous visitor directly — none
    of them are "unexpected" the way post_chat's catch-all is, so this
    doesn't need that same broad except-Exception fallback."""
    try:
        agent_name = resolve_theme(tenant_id)["agent_name"]
        send_transcript_email(tenant_id, req.conversation_id, req.email, agent_name=agent_name)
        return {"ok": True}
    except TranscriptEmailError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
