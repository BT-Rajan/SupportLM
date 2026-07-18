-- Phase 1 — 1.1: Tenant/org schema
--
-- Adds `tenant` (the org-level record every future table will scope to)
-- and `tenant_user` (which admin_user accounts belong to which tenant —
-- role list here is a placeholder; Phase 2 RBAC extends/replaces it).
--
-- Does NOT touch `company`, `document`, `conversation`, etc. yet:
--   - `company` -> `tenant` data fold-in happens in the 1.3 backfill
--     migration, once a default tenant exists to fold it into.
--   - `tenant_id` retrofit onto existing tables is 1.2, next tranche.
--
-- Safe to re-run on a fresh install (drops first, like 001_init.sql).
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS tenant_user;
DROP TABLE IF EXISTS tenant;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE tenant (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(150) NOT NULL UNIQUE,
    plan_tier       VARCHAR(50) NOT NULL DEFAULT 'free',   -- 5.1 will formalize the tier table this points at
    status          ENUM('active','suspended','trial') NOT NULL DEFAULT 'trial',
    profile_json    JSON NULL,           -- absorbs what `company.profile_json` held (industry, about, etc.)
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE tenant_user (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    tenant_id       INT NOT NULL,
    admin_id        INT NOT NULL,
    role            ENUM('owner','admin') NOT NULL DEFAULT 'admin',   -- placeholder; Phase 2 RBAC extends this
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE,
    FOREIGN KEY (admin_id) REFERENCES admin_user(id) ON DELETE CASCADE,
    UNIQUE KEY uq_tenant_admin (tenant_id, admin_id)
);
