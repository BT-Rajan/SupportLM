"""WBS 3.3 — the systematic regression net for 3.2, asserting tenant A's
request can never read or write tenant B's documents/conversations/
citations.

This file does NOT re-implement what test_query_isolation.py and
test_tenant_resolution.py already cover well — duplicating those would
just be more tests to maintain with no more protection. Coverage map
across the 8 tenant-scoped tables (see docs/schema/1.1-tenant-schema-
proposal.md):

  document        -> test_query_isolation.py (list/reindex/delete blocked)
  document_chunk  -> test_query_isolation.py (vector search isolation)
  embedding       -> test_query_isolation.py (vector search isolation)
  category        -> test_query_isolation.py (list/create/delete blocked)
  conversation    -> test_query_isolation.py (hijack guard)
  message         -> test_query_isolation.py (hijack guard, zero leak)
  citation        -> NOT covered elsewhere -> tested here
  agent           -> no query surface exists yet (no route reads/writes
                      it beyond the tenant_id column added in 1.2/1.3);
                      nothing to test at the application layer until
                      4.1 wires branding to it. Structurally it already
                      has the same NOT NULL FK + cascade as every other
                      table, which the cascade test below covers.
  tenant_branding -> added in 4.1, after this file was first written;
                      included in the cascade test below. No cross-
                      tenant read/write surface exists for it yet (no
                      route reads another tenant's branding by id —
                      resolve_theme() only ever queries by the already-
                      resolved tenant_id), so there's nothing else to
                      add here until that changes.

What's added here, specifically to close gaps:
  1. Citation referential integrity: every citation a tenant's
     conversation produces must reference a chunk that ALSO belongs to
     that tenant — not just "search didn't return the wrong chunk"
     (already tested) but "even if something upstream changed, the
     citation itself can't silently point cross-tenant."
  2. Schema-level cascade regression: formalizes what was checked by
     hand back in round 1 (1.1) into an actual pytest test, so if a FK
     or its ON DELETE CASCADE is ever weakened, this fails loudly
     instead of only being caught by memory of a manual check months
     ago.
"""
from unittest.mock import patch

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


def _ensure_tenant(slug: str, status: str = "active") -> int:
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM tenant WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if row:
            tenant_id = row["id"]
        else:
            cur.execute(
                "INSERT INTO tenant (name, slug, status) VALUES (%s, %s, %s)", (slug, slug, status)
            )
            tenant_id = cur.lastrowid
        cur.close()
    return tenant_id


def test_citations_never_reference_another_tenants_chunk():
    """Two tenants each get a real chunk indexed and ask a question.
    Every citation row produced must reference a chunk that belongs to
    the SAME tenant as the citation itself — checked via an explicit
    join, not inferred from search behavior."""
    import json

    from app.db.pool import get_conn
    from app.services.chat import ask

    tenant_a = _ensure_tenant("pytest-citation-a")
    tenant_b = _ensure_tenant("pytest-citation-b")

    with get_conn() as conn:
        cur = conn.cursor()
        for tenant_id, label in [(tenant_a, "A"), (tenant_b, "B")]:
            cur.execute(
                "INSERT INTO document (tenant_id, title, filename, raw_markdown, status) "
                "VALUES (%s, %s, %s, %s, 'ready')",
                (tenant_id, f"Doc {label}", f"citation-{label.lower()}.md", "# x"),
            )
            doc_id = cur.lastrowid
            cur.execute(
                "INSERT INTO document_chunk (tenant_id, document_id, chunk_index, heading_path, "
                "content, token_count) VALUES (%s, %s, 0, %s, %s, 10)",
                (tenant_id, doc_id, f"Section {label}", f"citation test content {label}"),
            )
            chunk_id = cur.lastrowid
            cur.execute(
                "INSERT INTO embedding (tenant_id, chunk_id, model, dims, embedding_vector) "
                "VALUES (%s, %s, 'test', 3, %s)",
                (tenant_id, chunk_id, json.dumps([1.0, 0.0, 0.0])),
            )
        cur.close()

    with patch("app.services.chat.embed_text", return_value=[1.0, 0.0, 0.0]), patch(
        "app.services.chat.chat_completion", return_value="mocked"
    ):
        ask(tenant_a, "question for A", None)
        ask(tenant_b, "question for B", None)

    with get_conn() as conn:
        cur = conn.cursor()
        # The actual regression assertion: for every citation in the
        # system, its own tenant_id must match the tenant_id of the
        # chunk it cites. A mismatch here means a citation is pointing
        # at another tenant's content.
        cur.execute(
            """
            SELECT c.id, c.tenant_id AS citation_tenant, dc.tenant_id AS chunk_tenant
            FROM citation c
            JOIN document_chunk dc ON dc.id = c.chunk_id
            WHERE c.tenant_id IN (%s, %s)
            """,
            (tenant_a, tenant_b),
        )
        rows = cur.fetchall()
        cur.close()

    assert rows, "expected at least one citation to have been created"
    for row in rows:
        assert row["citation_tenant"] == row["chunk_tenant"], (
            f"citation {row['id']} belongs to tenant {row['citation_tenant']} but cites a chunk "
            f"belonging to tenant {row['chunk_tenant']}"
        )


def test_deleting_a_tenant_cascades_to_every_tenant_scoped_table():
    """Formalizes the manual cascade check from round 1 (1.1) as a real
    regression test: if any table's tenant FK or ON DELETE CASCADE is
    ever weakened, this fails instead of silently leaving orphaned rows
    that could later be misattributed to a reused tenant_id."""
    import json

    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO tenant (name, slug, status) VALUES ('Cascade Test', 'pytest-cascade-test', 'active')")
        tenant_id = cur.lastrowid

        cur.execute(
            "INSERT INTO category (tenant_id, name, slug) VALUES (%s, 'Cat', 'cat')", (tenant_id,)
        )
        category_id = cur.lastrowid
        cur.execute(
            "INSERT INTO document (tenant_id, category_id, title, filename, raw_markdown, status) "
            "VALUES (%s, %s, 'Doc', 'doc.md', '# x', 'ready')",
            (tenant_id, category_id),
        )
        document_id = cur.lastrowid
        cur.execute(
            "INSERT INTO document_chunk (tenant_id, document_id, chunk_index, heading_path, content, token_count) "
            "VALUES (%s, %s, 0, 'S', 'content', 5)",
            (tenant_id, document_id),
        )
        chunk_id = cur.lastrowid
        cur.execute(
            "INSERT INTO embedding (tenant_id, chunk_id, model, dims, embedding_vector) "
            "VALUES (%s, %s, 'test', 3, %s)",
            (tenant_id, chunk_id, json.dumps([1.0, 0.0, 0.0])),
        )
        cur.execute("INSERT INTO conversation (id, tenant_id) VALUES (UUID(), %s)", (tenant_id,))
        cur.execute("SELECT id FROM conversation WHERE tenant_id = %s LIMIT 1", (tenant_id,))
        conversation_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO message (tenant_id, conversation_id, role, content) VALUES (%s, %s, 'user', 'hi')",
            (tenant_id, conversation_id),
        )
        message_id = cur.lastrowid
        cur.execute(
            "INSERT INTO citation (tenant_id, message_id, chunk_id, rank, similarity) VALUES (%s, %s, %s, 1, 0.9)",
            (tenant_id, message_id, chunk_id),
        )
        cur.execute("INSERT INTO agent (tenant_id, name) VALUES (%s, 'Bot')", (tenant_id,))
        cur.execute(
            "INSERT INTO tenant_branding (tenant_id, display_name, accent_hex) VALUES (%s, 'Cascade Co', '#7c3aed')",
            (tenant_id,),
        )
        cur.close()

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tenant WHERE id = %s", (tenant_id,))
        cur.close()

    with get_conn() as conn:
        cur = conn.cursor()
        for table in (
            "category", "document", "document_chunk", "embedding",
            "conversation", "message", "citation", "agent", "tenant_branding",
        ):
            cur.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE tenant_id = %s", (tenant_id,))
            remaining = cur.fetchone()["n"]
            assert remaining == 0, f"{table} still has {remaining} row(s) after its tenant was deleted"
        cur.close()
