-- Phase 1 — 1.2: Retrofit tenant_id onto existing tables
--
-- Adds a flat `tenant_id` column (FK -> tenant(id)) directly to every
-- table that needs tenant scoping, per the 1.1 proposal's decision to
-- denormalize rather than rely on joins back through a parent table.
--
-- NULLable for now: there is no tenant data to stamp existing rows with
-- yet (that's 1.3's backfill). 1.3 will also convert these to NOT NULL
-- once every row has a value. Composite `(tenant_id, ...)` indexes for
-- hot-path queries are 1.4, not this migration — the FK here only gives
-- each column its own single-column index for free.
--
-- Does NOT touch `company` (folded into `tenant` during 1.3's backfill,
-- then dropped) or `tenant`/`tenant_user` (already correct from 1.1).
--
-- Re-runnable on a fresh install: drops the columns first if present.

-- document
ALTER TABLE document DROP FOREIGN KEY IF EXISTS fk_document_tenant;
ALTER TABLE document DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE document
    ADD COLUMN tenant_id INT NULL AFTER id,
    ADD CONSTRAINT fk_document_tenant FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE;

-- document_chunk
ALTER TABLE document_chunk DROP FOREIGN KEY IF EXISTS fk_document_chunk_tenant;
ALTER TABLE document_chunk DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE document_chunk
    ADD COLUMN tenant_id INT NULL AFTER id,
    ADD CONSTRAINT fk_document_chunk_tenant FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE;

-- embedding
ALTER TABLE embedding DROP FOREIGN KEY IF EXISTS fk_embedding_tenant;
ALTER TABLE embedding DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE embedding
    ADD COLUMN tenant_id INT NULL AFTER id,
    ADD CONSTRAINT fk_embedding_tenant FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE;

-- category
ALTER TABLE category DROP FOREIGN KEY IF EXISTS fk_category_tenant;
ALTER TABLE category DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE category
    ADD COLUMN tenant_id INT NULL AFTER id,
    ADD CONSTRAINT fk_category_tenant FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE;

-- conversation
ALTER TABLE conversation DROP FOREIGN KEY IF EXISTS fk_conversation_tenant;
ALTER TABLE conversation DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE conversation
    ADD COLUMN tenant_id INT NULL AFTER id,
    ADD CONSTRAINT fk_conversation_tenant FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE;

-- message
ALTER TABLE message DROP FOREIGN KEY IF EXISTS fk_message_tenant;
ALTER TABLE message DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE message
    ADD COLUMN tenant_id INT NULL AFTER id,
    ADD CONSTRAINT fk_message_tenant FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE;

-- citation
ALTER TABLE citation DROP FOREIGN KEY IF EXISTS fk_citation_tenant;
ALTER TABLE citation DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE citation
    ADD COLUMN tenant_id INT NULL AFTER id,
    ADD CONSTRAINT fk_citation_tenant FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE;

-- agent
ALTER TABLE agent DROP FOREIGN KEY IF EXISTS fk_agent_tenant;
ALTER TABLE agent DROP COLUMN IF EXISTS tenant_id;
ALTER TABLE agent
    ADD COLUMN tenant_id INT NULL AFTER id,
    ADD CONSTRAINT fk_agent_tenant FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE;
