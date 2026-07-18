"""VectorStore isolates *how* similarity search is done from the callers
(chat service, search endpoint). Phase 1 implementation does brute-force
cosine similarity over embeddings stored as JSON in MySQL — fine at the
scale of a few thousand chunks. To move to pgvector/Qdrant/etc. later,
implement the same interface and swap it in app/services/chat.py.
"""
import json
import math
from dataclasses import dataclass
from typing import Protocol

from app.db.pool import get_cursor


@dataclass
class SearchResult:
    chunk_id: int
    document_id: int
    content: str
    heading_path: str | None
    similarity: float


@dataclass
class HybridSearchResult:
    """Phase 9 — 1.2: wraps hybrid_search()'s fused/ranked results with
    the raw (pre-normalization) top semantic similarity, so callers can
    gate on absolute confidence — `_min_max_normalize` always rescales
    the pool's best result toward 1.0, which makes "closest available
    match" indistinguishable from "actually relevant match" once fused.
    `best_semantic_similarity` is the one number in this whole pipeline
    that isn't relative to the rest of the pool."""

    results: list[SearchResult]
    best_semantic_similarity: float


class VectorStore(Protocol):
    def search(self, tenant_id: int, query_vector: list[float], top_k: int = 5) -> list[SearchResult]: ...


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class MySQLVectorStore:
    """Brute-force cosine similarity, computed in Python over rows pulled
    from MySQL. Only reads chunks belonging to `tenant_id`'s 'ready'
    AND 'published' documents — WBS 3.2 (Phase 2) added the 'ready'
    half of this (tenant isolation); WBS 1.2 (Phase 3) adds the
    'published' half. Both checks are independent and both must pass:
    `status = 'ready'` means ingestion succeeded, `review_state =
    'published'` means it's editorially approved to be customer-facing
    — a document can be one without the other (freshly-ingested but
    still a draft; or previously published, now mid-reindex and
    temporarily 'processing'), and either failing is enough to exclude
    it from what a visitor's question can be answered from."""

    def search(self, tenant_id: int, query_vector: list[float], top_k: int = 5) -> list[SearchResult]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT e.chunk_id, dc.document_id, dc.content, dc.heading_path, e.embedding_vector
                FROM embedding e
                JOIN document_chunk dc ON dc.id = e.chunk_id
                JOIN document d ON d.id = dc.document_id
                WHERE e.tenant_id = %s AND d.status = 'ready' AND d.review_state = 'published'
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()

        scored: list[SearchResult] = []
        for row in rows:
            vec = json.loads(row["embedding_vector"])
            sim = _cosine_similarity(query_vector, vec)
            scored.append(
                SearchResult(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    content=row["content"],
                    heading_path=row["heading_path"],
                    similarity=sim,
                )
            )

        scored.sort(key=lambda r: r.similarity, reverse=True)
        return scored[:top_k]


# Module-level instance so hybrid_search() (and any other future
# caller in this file) doesn't need chat.py's own `_store` — that one
# stays private to chat.py, this one is this module's own.
_semantic_store = MySQLVectorStore()


def keyword_search(tenant_id: int, query: str, top_k: int = 5) -> list[SearchResult]:
    """MySQL FULLTEXT natural-language search over document_chunk.content.

    Phase 4 — 1.2. Same tenant/status/review-state scoping as
    MySQLVectorStore.search() — a keyword search is just as capable of
    leaking cross-tenant or unpublished-draft content as a vector one
    if left unscoped (WBS 3.2 (Phase 2) for the tenant/status half,
    WBS 1.2 (Phase 3) for the review_state half — this function was
    originally built without the review_state half, since it landed
    before Phase 3's review workflow was reconciled into this file;
    fixed here so hybrid_search()'s keyword contribution can't
    resurface a draft that the semantic contribution already excludes).
    Returns SearchResult with `similarity` holding the raw MySQL
    MATCH() relevance score (NOT comparable to cosine similarity —
    1.3's hybrid_search() normalizes both independently before blending).
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT dc.id AS chunk_id, dc.document_id, dc.content, dc.heading_path,
                   MATCH(dc.content) AGAINST (%s IN NATURAL LANGUAGE MODE) AS relevance
            FROM document_chunk dc
            JOIN document d ON d.id = dc.document_id
            WHERE dc.tenant_id = %s AND d.status = 'ready' AND d.review_state = 'published'
              AND MATCH(dc.content) AGAINST (%s IN NATURAL LANGUAGE MODE) > 0
            ORDER BY relevance DESC
            LIMIT %s
            """,
            (query, tenant_id, query, top_k),
        )
        rows = cur.fetchall()

    return [
        SearchResult(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            content=row["content"],
            heading_path=row["heading_path"],
            similarity=float(row["relevance"]),
        )
        for row in rows
    ]


def _min_max_normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        # All equal (including the single-value and all-zero cases) —
        # every candidate is equally relevant on this signal, so give
        # each a neutral, non-zero score rather than dividing by zero.
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def hybrid_search(
    tenant_id: int,
    query: str,
    query_vector: list[float],
    top_k: int = 5,
    keyword_weight: float = 0.3,
    semantic_pool: int = 20,
    keyword_pool: int = 20,
) -> HybridSearchResult:
    """Phase 4 — 1.3: fuse semantic (cosine) and keyword (FULLTEXT)
    search via a weighted blend of independently min-max-normalized
    scores. NOT reciprocal rank fusion — the owner explicitly chose a
    score blend at Phase 4 kickoff (docs/Phase IV WBS.md).

    Each side is pulled with its own wider pool (`semantic_pool`/
    `keyword_pool`, default 20) before normalizing and blending, so a
    chunk that ranks outside the final top_k on one signal alone but
    strong on the other still has a chance to surface — normalizing
    only the top_k from each side would silently exclude anything not
    already in both narrow slices.

    `keyword_weight` in [0, 1]: 0 disables keyword's contribution
    (pure semantic), 1 disables semantic's contribution (pure keyword)
    — useful for isolating each signal in tests.

    Phase 9 — 1.2: returns a HybridSearchResult, not a bare list —
    callers that need to gate on absolute confidence (chat.py) read
    `.best_semantic_similarity`; callers that just want ranked chunks
    (anything else) read `.results`.
    """
    semantic_results = _semantic_store.search(tenant_id, query_vector, top_k=semantic_pool)
    keyword_results = keyword_search(tenant_id, query, top_k=keyword_pool)
    best_semantic_similarity = semantic_results[0].similarity if semantic_results else 0.0

    semantic_scores = _min_max_normalize([r.similarity for r in semantic_results])
    keyword_scores = _min_max_normalize([r.similarity for r in keyword_results])

    by_chunk: dict[int, SearchResult] = {}
    semantic_norm: dict[int, float] = {}
    keyword_norm: dict[int, float] = {}

    for r, s in zip(semantic_results, semantic_scores):
        by_chunk[r.chunk_id] = r
        semantic_norm[r.chunk_id] = s
    for r, s in zip(keyword_results, keyword_scores):
        by_chunk.setdefault(r.chunk_id, r)
        keyword_norm[r.chunk_id] = s

    fused: list[tuple[float, SearchResult]] = []
    for chunk_id, result in by_chunk.items():
        sem = semantic_norm.get(chunk_id, 0.0)
        kw = keyword_norm.get(chunk_id, 0.0)
        final_score = (1 - keyword_weight) * sem + keyword_weight * kw
        fused.append((final_score, result))

    fused.sort(key=lambda pair: pair[0], reverse=True)
    return HybridSearchResult(
        results=[result for _, result in fused[:top_k]],
        best_semantic_similarity=best_semantic_similarity,
    )
