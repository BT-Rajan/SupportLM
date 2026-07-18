"""Tests for Phase 4 — 1.0 Hybrid Search: keyword_search() tenant
isolation, and hybrid_search()'s score-fusion behavior at the weight
extremes and in between. Requires a reachable, migrated DB (015 applied)
— skips cleanly if one isn't configured, same pattern as
test_query_isolation.py.
"""
import json

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


def _reset_tenant_content(tenant_id: int) -> None:
    """Deletes any documents (cascading to document_chunk/embedding) left
    over from a prior run against this tenant. Without this, rerunning
    the suite against the same DB accumulates chunks across runs and
    breaks tests that assume an exact, small candidate pool — the same
    non-idempotency pitfall Round 9 hit with the category-isolation
    test."""
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM document WHERE tenant_id = %s", (tenant_id,))
        cur.close()


def _seed_chunk(tenant_id: int, content: str, vector: list[float], heading: str = "Section") -> int:
    from app.db.pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO document (tenant_id, title, filename, raw_markdown, status, review_state) "
            "VALUES (%s, 'Doc', 'd.md', '# x', 'ready', 'published')",
            (tenant_id,),
        )
        doc_id = cur.lastrowid
        cur.execute(
            "INSERT INTO document_chunk (tenant_id, document_id, chunk_index, heading_path, "
            "content, token_count) VALUES (%s, %s, 0, %s, %s, 10)",
            (tenant_id, doc_id, heading, content),
        )
        chunk_id = cur.lastrowid
        cur.execute(
            "INSERT INTO embedding (tenant_id, chunk_id, model, dims, embedding_vector) "
            "VALUES (%s, %s, 'test', 3, %s)",
            (tenant_id, chunk_id, json.dumps(vector)),
        )
        cur.close()
    return chunk_id


def test_keyword_search_only_returns_own_tenant_chunks():
    """Same isolation rule as vector search (WBS 3.2) applies to the new
    FULLTEXT keyword path — a keyword search is just as capable of
    leaking cross-tenant content as the semantic one if unscoped."""
    from app.services.vector_store import keyword_search

    tenant_a = _ensure_tenant("pytest-hybrid-a")
    tenant_b = _ensure_tenant("pytest-hybrid-b")
    _reset_tenant_content(tenant_a)
    _reset_tenant_content(tenant_b)

    _seed_chunk(tenant_a, "pytest unique billing keyword tenant A content", [1.0, 0.0, 0.0])
    _seed_chunk(tenant_b, "pytest unique billing keyword tenant B content", [1.0, 0.0, 0.0])

    results_a = keyword_search(tenant_a, "billing keyword", top_k=5)
    results_b = keyword_search(tenant_b, "billing keyword", top_k=5)

    assert results_a and all("tenant A" in r.content for r in results_a)
    assert results_b and all("tenant B" in r.content for r in results_b)


def test_keyword_search_no_match_returns_empty():
    from app.services.vector_store import keyword_search

    tenant_id = _ensure_tenant("pytest-hybrid-nomatch")
    _reset_tenant_content(tenant_id)
    _seed_chunk(tenant_id, "pytest completely unrelated shipping content here", [0.5, 0.5, 0.0])

    results = keyword_search(tenant_id, "xyzxyz_no_such_term_zzz", top_k=5)
    assert results == []


def test_hybrid_search_pure_semantic_at_weight_zero():
    """keyword_weight=0 should reproduce plain semantic ranking: the
    chunk whose embedding is closest to the query vector wins, even if
    a keyword-irrelevant chunk scores higher on FULLTEXT."""
    from app.services.vector_store import hybrid_search

    tenant_id = _ensure_tenant("pytest-hybrid-semantic")
    _reset_tenant_content(tenant_id)
    close_id = _seed_chunk(tenant_id, "pytest irrelevant keywords zzqq", [1.0, 0.0, 0.0])
    far_id = _seed_chunk(tenant_id, "pytest reset password billing portal", [0.0, 1.0, 0.0])

    results = hybrid_search(
        tenant_id, "reset password billing portal", [1.0, 0.0, 0.0], top_k=1, keyword_weight=0.0
    )

    assert len(results) == 1
    assert results[0].chunk_id == close_id
    assert results[0].chunk_id != far_id


def test_hybrid_search_pure_keyword_at_weight_one():
    """keyword_weight=1 should reproduce plain keyword ranking: the
    FULLTEXT-relevant chunk wins even if its embedding is far from the
    query vector."""
    from app.services.vector_store import hybrid_search

    tenant_id = _ensure_tenant("pytest-hybrid-keyword")
    _reset_tenant_content(tenant_id)
    semantic_close_id = _seed_chunk(tenant_id, "pytest zzqq unrelated words here", [1.0, 0.0, 0.0])
    keyword_relevant_id = _seed_chunk(tenant_id, "pytest reset password billing portal", [0.0, 1.0, 0.0])

    results = hybrid_search(
        tenant_id, "reset password billing portal", [1.0, 0.0, 0.0], top_k=1, keyword_weight=1.0
    )

    assert len(results) == 1
    assert results[0].chunk_id == keyword_relevant_id
    assert results[0].chunk_id != semantic_close_id


def test_hybrid_search_blend_surfaces_chunk_strong_on_both_signals():
    """A chunk that's decently close on both signals should outrank one
    that's only excellent on a single signal, at a mid-range weight.

    Needs a third, weak-on-both distractor chunk to widen the pool: with
    only two candidates, min-max normalization forces the *worse* of the
    two semantic scores all the way to 0 regardless of how close it
    actually was, coincidentally tying it with an unmatched keyword
    score of 0 — an artifact of a 2-point pool, not of the blend logic
    itself. A third point makes the normalization meaningful."""
    from app.services.vector_store import hybrid_search

    tenant_id = _ensure_tenant("pytest-hybrid-blend")
    _reset_tenant_content(tenant_id)
    # Strongest possible semantic match, zero keyword relevance.
    semantic_only_id = _seed_chunk(
        tenant_id, "pytest totally unrelated words zzqq foobar", [1.0, 0.0, 0.0]
    )
    # Decent on both: reasonably close vector AND keyword-relevant text.
    balanced_id = _seed_chunk(
        tenant_id, "pytest reset password billing portal instructions", [0.9, 0.1, 0.0]
    )
    # Weak on both — widens the normalization pool without competing
    # for the top spot.
    _seed_chunk(tenant_id, "pytest filler unrelated distractor content", [0.0, 0.0, 1.0])

    results = hybrid_search(
        tenant_id,
        "reset password billing portal",
        [1.0, 0.0, 0.0],
        top_k=2,
        keyword_weight=0.5,
    )

    result_ids = [r.chunk_id for r in results]
    assert balanced_id in result_ids
    assert semantic_only_id in result_ids
    # At an even 0.5 blend, the balanced chunk (strong on both) should
    # rank above the chunk that's only strong on one signal.
    assert result_ids.index(balanced_id) < result_ids.index(semantic_only_id)


def test_hybrid_search_tenant_isolation():
    """The fused result set must never cross tenants on either signal."""
    from app.services.vector_store import hybrid_search

    tenant_a = _ensure_tenant("pytest-hybrid-iso-a")
    tenant_b = _ensure_tenant("pytest-hybrid-iso-b")
    _reset_tenant_content(tenant_a)
    _reset_tenant_content(tenant_b)

    _seed_chunk(tenant_a, "pytest shared query terms tenant A secret", [1.0, 0.0, 0.0])
    _seed_chunk(tenant_b, "pytest shared query terms tenant B secret", [1.0, 0.0, 0.0])

    results_a = hybrid_search(tenant_a, "shared query terms", [1.0, 0.0, 0.0], top_k=5)
    results_b = hybrid_search(tenant_b, "shared query terms", [1.0, 0.0, 0.0], top_k=5)

    assert all("tenant A" in r.content for r in results_a)
    assert all("tenant B" in r.content for r in results_b)


def test_keyword_search_excludes_unpublished_documents():
    """Reconciliation test (Phase 3 x Phase 4): keyword_search() was
    originally built with only the WBS 3.2 tenant/status isolation
    check, before Phase 3's review_state workflow existed in this
    session's context. Merging the two surfaced a real gap — the
    semantic path (MySQLVectorStore.search()) was gated on
    review_state='published', the keyword path wasn't, so
    hybrid_search()'s keyword contribution could still resurface a
    draft the semantic contribution correctly excluded. This is the
    regression test for that fix — mirrors
    test_review_workflow.py::test_retrieval_excludes_unpublished_documents
    but for the FULLTEXT path instead of the cosine one."""
    from app.db.pool import get_conn
    from app.services.vector_store import keyword_search

    tenant_id = _ensure_tenant("pytest-hybrid-review-state")
    _reset_tenant_content(tenant_id)

    def _seed_with_review_state(review_state: str) -> int:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO document (tenant_id, title, filename, raw_markdown, status, review_state) "
                "VALUES (%s, 'Doc', 'd.md', '# x', 'ready', %s)",
                (tenant_id, review_state),
            )
            doc_id = cur.lastrowid
            cur.execute(
                "INSERT INTO document_chunk (tenant_id, document_id, chunk_index, heading_path, content, token_count) "
                "VALUES (%s, %s, 0, 'Section', %s, 10)",
                (tenant_id, doc_id, "pytest unique widgetfrobnicator keyword content"),
            )
            cur.close()
        return doc_id

    _seed_with_review_state("draft")
    _seed_with_review_state("review")
    published_id = _seed_with_review_state("published")

    results = keyword_search(tenant_id, "widgetfrobnicator keyword", top_k=10)
    assert {r.document_id for r in results} == {published_id}
