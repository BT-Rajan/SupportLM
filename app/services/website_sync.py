"""Website content sync (Phase 3 WBS 2.2).

Fetches each of a tenant's configured source URLs directly — NOT a
recursive/link-following crawl. "Configured URLs" in the master prompt
reads as a fixed list the tenant provides, not open-ended crawling,
and a recursive crawler is a much bigger, riskier thing to build
without being asked for it explicitly.

HTML-to-text extraction uses the stdlib's `html.parser.HTMLParser`
rather than adding `beautifulsoup4` as a new dependency — this only
needs "strip tags, keep text," not full DOM traversal.

Content is hashed and compared against the source's last known hash.
Unchanged content is a no-op. Changed content is ingested through the
existing `ingest_document()` pipeline from Phase 1, landing at
`review_state = 'draft'` (1.1) like any other new content — synced
pages get the same review gate as everything else, not a bypass. A
source maps to exactly one document (`tenant_sync_source.document_id`,
see migrations/013_website_sync.sql) — re-syncing an unchanged-URL
source updates that same document in place rather than creating a new
one every run, and a content change resets an already-published
document back to 'draft' since live content silently changing without
re-review would defeat the point of 1.0's review workflow.
"""
import hashlib
from html.parser import HTMLParser

import httpx

from app.db.pool import get_conn
from app.services.ingestion import ingest_document

_SKIP_TAGS = {"script", "style", "noscript", "head"}


class _TextExtractor(HTMLParser):
    """Strips tags, keeps text and the page <title> (used as the
    document title when a source's first sync creates its document).
    Deliberately not a full DOM parser — see module docstring."""

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        stripped = data.strip()
        if not stripped:
            return
        if self._in_title:
            self.title_parts.append(stripped)
        elif self._skip_depth == 0:
            self.text_parts.append(stripped)


def extract_text(html: str) -> tuple[str, str | None]:
    """Returns (body_text, page_title_or_None)."""
    parser = _TextExtractor()
    parser.feed(html)
    title = " ".join(parser.title_parts).strip() or None
    return "\n\n".join(parser.text_parts), title


def _hash_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class WebsiteSyncError(Exception):
    """User-facing failure for a single source: fetch failed, source
    not found for this tenant, etc. Endpoints turn this into a 400/404
    without leaking exception internals; sync_all_sources() below
    catches it per-source instead so one bad URL doesn't abort an
    entire batch sync."""


def sync_source(tenant_id: int, source_id: int) -> str:
    """Fetches, diffs, and ingests-if-changed one configured source.
    Returns 'unchanged' or 'ingested'. Raises WebsiteSyncError on
    fetch/lookup failure — callers doing a single explicit sync should
    see that; sync_all_sources() below catches it per-source instead."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT url, document_id, last_content_hash FROM tenant_sync_source WHERE id = %s AND tenant_id = %s",
            (source_id, tenant_id),
        )
        row = cur.fetchone()
        cur.close()
    if row is None:
        raise WebsiteSyncError("Sync source not found.")

    url = row["url"]
    try:
        resp = httpx.get(url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        raise WebsiteSyncError(f"Failed to fetch {url}: {exc}") from exc

    text, title = extract_text(resp.text)
    content_hash = _hash_content(text)

    if row["document_id"] is not None and content_hash == row["last_content_hash"]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE tenant_sync_source SET last_synced_at = NOW() WHERE id = %s AND tenant_id = %s",
                (source_id, tenant_id),
            )
            cur.close()
        return "unchanged"

    document_id = _upsert_synced_document(tenant_id, row["document_id"], url, title, text)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE tenant_sync_source
               SET document_id = %s, last_synced_at = NOW(), last_content_hash = %s
               WHERE id = %s AND tenant_id = %s""",
            (document_id, content_hash, source_id, tenant_id),
        )
        cur.close()

    ingest_document(document_id)
    return "ingested"


def _upsert_synced_document(tenant_id: int, document_id: int | None, url: str, title: str | None, text: str) -> int:
    """Creates the source's document on first sync, or updates it in
    place on a later sync — same "clear old chunks, reset to pending,
    let ingest_document() rebuild" shape app/api/documents.py's
    reindex_document() already uses. Explicitly resets review_state to
    'draft' on update, even if the document was 'published' — a
    content change on a live synced page needs the same re-review a
    brand new document would get, not a silent live update."""
    doc_title = title or url

    with get_conn() as conn:
        cur = conn.cursor()
        if document_id is None:
            cur.execute(
                """INSERT INTO document (tenant_id, title, filename, raw_markdown, status, review_state)
                   VALUES (%s, %s, %s, %s, 'pending', 'draft')""",
                (tenant_id, doc_title, url, text),
            )
            document_id = cur.lastrowid
        else:
            cur.execute(
                """UPDATE document
                   SET title = %s, raw_markdown = %s, status = 'pending',
                       review_state = 'draft', error_message = NULL
                   WHERE id = %s AND tenant_id = %s""",
                (doc_title, text, document_id, tenant_id),
            )
            cur.execute("DELETE FROM document_chunk WHERE document_id = %s AND tenant_id = %s", (document_id, tenant_id))
        cur.close()
    return document_id


def sync_all_sources(tenant_id: int) -> list[dict]:
    """2.3's 'Sync now' entry point — syncs every configured source
    for a tenant. Per-source failures are caught and reported rather
    than raised, so one unreachable URL doesn't stop the rest of the
    batch from syncing."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, url FROM tenant_sync_source WHERE tenant_id = %s", (tenant_id,))
        sources = cur.fetchall()
        cur.close()

    results = []
    for source in sources:
        try:
            status = sync_source(tenant_id, source["id"])
            results.append({"id": source["id"], "url": source["url"], "status": status})
        except WebsiteSyncError as exc:
            results.append({"id": source["id"], "url": source["url"], "status": f"error: {exc}"})
    return results
