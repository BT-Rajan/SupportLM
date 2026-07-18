-- Phase 9 — 1.1: Per-tenant retrieval confidence threshold
--
-- Gates whether hybrid_search()'s top result is treated as real
-- context at all, independent of ranking — the fused/normalized score
-- always makes the best-of-the-pool look maximally confident even
-- when nothing in the pool is actually relevant. This column holds
-- the raw cosine-similarity floor an admin requires before the
-- retrieved chunks are trusted enough to answer from; below it, the
-- assistant falls back to "I don't know" / escalation instead of
-- narrating from weak matches.
--
-- DECIMAL(3,2) covers the full 0.00–1.00 cosine range at the
-- precision a slider UI needs. NULL means "use the app-wide default"
-- (chat.py's _DEFAULT_CONFIDENT_SIMILARITY) — same nullable,
-- explicit-override contract as every other optional column on this
-- table (tone, agent_name, accent_hex).
--
-- Safe to re-run: ADD COLUMN IF NOT EXISTS is idempotent, same idiom
-- as 010/011/017/018/027.

ALTER TABLE tenant_branding
    ADD COLUMN IF NOT EXISTS retrieval_confidence_threshold DECIMAL(3,2) NULL;
