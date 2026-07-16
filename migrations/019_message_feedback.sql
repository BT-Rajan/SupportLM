-- Phase 5 — 3.1: Thumbs up/down feedback schema
--
-- `message_id` is UNIQUE, not just indexed — the direct consequence of
-- the owner's kickoff decision: "let the visitor change their vote
-- afterward" was explicitly NOT chosen. One feedback row per message,
-- ever. A second submission attempt is rejected at the app layer
-- (3.2) with a 409, and the UNIQUE constraint here is the schema-level
-- backstop against that ever being bypassed by a race or a bug.
--
-- No visitor identity to key on (the chat widget is fully anonymous —
-- same as every other message/conversation row in this schema), so
-- feedback is keyed purely on which message it's about.
--
-- `tenant_id` is denormalized onto this table (derivable via
-- `message.tenant_id`) for the same reason every other table in this
-- schema denormalizes it: every tenant-scoped query filters on
-- `tenant_id` directly rather than joining through `message` first,
-- matching the isolation-enforcement pattern established across all
-- of Phase 1.
--
-- Safe to re-run: CREATE TABLE IF NOT EXISTS is idempotent.

CREATE TABLE IF NOT EXISTS message_feedback (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id   INT NOT NULL,
    message_id  INT NOT NULL,
    rating      ENUM('up', 'down') NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES message(id) ON DELETE CASCADE,
    UNIQUE KEY uq_message_feedback_message (message_id)
);
