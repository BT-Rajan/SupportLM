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
    documents — WBS 3.2: this used to scan every tenant's chunks, which
    meant tenant A's questions could get answered (and cited!) from
    tenant B's knowledge base."""

    def search(self, tenant_id: int, query_vector: list[float], top_k: int = 5) -> list[SearchResult]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT e.chunk_id, dc.document_id, dc.content, dc.heading_path, e.embedding_vector
                FROM embedding e
                JOIN document_chunk dc ON dc.id = e.chunk_id
                JOIN document d ON d.id = dc.document_id
                WHERE e.tenant_id = %s AND d.status = 'ready'
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
