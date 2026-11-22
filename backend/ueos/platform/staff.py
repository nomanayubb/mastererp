"""Platform-staff realm: separate identities, separate JWT audience, separate audit stream. No implicit tenant-data access."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import text

from ueos.platform import audit
from ueos.platform.config import get_settings
from ueos.platform.db import tx
from ueos.platform.errors import AuthError, Conflict, Invalid
from ueos.platform.security import (
    hash_password,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)

STAFF_AUD = "ueos-platform"
STAFF_ROLES = ("super_admin", "registry_admin", "support_admin")


def create_staff(email: str, password: str, role: str, display_name: str = "") -> UUID:
    email = email.lower().strip()
    try:
        TypeAdapter(EmailStr).validate_python(email)
    except ValidationError as e:
        raise Invalid("invalid email address (reserved domains such as .local/.test are not accepted)") from e
    if role not in STAFF_ROLES:
        raise Invalid(f"role must be one of {STAFF_ROLES}")
    if len(password) < get_settings().min_password_length:
        raise Invalid("password too short")
    sid = uuid4()
    with tx(None) as c:
        try:
            with c.begin_nested():
                c.execute(text("insert into platform.staff (id,email,password_hash,display_name,role) values (:i,:e,:h,:d,:r)"),
                          {"i": sid, "e": email, "h": hash_password(password), "d": display_name, "r": role})
        except Exception as e:
            if getattr(getattr(e, "orig", None), "sqlstate", None) == "23505":
                raise Conflict("staff email exists") from e
            raise
        audit.record_platform(c, None, "staff.created", "staff", sid, {"email": email, "role": role})
    return sid


def login(email: str, password: str, mfa_code: str | None) -> dict[str, Any]:
    s, email = get_settings(), email.lower().strip()
    reason: str | None = None
    with tx(None) as c:
        u = c.execute(text("select * from platform.staff where email=:e"), {"e": email}).mappings().first()
        now = datetime.now(UTC)
        if u is None or u["status"] != "active":
            verify_password(None, password)
            reason = "invalid_credentials"
        elif u["locked_until"] and u["locked_until"] > now:
            reason = "account_locked"
        elif not verify_password(u["password_hash"], password):
            n = u["failed_attempts"] + 1
            lock = now + timedelta(minutes=s.lockout_minutes) if n >= s.max_failed_logins else None
            c.execute(text("update platform.staff set failed_attempts=:n, locked_until=:l where id=:i"),
                      {"n": 0 if lock else n, "l": lock, "i": u["id"]})
            reason = "invalid_credentials"
        elif u["mfa_enabled"] and not (mfa_code and verify_totp(u["mfa_secret"], mfa_code)):
            reason = "mfa_required" if not mfa_code else "invalid_mfa_code"
        else:
            c.execute(text("update platform.staff set failed_attempts=0, locked_until=null where id=:i"), {"i": u["id"]})
            audit.record_platform(c, u["id"], "staff.login")
            exp = now + timedelta(minutes=30)
            tok = jwt.encode({"sub": str(u["id"]), "role": u["role"], "aud": STAFF_AUD, "iat": now, "exp": exp},
                             s.jwt_secret, algorithm="HS256")
            return {"access_token": tok, "token_type": "bearer", "role": u["role"]}
        audit.record_platform(c, u["id"] if u else None, "staff.login_failed", data={"reason": reason, "email": email})
    raise AuthError(reason or "invalid_credentials")


def decode(token: str) -> tuple[UUID, str]:
    try:
        c = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], audience=STAFF_AUD)
    except jwt.PyJWTError as e:
        raise AuthError("invalid_token") from e
    return UUID(c["sub"]), c["role"]


def current_role(staff_id: UUID) -> str | None:
    with tx(None) as c:
        return c.execute(text("select role from platform.staff where id=:i and status='active'"), {"i": staff_id}).scalar()


def mfa_enroll(staff_id: UUID) -> dict[str, str]:
    secret = new_totp_secret()
    with tx(None) as c:
        email = c.execute(text("update platform.staff set mfa_secret=:s, mfa_enabled=false where id=:i returning email"),
                          {"s": secret, "i": staff_id}).scalar()
    return {"secret": secret, "otpauth_uri": totp_uri(secret, str(email))}


def mfa_confirm(staff_id: UUID, code: str) -> None:
    with tx(None) as c:
        secret = c.execute(text("select mfa_secret from platform.staff where id=:i"), {"i": staff_id}).scalar()
        if not secret or not verify_totp(secret, code):
            raise Invalid("invalid code")
        c.execute(text("update platform.staff set mfa_enabled=true where id=:i"), {"i": staff_id})
        audit.record_platform(c, staff_id, "staff.mfa_enabled")


def list_tenants() -> list[dict[str, Any]]:
    with tx(None) as c:
        return [{**r, "id": str(r["id"])} for r in c.execute(text("select * from platform.list_tenants()")).mappings().all()]


def set_tenant_status(actor: UUID, tenant_id: UUID, status: str) -> None:
    if status not in ("active", "suspended", "archived"):
        raise Invalid("status must be active, suspended or archived")
    with tx(tenant_id) as c:
        n = c.execute(text("update platform.tenants set status=:s where id=:i"), {"s": status, "i": tenant_id}).rowcount
        if not n:
            raise Invalid("tenant not found")
        audit.record_platform(c, actor, "tenant.status_changed", "tenant", tenant_id, {"status": status})
        audit.record(c, tenant_id, None, "tenant.status_changed_by_platform", "tenant", tenant_id, {"status": status})


def grant_entitlement(actor: UUID, tenant_id: UUID, feature_key: str, expires_at: datetime | None,
                      limits: dict[str, Any]) -> None:
    from ueos.platform import registry

    with tx(tenant_id) as c:
        if not c.execute(text("select 1 from platform.tenants where id=:i"), {"i": tenant_id}).first():
            raise Invalid("tenant not found")
        registry.validate_permission(c, feature_key, "*")
        c.execute(text("insert into platform.entitlements (id,tenant_id,feature_key,expires_at,limits) values (:i,:t,:k,:e,cast(:l as jsonb))"
                       " on conflict (tenant_id, feature_key) do update set expires_at=excluded.expires_at, limits=excluded.limits"),
                  {"i": uuid4(), "t": tenant_id, "k": feature_key, "e": expires_at, "l": __import__("json").dumps(limits)})
        audit.record_platform(c, actor, "entitlement.granted", "tenant", tenant_id, {"feature": feature_key})
        audit.record(c, tenant_id, None, "entitlement.granted_by_platform", data={"feature": feature_key})


def revoke_entitlement(actor: UUID, tenant_id: UUID, feature_key: str) -> None:
    with tx(tenant_id) as c:
        c.execute(text("delete from platform.entitlements where feature_key=:k"), {"k": feature_key})
        audit.record_platform(c, actor, "entitlement.revoked", "tenant", tenant_id, {"feature": feature_key})
        audit.record(c, tenant_id, None, "entitlement.revoked_by_platform", data={"feature": feature_key})


def list_entitlements(tenant_id: UUID) -> list[dict[str, Any]]:
    with tx(tenant_id) as c:
        return [{**r, "id": str(r["id"]), "tenant_id": str(r["tenant_id"])} for r in
                c.execute(text("select * from platform.entitlements order by feature_key")).mappings().all()]
