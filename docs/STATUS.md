# SupportLM — Status

> Updated at the end of every round. Read this right after
> `docs/MASTER_PROMPT.md` at the start of any session.

## Current phase

**Phase 1 — Round 9 complete (3.2: query retrofit). 3.0 Data Isolation
Enforcement done. Next: 3.3 (automated cross-tenant access tests).**

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

### Round 7 — completed 3.1
- Wrote `app/core/tenant_scope.py`, the request-scoping mechanism the
  WBS calls for. Decided the resolution source (WBS 3.1 required this
  be decided, not deferred): **path param** (`{tenant_slug}` in the
  route path), not subdomain or API key. Subdomain routing needs
  DNS/reverse-proxy vhost config that doesn't exist in this deployment
  and is infra work explicitly out of scope (`MASTER_PROMPT.md` Section
  2.8). API keys are exactly what Phase 2 introduces ("API keys for
  programmatic access") — building a per-tenant key system now would
  duplicate that a phase early.
- Two dependencies, matching the app's two caller types:
  - `resolve_tenant(tenant_slug)` — anonymous routes (chat widget).
    slug -> tenant_id, 404 unknown slug, 403 suspended (reuses 2.2's
    `enforce_active`).
  - `resolve_tenant_for_admin(tenant_slug, admin_id)` — admin-session
    routes. Same checks, plus 403 unless the logged-in admin is linked
    to that tenant via `tenant_user`. Needed because 2.1 made "one
    admin owns multiple tenants" valid, so `require_admin` alone can't
    imply which tenant a request means — without this check, admin A
    could read tenant B's data just by typing B's slug into the URL.
- Scope note, same pattern as round 6: this round builds and validates
  the mechanism only. It is not yet wired into any real route — that
  audit-every-query work is 3.2, which the WBS places after 3.1.
- Validated against a real MariaDB instance (full 001->005 chain) using
  a throwaway FastAPI app + TestClient exercising both dependencies:
  confirmed active-tenant success (200), unknown slug (404), suspended
  tenant (403) for the anonymous path; and for the admin path, a linked
  owner succeeds (200), an admin with no link to that tenant is blocked
  (403), no session cookie is blocked (401), an unknown slug 404s, and
  a suspended tenant blocks even an admin who *is* linked to it (403,
  suspension checked before membership) — confirming suspension always
  wins regardless of who's asking.
- Full regression pass: `pytest tests/ -q` still 6/6 (no existing tests
  touched this round; nothing to break since nothing was wired in yet).
- Next up: 3.2 — audit and update every existing query in
  `app/services/*` and `app/api/*` to filter by tenant_id, wiring in
  `resolve_tenant`/`resolve_tenant_for_admin` on the actual routes
  (chat, documents, categories, admin dashboard). This is the round
  most likely to reveal missed spots per the WBS's own warning — treat
  it as a full checklist pass, not a quick one.

### Round 8 — wired 3.1's dependencies into every route
- **Process note, for the record:** two different sessions independently
  built 3.1 and both pushed. The other session's `tenant_scope.py`
  (round 7 above) is the one that stuck — it catches a real gap the
  other implementation didn't: without the `tenant_user` membership
  check in `resolve_tenant_for_admin`, an admin who legitimately owns
  tenant A could visit `/t/{tenant-B-slug}/admin` and pass the tenant
  gate for tenant B too, since a valid session alone doesn't say which
  tenant it's for. Reconciled by keeping `tenant_scope.py` as-is and
  building the route-wiring layer on top of it.
- Wired `resolve_tenant` / `resolve_tenant_for_admin` into every actual
  route, matching what each one really needs (not a blanket dependency):
  - `chat.py`, `auth.py`: router-level `resolve_tenant` (anonymous —
    login has no session yet to check membership against, and rejecting
    it would be a different bug).
  - `documents.py`: router-level `resolve_tenant_for_admin` (all 4
    routes are admin-only); dropped the now-redundant per-route
    `require_admin` (membership check needs `require_admin`'s result
    internally anyway, so it's still enforced, just via one dependency
    instead of two).
  - `categories.py`: mixed per-route — `GET` (public listing) uses
    `resolve_tenant`; `POST`/`DELETE` (writes) use
    `resolve_tenant_for_admin`.
  - `main.py`: both routers and the two page routes (`/t/{slug}/`,
    `/t/{slug}/admin`) moved under `/t/{tenant_slug}`. The admin *page*
    route deliberately uses `resolve_tenant`, not the admin variant —
    it just serves the login-form/dashboard HTML shell; requiring a
    valid session to view it would mean you couldn't reach the login
    form. Bare `/` now 404s pointing at the tenant-scoped shape.
- Updated `templates/chat.html`/`admin.html` to inject
  `window.TENANT_SLUG`, and `static/js/chat.js`/`admin.js` to prefix
  every fetch call with `/t/${TENANT_SLUG}` (chat send, login, logout,
  categories, documents, upload) — the frontend actually still works
  end-to-end under the new URL scheme, not just the backend routes.
- Validated against a real MariaDB-backed app via `TestClient`,
  including the specific scenario this reconciliation exists for:
  logged in as an admin linked to `acme-corp` and `beta-inc` — both
  succeed (200); the same session against `no-owner-yet` (not linked)
  correctly 403s with "You do not have access to this tenant." on both
  a read and a write route. Also re-confirmed: unscoped `/` → 404,
  unknown slug → 404, suspended tenant blocks anonymous *and* admin
  routes (including a linked admin), no-session admin routes → 401,
  active/trial tenants render correctly with the right `TENANT_SLUG`.
- Added `tests/test_tenant_resolution.py` (8 tests, DB-backed, skips
  cleanly with no DB configured) covering all of the above, including
  the cross-tenant block and suspension-overrides-membership cases.
  Full suite: 14/14 passing.
- One unrelated thing surfaced during testing, not a regression: `POST
  /api/chat` 500s in this sandbox because `sentence_transformers` isn't
  installed here (it's a lazy import in `llm_client.py`, real installs
  have it per `requirements.txt`) — tenant resolution itself ran
  correctly and reached the handler before hitting that unrelated
  missing dependency.
- **3.1 is now fully done, including the route-wiring the WBS's own
  ordering had deferred to 3.2.** What's left for 3.2 specifically:
  the actual SQL `WHERE tenant_id = %s` filtering inside
  `app/services/*`/`app/api/*` query bodies — right now the gate is
  correct (wrong tenant can't get past the dependency), but a query
  that *does* get through, e.g. `list_documents()` for a legitimate
  admin, still returns every tenant's documents, not just theirs. That
  data-filtering work is next.

### Round 9 — completed 3.2
- Full checklist pass (per the WBS's own warning that this item is
  "most likely to reveal missed spots") over every `cur.execute(...)`
  in `app/api/*` and `app/services/*`:
  - `vector_store.py`: **the core bug this round exists to fix** —
    `MySQLVectorStore.search()` had no tenant filter at all, so any
    tenant's question could get answered (and cited!) using another
    tenant's private knowledge base. Now filters on `e.tenant_id`.
  - `chat.py` service: `ask()` now takes `tenant_id`, threads it onto
    every `conversation`/`message`/`citation` insert, and — found
    while doing this, not asked for — guards against cross-tenant
    conversation hijacking: if a caller supplies a `conversation_id`
    belonging to a *different* tenant, it's silently discarded and a
    fresh one is issued instead of writing into the other tenant's
    thread.
  - `ingestion.py`: `ingest_document()` now reads `tenant_id` off the
    `document` row itself and stamps it onto every `document_chunk`/
    `embedding` row it writes (both are `NOT NULL` since 1.3).
  - `documents.py`: all 4 routes now filter/scope by `tenant_id`.
    Found and fixed two real holes while doing this: `reindex_document`
    and `delete_document` previously operated on `document_id` alone
    with no ownership check — an admin could reindex or **delete**
    another tenant's document (and reindex would `DELETE FROM
    document_chunk WHERE document_id = %s` with no tenant filter,
    which would have deleted the *other* tenant's chunks). Both now
    404 if the `document_id` doesn't belong to the resolved tenant,
    checked *before* any mutation. Also added a check that a supplied
    `category_id` belongs to the same tenant, rejecting cross-tenant
    category assignment on upload (400).
  - `categories.py`: `list`/`create`/`delete` all scoped;
    `delete_category` now 404s instead of silently no-op'ing on a
    cross-tenant or nonexistent id.
  - `auth.py`: intentionally left unscoped — `admin_user` isn't
    tenant-owned (one admin can belong to several tenants via
    `tenant_user`), so login/logout correctly query it globally by
    email/session, not by tenant.
- Validated well beyond "written and assumed": a direct DB-level test
  with two tenants holding *identical* embedding vectors, confirming
  each tenant's search only ever returns its own chunk; `ingest_document`
  tested with `embed_text` mocked, confirming tenant_id lands on every
  chunk/embedding row; full `TestClient` runs proving a second tenant
  can't see, reindex, or delete a first tenant's documents/categories
  by id-guessing, and can't upload against the first tenant's
  `category_id`; and a direct test of the conversation-hijack guard —
  tenant Q handed tenant P's `conversation_id` gets silently issued a
  new one, zero messages leak into P's thread, and legitimate
  same-tenant conversation continuation still works.
- Added `tests/test_query_isolation.py` (4 tests, DB-backed, skips
  cleanly with no DB) covering all of the above as permanent
  regression tests, not just one-off validation scripts. Caught my own
  bug before pushing: the category-isolation test wasn't idempotent —
  reusing the same test tenant across runs collided with 1.4's new
  per-tenant unique slug constraint on the second run. Fixed by having
  the test clean up its own fixture rows first; reran the full suite
  3x consecutively against the same DB to confirm. Full suite: 18/18
  passing, repeatably.
- Also fixed while here: a small doc slip from a previous round — the
  "Open decisions" header below had been accidentally dropped during
  an earlier edit; restored it in this same commit.
- **3.0 Data Isolation Enforcement is now fully done (3.1–3.2).** Next
  is 3.3 — automated cross-tenant access tests as the *permanent*
  regression net for 3.2 going forward (this round's tests cover what
  I thought to check; 3.3 is about making that coverage systematic
  rather than ad hoc).

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
