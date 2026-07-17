"""Pluggable chat-completion providers (Phase 4 — 2.0, extended in
Phase 5 — 1.3 for multi-turn history).

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

`history` (Phase 5 — 1.3): an ordered list of
`{"role": "user"|"assistant", "content": str}` dicts — every prior turn
of the conversation, oldest first. DeepSeek/OpenAI splice it into the
`messages` array between the system message and the new user message;
Anthropic does the same into its own `messages` array, with `system`
staying a top-level field exactly as it already was.

`chat_completion()` return shape (Phase 7 — 0.1): a dict, `{"content":
str, "input_tokens": int, "output_tokens": int}` — used to arrive as a
bare string. Every provider's real response already includes a usage
block that was being silently discarded; Phase 7's cost tracking needs
real per-request token counts, not an estimate reconstructed from text
length after the fact.
"""
import httpx

from app.core.config import settings
from app.db.pool import get_cursor


class ChatProvider:
    def chat_completion(self, system_prompt: str, history: list[dict], user_message: str) -> dict:
        raise NotImplementedError


class DeepSeekProvider(ChatProvider):
    _URL = "https://api.deepseek.com/chat/completions"
    PROVIDER_NAME = "deepseek"

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model
        self.model = model  # public alias — Phase 7 0.4 needs this for the usage-log write

    def chat_completion(self, system_prompt: str, history: list[dict], user_message: str) -> dict:
        resp = httpx.post(
            self._URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    *history,
                    {"role": "user", "content": user_message},
                ],
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        body = resp.json()
        usage = body.get("usage", {})
        return {
            "content": body["choices"][0]["message"]["content"],
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }


class OpenAIProvider(ChatProvider):
    _URL = "https://api.openai.com/v1/chat/completions"
    PROVIDER_NAME = "openai"

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model
        self.model = model

    def chat_completion(self, system_prompt: str, history: list[dict], user_message: str) -> dict:
        resp = httpx.post(
            self._URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    *history,
                    {"role": "user", "content": user_message},
                ],
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        body = resp.json()
        usage = body.get("usage", {})
        return {
            "content": body["choices"][0]["message"]["content"],
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }


class AnthropicProvider(ChatProvider):
    _URL = "https://api.anthropic.com/v1/messages"
    _ANTHROPIC_VERSION = "2023-06-01"
    PROVIDER_NAME = "anthropic"

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model
        self.model = model

    def chat_completion(self, system_prompt: str, history: list[dict], user_message: str) -> dict:
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
                "messages": [*history, {"role": "user", "content": user_message}],
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        body = resp.json()
        # Anthropic's response content is a list of blocks (text/tool_use/
        # etc.) — join every text block rather than assuming index 0 is
        # the whole answer, in case a future model returns more than one.
        blocks = body["content"]
        content = "".join(b["text"] for b in blocks if b.get("type") == "text")
        usage = body.get("usage", {})
        return {
            "content": content,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }


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
