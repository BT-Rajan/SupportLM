"""Local embedding model, provider-agnostic (Phase 4 — 2.0).

Chat completions moved to app/core/llm_providers.py, which is now
pluggable across DeepSeek/OpenAI/Anthropic, selected per-tenant. This
file keeps only embed_text() — embeddings run LOCALLY via
sentence-transformers regardless of which provider a tenant picks for
chat (not every provider offers a public embeddings endpoint, and
switching embedding models mid-flight would invalidate every stored
vector, so this stays a single, install-wide choice).
"""
from app.core.config import settings

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
