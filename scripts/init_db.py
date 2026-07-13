"""Runs all .sql files in migrations/ in filename order. Idempotency is
the operator's responsibility for now (Phase 1: run once on a fresh DB)."""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.pool import get_conn  # noqa: E402

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "migrations")


def run_migrations():
    files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
    if not files:
        print("No migration files found.")
        return

    with get_conn() as conn:
        cur = conn.cursor()
        for path in files:
            print(f"Applying {os.path.basename(path)} ...")
            with open(path, "r") as f:
                sql = f.read()
            for statement in filter(None, (s.strip() for s in sql.split(";"))):
                cur.execute(statement)
        cur.close()
    print("Done.")


if __name__ == "__main__":
    run_migrations()
