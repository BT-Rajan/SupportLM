"""Tests for WBS 5.1-5.3: plan tiers, usage counting, and limit
enforcement. Requires a reachable, migrated DB (through 007) — skips
cleanly if one isn't configured, matching the rest of the suite.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

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


def _ensure_tenant(slug: str, plan_tier: str = "starter", status: str = "active") -> int:
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM tenant WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if row:
            tenant_id = row["id"]
            cur.execute(
                "UPDATE tenant SET plan_tier = %s, status = %s WHERE id = %s",
                (plan_tier, status, tenant_id),
            )
        else:
            cur.execute(
                "INSERT INTO tenant (name, slug, plan_tier, status) VALUES (%s, %s, %s, %s)",
                (slug, slug, plan_tier, status),
            )
            tenant_id = cur.lastrowid
        cur.close()
    return tenant_id


def _ensure_admin_linked(email: str, password: str, tenant_id: int) -> int:
    from app.core.security import hash_password
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM admin_user WHERE email = %s", (email,))
        row = cur.fetchone()
        if row:
            admin_id = row["id"]
        else:
            cur.execute(
                "INSERT INTO admin_user (email, password_hash, role) VALUES (%s, %s, 'owner')",
                (email, hash_password(password)),
            )
            admin_id = cur.lastrowid
        cur.execute(
            "INSERT IGNORE INTO tenant_user (tenant_id, admin_id, role) VALUES (%s, %s, 'owner')",
            (tenant_id, admin_id),
        )
        cur.close()
    return admin_id


def _clear_documents(tenant_id: int):
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM document WHERE tenant_id = %s", (tenant_id,))
        cur.close()


def test_plan_tiers_seeded_correctly():
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT slug, doc_limit, message_limit, seat_limit FROM plan_tier ORDER BY slug")
        rows = {r["slug"]: r for r in cur.fetchall()}
        cur.close()

    assert rows["starter"]["doc_limit"] == 25
    assert rows["starter"]["message_limit"] == 500
    assert rows["starter"]["seat_limit"] == 2
    assert rows["pro"]["doc_limit"] == 200
    assert rows["pro"]["message_limit"] == 5000
    assert rows["pro"]["seat_limit"] == 10
    assert rows["enterprise"]["doc_limit"] is None
    assert rows["enterprise"]["message_limit"] is None
    assert rows["enterprise"]["seat_limit"] is None


def test_get_tier_limits_reads_joined_tenant_and_plan_tier():
    from app.services.usage import get_tier_limits

    tenant_id = _ensure_tenant("pytest-usage-limits", plan_tier="pro")
    limits = get_tier_limits(tenant_id)
    assert limits["slug"] == "pro"
    assert limits["doc_limit"] == 200
    assert limits["message_limit"] == 5000


def test_document_upload_blocked_once_starter_limit_reached():
    """A starter tenant at 25 documents gets a 403 on the 26th upload;
    a document is NOT inserted as a side effect of the rejected call."""
    from app.db.pool import get_conn

    tenant_id = _ensure_tenant("pytest-doc-limit", plan_tier="starter")
    _ensure_admin_linked("doclimit@pytest.local", "testpass123", tenant_id)
    _clear_documents(tenant_id)

    with get_conn() as conn:
        cur = conn.cursor()
        for i in range(25):
            cur.execute(
                "INSERT INTO document (tenant_id, title, filename, raw_markdown, status) "
                "VALUES (%s, %s, %s, '# x', 'ready')",
                (tenant_id, f"Doc {i}", f"doc-{i}.md"),
            )
        cur.close()

    from app.services.usage import enforce_document_limit

    with pytest.raises(HTTPException) as exc_info:
        enforce_document_limit(tenant_id)
    assert exc_info.value.status_code == 403

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM document WHERE tenant_id = %s", (tenant_id,))
        assert cur.fetchone()["n"] == 25  # unchanged — nothing snuck in
        cur.close()


def test_document_upload_allowed_below_limit():
    from app.services.usage import enforce_document_limit

    tenant_id = _ensure_tenant("pytest-doc-under-limit", plan_tier="starter")
    _clear_documents(tenant_id)
    enforce_document_limit(tenant_id)  # should not raise with 0 documents


def test_enterprise_tenant_never_blocked_on_documents():
    from app.db.pool import get_conn
    from app.services.usage import enforce_document_limit

    tenant_id = _ensure_tenant("pytest-enterprise-docs", plan_tier="enterprise")
    _clear_documents(tenant_id)
    with get_conn() as conn:
        cur = conn.cursor()
        for i in range(30):  # well past what would block a starter/pro tenant
            cur.execute(
                "INSERT INTO document (tenant_id, title, filename, raw_markdown, status) "
                "VALUES (%s, %s, %s, '# x', 'ready')",
                (tenant_id, f"Doc {i}", f"ent-doc-{i}.md"),
            )
        cur.close()
    enforce_document_limit(tenant_id)  # should not raise — unlimited tier


def test_message_limit_warning_is_none_below_limit():
    from app.services.usage import message_limit_warning

    tenant_id = _ensure_tenant("pytest-msg-under-limit", plan_tier="starter")
    assert message_limit_warning(tenant_id) is None


def test_message_limit_warning_fires_at_limit_but_never_blocks():
    """Message limits are a soft warn per the owner's decision — chat
    must remain fully callable even once the limit is reached."""
    from app.db.pool import get_conn
    from app.services.chat import ask
    from app.services.usage import message_limit_warning

    tenant_id = _ensure_tenant("pytest-msg-at-limit", plan_tier="starter")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM message WHERE tenant_id = %s", (tenant_id,))
        cur.execute(
            "INSERT INTO conversation (id, tenant_id) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE last_message_at = NOW()",
            ("11111111-1111-1111-1111-111111111111", tenant_id),
        )
        for _ in range(500):  # starter's message_limit
            cur.execute(
                "INSERT INTO message (tenant_id, conversation_id, role, content) "
                "VALUES (%s, %s, 'user', 'hi')",
                (tenant_id, "11111111-1111-1111-1111-111111111111"),
            )
        cur.close()

    warning = message_limit_warning(tenant_id)
    assert warning is not None
    assert "500" in warning

    with patch("app.services.chat.embed_text", return_value=[0.1, 0.2, 0.3]), patch(
        "app.services.chat.get_provider",
        return_value=type("_P", (), {"chat_completion": staticmethod(lambda *a, **kw: "a real answer")})(),
    ):
        result = ask(tenant_id, "one more question", None)
    assert result["answer"] == "a real answer"  # chat still works past the limit
