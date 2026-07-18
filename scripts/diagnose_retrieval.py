"""Diagnoses why chat isn't referring to a tenant's uploaded/synced
content. Runs the exact same retrieval path app/services/chat.py's
ask() uses (embed the question, semantic search, keyword search,
hybrid fusion, confidence-threshold gate) but prints every intermediate
number instead of silently swallowing it into "(no relevant context
found)".

Usage:
  python scripts/diagnose_retrieval.py <tenant_slug> "<question>"

Example:
  python scripts/diagnose_retrieval.py rajan-corp "What does the company do?"
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.llm_client import embed_text  # noqa: E402
from app.core.theme import resolve_theme  # noqa: E402
from app.core.tenant_scope import tenant_id_for_slug  # noqa: E402
from app.db.pool import get_cursor  # noqa: E402
from app.services.vector_store import _semantic_store, keyword_search, hybrid_search  # noqa: E402


def _print_header(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def diagnose(tenant_slug: str, question: str) -> None:
    try:
        tenant_id = tenant_id_for_slug(tenant_slug)
    except Exception as exc:
        print(f"Could not resolve tenant '{tenant_slug}': {exc}")
        return
    print(f"tenant_id for '{tenant_slug}': {tenant_id}")

    # --- 1. Document/chunk/embedding inventory -----------------------
    _print_header("1. Document inventory (status / review_state / chunks / embeddings)")
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.title, d.status, d.review_state,
                   COUNT(DISTINCT dc.id) AS chunk_count,
                   COUNT(DISTINCT e.id) AS embedding_count
            FROM document d
            LEFT JOIN document_chunk dc ON dc.document_id = d.id
            LEFT JOIN embedding e ON e.chunk_id = dc.id
            WHERE d.tenant_id = %s
            GROUP BY d.id, d.title, d.status, d.review_state
            """,
            (tenant_id,),
        )
        docs = cur.fetchall()

    if not docs:
        print("No documents at all for this tenant. Nothing to retrieve from — upload/sync something first.")
        return

    searchable_count = 0
    for d in docs:
        searchable = d["status"] == "ready" and d["review_state"] == "published"
        flag = "OK  (searchable)" if searchable else "SKIP (excluded from search)"
        if searchable:
            searchable_count += 1
        print(
            f"  [{flag}] id={d['id']:<4} '{d['title'][:40]:<40}' "
            f"status={d['status']:<10} review_state={d['review_state']:<10} "
            f"chunks={d['chunk_count']:<4} embeddings={d['embedding_count']}"
        )
        if searchable and d["chunk_count"] == 0:
            print(
                f"    ^ WARNING: published+ready but 0 chunks. Ingestion produced nothing usable — "
                f"check raw_markdown content via GET /t/{tenant_slug}/api/documents/{d['id']}/preview"
            )
        if searchable and d["chunk_count"] != d["embedding_count"]:
            print(f"    ^ WARNING: chunk_count != embedding_count — embedding step partially failed.")

    if searchable_count == 0:
        print("\n  >>> ROOT CAUSE: zero documents are both status='ready' AND review_state='published'.")
        print("  >>> Nothing is eligible for retrieval regardless of what the question is. Publish a document and re-run this script.")
        return

    # --- 2. Confidence threshold in effect ----------------------------
    _print_header("2. Confidence threshold in effect for this tenant")
    theme = resolve_theme(tenant_id)
    threshold = theme["retrieval_confidence_threshold"]
    print(f"  retrieval_confidence_threshold = {threshold}")

    # --- 3. Embed the test question -----------------------------------
    _print_header(f"3. Embedding test question: {question!r}")
    query_vector = embed_text(question)
    print(f"  embedded ok, dims={len(query_vector)}")

    # --- 4. Raw semantic search (unfiltered by threshold) -------------
    _print_header("4. Raw semantic search results (top 5, BEFORE threshold gating)")
    semantic_results = _semantic_store.search(tenant_id, query_vector, top_k=5)
    if not semantic_results:
        print("  No semantic results at all — see section 1, likely 0 searchable chunks.")
    for r in semantic_results:
        preview = r.content[:100].replace("\n", " ")
        print(f"  similarity={r.similarity:.4f}  chunk_id={r.chunk_id}  [{r.heading_path or 'untitled'}]  {preview!r}")

    # --- 5. Keyword search ----------------------------------------------
    _print_header("5. Keyword (FULLTEXT) search results (top 5)")
    kw_results = keyword_search(tenant_id, question, top_k=5)
    if not kw_results:
        print("  No keyword matches (this is normal/fine if the phrasing doesn't share exact words with the content).")
    for r in kw_results:
        preview = r.content[:100].replace("\n", " ")
        print(f"  relevance={r.similarity:.4f}  chunk_id={r.chunk_id}  [{r.heading_path or 'untitled'}]  {preview!r}")

    # --- 6. Hybrid fusion + the actual gate chat.py applies ------------
    _print_header("6. Hybrid search result + threshold gate (what chat.py actually does)")
    fused = hybrid_search(tenant_id, question, query_vector, top_k=5)
    print(f"  best_semantic_similarity = {fused.best_semantic_similarity:.4f}")
    print(f"  confidence_threshold     = {threshold:.4f}")
    passes = fused.best_semantic_similarity >= threshold
    print(f"  has_relevant_context     = {passes}")

    if not passes:
        print(
            f"\n  >>> ROOT CAUSE FOUND: best semantic similarity ({fused.best_semantic_similarity:.4f}) "
            f"is below the confidence threshold ({threshold:.4f})."
        )
        print(
            "  >>> chat.py treats this exactly like an empty knowledge base and tells the LLM there's no "
            "context at all — this is why answers ignore the document even though it's published and chunked."
        )
        print(
            "  >>> Fix: lower retrieval_confidence_threshold for this tenant (POST "
            f"/t/{tenant_slug}/api/agent-config, or the admin console's agent settings). "
            f"Try {max(fused.best_semantic_similarity - 0.1, 0.0):.2f} as a starting point, "
            "given the closest real match scored "
            f"{fused.best_semantic_similarity:.4f}."
        )
    else:
        print("\n  >>> Threshold passes. If chat still isn't using this content, the issue is downstream of "
              "retrieval (prompt construction / provider call) — share this script's full output for further help.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <tenant_slug> \"<question>\"")
        sys.exit(1)
    diagnose(sys.argv[1], sys.argv[2])
