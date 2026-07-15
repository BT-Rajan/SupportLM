-- Phase 4 — 1.1: Hybrid search schema
--
-- Adds a MySQL/MariaDB native FULLTEXT index on document_chunk.content
-- so 1.2's keyword_search() can run MATCH(content) AGAINST(...) IN
-- NATURAL LANGUAGE MODE alongside the existing brute-force cosine
-- vector search from Phase 1. No vector DB migration — per
-- docs/MASTER_PROMPT.md Phase 4 scope, this stays on the existing
-- MySQL store.
--
-- InnoDB has supported FULLTEXT indexes natively since MySQL 5.6 /
-- MariaDB 10.0.5 — document_chunk is already InnoDB, no engine change
-- needed.
--
-- Idempotency note: `ADD FULLTEXT INDEX IF NOT EXISTS` follows the
-- same pattern as 005_tenant_scoped_indexes.sql (plain composite
-- indexes aren't FK-load-bearing here, so IF NOT EXISTS is sufficient
-- with no drop-then-add complication).

ALTER TABLE document_chunk
    ADD FULLTEXT INDEX IF NOT EXISTS ft_document_chunk_content (content);
