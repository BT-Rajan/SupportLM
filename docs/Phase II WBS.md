# Phase 2 WBS — Access Control & Anonymous-Chat Transcript Email

> Scope source: `docs/MASTER_PROMPT.md` Section 3, "Phase 2". Nothing
> here expands that scope; this file just breaks it into buildable,
> ordered rounds the way `docs/Phase I WBS.md` did for Phase 1.

Phase 2 scope, verbatim from the master prompt: RBAC (Owner/Admin/
Editor/Viewer replacing the single flat `require_admin`), API keys for
programmatic access, session management hardening. No SSO. No
end-user login — chats stay fully anonymous. New feature: at the end
of a chat, optionally email the full transcript to an address the
visitor provides (opt-in, no account required).

Dependency order: 1.0 has to land before 2.0 (API keys carry a role
from the same hierarchy 1.0 defines) and before 3.0 (session hardening
touches the same auth path RBAC re-shapes). 4.0 (transcript email) is
independent of 1.0-3.0 — anonymous chat has no admin/session/role
concept — so it can be built in parallel if picked up out of order.

## 1.0 RBAC Role Model
Extends `tenant_user.role` (placeholder `'owner'|'admin'` from Phase
1's 002 migration) into the four-tier hierarchy the master prompt
names, and replaces the flat "any authenticated admin can do anything"
model with per-action minimum-role checks.

- **1.1 Migration**: `tenant_user.role` -> `ENUM('owner','admin',
  'editor','viewer')`. `admin_user.role` (a separate, legacy column)
  is left alone — confirmed unused for authorization anywhere in the
  codebase; RBAC lives on `tenant_user` because one admin account can
  hold different roles on different tenants (Phase 1 already made
  "one admin, multiple tenants" real).
- **1.2 Role hierarchy + `require_role()` dependency**
  (`app/core/rbac.py`): `viewer < editor < admin < owner`. Builds on
  `resolve_tenant_for_admin` (calls it directly rather than
  duplicating its slug/active/membership checks) and adds a role-rank
  check on top.
- **1.3 Apply role minimums to existing admin routes**: read-only admin
  routes (list documents) -> `viewer`+; content-creating routes
  (upload, reindex, create category) -> `editor`+; destructive routes
  (delete document, delete category) -> `admin`+. Tenant-management
  actions (branding, plan tier — currently owner-only CLI scripts, no
  API route yet) stay conceptually `owner`+ for when they get routes.

## 2.0 API Keys for Programmatic Access
- **2.1 Schema** (`migrations/009_api_keys.sql`): `api_key` table —
  tenant-scoped, one role per key from 1.0's hierarchy, only a
  SHA-256 hash stored (never the raw key, same principle as password
  hashing).
- **2.2 Key management endpoints** (`app/api/api_keys.py`): create
  (returns the raw key once), list (hashes never returned), revoke.
  Minting a credential is sensitive -> `admin`+ only.
- **2.3 API-key auth path**: `require_role()` accepts either the
  existing session cookie OR an `X-API-Key` header on the same
  tenant-scoped routes — a key is checked against the tenant named in
  the URL and must not be revoked, exactly mirroring the session path's
  membership + role check.

## 3.0 Session Management Hardening
- **3.1 Server-side session invalidation**: `admin_user.session_version`
  (migration `010_session_hardening.sql`). Session tokens embed the
  version at issue time; `require_admin` rejects a token whose version
  doesn't match the current DB value — turns "delete the cookie" into
  "actually revoke," which a stateless signed token can't do alone.
- **3.2 Logout-everywhere endpoint**: `POST /api/auth/logout-all`
  bumps `session_version`, invalidating every outstanding session for
  that admin in one call.
- **3.3 Cookie hardening audit**: `secure` flag on the session cookie
  when `app_env == "production"` (was unconditionally absent before —
  fine on localhost/XAMPP dev, not fine once served over HTTPS).

## 4.0 Anonymous Chat Transcript Email
- **4.1 Schema**: `conversation.visitor_email` (migration
  `011_transcript_email.sql`) — nullable, set only if the visitor
  opts in; no account, no auth, matches "opt-in, no account required."
- **4.2 Transcript service + endpoint**
  (`app/services/transcript_email.py`, `POST /api/chat/transcript`):
  builds a plain-text transcript from `message` rows for a
  conversation, sends it over SMTP. Anonymous route (`resolve_tenant`,
  not `resolve_tenant_for_admin`) — matches the rest of the chat
  widget's auth-free surface.
- **4.3 Widget UI**: an "email me this conversation" affordance in
  `chat.html`/`chat.js`, styled from `docs/DESIGN_SYSTEM.md` tokens —
  no new colors or components invented inline.

## 5.0 Testing & Validation
Same shape as Phase 1's 6.0. Round-by-round smoke tests land alongside
each round above (`tests/test_rbac.py`, `tests/test_api_keys.py`,
`tests/test_session_hardening.py`, `tests/test_transcript_email.py`),
skip-marked like the rest of the suite when no DB is reachable. This
section is for a final full-suite pass across all of Phase 2 together,
the way 6.0 would have been for Phase 1 — owner may choose to skip it
the same way, that's a call for when 1.0-4.0 are done, not now.

## 6.0 Documentation & Handoff
`docs/STATUS.md` updated per round (not just at the end) so a
session that ends mid-phase never leaves work undocumented — same
discipline as Phase 1. `docs/DESIGN_SYSTEM.md` gets 4.3's component if
it introduces a new pattern.
