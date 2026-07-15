-- Phase 2 — 4.1: Anonymous chat transcript email
--
-- `conversation.visitor_email` — nullable, set only when a visitor
-- opts in to receiving their transcript by email (4.2's
-- POST /api/chat/transcript). No account, no auth, no end-user login
-- anywhere in this feature — matches docs/MASTER_PROMPT.md's explicit
-- "no SSO, no end-user login, chats stay fully anonymous" scope for
-- Phase 2. This is the visitor voluntarily giving one address for one
-- outbound send, not an identity.
--
-- Column lives on `conversation`, not a new table: one visitor email
-- per conversation is all this feature needs (docs/MASTER_PROMPT.md's
-- scope list explicitly declines PII redaction / data retention
-- tooling / encryption at rest for this phase, so there's no reason
-- to over-engineer the storage shape beyond what 4.2 actually reads
-- and writes).
--
-- Safe to re-run: ADD COLUMN IF NOT EXISTS is idempotent.

ALTER TABLE conversation
    ADD COLUMN IF NOT EXISTS visitor_email VARCHAR(255) NULL AFTER visitor_label;
