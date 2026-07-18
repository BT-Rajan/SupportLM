-- Phase 8 — 1.1: Audit log schema
--
-- Scoped exactly to the master prompt's literal list —
-- uploads/edits/deletes/admin logins — not every admin action across
-- the whole system. That broader scope is a real temptation this
-- table's existence invites; resisting it here rather than letting
-- this migration silently grow into a general-purpose event log.
--
-- `admin_id` is nullable with ON DELETE SET NULL, not CASCADE — same
-- rationale as `api_key.created_by_admin_id` and `tenant_prompt_
-- version.created_by_admin_id`: deleting the admin who performed an
-- action must not delete the audit record OF that action. An audit
-- log that vanishes when the person it's about is removed defeats its
-- own purpose.
--
-- `entity_id` is nullable — a login event has no entity (there's no
-- "thing" being logged in, just an admin+tenant pair), while
-- upload/edit/delete events reference a specific document.
--
-- Safe to re-run: CREATE TABLE IF NOT EXISTS is idempotent.

CREATE TABLE IF NOT EXISTS audit_log (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id    INT NOT NULL,
    admin_id     INT NULL,
    action       VARCHAR(50) NOT NULL,
    entity_type  VARCHAR(50) NOT NULL,
    entity_id    INT NULL,
    detail       TEXT NULL,
    ip_address   VARCHAR(45) NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE,
    FOREIGN KEY (admin_id) REFERENCES admin_user(id) ON DELETE SET NULL,
    KEY idx_audit_log_tenant_created (tenant_id, created_at)
);
