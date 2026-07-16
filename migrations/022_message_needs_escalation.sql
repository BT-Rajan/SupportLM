-- Phase 6 — 3.4 (validation dependency): persist the escalation signal
--
-- `ask()`'s `needs_escalation` was, until now, a transient value only
-- ever returned to the caller — never stored. 3.4's `/escalate`
-- endpoint needs to verify that a submitted `message_id` is the
-- SPECIFIC assistant message that actually signaled escalation, not
-- just any assistant message in the conversation (per
-- docs/Phase VI WBS.md's 3.4 note) — that check is impossible without
-- persisting the flag somewhere. `message` is the natural home for it
-- rather than a new table, since it's a property of that one row.
--
-- Defaults to FALSE, not NULL — every existing message legitimately
-- never signaled escalation (this column didn't exist when they were
-- written), so FALSE is the accurate historical value, not an unknown.
--
-- Safe to re-run: ADD COLUMN IF NOT EXISTS is idempotent, same idiom
-- as 010/011/017/018.

ALTER TABLE message
    ADD COLUMN IF NOT EXISTS needs_escalation BOOLEAN NOT NULL DEFAULT FALSE;
