# SupportLM — Design System

Canonical reference for every screen built from Phase 1 onward (admin,
analytics, agent config, escalation console, customer chat). New screens
extend this file if a component is missing — they don't invent one-off
styles inline. Goal: the product should feel like it was built by one
team with one set of rules, not a collection of per-page experiments.

## Tokens (source of truth: `frontend/src/styles/tokens.css`)

Both the chat widget and the admin console are Vue builds now (see
"Admin console" section below — the customer-facing chat widget went
through the same "built but never wired in" bug the admin console once
had; both are fixed now, and the pre-Vue `static/css/chat.css` /
`static/js/chat.js` have been removed rather than left as unreferenced
dead code). `tokens.css` is imported by both `main.js` and
`admin-main.js`, so it's the one file that has to change to move every
screen's palette at once — don't let it drift from what's actually
shipped in `static/dist/*.css` again.

v3 — premium enterprise refresh (previously an emerald/Fraunces
"luxury" palette; before that, an unfollowed system-ui/indigo baseline
— see the Admin console section below). Flat elevation, no heavy
gradients, cool neutral grays, Inter-only type. Dark mode lives under
`[data-theme="dark"]` on `<html>` (values below); the toggle that sets
that attribute is wired up in a later pass.

```css
--ink: #111827;          /* primary text */
--muted: #6b7280;        /* secondary text, timestamps, helper copy */
--muted-soft: #9ca3af;   /* tertiary/disabled text */
--bg: #fafafa;           /* page background */
--surface: #ffffff;      /* card/panel background */
--surface-alt: #f5f6f8;  /* recessed areas: message thread, inputs */
--border: #e5e7eb;
--border-strong: #d1d5db;

--accent: #2563eb;       /* primary actions, links, brand mark */
--accent-ink: #1d4ed8;   /* hover/active state of accent */
--accent-soft: #eaf1fd;  /* tinted backgrounds: user bubbles, tags */

--live: #10b981;         /* status-online indicator only */

--font-display: "Inter";       /* brand name, page titles, section headers */
--font-body: "Inter";          /* body copy, form inputs, buttons — same face as display now */
--font-mono: "JetBrains Mono"; /* timestamps, IDs, status text, SR numbers */

--radius-sm: 8px;        /* inputs, small controls */
--radius: 12px;          /* default corner radius for cards/bubbles */
--radius-lg: 16px;       /* larger panels */
--radius-xl: 20px;       /* dialogs */
```

Semantic colors for state (add here when first needed, don't invent
inline hex values in a component file):
- Success: `--live` (#10b981)
- Error/danger: `--danger` (#ef4444) text on `--danger-bg` (#fdecec)
  background, `--danger-border` (#f7c9c9) border (already used for
  chat error bubbles — reuse exactly, don't create a second red)
- Warning: `--warning` (#f59e0b) on `--warning-bg` (#fdf3df),
  `--warning-border` (#f2ddab) — used by admin review-state badges.

Gradients are deliberately gone from every surface (brand marks,
buttons, the composer send control, the topbar/header) — flat fills
only, per the flat-elevation design principle. Don't reintroduce a
`linear-gradient`/`radial-gradient` on a new component without a
strong reason; if elevation is needed, reach for `--shadow-card` /
`--shadow-soft` / `--shadow-elevated` instead.

## Component patterns established so far

- **Card/panel**: `surface` background, 1px `border`, `radius` corners,
  soft layered shadow (see `.console` in chat.css for the exact shadow
  values) — this is the base container for every panel in the product.
- **Primary button**: `accent` background, white text, `radius`-scaled
  corner (~12px for buttons), `accent-ink` on hover, scale-down (0.94–0.98)
  on active press. No other button color for primary actions anywhere in
  the product.
- **Chip/tag**: `surface` background with `border`, or `accent-soft`
  background with `accent-ink` text for a "tinted" tag (see `.ai-tag`,
  `.chip`) — used for suggestions, status labels, categories.
- **Mono utility text**: timestamps, IDs, ticket/SR numbers, and short
  status strings always render in `--font-mono`, small size (~11px),
  `--muted` or `--accent-ink` color. This is what visually distinguishes
  "system/utility" text from conversational content across the whole
  product — keep it consistent everywhere a new numeric/status field
  shows up (SR numbers in Phase 6, cost figures in Phase 7, etc).
- **Signature motif**: the clipped ticket-stub corner on assistant chat
  bubbles (`.msg-assistant` in chat.css) is specific to chat messages
  only — don't reuse the notch shape for unrelated cards; it means
  "this came from the support/ticket system," not "generic panel."
- **Inline collapsible action panel** (WBS 4.3, `.transcript-panel` in
  chat.css): a ghost icon button in the header (`.transcript-btn` —
  `surface` background, `border`, `muted` icon color, `accent`/
  `accent-soft` on hover and while its panel is open) toggles a
  `surface-alt` strip anchored to the composer, containing one
  `.transcript-input` (identical styling to `.composer-input`, just
  smaller) and one small primary button. This is the pattern for any
  future "one quick input, one action, dismissible" affordance
  attached to the chat widget — don't build a modal/overlay for
  something this small, extend this strip pattern instead. Status
  feedback for the action reuses `--font-mono`/small-size (matching
  the existing "system/utility text" rule above) and the existing
  error red / `accent-ink` success color — no new colors introduced.

## Per-tenant branding (WBS 4.1-4.3)

Tenants can override brand name, logo, and accent color; the underlying
component set and typography (this whole file) stay standardized. This
is NOT a second design system — it's one controlled seam into this one.

- **The only color input a tenant gives is one accent hex.**
  `app/core/theme.py`'s `derive_palette()` produces `--accent-ink` and
  `--accent-soft` from it via the same HSL relationship the default
  emerald triad already has (darken ~12 percentage points of lightness
  for ink; desaturate + lighten to ~92% lightness for soft). Never ask
  a tenant to pick `--accent-ink`/`--accent-soft` independently —
  three independent pickers is how a tenant ends up with a clashing
  palette; one input color is how every tenant's result stays
  internally consistent with itself.
- **Lightness is clamped to 0.28–0.62** before deriving anything, so a
  tenant can't pick a pale color that breaks white-on-accent contrast
  on `.composer-send` / `.msg-user`, or a near-black that reads as
  invisible. The quality floor holds regardless of tenant input —
  don't remove this clamp to give tenants "more freedom."
- **Injection mechanism**: an inline `<style>:root{...}</style>` block
  in the `<head>`, after the base stylesheet link, overriding the same
  three CSS variables. Later in source order wins the cascade with no
  `!important` — this is the whole "pluggable" seam. Any new
  per-tenant-overridable token added later follows this same pattern:
  add it to `DEFAULT_THEME` in `theme.py`, resolve it in
  `resolve_theme()`, inject it in the same style block. Don't invent a
  second injection mechanism (e.g. a `data-theme` attribute + CSS
  selectors) for a new token — extend this one.
- **Brand mark**: a tenant's `logo_url` renders as an `<img>` in the
  same 36×36 footprint as the default monogram square
  (`.brand-mark-logo` in chat.css — `object-fit: contain` + a border,
  since an arbitrary uploaded logo won't be pre-cropped to a square).
  No logo → a single-letter monogram derived from `display_name`,
  same treatment as today's "S". Never leave the brand-mark slot empty.
- **Fallback is exact, not inferred**: a tenant with no branding row —
  or no value for one specific field — gets exactly today's default
  for that field (`Support` / `Assistant` / blue `#2563eb` /
  monogram), not a value auto-derived from the tenant's internal org
  name (`tenant.name`). That name may not even be customer-facing copy
  (e.g. "Acme Corp LLC (Trial)"). Branding is opt-in per field via
  `tenant_branding`, never inferred from other tables.
- Only `templates/chat.html` reads tenant branding today. The admin
  dashboard intentionally stays on the default theme — it's an
  internal tool, not customer-facing, and mixing per-tenant branding
  into it would make screenshots/support harder to reason about across
  tenants. Revisit only if a later phase explicitly asks for a branded
  admin experience.

## Rules for new screens (admin dashboard, analytics, agent config, etc.)

1. Pull in the same Google Fonts stack (Inter + JetBrains Mono) — don't
   default to system-ui for a new screen just because it's "internal."
2. Reuse the token variables directly; don't hardcode hex values in a new
   CSS file. If a new page needs a new file, `:root` should still resolve
   to the same values (share a `tokens.css` once there are 3+ stylesheets
   — flag this refactor when it comes up rather than copy-pasting the
   `:root` block a fourth time).
3. Tables (needed from Phase 1 admin screens onward): header row
   `surface-alt` background, `--font-mono` for numeric columns, `border`
   between rows, no zebra-striping unless a screen genuinely needs it for
   dense data (state that reasoning if you add it).
4. Forms: same input styling as `.composer-input` (border, radius,
   `surface-alt` background, `accent` border on focus) — one input style
   for the whole product.
5. Empty states: every list/table screen gets an empty-state pattern
   analogous to `.welcome` in the chat UI — a short title, one line of
   help text, and a primary action — not just a blank table.
6. Accessibility floor carried forward to every new screen: visible
   focus rings (`:focus-visible` block), `prefers-reduced-motion`
   respected for any animation, semantic HTML over div-soup.

## Admin console (built Phase 3, WBS 1.3)

`templates/admin.html` / `static/css/admin.css` / `static/js/admin.js`
were the first real application of the six rules above — they'd sat
unfollowed since whenever this section was written; the admin console
predated the design system entirely (system-ui font, hardcoded
`#4f46e5`/`#dc2626`, no tokens). Rebuilt onto the same `:root` block as
`chat.css` (duplicated, not shared — see rule 2's own note: still only
2 stylesheets, the "3+" trigger for extracting `tokens.css` hasn't
fired).

- **Badges** (`.badge-draft` / `.badge-review` / `.badge-published` /
  `.badge-error`): `--font-mono`, small pill, reusing the exact
  `--accent`/`--accent-soft`/error-red already established by
  `.ai-tag` and `.transcript-status` — no new colors introduced, and
  `--live` is deliberately not used here (reserved for the chat
  widget's online indicator only).
- **Review-state control**: a plain `<select>` per document row, not
  a multi-step wizard or forward-only button chain — matches the
  owner's 1.0 decision that editor+ can move a document to any of the
  three states directly, in either direction.
- **Rule 5 (empty states), one deliberate deviation**: the "primary
  action" a `.empty-state` normally needs is the add/upload form
  directly above it on the same screen, not a duplicate CTA inside
  the empty-state block itself. Different from `.welcome` in the chat
  widget, where the composer is a separate pane below the fold — here
  the form and the list it populates share one screen with nothing
  between them, so a second button pointing at the same form immediately
  above would be redundant, not clarifying.
