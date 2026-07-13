# SupportLM — Status

> Updated at the end of every round. Read this right after
> `docs/MASTER_PROMPT.md` at the start of any session.

## Current phase

**Phase 1 — Round 6 complete (2.2: status lifecycle). 2.0 Tenant
Provisioning done. Next: 3.1 (request-scoping middleware).**

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

### Round 3 — completed 1.3
- Wrote `migrations/004_backfill_default_tenant.sql` — the one-time
  backfill (explicitly NOT safe to re-run after it completes, unlike
  001–003, since it drops `company` and tightens columns):
  1. Creates a single default tenant, folding in `company`'s
     name/profile_json if a `company` row exists.
  2. Stamps every row in the 1.2-retrofitted tables with that
     tenant's id.
  3. Links every existing `admin_user` to the default tenant via
     `tenant_user` as `role = 'owner'`. This wasn't explicit in the
     WBS wording but follows directly from 1.1's "ownership assignable
     from Phase 1" goal — without it no existing admin could pass a
     tenant-scoped check once 3.0 lands.
  4. Drops `company`.
  5. Converts `tenant_id` to `NOT NULL` on all 8 tables.
- Validated against MariaDB with two scenarios: (a) an "existing
  production" DB seeded with a `company` row, two admins, and sample
  document/conversation/category/agent rows — confirmed the tenant
  absorbed `company`'s data, both admins got linked as owners, all
  rows stamped with zero NULLs remaining, and columns are NOT NULL;
  (b) a brand-new install with no `company` row and no admins at all —
  confirmed it falls back to `'Default Tenant'` cleanly with no errors.
- Next up: 1.4 — composite `(tenant_id, ...)` indexes for hot-path
  queries (chunk search, document listing, conversation lookup).

### Round 4 — completed 1.4
- Wrote `migrations/005_tenant_scoped_indexes.sql`: tenant-led composite
  indexes on `document` (tenant_id, status) and (tenant_id,
  uploaded_at), `document_chunk` (tenant_id, document_id), `embedding`
  (tenant_id, chunk_id), `conversation` (tenant_id, last_message_at),
  `message` (tenant_id, conversation_id, created_at), and `citation`
  (tenant_id, message_id) — covering the chunk-search, document-listing,
  and conversation-lookup hot paths named in the WBS.
- Found and fixed a real multi-tenant correctness bug along the way:
  `category.slug` had a GLOBAL UNIQUE constraint, which would have
  stopped two different tenants both using a slug like 'billing'.
  Replaced it with a composite `UNIQUE (tenant_id, slug)`.
- Discovered mid-testing that MariaDB automatically repoints each
  table's tenant FK constraint onto the new tenant-led composite index
  (dropping the old single-column FK index from 1.2) as soon as the
  composite is added — which breaks a DROP-then-ADD idempotency pattern
  on re-run, since the composite becomes FK-load-bearing. Switched to
  `ADD INDEX IF NOT EXISTS` instead; verified 3 consecutive re-runs
  succeed with no errors.
- Validated against MariaDB: full 001→005 chain applies cleanly on a
  fresh DB; confirmed two different tenants can both use slug
  `billing` while a duplicate within the same tenant is correctly
  rejected; confirmed the exact composite index set landed on all 7
  affected tables via `SHOW INDEX`.
- **1.0 Data Model & Schema is now fully done (1.1–1.4).**
- Next up: 2.1 — tenant creation flow (programmatic way to stand up a
  new tenant, working end-to-end before anything else in this phase
  is verifiable).

### Round 5 — completed 2.1
- Wrote `scripts/create_tenant.py`, mirroring the existing
  `create_admin.py` script convention (argparse CLI, `get_conn()`,
  clean exits on known error cases rather than raw tracebacks).
- Creates a `tenant` row and, optionally, links an owner via
  `--owner-email` (+ `--owner-password` if that admin doesn't exist
  yet — reuses the admin and just links it if it does, which is how
  one admin ends up owning multiple tenants).
- A full admin UI for this is out of scope per the WBS; a platform
  API endpoint is deferred too, since there's no platform-admin auth
  model yet to guard it with (today's `admin_user`/sessions are
  tenant-scoped once RBAC lands in Phase 2) — a script is the
  appropriate "not full UI" path for this phase.
- Validated end-to-end against a real MariaDB instance seeded via
  the full 001→005 migration chain: created a tenant with a new
  owner; created a second tenant reusing that same admin as owner
  (confirming one admin can own multiple tenants via `tenant_user`);
  created a tenant with no owner at all; and confirmed clean
  (non-crashing) error messages for a duplicate slug, an invalid
  slug, and `--owner-email` given for a brand-new admin without
  `--owner-password`.
- Next up: 2.2 — tenant status lifecycle (active/suspended/trial
  enforcement on every tenant-scoped route).

### Round 6 — completed 2.2
- Wrote `app/core/tenant_access.py`: `enforce_active(status)` is a
  pure, DB-free function deciding whether a status should block a
  request ('suspended' → 403, 'active'/'trial' → allowed, anything
  else → ValueError); `get_tenant_status(tenant_id)` does the one-row
  lookup; `enforce_tenant_active(tenant_id)` combines both (404 if the
  tenant doesn't exist, 403 if suspended).
- Important ordering note: there is no per-request tenant resolution
  yet — that's 3.1, which comes after all of 2.0 per the WBS's own
  dependency graph. So this round could not literally wire status
  checks into "every tenant-scoped route" yet (there's nothing that
  currently resolves which tenant a request belongs to). Instead this
  delivers the tested enforcement primitive 3.1's middleware will call
  once it resolves `tenant_id` per request — the same "build the piece
  before its consumer exists" pattern used for `tenant_user` in 1.1.
- Wrote `scripts/set_tenant_status.py` (active/suspended/trial
  transitions by slug) so the lifecycle states are actually reachable,
  not just structurally present on the `tenant` table.
- Added `tests/test_tenant_access.py` (4 unit tests on `enforce_active`,
  no DB needed) — full suite passes (6/6, including the pre-existing
  chunking tests).
- Validated the DB-touching pieces against a real MariaDB instance:
  suspended a tenant via the script, confirmed
  `enforce_tenant_active` correctly 403s it and correctly allows a
  'trial' tenant, confirmed a nonexistent tenant_id 404s, confirmed
  invalid status/unknown slug fail cleanly via the script, then
  reactivated the tenant.
- **2.0 Tenant Provisioning is now fully done (2.1–2.2).**
- Next up: 3.1 — request-scoping middleware/dependency (resolves
  `tenant_id` per request; decide subdomain vs path param vs API key).

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
