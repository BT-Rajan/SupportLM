-- Phase 2 — 3.1: Server-side session invalidation
--
-- Adds `admin_user.session_version`. A signed session token
-- (itsdangerous, see app/core/security.py) is stateless by design —
-- deleting the cookie is the only thing "logging out" could mean
-- before this, and a stolen/leaked token stays valid until it expires
-- on its own (8h, `_SESSION_MAX_AGE`). This column turns "delete the
-- cookie" into "actually revoke": the token embeds the version at
-- issue time, `require_admin` (3.1, app/core/deps.py) rejects any
-- token whose embedded version doesn't match the current DB value,
-- and `POST /api/auth/logout-all` (3.2) bumps this column to
-- invalidate every outstanding session for that admin in one call —
-- something a purely stateless token could never do on its own.
--
-- Starts at 1, not 0: a token minted before this migration existed
-- has no `session_version` claim in its payload at all (old shape:
-- `{"admin_id": ...}` only). `read_session_token` (security.py) reads
-- that missing claim as `None`, which will never equal an integer
-- column, so this migration also has the side effect of invalidating
-- every session issued before it runs — deliberate, not a bug: a
-- security-hardening change should not grandfather in tokens minted
-- under the weaker, unrevocable model. Every admin simply logs in
-- again once, gets a token carrying `session_version: 1`, and is
-- fine from then on.
--
-- Safe to re-run: ADD COLUMN IF NOT EXISTS is idempotent, unlike a
-- bare ADD COLUMN which would error on a second run.

ALTER TABLE admin_user
    ADD COLUMN IF NOT EXISTS session_version INT NOT NULL DEFAULT 1;
