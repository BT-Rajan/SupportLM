"""Isolates the embedding/chat provider behind a small interface. Swap the
implementation here without touching callers if the provider changes."""
import httpx

from app.core.config import settings

_EMBED_URL = "https://api.openai.com/v1/embeddings"
_CHAT_URL = "https://api.openai.com/v1/chat/completions"


def embed_text(text: str) -> list[float]:
    resp = httpx.post(
        _EMBED_URL,
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={"model": settings.llm_embedding_model, "input": text},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def chat_completion(system_prompt: str, user_message: str) -> str:
    resp = httpx.post(
        _CHAT_URL,
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={
            "model": settings.llm_chat_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
