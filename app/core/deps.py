from fastapi import Cookie, HTTPException, status

from app.core.security import read_session_token


def require_admin(session: str | None = Cookie(default=None)) -> int:
    admin_id = read_session_token(session) if session else None
    if admin_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return admin_id
