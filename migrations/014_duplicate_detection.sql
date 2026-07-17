-- Phase 3 — 3.1: Duplicate/conflict detection
--
-- One row per flagged near-duplicate PAIR — either two documents with
-- similar titles, or two chunk headings (in different documents) with
-- similar text. `source` distinguishes which comparison produced the
-- flag; `label_a`/`label_b` store the actual text that was compared
-- (a document's title, or a chunk's heading_path) so the admin review
-- UI (3.3) can show exactly what looked similar, not just "these two
-- documents might be related."
--
-- `document_id_a` is always the lower id of the pair (enforced in
-- app/services/duplicate_detection.py, not the DB) -- so (A,B) and
-- (B,A) are never stored as two separate flags for the same pair.
--
-- `resolved_at IS NULL` means still needs review -- same nullable-
-- timestamp-as-active/resolved pattern `api_key.revoked_at`
-- established in Phase 2. A resolved flag is never automatically
-- re-created by a later scan even if the same similar text is still
-- there (see duplicate_detection.py's `_flag_exists()`) -- once an
-- admin has looked at a pair and dismissed it, repeated re-scans
-- shouldn't keep re-surfacing the same dismissed pair every time.
--
-- ON DELETE CASCADE on both document FKs: a flag referencing a
-- document that no longer exists isn't useful information, it's
-- stale noise -- deleting either side of the pair should delete the
-- flag, unlike tenant_sync_source's ON DELETE SET NULL (a document
-- outliving the source that created it is meaningful there; a flag
-- outliving one of the two documents it's ABOUT is not).
--
-- No DB-level uniqueness constraint on (document_id_a, document_id_b,
-- source, label_a, label_b) -- label text can be long, and a
-- MySQL/MariaDB unique index across two VARCHAR(255) columns plus the
-- rest of the row risks the same key-length ceiling
-- tenant_sync_source's url(255) prefix index was built to avoid.
-- Dedup is enforced at the application layer instead
-- (`_flag_exists()` checks before inserting), which also lets it
-- apply the "don't re-flag something already resolved" rule a plain
-- DB constraint couldn't express anyway.
--
-- Safe to re-run: CREATE TABLE IF NOT EXISTS is idempotent.

CREATE TABLE IF NOT EXISTS duplicate_flag (
    id            INT PRIMARY KEY AUTO_INCREMENT,
    tenant_id     INT NOT NULL,
    document_id_a INT NOT NULL,
    document_id_b INT NOT NULL,
    source        ENUM('title','heading') NOT NULL,
    label_a       VARCHAR(255) NOT NULL,
    label_b       VARCHAR(255) NOT NULL,
    similarity    FLOAT NOT NULL,
    detected_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at   TIMESTAMP NULL,
    CONSTRAINT fk_duplicate_flag_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE,
    CONSTRAINT fk_duplicate_flag_doc_a
        FOREIGN KEY (document_id_a) REFERENCES document(id) ON DELETE CASCADE,
    CONSTRAINT fk_duplicate_flag_doc_b
        FOREIGN KEY (document_id_b) REFERENCES document(id) ON DELETE CASCADE,
    INDEX idx_duplicate_flag_tenant (tenant_id, resolved_at)
);
