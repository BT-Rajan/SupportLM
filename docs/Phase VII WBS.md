# Phase 7 WBS — Analytics & Reporting

> Scope source: `docs/MASTER_PROMPT.md` Section 3, "Phase 7". Nothing
> here expands that scope; this file breaks it into buildable, ordered
> rounds the way `docs/Phase I-VI WBS.md` did for their phases.

Phase 7 scope, verbatim from the master prompt: usage dashboard,
unanswered/low-confidence question log, CSAT tied to thumbs up/down,
per-tenant LLM cost tracking, exportable reports.

## Owner decisions confirmed at kickoff

- **1.0 usage dashboard**: a **real dashboard page** in the admin
  console — charts and numbers, not just a data API. Built this phase,
  not deferred to the admin-UI backlog the way Phase 4/6's
  LLM-config/prompt-version/support-config panels were.
- **4.0 cost tracking**: **token counts plus an estimated dollar
  cost**, using a hardcoded price-per-token table per provider/model —
  not raw tokens only, and not live-fetched pricing.
- **5.0 exportable reports**: **CSV** of raw usage/conversation data,
  not a formatted PDF-style summary.

## A foundational gap this WBS had to resolve before 1.0/4.0 can start

Neither the usage dashboard nor cost tracking has anything to show
without first capturing **token counts per request** — and nothing in
this codebase captures that today. `app/core/llm_providers.py`'s
`ChatProvider.chat_completion()` currently returns a bare answer
string; every provider's real API response actually includes a usage
block (DeepSeek/OpenAI: `response["usage"]["prompt_tokens"]`/
`["completion_tokens"]`; Anthropic: `response["usage"]["input_tokens"]`
/`["output_tokens"]`), and it's being discarded today.

**This requires a real interface change**, flagged explicitly rather
than smuggled in as a side effect: `chat_completion()`'s return type
changes from `str` to a small dict, `{"content": str, "input_tokens":
int, "output_tokens": int}`. Every existing test stub provider across
`tests/test_prompt_versions.py`, `test_multiturn_memory.py`,
`test_multilanguage.py`, `test_message_feedback.py`,
`test_escalation_detection.py`, `test_escalation_completion.py`, and
`test_escalation_api.py` currently returns a bare string from
`chat_completion()` and will need updating — a real, broad but
mechanical touch, same shape as Phase 5 — 1.3's history-parameter
change (which touched 2 stub signatures; this one touches more,
because more phases have shipped since).

This is Section **0.0** below — genuinely foundational, built before
1.0 and 4.0 both, even though the master prompt doesn't list it as its
own numbered item.

## A second thing worth flagging: the pricing table will go stale

The hardcoded price-per-token table (0.0/4.0) reflects this session's
best knowledge of DeepSeek/OpenAI/Anthropic per-token pricing — it is
**not** independently verified against each provider's current pricing
page as of the actual date this is built, and provider prices change
over time. Flagged in the code itself (not just here) so the owner
knows to verify/update it periodically, the same way Phase 5's
uncapped-history risk and Phase 6's model-compliance risk were flagged
as accepted-not-guaranteed rather than presented as precise.

## Dependency order

**0.0 (token/cost capture) must come first** — 1.0's dashboard and
4.0's cost tracking both render data 0.0 produces; nothing to show
without it. 2.0 (unanswered/low-confidence log) and 3.0 (CSAT) don't
depend on 0.0 at all — they're built entirely from data Phases 5/6
already created (`message.needs_escalation`, `citation.similarity`,
`message_feedback`), so they could be built in any order relative to
0.0, sequenced after it here only because 1.0's dashboard page is a
natural place to surface all four (usage, cost, CSAT, flagged
questions) together rather than building the same admin page four
separate times. 5.0 (CSV export) goes last since it exports whichever
of the above data already exists — building it before the data model
solidifies would risk hand-designing a CSV schema before all the real
columns are in place.

## 0.0 Foundation: Token & Cost Capture

- **0.1 `ChatProvider` interface change**: `chat_completion()` returns
  `{"content": str, "input_tokens": int, "output_tokens": int}`
  instead of a bare string. Each of `DeepSeekProvider`/`OpenAIProvider`
  /`AnthropicProvider` parses its own response shape's usage block —
  no shared assumption about where usage numbers live in the JSON,
  same "each provider owns its own response shape" principle Phase 4
  — 2.2 established.
- **0.2 Pricing table**: a new `app/core/llm_pricing.py` —
  `PRICING = {"deepseek": {"deepseek-chat": {"input_per_1k": ...,
  "output_per_1k": ...}}, "openai": {...}, "anthropic": {...}}`, with
  the "verify this periodically" flag from above as a module-level
  comment. `estimate_cost(provider, model, input_tokens,
  output_tokens) -> Decimal` — falls back to a `$0` estimate with a
  logged warning for any provider/model combination not in the table
  (a tenant on a brand-new model shouldn't crash cost tracking, just
  under-report it visibly in the logs).
- **0.3 Schema**: `migrations/023_llm_usage_log.sql` — one row per
  assistant message: `tenant_id`, `message_id` (UNIQUE — one usage
  record per message, same shape as feedback/escalation's
  one-per-message tables), `provider`, `model`, `input_tokens`,
  `output_tokens`, `estimated_cost_usd DECIMAL(10,6)`, `created_at`.
- **0.4 Wire into `ask()`**: after the provider call, insert the usage
  row using the actual `input_tokens`/`output_tokens` the provider
  returned and `estimate_cost()`'s result.

## 1.0 Usage Dashboard

- **1.1 Aggregation service** (`app/services/analytics.py`): per-tenant,
  date-range-scoped queries — conversation count, message count,
  escalation count, average messages per conversation, daily message
  volume (for a trend chart).
- **1.2 Dashboard endpoint**: `GET /api/tenant/analytics/dashboard?days=30`
  (`viewer`+ — a dashboard is read-only reporting, same floor as
  prompt-version's list endpoint, not the `admin`+ floor
  live-credential surfaces need).
- **1.3 Dashboard page**: a new `templates/analytics.html` +
  `static/js/analytics.js` in the admin console — hand-rolled SVG bar/
  line charts (no external charting library dependency; this is a
  self-hosted app, and a hand-rolled SVG chart is a few dozen lines for
  the shapes this needs, not worth a new client-side dependency for).
  Surfaces usage, cost (4.0), CSAT (3.0), and the flagged-questions log
  (2.0) together on one page — the natural single "analytics" surface
  a tenant admin would look for, rather than four separate scattered
  panels.

## 2.0 Unanswered/Low-Confidence Question Log

- **2.1 No new schema** — this reuses data Phases 5/6 already created:
  `message.needs_escalation = TRUE` (Phase 6's "escalated" signal) and
  a message whose best `citation.similarity` fell below a threshold
  (a default of 0.3 is assumed here, not separately confirmed at
  kickoff — flagged the same way Phase III's cadence assumption was —
  since low-confidence-but-not-escalated is a genuinely new category
  this phase introduces, distinct from Phase 6's escalation signal).
- **2.2 Query** (`app/services/analytics.py`): messages where
  `needs_escalation = TRUE` OR the best citation similarity for that
  message is below the threshold, tagged with which reason applied (a
  message could be both).
- **2.3 Endpoint**: `GET /api/tenant/analytics/flagged-questions?days=30`
  (`viewer`+), surfaced in 1.3's dashboard page as a scannable list.

## 3.0 CSAT (tied to thumbs up/down)

- **3.1 No new schema** — `message_feedback` (Phase 5) already has
  everything needed: `CSAT = up_count / (up_count + down_count) * 100`
  over the date range.
- **3.2 Included in the 1.2 dashboard endpoint's response** rather
  than a separate endpoint — CSAT is one number alongside the other
  dashboard metrics, not its own reporting surface.

## 4.0 Per-tenant LLM Cost Tracking

- **4.1 Aggregation**: total estimated cost and a cost-by-provider/
  model breakdown from `llm_usage_log` (0.3) over the date range,
  included in the same 1.2 dashboard endpoint.
- **4.2 Surfaced in 1.3's dashboard page** as its own panel — total
  cost, and a simple breakdown table by provider/model.

## 5.0 Exportable Reports (CSV)

- **5.1 Endpoint**: `GET /api/tenant/analytics/export.csv?days=30`
  (`admin`+ — raw per-message data, including visitor content, is more
  sensitive than the aggregated dashboard numbers, so this gets the
  higher floor). One row per assistant message: `conversation_id`,
  `message_id`, `created_at`, `provider`, `model`, `input_tokens`,
  `output_tokens`, `estimated_cost_usd`, `needs_escalation`,
  `feedback_rating` (blank if none) — the natural analytics unit this
  schema already anchors everything else to (citations, feedback,
  escalation, and now usage all key off `message_id`).
- **5.2 "Download CSV" button on 1.3's dashboard page** — not a
  separate admin-UI backlog item, since it's simple and belongs
  directly on the page being built this phase anyway.

## 6.0 Testing & Validation

Same shape as every phase so far: round-by-round tests land alongside
each round above, DB-gated tests skip cleanly with no DB reachable,
plus a full-suite pass on a freshly rebuilt database once 0.0-5.0 are
done. 0.0's provider-interface change needs its own explicit pass
confirming every existing test file that mocks `chat_completion()`
still passes with the new return shape — not just new tests for new
code, a real regression risk given how many files that touches.

## 7.0 Documentation & Handoff

`docs/STATUS.md` updated per round, same as every prior phase. 1.3's
dashboard page is new admin-facing UI actually built this phase (not
backlogged), so no new backlog item — the opposite of what Phase 4/6
did with their config panels.
