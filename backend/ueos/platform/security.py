import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from ueos.platform.config import get_settings
from ueos.platform.errors import AuthError

_ph = PasswordHasher()  # argon2id
_DUMMY = _ph.hash("dummy-password-for-timing")
AUDIENCE = "ueos-tenant"


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(hashed: str | None, pw: str) -> bool:
    try:
        return _ph.verify(hashed or _DUMMY, pw) and hashed is not None
    except (VerificationError, InvalidHashError):
        return False


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def safe_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def make_access_token(*, user_id: str, tenant_id: str, membership_id: str, role: str, session_id: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    claims = {
        "sub": user_id, "tid": tenant_id, "mid": membership_id, "role": role, "sid": session_id,
        "aud": AUDIENCE, "iat": now, "exp": now + timedelta(minutes=s.access_ttl_minutes),
    }
    return jwt.encode(claims, s.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], audience=AUDIENCE)
    except jwt.PyJWTError as e:
        raise AuthError("invalid_token") from e


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="UEOS")


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)
