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


def create_session_token(admin_id: int) -> str:
    return _serializer.dumps({"admin_id": admin_id})


def read_session_token(token: str) -> int | None:
    try:
        data = _serializer.loads(token, max_age=_SESSION_MAX_AGE)
        return data.get("admin_id")
    except BadSignature:
        return None
