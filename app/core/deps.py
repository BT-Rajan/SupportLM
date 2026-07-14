from fastapi import Cookie, HTTPException, status

from app.core.security import read_session_token
from app.core.session import current_session_version


def require_admin(session: str | None = Cookie(default=None)) -> int:
    claims = read_session_token(session) if session else None
    if claims is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    admin_id = claims.get("admin_id")
    token_version = claims.get("session_version")
    if admin_id is None or token_version != current_session_version(admin_id):
        # Covers three cases the same way, deliberately: a pre-3.1
        # token with no session_version claim at all, a version that's
        # been bumped by logout-all (3.2) since this token was issued,
        # and an admin_id that no longer exists. All three mean "this
        # token doesn't authenticate anymore" — none of them should
        # 500 or silently succeed.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return admin_id
