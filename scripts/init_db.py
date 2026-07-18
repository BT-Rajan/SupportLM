"""Creates the database if it doesn't exist, then runs all .sql files in
migrations/ in filename order. Idempotency beyond that is the operator's
responsibility for now (Phase 1: run once on a fresh DB).

Usage: python scripts/init_db.py
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymysql  # noqa: E402
import pymysql.cursors  # noqa: E402

from app.core.config import settings  # noqa: E402

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "migrations")


def ensure_database_exists():
    """Connect WITHOUT selecting a database (it may not exist yet) and
    create it if needed."""
    conn = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
        print(f"Database '{settings.db_name}' ready.")
    finally:
        conn.close()


def run_migrations():
    files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
    if not files:
        print("No migration files found in migrations/ — nothing to do.")
        return

    conn = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            for path in files:
                print(f"Applying {os.path.basename(path)} ...")
                with open(path, "r") as f:
                    sql = f.read()
                # Strip SQL comments (full-line and trailing) before splitting on
                # ';' — a semicolon inside a comment would otherwise break a
                # statement in half.
                cleaned_lines = []
                for ln in sql.splitlines():
                    if "--" in ln:
                        ln = ln.split("--", 1)[0]
                    if ln.strip():
                        cleaned_lines.append(ln)
                sql = "\n".join(cleaned_lines)
                statements = [s.strip() for s in sql.split(";") if s.strip()]
                for statement in statements:
                    cur.execute(statement)
                print(f"  {len(statements)} statement(s) executed.")
            conn.commit()

            cur.execute("SHOW TABLES")
            tables = [row[f"Tables_in_{settings.db_name}"] for row in cur.fetchall()]
            print(f"Tables now in '{settings.db_name}': {', '.join(tables)}")
    except Exception as exc:
        conn.rollback()
        print(f"Migration failed, rolled back: {exc}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"Connecting to {settings.db_host}:{settings.db_port} as {settings.db_user} ...")
    try:
        ensure_database_exists()
        run_migrations()
        print("Done.")
    except pymysql.err.OperationalError as exc:
        print(f"Could not connect to MySQL: {exc}")
        print("Check that XAMPP's MySQL service is running and DB_USER/DB_PASSWORD in .env are correct.")
        sys.exit(1)
