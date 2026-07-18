"""Minimal auth: bcrypt password hashing + signed session cookies via
itsdangerous. No user-facing signup — the first admin is created by a
setup script (part of the installer flow)."""
import bcrypt
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.core.config import settings

_serializer = URLSafeTimedSerializer(settings.app_secret_key, salt="admin-session")
_SESSION_MAX_AGE = 60 * 60 * 8  # 8 hours


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_session_token(admin_id: int, session_version: int) -> str:
    """`session_version` is embedded at issue time so `require_admin`
    (app/core/deps.py, 3.1) can reject a token whose version no longer
    matches the current DB value — see migrations/010_session_hardening.sql
    for why a stateless signed token needs this to be revocable at all."""
    return _serializer.dumps({"admin_id": admin_id, "session_version": session_version})


def read_session_token(token: str) -> dict | None:
    """Returns the decoded claims dict, or None if the signature is
    invalid/expired. `session_version` may be missing (a token minted
    before 010_session_hardening.sql existed) — callers must treat a
    missing claim as never matching a real version, not as "skip the
    check"."""
    try:
        return _serializer.loads(token, max_age=_SESSION_MAX_AGE)
    except BadSignature:
        return None
