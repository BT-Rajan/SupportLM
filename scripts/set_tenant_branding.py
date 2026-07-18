"""Sets or updates a tenant's branding (WBS 4.1-4.3).

A full admin UI for this is out of scope for this phase (same reasoning
as scripts/create_tenant.py) — this is the working, tested path to
actually configure branding until one exists.

Usage:
  python scripts/set_tenant_branding.py <slug> [--display-name NAME]
      [--agent-name NAME] [--logo-url URL] [--accent '#7c3aed']

Only the fields you pass are changed; omitted fields are left as-is
(or NULL/default if never set). Pass an empty string to clear a field
back to its default, e.g. --accent ''.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.theme import is_valid_hex  # noqa: E402
from app.db.pool import get_conn  # noqa: E402


def set_tenant_branding(slug: str, display_name, agent_name, logo_url, accent):
    if accent is not None and accent != "" and not is_valid_hex(accent):
        print(f"Invalid accent color '{accent}': must be a 6-digit hex like '#7c3aed'.")
        sys.exit(1)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM tenant WHERE slug = %s", (slug,))
        tenant = cur.fetchone()
        if tenant is None:
            print(f"No tenant found with slug '{slug}'.")
            cur.close()
            sys.exit(1)
        tenant_id = tenant["id"]

        cur.execute("SELECT tenant_id FROM tenant_branding WHERE tenant_id = %s", (tenant_id,))
        exists = cur.fetchone() is not None

        # Empty string ('') means "clear this field back to default";
        # None means "not passed on the command line, leave as-is".
        fields = {"display_name": display_name, "agent_name": agent_name, "logo_url": logo_url, "accent_hex": accent}
        fields = {k: (None if v == "" else v) for k, v in fields.items() if v is not None}

        if not exists:
            cur.execute("INSERT INTO tenant_branding (tenant_id) VALUES (%s)", (tenant_id,))

        if fields:
            set_clause = ", ".join(f"{col} = %s" for col in fields)
            cur.execute(
                f"UPDATE tenant_branding SET {set_clause} WHERE tenant_id = %s",
                (*fields.values(), tenant_id),
            )

        cur.execute(
            "SELECT display_name, agent_name, logo_url, accent_hex FROM tenant_branding WHERE tenant_id = %s",
            (tenant_id,),
        )
        result = cur.fetchone()
        cur.close()

    print(f"Branding for '{tenant['name']}' (slug={slug}):")
    print(f"  display_name = {result['display_name'] or '(default: Support)'}")
    print(f"  agent_name   = {result['agent_name'] or '(default: Assistant)'}")
    print(f"  logo_url     = {result['logo_url'] or '(default: monogram)'}")
    print(f"  accent_hex   = {result['accent_hex'] or '(default: emerald #0e7c66)'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Set or update a tenant's branding.")
    parser.add_argument("slug", help="Tenant slug")
    parser.add_argument("--display-name", default=None, help="Widget header text (empty string clears it)")
    parser.add_argument("--agent-name", default=None, help="What the assistant calls itself (empty string clears it)")
    parser.add_argument("--logo-url", default=None, help="Logo image URL (empty string clears it)")
    parser.add_argument("--accent", default=None, help="Accent hex like '#7c3aed' (empty string clears it)")
    args = parser.parse_args()

    set_tenant_branding(args.slug, args.display_name, args.agent_name, args.logo_url, args.accent)
