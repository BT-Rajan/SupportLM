from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.deps import require_admin
from app.core.security import create_session_token, verify_password
from app.core.session import bump_session_version
from app.core.tenant_scope import resolve_tenant
from app.db.pool import get_conn

router = APIRouter(prefix="/api/auth", tags=["auth"], dependencies=[Depends(resolve_tenant)])

# WBS 3.3: cookie hardening audit. `secure` was unconditionally absent
# before this round — fine on localhost/XAMPP dev (plain HTTP), not
# fine once this is served over HTTPS in production, where a cookie
# without `secure` can be sent over a downgraded/plain connection by a
# network attacker. Conditional, not unconditional True, because
# XAMPP dev over plain http:// would silently never send the cookie
# back at all if this were hardcoded on.
_COOKIE_SECURE = settings.app_env == "production"


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(req: LoginRequest, response: Response):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, password_hash, session_version FROM admin_user WHERE email = %s",
            (req.email,),
        )
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE admin_user SET last_login_at = NOW() WHERE id = %s", (row["id"],))
        cur.close()

    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_session_token(row["id"], row["session_version"])
    response.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="lax",
        secure=_COOKIE_SECURE,
        max_age=60 * 60 * 8,
    )
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("session")
    return {"ok": True}


@router.post("/logout-all")
def logout_all(response: Response, admin_id: int = Depends(require_admin)):
    """WBS 3.2: bumps admin_user.session_version, which invalidates
    every outstanding session for this admin in one call — including
    the one making this request, since its token carries the
    now-stale version too. That's intentional: "log out everywhere"
    should mean everywhere, not everywhere-except-here."""
    bump_session_version(admin_id)
    response.delete_cookie("session")
    return {"ok": True}
