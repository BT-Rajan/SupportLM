from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from app.core.security import create_session_token, verify_password
from app.db.pool import get_conn

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(req: LoginRequest, response: Response):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, password_hash FROM admin_user WHERE email = %s", (req.email,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE admin_user SET last_login_at = NOW() WHERE id = %s", (row["id"],))
        cur.close()

    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_session_token(row["id"])
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=60 * 60 * 8)
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("session")
    return {"ok": True}
