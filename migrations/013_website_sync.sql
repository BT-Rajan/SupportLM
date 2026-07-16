-- Phase 3 — 2.1: Website content sync — configured source URLs
--
-- One row per URL a tenant wants kept in sync. Deliberately a flat
-- list, not a crawl-configuration object (no depth, no include/exclude
-- patterns) -- per docs/Phase III WBS.md, 2.2 fetches each configured
-- URL directly, it does not recursively follow links, so there's
-- nothing to configure beyond "which URLs."
--
-- `document_id` links a source to the ONE document it produces --
-- design decision made while building 2.2, not explicit in the WBS
-- text: re-syncing the same URL updates that same document in place
-- (same "delete old chunks, update raw_markdown, re-ingest" shape
-- reindex_document already uses) rather than creating a new document
-- every sync, which would otherwise pile up duplicate documents for
-- one URL over time. Nullable because a freshly-added source hasn't
-- produced a document yet -- its first sync creates one.
-- ON DELETE SET NULL, not CASCADE: deleting a document (e.g. an admin
-- manually removing it) shouldn't silently delete the sync source
-- config that made it -- the source just goes back to "not yet
-- synced" and will recreate the document on its next sync.
--
-- `last_synced_at` / `last_content_hash` are both nullable and both
-- NULL until the first sync actually runs -- a source that's been
-- added but never synced yet is a normal, valid state, not an error.
-- `last_content_hash` is what 2.2's diff check compares against on
-- each sync: unchanged hash means no-op, changed hash means re-ingest
-- (and -- another decision made while building 2.2 -- resets
-- review_state back to 'draft' even if the document was previously
-- published, since already-live content silently changing without
-- re-review would violate the whole point of 1.0's review workflow).
--
-- UNIQUE (tenant_id, url): the same URL can't be configured twice for
-- one tenant, but different tenants can each configure the same
-- public URL independently -- no cross-tenant uniqueness, matching
-- every other per-tenant uniqueness constraint in this schema (e.g.
-- category.slug's tenant-scoped UNIQUE from 1.4).
--
-- Safe to re-run: CREATE TABLE IF NOT EXISTS / ADD ... IF NOT EXISTS
-- below are idempotent.

CREATE TABLE IF NOT EXISTS tenant_sync_source (
    id                INT PRIMARY KEY AUTO_INCREMENT,
    tenant_id         INT NOT NULL,
    url               VARCHAR(2048) NOT NULL,
    document_id       INT NULL,
    last_synced_at    TIMESTAMP NULL,
    last_content_hash CHAR(64) NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_tenant_sync_source_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE,
    CONSTRAINT fk_tenant_sync_source_document
        FOREIGN KEY (document_id) REFERENCES document(id) ON DELETE SET NULL,
    INDEX idx_tenant_sync_source_tenant (tenant_id)
);

-- VARCHAR can't carry a UNIQUE constraint at full length (2048) under
-- MySQL/MariaDB's default index key-length limits, so the uniqueness
-- constraint uses a prefix index instead -- 255 chars is enough to
-- distinguish any realistic pair of configured URLs while staying
-- safely under the limit.
ALTER TABLE tenant_sync_source
    ADD UNIQUE INDEX IF NOT EXISTS uq_tenant_sync_source_url (tenant_id, url(255));
