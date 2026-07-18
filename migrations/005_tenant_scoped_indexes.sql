-- Phase 1 — 1.4: Indexes for tenant-scoped queries
--
-- Composite indexes for the hot paths named in the WBS: chunk search
-- (embedding -> document_chunk -> document, filtered by ready status),
-- document listing (ordered by upload time), and conversation lookup
-- (messages within a conversation, ordered by time). All lead with
-- `tenant_id` so they can also serve as the primary filter once 3.1/3.2
-- add `WHERE tenant_id = %s` to every query.
--
-- Also fixes a real multi-tenant correctness bug found while doing
-- this: `category.slug` currently has a GLOBAL UNIQUE constraint, which
-- would stop two different tenants from both using a slug like
-- 'billing'. Replaced with a composite UNIQUE (tenant_id, slug).
--
-- Idempotency note: `ADD INDEX IF NOT EXISTS` is used instead of the
-- DROP-then-ADD pattern from 002/003. Testing showed MariaDB
-- automatically repoints each table's FK constraint onto the new
-- tenant-led composite index (and drops the old single-column FK index
-- 1.2 created, e.g. `fk_document_tenant`) as soon as the composite
-- exists. That makes the composite FK-load-bearing, so a later
-- `DROP INDEX IF EXISTS` on it fails with "needed in a foreign key
-- constraint" on re-run. `IF NOT EXISTS` sidesteps this: nothing is
-- ever dropped, so there's nothing for the FK to lose.

-- document: chunk-search join filters on (tenant_id, status); document
-- listing is ordered by (tenant_id, uploaded_at).
ALTER TABLE document ADD INDEX IF NOT EXISTS idx_document_tenant_status (tenant_id, status);
ALTER TABLE document ADD INDEX IF NOT EXISTS idx_document_tenant_uploaded (tenant_id, uploaded_at);

-- document_chunk: joined from document by document_id, scoped by tenant.
ALTER TABLE document_chunk ADD INDEX IF NOT EXISTS idx_document_chunk_tenant_doc (tenant_id, document_id);

-- embedding: chunk_id is already UNIQUE (1:1 with document_chunk), but a
-- tenant-led composite lets the search query filter by tenant without
-- touching document_chunk/document first.
ALTER TABLE embedding ADD INDEX IF NOT EXISTS idx_embedding_tenant_chunk (tenant_id, chunk_id);

-- category: fix global-unique slug bug + add tenant-scoped lookup index.
-- This one IS safe to drop-then-add: `slug`'s unique index isn't the
-- one the tenant FK depends on (tenant FK already repoints to whatever
-- tenant-led index exists once one is added), so we run this drop once;
-- on re-run the `slug` key is already gone and the IF EXISTS guard
-- makes that a no-op.
ALTER TABLE category DROP INDEX IF EXISTS slug;
ALTER TABLE category ADD UNIQUE INDEX IF NOT EXISTS uq_category_tenant_slug (tenant_id, slug);

-- conversation: listing/lookup ordered by recency, scoped by tenant.
ALTER TABLE conversation ADD INDEX IF NOT EXISTS idx_conversation_tenant_last_msg (tenant_id, last_message_at);

-- message: fetching a conversation's messages in order, scoped by tenant.
ALTER TABLE message ADD INDEX IF NOT EXISTS idx_message_tenant_conv_created (tenant_id, conversation_id, created_at);

-- citation: citations for a message, scoped by tenant.
ALTER TABLE citation ADD INDEX IF NOT EXISTS idx_citation_tenant_message (tenant_id, message_id);
