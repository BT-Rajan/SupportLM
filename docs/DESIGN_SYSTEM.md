# SupportLM — Design System

Canonical reference for every screen built from Phase 1 onward (admin,
analytics, agent config, escalation console, customer chat). New screens
extend this file if a component is missing — they don't invent one-off
styles inline. Goal: the product should feel like it was built by one
team with one set of rules, not a collection of per-page experiments.

## Tokens (source of truth: `static/css/chat.css`)

```css
--ink: #16211d;          /* primary text */
--muted: #64756e;        /* secondary text, timestamps, helper copy */
--bg: #eaeeec;           /* page background */
--surface: #ffffff;      /* card/panel background */
--surface-alt: #f2f5f3;  /* recessed areas: message thread, inputs */
--border: #dbe3de;

--accent: #0e7c66;       /* primary actions, links, brand mark */
--accent-ink: #0b5f4f;   /* hover/active state of accent */
--accent-soft: #dcefe9;  /* tinted backgrounds: user bubbles, tags */

--live: #22c55e;         /* status-online indicator only */

--font-display: "Space Grotesk";  /* brand name, page titles, section headers */
--font-body: "Inter";             /* body copy, form inputs, buttons */
--font-mono: "IBM Plex Mono";     /* timestamps, IDs, status text, SR numbers */

--radius: 14px;          /* default corner radius for cards/bubbles */
```

Semantic colors for state (add here when first needed, don't invent
inline hex values in a component file):
- Success: `--live` (#22c55e)
- Error/danger: `#9c2b25` text on `#fdecec` background, `#f3c6c4` border
  (already used for chat error bubbles — reuse exactly, don't create a
  second red)
- Warning: to be added in Phase 3 (draft/review states) — pick once,
  document here, reuse everywhere.

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
  for that field (`Support` / `Assistant` / emerald `#0e7c66` /
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

1. Pull in the same Google Fonts stack (Space Grotesk / Inter / IBM Plex
   Mono) — don't default to system-ui for a new screen just because it's
   "internal."
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
