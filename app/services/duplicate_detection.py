"""Duplicate/conflict detection (Phase 3 WBS 3.0).

Deliberately simple, per the owner's kickoff decision (see
docs/Phase III WBS.md): flags near-duplicate document TITLES and
near-duplicate CHUNK HEADINGS across *different* documents within a
tenant, using the stdlib's difflib.SequenceMatcher on normalized text
— no embeddings, no new dependency, and NOT semantic/meaning-based
conflict detection. A pair scoring above the threshold gets a
duplicate_flag row for a human to review; nothing is ever deleted,
merged, or otherwise acted on automatically.

O(n^2) pairwise comparison within a tenant's titles and, separately,
within a tenant's headings — fine at the scale this feature is scoped
for (a single tenant's knowledge base), not designed to scale to tens
of thousands of documents. If that ever becomes a real constraint,
the fix is a smarter candidate-pruning step before the pairwise
comparison, not a rewrite of this module's approach.
"""
import re
from difflib import SequenceMatcher

from app.db.pool import get_conn, get_cursor

# Verified against a spread of realistic title pairs while building
# this (not invented — computed, see docs/STATUS.md's round entry for
# the exact numbers): at 0.80, this catches near-identical text —
# typos, punctuation, singular/plural ("Refund Policy" vs "Refunds
# Policy": 0.96; "Cancellation Policy" vs "Cancelation Policy": 0.97;
# "Getting Started Guide" vs "Getting Started": 0.83) — while
# correctly NOT flagging genuinely different topics ("Shipping Policy"
# vs "Return Policy": 0.57).
#
# Real, honest limitation: this is character-sequence similarity, not
# semantic similarity, so it will MISS reworded or synonym-based
# duplicates that a human would recognize instantly — "Contact
# Support" vs "Contact Us" scores only 0.72, "API Rate Limits" vs
# "Rate Limiting for APIs" only 0.60, both below this threshold. This
# is the direct, accepted cost of the owner's "keep it simple, no
# embeddings" kickoff decision, not an oversight — see
# docs/Phase III WBS.md's 3.2 for the explicit tradeoff. A future
# upgrade to embedding-based comparison (the module docstring above
# notes this is a service-level change, not a schema change) would
# close this specific gap.
DEFAULT_SIMILARITY_THRESHOLD = 0.80

_PUNCT_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = _PUNCT_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _fetch_titles(tenant_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT id AS document_id, title AS label FROM document WHERE tenant_id = %s",
            (tenant_id,),
        )
        return cur.fetchall()


def _fetch_headings(tenant_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT DISTINCT dc.document_id, dc.heading_path AS label
               FROM document_chunk dc
               WHERE dc.tenant_id = %s AND dc.heading_path IS NOT NULL AND dc.heading_path != ''""",
            (tenant_id,),
        )
        return cur.fetchall()


def _flag_exists(tenant_id: int, doc_id_a: int, doc_id_b: int, source: str, label_a: str, label_b: str) -> bool:
    """Checks for ANY existing flag for this exact pair+source+labels
    — resolved or not. A resolved flag must still count here, or a
    later scan would silently recreate the exact pair an admin already
    dismissed, contradicting the whole point of `resolved_at`. If the
    underlying text actually changes (a title gets edited), that's a
    different label_a/label_b and will correctly be treated as a new,
    unseen pair."""
    with get_cursor() as cur:
        cur.execute(
            """SELECT id FROM duplicate_flag
               WHERE tenant_id = %s AND document_id_a = %s AND document_id_b = %s
                 AND source = %s AND label_a = %s AND label_b = %s""",
            (tenant_id, doc_id_a, doc_id_b, source, label_a, label_b),
        )
        return cur.fetchone() is not None


def _insert_flag(tenant_id: int, doc_id_a: int, doc_id_b: int, source: str, label_a: str, label_b: str, score: float) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO duplicate_flag
               (tenant_id, document_id_a, document_id_b, source, label_a, label_b, similarity)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (tenant_id, doc_id_a, doc_id_b, source, label_a, label_b, score),
        )
        flag_id = cur.lastrowid
        cur.close()
    return flag_id


def _scan_pairs(tenant_id: int, items: list[dict], source: str, threshold: float) -> list[dict]:
    created = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a["document_id"] == b["document_id"]:
                continue  # two headings in the SAME document aren't a cross-document conflict
            score = _similarity(a["label"], b["label"])
            if score < threshold:
                continue

            doc_id_a, doc_id_b = sorted((a["document_id"], b["document_id"]))
            label_a, label_b = (a["label"], b["label"]) if a["document_id"] == doc_id_a else (b["label"], a["label"])

            if _flag_exists(tenant_id, doc_id_a, doc_id_b, source, label_a, label_b):
                continue

            flag_id = _insert_flag(tenant_id, doc_id_a, doc_id_b, source, label_a, label_b, score)
            created.append(
                {
                    "id": flag_id, "document_id_a": doc_id_a, "document_id_b": doc_id_b,
                    "source": source, "label_a": label_a, "label_b": label_b, "similarity": score,
                }
            )
    return created


def scan_for_duplicates(tenant_id: int, threshold: float = DEFAULT_SIMILARITY_THRESHOLD) -> list[dict]:
    """Runs a fresh scan for this tenant across both titles and
    headings. Returns only the flags newly created by this run —
    already-flagged (and still-unresolved) pairs aren't duplicated,
    and previously-resolved pairs aren't recreated."""
    titles = _fetch_titles(tenant_id)
    headings = _fetch_headings(tenant_id)

    created = []
    created += _scan_pairs(tenant_id, titles, "title", threshold)
    created += _scan_pairs(tenant_id, headings, "heading", threshold)
    return created
