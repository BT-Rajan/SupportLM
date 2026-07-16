# Phase 6 WBS — Escalation to Service Request (SR)

> Scope source: `docs/MASTER_PROMPT.md` Section 3, "Phase 6". Nothing
> here expands that scope; this file breaks it into buildable, ordered
> rounds the way `docs/Phase I-V WBS.md` did for their phases.

Phase 6 scope, verbatim from the master prompt: when the assistant
can't help, escalate to a Service Request — generate a unique SR
number, attach the full chat history, and send email notifications to
**both** the company (support inbox) and the end user with the SR
number and transcript.

## Owner decisions confirmed at kickoff

- **1.0 trigger**: **automatic only** — the model itself signals when
  it can't answer from the provided context; escalation is never a
  visitor-initiated button. No manual "talk to a human" affordance in
  this phase's scope.
- **2.0 SR number format**: **date-prefixed sequential**, e.g.
  `SR-20260716-0007`.
- **3.0 support inbox source**: **per-tenant, configured by the admin,
  required** — not a global fallback. If a tenant hasn't set a support
  email, escalation cannot complete for that tenant (see the design
  note below for exactly what "cannot complete" means in practice).

## A design gap this WBS had to resolve, not just ask about

The master prompt requires emailing "the end user," but this widget is
**fully anonymous** — no visitor email is collected upfront, only
opt-in at the end of a chat via Phase 2's transcript-email feature.
Escalation can't email an address it doesn't have.

**Assumed, not separately confirmed at kickoff** (flagging this
explicitly, same as Phase III WBS's cadence assumption): when the model
signals it can't help, the widget asks the visitor for their email
*before* the SR is created and both notification emails go out — a
short, one-time prompt, not a full account/login flow, staying
consistent with the "no SSO, no end-user login" scope decision already
established for this project. If the visitor declines/abandons that
prompt, no SR is created and no emails are sent — an SR without a way
to reach the visitor back would be a support ticket the company
receives with a chat number and no reply channel, which doesn't serve
the actual purpose of this feature.

## Dependency order

1.0 (detecting the model's escalation signal) has to exist before
anything else — 2.0 (SR generation) and 3.0 (the dual email) are both
downstream of "an escalation was actually triggered." 2.0 before 3.0
since 3.0's emails need an SR number and transcript that 2.0 produces.

## 1.0 Escalation Detection

- **1.1 System prompt signal**: appended to the system prompt (same
  place Phase 5's language instruction gets appended — after whichever
  prompt is already in play, default or tenant-custom), a new
  instruction: if the provided context doesn't contain enough to
  answer the question, end the response with a literal marker line,
  `\n\n[ESCALATE]`, and nothing else about formatting. This is a
  **text-marker convention**, not structured/function-calling output —
  consistent with how all three providers are wired today (plain
  chat-completion text, no tool-calling schema in this architecture).
  Accepted limitation, not silently glossed over: this relies on model
  compliance, and different providers/models may follow it with
  different reliability — there's no hard guarantee here, same
  category of "accepted, not fixed" risk Phase 5's WBS flagged for
  uncapped history.
- **1.2 Detect + strip in `ask()`**: after the provider call, check the
  raw answer for the trailing marker. If present: strip it from the
  text actually shown to the visitor (the marker itself is an internal
  signal, never visitor-facing), and set `needs_escalation: True` on
  `ask()`'s return dict — no SR is created yet at this point.
- **1.3 Widget reacts**: `chat.js` sees `needs_escalation: true` on a
  response and shows a distinct prompt (not a normal assistant bubble)
  asking for the visitor's email, per the design-gap resolution above.

## 2.0 SR Generation

- **2.1 Schema**: `migrations/020_service_requests.sql` — a
  `service_request` table (`sr_number` UNIQUE, `tenant_id`,
  `conversation_id`, `message_id` — the assistant message that
  triggered escalation, `visitor_email`, `status
  ENUM('open','closed')` default `'open'`, `created_at`) and a small
  `sr_sequence` counter table (`tenant_id`, `date`, `next_seq`) to
  generate collision-free numbers under concurrency — an `INSERT ...
  ON DUPLICATE KEY UPDATE next_seq = next_seq + 1` then read-back,
  not a `COUNT(*) + 1` (which races under concurrent escalations for
  the same tenant on the same day).
- **2.2 SR number generation**: `generate_sr_number(tenant_id)` in a
  new `app/services/escalation.py` — `SR-{YYYYMMDD}-{4-digit,
  zero-padded, per-tenant-per-day sequence}`. Sequence resets daily,
  scoped per tenant (Tenant A's and Tenant B's `SR-20260716-0001` on
  the same day are two different, unrelated tickets — no cross-tenant
  meaning to a shared sequence, and each tenant's own numbers stay
  small and readable).
- **2.3 Chat history attachment**: reuses Phase 2's existing
  `build_transcript()` from `app/services/transcript_email.py` rather
  than duplicating message-history logic — the transcript is built
  fresh from `conversation_id` at send time (messages are append-only
  and never edited/deleted, so this is equivalent to a stored
  snapshot without actually duplicating the data).

## 3.0 Dual Email Notification

- **3.1 Schema**: `migrations/021_tenant_support_email.sql` adds
  `tenant_support_config` (`tenant_id` PK, `support_email NOT NULL` —
  intentionally NOT nullable the way `tenant_llm_config`'s per-tenant
  overrides are, since this phase's kickoff decision was "required,"
  not "override with a fallback"; a tenant simply has no row until an
  admin sets one).
- **3.2 Escalation completion flow**: when the visitor submits their
  email (from 1.3's prompt), a new endpoint checks whether this
  tenant has a `tenant_support_config` row. **If not**: escalation
  does NOT silently half-succeed — no SR is created, and the visitor
  sees a plain, honest message that a human follow-up isn't available
  for this tenant right now (not an internal config error dumped to an
  anonymous visitor, but not a fake "ticket created!" either). **If
  yes**: create the SR (2.0), then send two emails — one to the
  tenant's `support_email` and one to the visitor's just-submitted
  address — both containing the SR number and the transcript.
- **3.3 Admin endpoint**: `app/api/support_config.py` —
  `GET`/`POST /api/tenant/support-config` (`admin`+, same floor as
  every other live-credential-adjacent config surface this project has
  built: LLM config, prompt versioning's activate). Admin UI panel
  deferred to the same backlog as Phase 4's LLM-config/prompt-version
  panels — not built ad-hoc this phase, consistent with that
  established pattern.
- **3.4 Endpoint**: `POST /api/chat/{message_id}/escalate` in
  `app/api/chat.py` — anonymous, same auth-free surface as
  `post_chat`/`post_transcript`/the feedback endpoint. Body:
  `{"email": "..."}`. Validates the message belongs to this tenant,
  is the specific assistant message that actually signaled
  `needs_escalation` (not just any assistant message — reusing another
  message's id here shouldn't be able to manufacture an SR that was
  never actually triggered), and that no SR already exists for this
  message (an escalation, like feedback, happens once per triggering
  message — no re-submission).

## 4.0 Testing & Validation

Same shape as every phase so far: round-by-round tests land alongside
each round above, DB-gated tests skip cleanly with no DB reachable,
plus a full-suite pass on a freshly rebuilt database once 1.0-3.0 are
done.

## 5.0 Documentation & Handoff

`docs/STATUS.md` updated per round, same as every prior phase. The
admin UI panel for 3.3 is a new backlog item, tracked alongside the
existing LLM-config/prompt-version panels — not a separate list, the
same one.
