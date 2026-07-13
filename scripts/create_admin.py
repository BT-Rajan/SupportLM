"""Creates the first admin_user row. Run once after init_db.py.
Usage: python scripts/create_admin.py owner@company.com somepassword
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymysql  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.pool import get_conn  # noqa: E402


def create_admin(email: str, password: str):
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO admin_user (email, password_hash, role) VALUES (%s, %s, 'owner')",
                (email, hash_password(password)),
            )
            cur.close()
        print(f"Admin user created: {email}")
    except pymysql.err.ProgrammingError as exc:
        if "doesn't exist" in str(exc):
            print("The admin_user table doesn't exist yet. Run this first:")
            print("  python scripts/init_db.py")
        else:
            print(f"Database error: {exc}")
        sys.exit(1)
    except pymysql.err.IntegrityError:
        print(f"An admin with email '{email}' already exists.")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/create_admin.py <email> <password>")
        sys.exit(1)
    create_admin(sys.argv[1], sys.argv[2])
