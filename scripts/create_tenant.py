"""Creates a new tenant, optionally with an owner admin attached.

This is the programmatic tenant-creation path required by WBS 2.1 — a
full admin UI for tenant creation is out of scope for this phase. A
platform-level API endpoint can be added later once there's a
platform-admin auth model to guard it with (there isn't one yet;
admin_user/sessions are per-tenant-scoped once RBAC lands in Phase 2).

Usage:
  python scripts/create_tenant.py <name> <slug>
  python scripts/create_tenant.py <name> <slug> --owner-email E --owner-password P

If --owner-email is given and that admin doesn't exist yet, it's created
with the given password (required in that case) and linked as 'owner'.
If the admin already exists, it's just linked as 'owner' (no password
needed/used).
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymysql  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.pool import get_conn  # noqa: E402

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _validate_slug(slug: str):
    if not _SLUG_RE.match(slug):
        print(
            f"Invalid slug '{slug}': must be lowercase letters/digits, "
            "hyphen-separated (e.g. 'acme-corp')."
        )
        sys.exit(1)


def create_tenant(name: str, slug: str, owner_email: str | None, owner_password: str | None):
    _validate_slug(slug)

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO tenant (name, slug, plan_tier, status) VALUES (%s, %s, 'free', 'trial')",
                (name, slug),
            )
            tenant_id = cur.lastrowid

            admin_id = None
            if owner_email:
                cur.execute("SELECT id FROM admin_user WHERE email = %s", (owner_email,))
                row = cur.fetchone()
                if row:
                    admin_id = row["id"]
                else:
                    if not owner_password:
                        raise ValueError(
                            f"Admin '{owner_email}' doesn't exist yet — --owner-password is required to create it."
                        )
                    cur.execute(
                        "INSERT INTO admin_user (email, password_hash, role) VALUES (%s, %s, 'owner')",
                        (owner_email, hash_password(owner_password)),
                    )
                    admin_id = cur.lastrowid

                cur.execute(
                    "INSERT INTO tenant_user (tenant_id, admin_id, role) VALUES (%s, %s, 'owner')",
                    (tenant_id, admin_id),
                )
            cur.close()
    except pymysql.err.ProgrammingError as exc:
        if "doesn't exist" in str(exc):
            print("The tenant table doesn't exist yet. Run this first:")
            print("  python scripts/init_db.py")
        else:
            print(f"Database error: {exc}")
        sys.exit(1)
    except pymysql.err.IntegrityError as exc:
        if "slug" in str(exc).lower():
            print(f"A tenant with slug '{slug}' already exists.")
        else:
            print(f"Integrity error: {exc}")
        sys.exit(1)
    except ValueError as exc:
        print(str(exc))
        sys.exit(1)

    print(f"Tenant created: {name} (id={tenant_id}, slug={slug})")
    if owner_email:
        print(f"  Owner linked: {owner_email} (admin_id={admin_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a new tenant.")
    parser.add_argument("name", help="Tenant display name, e.g. 'Acme Corp'")
    parser.add_argument("slug", help="URL-safe tenant identifier, e.g. 'acme-corp'")
    parser.add_argument("--owner-email", help="Email of the admin to link as this tenant's owner")
    parser.add_argument("--owner-password", help="Password to set if --owner-email doesn't exist yet")
    args = parser.parse_args()

    create_tenant(args.name, args.slug, args.owner_email, args.owner_password)
