"""Isolates the chat/embedding provider behind a small interface.

Chat completions go to DeepSeek (OpenAI-compatible chat API).
Embeddings run LOCALLY via sentence-transformers — DeepSeek does not
offer a public embeddings endpoint, so there is no remote embedding
call to make. This also means ingestion has one less external
failure mode (no network/API-key dependency for embedding).
"""
import httpx

from app.core.config import settings

_CHAT_URL = "https://api.deepseek.com/chat/completions"

# Loaded lazily on first use — avoids paying the model-load cost at
# import time (e.g. for scripts that don't need embeddings).
_embedding_model = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(settings.embedding_model_name)
    return _embedding_model


def embed_text(text: str) -> list[float]:
    model = _get_embedding_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


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
