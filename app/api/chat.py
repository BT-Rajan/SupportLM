import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.chat import ask

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    question: str
    conversation_id: str | None = None


@router.post("")
def post_chat(req: ChatRequest):
    try:
        return ask(req.question, req.conversation_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Chat provider returned an error ({exc.response.status_code}): {exc.response.text[:300]}",
        )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach chat provider: {exc}")
