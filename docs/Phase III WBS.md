# Phase 3 WBS — Knowledge Base Management

> Scope source: `docs/MASTER_PROMPT.md` Section 3, "Phase 3". Nothing
> here expands that scope; this file breaks it into buildable, ordered
> rounds the way `docs/Phase I WBS.md` and `docs/Phase II WBS.md` did
> for their phases.

Phase 3 scope, verbatim from the master prompt: draft → review →
publish workflow for documents (no more instant-live on upload). Daily
incremental website content sync (crawl configured URLs once a day,
diff against existing docs). Daily automated job that analyzes the
knowledge base for duplicate and conflicting content across documents
and surfaces it for review. **Not included:** Confluence/Notion
connectors.

## Owner decisions confirmed at kickoff

- **1.0 role gating**: any role at `editor`+ can move a document
  through every review state — no separate "reviewer" or "publisher"
  tier. The three-state field still exists and still blocks retrieval
  until `published` (see 1.1 below); it just isn't role-gated between
  its own states beyond the existing `editor`+ floor.
- **2.0 sync cadence**: **manual trigger only** ("Sync now" button) —
  not a daily cron. This is a direct, explicit deviation from the
  master prompt's "daily incremental... sync" language, confirmed with
  the owner rather than silently reinterpreted. If automatic daily
  cadence is wanted later, it's a small addition on top of this (a
  cron entry calling the same sync function 2.2 already builds) —
  not a redesign.
- **3.0 conflict definition**: kept deliberately simple — near-duplicate
  **titles/headings only**, not semantic/embedding-based conflict
  detection. A real scope reduction from "duplicate and conflicting
  content" as written; flagged here rather than silently narrowed.
- **3.0 cadence — assumption, not confirmed**: the owner wasn't asked
  about this one directly. Building it manual-trigger too, for
  consistency with 2.0 and to avoid introducing a second job-runner
  mechanism for one phase. Flagged in `docs/STATUS.md` as an
  assumption to confirm, not a decided item — easy to add a cron
  trigger later if the owner wants automatic daily scans after all.

## A schema collision worth flagging before 1.1

`document.status` (`ENUM('pending','processing','ready','error')`,
from Phase 1) is the **ingestion pipeline** state — has this document
been chunked and embedded successfully — and `vector_store.py`'s
`search()` already filters on `d.status = 'ready'`. The new
draft/review/publish workflow is a completely different axis — **is
this content approved to be customer-facing** — and reusing `status`
for both would silently break the ingestion state machine (a document
mid-reindex would need to be simultaneously `'processing'` for
ingestion purposes and something else for editorial purposes; one
column can't hold both). 1.1 adds a **separate** column rather than
overloading `status`. Retrieval ends up gated on both: a document must
be `status = 'ready'` (successfully ingested) **and**
`review_state = 'published'` (editorially approved) to be retrievable
— failing either check is enough to exclude it.

## Dependency order

1.0 lands first — 2.0's synced content needs `review_state` to exist
so synced pages land as `draft`, not instant-live, matching the same
"no more instant-live" rule uploads now follow. 3.0 (duplicate
detection) is independent of 1.0/2.0's content — it compares
title/heading strings regardless of review state — so it could be
built in parallel if picked up out of order, but is sequenced last
here since it's the simplest of the three once 1.0/2.0 establish the
patterns (new migration + service + admin endpoints + admin UI) this
phase reuses three times.

## 1.0 Content Review Workflow

- **1.1 Schema**: `migrations/012_document_review_workflow.sql` adds
  `document.review_state ENUM('draft','review','published') NOT NULL
  DEFAULT 'draft'`. Existing documents backfill to `'published'` in
  the same migration — a document that was already live under the old
  instant-live model shouldn't silently vanish from retrieval the
  moment this migration runs; only documents created *after* this
  migration start at `'draft'` (enforced in 1.2's upload path, not by
  the column default alone — the default only governs what a bare
  `INSERT` gets, `app/api/documents.py`'s upload route sets it
  explicitly for clarity).
- **1.2 Retrieval gating + state-transition endpoint**:
  `app/services/vector_store.py`'s `search()` WHERE clause gets
  `AND d.review_state = 'published'` alongside the existing
  `d.status = 'ready'`. New `POST /api/documents/{id}/review-state`
  (`editor`+, body `{"state": "draft"|"review"|"published"}`) — no
  transition-order restriction beyond the three legal values, per the
  owner's "any editor+ can do both" decision. `DocumentOut` gets a
  `review_state` field.
- **1.3 Admin UI**: `templates/admin.html`'s document table gets a
  review-state badge + a control to advance/revert it. This is also
  where `admin.html`/`admin.css` finally move onto
  `docs/DESIGN_SYSTEM.md` tokens — the current admin console predates
  the design system (system-ui font, hardcoded `#4f46e5`/`#dc2626`,
  no `--accent`/`--ink` variables at all) and this phase adds enough
  new admin surface across 1.0-3.0 (review-state controls, sync
  management, duplicate-review queue) that building three more pieces
  on top of the old ad hoc styling would compound rather than pay down
  that debt. Documented as a new "Admin console" section in
  `docs/DESIGN_SYSTEM.md` once built, per that file's own existing
  (previously unfollowed) "Rules for new screens" section.

## 2.0 Website Content Sync

- **2.1 Schema**: `migrations/013_website_sync.sql` adds
  `tenant_sync_source` (id, tenant_id, url, last_synced_at NULL,
  last_content_hash NULL) — the configured-URL list the master prompt
  calls for, one row per URL a tenant wants kept in sync.
- **2.2 Crawl + diff service** (`app/services/website_sync.py`):
  fetches each configured URL directly via `httpx` (already a
  dependency) — **not** a recursive/link-following crawl; "configured
  URLs" in the master prompt reads as a fixed list the tenant
  provides, not open-ended crawling, and a recursive crawler is a much
  bigger, riskier thing to scope without being asked for it
  explicitly. HTML-to-text extraction uses Python's built-in
  `html.parser.HTMLParser` rather than adding `beautifulsoup4` as a
  new dependency — this only needs "strip tags, keep text," not full
  DOM traversal. Content is hashed (`hashlib.sha256`) and compared to
  `last_content_hash`; unchanged content is a no-op, changed content
  is ingested through the **existing** `ingest_document()` pipeline
  from Phase 1, landing at `review_state = 'draft'` (1.1) like any
  other new content — synced pages get the same review gate as
  everything else, not a bypass.
- **2.3 Admin endpoints + UI**: `POST/GET/DELETE
  /api/documents/sync-sources` (manage the configured URL list,
  `editor`+ to add/remove, matching 1.0's upload floor) and `POST
  /api/documents/sync-sources/sync-now` (`admin`+ — this fetches
  external URLs and writes documents, closer to upload than to a
  read-only action, so it sits at the same floor as delete). Admin UI:
  a source-URL manager + "Sync now" button + last-synced timestamp per
  source, in the same `admin.html` rebuild as 1.3.

## 3.0 Duplicate/Conflict Detection

- **3.1 Schema**: `migrations/014_duplicate_detection.sql` adds
  `duplicate_flag` (id, tenant_id, document_id_a, document_id_b,
  similarity, detected_at, resolved_at NULL) — one row per flagged
  pair, `resolved_at IS NULL` meaning still needs review (same
  "nullable timestamp as the active/resolved signal" pattern
  `api_key.revoked_at` already established in Phase 2).
- **3.2 Detection service** (`app/services/duplicate_detection.py`):
  compares document titles and `document_chunk.heading_path` values
  pairwise within a tenant using `difflib.SequenceMatcher` (stdlib, no
  new dependency) after normalizing (lowercase, strip punctuation).
  Pairs above a similarity threshold get upserted into
  `duplicate_flag`. Deliberately not embedding/semantic-similarity
  based, per the owner's explicit "keep it simple" scope decision —
  if that turns out to be too shallow in practice, upgrading to
  embedding comparison is a service-level change, not a schema change
  (the `duplicate_flag` table doesn't care how similarity was
  computed).
- **3.3 Admin endpoints + UI**: `POST /api/documents/scan-duplicates`
  (`admin`+ — runs the scan explicitly, per the cadence assumption
  above), `GET /api/documents/duplicate-flags` (`viewer`+, list
  unresolved), `POST /api/documents/duplicate-flags/{id}/resolve`
  (`editor`+, dismiss). Admin UI: a duplicate-review list in the same
  `admin.html`.

## 4.0 Testing & Validation

Same shape as Phase 2's 5.0: round-by-round tests land alongside each
round above, skip-marked when no DB is reachable, plus a final full
suite pass on a freshly rebuilt DB (not reused state) across all of
Phase 3 together once 1.0-3.0 are done.

## 5.0 Documentation & Handoff

`docs/STATUS.md` updated per round, not just at the end. The
admin-console redesign in 1.3 gets documented in
`docs/DESIGN_SYSTEM.md` as it's built (same discipline as Phase 2's
4.3 transcript panel), not deferred to this closing round.
