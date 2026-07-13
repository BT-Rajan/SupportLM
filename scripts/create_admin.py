"""Creates the first admin_user row. Run once after init_db.py.
Usage: python scripts/create_admin.py owner@company.com somepassword
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.security import hash_password  # noqa: E402
from app.db.pool import get_conn  # noqa: E402


def create_admin(email: str, password: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO admin_user (email, password_hash, role) VALUES (%s, %s, 'owner')",
            (email, hash_password(password)),
        )
        cur.close()
    print(f"Admin user created: {email}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/create_admin.py <email> <password>")
        sys.exit(1)
    create_admin(sys.argv[1], sys.argv[2])
