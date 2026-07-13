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

### Round 1 — completed 1.1
- Drafted and confirmed tenant/org schema proposal at
  `docs/schema/1.1-tenant-schema-proposal.md`: new `tenant` and
  `tenant_user` tables, `company` to be folded into `tenant` (data
  move happens in the 1.3 backfill, not here).
- Wrote `migrations/002_tenant_org.sql` (creates `tenant`, `tenant_user`
  only — `company` and existing tables untouched, that's 1.2/1.3).
- Validated against a real MariaDB instance: 001 → 002 apply cleanly
  on a fresh DB, `uq_tenant_admin` rejects duplicate
  (tenant_id, admin_id) pairs, `ON DELETE CASCADE` from `tenant` to
  `tenant_user` confirmed.
- Next up: 1.2 — retrofit `tenant_id` onto existing tables.

### Round 2 — completed 1.2
- Wrote `migrations/003_retrofit_tenant_id.sql`: adds a flat, nullable
  `tenant_id` column (FK -> `tenant(id)` ON DELETE CASCADE) to
  `document`, `document_chunk`, `embedding`, `category`, `conversation`,
  `message`, `citation`, `agent` — one migration per proposal's
  denormalize-not-join decision from 1.1.
- Nullable is intentional: no tenant data exists to stamp rows with
  yet. 1.3's backfill creates the default tenant, stamps every
  existing row, then converts these columns to `NOT NULL`.
- Composite `(tenant_id, ...)` indexes for hot-path queries are 1.4,
  not this migration — each FK here only gets its own single-column
  index for free.
- Validated against a real MariaDB instance: 001 → 002 → 003 apply
  cleanly on a fresh DB, migration 003 is idempotent (safe to re-run),
  and every table's FK/column shape was inspected directly via
  `SHOW CREATE TABLE`.
- Next up: 1.3 — backfill migration (default tenant + stamp existing
  rows + fold `company` into `tenant` + convert `tenant_id` to
  `NOT NULL`).

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
