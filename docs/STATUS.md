# SupportLM — Status

> Updated at the end of every round. Read this right after
> `docs/MASTER_PROMPT.md` at the start of any session.

## Current phase

**Phase 1 — Round 1 in progress (1.1: tenant/org schema design).**

## Phase progress

| Phase | Name                                   | Status      |
|-------|-----------------------------------------|-------------|
| 1     | Multi-tenancy & Org Foundation           | In progress |
| 2     | Access Control & Anonymous-Chat Email    | Not started |
| 3     | Knowledge Base Management                | Not started |
| 4     | Retrieval & Answer Quality                | Not started |
| 5     | Conversation Experience                   | Not started |
| 6     | Escalation to Service Request (SR)        | Not started |
| 7     | Analytics & Reporting                     | Not started |
| 8     | Admin, Ops & Webhooks                     | Not started |

## Round log

### Round 0 — Planning
- Defined enterprise transformation scope across 8 phases (see
  `docs/MASTER_PROMPT.md` Section 3).
- Established `docs/DESIGN_SYSTEM.md` from the existing chat UI tokens
  as the canonical standard for every future screen.
- No application code changed this round.

### Round 1 — completed 1.1 (proposal stage)
- Drafted tenant/org schema proposal at
  `docs/schema/1.1-tenant-schema-proposal.md`: new `tenant` and
  `tenant_user` tables, and a recommendation to fold the existing
  `company` singleton table into `tenant` (its `profile_json` moves
  over, `company` is dropped) rather than carry two parallel
  "owner" concepts into Phase 2.
- No migration SQL written yet — per 1.1's deliverable, this is a
  proposal awaiting confirmation before 1.2 starts.

## Open decisions / things to confirm before Phase 1 starts

- Multi-tenant isolation strategy: separate DB schema per tenant vs.
  shared schema with `tenant_id` row-level scoping. Recommendation to
  bring to Phase 1 kickoff: shared schema + `tenant_id` (simpler
  migrations, fine at current scale) unless the owner wants hard
  isolation for compliance reasons — flagged here, not yet decided.
- Usage tiers/plan limits: need the actual tier names/limits (e.g. doc
  count, messages/month, seats) before building enforcement — currently
  just listed as in-scope, not specified.
- Per-tenant branding: confirm whether this replaces the current
  hardcoded "Support" header or sits alongside a platform-default theme
  for tenants who don't customize.

## Next action

Start Phase 1, Round 1: multi-tenant schema design (tenant/org tables,
`tenant_id` scoping plan for existing `document`, `document_chunk`,
`conversation`, `message`, `citation` tables) — proposal first, then
migration + code once confirmed.
