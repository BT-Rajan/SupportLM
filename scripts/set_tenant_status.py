"""Transitions a tenant between lifecycle states (WBS 2.2).

Usage:
  python scripts/set_tenant_status.py <slug> <active|suspended|trial>
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.pool import get_conn  # noqa: E402

_VALID_STATUSES = ("active", "suspended", "trial")


def set_tenant_status(slug: str, new_status: str):
    if new_status not in _VALID_STATUSES:
        print(f"Invalid status '{new_status}'. Must be one of: {', '.join(_VALID_STATUSES)}")
        sys.exit(1)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, status FROM tenant WHERE slug = %s", (slug,))
        row = cur.fetchone()
        if row is None:
            print(f"No tenant found with slug '{slug}'.")
            cur.close()
            sys.exit(1)

        old_status = row["status"]
        cur.execute("UPDATE tenant SET status = %s WHERE id = %s", (new_status, row["id"]))
        cur.close()

    print(f"Tenant '{row['name']}' (slug={slug}): {old_status} -> {new_status}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/set_tenant_status.py <slug> <active|suspended|trial>")
        sys.exit(1)
    set_tenant_status(sys.argv[1], sys.argv[2])
