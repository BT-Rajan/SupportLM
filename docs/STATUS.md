# SupportLM — Status

> Updated at the end of every round. Read this right after
> `docs/MASTER_PROMPT.md` at the start of any session.

## Current phase

**Phase 8 (final phase) — Round 41 complete (other session). 1.0
Audit Log done (1.1-1.4).** 2.0 Rate Limiting & Abuse Protection is
next. Phase 3 is fully complete (1.0/2.0/3.0). Phases 4, 5, 6, and 7
are complete. This session's cross-cutting data-integrity fix (below,
also originally written as "Round 41" before this collision was
found — see that entry's own note) landed alongside their real Round
41; no round-number renumbering needed since it's a standalone
addition, not part of either session's phase sequence.

## Phase progress

| Phase | Name                                   | Status      |
|-------|-----------------------------------------|-------------|
| 1     | Multi-tenancy & Org Foundation           | Complete (6.0 skipped by owner decision) |
| 2     | Access Control & Anonymous-Chat Email    | Complete    |
| 3     | Knowledge Base Management                | Complete — 1.0/2.0/3.0 all done (supersedes an earlier "stops at 1.0" decision — see Round 38 below) |
| 4     | Retrieval & Answer Quality                | Complete |
| 5     | Conversation Experience                   | Complete |
| 6     | Escalation to Service Request (SR)        | Complete |
| 7     | Analytics & Reporting                     | Complete |
| 8     | Admin, Ops & Webhooks                     | In progress (planning) |

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

### Round 21 — completed 1.0 (1.1, 1.2, 1.3)
- **1.1 — schema**: `migrations/012_document_review_workflow.sql` adds
  `document.review_state`, deliberately separate from `status` (see
  `docs/Phase III WBS.md`'s collision writeup). Existing documents
  backfilled to `'published'` in the same migration so nothing already
  live vanishes from retrieval the moment it runs.
  **Important, and different from every migration in Phases 1-2**:
  the backfill `UPDATE` is a genuine one-time operation, not endlessly
  re-runnable — re-applying it after real drafts exist would silently
  flip them back to `'published'`. Caught this the hard way: routinely
  re-ran the migration during validation the way every prior round
  did, and it silently re-published draft/review test documents left
  over from an earlier suite run, which then broke a later test in a
  confusing way (an exact-match assertion picking up leftover rows).
  Documented in the migration itself with the same "one-time, not
  endlessly safe" framing `004_backfill_default_tenant.sql` already
  established in Phase 1 — this project already had the right pattern
  for this exact situation, I just didn't apply it until the mistake
  surfaced it. Verified the *schema* half (`ALTER ... ADD COLUMN IF
  NOT EXISTS`) genuinely is idempotent on its own, in isolation, on a
  disposable scratch database — it's specifically the backfill that
  isn't safe to repeat.
- **1.2 — retrieval gating + transition endpoint**:
  `vector_store.py`'s `search()` now requires `status = 'ready' AND
  review_state = 'published'`, not just `status = 'ready'`. New `POST
  /api/documents/{id}/review-state` (`editor`+, any direction, no
  forced ordering, per the owner's decision). Caught a second real bug
  before it shipped: the endpoint's original 404 check used the
  `UPDATE`'s rowcount, but pymysql reports rows *changed* not rows
  *matched* — setting a document's review_state to the value it
  already has updates 0 rows, which would have 404'd a document that
  actually exists. Fixed by checking existence via `SELECT` first,
  matching the pattern `reindex_document` already used for the same
  reason. Caught a third, in the tests: an existing Phase 1 test
  (`test_vector_store_search_only_returns_own_tenant_chunks`) would
  have kept "passing" on empty result sets after this change — its
  assertions were all vacuously true for zero results — so it was
  silently testing nothing. Fixed the fixture (documents there now
  need `review_state = 'published'` too) and added explicit
  non-emptiness assertions so it can't silently pass that way again.
- **1.3 — admin UI + design-system migration**: `templates/admin.html`
  document table gets a `review_state` badge and a select to move it
  directly. Also finally brought `admin.html`/`admin.css`/`admin.js`
  onto `docs/DESIGN_SYSTEM.md` tokens — the console had predated the
  design system entirely since it was first built. Documented as a new
  "Admin console" section in `docs/DESIGN_SYSTEM.md`, including the
  one deliberate deviation from its own empty-state rule (reasoning
  given inline there, not just in code).
- `tests/test_review_workflow.py` added: upload defaults to draft,
  retrieval excludes draft/review (only `ready`+`published` shows up),
  editor can transition/viewer can't, setting the same state twice
  doesn't 404 (regression test for the rowcount bug above), invalid
  state rejected, unknown document 404s.
- Validated against a live MariaDB instance: rebuilt fresh, applied
  the full `001`→`012` chain cleanly, ran the suite repeatedly —
  **64/64 passing** across 4 consecutive clean runs (the first of the
  four rebuild+run cycles surfaced both the migration re-run pitfall
  above and a test-isolation bug in my own new test — fixed both, then
  reconfirmed clean).
- **1.0 Content Review Workflow is done (1.1-1.3).**

### Round 22 — cross-session reconciliation + Phase 4 planning
- **What actually happened, corrected from this file's own earlier,
  wrong account**: a *different* Claude session was working on this
  same repo concurrently with the session that built Round 21 above.
  The owner told that other session "Phase 3 was completed outside
  this repo/session" — which was not accurate; Phase 3's 1.0 was, at
  that moment, actively being built in the session that produced
  Round 21, just not yet pushed. That other session took the owner's
  statement at face value (reasonably — it had no way to independently
  verify a claim about work happening somewhere it couldn't see),
  marked Phase 3 complete on that basis, and proceeded straight to
  Phase 4 planning and Round "22"'s Hybrid Search build (renumbered to
  Round 23 below). This file's previous version of this entry recorded
  that "Phase 3 was completed outside this repo" as if it were
  confirmed fact — it wasn't; it was an honest mixup between two
  concurrent sessions the owner was running. Corrected here once both
  sessions' histories were compared directly.
- **Reconciliation, per the owner's explicit instruction**: Round 21's
  Phase 3 1.0 work (this session) is authoritative for Phases 1-3;
  Phase 4's planning and 1.0 build (the other session, renumbered
  Round 22→ this entry, Round 23 below) stands as-is for Phase 4
  onward. Reconciled via `git stash` + fast-forward + `stash pop`,
  not a merge commit — the two sessions' local histories never
  actually diverged at the commit level (this session simply hadn't
  pushed Round 21 yet when the other session pushed its planning and
  build), so a linear round-number renumbering was enough; no
  conflicting commits needed resolving, just two conflicting
  *files-in-progress*.
- **One real technical conflict, not just a bookkeeping one**: the
  other session's `keyword_search()` (Phase 4's 1.2, part of Round 23
  below) was built with only `status = 'ready'` scoping — reasonable
  at the time, since that session believed `review_state` didn't
  exist yet. Merged in Round 21's `review_state = 'published'` gate
  from `MySQLVectorStore.search()`, but `keyword_search()` needed the
  identical gate added by hand — a plain file merge doesn't know that
  two independently-correct-looking WHERE clauses need to agree with
  each other. Without this fix, `hybrid_search()`'s keyword
  contribution could have resurfaced a draft document that its
  semantic contribution correctly excluded. Added
  `tests/test_hybrid_search.py::test_keyword_search_excludes_unpublished_documents`
  as the regression test for this specific gap. Also fixed
  `test_hybrid_search.py`'s `_seed_chunk` fixture, which — like two
  other pre-existing Phase 1/2 test fixtures Round 21 already had to
  fix for the same reason — inserted documents without `review_state`,
  so they'd default to `'draft'` and silently return zero search
  results once the gate landed.
- **Migration numbering resolved itself by luck, not by this
  reconciliation**: the other session, uncertain whether Phase 3's
  "elsewhere" migrations used `012`-`014`, preemptively renumbered
  Phase 4 to start at `015` instead. Phase 3's real migration is (and
  was always going to be) `012`, so there's no actual collision either
  way — `012` is Phase 3's, `015`+ is Phase 4's, `013`-`014` remain
  open for Phase 3's still-unbuilt 2.0/3.0. Nothing needed renaming.
- Full suite re-validated after reconciliation against a freshly
  rebuilt live MariaDB instance: complete `001`→`015` migration chain
  (skipping the intentionally-unused `013`-`014` gap) applies cleanly,
  and the combined suite — Phase 1 through Phase 3's 1.0 plus Phase
  4's 1.0 — passes together with the `keyword_search()` fix in place.
- Everything below this point (Phase 4 planning + the Hybrid Search
  build, renumbered Round 23) is the other session's real work,
  content-unmodified — reviewed for the reconciliation above but not
  otherwise altered. One further renumbering was needed on top of
  this: the other session kept pushing (Multi-LLM, Prompt Versioning,
  Phase 5 planning, Multi-turn Memory, Multi-language) *while this
  reconciliation was happening*, and its own next round reused the
  number "23" for real new content (Multi-LLM Provider Support),
  colliding with this reconciliation's already-renumbered "Round 23"
  (Hybrid Search). Everything from the real Multi-LLM round onward is
  shifted +1 here (23→24, 24→25, 25→26, 26→27, 27→28) to keep the
  sequence clean — content untouched, only the round numbers moved.

### Round 23 — completed 1.0 Hybrid Search (1.1-1.4)
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
  *Round 22 note: also needed `review_state = 'published'` scoping,
  added during cross-session reconciliation — see above.*
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

### Round 24 — completed 2.0 Multi-LLM Provider Support (2.1-2.4, UI panel pending)
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

### Round 25 — completed 3.0 Prompt Versioning (3.1-3.4) — Phase 4 done
- **3.1 — schema**: `migrations/017_prompt_versions.sql` adds
  `tenant_prompt_version` (append-only: `create_version()` never
  overwrites, only inserts) and `tenant.active_prompt_version_id`
  (nullable — NULL = use the hardcoded default in `chat.py`, same
  fallback contract as 2.0's `tenant_llm_config`).
  `created_by_admin_id` is `ON DELETE SET NULL`, same rationale as
  `api_key.created_by_admin_id` — deleting the admin who wrote a
  version must not invalidate it. Used the simpler `ADD COLUMN IF NOT
  EXISTS` idiom from 010/011 for the column itself; the FK on that
  column needed its own `information_schema`-guarded block since
  `ADD CONSTRAINT IF NOT EXISTS` isn't available in MariaDB — first
  migration in this repo to need that pattern, documented inline.
- **3.2 — service** (`app/services/prompt_versions.py`):
  `create_version()` (always inserts, never auto-activates — same
  "draft before it's live" spirit as Phase 3's document review),
  `activate_version()` (the entire rollback mechanism — reactivating
  an old version_id IS rollback, no separate revert mutation exists;
  rejects a version_id belonging to another tenant, same cross-tenant
  guard pattern as every other Phase 1-3 write path), `list_versions()`,
  `get_active_prompt()`.
- **3.3 — admin endpoints** (`app/api/prompt_versions.py`): `POST
  /api/tenant/prompt-versions` (`editor`+ — drafting is low-risk, same
  floor as document upload), `GET` (`viewer`+), `POST
  /{id}/activate` (`admin`+ — this is the one action that changes what
  every visitor's conversation actually sees, same floor as API-key
  mint/revoke).
- **3.4 — wired into `ask()`**: `app/services/chat.py`'s
  `_SYSTEM_PROMPT` module constant is now the fallback only;
  `get_active_prompt(tenant_id)` is tried first. Added a safeguard not
  explicitly in the WBS but found necessary while building this: a new
  `_render_system_prompt()` helper catches `template.format()` raising
  on a tenant-authored prompt with a stray/unescaped brace — an
  admin's editing mistake shouldn't 500 every visitor's chat request,
  so it falls back to appending context directly after the raw
  template rather than crashing. Logged as a warning when this
  triggers, not swallowed silently.
- `tests/test_prompt_versions.py` (10 tests, including 3 chat.py
  integration tests): no-config returns None, create doesn't
  auto-activate, version numbers increment per-tenant, activate then
  read back, **activate-new-then-roll-back-by-reactivating-the-old-one**
  (the actual rollback mechanism), cross-tenant activation rejected,
  `created_by_admin_id` survives admin deletion, `ask()` actually uses
  the tenant's active prompt end-to-end, `ask()` falls back to the
  default when unconfigured, and `ask()` survives a malformed custom
  prompt without 500ing. `tests/test_prompt_versions_api.py` (7 tests):
  viewer can list but not create/activate, editor can create but not
  activate, create-doesn't-auto-activate at the endpoint level, full
  admin activate/rollback lifecycle via the API, unknown version_id
  404s, cross-tenant activation rejected via the API.
- Validated against a real MariaDB instance: full `001`→`017` chain
  applies cleanly on a fresh database, `017` confirmed independently
  re-runnable (both the `CREATE TABLE IF NOT EXISTS` and the
  information_schema-guarded FK block). Full suite run 3 consecutive
  times against the same DB with no cleanup between runs: **90/90
  passing every time**, no regressions anywhere in Phases 1-3 or
  Phase 4's 1.0/2.0.
- **Phase 4 (Retrieval & Answer Quality) is done: 1.0 Hybrid Search,
  2.0 Multi-LLM Provider Support, 3.0 Prompt Versioning all complete.**
  Admin UI panels for 2.0/3.0 remain backlog items alongside the
  existing admin console redesign, not built ad-hoc. Next: 4.0 Testing
  & Validation (already continuously satisfied round-by-round per this
  log) and 5.0 Documentation & Handoff — then Phase 5 (Conversation
  Experience) per `docs/MASTER_PROMPT.md`.

### Round 26 — Phase 5 planning (Conversation Experience)
- Wrote `docs/Phase V WBS.md`, breaking the master prompt's Phase 5
  scope into 1.0 Multi-turn Memory, 2.0 Multi-language Support, 3.0
  Thumbs Up/Down Feedback, 4.0 Testing & Validation, 5.0 Documentation
  & Handoff — same shape as Phases 1-4's WBS docs.
- Confirmed three kickoff decisions directly with the owner: **1.0
  multi-turn memory** is full, uncapped conversation history in both
  retrieval and the answer call (not a capped window, not a
  query-rewriting LLM call first); **2.0 multi-language** is an
  explicit widget language selector that forces replies into the
  chosen language (not auto-detection); **3.0 feedback** is simple
  thumbs up/down, anonymous, no comment field, and — the specific
  thing this decision rules out — **no re-voting after the first
  submission**.
- Flagged a real, accepted-not-fixed risk before 1.1: "no cap" on
  conversation history runs into three independent ceilings this phase
  doesn't work around — `sentence-transformers`' 256-token embedding
  input limit (silent truncation, not a failure), MySQL FULLTEXT's
  practical relevance-quality degradation on very long query text (not
  a hard cap), and every provider's real context-window limit
  (surfaces as the existing `502` handling in `post_chat`, nothing new
  needed). Recorded explicitly so a long-conversation quality
  degradation later isn't mistaken for a bug this phase should have
  prevented — capping/summarizing history is exactly the follow-up
  work the "no cap" decision defers, not an oversight.
- Read `app/api/chat.py`'s `post_chat` (existing `httpx.HTTPStatusError`
  handling already surfaces provider context-limit errors usefully — no
  changes needed there for 1.0) and `templates/chat.html`/
  `static/js/chat.js` (already a fully built, real widget with a
  transcript-email feature — unlike `admin.html`, this surface gets a
  real UI addition each phase, not a backlogged one; 2.0's language
  selector and 3.0's thumbs icons both get built this phase, not
  deferred) before writing the WBS.
- **Phase 5 planning is done.** Starting 1.1 (fetch conversation
  history in `ask()`) next.

### Round 27 — completed 1.0 Multi-turn Memory (1.1-1.4)
- **1.1 — fetch history**: new `_fetch_history()` in
  `app/services/chat.py` — every prior `message` row for the
  conversation, oldest first. Cross-tenant `conversation_id` reuse is
  guarded **once**, at the top of `ask()`, before history is fetched —
  the old duplicate guard further down (right before the DB write) was
  removed as dead weight now that the same check already ran earlier
  in the same call.
- **1.2 — retrieval folds in the full transcript**: the text passed to
  `hybrid_search()` (both its keyword and semantic sides) is now the
  entire prior transcript concatenated with the current question, not
  the bare question alone — per the owner's "full history, no cap"
  kickoff decision. The three practical ceilings this runs into
  (embedding truncation, FULLTEXT relevance degradation, provider
  context limits) are exactly what `docs/Phase V WBS.md` flagged as
  accepted-not-fixed, not new problems found during the build.
- **1.3 — `ChatProvider` protocol gains real multi-turn support**:
  `chat_completion(system_prompt, user_message)` →
  `chat_completion(system_prompt, history, user_message)` across the
  base class and all three implementations. DeepSeek/OpenAI splice
  `history` into their `messages` array between the system message and
  the new user message; Anthropic does the same into its own
  `messages` array, `system` staying a top-level field exactly as
  before.
- **1.4 — wired into `ask()`**: `provider.chat_completion(system_prompt,
  history, question)` replaces the old 2-argument call. Fixed 2 of my
  own Phase 4 test stubs (`test_prompt_versions.py`) that had an
  explicit `(self, system_prompt, user_message)` signature and broke
  immediately on this change — the other existing stubs already used
  `*a, **kw`/lambdas and needed no changes.
- `tests/test_multiturn_memory.py` (5 tests): first turn has empty
  history, second turn's history includes the first turn's real
  question and the actual stored answer, history comes back oldest-
  first across three turns, the retrieval-side `embed_text()` call
  actually receives the folded transcript (verified via a captured
  side-effect, not just trusting the code path), and cross-tenant
  `conversation_id` reuse still yields empty history for the "wrong"
  tenant (no leakage).
- Full suite run 3 consecutive times against the same DB with no
  cleanup between runs: **95/95 passing every time**, no regressions
  anywhere in Phases 1-4.
- **1.0 Multi-turn Memory is done (1.1-1.4).** Next: 2.0 Multi-language
  Support.

### Round 28 — completed 2.0 Multi-language Support (2.1-2.4)
- **2.1 — schema**: `migrations/018_conversation_language.sql` adds
  `conversation.language` (nullable — same "explicit override, no
  forced default" contract as every other nullable config column this
  project has added).
- **2.2 — enforcement + resolution** (`app/services/chat.py`):
  `_resolve_language()` — the widget's selection on the current
  request wins if sent (so switching mid-conversation takes effect
  immediately); otherwise falls back to whatever the conversation
  already has stored; `None` if neither exists (today's behavior,
  unchanged). `_language_instruction()` appends *"Respond only in
  {language}, regardless of what language the question is written
  in"* **after** whichever system prompt is already in play (Phase 4
  default or a tenant's active custom version) — a tenant's custom
  prompt doesn't need to know about language selection for this to
  work. Resolved and persisted using the same cross-tenant
  `conversation_id` guard 1.1 already established — a nulled-out
  `conversation_id` must not leak another tenant's language setting
  any more than it leaks their history.
- **2.3 — widget UI**: a language `<select>` in `chat.html`'s header
  (English/Spanish/French/German/Arabic/Hindi/Chinese/Portuguese/
  Japanese/Russian), `chat.js` persists the selection via
  `localStorage` (scoped per-tenant-slug, since one browser may visit
  multiple tenants' widgets) and sends it on every request.
- **2.4 — `ChatRequest` gains `language`**: `app/api/chat.py`, passed
  straight through to `ask()`.
- `tests/test_multilanguage.py` (9 tests): instruction text for a
  known code, unknown-code fallback to the raw code, no-instruction
  when nothing's selected, first-turn selection both appends the
  instruction AND persists to `conversation.language`, a second turn
  that resends no `language` field still gets the stored language
  enforced, **switching languages mid-conversation takes effect
  immediately and the third turn (which also sends no `language`
  field) keeps using the most recent selection, not the first one**,
  and cross-tenant `conversation_id` reuse doesn't leak tenant A's
  language choice to tenant B.
- Full suite run 3 consecutive times against the same DB with no
  cleanup between runs: **103/103 passing every time**, no regressions
  anywhere in Phases 1-4 or Phase 5's 1.0.
- **2.0 Multi-language Support is done (2.1-2.4).** Next: 3.0 Thumbs
  Up/Down Feedback.

### Round 29 — completed 3.0 Thumbs Up/Down Feedback (3.1-3.3) — Phase 5 done
- **3.1 — schema**: `migrations/019_message_feedback.sql` adds
  `message_feedback` with `message_id` **UNIQUE** — the direct,
  literal consequence of the kickoff decision that "let the visitor
  change their vote" was explicitly *not* chosen. One row per message,
  ever; the UNIQUE constraint is the schema-level backstop behind the
  app-layer 409 in 3.2.
- **3.2 — endpoint**: `POST /api/chat/{message_id}/feedback`
  (`app/api/chat.py`, anonymous — same auth-free surface as
  `post_chat`/`post_transcript`). Validates, in order: rating is
  `'up'`/`'down'` (400), message exists and belongs to this tenant
  (404 — doesn't distinguish "doesn't exist" from "wrong tenant," same
  non-distinguishing pattern as every other cross-tenant guard in this
  codebase), message is an **assistant** message not a user one (400 —
  a visitor can't rate their own question), no existing feedback row
  for this message (409). `ask()`'s return value gained `message_id`
  (the assistant message's real row id — it already tracked this
  internally as `assistant_message_id` for the citation writes, just
  wasn't surfacing it) so the widget has something to attach feedback
  to.
- **3.3 — widget UI**: thumbs-up/down icon pair (`chat.js`'s new
  `attachFeedback()`) rendered into each assistant message's meta row,
  right where the existing sources-toggle already lives. Both buttons
  disable immediately on click, client-side, mirroring the
  server-enforced "no re-voting" rule rather than waiting for a 409
  round-trip to communicate it. Best-effort `fetch` — a failed
  feedback POST doesn't surface an error bubble of its own, since a
  missed vote shouldn't disrupt the actual chat experience.
- `tests/test_message_feedback.py` (8 tests, exercised through the
  real `/api/chat` endpoint rather than calling `ask()` directly, so
  the `message_id` under test is a genuine row created the same way
  production traffic creates one): up-vote succeeds, down-vote
  succeeds, invalid rating rejected, **second vote on the same message
  rejected with 409** (the actual kickoff decision under test), unknown
  message_id 404s, rating a user's own message rejected, cross-tenant
  message_id rejected via another tenant's URL, and `ask()`'s response
  actually includes a usable `message_id`.
- Full suite run 3 consecutive times against the same DB with no
  cleanup between runs: **111/111 passing every time**, no regressions
  anywhere in Phases 1-4 or Phase 5's 1.0/2.0.
- **Phase 5 (Conversation Experience) is done: 1.0 Multi-turn Memory,
  2.0 Multi-language Support, 3.0 Thumbs Up/Down Feedback all
  complete.** No new admin-facing surface this phase, so no new admin
  UI backlog item. Next: Phase 6 (Escalation to Service Request) per
  `docs/MASTER_PROMPT.md`.

### Round 30 — cross-session merge reconciliation (Phase 3 1.0 + Phase 4/5 continuation)
- On pushing Round 28, the remote had diverged: a **different
  concurrent session** had pushed real Phase 3 1.0 (Content Review
  Workflow) work — `migrations/012_document_review_workflow.sql`,
  `review_state` gating in `MySQLVectorStore.search()`, a full
  `admin.html`/`admin.css`/`admin.js` rebuild onto
  `docs/DESIGN_SYSTEM.md` tokens, and `tests/test_review_workflow.py`
  — plus its own fix to this session's `keyword_search()` (Phase 4)
  so its FULLTEXT contribution respected the same `review_state`
  gate the semantic side got, with a regression test for it.
- **Merged via `git merge`, not a force-push.** Ran it on a scratch
  branch first to inspect every conflict before touching `main`. Only
  one file actually conflicted — `docs/STATUS.md` — because both
  sessions had independently rewritten large stretches of the same
  narrative sections after forking from the same commit
  (`a77ed0e`, Round 27). Everything else (`vector_store.py`,
  `documents.py`, the three shared test files) merged cleanly with no
  conflicts, since neither session had touched the same lines of code
  — a good sign the two bodies of work were genuinely independent, not
  overlapping.
- **Resolved `docs/STATUS.md` by keeping whichever side had the more
  accurate, more recent ground truth for each claim** — not by
  mechanically picking one side wholesale: Phase 5 is genuinely
  complete (this session's Round 26-28, more recent than the other
  session's snapshot), while Phase 3 is genuinely NOT complete beyond
  1.0 (the other session's real, verified work — corrected the
  "complete per owner confirmation" note this file carried since
  Round 21, which was a mixup, not a fact).
- No migration-numbering collision: the other session's real migration
  landed as `012`, exactly the number this session left as a
  deliberate gap back at Round 21/22 for this exact reason. Their
  planned `019_message_feedback.sql` (referenced in their half of the
  "Next action" conflict, for their own future Round 29) was never
  actually written as a file — this session had already built and
  pushed the real `019_message_feedback.sql` in Round 28, so there's
  no file collision, just a moot forward-reference in prose.
- Full suite run against the merged tree before pushing (see the
  validation note right after this entry) to confirm the merge didn't
  silently break either session's work.
- **Validated**: full `001`→`012`,`015`-`019` migration chain (the
  deliberate `013`-`014` gap intact) applies cleanly on a freshly
  rebuilt database. Full suite run 3 consecutive times against the
  same DB with no cleanup between runs: **118/118 passing every
  time** — both sessions' work (Phase 3's 1.0, Phase 4's complete
  scope, Phase 5's complete scope) verified functioning together, not
  just merged textually.
- **Open, unresolved**: Phase 3's 2.0 (Website Content Sync) and 3.0
  (Duplicate/Conflict Detection) are still genuinely unbuilt — neither
  concurrent session picked them up. This needs an explicit owner
  decision (see "Next action" below), not another session quietly
  choosing for them.

### Round 31 — owner decision: Phase 3 intentionally stops at 1.0
- Presented the Round 29 reconciliation finding directly to the owner
  (Phase 3 was really only 1.0 done, not complete as this file had
  said) rather than assuming either "finish it" or "leave it" on this
  session's own authority.
- **Owner's explicit call: leave Phase 3 at 1.0, move on to Phase 6.**
  2.0 (Website Content Sync) and 3.0 (Duplicate/Conflict Detection)
  from `docs/Phase III WBS.md` will not be built. This is a scope
  decision, not an abandoned TODO — recorded as such so a future
  session doesn't mistake it for unfinished work needing a resume.
- Phase progress table and current-phase header updated to reflect
  this as **Complete (1.0 only, by owner decision)** rather than "in
  progress" or "not started."

### Round 32 — Phase 6 planning (Escalation to Service Request)
- Wrote `docs/Phase VI WBS.md`, breaking the master prompt's Phase 6
  scope into 1.0 Escalation Detection, 2.0 SR Generation, 3.0 Dual
  Email Notification, 4.0 Testing & Validation, 5.0 Documentation &
  Handoff — same shape as every phase's WBS so far.
- Confirmed three kickoff decisions directly with the owner:
  **1.0 trigger** is automatic only (the model signals when it can't
  help; no manual escalation button in this phase's scope);
  **2.0 SR number format** is date-prefixed sequential
  (`SR-20260716-0007`); **3.0 support inbox** is per-tenant, admin-set,
  and required — no global fallback.
- **Resolved, not just asked about, a real design gap**: the master
  prompt requires emailing "the end user," but this widget is fully
  anonymous with no visitor email collected upfront. Assumed (flagged
  explicitly, same as Phase III WBS's cadence assumption) that the
  widget prompts the visitor for their email at the moment escalation
  triggers, before the SR is created or either email goes out — if the
  visitor doesn't provide one, no SR is created and no emails send,
  since a support ticket with no way to reach the visitor back doesn't
  serve this feature's actual purpose.
- Read `app/services/transcript_email.py` before writing the WBS —
  2.3 reuses its existing `build_transcript()` rather than duplicating
  chat-history-assembly logic, and 3.x's dual-email sending follows
  the same `_send_email()`/SMTP-config pattern already established
  there.
- **Phase 6 planning is done.** Starting 1.1 (system-prompt escalation
  signal) next.

### Round 33 — completed 1.1/1.2 of Escalation Detection (1.3 deferred to Round 35)
- **1.1 — system-prompt signal**: appended, last (after Phase 5's
  language instruction), a new instruction telling the model to end
  its response with a literal `[ESCALATE]` marker line if — and only
  if — the provided context doesn't contain enough to answer. Text
  marker, not structured/function-calling output, per
  `docs/Phase VI WBS.md`'s note on why that fits this architecture.
- **1.2 — detect + strip**: new `_detect_and_strip_escalation()` in
  `app/services/chat.py` — checks the raw answer's trailing text for
  the marker (a marker-looking string in the *middle* of a real answer
  must not trigger this — only a genuine trailing marker counts, and
  there's a test for exactly that), strips it before the answer is
  shown to the visitor OR written to the `message` table, and sets
  `needs_escalation` on `ask()`'s return dict.
- **1.3 deliberately deferred to Round 35**: the widget's "ask for an
  email" prompt has nothing useful to submit to until 3.4's
  `/escalate` endpoint exists — building UI against a non-existent
  endpoint can't actually be tested, so 1.3 is built together with
  3.4 once 2.0/3.0 land, not left half-built now. Not silently
  skipped — recorded as an explicit sequencing choice.
- `tests/test_escalation_detection.py` (7 tests): marker detected and
  stripped, no-marker case passes through unchanged, a marker-looking
  substring mid-answer does NOT trigger escalation (only a genuine
  trailing marker does), `ask()` surfaces `needs_escalation: true`/
  `false` correctly in both directions, the stripped marker never
  lands in the stored `message` row, the escalation instruction is
  actually present in the system prompt sent to the provider.
- Full suite run 3 consecutive times against the same DB with no
  cleanup between runs: **125/125 passing every time**, no regressions
  anywhere in Phases 1-5.
- Next: 2.0 SR Generation.

### Round 34 — completed 2.0 SR Generation (2.1-2.3)
- **2.1 — schema**: `migrations/020_service_requests.sql` adds
  `sr_sequence` (per-tenant, per-day counter) and `service_request`
  (`message_id` UNIQUE — one escalation per triggering message, no
  re-submission, same "no re-voting" shape as Phase 5's feedback).
  **Caught and fixed a real bug via my own test before pushing**: the
  first draft made `sr_number` globally `UNIQUE`, but two different
  tenants are *expected* to produce the identical human-readable
  number on the same day (each has its own sequence — same as two
  companies both having invoice #1001). A global `UNIQUE` would have
  incorrectly rejected the second tenant's insert; fixed to a
  composite `UNIQUE (tenant_id, sr_number)`, which is what the format's
  actual guarantee (collision-free *within* a tenant/day) requires.
- **2.2 — SR number generation**: new `app/services/escalation.py`,
  `generate_sr_number()` — `INSERT ... ON DUPLICATE KEY UPDATE
  next_seq = next_seq + 1` then a read-back, atomic under InnoDB row
  locking (safe under concurrent escalations for the same tenant/day,
  unlike a `COUNT(*) + 1` against `service_request`, which would
  race).
- **2.3 — chat history attachment**: no new code — confirmed
  `app/services/transcript_email.py`'s existing `build_transcript()`
  is reusable as-is for 3.0's email bodies once built, since messages
  are append-only and a live rebuild from `conversation_id` is
  equivalent to a stored snapshot.
- `tests/test_escalation_service.py` (4 tests): SR number format,
  increments correctly across 3 calls for one tenant, two tenants'
  sequences are independent (both starting at `0001` the same day is
  correct, not a bug), and — the test that actually caught the schema
  bug above — two tenants' identical-looking SR numbers both insert
  successfully into `service_request` without violating the (now
  correctly composite) uniqueness constraint.
- Full suite run 3 consecutive times against the same DB with no
  cleanup between runs: **129/129 passing every time**, no regressions
  anywhere in Phases 1-5 or Phase 6's 1.0.
- Next: 3.0 Dual Email Notification (plus 1.3's deferred widget UI,
  built together with 3.4's endpoint).

### Round 35 — completed 3.0 Dual Email Notification + deferred 1.3 — Phase 6 done
- **3.1 — schema**: `migrations/021_tenant_support_email.sql` adds
  `tenant_support_config` (`support_email NOT NULL` — intentionally not
  nullable-with-a-fallback the way `tenant_llm_config` is, since the
  kickoff decision was "required," not "override with a fallback").
- **A dependency surfaced while building 3.4's validation**:
  `docs/Phase VI WBS.md`'s 3.4 note requires verifying a submitted
  `message_id` is the SPECIFIC message that signaled escalation, not
  just any assistant message — but `needs_escalation` was, until now,
  only ever a transient value `ask()` returned, never stored.
  `migrations/022_message_needs_escalation.sql` adds `message
  .needs_escalation` (defaults `FALSE`, not `NULL` — every existing
  message legitimately never signaled escalation, which is the
  accurate historical value); `chat.py`'s message INSERT now persists
  it.
- **3.2 — `complete_escalation()`** (`app/services/escalation.py`):
  validates email format, message exists/belongs to tenant, message is
  the specific assistant message that signaled escalation, no SR
  already exists for it, and a support-email config exists for the
  tenant — in that order. **Deliberately sends both emails BEFORE
  inserting the `service_request` row**, mirroring
  `transcript_email.py`'s "only persist after a successful send"
  philosophy: a failed send leaves a retryable state (message_id has
  no row yet), not a permanently-stuck one (`message_id` is UNIQUE on
  that table). Documented, not hidden, tradeoff: if the company email
  succeeds but the visitor's then fails, a retry produces a genuinely
  new SR number and the company gets a second, similar email — a minor
  real-world imperfection, not data loss, judged worth it for
  guaranteeing retries are never permanently blocked by a transient
  SMTP hiccup.
- **3.3 — admin endpoint**: `app/api/support_config.py` —
  `GET`/`POST /api/tenant/support-config` (`admin`+, same floor as
  every other live-config surface this project has built). UI panel
  deferred to the same backlog as the LLM-config/prompt-version
  panels.
- **3.4 — endpoint**: `POST /api/chat/{message_id}/escalate`
  (`app/api/chat.py`, anonymous) — maps `EscalationError` to
  404 (message not found)/409 (already escalated)/400 (everything
  else: bad email, wrong message, no support config).
- **1.3 (deferred from Round 33) — widget UI**: `chat.js`'s new
  `attachEscalation()` renders an inline panel (not folded into the
  meta row like feedback/sources — this needs an email input and a
  submit action, more visual room) under the assistant bubble whenever
  `needs_escalation: true` comes back from `/api/chat`.
- `tests/test_escalation_completion.py` (8 tests, exercised through
  real `ask()` calls with escalating/non-escalating stub providers,
  not hand-crafted DB rows): invalid email, unknown message, a message
  that never signaled escalation, no support config (and confirms no
  SR row gets created), successful escalation sends both emails with
  the right recipients/SR number and persists the row, a second
  attempt on the same message is rejected, **a failed send doesn't
  persist an SR and a subsequent retry succeeds** (the core tradeoff
  under test), cross-tenant message_id rejected.
  `tests/test_escalation_api.py` (7 tests): the full endpoint stack —
  happy path, 404/409/400 mapping, admin-only support-config gating,
  invalid-email rejection, and a full get/set roundtrip.
- Validated against a real MariaDB instance: full `001`→`022`
  migration chain (with the deliberate `013`-`014` gap) applies
  cleanly on a freshly rebuilt database, app imports cleanly with all
  35 routes. Full suite run 3 consecutive times against the same DB
  with no cleanup between runs: **144/144 passing every time**, no
  regressions anywhere in Phases 1-5 or Phase 6's 1.0/2.0.
- **Phase 6 (Escalation to Service Request) is done: 1.0 Escalation
  Detection, 2.0 SR Generation, 3.0 Dual Email Notification all
  complete.** Support-config admin UI panel added to the existing
  backlog alongside LLM-config/prompt-version panels. Next: Phase 7
  (Analytics & Reporting) per `docs/MASTER_PROMPT.md`.

### Round 36 — Phase 7 planning (Analytics & Reporting)
- Wrote `docs/Phase VII WBS.md`, breaking the master prompt's Phase 7
  scope into 0.0 Foundation (Token & Cost Capture — not in the master
  prompt's own list, but genuinely required before 1.0/4.0 can render
  anything), 1.0 Usage Dashboard, 2.0 Unanswered/Low-Confidence
  Question Log, 3.0 CSAT, 4.0 Per-tenant LLM Cost Tracking, 5.0
  Exportable Reports, 6.0 Testing & Validation, 7.0 Documentation &
  Handoff.
- Confirmed three kickoff decisions: **1.0 usage dashboard** is a real
  admin-console page with charts, built this phase (not deferred to
  the backlog Phase 4/6's config panels went to); **4.0 cost
  tracking** is token counts plus an estimated dollar cost via a
  hardcoded per-provider/model price table; **5.0 reports** are CSV,
  not a formatted PDF-style summary.
- **Identified and flagged a real foundational gap before writing
  1.0/4.0's details**: nothing in this codebase captures token usage
  today — `ChatProvider.chat_completion()` returns a bare string,
  discarding every provider's real usage block. This requires an
  actual interface change (return a dict instead of a string), which
  touches every existing test stub across 7 test files. Called out
  explicitly as broad-but-mechanical, same shape as Phase 5 — 1.3's
  history-parameter change, not hidden as an incidental side effect.
- **Flagged the pricing table itself as something that will go
  stale**: this session's best knowledge of current provider pricing,
  not independently verified against live pricing pages, and prices
  change over time — same "accepted, not guaranteed" framing as Phase
  5's uncapped-history risk and Phase 6's model-compliance risk.
- Confirmed 2.0 (flagged questions) and 3.0 (CSAT) need **no new
  schema** — both are computable entirely from data Phases 5/6 already
  created (`message.needs_escalation`, `citation.similarity`,
  `message_feedback`).
- **Phase 7 planning is done.** Starting 0.1 (the `ChatProvider`
  interface change) next.

### Round 36 — completed 0.0 Foundation: Token & Cost Capture (0.1-0.4)
- **0.1 — `ChatProvider` interface change**: `chat_completion()` now
  returns `{"content", "input_tokens", "output_tokens"}` instead of a
  bare string, across the base class and all three implementations —
  each parsing its own response shape's real usage block (DeepSeek/
  OpenAI: `usage.prompt_tokens`/`completion_tokens`; Anthropic:
  `usage.input_tokens`/`output_tokens`), defaulting to 0 rather than
  raising if a response is ever missing its usage block entirely.
  Added a public `PROVIDER_NAME`/`model` attribute to each provider
  class (previously private/absent) so `ask()` has something to write
  into the usage log without re-deriving it.
- **Touched every existing test stub, exactly as flagged in the WBS**:
  10 test files (`test_cross_tenant_access.py`,
  `test_escalation_api.py`, `test_escalation_completion.py`,
  `test_escalation_detection.py`, `test_message_feedback.py`,
  `test_multilanguage.py`, `test_multiturn_memory.py`,
  `test_prompt_versions.py`, `test_query_isolation.py`,
  `test_usage_limits.py`) — every stub provider (lambda-based and
  class-based) updated to return the new dict shape AND to carry
  `PROVIDER_NAME`/`model`, since `ask()`'s new usage-log write reads
  those off whatever `get_provider()` returns, real or mocked. Missed
  two on the first pass (`test_prompt_versions.py`'s two nested
  `_StubProvider` classes, `test_escalation_detection.py`'s
  `_CapturingProvider`) — caught by actually running the full suite
  rather than assuming the sweep was complete, exactly the kind of
  gap a mechanical-but-broad change risks.
- **0.2 — pricing table**: new `app/core/llm_pricing.py` —
  `PRICING` keyed by provider/model, `estimate_cost()` falling back to
  `$0` with a logged warning (not a crash) for any unrecognized
  provider/model. Flagged prominently, in the module docstring itself
  and not just this log: these figures are this session's best
  knowledge, not independently verified against live pricing pages,
  and will need periodic verification/updates.
- **0.3 — schema**: `migrations/023_llm_usage_log.sql` — one row per
  assistant message (`message_id` UNIQUE, same shape as feedback/
  escalation/SR's one-per-message tables). `estimated_cost_usd` is
  `DECIMAL(10,6)`, not `FLOAT` — deliberate, since dashboard totals sum
  many rows and floating-point summation error compounds.
- **0.4 — wired into `ask()`**: the usage-log insert happens right
  after the citation writes, using the actual token counts the
  provider returned and `estimate_cost()`'s result.
- `tests/test_llm_provider_usage.py` (5 tests, no DB needed — pure
  parsing logic with mocked `httpx.post`): each provider correctly
  extracts content/tokens from its own realistic response shape,
  Anthropic joins multiple text blocks correctly, a missing usage
  block degrades to 0 tokens rather than raising.
  `tests/test_llm_usage_capture.py` (4 tests, exercised through real
  `ask()` calls): usage log persists with correct tenant/provider/
  model/tokens, the estimated cost calculation is arithmetically
  correct against the actual pricing table, an unrecognized model
  records `$0` cost without crashing while still recording accurate
  token counts, and two separate messages each get their own usage-log
  row rather than sharing one.
- Full suite run 3 consecutive times against the same DB with no
  cleanup between runs: **153/153 passing every time**, no regressions
  anywhere in Phases 1-6.
- **0.0 Foundation is done.** Next: 1.0 Usage Dashboard (data +
  real admin-console page).

### Round 37 — completed 2.0 Website Content Sync (2.1, 2.2, 2.3)
- **Renumbering note**: this round was originally written as "Round
  29" (this session's own next number after Round 28). By the time it
  was ready to push, the other session had continued to Round 36 and
  its own history contained an unresolved duplicate "Round 28" (two
  different rounds both claiming that number, from the two sessions'
  independent counters). Renumbered on top of the other session's
  final sequence (their duplicate 28 →29, and everything after it
  shifted +1 through their Round 36) rather than leaving a second
  collision. Content below is unchanged from what was actually built
  and tested — only the round number and a few forward/backward
  cross-references moved.
- **2.1 — schema**: `migrations/013_website_sync.sql` adds
  `tenant_sync_source` — one row per configured URL, filling the
  `012`/`013`/`014` gap this repo had reserved for Phase 3 since Round
  20's planning. Added a `document_id` link not explicit in
  `docs/Phase III WBS.md`'s original text — a design decision made
  while actually building this: without it, every sync of an
  unchanged URL would either no-op with no way to find "the document
  this source already made" or, worse, create a new duplicate document
  every run. One source now maps to exactly one document, updated in
  place on re-sync (`ON DELETE SET NULL`, not `CASCADE` — deleting the
  document a source produced shouldn't delete the source config
  itself; it just goes back to "not yet synced" and recreates the
  document on its next run).
- **2.2 — crawl + diff service** (`app/services/website_sync.py`):
  fetches each configured URL directly (no recursive crawl, per the
  WBS), extracts text via the stdlib's `html.parser.HTMLParser` (no
  new dependency — confirmed `beautifulsoup4` wasn't needed for
  "strip tags, keep text"), hashes it, diffs against
  `last_content_hash`. Unchanged is a no-op. Changed content goes
  through the existing `ingest_document()` pipeline from Phase 1.
  **One decision beyond the WBS's literal text, made while building
  this and worth calling out directly**: a content change on an
  already-*published* synced document resets it to `'draft'`, not just
  a fresh unpublished document staying `'draft'`. Without this, a
  tenant could publish a synced page once and have it silently keep
  updating live forever after — exactly the "instant-live" problem
  1.0 exists to prevent, just re-introduced through the sync door
  instead of the upload door. Tested directly
  (`test_sync_source_changed_content_updates_same_document_and_resets_to_draft`).
- **2.3 — admin endpoints + UI**: `POST/GET/DELETE
  /api/documents/sync-sources` (`editor`+ to add/remove, matching
  1.0's upload floor; `viewer`+ to list) and `POST
  /api/documents/sync-sources/sync-now` (`admin`+, manual-trigger only
  per the owner's kickoff decision — no cron anywhere in this). Runs
  synchronously, not via `BackgroundTasks` like upload/reindex — an
  admin clicking "Sync now" is explicitly waiting for the result, and
  `sync_all_sources()`'s per-source try/except already keeps one
  slow/broken URL from blocking the batch. Admin UI: a new "Website
  sync" panel in `admin.html`/`admin.js` (URL list + add form + Sync
  now button showing updated/unchanged/failed counts) — built entirely
  from existing `admin.css` tokens and component classes from Round
  21's redesign, nothing new needed there.
- `tests/test_website_sync.py` added: HTML extraction (tags stripped,
  title captured), full sync lifecycle (create on first sync, no-op on
  unchanged, update-in-place + draft-reset on changed content), a
  batch sync continuing past one broken URL, URL-format and duplicate-
  URL rejection, role floors on all four endpoints, and confirming
  deleting a sync source leaves its document alone. `httpx.get` and
  `ingest_document` are both monkeypatched throughout — same "isolate
  the one I/O boundary" pattern already used for `_send_email` in
  Phase 2's transcript-email work, since this suite has no reachable
  network for real HTTP fetches or a real embedding model to call.
- Validated against a live MariaDB instance: full `001`→`013`,`015`→`022`
  migration chain (the `014` gap deliberately intact, the `012`-`013`
  gap now filled) applies cleanly on a completely fresh database, `013`
  confirmed independently re-runnable, admin page rendering confirmed
  to include the new panel via a live `TestClient` request.
  Re-validated a second time, after the renumbering above, against the
  full current chain through Phase 7's planning commit (the other
  session's latest at push time) — not just the state this was
  originally built against. Full suite run 3 consecutive times:
  **154/154 passing** every time — everything from Phase 1 through
  Phase 7's planning, no regressions anywhere.
- **2.0 Website Content Sync is done (2.1-2.3).** Phase 3 is now 1.0
  and 2.0 done, 3.0 (Duplicate/Conflict Detection) remains.

### Round 38 — completed 3.0 Duplicate/Conflict Detection (3.1, 3.2, 3.3) — Phase 3 done
- Owner said "continue" without answering the 3.0-cadence question
  Round 37 left open — proceeded with the already-documented default
  assumption (manual-trigger, matching 2.0's "Sync now" shape) rather
  than stopping to ask again for something already flagged as a
  reasonable default.
- **3.1 — schema**: `migrations/014_duplicate_detection.sql` adds
  `duplicate_flag` — one row per flagged pair, `source` distinguishing
  a title-vs-title match from a heading-vs-heading match,
  `label_a`/`label_b` storing the actual compared text so the review
  UI can show what looked similar, not just which two documents.
  `document_id_a` always the lower id of the pair (enforced in the
  service, not the DB) so a pair is never stored twice in flipped
  order. No DB-level uniqueness constraint on the label columns —
  would risk the same key-length ceiling `tenant_sync_source.url(255)`
  was built to avoid — dedup enforced at the application layer
  instead, in `_flag_exists()`.
- **3.2 — detection service** (`app/services/duplicate_detection.py`):
  `difflib.SequenceMatcher` on normalized (lowercased, punctuation-
  stripped) text, no embeddings, per the owner's "keep it simple"
  kickoff decision. **Caught a real inaccuracy before it shipped**:
  the first draft of this module's threshold comment cited invented
  similarity numbers ("Billing FAQ" vs "Billing Questions" ≈ 0.85,
  supposedly higher than "Billing FAQ" vs "Shipping FAQ" ≈ 0.75) that
  were never actually computed. Ran the real numbers before writing
  them down as documentation — the true values are 0.643 and 0.696
  respectively, meaning the *unrelated* pair actually scores higher
  than the *near-duplicate* pair on this specific example, the
  opposite of what the invented numbers claimed. Recalibrated against
  ten genuinely-computed title pairs (`docs/STATUS.md`'s own working
  notes, not repeated here) and picked `0.80` as the real threshold —
  reliably catches typo/punctuation/singular-plural variants
  ("Cancellation Policy" vs "Cancelation Policy": 0.973) while
  correctly excluding unrelated topics ("Shipping Policy" vs "Return
  Policy": 0.571). Documented an honest limitation directly in the
  module rather than only in this file: plain character-sequence
  similarity misses reworded/synonym duplicates a human would catch
  instantly ("Contact Support" vs "Contact Us": 0.72, below
  threshold) — the accepted cost of "no embeddings," not an oversight.
  **Second bug caught by the test suite itself**: `_flag_exists()`
  originally only checked *unresolved* flags before deciding whether
  to insert a new one, which meant dismissing a flag and re-running
  the scan silently recreated the exact same flag — the opposite of
  the documented "a dismissed pair doesn't come back" behavior. Fixed
  to check for any existing flag regardless of resolution state.
- **3.3 — admin endpoints + UI**: `POST /api/documents/scan-duplicates`
  (`admin`+, manual-trigger only), `GET /api/documents/duplicate-flags`
  (`viewer`+), `POST .../duplicate-flags/{id}/resolve` (`editor`+ —
  dismissing a flag is a routine review action, not an admin-only
  one). Admin UI: a "Duplicate content review" panel in
  `admin.html`/`admin.js`, built from the same existing tokens/
  component classes as every other panel — nothing new needed in
  `admin.css`.
- `tests/test_duplicate_detection.py` added: near-duplicate titles
  flagged, distinct titles not flagged, same-document headings not
  flagged against each other, cross-document near-duplicate headings
  flagged, rescanning doesn't duplicate an unresolved flag, a resolved
  flag is genuinely not recreated by a later scan (the regression test
  for the bug above), role floors on all three endpoints, full
  scan→list→resolve round trip, and a 404 for an unknown flag.
- Validated against a live MariaDB instance: full `001`→`022`
  migration chain (no more gaps — `013` and `014` both now filled)
  applies cleanly on a fresh database, `014` confirmed independently
  re-runnable, admin page rendering confirmed via a live `TestClient`
  request. Full suite run 3 consecutive times: **164/164 passing**
  every time, no regressions anywhere in Phases 1 through 7's planning.
- **3.0 Duplicate/Conflict Detection is done (3.1-3.3). Phase 3
  (Knowledge Base Management) is now fully complete — 1.0, 2.0, and
  3.0 all built and validated, superseding Round 30's "stops at 1.0"
  decision in full, not just partially.**

### Round 39 — completed 1.0-5.0: Usage Dashboard, Flagged Questions, CSAT, Cost Tracking, CSV Export — Phase 7 done
- **1.1/2.2/3.1/4.1 — aggregation service** (`app/services/analytics.py`):
  tenant- and date-range-scoped queries for conversation/answer/
  escalation counts, daily answer volume, CSAT (from
  `message_feedback`, Phase 5), cost breakdown by provider/model (from
  `llm_usage_log`, Round 36), and flagged questions — reusing
  `message.needs_escalation` (Phase 6) and `citation.similarity`
  (Phase 1) rather than introducing new schema for either, per the
  WBS's explicit "no new schema" call for 2.0/3.0. `LOW_CONFIDENCE_THRESHOLD
  = 0.3` is a default assumed, not separately confirmed at kickoff —
  flagged the same way Phase III's cadence assumption was.
- **1.2/2.3/5.1 — endpoints** (`app/api/analytics.py`): `GET
  /api/tenant/analytics/dashboard` and `/flagged-questions`
  (`viewer`+ — read-only reporting, same floor as prompt-version's
  list), `GET /export.csv` (`admin`+ — raw per-message content is more
  sensitive than aggregated numbers, so a higher floor).
- **1.3 — dashboard page**: added directly to the existing
  `templates/admin.html`/`static/js/admin.js` (an "Analytics" panel,
  matching how the concurrent session's website-sync/duplicate-
  detection panels were added to the same file, not a separate
  template) — stat cards, hand-rolled SVG bar charts (answers/day,
  cost by model) with zero external charting dependency, a flagged-
  questions list, a range selector (7/30/90 days), and a "Download
  CSV" link wired straight to 5.1's endpoint.
- `tests/test_analytics.py` (9 tests): conversation/answer/escalation
  counts, CSAT percentage arithmetic (including the no-votes-yet
  `None` case), cost breakdown and total, escalated questions get
  tagged with reasons correctly, a confident un-escalated answer with
  no citations at all is correctly NOT flagged (`NULL < threshold` is
  `NULL`/false in SQL, not true — worth its own explicit test),
  dashboard's flagged count matches the full list's length, and
  tenant isolation. `tests/test_analytics_api.py` (5 tests): auth
  floor enforcement (no session, viewer, admin), CSV header/content
  shape, and endpoint-level tenant isolation.
- Validated: admin page renders cleanly with the new panel present
  (smoke-tested via TestClient, not just visual inspection), full
  `001`→`023` migration chain applies cleanly on a freshly rebuilt
  database, full suite run 3 consecutive times with no cleanup between
  runs: **187/187 passing every time**, no regressions anywhere in
  Phases 1-6 or Phase 7's own foundation round.
- **Phase 7 (Analytics & Reporting) is done: 0.0 Foundation, 1.0 Usage
  Dashboard, 2.0 Unanswered/Low-Confidence Log, 3.0 CSAT, 4.0 Cost
  Tracking, 5.0 CSV Export all complete.** Next: Phase 8 (Admin, Ops &
  Webhooks) — the final phase in `docs/MASTER_PROMPT.md`.

### Round 40 — Phase 8 planning (Admin, Ops & Webhooks — final phase)
- Wrote `docs/Phase VIII WBS.md`, breaking the master prompt's Phase 8
  scope into 1.0 Audit Log, 2.0 Rate Limiting & Abuse Protection, 3.0
  Agent/Bot Configuration UI, 4.0 Health/Status Page, 5.0 Webhooks,
  6.0 Testing & Validation, 7.0 Documentation & Handoff — same shape
  as every phase's WBS so far.
- Confirmed three kickoff decisions: **2.0 rate limiting** is combined
  per-IP AND per-tenant limits together; **3.0 agent config** is just
  name + a freeform tone field merged into the system prompt (not an
  escalation-threshold override or a rules composer); **5.0
  webhooks** get retries with backoff and delivery logging (not
  fire-and-forget, not HMAC-signed).
- **Resolved two things beyond the kickoff questions**: (1) agent name
  already exists (`tenant_branding.agent_name`, Phase 1) but only via
  `scripts/set_tenant_branding.py` — this phase adds the missing UI +
  a new `tone` column, superseding the script for just those two
  fields. (2) webhook retries need a mechanism, but this project has
  no job queue (explicitly out of scope in `docs/MASTER_PROMPT.md`) —
  resolved via FastAPI `BackgroundTasks` (deferred in-process
  execution after the response, not a durable queue), flagged
  explicitly that a retry loop is lost on a mid-retry process
  restart, an accepted limitation of staying within that scope
  boundary.
- **Phase 8 planning is done.** Starting 1.1 (`audit_log` schema)
  next. This is the final phase in `docs/MASTER_PROMPT.md`.

### Round 41 — completed 1.0 Audit Log (1.1-1.4)
- **1.1 — schema**: `migrations/024_audit_log.sql` — scoped exactly to
  the master prompt's literal list (uploads/edits/deletes/admin
  logins), not a general-purpose event log. `admin_id` is nullable
  with `ON DELETE SET NULL`, same rationale as `api_key.created_by_
  admin_id`/`tenant_prompt_version.created_by_admin_id` — deleting the
  admin must not delete the record of what they did.
- **1.2 — logging helper** (`app/services/audit.py`):
  `log_audit_event()` (captures `X-Forwarded-For`'s first entry if
  present, else `request.client.host`) and `get_audit_log()`. Wired
  into exactly four call sites: `documents.py`'s upload (using
  `require_role_ctx` instead of `require_role` now, to get `admin_id`
  alongside `tenant_id`), review-state change ("edit"), delete, and
  `auth.py`'s successful login (only successful — a failed attempt
  already 401s before reaching the log call; logging failed attempts
  too is a reasonable security feature but broader than this phase's
  literal scope).
- **1.3 — endpoint**: `GET /api/tenant/audit-log?days=30`
  (`app/api/audit.py`, `admin`+ — who-did-what is sensitive, same
  floor as CSV export).
- **1.4 — admin UI panel**: added directly to `admin.html`/`admin.js`
  (Phase 7's shift to building real UI in-phase continues). First
  page-load-triggered `admin`+-only panel this project has — every
  other auto-loaded panel so far is `viewer`+/`editor`+, so an
  editor/viewer hitting this panel's 403 needed its own explicit,
  graceful handling (a quiet "admin access required" message) rather
  than letting `entries.forEach` throw on an error body that isn't an
  array.
- `tests/test_audit_log.py` (7 tests): login/upload/edit/delete each
  create the correct entry with correct action/entity/detail/admin
  attribution, the endpoint requires `admin`+, tenant isolation, and
  an entry survives its admin being deleted. Caught my own
  non-idempotency bug before it became a flaky-test problem: the
  admin-deletion test recreated a new admin on every rerun (since
  `_ensure_admin` looks up by email and the prior run's admin was
  gone) and accumulated matching rows — same pitfall Round 9 hit with
  the category-isolation test. Fixed with an explicit cleanup DELETE
  before reseeding.
- Full suite run 3 consecutive times against the same DB with no
  cleanup between runs: **194/194 passing every time**, plus a
  separate fresh-DB rebuild (full `001`→`024` chain) also at 194/194.
  No regressions anywhere in Phases 1-7.
- **1.0 Audit Log is done (1.1-1.4).** Next: 2.0 Rate Limiting & Abuse
  Protection.

## Open decisions / things to confirm during Phase 3

**Phase 3 is fully complete as of Round 38** — both items previously
open here are resolved: the cadence question was answered by proceeding
with the already-documented manual-trigger default (owner said
"continue" without objecting to it), and the similarity threshold
(0.80) was calibrated against real, computed examples — see Round 38's
entry for the specific numbers and the honest limitation (misses
reworded/synonym duplicates) that comes with the "no embeddings" scope
decision. Nothing left open in this phase.

### Round 41 — cross-cutting data integrity audit (not tied to a phase)
- Owner asked for a retrospective classification of every bug caught
  across the project so far, then asked to fix anything in the "data
  integrity" category specifically. Both previously-listed items
  there were already fixed at the time they were found (`sr_number`'s
  tenant-scoping, migration 012's documented one-time backfill) — so
  this round is a fresh audit for anything in the same family that
  hadn't been caught yet, not a re-fix of old news.
- **Audited every `UNIQUE` constraint across all 23 migrations**
  (grepped, then checked each one's scoping by hand) looking for
  another `sr_number`-shaped bug — a constraint that's global when it
  should be per-tenant. Found none: `tenant.slug` and
  `admin_user.email` are correctly global (they're identifiers for the
  tenant/admin record itself, not per-tenant-scoped data);
  `embedding.chunk_id` and the two `message_id`-keyed feedback/SR
  constraints are correctly global 1:1 relationships;
  `category.slug`'s old global-unique constraint (the same bug class,
  from 001_init.sql) was already found and fixed in Phase 1's Round
  4 — confirmed directly against the live DB's `SHOW INDEX` output
  that the old constraint is actually gone, not just superseded by an
  unused new one sitting alongside it.
- **Found and fixed a real, previously-uncaught race condition**:
  `prompt_versions.py`'s `create_version()` used
  `SELECT MAX(version_number) + 1` with a lock-free read, then
  INSERT — the exact same anti-pattern `escalation.py`'s own docstring
  explicitly warns against for SR numbers, just not yet applied there.
  Two concurrent calls for the same tenant could compute the same
  `next_version`, and the second INSERT would fail against
  `uq_tenant_version`. Grepped the rest of the codebase for `MAX(`
  first — this was the only instance.
- **Confirmed the bug for real** with a genuine concurrency test — 8
  real threads, real independent DB connections, a `threading.Barrier`
  to force them to actually race rather than just run sequentially
  fast. Reliably reproduced `IntegrityError: Duplicate entry` on every
  run against the unfixed code.
- **First fix attempt (`SELECT ... FOR UPDATE`) was wrong** — it does
  stop the duplicate-key corruption, but re-running the same
  concurrency test against it produced a *different* failure every
  time: `Deadlock found when trying to get lock`. `FOR UPDATE` against
  a WHERE clause matching zero existing rows still takes a gap lock
  under InnoDB's default REPEATABLE READ, and 8 threads all
  contending for the same empty gap (a brand-new tenant's first
  version) deadlock each other. Caught this only because the
  concurrency test was re-run against the "fixed" code instead of
  assuming a plausible-sounding fix was correct — a single-threaded
  sanity check (create two versions in a row, assert `[1, 2]`) would
  never have caught either the original race or this new failure
  mode, since neither bug needs true concurrency to exist, but does
  need true concurrency to *manifest*.
- **Real fix**: `migrations/025_prompt_version_seq.sql` adds
  `tenant.next_prompt_version_seq` — the same atomic-counter shape
  `sr_sequence` already established, adapted for a table (`tenant`)
  where the row being incremented always already exists, so a plain
  `UPDATE ... SET x = x + 1 WHERE id = %s` takes a definite row lock,
  never a gap lock, and concurrent callers serialize cleanly instead
  of deadlocking. Verified with the same concurrency test, run 20
  times total across this round: zero failures.
- **Migration numbering collided twice while pushing this, not
  once** — worth being honest about both, not just the one caught
  before it happened. First: built and initially numbered `023`, but
  the other session's Round 40 had already claimed
  `023_llm_usage_log.sql` by the time this was ready to push — caught
  by re-fetching origin before committing, renumbered to `024`.
  Second: after renumbering to `024` and rebasing onto the other
  session's *next* push, their own Round 41 (built concurrently,
  landed first) had claimed `024_audit_log.sql` too — a real, live
  collision this time, not caught until the rebase itself surfaced
  two files both named `024_*.sql`. Renumbered again, to
  `025_prompt_version_seq.sql`, which is also why their own planned
  Round 42 migration (`rate_limit_bucket`) needed flagging in "Next
  action" below to move from `025` to `026` before they build it —
  otherwise this same collision would have just repeated a third time,
  on their side instead of this one.
- **Separately, while reading through `test_prompt_versions.py` for
  this**: found a missing `def test_...():` line had silently merged
  an entire test — verifying the `created_by_admin_id ON DELETE SET
  NULL` data-integrity guarantee from `017_prompt_versions.sql` — into
  the tail of an unrelated test's body. `pytest --collect-only`
  confirmed only 9 tests were ever actually collected from that file,
  not 10; the merged logic executed (Python allows an orphaned
  docstring as a no-op statement) but was never its own discoverable,
  independently-failing test. Split it out properly, now 10 (11 after
  the new concurrency test).
- Rebased cleanly onto the other session's Round 40 (Phase 8
  planning) — no conflicts in `test_prompt_versions.py` despite both
  sessions editing it concurrently (they touched the `_StubProvider`
  mock shape for token-capture in different lines than this round's
  changes).
- Validated against a live MariaDB instance: full `001`→`024`
  migration chain (no gaps) applies cleanly on a fresh database, `024`
  confirmed independently re-runnable. Full suite run 3 consecutive
  times: **189/189 passing** every time. The concurrency test
  specifically run 20 times total across this round (5 before the
  final full-suite validation, 15 during initial fix iteration): zero
  failures once the real fix landed.
- No other data-integrity issues found in this audit. The two
  originally-listed ones were already fixed; this round found and
  fixed one more in the same family that hadn't been surfaced before.

## Next action

**This session's own scope is done** — the data-integrity audit and
fix above is complete; nothing further queued from this thread.

**The other session** continues with Phase 8, their own Round 42:
2.1 — a new `rate_limit_bucket` migration, then 2.4 —
`enforce_rate_limit()` in a new `app/core/rate_limit.py`, applied
only to `POST /api/chat`. **One more number to flag before they build
it**: their plan says `migrations/025_rate_limit_bucket.sql`, but
this round's rebase just renumbered the data-integrity fix's own
migration from `024` to **`025_prompt_version_seq.sql`** (to avoid
colliding with their `024_audit_log.sql`, which landed first). Their
rate-limit migration should be **`migrations/026_rate_limit_bucket.sql`**
instead — flagged here for the same reason as the `024`→`025` note
above: better to catch a numbering collision before it's built than
after.
