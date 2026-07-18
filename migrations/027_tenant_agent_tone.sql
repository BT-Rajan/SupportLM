-- Phase 8 — 3.1: Agent tone configuration schema
--
-- Living alongside `agent_name` on `tenant_branding` rather than a new
-- table — both are the same "voice" concept Phase 1 already anchored
-- there. Nullable: NULL means no tone configured, same "explicit
-- override, no forced default" contract as every other optional
-- per-tenant config column in this schema.
--
-- Safe to re-run: ADD COLUMN IF NOT EXISTS is idempotent, same idiom
-- as 010/011/017/018.

ALTER TABLE tenant_branding
    ADD COLUMN IF NOT EXISTS tone TEXT NULL;
