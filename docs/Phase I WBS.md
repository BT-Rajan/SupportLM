# Phase 1 — Work Breakdown Structure: Multi-tenancy & Org Foundation

> Companion to `docs/MASTER_PROMPT.md` (Section 3, Phase 1) and
> `docs/STATUS.md`. This is the task-level plan for the phase. Each
> round in `STATUS.md`'s round log should map to one or more WBS items
> below, referenced by ID (e.g. "Round 3 — completed 1.2, 1.3").

**Assumed default** (per `STATUS.md` open decisions, proceeding unless
told otherwise before 1.1 starts): shared MySQL schema with `tenant_id`
row-level scoping, not separate schemas per tenant.

---

## 1.0 Data Model & Schema

- **1.1 — Tenant/org schema design**
  New `tenant` table (id, name, slug, plan_tier, created_at, status) and
  `tenant_user` join/role table (ties into Phase 2 RBAC, but the table
  needs to exist now so ownership is assignable from Phase 1). Deliverable:
  migration file `docs/schema` proposal reviewed before writing SQL.
- **1.2 — Retrofit `tenant_id` onto existing tables**
  Add `tenant_id` (FK to `tenant.id`) to `document`, `document_chunk`,
  `embedding`, `category`, `conversation`, `message`, `citation`, `agent`,
  `company` (or fold `company` into `tenant` if they're redundant —
  confirm during 1.1). Deliverable: numbered migration, not a hand-edit
  of `001_init.sql`.
- **1.3 — Backfill migration for existing data**
  Since the current DB has one implicit tenant, write a one-time backfill
  that creates a default tenant row and stamps all existing rows with its
  `tenant_id`, so nothing currently in the DB is orphaned.
- **1.4 — Indexes for tenant-scoped queries**
  Add/verify indexes on `(tenant_id, ...)` composite keys for the
  hot-path queries (chunk search, document listing, conversation lookup)
  so scoping doesn't degrade query performance.

## 2.0 Tenant Provisioning

- **2.1 — Tenant creation flow**
  Programmatic way to create a new tenant (script or minimal endpoint) —
  full admin UI for this can wait, but there must be a working, tested
  path to stand up a new tenant before anything else in this phase is
  verifiable end-to-end.
- **2.2 — Tenant status lifecycle**
  Active / suspended / trial states on the `tenant` table, and every
  tenant-scoped route respects status (e.g. a suspended tenant's chat
  widget stops answering).

## 3.0 Data Isolation Enforcement

- **3.1 — Request-scoping middleware/dependency**
  A single, unavoidable mechanism (FastAPI dependency) that resolves the
  current `tenant_id` for every request (from subdomain, path param, or
  API key — decide which in 3.1 itself) and injects it into every query,
  rather than trusting each route handler to remember to filter.
- **3.2 — Retrofit existing queries**
  Audit and update every existing query in `app/services/*` and
  `app/api/*` to filter by the resolved `tenant_id`. This is the item
  most likely to reveal missed spots — treat it as a checklist against
  every SQL statement in the codebase, not a quick pass.
- **3.3 — Cross-tenant access tests**
  Automated tests that assert tenant A's request can never read or
  write tenant B's documents/conversations/citations. This is the
  regression net for 3.2 going forward.

## 4.0 Per-Tenant Branding

- **4.1 — Branding data model**
  Fields on `tenant` (or a `tenant_branding` table): display name, logo
  URL, accent color override, agent name — extending, not replacing,
  the token system in `docs/DESIGN_SYSTEM.md` (tenants can override
  brand name/logo/accent; the underlying component set and typography
  stay standardized per the design system rules).
- **4.2 — Chat UI branding injection**
  `templates/chat.html` reads tenant branding at render time instead of
  the hardcoded "Support" header built in the earlier redesign.
- **4.3 — Fallback/default theme**
  A tenant with no branding configured gets the current default
  (emerald/teal, "Support") rather than a broken/empty header.

## 5.0 Usage Tiers & Plan Limits

- **5.1 — Define tier structure**
  This is the open item flagged in `STATUS.md` — needs actual tier
  names and numeric limits (doc count, messages/month, seats) confirmed
  before 5.2 can be built. Deliverable of 5.1 is just the confirmed
  table, not code.
- **5.2 — Limit enforcement**
  Checks at document upload (doc count) and chat request (messages/
  month) that reject or warn once a tenant's plan limit is hit, reading
  from the 5.1 tier table.
- **5.3 — Usage counters**
  Running counters per tenant (docs stored, messages this billing
  period) that 5.2 reads from and that Phase 7 analytics will later
  surface.

## 6.0 Testing & Validation

- **6.1 — Migration rollback test**
  Confirm the 1.2/1.3 migrations can be applied to a copy of current
  production-shaped data without data loss, and that a rollback path
  exists.
- **6.2 — Multi-tenant smoke test**
  Two test tenants, each with their own documents and chat history,
  exercised end-to-end (upload → ready → chat → citation) confirming
  full isolation and correct branding per tenant.
- **6.3 — Full regression pass**
  Existing `tests/` suite plus everything added in 6.1/6.2 passes before
  Phase 1 is marked done in `STATUS.md`.

## 7.0 Documentation & Handoff

- **7.1 — Update `docs/STATUS.md`**
  Mark Phase 1 complete, log final round notes, and pre-fill the "open
  decisions" section for Phase 2 (RBAC needs the `tenant_user` table
  from 1.1 — confirm role list before Phase 2 starts).
- **7.2 — Update `docs/DESIGN_SYSTEM.md` if 4.0 introduces new patterns**
  E.g. if branding introduces a new "tenant switcher" or settings-panel
  component, document it there so Phase 2+ admin screens reuse it.

---

## Dependency order (build sequence)

```
1.1 → 1.2 → 1.3 → 1.4
        ↓
2.1 → 2.2
        ↓
3.1 → 3.2 → 3.3
        ↓
4.1 → 4.2 → 4.3        5.1 → 5.2 → 5.3
        ↓                       ↓
              6.1 → 6.2 → 6.3
                    ↓
              7.1 → 7.2
```

4.0 and 5.0 can run in parallel once 3.0 is done (both just need tenant
isolation in place, not each other). Everything funnels into 6.0 before
Phase 1 is declared complete in `STATUS.md`.
