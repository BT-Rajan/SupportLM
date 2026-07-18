-- Phase 4 — 3.1: Prompt versioning schema
--
-- Per-tenant, not global — same kickoff decision as 2.0's provider
-- config: a tenant's system prompt is the other half of its "voice"
-- alongside branding (Phase 1, 006_tenant_branding.sql), so it's
-- configurable at the same per-tenant level.
--
-- `tenant_prompt_version` is append-only from the app's perspective —
-- creating a new version never overwrites an old one (3.2's
-- create_version() always inserts). Rollback is just re-activating an
-- older row via `tenant.active_prompt_version_id`, not a separate
-- "revert" mutation on the version rows themselves.
--
-- `created_by_admin_id` is nullable with ON DELETE SET NULL — deleting
-- the admin who wrote a prompt version must not invalidate or cascade-
-- delete a version that might still be live. Exact same rationale as
-- `api_key.created_by_admin_id` (009_api_keys.sql).
--
-- `tenant.active_prompt_version_id` is nullable: NULL means "use the
-- hardcoded _SYSTEM_PROMPT default in chat.py" — same fallback
-- contract as 2.0's tenant_llm_config (explicit override, sane
-- default otherwise, no tenant forced to have a row just to get
-- default behavior).
--
-- Safe to re-run: CREATE TABLE IF NOT EXISTS and ADD COLUMN IF NOT
-- EXISTS are both idempotent, same idiom as 010/011. The FK on the new
-- column is added in its own guarded block since "ADD CONSTRAINT IF
-- NOT EXISTS" isn't available — checked against information_schema
-- instead, the one part of this file that can't use the simpler
-- IF-NOT-EXISTS idiom.

CREATE TABLE IF NOT EXISTS tenant_prompt_version (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id           INT NOT NULL,
    version_number      INT NOT NULL,
    prompt_text         TEXT NOT NULL,
    created_by_admin_id INT NULL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_admin_id) REFERENCES admin_user(id) ON DELETE SET NULL,
    UNIQUE KEY uq_tenant_version (tenant_id, version_number)
);

ALTER TABLE tenant
    ADD COLUMN IF NOT EXISTS active_prompt_version_id INT NULL;

SET @fk_exists = (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tenant'
      AND CONSTRAINT_NAME = 'fk_tenant_active_prompt_version'
);
SET @ddl = IF(
    @fk_exists = 0,
    'ALTER TABLE tenant ADD CONSTRAINT fk_tenant_active_prompt_version '
    'FOREIGN KEY (active_prompt_version_id) REFERENCES tenant_prompt_version(id) ON DELETE SET NULL',
    'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
