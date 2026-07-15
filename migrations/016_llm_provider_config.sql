-- Phase 4 — 2.1: Multi-LLM provider configuration
--
-- One row per tenant that has customized its chat LLM provider —
-- 1:1 with `tenant`, same "dedicated table over more columns on
-- tenant itself" pattern `tenant_branding` (Phase 1, 006) established.
-- A tenant with NO row here uses the global default (DeepSeek, via
-- the existing `settings.llm_api_key`/`settings.llm_chat_model` env
-- vars) — same "explicit override, sane default otherwise" fallback
-- contract as branding, not an inferred/auto-selected provider.
--
-- `api_key` is stored in PLAINTEXT, not encrypted. This is a
-- deliberate scope decision, not an oversight: docs/MASTER_PROMPT.md
-- Section 2.8 explicitly lists "encryption at rest" and "secrets
-- management overhaul" as out of scope for this transformation. A
-- one-way hash (the `api_key`/`api_key` table's pattern) doesn't work
-- here — this key must be read back in plaintext to actually call the
-- provider's API, unlike an api_key row which is only ever compared,
-- never sent anywhere. If encryption-at-rest is added to scope later,
-- this column is the one to revisit first.
--
-- Safe to re-run: CREATE TABLE IF NOT EXISTS is idempotent.

CREATE TABLE IF NOT EXISTS tenant_llm_config (
    tenant_id       INT PRIMARY KEY,
    provider        ENUM('deepseek', 'openai', 'anthropic') NOT NULL,
    model           VARCHAR(100) NOT NULL,
    api_key         VARCHAR(500) NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE
);
