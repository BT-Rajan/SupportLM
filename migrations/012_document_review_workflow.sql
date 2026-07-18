-- Phase 3 — 1.1: Content review workflow
--
-- Adds `document.review_state`, deliberately separate from the
-- existing `document.status` column. `status`
-- (`pending`/`processing`/`ready`/`error`) is the ingestion PIPELINE
-- state -- has this document been chunked and embedded successfully --
-- and `app/services/vector_store.py`'s `search()` already filters on
-- `status = 'ready'`. `review_state` is a different axis entirely: is
-- this content approved to be customer-facing. Reusing `status` for
-- both would silently break the ingestion state machine -- a document
-- mid-reindex needs to be `'processing'` for ingestion purposes while
-- staying whatever it was editorially, and one column can't hold both
-- at once. See docs/Phase III WBS.md's "A schema collision worth
-- flagging before 1.1" for the full reasoning.
--
-- Retrieval ends up gated on BOTH columns (1.2): a document must be
-- `status = 'ready'` (successfully ingested) AND
-- `review_state = 'published'` (editorially approved) to be
-- retrievable. Failing either is enough to exclude it.
--
-- Idempotency note, same shape as 004_backfill_default_tenant.sql:
-- the ALTER below is safe to re-run (IF NOT EXISTS). The backfill
-- UPDATE is NOT safe to re-run once real drafts exist -- it sets
-- every document to 'published' unconditionally, which is correct
-- exactly once (existing pre-1.1 documents were all instant-live, so
-- they should stay visible) but would silently re-publish genuine
-- drafts if this file were ever re-applied to a database that's
-- already been used under the new workflow. On a fresh install this
-- is a non-issue -- 001-012 run back-to-back against an empty
-- database, so the backfill UPDATE simply touches 0 rows. Documents
-- created AFTER this migration start at 'draft' via the column
-- DEFAULT plus an explicit review_state='draft' in
-- app/api/documents.py's upload route (1.2) -- not relying on the
-- default alone, since a bare INSERT omitting the column is the only
-- thing the default actually governs.

ALTER TABLE document
    ADD COLUMN IF NOT EXISTS review_state ENUM('draft','review','published') NOT NULL DEFAULT 'draft' AFTER status;

-- One-time backfill -- see note above. Everything that existed before
-- this migration was instant-live under the old model, so it starts
-- 'published' rather than disappearing from retrieval.
UPDATE document SET review_state = 'published';
