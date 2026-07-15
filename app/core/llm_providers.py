"""Pluggable chat-completion providers (Phase 4 — 2.0).

Mirrors the VectorStore protocol pattern in vector_store.py: one small
interface, one implementation class per provider, and a resolver
function that picks the right instance at call time. Replaces
llm_client.py's previous hard-coded, DeepSeek-only chat_completion() —
llm_client.py now only owns embed_text(), which stays provider-agnostic
per the Phase 4 kickoff decision (embeddings run locally regardless of
which provider a tenant picks for chat).

Each provider wraps that provider's own request/response shape rather
than being forced into a shared "OpenAI-compatible" base class —
DeepSeek and OpenAI happen to share a shape today, but Anthropic's
/v1/messages does not (system prompt is a top-level field, not a
messages-array entry; response content is a list of blocks, not a
single message string), so hard-coding that assumption into a shared
base would break the moment any provider's API changes independently.
"""
import httpx

from app.core.config import settings
from app.db.pool import get_cursor


class ChatProvider:
    def chat_completion(self, system_prompt: str, user_message: str) -> str:
        raise NotImplementedError


class DeepSeekProvider(ChatProvider):
    _URL = "https://api.deepseek.com/chat/completions"

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model

    def chat_completion(self, system_prompt: str, user_message: str) -> str:
        resp = httpx.post(
            self._URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class OpenAIProvider(ChatProvider):
    _URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model

    def chat_completion(self, system_prompt: str, user_message: str) -> str:
        resp = httpx.post(
            self._URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class AnthropicProvider(ChatProvider):
    _URL = "https://api.anthropic.com/v1/messages"
    _ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model

    def chat_completion(self, system_prompt: str, user_message: str) -> str:
        resp = httpx.post(
            self._URL,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": self._ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": 1024,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}],
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        # Anthropic's response content is a list of blocks (text/tool_use/
        # etc.) — join every text block rather than assuming index 0 is
        # the whole answer, in case a future model returns more than one.
        blocks = resp.json()["content"]
        return "".join(b["text"] for b in blocks if b.get("type") == "text")


def _get_tenant_llm_config(tenant_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute(
            "SELECT provider, model, api_key FROM tenant_llm_config WHERE tenant_id = %s",
            (tenant_id,),
        )
        return cur.fetchone()


def get_provider(tenant_id: int) -> ChatProvider:
    """Resolves the tenant's configured provider, or falls back to the
    global DeepSeek default if the tenant has no tenant_llm_config row —
    same fallback contract as branding/theme (explicit override, sane
    default otherwise, never inferred)."""
    config = _get_tenant_llm_config(tenant_id)

    if config is None:
        return DeepSeekProvider(api_key=settings.llm_api_key, model=settings.llm_chat_model)

    provider = config["provider"]
    model = config["model"]
    # A tenant-configured api_key overrides the global one for that
    # provider; a NULL/empty tenant api_key falls back to the matching
    # global credential rather than failing outright.
    tenant_api_key = config["api_key"] or None

    if provider == "deepseek":
        return DeepSeekProvider(api_key=tenant_api_key or settings.llm_api_key, model=model)
    if provider == "openai":
        return OpenAIProvider(api_key=tenant_api_key or settings.openai_api_key, model=model)
    if provider == "anthropic":
        return AnthropicProvider(api_key=tenant_api_key or settings.anthropic_api_key, model=model)

    raise ValueError(f"Unknown provider '{provider}' in tenant_llm_config")
