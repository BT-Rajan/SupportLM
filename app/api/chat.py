from fastapi import APIRouter
from pydantic import BaseModel

from app.services.chat import ask

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    question: str
    conversation_id: str | None = None


@router.post("")
def post_chat(req: ChatRequest):
    return ask(req.question, req.conversation_id)
