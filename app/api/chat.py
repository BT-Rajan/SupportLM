import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.core.tenant_scope import resolve_tenant
from app.core.theme import resolve_theme
from app.services.chat import ask
from app.services.usage import message_limit_warning

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(resolve_tenant)])
logger = logging.getLogger("supportlm.chat")


class ChatRequest(BaseModel):
    question: str
    conversation_id: str | None = None


@router.post("")
def post_chat(req: ChatRequest, tenant_id: int = Depends(resolve_tenant)):
    try:
        agent_name = resolve_theme(tenant_id)["agent_name"]
        result = ask(tenant_id, req.question, req.conversation_id, agent_name=agent_name)
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
