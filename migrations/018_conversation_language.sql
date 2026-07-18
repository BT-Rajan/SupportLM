-- Phase 5 — 2.1: Multi-language support schema
--
-- `language` is nullable: NULL means no explicit selection has been
-- made yet (a conversation's very first message, before the widget's
-- selector value has been recorded) — same "explicit override, no
-- forced default" contract as every other nullable config column in
-- this schema (tenant_llm_config, active_prompt_version_id). Set once
-- from the widget's selected value on the first message of a
-- conversation; a visitor switching the selector mid-conversation
-- updates it going forward, not retroactively.
--
-- VARCHAR(10) comfortably fits an IETF-style tag (e.g. 'en', 'es',
-- 'zh-Hans') without over-allocating.
--
-- Safe to re-run: ADD COLUMN IF NOT EXISTS is idempotent, same idiom
-- as 010/011/017.

ALTER TABLE conversation
    ADD COLUMN IF NOT EXISTS language VARCHAR(10) NULL AFTER visitor_email;
