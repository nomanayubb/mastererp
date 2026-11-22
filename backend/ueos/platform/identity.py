"""Registration, login, sessions (rotating refresh tokens), MFA (TOTP) and invitations."""

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from ueos.platform import audit, authz
from ueos.platform.config import get_settings
from ueos.platform.db import tx
from ueos.platform.errors import AuthError, Conflict, Invalid, NotFound
from ueos.platform.security import (
    hash_password,
    make_access_token,
    new_secret,
    new_totp_secret,
    safe_eq,
    sha256,
    totp_uri,
    verify_password,
    verify_totp,
)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,40}$")


def _check_password(pw: str) -> None:
    if len(pw) < get_settings().min_password_length:
        raise Invalid(f"password must be at least {get_settings().min_password_length} characters")


def _issue(conn: Connection, tenant_id: UUID, user_id: UUID, membership_id: UUID, role: str, ua: str | None) -> dict[str, Any]:
    sid, secret = uuid4(), new_secret()
    exp = datetime.now(UTC) + timedelta(days=get_settings().refresh_ttl_days)
    conn.execute(
        text("insert into platform.sessions (id, tenant_id, user_id, refresh_hash, user_agent, expires_at)"
             " values (:i, :t, :u, :h, :ua, :e)"),
        {"i": sid, "t": tenant_id, "u": user_id, "h": sha256(secret), "ua": ua, "e": exp},
    )
    access = make_access_token(user_id=str(user_id), tenant_id=str(tenant_id), membership_id=str(membership_id),
                               role=role, session_id=str(sid))
    return {"access_token": access, "refresh_token": f"{tenant_id}.{sid}.{secret}", "token_type": "bearer",
            "tenant_id": str(tenant_id), "role": role}


def register_tenant(*, tenant_name: str, slug: str, email: str, password: str, display_name: str,
                    ua: str | None = None) -> dict[str, Any]:
    slug, email = slug.lower().strip(), email.lower().strip()
    if not SLUG_RE.match(slug):
        raise Invalid("slug must be 3-41 chars: lowercase letters, digits, hyphens")
    _check_password(password)
    tid, uid, mid = uuid4(), uuid4(), uuid4()
    with tx(tid) as c:
        if c.execute(text("select 1 from platform.users where email = :e"), {"e": email}).first():
            raise Conflict("email already registered; log in and create the tenant from your account")
        try:
            c.execute(text("insert into platform.tenants (id, slug, name) values (:i, :s, :n)"),
                      {"i": tid, "s": slug, "n": tenant_name})
        except Exception as e:  # unique slug
            if getattr(getattr(e, "orig", None), "sqlstate", None) == "23505":
                raise Conflict("tenant slug already taken") from e
            raise
        c.execute(text("insert into platform.users (id, email, password_hash, display_name) values (:i,:e,:h,:d)"),
                  {"i": uid, "e": email, "h": hash_password(password), "d": display_name})
        c.execute(text("insert into platform.memberships (id, tenant_id, user_id, role) values (:i,:t,:u,'owner')"),
                  {"i": mid, "t": tid, "u": uid})
        authz.seed_system_roles(c, tid)
        authz.assign_base_role(c, tid, mid, "owner", uid)
        audit.record(c, tid, uid, "tenant.registered", "tenant", tid, {"slug": slug})
        return _issue(c, tid, uid, mid, "owner", ua)


def login(*, tenant_slug: str, email: str, password: str, mfa_code: str | None, ua: str | None = None) -> dict[str, Any]:
    s, email = get_settings(), email.lower().strip()
    with tx(None) as c:
        tid = c.execute(text("select platform.tenant_id_by_slug(:s)"), {"s": tenant_slug.lower()}).scalar()
    if not tid:
        verify_password(None, password)  # equalise timing
        raise AuthError("invalid_credentials")
    reason: str | None = None
    with tx(tid) as c:
        u = c.execute(text("select * from platform.users where email = :e"), {"e": email}).mappings().first()
        now = datetime.now(UTC)
        if u is None:
            verify_password(None, password)
            reason = "invalid_credentials"
        elif u["locked_until"] and u["locked_until"] > now:
            reason = "account_locked"
        elif not verify_password(u["password_hash"], password):
            n = u["failed_attempts"] + 1
            lock = now + timedelta(minutes=s.lockout_minutes) if n >= s.max_failed_logins else None
            c.execute(text("update platform.users set failed_attempts=:n, locked_until=:l where id=:i"),
                      {"n": 0 if lock else n, "l": lock, "i": u["id"]})
            reason = "invalid_credentials"
        else:
            m = c.execute(text("select id, role, status from platform.memberships where user_id = :u"),
                          {"u": u["id"]}).mappings().first()
            if not m or m["status"] != "active":
                reason = "invalid_credentials"
            elif u["mfa_enabled"] and not (mfa_code and verify_totp(u["mfa_secret"], mfa_code)):
                reason = "mfa_required" if not mfa_code else "invalid_mfa_code"
            else:
                c.execute(text("update platform.users set failed_attempts=0, locked_until=null where id=:i"), {"i": u["id"]})
                audit.record(c, tid, u["id"], "auth.login")
                return _issue(c, tid, u["id"], m["id"], m["role"], ua)
        audit.record(c, tid, u["id"] if u else None, "auth.login_failed", data={"reason": reason, "email": email})
    raise AuthError(reason or "invalid_credentials")


def refresh(token: str) -> dict[str, Any]:
    try:
        tid_s, sid_s, secret = token.split(".", 2)
        tid, sid = UUID(tid_s), UUID(sid_s)
    except ValueError as e:
        raise AuthError("invalid_refresh_token") from e
    with tx(tid) as c:
        r = c.execute(text("select * from platform.sessions where id=:i and revoked_at is null and expires_at>now()"),
                      {"i": sid}).mappings().first()
        if not r:
            raise AuthError("invalid_refresh_token")
        h = sha256(secret)
        if r["prev_refresh_hash"] and safe_eq(h, r["prev_refresh_hash"]):  # reuse of a rotated token => theft
            c.execute(text("update platform.sessions set revoked_at=now() where id=:i"), {"i": sid})
            audit.record(c, tid, r["user_id"], "auth.refresh_reuse_detected", "session", sid)
        elif not safe_eq(h, r["refresh_hash"]):
            raise AuthError("invalid_refresh_token")
        else:
            m = c.execute(text("select id, role, status from platform.memberships where user_id=:u"),
                          {"u": r["user_id"]}).mappings().first()
            if not m or m["status"] != "active":
                raise AuthError("invalid_refresh_token")
            new = new_secret()
            c.execute(text("update platform.sessions set prev_refresh_hash=refresh_hash, refresh_hash=:h where id=:i"),
                      {"h": sha256(new), "i": sid})
            access = make_access_token(user_id=str(r["user_id"]), tenant_id=str(tid), membership_id=str(m["id"]),
                                       role=m["role"], session_id=str(sid))
            return {"access_token": access, "refresh_token": f"{tid}.{sid}.{new}", "token_type": "bearer",
                    "tenant_id": str(tid), "role": m["role"]}
    raise AuthError("invalid_refresh_token")  # reached only after reuse detection (revocation committed above)


def logout(tenant_id: UUID, session_id: UUID, user_id: UUID) -> None:
    with tx(tenant_id) as c:
        c.execute(text("update platform.sessions set revoked_at=now() where id=:i"), {"i": session_id})
        audit.record(c, tenant_id, user_id, "auth.logout", "session", session_id)


def session_active(tenant_id: UUID, session_id: UUID, membership_id: UUID) -> str | None:
    """Returns the membership's current role if session and membership are valid, else None."""
    with tx(tenant_id) as c:
        return c.execute(
            text("select m.role from platform.sessions s join platform.memberships m on m.user_id = s.user_id"
                 " where s.id=:s and s.revoked_at is null and s.expires_at>now() and m.id=:m and m.status='active'"),
            {"s": session_id, "m": membership_id}).scalar()


def mfa_enroll(tenant_id: UUID, user_id: UUID) -> dict[str, str]:
    secret = new_totp_secret()
    with tx(tenant_id) as c:
        email = c.execute(text("update platform.users set mfa_secret=:s, mfa_enabled=false where id=:i returning email"),
                          {"s": secret, "i": user_id}).scalar()
        audit.record(c, tenant_id, user_id, "auth.mfa_enroll_started")
    return {"secret": secret, "otpauth_uri": totp_uri(secret, str(email))}


def mfa_confirm(tenant_id: UUID, user_id: UUID, code: str) -> None:
    with tx(tenant_id) as c:
        secret = c.execute(text("select mfa_secret from platform.users where id=:i"), {"i": user_id}).scalar()
        if not secret or not verify_totp(secret, code):
            raise Invalid("invalid code")
        c.execute(text("update platform.users set mfa_enabled=true where id=:i"), {"i": user_id})
        audit.record(c, tenant_id, user_id, "auth.mfa_enabled")


def create_invitation(tenant_id: UUID, inviter: UUID, email: str, role: str) -> dict[str, Any]:
    email = email.lower().strip()
    if role not in ("admin", "member"):
        raise Invalid("role must be admin or member")
    token = new_secret()
    iid = uuid4()
    with tx(tenant_id) as c:
        c.execute(text("insert into platform.invitations (id, tenant_id, email, role, token_hash, invited_by, expires_at)"
                       " values (:i,:t,:e,:r,:h,:b, now() + interval '7 days')"),
                  {"i": iid, "t": tenant_id, "e": email, "r": role, "h": sha256(token), "b": inviter})
        audit.record(c, tenant_id, inviter, "user.invited", "invitation", iid, {"email": email, "role": role})
    # No email service until M7: token is returned to the inviting admin only.
    return {"invitation_id": str(iid), "token": token, "email": email, "role": role}


def accept_invitation(token: str, password: str, display_name: str, ua: str | None = None) -> dict[str, Any]:
    h = sha256(token)
    with tx(None) as c:
        tid = c.execute(text("select platform.invitation_tenant(:h)"), {"h": h}).scalar()
    if not tid:
        raise NotFound("invitation invalid or expired")
    with tx(tid) as c:
        inv = c.execute(text("select * from platform.invitations where token_hash=:h and accepted_at is null"
                             " and expires_at>now() for update"), {"h": h}).mappings().first()
        if not inv:
            raise NotFound("invitation invalid or expired")
        u = c.execute(text("select id, password_hash from platform.users where email=:e"), {"e": inv["email"]}).mappings().first()
        if u:
            if not verify_password(u["password_hash"], password):
                raise AuthError("invalid_credentials")
            uid = u["id"]
        else:
            _check_password(password)
            uid = uuid4()
            c.execute(text("insert into platform.users (id,email,password_hash,display_name) values (:i,:e,:h,:d)"),
                      {"i": uid, "e": inv["email"], "h": hash_password(password), "d": display_name})
        mid = uuid4()
        try:
            c.execute(text("insert into platform.memberships (id,tenant_id,user_id,role) values (:i,:t,:u,:r)"),
                      {"i": mid, "t": tid, "u": uid, "r": inv["role"]})
        except Exception as e:
            if getattr(getattr(e, "orig", None), "sqlstate", None) == "23505":
                raise Conflict("already a member of this tenant") from e
            raise
        authz.assign_base_role(c, tid, mid, inv["role"], inv["invited_by"])
        c.execute(text("update platform.invitations set accepted_at=now() where id=:i"), {"i": inv["id"]})
        audit.record(c, tid, uid, "user.invitation_accepted", "membership", mid)
        return _issue(c, tid, uid, mid, inv["role"], ua)


def list_members(tenant_id: UUID) -> list[dict[str, Any]]:
    with tx(tenant_id) as c:
        rows = c.execute(text("select m.id, m.role, m.status, u.email, u.display_name from platform.memberships m"
                              " join platform.users u on u.id = m.user_id order by u.email")).mappings().all()
    return [{**r, "id": str(r["id"])} for r in rows]


def disable_member(tenant_id: UUID, actor: UUID, membership_id: UUID) -> None:
    with tx(tenant_id) as c:
        m = c.execute(text("select role, user_id from platform.memberships where id=:i"), {"i": membership_id}).mappings().first()
        if not m:
            raise NotFound("member not found")
        if m["role"] == "owner":
            raise Invalid("owner cannot be disabled")
        c.execute(text("update platform.memberships set status='disabled' where id=:i"), {"i": membership_id})
        c.execute(text("update platform.sessions set revoked_at=now() where user_id=:u and revoked_at is null"), {"u": m["user_id"]})
        audit.record(c, tenant_id, actor, "user.disabled", "membership", membership_id)
