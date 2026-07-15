# SupportLM — Status

> Updated at the end of every round. Read this right after
> `docs/MASTER_PROMPT.md` at the start of any session.

## Current phase

**Phase 4 — Round 23 complete. 2.0 Multi-LLM Provider Support done
(2.1-2.4; admin UI panel tracked as backlog alongside the existing
admin console redesign item, not built this round). 3.0 Prompt
Versioning is next.** Phase 3 is marked complete per owner
confirmation — see the Round 21 note below for what this session
could and couldn't independently verify.

## Phase progress

| Phase | Name                                   | Status      |
|-------|-----------------------------------------|-------------|
| 1     | Multi-tenancy & Org Foundation           | Complete (6.0 skipped by owner decision) |
| 2     | Access Control & Anonymous-Chat Email    | Complete    |
| 3     | Knowledge Base Management                | Complete (per owner confirmation; 1.0-6.0 build not in this repo's round log — see Round 21 note) |
| 4     | Retrieval & Answer Quality                | In progress (planning) |
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

### Round 10 — completed 3.3
- Did the gap analysis first rather than re-testing what 3.2 already
  covers well. Mapped all 8 tenant-scoped tables against existing test
  coverage (documented as a table in the new file's own docstring so
  it stays discoverable, not just in this log):
  - `document`, `document_chunk`, `embedding`, `category`,
    `conversation`, `message` — already covered by
    `test_query_isolation.py`. Not duplicated here.
  - `citation` — gap. Prior tests confirmed search never *returns* the
    wrong tenant's chunk, but nothing asserted that a citation row's
    own `tenant_id` actually matches the chunk it references — a
    weaker, more direct correctness property that could in principle
    fail even if search itself is correct (e.g. a future refactor that
    passes the wrong tenant_id into the citation INSERT).
  - `agent` — no route or service reads/writes it yet beyond the
    column existing since 1.2/1.3 (no agent CRUD, branding isn't built
    until 4.1). Nothing at the application layer to test yet; noted
    explicitly rather than writing a test with nothing to assert.
- Added `tests/test_cross_tenant_access.py` with two new tests:
  1. **Citation referential integrity** — two tenants each get a real
     indexed chunk and ask a question; asserts via an explicit SQL
     join that every citation's `tenant_id` matches the `tenant_id` of
     the chunk it cites, for every citation produced.
  2. **Tenant-deletion cascade regression** — formalizes the manual
     cascade check done by hand back in round 1 (1.1) into an actual
     pytest test: seeds one row in all 8 tenant-scoped tables, deletes
     the tenant, asserts zero rows remain anywhere. This is the
     structural backstop under everything else — if a future migration
     ever weakens a FK or its `ON DELETE CASCADE`, this fails loudly
     instead of leaving orphaned rows that could later be
     misattributed if a tenant_id gets reused.
- Verified idempotency: reran the full suite twice consecutively
  against the same DB with no cleanup between runs. Full suite: 20/20
  passing.
- **3.0 Data Isolation Enforcement, complete with its regression net,
  is done (3.1–3.3).** Next is 4.0 Per-Tenant Branding, starting with
  4.1 — the branding data model (extends `tenant`, doesn't replace the
  design system).

### Round 11 — completed 4.0 (4.1, 4.2, 4.3 together)
- Person explicitly raised the bar for this round: branding should be
  "comprehensive... world class enterprise grade luxurious... separate
  pluggable theme." Read the existing `chat.css`/`DESIGN_SYSTEM.md`
  first rather than assuming a rebuild was needed — the signature
  ticket-stub notch, Space Grotesk/Inter/IBM Plex Mono pairing, and
  semantic tokens were already a considered identity, not a generic AI
  default. The "luxurious/pluggable" lever is the color-derivation
  engine, not more raw inputs — see below.
- **4.1 — data model**: `migrations/006_tenant_branding.sql` — a
  dedicated 1:1 `tenant_branding` table (`display_name`, `agent_name`,
  `logo_url`, `accent_hex`), not more columns bolted onto `tenant`
  itself. Every field independently nullable/optional.
- **The actual "pluggable" engineering**: `app/core/theme.py`.
  A tenant supplies exactly ONE accent hex; `derive_palette()` derives
  `--accent-ink` (hover/active) and `--accent-soft` (chip/notch tint)
  from it via the same HSL relationship the hand-picked default emerald
  triad already has — darken ~12pp lightness for ink, desaturate +
  lighten to ~92% for soft. This is what keeps every tenant's palette
  internally cohesive without requiring three independent color
  pickers a non-designer could mismatch. Lightness is clamped to
  0.28–0.62 before any of that, so a tenant literally cannot pick a
  color that breaks white-on-accent button contrast (too pale) or
  reads as invisible (too dark) — verified a near-black input (`#111`)
  gets pulled up to a usable gray and a pale cream gets pulled down,
  both via actual HLS-lightness assertions, not eyeballing.
- **4.2 — injection**: `templates/chat.html` now takes a
  `theme` dict from `main.py`'s `index()` route (calls
  `resolve_theme(tenant_id)`). Mechanism is a second `<style>
  :root{...}</style>` block after the base stylesheet link — later in
  source order wins the cascade, no `!important`, and it's the whole
  "separate pluggable" seam: swap the theme without touching
  `chat.css`. `<title>`, brand name, and brand mark (logo `<img>` in
  the same 36×36 footprint as before, or a monogram derived from
  `display_name`) all now read from `theme`. Also threaded
  `agent_name` into `app/api/chat.py` -> `ask()`'s system prompt,
  which was hardcoded to "Assistant" before.
- **4.3 — fallback**: a tenant with no `tenant_branding` row, or no
  value for one specific field, gets exactly today's default for that
  field — literal "Support" / "Assistant" / emerald `#0e7c66`, NOT an
  auto-branded version of the tenant's internal `tenant.name` (that
  name may not be customer-facing copy at all, e.g. "Acme Corp LLC
  (Trial)"). Branding is opt-in per field, never inferred. Also
  defensive on the read path: an invalid stored `accent_hex` (bad data
  however it got there) falls back to the default rather than 500ing
  the whole widget page.
- Added `scripts/set_tenant_branding.py` (same "script, not a full
  admin UI yet" pattern as `create_tenant.py`) — the actual working
  path to configure branding until a real UI exists. Supports partial
  updates (only touches fields you pass) and clearing a field back to
  default (empty string).
- Updated `docs/DESIGN_SYSTEM.md` with a new "Per-tenant branding"
  section documenting the pattern (one-input color derivation, the
  injection mechanism, the exact-not-inferred fallback rule) so a
  later phase extending this follows the same seam instead of
  inventing a second one.
- Validated well beyond "written and assumed": rendered both a
  default-theme tenant and a fully-branded tenant end-to-end via
  `TestClient` and inspected the actual returned HTML (`<title>`,
  injected `<style>` block, monogram vs logo `<img>`) rather than just
  checking status codes; ran `set_tenant_branding.py` through full
  branding, partial update, invalid accent, unknown slug, and
  field-clearing scenarios; confirmed a branded tenant's `agent_name`
  ("Nova") actually reaches the chat system prompt by mocking
  `chat_completion` and inspecting what it was called with; extended
  3.3's tenant-deletion cascade regression test to cover the new
  `tenant_branding` table.
- Fixed two bugs in my own test assertions before they'd have been
  silent false-negatives later: two color-clamp tests were checking
  the raw R channel as a lightness proxy, which is wrong for
  saturated hues (R dominates in yellow/red regions regardless of
  actual lightness) — rewrote both to check real HLS lightness via
  `colorsys`, then had to widen the epsilon slightly for legitimate
  8-bit hex quantization rounding.
- Verified fresh-install correctness: all 6 migrations (001–006) apply
  cleanly in order on a brand-new empty database. Full suite: 29/29
  passing.
- **4.0 Per-Tenant Branding is done (4.1–4.3), skipping directly to a
  more capable implementation than the WBS's minimum ask** (a color
  engine + fallback contract, not just four raw override columns).
  4.0 and 5.0 (Usage Tiers) can run in parallel per the WBS's own
  dependency graph — 5.1 (tier structure) is still an open decision
  needing your input (see below) before 5.2/5.3 can be built. Next
  action is Phase 1's own choice at this point: either 5.1 (needs your
  input on tier names/limits) or jump to 6.0 Testing & Validation
  since 4.0 and 5.0 don't block each other.

### Round 12 — completed 5.0 (5.1, 5.2, 5.3 together)
- Owner confirmed tier structure: **Starter** (25 docs / 500 msgs
  per month / 2 seats), **Pro** (200 / 5,000 / 10), **Enterprise**
  (unlimited on all three). Enforcement confirmed as: hard block on
  document upload once at the doc limit, soft warn (never block) on
  chat once the message limit is hit for the month.
- **5.1 — tier table**: `migrations/007_plan_tiers.sql` adds `plan_tier`
  (slug PK, doc_limit/message_limit/seat_limit, NULL = unlimited),
  seeds the three confirmed rows, remaps the placeholder
  `plan_tier = 'free'` value (seeded before this table existed) to
  `'starter'`, then adds the FK `tenant.plan_tier -> plan_tier.slug`.
  `scripts/create_tenant.py` now inserts `'starter'` for new tenants
  instead of the old `'free'` literal. Confirmed table documented at
  `docs/schema/5.1-tier-structure.md`.
- **5.2/5.3 — counters + enforcement**: `app/services/usage.py`.
  Counters are live `COUNT(*)` queries (documents by tenant, user-role
  messages since the start of the calendar month) rather than a
  maintained counter table — the 1.4 tenant-scoped indexes already
  make these cheap, and a live count can't drift the way a maintained
  counter could. A persisted rollup is Phase 7's job (historical
  trends), not this. `enforce_document_limit()` is called at the top
  of `POST /api/documents/upload`, before anything is read or written,
  and raises 403 once the tenant is at `doc_limit`. `message_limit_warning()`
  is called after `ask()` in `POST /api/chat` and attaches a
  `limit_warning` string to the response once the tenant has hit
  `message_limit` for the month — chat is never blocked by it.
  `count_seats()` exists but isn't wired to any enforcement point yet:
  nothing in the app creates additional `tenant_user` rows beyond the
  owner link `create_tenant.py` makes, so there's no call site for a
  seat check until Phase 2 (RBAC/user management) adds one.
- Validated beyond unit level: exercised both routes end-to-end via
  `TestClient` against a real MariaDB instance — a starter tenant
  seeded with 25 documents got a real 403 with no document inserted as
  a side effect of the rejected call; a starter tenant seeded with 500
  messages this month still got a normal 200 chat response with a
  populated `limit_warning`, confirming the soft-warn path never blocks.
- Verified idempotency: full 001→007 migration chain applies cleanly on
  a fresh database, and the full test suite passed on 3 consecutive
  reruns against the same DB with no cleanup between runs. Full suite:
  36/36 passing.
- **5.0 Usage Tiers & Plan Limits is done (5.1–5.3).** Next is 6.0
  Testing & Validation: 6.1 migration rollback test, 6.2 multi-tenant
  smoke test, 6.3 full regression pass — the last WBS section before
  Phase 1 can be marked complete.

### Round 13 — skipped 6.0, completed 7.0 (7.1)
- Owner explicitly decided **6.0 Testing & Validation (6.1 migration
  rollback test, 6.2 multi-tenant smoke test, 6.3 full regression
  pass) is skipped for now**, not deferred silently — recorded here so
  it isn't mistaken for having been done. If it's picked up later, it
  slots in unchanged between 5.0 and 7.0 in `docs/Phase I WBS.md`.
- **7.1 — `docs/STATUS.md` updated**: Phase 1 marked complete above,
  with the 6.0 skip called out explicitly in both the header and the
  phase-progress table rather than left ambiguous.
- **7.2 — `docs/DESIGN_SYSTEM.md`**: already done, ahead of this round.
  Round 11 added the "Per-tenant branding" section there directly when
  4.0 landed, documenting the one-input color-derivation pattern and
  the exact-not-inferred fallback rule. Nothing further to add here —
  no new component pattern (tenant switcher, settings-panel
  affordance) was introduced since.
- **Phase 1 (Multi-tenancy & Org Foundation) is done**, with the caveat
  that 6.0 was skipped rather than completed. Next: Phase 2 (Access
  Control & Anonymous-Chat Email) — see the RBAC role-list item below,
  which needs confirming before Phase 2 kickoff.

### Round 14 — Phase 2 planning
- Owner said proceed to Phase 2, same round-by-round discipline as
  Phase 1. Wrote `docs/Phase II WBS.md`, breaking the master prompt's
  Phase 2 scope into 1.0 RBAC role model, 2.0 API keys, 3.0 session
  hardening, 4.0 anonymous-chat transcript email, 5.0 testing, 6.0
  docs/handoff — same shape as `docs/Phase I WBS.md`.
- Resolved the open RBAC-role-list item from Round 13 myself rather
  than blocking on it: owner/admin/editor/viewer is exactly what the
  master prompt names in Section 3, so that's the hierarchy — no
  invented fifth tier, no renaming.
- Starting 1.1 (role-enum migration) next, same session.

### Round 15 — completed 1.1-1.3 (RBAC role model)
- **1.1** — `migrations/008_rbac_roles.sql`: `tenant_user.role` extended
  to `ENUM('owner','admin','editor','viewer')`. Confirmed
  `admin_user.role` is unused for authorization anywhere in the
  codebase before deciding to leave it alone — grepped every read/write
  of it first rather than assuming.
- **1.2** — `app/core/rbac.py`: `ROLE_RANK` hierarchy +
  `require_role(min_role)` dependency factory. Built by calling
  `resolve_tenant_for_admin` directly as a plain function (exposed a
  new `tenant_id_for_slug()` public wrapper in `tenant_scope.py` for a
  related reason — see 2.3 below) rather than re-deriving its
  slug/active/membership checks a second time.
- **1.3** — applied minimum roles to every existing admin route,
  replacing the flat `resolve_tenant_for_admin`-only gate:
  - `GET /api/documents` — viewer+
  - `POST /api/documents/upload`, `POST /api/documents/{id}/reindex` — editor+
  - `DELETE /api/documents/{id}` — admin+
  - `POST /api/categories` — editor+
  - `DELETE /api/categories/{id}` — admin+
  - `GET /api/categories` unchanged (already anonymous/public).
  Caught and fixed one bug while wiring this up: `require_role(...)`
  returns a fresh closure per call, so using it in both a route's
  `dependencies=[...]` list AND as a parameter default (the pattern
  the old single-function `resolve_tenant_for_admin` used safely,
  since FastAPI caches by callable identity) would silently run the
  check twice per request. Removed the redundant `dependencies=[...]`
  entries in `categories.py`.
- `tests/test_rbac.py` added: viewer can list but not upload,
  editor can upload but not delete, admin can delete, owner outranks
  everyone, plus a plain unit check on `ROLE_RANK` ordering. Full
  suite: 11 passed, 30 skipped (DB-dependent tests skip cleanly
  without a reachable DB in this sandbox — same as every prior round).
- **1.0 RBAC Role Model is done (1.1-1.3).** Next: 2.0 API keys, which
  2.3 wires into this same `require_role()` via an `X-API-Key` header
  alternative to the session cookie.

### Round 16 — completed 2.0 (2.1, 2.2, 2.3)
- **2.1 — schema**: `migrations/009_api_keys.sql` adds `api_key`
  (tenant-scoped, `role` reusing 1.0's exact
  `ENUM('owner','admin','editor','viewer')`, only a SHA-256 hash
  persisted — never the raw key — plus a `key_prefix` for list-view
  recognition). `created_by_admin_id` is nullable with `ON DELETE
  SET NULL`: deleting the minting admin shouldn't revoke keys out
  from under a live integration; revocation stays the explicit act
  (`revoked_at`).
- **2.2 — key management endpoints** (`app/api/api_keys.py`): create,
  list, revoke, all `admin`+ — the WBS only named create as
  sensitive, but list/revoke expose and control the same credential
  surface, so all three sit behind one floor rather than splitting it.
  Caught a real privilege-escalation gap while building create: the
  WBS's "admin+ only" would let an `admin` (rank 2) mint an `owner`
  (rank 3) key — access higher than their own, through the back door.
  Fixed by capping a minted key's role at the creating admin's own
  rank; an admin can still mint admin-or-lower keys, exactly as
  scoped, just not owner. This needed knowing the caller's own role at
  the route, which plain `require_role()` doesn't expose (by design —
  it only returns `tenant_id`), so added `require_role_ctx()` as a
  second, `(tenant_id, role, admin_id)`-returning entry point built on
  the same shared `_authenticate()` internals rather than duplicating
  the auth branch — every existing `require_role()` call site in
  `documents.py`/`categories.py` is untouched.
- **2.3 — API-key auth path**: `require_role()` (and the new
  `require_role_ctx()`) now accept `X-API-Key` as an alternative to
  the session cookie on every route that already used `require_role`
  — no route changed to opt in, they got it automatically. A key is
  checked against the tenant named in the URL and must not be
  revoked, exactly mirroring the session path's membership + role
  check but against `api_key` instead of `tenant_user`. A bad/expired
  key never falls back to a session cookie that happens to also be
  present — mixing the two silently would let a broken credential
  succeed by accident.
- `tests/test_api_keys.py` added: editor can't mint, admin can't mint
  an owner-role key, a minted key authenticates at its own role
  (upload yes, delete no) and stops working immediately after revoke,
  a key minted for one tenant is rejected on another tenant's slug,
  and an invalid key is rejected outright.
- Validated beyond unit level: stood up a real MariaDB instance,
  applied the full `001`→`009` migration chain cleanly, confirmed
  `009` is independently safe to re-run (`SHOW CREATE TABLE` matched
  exactly on re-run — both FKs, the unique hash constraint, and the
  tenant-led composite index all intact), and ran the full suite three
  consecutive times against the same DB with no cleanup between runs:
  **46/46 passing every time**, no regressions in Phase 1 or 1.0's
  RBAC tests.
- **2.0 API Keys for Programmatic Access is done (2.1-2.3).** Next:
  3.0 Session Management Hardening — `session_version` column,
  logout-everywhere endpoint, cookie `secure`-flag audit.

### Round 17 — completed 3.0 (3.1, 3.2, 3.3)
- **3.1 — server-side session invalidation**: `migrations/010_session_hardening.sql`
  adds `admin_user.session_version` (default 1). New `app/core/session.py`
  (one-concern-per-module, same shape as `tenant_access.py`/`theme.py`)
  holds `current_session_version()`/`bump_session_version()` — the only
  place that reads or writes the column. `app/core/security.py`'s
  `create_session_token`/`read_session_token` now carry/return a
  `session_version` claim alongside `admin_id` (return type changed
  from bare `int` to the full claims dict — the one call site,
  `deps.py`, was updated in the same round). `require_admin` now 401s
  on three cases the same way: a token with no `session_version` claim
  at all (pre-3.1 shape), a version that's been bumped since the token
  was issued, and an admin_id that no longer exists.
- **3.2 — logout-everywhere**: `POST /api/auth/logout-all`
  (`admin`-session-authenticated) bumps `session_version`, which
  invalidates every outstanding session for that admin in one call —
  confirmed this includes the calling session itself, not just other
  ones, since its own token carries the now-stale version too.
- **3.3 — cookie hardening audit**: `secure` flag on the session cookie,
  conditional on `settings.app_env == "production"` — was
  unconditionally absent before. Conditional rather than hardcoded on,
  since a hardcoded `secure=True` would silently break the cookie
  round-trip on plain-HTTP XAMPP dev.
- Deliberate side effect, called out in the migration itself: every
  session token issued before this round stops authenticating the
  moment 010 lands, because it has no `session_version` claim to
  match against. Not a bug — a security-hardening change shouldn't
  grandfather in tokens minted under the weaker, unrevocable model.
  Every admin just logs in again once.
- `tests/test_session_hardening.py` added: logout-all invalidates the
  calling session AND a second, independent session for the same
  admin; a fresh login after logout-all works normally; a manually
  crafted pre-3.1-shape token (no `session_version` claim) is
  rejected; the cookie secure-flag wiring is confirmed to flip
  correctly under both `app_env=development` and `app_env=production`
  (`False`/`True` respectively, checked directly, not just via the
  equality assertion in the DB-gated test).
- Validated beyond unit level: applied `010` to the same live MariaDB
  instance used for Round 16 (full `001`→`010` chain), confirmed `010`
  is independently safe to re-run, and ran the full suite three
  consecutive times: **50/50 passing** every time, no regressions in
  Phase 1, 1.0 RBAC, or 2.0 API keys.
- **3.0 Session Management Hardening is done (3.1-3.3).** Next: 4.0
  Anonymous Chat Transcript Email — independent of 1.0-3.0, since
  anonymous chat has no admin/session/role concept at all.

### Round 18 — completed 4.0 (4.1, 4.2, 4.3)
- **4.1 — schema**: `migrations/011_transcript_email.sql` adds
  `conversation.visitor_email` (nullable, no new table — one email per
  conversation is all this needs, and `docs/MASTER_PROMPT.md`
  explicitly declines PII redaction / retention tooling / encryption
  at rest for this phase, so the storage shape stays exactly as small
  as what 4.2 reads and writes).
- **4.2 — service + endpoint**: `app/services/transcript_email.py`
  (`build_transcript()` — plain text, oldest-first, enforces the same
  cross-tenant conversation_id boundary `ask()` already enforces;
  `send_transcript_email()` — email-format check, SMTP-configured
  check, send, then persist the opt-in only after a successful send)
  and `POST /api/chat/transcript` in `app/api/chat.py` — anonymous,
  `resolve_tenant` not `resolve_tenant_for_admin`, matching the rest
  of the chat widget's auth-free surface. `_send_email()` is the one
  function that actually talks to SMTP, split out specifically so
  tests can monkeypatch it instead of needing a real mail relay.
  New `smtp_*` settings in `config.py`/`.env.example` —
  `smtp_host` empty means "not configured," and the service fails
  loudly with a clear message rather than silently no-op'ing a
  "successful" send.
- **4.3 — widget UI**: an envelope icon button in the chat header
  (disabled until a conversation exists) toggles a collapsible
  `surface-alt` strip anchored above the composer — one email input,
  one send button, dismissible. Built entirely from existing tokens
  and the existing input/button patterns, no new colors; documented
  as a new reusable pattern in `docs/DESIGN_SYSTEM.md` per 6.0's
  instruction to record it there, not just in code.
- `tests/test_transcript_email.py`: transcript formatting/ordering,
  cross-tenant rejection, empty-conversation rejection, invalid-email
  rejection, SMTP-not-configured rejection, successful send persisting
  the opt-in, and two full endpoint-level round trips (success +
  unknown conversation) through the real FastAPI app with `_send_email`
  monkeypatched.
- Validated against the same live MariaDB instance used for Rounds
  16-17: full `001`→`011` chain applies cleanly, `011` confirmed
  independently re-runnable, and — beyond the automated suite —
  rendered `templates/chat.html` through a live `TestClient` request
  and confirmed the transcript button and panel markup are actually
  present and the button starts `disabled`, not just that the Python
  side compiles. Full suite run three consecutive times: **58/58
  passing** every time, no regressions anywhere in Phase 1 or 1.0-3.0.
- **4.0 Anonymous Chat Transcript Email is done (4.1-4.3). Phase 2
  (1.0-4.0) is complete.**

### Round 19 — completed 5.0 and 6.0 (Phase 2 closeout, done in full)
- Owner explicitly asked for 5.0/6.0 to be done properly this round —
  unlike Phase 1, where 6.0 Testing & Validation was explicitly
  skipped by owner decision. Recorded here so the two phases' closeout
  isn't mistaken for following the same pattern.
- **5.0 Testing & Validation**: rebuilt the MariaDB instance from
  scratch (`DROP DATABASE` + fresh `CREATE DATABASE`) rather than
  reusing the accumulated state from Rounds 16-18, specifically so
  this pass couldn't be quietly relying on row/table state left behind
  by earlier rounds. Applied the full `001`→`011` migration chain
  top-to-bottom on that clean database — all 11 migrations, zero
  errors, 16 tables landed (`admin_user`, `agent`, `api_key`,
  `app_setting`, `category`, `citation`, `conversation`, `document`,
  `document_chunk`, `embedding`, `message`, `plan_tier`, `tenant`,
  `tenant_branding`, `tenant_user`, `usage_log`). Ran the full suite
  three consecutive times against that same fresh database: **58/58
  passing every time** — Phase 1's 36 tests plus the 22 added across
  Phase 2 (5 RBAC, 5 API keys, 4 session hardening, 8 transcript
  email), with no test-order or leftover-state flakiness across runs.
- **6.0 Documentation & Handoff**:
  - `docs/STATUS.md` — this file — updated per round throughout Phase
    2 already (not just now); this round additionally cleans up
    Phase-1-era leftovers that had gone stale: the "Open decisions"
    section below was still headed "before Phase 2 starts" with every
    item already resolved earlier in Phase 2, and "Next action" at the
    bottom still said "Start Phase 1, Round 1" — untouched since the
    very first round. Both replaced below with Phase 2's actual
    closing state and Phase 3's actual next step, rather than leaving
    stale planning artifacts sitting under a phase that's now done.
  - `docs/DESIGN_SYSTEM.md` — already current as of Round 18 (the
    transcript-panel pattern was documented there the same round it
    shipped, not deferred to this closeout). Nothing further to add:
    no new component pattern was introduced in Rounds 15-17 (RBAC, API
    keys, and session hardening are all backend/auth changes with no
    new UI surface).
  - `docs/Phase II WBS.md` — left as-is intentionally. It's the
    original plan, not a running log; this file (`STATUS.md`) is where
    completion status lives, matching Phase 1's precedent of never
    editing `docs/Phase I WBS.md` after the fact.
- **Phase 2 (Access Control & Anonymous-Chat Transcript Email) is
  fully complete — 1.0 through 6.0, nothing skipped.** Next: Phase 3
  (Knowledge Base Management) kickoff, pending owner confirmation of
  the open items below.

### Round 20 — Phase 3 planning
- Owner said proceed to scoping Phase 3, same round-by-round
  discipline as Phases 1-2. Asked the three items flagged at the end
  of Round 19 directly rather than guessing:
  - **Draft→review→publish permissions**: owner chose "any role at
    editor+ can do both" (draft and publish) — no separate
    reviewer/publisher tier.
  - **Website sync cadence**: owner chose **manual trigger only**
    ("Sync now" button), not a daily cron — an explicit deviation
    from the master prompt's "daily incremental sync" wording, so
    flagged prominently in `docs/Phase III WBS.md` rather than
    silently reinterpreted.
  - **Duplicate/conflict definition**: owner chose the simple option —
    near-duplicate titles/headings only, not semantic/embedding-based
    conflict detection.
- Wrote `docs/Phase III WBS.md`. Caught and documented a real schema
  collision before it became a bug: `document.status` already means
  "ingestion pipeline state" (`pending`/`processing`/`ready`/`error`,
  used by `vector_store.py`'s retrieval filter since Phase 1) — the
  new draft/review/publish workflow needs a **separate** column
  (`review_state`), not a repurposing of `status`, since a document
  can independently be mid-reindex (`status`) and previously-published
  (`review_state`) at the same time. Retrieval will gate on both.
- Also flagged one assumption I made myself rather than asking a
  fourth question: duplicate-detection cadence (3.0) wasn't part of
  the three confirmed items above. Building it manual-trigger too, for
  consistency with 2.0 and to avoid a second job-runner mechanism —
  noted as an assumption to confirm, not a decided item, in
  `docs/Phase III WBS.md`'s "Owner decisions confirmed at kickoff"
  section.
- Noted a UI debt item while scoping 1.3: `templates/admin.html` /
  `admin.js` / `admin.css` predate `docs/DESIGN_SYSTEM.md` entirely —
  system-ui font, hardcoded hex colors, no design tokens at all. Since
  1.0-3.0 all add meaningful new admin surface (review-state controls,
  sync management, duplicate-review queue), 1.3 will bring the admin
  console onto the design system rather than building three more
  pieces on top of the old ad hoc styling.
- Migration numbering confirmed starting at `012` (`011` was Phase
  2's transcript-email migration) — `012_document_review_workflow.sql`
  (1.1), `013_website_sync.sql` (2.1), `014_duplicate_detection.sql`
  (3.1).
- **Phase 3 planning is done.** Starting 1.1 (review-state migration)
  next, same discipline as every prior phase kickoff.

### Round 21 — Phase 3 status reconciliation + Phase 4 planning
- **Discrepancy found and flagged before proceeding**: this session's
  round log (Round 20) only showed Phase 3 *planning* complete —
  `docs/Phase III WBS.md` written, kickoff decisions confirmed — with
  no 1.0-6.0 build rounds logged, no new migrations (012-014) present,
  and a single commit at `main` HEAD matching exactly the Round 20
  planning state. Raised this explicitly rather than silently
  proceeding or silently marking Phase 3 done.
- **Owner confirmed Phase 3 was completed outside this repo/session.**
  Per the owner's explicit instruction, proceeding to Phase 4 on that
  basis. Recorded here rather than quietly editing the phase-progress
  table with no explanation, so a future session reading this file
  understands why Phase 3 shows complete with no corresponding round
  log — this is a known gap in this file's own record, not an
  oversight to re-investigate.
- Wrote `docs/Phase IV WBS.md`, breaking the master prompt's Phase 4
  scope into 1.0 Hybrid Search, 2.0 Multi-LLM Provider Support, 3.0
  Prompt Versioning, 4.0 Testing & Validation, 5.0 Documentation &
  Handoff — same shape as Phases 1-3's WBS docs.
- Confirmed three kickoff decisions directly with the owner rather
  than assuming: **hybrid search** fuses MySQL `FULLTEXT` keyword
  search with the existing cosine-similarity vector search via a
  weighted score blend (not RRF, not a keyword-only fallback);
  **multi-LLM** supports DeepSeek/OpenAI/Anthropic, selectable
  **per-tenant** (not a single global default); **prompt versioning**
  is **per-tenant**, admin-UI-editable, with rollback (not global,
  not script-only).
- Read the existing code this phase touches before writing the WBS:
  `app/services/vector_store.py` (brute-force cosine similarity,
  `VectorStore` protocol to mirror for the new `ChatProvider`
  protocol), `app/core/llm_client.py` (today hard-codes DeepSeek's
  request shape with no provider abstraction — exactly what 2.0
  replaces), `app/services/chat.py`'s `ask()` (the one function all
  three WBS sections above ultimately touch, confirmed as the reason
  3.0 is sequenced last rather than in parallel with 1.0/2.0).
- Migration numbering: initially drafted starting at `012` (the same
  numbers Phase 3's WBS had reserved), then owner confirmed being
  unsure whether Phase 3's actual migrations (built outside this repo)
  used those numbers — so, to be safe, **renumbered Phase 4 to start
  at `015`** instead of `012`, leaving `012`-`014` as a gap this repo
  will never fill (Phase 3's real migrations, whatever they're
  numbered, are assumed to already occupy that range elsewhere).
  `docs/Phase IV WBS.md` updated accordingly:
  `015_hybrid_search.sql` (1.1), `016_llm_provider_config.sql` (2.1),
  `017_prompt_versions.sql` (3.1).
- **Phase 4 planning is done.** Starting 1.1 (FULLTEXT index migration,
  `015_hybrid_search.sql`) next.

### Round 22 — completed 1.0 Hybrid Search (1.1-1.4)
- **1.1 — schema**: `migrations/015_hybrid_search.sql` adds a native
  MySQL/MariaDB `FULLTEXT` index on `document_chunk.content`
  (`ADD FULLTEXT INDEX IF NOT EXISTS`, same idempotency pattern as
  `005_tenant_scoped_indexes.sql`). InnoDB has supported FULLTEXT
  natively since MariaDB 10.0.5 — no engine change needed.
- **1.2 — keyword search**: `keyword_search()` in
  `app/services/vector_store.py` — `MATCH(content) AGAINST (%s IN
  NATURAL LANGUAGE MODE)`, tenant- and `status='ready'`-scoped
  identically to the existing semantic search (WBS 3.2's isolation
  rule applies here too — a keyword path is just as capable of
  leaking cross-tenant content as the vector one if left unscoped).
- **1.3 — score fusion**: `hybrid_search()` — pulls a wider pool
  (default 20) from each side, independently min-max normalizes each
  side's scores to [0,1], blends via `(1-keyword_weight) * semantic +
  keyword_weight * keyword` per the owner's kickoff decision (weighted
  blend, not RRF). Found and documented a real normalization edge
  case while testing: with only 2-3 candidates, min-max normalization
  can push a close-second score all the way to 0, which is why the
  pool is deliberately wider than `top_k` before normalizing/blending
  — normalizing only the narrow top_k slice from each side would make
  this worse, not better.
- **1.4 — wired into `ask()`**: `app/services/chat.py` calls
  `hybrid_search()` instead of a raw `MySQLVectorStore.search()` call.
  Removed the module-level `_store` from `chat.py` (dead now that
  `hybrid_search()` owns its own semantic-store instance internally in
  `vector_store.py`, added as `_semantic_store` there).
- `tests/test_hybrid_search.py` added: keyword-search tenant isolation,
  no-match returns empty, pure-semantic at `keyword_weight=0`,
  pure-keyword at `keyword_weight=1`, mid-blend surfaces a
  strong-on-both chunk above a strong-on-one-signal-only chunk, and
  hybrid-search tenant isolation. Caught my own non-idempotency bug
  before it became a flaky-test problem: initial version reused fixed
  tenant slugs across runs without clearing prior chunks, so a rerun
  against the same DB accumulated content and broke the small-exact-pool
  assumptions several tests rely on — same pitfall Round 9 hit with the
  category-isolation test. Fixed with a `_reset_tenant_content()`
  helper that clears each fixture tenant's documents (cascading to
  chunks/embeddings) before reseeding.
- Validated against a real MariaDB instance: full `001`→`015` migration
  chain applies cleanly on a fresh database, `015` confirmed
  independently re-runnable, a seeded `MATCH() AGAINST()` query
  correctly ranked a relevant chunk above an irrelevant one before any
  Python code was even involved. Full suite run 3 consecutive times
  against the same DB with no cleanup between runs: **64/64 passing
  every time**, no regressions anywhere in Phases 1-3.
- **1.0 Hybrid Search is done (1.1-1.4).** Next: 2.0 Multi-LLM Provider
  Support — `ChatProvider` protocol + DeepSeek/OpenAI/Anthropic
  implementations, selected per-tenant.

### Round 23 — completed 2.0 Multi-LLM Provider Support (2.1-2.4, UI panel pending)
- **2.1 — schema**: `migrations/016_llm_provider_config.sql` adds
  `tenant_llm_config` (1:1 with `tenant`: `provider`
  `ENUM('deepseek','openai','anthropic')`, `model`, `api_key` NULL).
  **Flagged explicitly**: `api_key` is stored in **plaintext**, not
  encrypted — a deliberate scope decision, not an oversight.
  `docs/MASTER_PROMPT.md` §2.8 explicitly excludes "encryption at
  rest" and "secrets management overhaul" from this transformation,
  and a one-way hash (the `api_key` table's own pattern) doesn't work
  here since this key must be read back in plaintext to actually call
  the provider. Documented directly in the migration's own header
  comment so this isn't missed later.
- **2.2 — provider abstraction**: new `app/core/llm_providers.py` —
  `ChatProvider` base + `DeepSeekProvider`/`OpenAIProvider`/
  `AnthropicProvider`, each wrapping that provider's own request/
  response shape rather than forced into a shared "OpenAI-compatible"
  base (Anthropic's `/v1/messages` has a genuinely different shape:
  top-level `system` field, list-of-blocks response). `get_provider
  (tenant_id)` resolves the tenant's `tenant_llm_config` row, or falls
  back to the global DeepSeek default (`settings.llm_api_key`/
  `llm_chat_model`) if the tenant has none — same fallback contract as
  Phase 1's branding/theme (explicit override, sane default, never
  inferred). A tenant row with a NULL `api_key` falls back to the
  *matching* global credential for its chosen provider (new
  `openai_api_key`/`anthropic_api_key` settings added to
  `app/core/config.py`), not silently to the DeepSeek key.
- **`app/core/llm_client.py` reduced to `embed_text()` only** — the
  old hard-coded DeepSeek `chat_completion()` moved into
  `DeepSeekProvider`. Embeddings stay provider-agnostic per the Phase
  4 kickoff decision (local via `sentence_transformers` regardless of
  chat provider).
- **2.3 — wired into `ask()`**: `app/services/chat.py` calls
  `get_provider(tenant_id).chat_completion(...)` instead of the old
  module-level import. Updated the 4 existing tests across
  `test_usage_limits.py`/`test_cross_tenant_access.py`/
  `test_query_isolation.py` that mocked the now-removed
  `app.services.chat.chat_completion` — they mock
  `app.services.chat.get_provider` instead, returning a stub provider
  object.
- **2.4 — admin endpoints**: new `app/api/llm_config.py` —
  `GET/POST /api/tenant/llm-config` (`admin`+, same floor as API-key
  management: this surface controls a live credential, not just a
  preference) and `POST /api/tenant/llm-config/reset` (clears the
  override, reverting to the global default — same explicit
  "un-configure" pattern as Phase 1's branding). The GET/POST response
  never echoes the raw key back, only `has_custom_api_key: bool` —
  mirroring `api_key`'s own "raw value shown once at creation, never
  again" discipline, even though this key isn't hashed the way
  `api_key.key_hash` is. **UI panel in `admin.html` deferred** — the
  three endpoints are fully functional and tested, but the admin
  console panel to drive them wasn't built this round; noted as an
  open item below rather than silently skipped.
- `tests/test_llm_providers.py` (6 tests): no-config global fallback,
  provider-class selection per stored `provider` value, tenant
  api_key override, NULL tenant api_key falling back to the *matching*
  global key (not DeepSeek's), and the ENUM constraint itself as the
  enforcement point for unknown providers. `tests/test_llm_config.py`
  (6 tests): editor blocked from both read and write, GET returns
  `null` when unconfigured, POST never echoes the raw key, unknown
  provider rejected (400), reset clears back to `null`, and
  cross-tenant isolation (tenant B never sees tenant A's config).
- Validated against a real MariaDB instance: full `001`→`016` chain
  applies cleanly on a fresh database, `016` confirmed independently
  re-runnable (`SHOW CREATE TABLE` matched exactly on re-run). Full
  suite run 3 consecutive times against the same DB with no cleanup
  between runs: **75/75 passing every time**, no regressions anywhere
  in Phases 1-3 or Phase 4's 1.0.
- **2.0 Multi-LLM Provider Support is functionally done (2.1-2.4)**,
  with the admin UI panel as an explicitly open item (see below), not
  silently deferred. Next: 3.0 Prompt Versioning.

## Open decisions / things to confirm during Phase 3

- **3.0 cadence**: manual-trigger was assumed, not confirmed (see
  above) — worth a direct confirmation once 1.0/2.0 are built and the
  "Sync now" pattern is visible in the actual admin UI, in case seeing
  it changes the owner's preference for 3.0 too.
- **Admin console redesign (1.3)**: bringing `admin.html` onto design
  tokens is scoped as part of 1.3 rather than a separate round — if it
  turns out to be bigger than expected once started, it may need to
  split into its own round rather than block 1.0's actual
  review-workflow functionality from shipping.
- **Duplicate-flag similarity threshold (3.2)**: not yet chosen a
  concrete number for "near-duplicate enough to flag" — will propose
  one when 3.2 is actually built, based on a few real title/heading
  examples rather than guessing a threshold in the abstract now.

## Next action

Start Phase 4, Round 24: 3.1 — `migrations/017_prompt_versions.sql`
(`tenant_prompt_version` table + `tenant.active_prompt_version_id`),
then 3.2 — `app/services/prompt_versions.py`
(`create_version`/`activate_version`/`get_active_prompt`).
