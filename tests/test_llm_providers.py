"""Tests for Phase 4 — 2.2/2.3: get_provider() resolution logic.
Requires a reachable, migrated DB (016 applied) — skips cleanly if one
isn't configured, same pattern as test_hybrid_search.py.
"""
import pytest

try:
    from app.db.pool import get_conn

    with get_conn() as _conn:
        pass
    _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _DB_AVAILABLE, reason="requires a configured, reachable DB (see .env.example)"
)


def _ensure_tenant(slug: str) -> int:
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM tenant WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if row:
            tenant_id = row["id"]
        else:
            cur.execute(
                "INSERT INTO tenant (name, slug, status) VALUES (%s, %s, 'active')", (slug, slug)
            )
            tenant_id = cur.lastrowid
        cur.close()
    return tenant_id


def _set_config(tenant_id: int, provider: str, model: str, api_key: str | None = None):
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO tenant_llm_config (tenant_id, provider, model, api_key)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE provider = VALUES(provider), model = VALUES(model),
                                       api_key = VALUES(api_key)""",
            (tenant_id, provider, model, api_key),
        )
        cur.close()


def _clear_config(tenant_id: int):
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tenant_llm_config WHERE tenant_id = %s", (tenant_id,))
        cur.close()


def test_no_config_falls_back_to_global_deepseek_default():
    from app.core.config import settings
    from app.core.llm_providers import DeepSeekProvider, get_provider

    tenant_id = _ensure_tenant("pytest-llm-nodefault")
    _clear_config(tenant_id)

    provider = get_provider(tenant_id)
    assert isinstance(provider, DeepSeekProvider)
    assert provider._model == settings.llm_chat_model
    assert provider._api_key == settings.llm_api_key


def test_tenant_config_selects_the_configured_provider_class():
    from app.core.llm_providers import AnthropicProvider, DeepSeekProvider, OpenAIProvider, get_provider

    tenant_id = _ensure_tenant("pytest-llm-select")

    _set_config(tenant_id, "openai", "gpt-4o-mini", api_key="tenant-openai-key")
    assert isinstance(get_provider(tenant_id), OpenAIProvider)

    _set_config(tenant_id, "anthropic", "claude-3-5-sonnet-20241022", api_key="tenant-anthropic-key")
    assert isinstance(get_provider(tenant_id), AnthropicProvider)

    _set_config(tenant_id, "deepseek", "deepseek-chat", api_key="tenant-deepseek-key")
    assert isinstance(get_provider(tenant_id), DeepSeekProvider)


def test_tenant_api_key_overrides_global_default():
    from app.core.llm_providers import get_provider

    tenant_id = _ensure_tenant("pytest-llm-override")
    _set_config(tenant_id, "openai", "gpt-4o-mini", api_key="tenant-specific-key")

    provider = get_provider(tenant_id)
    assert provider._api_key == "tenant-specific-key"
    assert provider._model == "gpt-4o-mini"


def test_null_tenant_api_key_falls_back_to_matching_global_key():
    from app.core.config import settings
    from app.core.llm_providers import get_provider

    tenant_id = _ensure_tenant("pytest-llm-nullkey")
    _set_config(tenant_id, "openai", "gpt-4o-mini", api_key=None)

    provider = get_provider(tenant_id)
    # No tenant-specific key configured — must fall back to the global
    # OpenAI key, NOT the global DeepSeek key/settings.llm_api_key.
    assert provider._api_key == settings.openai_api_key


def test_provider_enum_rejects_invalid_value_at_db_level():
    """Confirms `tenant_llm_config.provider` is a real ENUM at the
    schema level, not just an app-layer convention — an invalid value
    can't be written to the table at all, regardless of what any
    Python code does or doesn't check.

    Renamed from `test_unknown_provider_raises`, which claimed (in its
    own docstring) to test `get_provider()`'s defensive `raise
    ValueError` branch "in principle" without ever actually calling
    `get_provider()` — found via a repo-wide dead-code audit, where the
    unused `get_provider` import was the tell. This test is left as-is
    under its new, accurate name; see
    test_get_provider_raises_on_unknown_provider_value below for a
    test that actually exercises that branch."""
    from app.db.pool import get_conn

    tenant_id = _ensure_tenant("pytest-llm-badprovider")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO tenant_llm_config (tenant_id, provider, model)
               VALUES (%s, 'openai', 'x')
               ON DUPLICATE KEY UPDATE provider = 'openai', model = 'x'""",
            (tenant_id,),
        )
        cur.close()
    # Provider column is a real ENUM at the schema level, so an actually
    # invalid value can't land in the DB at all — confirms the schema
    # constraint is the enforcement point, not just app-layer trust.
    with pytest.raises(Exception):
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE tenant_llm_config SET provider = 'not-a-real-provider' WHERE tenant_id = %s",
                (tenant_id,),
            )
            cur.close()


def test_get_provider_raises_on_unknown_provider_value(monkeypatch):
    """Actually exercises get_provider()'s own `raise ValueError(...)`
    branch — the one the old, misleadingly-named test above claimed to
    cover without ever calling get_provider() at all. Since the DB's
    ENUM constraint means an invalid provider value can never actually
    be read back from a real tenant_llm_config row (confirmed by the
    test above), the only way to reach this branch is to monkeypatch
    the internal DB-lookup boundary and hand get_provider() a
    dict-shaped row it wouldn't normally get to see. If this ENUM is
    ever loosened (a raw VARCHAR, a different DB engine that doesn't
    enforce it, a migration mistake) without a corresponding app-layer
    check, this is the one test that actually verifies get_provider()
    fails loudly instead of silently misrouting to some other
    provider."""
    from app.core import llm_providers

    monkeypatch.setattr(
        llm_providers,
        "_get_tenant_llm_config",
        lambda tenant_id: {"provider": "not-a-real-provider", "model": "x", "api_key": None},
    )

    with pytest.raises(ValueError, match="Unknown provider 'not-a-real-provider'"):
        llm_providers.get_provider(tenant_id=1)
