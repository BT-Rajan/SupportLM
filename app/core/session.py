"""Server-side session state (Phase 2 WBS 3.1/3.2).

Split out from `app/core/security.py` (pure crypto: hashing, signing —
no DB access) and `app/core/deps.py` (the thin `require_admin`
dependency itself) — this module is the one place that reads or
writes `admin_user.session_version`, the same one-concern-per-module
shape as `tenant_access.py` / `tenant_scope.py` / `theme.py`.
"""
from app.db.pool import get_conn, get_cursor


def current_session_version(admin_id: int) -> int | None:
    """The admin's current `session_version`, or None if the admin_id
    doesn't exist (e.g. the account was deleted after the token was
    issued) — `require_admin` treats both "doesn't exist" and "version
    mismatch" the same way: reject."""
    with get_cursor() as cur:
        cur.execute("SELECT session_version FROM admin_user WHERE id = %s", (admin_id,))
        row = cur.fetchone()
    return row["session_version"] if row else None


def bump_session_version(admin_id: int) -> int:
    """Invalidate every outstanding session for this admin by
    incrementing the version every issued token is checked against.
    Returns the new version (not currently used by the caller, but
    matches the rest of the codebase's habit of returning the
    post-write state rather than nothing)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE admin_user SET session_version = session_version + 1 WHERE id = %s",
            (admin_id,),
        )
        cur.execute("SELECT session_version FROM admin_user WHERE id = %s", (admin_id,))
        row = cur.fetchone()
        cur.close()
    return row["session_version"]
