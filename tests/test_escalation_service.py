"""Tests for Phase 6 — 2.2: generate_sr_number(). Requires a reachable,
migrated DB (020 applied) — skips cleanly if one isn't configured.
"""
import re
from datetime import date

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


def _reset_sequence(tenant_id: int):
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM sr_sequence WHERE tenant_id = %s", (tenant_id,))
        cur.close()


def test_sr_number_format():
    from app.services.escalation import generate_sr_number

    tenant_id = _ensure_tenant("pytest-sr-format")
    _reset_sequence(tenant_id)

    sr = generate_sr_number(tenant_id)
    today_str = date.today().strftime("%Y%m%d")
    assert re.match(rf"^SR-{today_str}-\d{{4}}$", sr)
    assert sr == f"SR-{today_str}-0001"


def test_sr_number_increments_per_tenant_per_day():
    from app.services.escalation import generate_sr_number

    tenant_id = _ensure_tenant("pytest-sr-increment")
    _reset_sequence(tenant_id)

    sr1 = generate_sr_number(tenant_id)
    sr2 = generate_sr_number(tenant_id)
    sr3 = generate_sr_number(tenant_id)

    today_str = date.today().strftime("%Y%m%d")
    assert [sr1, sr2, sr3] == [
        f"SR-{today_str}-0001",
        f"SR-{today_str}-0002",
        f"SR-{today_str}-0003",
    ]


def test_sr_sequence_independent_across_tenants():
    from app.services.escalation import generate_sr_number

    tenant_a = _ensure_tenant("pytest-sr-iso-a")
    tenant_b = _ensure_tenant("pytest-sr-iso-b")
    _reset_sequence(tenant_a)
    _reset_sequence(tenant_b)

    sr_a1 = generate_sr_number(tenant_a)
    sr_b1 = generate_sr_number(tenant_b)
    sr_a2 = generate_sr_number(tenant_a)

    today_str = date.today().strftime("%Y%m%d")
    # Both tenants independently start at 0001 the same day - that's
    # expected (each tenant has its own sr_sequence row), not a bug.
    assert sr_a1 == f"SR-{today_str}-0001"
    assert sr_b1 == f"SR-{today_str}-0001"
    assert sr_a2 == f"SR-{today_str}-0002"


def test_identical_sr_numbers_across_tenants_both_insert_successfully():
    """Two different tenants are EXPECTED to produce the same
    human-readable SR number on the same day (each has its own
    sequence) — same as two companies both having invoice #1001. The
    schema's UNIQUE constraint must be scoped to (tenant_id,
    sr_number), not sr_number alone, or the second tenant's insert
    would be incorrectly rejected."""
    from app.db.pool import get_conn
    from app.services.escalation import generate_sr_number

    tenant_a = _ensure_tenant("pytest-sr-unique-a")
    tenant_b = _ensure_tenant("pytest-sr-unique-b")
    _reset_sequence(tenant_a)
    _reset_sequence(tenant_b)

    sr_a = generate_sr_number(tenant_a)
    sr_b = generate_sr_number(tenant_b)
    # Both starting fresh sequences on the same day — expected to
    # produce the identical human-readable string.
    assert sr_a == sr_b

    with get_conn() as conn:
        cur = conn.cursor()
        # Delete-then-recreate keeps this test idempotent across
        # repeated runs against the same DB (the fixed conversation_id
        # below would otherwise collide on a PK on the second run) —
        # the DELETE cascades to message/service_request too.
        cur.execute(
            "DELETE FROM conversation WHERE id IN (%s, %s)",
            ("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"),
        )
        cur.execute(
            "INSERT INTO conversation (id, tenant_id) VALUES (%s, %s)",
            ("11111111-1111-1111-1111-111111111111", tenant_a),
        )
        cur.execute(
            "INSERT INTO message (tenant_id, conversation_id, role, content) VALUES (%s, %s, 'assistant', 'x')",
            (tenant_a, "11111111-1111-1111-1111-111111111111"),
        )
        message_id_a = cur.lastrowid
        cur.execute(
            """INSERT INTO service_request (tenant_id, sr_number, conversation_id, message_id, visitor_email)
               VALUES (%s, %s, %s, %s, %s)""",
            (tenant_a, sr_a, "11111111-1111-1111-1111-111111111111", message_id_a, "a@example.com"),
        )

        cur.execute(
            "INSERT INTO conversation (id, tenant_id) VALUES (%s, %s)",
            ("22222222-2222-2222-2222-222222222222", tenant_b),
        )
        cur.execute(
            "INSERT INTO message (tenant_id, conversation_id, role, content) VALUES (%s, %s, 'assistant', 'y')",
            (tenant_b, "22222222-2222-2222-2222-222222222222"),
        )
        message_id_b = cur.lastrowid
        # This is the actual assertion: tenant B's identical-looking
        # sr_number must NOT be rejected by a global uniqueness
        # constraint — if the schema had a plain UNIQUE on sr_number
        # alone instead of (tenant_id, sr_number), this insert would
        # raise an IntegrityError here.
        cur.execute(
            """INSERT INTO service_request (tenant_id, sr_number, conversation_id, message_id, visitor_email)
               VALUES (%s, %s, %s, %s, %s)""",
            (tenant_b, sr_b, "22222222-2222-2222-2222-222222222222", message_id_b, "b@example.com"),
        )
        cur.close()
