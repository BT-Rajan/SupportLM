-- Phase 2 — 1.1: RBAC role hierarchy
--
-- Extends `tenant_user.role`, a placeholder ENUM('owner','admin') left
-- by Phase 1's 002 migration specifically for this, into the four-tier
-- hierarchy named in docs/MASTER_PROMPT.md Section 3's Phase 2 scope:
-- owner > admin > editor > viewer. Existing 'owner'/'admin' rows keep
-- their exact meaning — both values already exist in the new ENUM, so
-- this is additive, not a remap.
--
-- `admin_user.role` (001_init.sql) is a separate, tenant-independent
-- column and is deliberately NOT touched here: it's confirmed unused
-- for authorization anywhere in the codebase (only ever written by
-- scripts/create_admin.py and scripts/create_tenant.py, never read),
-- and a single account-wide role couldn't express RBAC correctly
-- anyway — the same admin can be 'owner' on one tenant and 'viewer' on
-- another (Phase 1 already made "one admin, multiple tenants" real).
-- Dropping that legacy column is a separate, explicit task, not a
-- side effect of this one.
--
-- New rows keep defaulting to 'admin' (unchanged from 002) — nothing
-- in the app inserts 'editor'/'viewer' tenant_user rows yet (there is
-- no invite flow), so there's no reason to change what a bare INSERT
-- without an explicit role produces.

ALTER TABLE tenant_user
    MODIFY COLUMN role ENUM('owner','admin','editor','viewer') NOT NULL DEFAULT 'admin';
