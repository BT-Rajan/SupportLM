-- Phase 2 — 2.1: API keys for programmatic access
--
-- Tenant-scoped credential store for the `X-API-Key` auth path 2.3
-- adds to `require_role()`. Only a SHA-256 hash of the raw key is
-- ever stored (never the raw key itself) — same principle as
-- admin_user.password_hash. `key_prefix` persists just enough of the
-- raw key (visible once, at creation time, before it's hashed) for an
-- admin to recognize which key is which in a list view; the hash
-- itself can't be reversed to redisplay it.
--
-- `role` reuses 1.0's ENUM('owner','admin','editor','viewer')
-- hierarchy verbatim rather than a separate key-scoped enum — a key
-- is just a non-interactive credential with a role, same shape as an
-- admin's role on a tenant via tenant_user.
--
-- `created_by_admin_id` is nullable with ON DELETE SET NULL, not
-- CASCADE: deleting the admin who minted a key shouldn't silently
-- revoke every key they ever created out from under whatever
-- integration depends on it. Revocation is the explicit act
-- (`revoked_at`), not a side effect of the minting admin's account
-- going away.
--
-- `revoked_at IS NULL` means active — no separate boolean, so "when
-- was it revoked" is never lost the way a flag flip would lose it.
--
-- Safe to re-run on a fresh install (drops first, like 002/007).

DROP TABLE IF EXISTS api_key;

CREATE TABLE api_key (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    tenant_id           INT NOT NULL,
    name                VARCHAR(100) NOT NULL,
    key_prefix          VARCHAR(16) NOT NULL,
    key_hash            CHAR(64) NOT NULL,
    role                ENUM('owner','admin','editor','viewer') NOT NULL,
    created_by_admin_id INT NULL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at          TIMESTAMP NULL,
    CONSTRAINT fk_api_key_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE,
    CONSTRAINT fk_api_key_admin
        FOREIGN KEY (created_by_admin_id) REFERENCES admin_user(id) ON DELETE SET NULL,
    CONSTRAINT uq_api_key_hash UNIQUE (key_hash),
    INDEX idx_api_key_tenant (tenant_id, revoked_at)
);
