-- Phase 6 — 3.1: Support inbox configuration schema
--
-- Intentionally NOT nullable-with-a-global-fallback the way
-- tenant_llm_config's per-tenant overrides are — the owner's kickoff
-- decision for this phase was "required," not "override with a
-- fallback." A tenant simply has no row here until an admin sets one;
-- 3.2's completion flow checks for that row's existence and refuses
-- to fabricate an escalation with nowhere for the company side of the
-- notification to go.
--
-- Safe to re-run: CREATE TABLE IF NOT EXISTS is idempotent.

CREATE TABLE IF NOT EXISTS tenant_support_config (
    tenant_id      INT PRIMARY KEY,
    support_email  VARCHAR(255) NOT NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE
);
