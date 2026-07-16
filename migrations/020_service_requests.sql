-- Phase 6 — 2.1: Service Request schema
--
-- `sr_sequence` is a small per-tenant, per-day counter used to
-- generate collision-free SR numbers under concurrency. An
-- `INSERT ... ON DUPLICATE KEY UPDATE next_seq = next_seq + 1` then a
-- read-back is atomic under InnoDB's row locking — a `COUNT(*) + 1`
-- against `service_request` would race under concurrent escalations
-- for the same tenant on the same day (two requests could both count
-- the same N existing rows and both compute N+1).
--
-- `service_request.sr_number` is UNIQUE PER TENANT, not globally —
-- the human-readable format (SR-YYYYMMDD-sequence) is only guaranteed
-- collision-free WITHIN a tenant/day by construction (each tenant has
-- its own `sr_sequence` row), so two different tenants are EXPECTED
-- to both produce e.g. "SR-20260716-0001" on the same day — same as
-- two different companies both having an invoice #1001. A plain
-- global UNIQUE on `sr_number` alone would incorrectly reject the
-- second tenant's identical-looking number; the composite
-- `(tenant_id, sr_number)` key is what actually matches the guarantee
-- this format provides.
--
-- `message_id` (not just `conversation_id`) is stored because 3.4's
-- endpoint needs to verify a re-submitted email is for the SAME
-- assistant message that actually signaled escalation, not any
-- arbitrary message in the conversation.
--
-- Safe to re-run: CREATE TABLE IF NOT EXISTS is idempotent.

CREATE TABLE IF NOT EXISTS sr_sequence (
    tenant_id  INT NOT NULL,
    seq_date   DATE NOT NULL,
    next_seq   INT NOT NULL DEFAULT 1,
    PRIMARY KEY (tenant_id, seq_date),
    FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS service_request (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id        INT NOT NULL,
    sr_number        VARCHAR(30) NOT NULL,
    conversation_id  CHAR(36) NOT NULL,
    message_id       INT NOT NULL,
    visitor_email    VARCHAR(255) NOT NULL,
    status           ENUM('open', 'closed') NOT NULL DEFAULT 'open',
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE,
    FOREIGN KEY (conversation_id) REFERENCES conversation(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES message(id) ON DELETE CASCADE,
    UNIQUE KEY uq_service_request_tenant_sr (tenant_id, sr_number),
    UNIQUE KEY uq_service_request_message (message_id)
);
