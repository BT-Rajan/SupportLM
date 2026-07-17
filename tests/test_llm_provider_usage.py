"""Tests for Phase 7 — 0.1: ChatProvider.chat_completion() returns
{"content", "input_tokens", "output_tokens"} parsed from each
provider's own real response shape. Mocks httpx.post with realistic
response bodies — no DB needed, these test pure parsing logic.
"""
from unittest.mock import MagicMock, patch


def _mock_response(json_body):
    resp = MagicMock()
    resp.json.return_value = json_body
    resp.raise_for_status.return_value = None
    return resp


def test_deepseek_parses_usage_from_openai_compatible_shape():
    from app.core.llm_providers import DeepSeekProvider

    provider = DeepSeekProvider(api_key="k", model="deepseek-chat")
    body = {
        "choices": [{"message": {"content": "the answer"}}],
        "usage": {"prompt_tokens": 42, "completion_tokens": 17},
    }
    with patch("app.core.llm_providers.httpx.post", return_value=_mock_response(body)):
        result = provider.chat_completion("system", [], "question")

    assert result == {"content": "the answer", "input_tokens": 42, "output_tokens": 17}


def test_openai_parses_usage_from_openai_shape():
    from app.core.llm_providers import OpenAIProvider

    provider = OpenAIProvider(api_key="k", model="gpt-4o-mini")
    body = {
        "choices": [{"message": {"content": "openai answer"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 55},
    }
    with patch("app.core.llm_providers.httpx.post", return_value=_mock_response(body)):
        result = provider.chat_completion("system", [], "question")

    assert result == {"content": "openai answer", "input_tokens": 100, "output_tokens": 55}


def test_anthropic_parses_usage_from_messages_shape():
    from app.core.llm_providers import AnthropicProvider

    provider = AnthropicProvider(api_key="k", model="claude-3-5-sonnet-20241022")
    body = {
        "content": [{"type": "text", "text": "anthropic answer"}],
        "usage": {"input_tokens": 200, "output_tokens": 80},
    }
    with patch("app.core.llm_providers.httpx.post", return_value=_mock_response(body)):
        result = provider.chat_completion("system", [], "question")

    assert result == {"content": "anthropic answer", "input_tokens": 200, "output_tokens": 80}


def test_anthropic_joins_multiple_text_blocks():
    from app.core.llm_providers import AnthropicProvider

    provider = AnthropicProvider(api_key="k", model="claude-3-5-sonnet-20241022")
    body = {
        "content": [
            {"type": "text", "text": "first part. "},
            {"type": "text", "text": "second part."},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    with patch("app.core.llm_providers.httpx.post", return_value=_mock_response(body)):
        result = provider.chat_completion("system", [], "question")

    assert result["content"] == "first part. second part."


def test_missing_usage_block_defaults_to_zero_tokens():
    """A provider response missing the usage block entirely (shouldn't
    happen in practice, but must not crash) degrades to 0 tokens rather
    than raising a KeyError."""
    from app.core.llm_providers import DeepSeekProvider

    provider = DeepSeekProvider(api_key="k", model="deepseek-chat")
    body = {"choices": [{"message": {"content": "an answer with no usage block"}}]}
    with patch("app.core.llm_providers.httpx.post", return_value=_mock_response(body)):
        result = provider.chat_completion("system", [], "question")

    assert result == {"content": "an answer with no usage block", "input_tokens": 0, "output_tokens": 0}
