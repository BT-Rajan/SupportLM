-- Phase 8 — 2.1: Rate limiting schema
--
-- A fixed 1-minute window, not a sliding one — simpler, and the
-- boundary-inflation edge case a fixed window has (a burst spanning
-- the boundary of two windows can briefly exceed the nominal limit)
-- is an acceptable tradeoff for the abuse-protection use case here,
-- not a precise quota system.
--
-- `INSERT ... ON DUPLICATE KEY UPDATE request_count = request_count +
-- 1` then a read-back is atomic under InnoDB row locking — same
-- pattern as Phase 6's `sr_sequence`, safe under concurrent requests
-- hitting the same window.
--
-- Safe to re-run: CREATE TABLE IF NOT EXISTS is idempotent.

CREATE TABLE IF NOT EXISTS rate_limit_bucket (
    scope_type     ENUM('ip', 'tenant') NOT NULL,
    scope_key      VARCHAR(100) NOT NULL,
    window_start   DATETIME NOT NULL,
    request_count  INT NOT NULL DEFAULT 1,
    PRIMARY KEY (scope_type, scope_key, window_start)
);
