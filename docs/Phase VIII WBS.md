# Phase 8 WBS — Admin, Ops & Webhooks

> Scope source: `docs/MASTER_PROMPT.md` Section 3, "Phase 8" — the
> **final phase**. Nothing here expands that scope; this file breaks
> it into buildable, ordered rounds the way `docs/Phase I-VII WBS.md`
> did for their phases.

Phase 8 scope, verbatim from the master prompt: audit log (uploads/
edits/deletes/admin logins), rate limiting & abuse protection on
`/api/chat`, agent/bot configuration UI (tone, name, escalation
rules), health/status page. Plus webhooks (new conversation,
escalation, low-confidence answer) — the only integration in scope.

## Owner decisions confirmed at kickoff

- **2.0 rate limiting**: **combined per-IP AND per-tenant** limits
  together — a single IP can't flood one tenant, and a single tenant's
  aggregate traffic (many visitors) is capped too, independently.
- **3.0 agent/bot config**: **just name + a freeform tone/personality
  field**, merged into the system prompt — not a structured
  escalation-threshold override or custom-rules composer.
- **5.0 webhooks**: **HTTP POST with retries (a few attempts with
  backoff) and delivery logging** — not fire-and-forget, not
  HMAC-signed.

## Two things this WBS had to resolve, not just ask about

**Agent name is already configurable — just not via a UI.**
`tenant_branding.agent_name` has existed since Phase 1 (`006_tenant_
branding.sql`), set today only via `scripts/set_tenant_branding.py`
(explicitly documented there as "a full admin UI is out of scope for
this phase" — that phase, not this one). This phase adds the missing
piece: a **tone** column alongside it, and a real admin UI + endpoint
for both — the script remains valid but is no longer the only path.

**Webhook retries need a mechanism, and this project has no job
queue.** `docs/MASTER_PROMPT.md`'s own out-of-scope list explicitly
excludes a background job queue. Retries with backoff can't block the
visitor's `/api/chat` response waiting on a possibly-slow or failing
webhook URL. Resolved by using FastAPI's `BackgroundTasks` — deferred,
in-process execution after the response is already sent, **not** a
persistent, durable queue. Flagged explicitly: a background task's
retry loop is lost if the app process restarts mid-retry (no
persistence across restarts), which is an accepted limitation of
staying within "no job queue," not an oversight. `webhook_delivery_
log` (5.1) still gives an admin visibility into what happened even
though the retry loop itself isn't durable.

## Dependency order

1.0 (audit log), 2.0 (rate limiting), 3.0 (agent config), and 4.0
(health page) are all independent of each other and of 5.0 —
built in the master prompt's own listed order. **5.0 (webhooks) goes
last** since its three trigger points (new conversation, escalation,
low-confidence answer) all live inside `ask()`/`complete_escalation()`,
which is calmer to wire into once nothing else in this phase is
still touching `chat.py`.

## 1.0 Audit Log

- **1.1 Schema**: `migrations/024_audit_log.sql` — `audit_log`
  (`tenant_id`, `admin_id`, `action VARCHAR(50)`, `entity_type
  VARCHAR(50)`, `entity_id INT NULL`, `detail TEXT NULL`, `ip_address
  VARCHAR(45)` — long enough for IPv6, `created_at`). Scoped exactly to
  the master prompt's literal list — uploads/edits/deletes/admin
  logins — not every admin action across the whole system (a
  temptation this table's existence invites, but scope creep worth
  resisting).
- **1.2 Logging helper**: `app/services/audit.py` —
  `log_audit_event(tenant_id, admin_id, action, entity_type,
  entity_id, detail, request)` — called from the exact endpoints the
  master prompt names: `documents.py`'s upload/delete/review-state-
  change, and `auth.py`'s successful login.
- **1.3 Endpoint**: `GET /api/tenant/audit-log?days=30` (`admin`+ —
  who-did-what is sensitive, same floor as CSV export).
- **1.4 Admin UI panel**: added directly to `admin.html`/`admin.js`
  (Phase 7 shifted this project toward building real UI in-phase
  rather than backlogging config panels — same pattern continues
  here), a simple scrollable recent-activity list.

## 2.0 Rate Limiting & Abuse Protection on `/api/chat`

- **2.1 Schema**: `migrations/026_rate_limit_bucket.sql` —
  `rate_limit_bucket` (`scope_type ENUM('ip','tenant')`, `scope_key
  VARCHAR(100)`, `window_start DATETIME`, `request_count INT`,
  composite PK on all three) — a **fixed 1-minute window**, not a
  sliding one, for simplicity. `INSERT ... ON DUPLICATE KEY UPDATE
  request_count = request_count + 1` then a read-back, same atomic
  pattern as Phase 6's `sr_sequence` — safe under concurrent requests
  hitting the same window.
- **2.2 Limits** (defaults, not yet admin-configurable — flagged as a
  reasonable follow-up, not built this phase to keep scope contained):
  **20 requests/minute per IP**, **100 requests/minute per tenant**
  (aggregate across all that tenant's visitors).
- **2.3 IP resolution assumption**: uses `request.client.host`,
  preferring the first entry of `X-Forwarded-For` if present (common
  reverse-proxy pattern). **Assumed, not confirmed** — flagged the
  same way Phase III's cadence assumption was — since whether this
  app sits behind a reverse proxy in production affects whether
  `X-Forwarded-For` is trustworthy at all (a raw client could forge
  it if there's no proxy actually stripping/setting it).
- **2.4 Enforcement**: a new `app/core/rate_limit.py`,
  `enforce_rate_limit(tenant_id, request)` — checks and increments
  both buckets, raises `HTTPException(429)` if either is exceeded.
  Applied **only** to `POST /api/chat` per the master prompt's literal
  scope — not the feedback/escalate/transcript endpoints.

## 3.0 Agent/Bot Configuration UI

- **3.1 Schema**: `migrations/027_tenant_agent_tone.sql` adds
  `tenant_branding.tone` (`TEXT NULL`) — living alongside
  `agent_name` on the same table rather than a new one, since both are
  the same "voice" concept Phase 1 already anchored there.
- **3.2 Merge into system prompt**: `app/services/chat.py`'s `ask()`
  appends the tone text (if set) to the system prompt — same
  "appended after whichever prompt is already in play" placement
  pattern Phase 5's language instruction and Phase 6's escalation
  instruction both used, so a tenant's custom Phase 4 prompt doesn't
  need to know about tone for this to work.
- **3.3 Endpoint**: `GET`/`POST /api/tenant/agent-config` (`admin`+) —
  reads/writes `tenant_branding.agent_name` and `.tone` together (this
  endpoint supersedes `scripts/set_tenant_branding.py` for these two
  fields specifically; the script remains valid for
  `display_name`/`logo_url`/`accent_hex`, which stay out of this
  phase's scope).
- **3.4 Admin UI panel**: name + tone textarea, added directly to
  `admin.html`/`admin.js`.

## 4.0 Health/Status Page

- **4.1 `/health` extended**: currently returns a bare `{"status":
  "ok"}` with no actual check behind it. Extended to verify DB
  connectivity (a real `SELECT 1`) and report `{"status": "ok"|
  "degraded", "database": "ok"|"unreachable"}` — still fast, still a
  liveness check suitable for automated monitoring, just an honest one
  now instead of a hardcoded constant.
- **4.2 `/status` page**: a new, public (no tenant scoping, no auth —
  a status page's entire purpose is being checkable without
  credentials), simple HTML page showing the same health data in
  human-readable form. Separate from `/health` (machine-readable,
  fast, for uptime monitors) rather than overloading one endpoint for
  both audiences.

## 5.0 Webhooks

- **5.1 Schema**: `migrations/027_webhooks.sql` — `tenant_webhook_
  config` (`tenant_id` PK, `url NOT NULL`) — **one URL per tenant**,
  receiving all three event types with an `event` field in the
  payload distinguishing them (not three separate URLs) — and
  `webhook_delivery_log` (`tenant_id`, `event_type`, `payload TEXT`,
  `url`, `attempt_count`, `status ENUM('delivered','failed')`,
  `last_error TEXT NULL`, `created_at`, `delivered_at NULL`) for the
  visibility the owner's "delivery logging" decision calls for.
- **5.2 Delivery function**: `app/services/webhooks.py` —
  `deliver_webhook(tenant_id, event_type, payload)` — up to 3 attempts
  with backoff (1s, 2s, 4s) via plain `httpx.post()` calls with a
  short timeout each; writes one `webhook_delivery_log` row per
  logical delivery attempt sequence (not one row per HTTP call), final
  `status` reflecting whether any attempt succeeded. A tenant with no
  `tenant_webhook_config` row simply has nothing to deliver to — no
  error, no log row, silently a no-op (same "no row = not configured,
  not broken" contract every other optional per-tenant config in this
  project uses).
- **5.3 Dispatch via `BackgroundTasks`**: `app/api/chat.py`'s
  `post_chat` and `post_escalate` both gain a `background_tasks:
  BackgroundTasks` parameter, calling `background_tasks.add_task
  (deliver_webhook, ...)` for whichever events actually fired — never
  calling `deliver_webhook()` inline in the request path, so a slow or
  down webhook URL never adds latency to the visitor's actual chat
  response.
- **5.4 Trigger points**: **new_conversation** — `ask()` already knows
  whether `history` was empty (Phase 5 — 1.1); empty history means
  this is the first message of a new conversation. **escalation** —
  fires from `complete_escalation()`'s success path (`app/services/
  escalation.py`), not from the model's `[ESCALATE]` signal alone —
  an actually-created SR with a real SR number is the more meaningful,
  actionable event for a tenant's downstream systems than "the model
  merely flagged uncertainty." **low_confidence_answer** — `ask()`
  computes this the same way Phase 7's flagged-questions query does
  (best citation similarity below `analytics.LOW_CONFIDENCE_THRESHOLD`,
  reusing that same constant rather than a second hardcoded number)
  and includes it in a new `webhook_events` list on `ask()`'s return
  dict, which the endpoint layer turns into actual `add_task()` calls
  — keeping `ask()` itself free of any FastAPI-specific
  `BackgroundTasks` dependency, so it stays as easily unit-testable as
  it already is.

## 6.0 Testing & Validation

Same shape as every phase so far: round-by-round tests land alongside
each round above, DB-gated tests skip cleanly with no DB reachable,
plus a full-suite pass on a freshly rebuilt database once 1.0-5.0 are
done. 2.0's rate limiter and 5.0's webhook retries both need a test
confirming they behave correctly under the "many rapid calls in a
short window" shape their real failure mode would actually take, not
just a single call each.

## 7.0 Documentation & Handoff

`docs/STATUS.md` updated per round, same as every prior phase. This
is the **last phase** in `docs/MASTER_PROMPT.md` — once 1.0-6.0 are
done, `docs/STATUS.md` should say so plainly rather than defaulting to
"start the next phase" language that no longer has a next phase to
point to.
