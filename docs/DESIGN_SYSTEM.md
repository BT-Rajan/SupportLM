# SupportLM — Design System (v2 — Vue rebuild)

Canonical reference for every screen built from Phase 1 onward (admin,
analytics, agent config, escalation console, customer chat). New screens
extend this file if a component is missing — they don't invent one-off
styles inline. Goal: the product should feel like it was built by one
team with one set of rules, not a collection of per-page experiments.

**v2 supersedes v1.** Both the customer chat widget and the admin
console were rebuilt as Vue 3 apps (`frontend/`, two separate Vite
builds — see `frontend/vite.chat.config.js` / `vite.admin.config.js`).
The vanilla-JS/Jinja-rendered originals (`static/js/chat.js`,
`static/js/admin.js`, `static/css/chat.css`, `static/css/admin.css`)
are gone; `templates/chat.html` and `templates/admin.html` are now thin
shells that only inject server-resolved config
(`window.__SUPPORTLM_CONFIG__` / `window.__SUPPORTLM_ADMIN_CONFIG__`)
and mount the built bundle from `static/dist/`. Anything below citing a
`.vue` file is the new source of truth; anything citing the old `.js`/
`.css` files in git history is v1 and no longer applies.

## Tokens (source of truth: `frontend/src/styles/tokens.css`)

Shared by both the chat widget and the admin console — imported once by
each entry point (`frontend/src/main.js` and `frontend/src/admin-main.js`),
never duplicated per-file. This was flagged as a TODO in v1 ("share a
tokens.css once there are 3+ stylesheets"); it's the actual `:root` now.

```css
--ink: #15171b;
--muted: #6c7178;
--muted-soft: #9a9da3;
--bg: #f6f5f2;
--surface: #ffffff;
--surface-alt: #f1efe9;
--border: #e7e3db;
--border-strong: #d8d3c7;

--accent: #0e7c66;       /* primary actions, links, brand mark — tenant-overridable in chat only, see below */
--accent-ink: #0b5f4f;
--accent-soft: #dcefe9;

--live: #22c55e;         /* status-online indicator only */
--danger: #9c2b25;
--danger-bg: #fdecec;
--danger-border: #f3c6c4;
--warning: #8a5a12;       /* added in the v2 rebuild — was a TBD in v1, first real use is document review-state badges */
--warning-bg: #fbf0dc;
--warning-border: #eeddb2;

--font-display: "Fraunces";       /* brand name, page titles, section headers — replaces v1's Space Grotesk */
--font-body: "Inter";             /* body copy, form inputs, buttons — unchanged from v1 */
--font-mono: "IBM Plex Mono";     /* timestamps, IDs, status text, SR numbers — unchanged from v1 */

--radius-lg: 22px;   /* outer shell: chat console, auth card */
--radius-md: 16px;   /* panels, message bubbles */
--radius-sm: 10px;   /* buttons, inputs, badges, chips */

--shadow-elevated: 0 1px 1px rgba(21, 23, 27, 0.03), 0 20px 48px -24px rgba(21, 23, 27, 0.28);
--shadow-card: 0 1px 2px rgba(21, 23, 27, 0.05);
```

Error red and the accent triad keep their v1 values unchanged (existing
brand recognition wasn't worth resetting); the neutral palette, radii,
shadows, and display font are new in v2.

## Component patterns established so far

- **Card/panel**: `surface` background, 1px `border`, `radius-md`
  corners, `--shadow-card` — the base container for every panel in the
  product (`.panel` in `frontend/src/admin/styles/admin.css`).
- **Outer shell** (chat console, login card): `radius-lg` and the
  heavier `--shadow-elevated` — one level up from a panel, used once
  per screen for the thing everything else sits inside.
- **Primary button**: `accent` background, white text, `radius-sm`
  corners, `accent-ink` on hover, scale-down (0.94–0.97) on active
  press. No other button color for primary actions anywhere in the
  product.
- **Chip/tag**: `surface` background with `border`, or `accent-soft`
  background with `accent-ink` text for a "tinted" tag (`.ai-tag`,
  `.chip`, `.badge`) — used for suggestions, status labels, categories.
- **Mono utility text**: timestamps, IDs, ticket/SR numbers, and short
  status strings always render in `--font-mono`, small size (~11px),
  `--muted` or `--accent-ink` color. This is what visually distinguishes
  "system/utility" text from conversational content across the whole
  product.
- **Signature motif (v2, chat only)**: the conic-gradient "aura ring"
  around the brand avatar (`BrandAura.vue`) — used in the chat header,
  on every assistant message's avatar, and (rotating) as the composing/
  loading state, replacing v1's three-dot typing bubble and ticket-stub
  notch. Chat-specific — don't reuse it in the admin console, which has
  no equivalent "the brand is at work" moment.
- **Inline collapsible action panel** (`TranscriptPanel.vue`): a ghost
  icon button in the chat header toggles a `surface-alt` strip anchored
  to the composer, containing one text input (identical styling to
  `.composer-input`, just smaller) and one small primary button. This is
  the pattern for any future "one quick input, one action, dismissible"
  affordance attached to the chat widget — don't build a modal/overlay
  for something this small, extend this strip pattern instead.
- **Toast**: bottom-right stack (`ToastHost.vue`, admin console only),
  `surface` card with a colored left border (`accent` = success,
  `danger` = error), auto-dismiss ~4s. This is how every admin async
  action reports success/failure — don't add a second notification
  mechanism (inline banners are still used for persistent state like
  the chat widget's `limit_warning`, not for one-off action feedback).

## Per-tenant branding (unchanged mechanism, v1 WBS 4.1-4.3)

Tenants can override brand name, logo, and accent color; the underlying
component set and typography (this whole file) stay standardized. This
is NOT a second design system — it's one controlled seam into this one.
The mechanism is unchanged by the v2 rebuild:

- **The only color input a tenant gives is one accent hex.**
  `app/core/theme.py`'s `derive_palette()` produces `--accent-ink` and
  `--accent-soft` from it via the same HSL relationship the default
  emerald triad already has. Never ask a tenant to pick `--accent-ink`/
  `--accent-soft` independently.
- **Lightness is clamped to 0.28–0.62** before deriving anything, so a
  tenant can't pick a color that breaks white-on-accent contrast or
  reads as invisible. Don't remove this clamp.
- **Injection mechanism**: an inline `<style>:root{...}</style>` block
  in `templates/chat.html`'s `<head>`, after the built stylesheet link,
  overriding the same three CSS variables — later in source order wins
  the cascade with no `!important`. This is the whole "pluggable" seam,
  and it's the one part of `chat.html` that stayed server-rendered
  through the Vue rebuild rather than moving into the bundle: the Vue
  app never needs to know the accent came from a tenant override versus
  the token file's default, it just reads the CSS variable. Any new
  per-tenant-overridable token added later follows this same pattern.
- **Brand mark**: a tenant's `logo_url` renders inside `BrandAura.vue`'s
  aura-ring frame (`object-fit: contain`, since an arbitrary uploaded
  logo won't be pre-cropped to a circle). No logo → a single-letter
  monogram derived from `display_name`. Never leave the brand-mark slot
  empty.
- **Fallback is exact, not inferred**: a tenant with no branding row —
  or no value for one specific field — gets exactly today's default for
  that field (`Support` / `Assistant` / emerald `#0e7c66` / monogram),
  not a value auto-derived from the tenant's internal org name. Branding
  is opt-in per field via `tenant_branding`, never inferred from other
  tables.
- Only `templates/chat.html` reads tenant branding. The admin console
  intentionally stays on the default palette — it's an internal tool,
  not customer-facing, and mixing per-tenant branding into it would
  make screenshots/support harder to reason about across tenants.
  Revisit only if a later phase explicitly asks for a branded admin
  experience. (No API exists today to let a tenant set their own
  branding through the admin UI either — it's still `scripts/
  set_tenant_branding.py` only. Worth a future phase if that's wanted.)

## Rules for new screens

1. Pull in the same Google Fonts stack (Fraunces / Inter / IBM Plex
   Mono) — don't default to system-ui for a new screen just because
   it's "internal."
2. Reuse the token variables from `frontend/src/styles/tokens.css`
   directly; don't hardcode hex values or re-declare `:root` in a new
   file.
3. Tables: header row `surface-alt` background, `--font-mono` for
   numeric columns, `border` between rows, no zebra-striping unless a
   screen genuinely needs it for dense data (state that reasoning if
   you add it).
4. Forms: same input styling as `.field-input` / `.composer-input`
   (border, radius, `surface-alt` background, `accent` border + soft
   glow on focus) — one input style for the whole product.
5. Empty states: every list/table screen gets an empty-state pattern —
   a short title (`.empty-title`), one line of help text
   (`.empty-body`). Where the add/create form for that list already
   sits directly above it on the same screen (the admin console's
   usual layout), that form is the de facto primary action — don't add
   a redundant second CTA inside the empty-state block itself.
6. Accessibility floor carried forward to every new screen: visible
   focus rings (`:focus-visible`), `prefers-reduced-motion` respected
   for any animation, semantic HTML over div-soup.
7. New Vue components: shared, reusable chrome (buttons, inputs,
   tables, badges, panels, empty states) goes in the plain-CSS class
   system (`frontend/src/admin/styles/admin.css` for the admin console)
   and gets used via class names, not re-implemented as scoped
   component styles — that's what keeps every table/button/input
   consistent across a dozen small view components instead of each one
   drifting slightly. Reach for a `<style scoped>` block only for a
   component's genuinely one-off layout (e.g. `ChatWidget.vue`'s own
   header/thread/composer grid), not for things like button or input
   appearance.

## Admin console (rebuilt v2 as a Vue app)

`templates/admin.html` mounts `frontend/src/AdminApp.vue`, which gates
on session state (loading → login → shell) and renders a persistent
left sidebar (`Overview` / `Knowledge base` / `Audit log` / `Settings`)
plus a content area — a real IA replacing v1's single long stacked page.
Every existing backend endpoint (`app/api/*.py`) got a proper screen;
no backend routes changed as part of this rebuild:

- **Overview** (`OverviewView.vue`): stat cards, two SVG bar charts
  (`BarChart.vue` — answers/day, cost/model), flagged questions, CSV
  export. Same `get_dashboard_data()`/`get_flagged_questions()` payload
  shapes as v1.
- **Knowledge base** (`KnowledgeBaseView.vue` composing five
  sub-panels under `frontend/src/admin/components/knowledge/`):
  categories, upload, website sync sources, duplicate-content review,
  and the documents table (status badge, review-state `<select>`,
  retry/delete). The review-state control is still a plain select, not
  a wizard — editor+ can move a document to any of the three states
  directly, in either direction, same as v1.
- **Audit log** (`AuditLogView.vue`): read-only table, unchanged data
  source.
- **Settings** (`SettingsView.vue` composing four sub-panels under
  `.../settings/`): LLM provider override, prompt versions (draft +
  activate), support inbox email, API key management (create/list/
  revoke, raw key shown once on creation and never again — same
  one-time-reveal rule the backend already enforced).
- **Auth**: no dedicated "am I logged in" endpoint exists, so
  `AdminApp.vue` probes session validity with a viewer-level
  `GET /api/documents` call on load, same trick v1 used. Any `401`
  from *any* later admin API call (session expired mid-use) now also
  bounces back to the login screen via a `window` custom event
  (`supportlm-admin-unauthorized`) — v1 only checked once, on load.
- **Badges** (`.badge-draft` / `.badge-review` / `.badge-published` /
  `.badge-error`): `--font-mono`, small pill. `.badge-review` now uses
  the dedicated `--warning` token added in this rebuild instead of
  reusing `--accent-soft` — v1 had flagged a real warning color as a
  TODO; this is that TODO resolved. `--live` is still reserved for the
  chat widget's online indicator only.
- **No RBAC/role-management screen**: `tenant_user.role` (owner/admin/
  editor/viewer) can only be set today via `scripts/create_admin.py`/
  `create_tenant.py` — there's no API to invite an admin or change an
  existing one's role, so there's nothing for the console to call. The
  console doesn't pre-hide actions by the current admin's role either
  (no "who am I, what's my role" endpoint exists to know it) — it
  relies entirely on the backend's existing `require_role()` checks and
  surfaces a `403` as a toast if an action isn't permitted. Both are
  worth a future phase if a self-serve "manage my team" screen is
  wanted.
