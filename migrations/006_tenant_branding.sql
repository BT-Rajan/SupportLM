-- Phase 1 — 4.1: Per-tenant branding data model
--
-- A dedicated 1:1 extension table, not more columns on `tenant` itself
-- — keeps "what does this org's widget look like" separate from the
-- core org record, and makes branding independently readable/writable
-- (the "pluggable" part: nothing about `tenant` itself needs to change
-- to add a new brandable field later).
--
-- Every column is nullable and independently optional — a tenant can
-- set just a logo, just an accent, all of it, or none of it. Rendering
-- (4.2/4.3) falls back to today's defaults for whatever's NULL.
--
-- accent_hex is deliberately the ONLY color input: app/core/theme.py
-- derives the full --accent/--accent-ink/--accent-soft trio from it,
-- so a tenant picks one color and still gets a cohesive palette rather
-- than three independent pickers that could clash.
--
-- Safe to re-run on a fresh install (drops first, like earlier
-- structural migrations).
DROP TABLE IF EXISTS tenant_branding;

CREATE TABLE tenant_branding (
    tenant_id       INT PRIMARY KEY,
    display_name    VARCHAR(255) NULL,   -- widget header text; falls back to tenant.name
    agent_name      VARCHAR(100) NULL,   -- falls back to "Assistant"
    logo_url        VARCHAR(500) NULL,   -- falls back to a generated monogram
    accent_hex      CHAR(7) NULL,        -- e.g. '#7c3aed'; falls back to the default emerald theme
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE
);
