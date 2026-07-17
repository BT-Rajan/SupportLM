"""Tests for Phase 4 — 3.2: create_version/activate_version/
get_active_prompt. Requires a reachable, migrated DB (017 applied) —
skips cleanly if one isn't configured, same pattern as
test_llm_providers.py.
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


def _reset_prompt_versions(tenant_id: int):
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE tenant SET active_prompt_version_id = NULL WHERE id = %s", (tenant_id,))
        cur.execute("DELETE FROM tenant_prompt_version WHERE tenant_id = %s", (tenant_id,))
        # Must also reset the counter migrations/024_prompt_version_seq.sql
        # added — clearing the version rows alone leaves the counter
        # wherever a prior test run left it, so a rerun against the
        # same tenant slug would start numbering from, e.g., 9 instead
        # of 1, even though nothing is actually broken.
        cur.execute("UPDATE tenant SET next_prompt_version_seq = 0 WHERE id = %s", (tenant_id,))
        cur.close()


def test_get_active_prompt_returns_none_when_unconfigured():
    from app.services.prompt_versions import get_active_prompt

    tenant_id = _ensure_tenant("pytest-prompt-none")
    _reset_prompt_versions(tenant_id)

    assert get_active_prompt(tenant_id) is None


def test_create_version_does_not_auto_activate():
    from app.services.prompt_versions import create_version, get_active_prompt

    tenant_id = _ensure_tenant("pytest-prompt-noauto")
    _reset_prompt_versions(tenant_id)

    create_version(tenant_id, "You are a helpful bot. {context}", admin_id=None)

    # Drafting a version must not make it live on its own.
    assert get_active_prompt(tenant_id) is None


def test_version_numbers_increment_per_tenant():
    from app.services.prompt_versions import create_version

    tenant_id = _ensure_tenant("pytest-prompt-increment")
    _reset_prompt_versions(tenant_id)

    v1 = create_version(tenant_id, "prompt one {context}", admin_id=None)
    v2 = create_version(tenant_id, "prompt two {context}", admin_id=None)
    v3 = create_version(tenant_id, "prompt three {context}", admin_id=None)

    assert [v1["version_number"], v2["version_number"], v3["version_number"]] == [1, 2, 3]


def test_concurrent_create_version_does_not_collide():
    """Regression test for a real race condition: create_version()
    used to read MAX(version_number) with a plain (lock-free) SELECT,
    so two near-simultaneous calls for the same tenant could both
    compute the same next_version and one would fail against
    uq_tenant_version. Fixed with SELECT ... FOR UPDATE. This test
    actually exercises concurrency with real threads and independent
    DB connections — a single-threaded call to create_version() twice
    in a row (see test_version_numbers_increment_per_tenant above)
    can't catch this class of bug, since the two calls are never
    actually concurrent that way."""
    import threading

    from app.services.prompt_versions import create_version

    tenant_id = _ensure_tenant("pytest-prompt-concurrent")
    _reset_prompt_versions(tenant_id)

    n_threads = 8
    results = []
    errors = []
    barrier = threading.Barrier(n_threads)

    def _worker(i):
        try:
            barrier.wait()  # line every thread up so they all start create_version() together
            result = create_version(tenant_id, f"concurrent prompt {i} {{context}}", admin_id=None)
            results.append(result["version_number"])
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"unexpected errors under concurrency: {errors}"
    assert sorted(results) == list(range(1, n_threads + 1)), (
        f"expected version numbers 1..{n_threads} with no duplicates/gaps, got {sorted(results)}"
    )


def test_activate_then_get_active_prompt_returns_that_text():
    from app.services.prompt_versions import activate_version, create_version, get_active_prompt

    tenant_id = _ensure_tenant("pytest-prompt-activate")
    _reset_prompt_versions(tenant_id)

    v1 = create_version(tenant_id, "You are Agent One. {context}", admin_id=None)
    ok = activate_version(tenant_id, v1["id"])

    assert ok is True
    assert get_active_prompt(tenant_id) == "You are Agent One. {context}"


def test_activating_a_new_version_then_rolling_back_restores_old_text():
    """Rollback IS re-activating an older version — no separate revert
    mutation exists, so this exercises that activate_version() is the
    entire rollback mechanism."""
    from app.services.prompt_versions import activate_version, create_version, get_active_prompt

    tenant_id = _ensure_tenant("pytest-prompt-rollback")
    _reset_prompt_versions(tenant_id)

    v1 = create_version(tenant_id, "Original prompt v1. {context}", admin_id=None)
    activate_version(tenant_id, v1["id"])
    assert get_active_prompt(tenant_id) == "Original prompt v1. {context}"

    v2 = create_version(tenant_id, "New prompt v2. {context}", admin_id=None)
    activate_version(tenant_id, v2["id"])
    assert get_active_prompt(tenant_id) == "New prompt v2. {context}"

    # Roll back to v1 by re-activating it.
    activate_version(tenant_id, v1["id"])
    assert get_active_prompt(tenant_id) == "Original prompt v1. {context}"


def test_activate_rejects_a_version_from_another_tenant():
    """Cross-tenant guard: activating another tenant's version_id must
    fail, not silently succeed or leak that version's text."""
    from app.services.prompt_versions import activate_version, create_version, get_active_prompt

    tenant_a = _ensure_tenant("pytest-prompt-cross-a")
    tenant_b = _ensure_tenant("pytest-prompt-cross-b")
    _reset_prompt_versions(tenant_a)
    _reset_prompt_versions(tenant_b)

    v_a = create_version(tenant_a, "Tenant A's secret prompt. {context}", admin_id=None)

    ok = activate_version(tenant_b, v_a["id"])

    assert ok is False
    assert get_active_prompt(tenant_b) is None


def test_ask_uses_tenant_active_prompt_when_configured():
    """Integration: chat.py's ask() must actually call the provider
    with the tenant's configured prompt, not the hardcoded default,
    once one is active."""
    from unittest.mock import patch

    from app.services.chat import ask
    from app.services.prompt_versions import activate_version, create_version

    tenant_id = _ensure_tenant("pytest-prompt-integration")
    _reset_prompt_versions(tenant_id)

    v1 = create_version(tenant_id, "CUSTOM_MARKER_PROMPT for {agent_name}. {context}", admin_id=None)
    activate_version(tenant_id, v1["id"])

    captured = {}

    class _StubProvider:
        PROVIDER_NAME = "stub"
        model = "stub-model"
        def chat_completion(self, system_prompt, history, user_message):
            captured["system_prompt"] = system_prompt
            return {"content": "stubbed answer", "input_tokens": 10, "output_tokens": 10}

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_StubProvider()
    ):
        ask(tenant_id, "does this use my custom prompt?", None)

    assert "CUSTOM_MARKER_PROMPT" in captured["system_prompt"]


def test_ask_falls_back_to_default_prompt_when_unconfigured():
    from unittest.mock import patch

    from app.services.chat import ask

    tenant_id = _ensure_tenant("pytest-prompt-integration-default")
    _reset_prompt_versions(tenant_id)

    captured = {}

    class _StubProvider:
        PROVIDER_NAME = "stub"
        model = "stub-model"
        def chat_completion(self, system_prompt, history, user_message):
            captured["system_prompt"] = system_prompt
            return {"content": "stubbed answer", "input_tokens": 10, "output_tokens": 10}

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider", return_value=_StubProvider()
    ):
        ask(tenant_id, "no custom prompt configured here", None)

    assert "support assistant" in captured["system_prompt"]


def test_ask_survives_a_malformed_custom_prompt_without_500ing():
    """A stray, unescaped brace in a tenant's custom prompt must not
    crash the request — _render_system_prompt() falls back to
    appending context directly."""
    from unittest.mock import patch

    from app.services.chat import ask
    from app.services.prompt_versions import activate_version, create_version

    tenant_id = _ensure_tenant("pytest-prompt-malformed")
    _reset_prompt_versions(tenant_id)

    v1 = create_version(tenant_id, "Broken prompt with a stray brace: { oops", admin_id=None)
    activate_version(tenant_id, v1["id"])

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider",
        return_value=type("_P", (), {"chat_completion": staticmethod(lambda *a, **kw: {"content": "ok", "input_tokens": 10, "output_tokens": 10}), "PROVIDER_NAME": "stub", "model": "stub-model"})(),
    ):
        result = ask(tenant_id, "will this crash?", None)

    assert result["answer"] == "ok"


def test_prompt_version_survives_admin_deletion():
    """`created_by_admin_id` is ON DELETE SET NULL — deleting the admin
    who wrote a version must not delete or invalidate that version.

    Bug note: this test used to be silently merged into the tail of
    test_ask_survives_a_malformed_custom_prompt_without_500ing() above
    — a missing `def test_...():` line meant this docstring and
    everything below it ran as trailing statements inside that OTHER
    test's body instead of as its own test. `pytest --collect-only`
    confirmed it: only 9 tests were ever actually collected from this
    file, not 10. The logic itself was executing (Python doesn't error
    on an orphaned docstring-as-statement), so nothing ever failed
    loudly — this was silent, not broken-and-caught. Found while
    auditing this file for something unrelated (a data-integrity race
    condition in create_version()) and reading through the whole file
    in the process."""
    from app.core.security import hash_password
    from app.db.pool import get_conn
    from app.services.prompt_versions import activate_version, create_version, get_active_prompt

    tenant_id = _ensure_tenant("pytest-prompt-admindel")
    _reset_prompt_versions(tenant_id)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM admin_user WHERE email = %s", ("prompt-admindel@example.com",))
        cur.execute(
            "INSERT INTO admin_user (email, password_hash, role) VALUES (%s, %s, 'admin')",
            ("prompt-admindel@example.com", hash_password("testpass123")),
        )
        admin_id = cur.lastrowid
        cur.close()

    v1 = create_version(tenant_id, "Written by an admin who'll be deleted. {context}", admin_id=admin_id)
    activate_version(tenant_id, v1["id"])

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM admin_user WHERE id = %s", (admin_id,))
        cur.close()

    # The version (and its being active) survives the admin's deletion.
    assert get_active_prompt(tenant_id) == "Written by an admin who'll be deleted. {context}"
