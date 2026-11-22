"""Authorization engine. Deny by default.

Pipeline: tenant active -> entitlement (app/feature) -> RBAC grant (feature pattern + action) -> static ABAC (hours)
-> [handler] dynamic ABAC (amount limit, no self-approval, own records) -> record scope (SQL predicate) -> field masking.

Permission = (feature pattern, action, constraints). Pattern: exact key, 'app.*' prefix wildcard, or '*'.
Assignment = role + optional scope {company_ids, branch_ids, department_ids} + optional expiry (temporary delegation).
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from ueos.platform import audit, registry
from ueos.platform.db import tx
from ueos.platform.errors import Conflict, Forbidden, Invalid, NotFound
from ueos.platform.principal import Principal

ALLOWED_CONSTRAINTS = {"max_amount", "hours", "no_self_approval", "own_records_only", "hide_fields"}

SYSTEM_ROLES: dict[str, list[tuple[str, str]]] = {
    "Owner": [("*", "*")],
    "Admin": [("platform.*", "*")],
    "Member": [
        ("platform.tenant.settings", "view"),
        ("platform.users.members", "view"),
        ("platform.org.*", "view"),
        ("platform.registry.catalog", "view"),
    ],
}


def matches(pattern: str, key: str) -> bool:
    return pattern == "*" or pattern == key or (pattern.endswith(".*") and key.startswith(pattern[:-1]))


def covers(pattern: str, requested: str) -> bool:
    """Does `pattern` grant at least everything `requested` (itself a pattern or key) would?"""
    return pattern == "*" or pattern == requested or (pattern.endswith(".*") and requested.startswith(pattern[:-1]))


@dataclass(frozen=True)
class Grant:
    pattern: str
    action: str
    constraints: dict[str, Any]
    scope: dict[str, Any]
    role: str


@dataclass(frozen=True)
class Scope:
    unrestricted: bool
    company_ids: frozenset[str] = frozenset()
    branch_ids: frozenset[str] = frozenset()
    department_ids: frozenset[str] = frozenset()

    def where(self, company: str | None = None, branch: str | None = None,
              department: str | None = None) -> tuple[str, dict[str, Any]]:
        """SQL predicate restricting rows to this scope. A row is visible if it matches any applicable dimension."""
        if self.unrestricted:
            return "true", {}
        parts: list[str] = []
        params: dict[str, Any] = {}
        for col, ids, name in ((company, self.company_ids, "sc_c"), (branch, self.branch_ids, "sc_b"),
                               (department, self.department_ids, "sc_d")):
            if col and ids:
                parts.append(f"{col} = any(cast(:{name} as uuid[]))")
                params[name] = sorted(ids)
        return ("(" + " or ".join(parts) + ")" if parts else "false"), params


@dataclass
class Authz:
    p: Principal
    key: str
    action: str
    grants: list[Grant] = field(default_factory=list)

    def scope(self) -> Scope:
        c: set[str] = set()
        b: set[str] = set()
        d: set[str] = set()
        for g in self.grants:
            s = g.scope or {}
            if not (s.get("company_ids") or s.get("branch_ids") or s.get("department_ids")):
                return Scope(True)
            c |= set(s.get("company_ids", []))
            b |= set(s.get("branch_ids", []))
            d |= set(s.get("department_ids", []))
        return Scope(False, frozenset(c), frozenset(b), frozenset(d))

    def require_scope(self, company_id: UUID | str | None = None, branch_id: UUID | str | None = None,
                      department_id: UUID | str | None = None) -> None:
        s = self.scope()
        if s.unrestricted:
            return
        if ((company_id and str(company_id) in s.company_ids) or (branch_id and str(branch_id) in s.branch_ids)
                or (department_id and str(department_id) in s.department_ids)):
            return
        raise Forbidden("outside your assigned scope")

    def require_unrestricted(self) -> None:
        if not self.scope().unrestricted:
            raise Forbidden("requires an unscoped permission")

    def hidden_fields(self) -> set[str]:
        """A field is hidden only if every granting permission hides it."""
        sets = [set(g.constraints.get("hide_fields", [])) for g in self.grants]
        return set.intersection(*sets) if sets else set()

    def enforce(self, ctx: dict[str, Any]) -> None:
        """Dynamic ABAC against a concrete record/request: amount limits, no self-approval, own-records-only."""
        for g in self.grants:
            if _dynamic_ok(g.constraints, ctx, self.p):
                return
        raise Forbidden("policy constraints not satisfied")


def _dynamic_ok(c: dict[str, Any], ctx: dict[str, Any], p: Principal) -> bool:
    if "max_amount" in c:
        try:
            if ctx.get("amount") is None or Decimal(str(ctx["amount"])) > Decimal(str(c["max_amount"])):
                return False
        except InvalidOperation:
            return False
    if c.get("no_self_approval") and (ctx.get("created_by") is None or str(ctx["created_by"]) == str(p.user_id)):
        return False
    return not (c.get("own_records_only") and str(ctx.get("created_by")) != str(p.user_id))


def _static_ok(c: dict[str, Any], now: datetime) -> bool:
    h = c.get("hours")
    if h:
        f, t = h["from"], h["to"]
        cur = now.strftime("%H:%M")
        inside = (f <= cur <= t) if f <= t else (cur >= f or cur <= t)  # UTC; overnight windows allowed
        if not inside:
            return False
    return True


def load_grants(conn: Connection, membership_id: UUID) -> list[Grant]:
    rows = conn.execute(
        text("select rp.feature_key, rp.action, rp.constraints, mr.scope, r.name from platform.membership_roles mr"
             " join platform.roles r on r.id = mr.role_id join platform.role_permissions rp on rp.role_id = r.id"
             " where mr.membership_id = :m and (mr.expires_at is null or mr.expires_at > now())"), {"m": membership_id}).all()
    return [Grant(r.feature_key, r.action, r.constraints or {}, r.scope or {}, r.name) for r in rows]


def _entitled(conn: Connection, key: str) -> bool:
    if key.split(".")[0] == "platform":
        return True  # kernel services are always available
    rows = conn.execute(text("select feature_key from platform.entitlements where expires_at is null or expires_at > now()")).all()
    return any(matches(r.feature_key, key) for r in rows)


def entitled(conn: Connection, key: str) -> bool:
    return _entitled(conn, key)


def authorize(p: Principal, key: str, action: str, ctx: dict[str, Any] | None = None) -> Authz:
    with tx(p.tenant_id) as c:
        status = c.execute(text("select status from platform.tenants")).scalar()
        if status != "active":
            raise Forbidden("tenant_inactive")
        if not _entitled(c, key):
            raise Forbidden("not_entitled")
        now = datetime.now(UTC)
        grants = [g for g in load_grants(c, p.membership_id)
                  if matches(g.pattern, key) and g.action in ("*", action) and _static_ok(g.constraints, now)]
    if not grants:
        raise Forbidden("forbidden")
    a = Authz(p, key, action, grants)
    if ctx is not None:
        a.enforce(ctx)
    return a


# ------------------------------------------------------------------ system roles
def seed_system_roles(conn: Connection, tenant_id: UUID) -> dict[str, UUID]:
    ids: dict[str, UUID] = {}
    for name, perms in SYSTEM_ROLES.items():
        rid = uuid4()
        conn.execute(text("insert into platform.roles (id, tenant_id, name, description, is_system) values (:i,:t,:n,:d,true)"),
                     {"i": rid, "t": tenant_id, "n": name, "d": f"{name} (system role)"})
        for pattern, action in perms:
            conn.execute(text("insert into platform.role_permissions (id, tenant_id, role_id, feature_key, action)"
                              " values (:i,:t,:r,:k,:a)"), {"i": uuid4(), "t": tenant_id, "r": rid, "k": pattern, "a": action})
        ids[name] = rid
    return ids


def assign_base_role(conn: Connection, tenant_id: UUID, membership_id: UUID, base_role: str, granted_by: UUID | None) -> None:
    rid = conn.execute(text("select id from platform.roles where name=:n and is_system"), {"n": base_role.capitalize()}).scalar()
    if not rid:
        raise NotFound(f"system role {base_role} missing")
    conn.execute(text("insert into platform.membership_roles (id, tenant_id, membership_id, role_id, granted_by)"
                      " values (:i,:t,:m,:r,:g)"), {"i": uuid4(), "t": tenant_id, "m": membership_id, "r": rid, "g": granted_by})


# ------------------------------------------------------------------ role management (with anti-escalation)
def _check_constraints(cons: dict[str, Any]) -> dict[str, Any]:
    bad = set(cons) - ALLOWED_CONSTRAINTS
    if bad:
        raise Invalid(f"unknown constraints: {sorted(bad)}")
    if "max_amount" in cons:
        try:
            Decimal(str(cons["max_amount"]))
        except InvalidOperation as e:
            raise Invalid("max_amount must be numeric") from e
    h = cons.get("hours")
    if h is not None:
        import re

        if not (isinstance(h, dict) and all(isinstance(h.get(k), str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h[k]) for k in ("from", "to"))):
            raise Invalid("hours must be {from:'HH:MM', to:'HH:MM'}")
    if "hide_fields" in cons and not (isinstance(cons["hide_fields"], list) and all(isinstance(x, str) for x in cons["hide_fields"])):
        raise Invalid("hide_fields must be a list of field names")
    return cons


def _escalation_guard(actor_grants: list[Grant], pattern: str, action: str, constraints: dict[str, Any]) -> None:
    """Nobody can grant more than they hold: some actor grant must cover (pattern, action) and not be more constrained."""
    for g in actor_grants:
        if covers(g.pattern, pattern) and g.action in ("*", action) and (not g.constraints or g.constraints == constraints):
            return
    raise Forbidden(f"cannot grant '{pattern}:{action}' — you do not hold it")


def list_roles(tenant_id: UUID) -> list[dict[str, Any]]:
    with tx(tenant_id) as c:
        roles = c.execute(text("select id, name, description, is_system from platform.roles order by is_system desc, name")).mappings().all()
        perms = c.execute(text("select role_id, feature_key, action, constraints from platform.role_permissions order by feature_key, action")).mappings().all()
    return [{"id": str(r["id"]), "name": r["name"], "description": r["description"], "is_system": r["is_system"],
             "permissions": [{"feature_key": x["feature_key"], "action": x["action"], "constraints": x["constraints"]}
                             for x in perms if x["role_id"] == r["id"]]} for r in roles]


def _set_perms(c: Connection, tenant_id: UUID, rid: UUID, perms: list[dict[str, Any]], actor: Principal) -> None:
    actor_grants = load_grants(c, actor.membership_id)
    c.execute(text("delete from platform.role_permissions where role_id=:r"), {"r": rid})
    seen: set[tuple[str, str]] = set()
    for pm in perms:
        key, act, cons = pm["feature_key"], pm["action"], _check_constraints(pm.get("constraints") or {})
        registry.validate_permission(c, key, act)
        _escalation_guard(actor_grants, key, act, cons)
        if (key, act) in seen:
            raise Invalid(f"duplicate permission {key}:{act}")
        seen.add((key, act))
        c.execute(text("insert into platform.role_permissions (id, tenant_id, role_id, feature_key, action, constraints)"
                       " values (:i,:t,:r,:k,:a,cast(:c as jsonb))"),
                  {"i": uuid4(), "t": tenant_id, "r": rid, "k": key, "a": act, "c": json.dumps(cons)})


def create_role(actor: Principal, name: str, description: str, perms: list[dict[str, Any]]) -> dict[str, Any]:
    rid = uuid4()
    with tx(actor.tenant_id) as c:
        try:
            with c.begin_nested():
                c.execute(text("insert into platform.roles (id, tenant_id, name, description) values (:i,:t,:n,:d)"),
                          {"i": rid, "t": actor.tenant_id, "n": name, "d": description})
        except Exception as e:
            if getattr(getattr(e, "orig", None), "sqlstate", None) == "23505":
                raise Conflict("role name already exists") from e
            raise
        _set_perms(c, actor.tenant_id, rid, perms, actor)
        audit.record(c, actor.tenant_id, actor.user_id, "role.created", "role", rid, {"name": name, "permissions": len(perms)})
    return {"id": str(rid), "name": name}


def replace_role_permissions(actor: Principal, role_id: UUID, perms: list[dict[str, Any]]) -> None:
    with tx(actor.tenant_id) as c:
        r = c.execute(text("select is_system from platform.roles where id=:i"), {"i": role_id}).first()
        if not r:
            raise NotFound("role not found")
        if r.is_system:
            raise Forbidden("system roles cannot be modified")
        _set_perms(c, actor.tenant_id, role_id, perms, actor)
        audit.record(c, actor.tenant_id, actor.user_id, "role.permissions_replaced", "role", role_id, {"permissions": len(perms)})


def delete_role(actor: Principal, role_id: UUID) -> None:
    with tx(actor.tenant_id) as c:
        r = c.execute(text("select is_system from platform.roles where id=:i"), {"i": role_id}).first()
        if not r:
            raise NotFound("role not found")
        if r.is_system:
            raise Forbidden("system roles cannot be deleted")
        c.execute(text("delete from platform.roles where id=:i"), {"i": role_id})
        audit.record(c, actor.tenant_id, actor.user_id, "role.deleted", "role", role_id)


def assign_role(actor: Principal, membership_id: UUID, role_id: UUID, scope: dict[str, Any],
                expires_at: datetime | None) -> dict[str, Any]:
    scope = {k: sorted({str(x) for x in scope.get(k, [])}) for k in ("company_ids", "branch_ids", "department_ids") if scope.get(k)}
    if expires_at and expires_at <= datetime.now(UTC):
        raise Invalid("expires_at must be in the future")
    aid = uuid4()
    with tx(actor.tenant_id) as c:
        role = c.execute(text("select name from platform.roles where id=:i"), {"i": role_id}).first()
        if not role:
            raise NotFound("role not found")
        if not c.execute(text("select 1 from platform.memberships where id=:i and status='active'"), {"i": membership_id}).first():
            raise NotFound("active member not found")
        actor_grants = load_grants(c, actor.membership_id)
        for pm in c.execute(text("select feature_key, action, constraints from platform.role_permissions where role_id=:r"),
                            {"r": role_id}).all():
            _escalation_guard(actor_grants, pm.feature_key, pm.action, pm.constraints or {})
        c.execute(text("insert into platform.membership_roles (id, tenant_id, membership_id, role_id, scope, expires_at, granted_by)"
                       " values (:i,:t,:m,:r,cast(:s as jsonb),:e,:g)"),
                  {"i": aid, "t": actor.tenant_id, "m": membership_id, "r": role_id, "s": json.dumps(scope), "e": expires_at,
                   "g": actor.user_id})
        audit.record(c, actor.tenant_id, actor.user_id, "role.assigned", "membership", membership_id,
                     {"role": role.name, "scope": scope, "expires_at": expires_at.isoformat() if expires_at else None})
    return {"id": str(aid)}


def unassign_role(actor: Principal, assignment_id: UUID) -> None:
    with tx(actor.tenant_id) as c:
        row = c.execute(text("select mr.membership_id, mr.role_id, r.name from platform.membership_roles mr"
                             " join platform.roles r on r.id=mr.role_id where mr.id=:i"), {"i": assignment_id}).first()
        if not row:
            raise NotFound("assignment not found")
        actor_grants = load_grants(c, actor.membership_id)
        for pm in c.execute(text("select feature_key, action, constraints from platform.role_permissions where role_id=:r"),
                            {"r": row.role_id}).all():
            _escalation_guard(actor_grants, pm.feature_key, pm.action, pm.constraints or {})
        if row.name == "Owner":
            left = c.execute(text("select count(*) from platform.membership_roles mr join platform.roles r on r.id=mr.role_id"
                                  " where r.name='Owner' and r.is_system and mr.id<>:i"), {"i": assignment_id}).scalar()
            if not left:
                raise Invalid("the last Owner cannot be removed")
        c.execute(text("delete from platform.membership_roles where id=:i"), {"i": assignment_id})
        audit.record(c, actor.tenant_id, actor.user_id, "role.unassigned", "membership", row.membership_id, {"role": row.name})


def list_assignments(tenant_id: UUID) -> list[dict[str, Any]]:
    with tx(tenant_id) as c:
        rows = c.execute(text("select mr.id, mr.membership_id, r.name as role, mr.scope, mr.expires_at, u.email"
                              " from platform.membership_roles mr join platform.roles r on r.id=mr.role_id"
                              " join platform.memberships m on m.id=mr.membership_id join platform.users u on u.id=m.user_id"
                              " order by u.email, r.name")).mappings().all()
    return [{**r, "id": str(r["id"]), "membership_id": str(r["membership_id"])} for r in rows]


def effective_permissions(p: Principal) -> list[dict[str, Any]]:
    with tx(p.tenant_id) as c:
        return [{"feature_key": g.pattern, "action": g.action, "constraints": g.constraints, "scope": g.scope, "role": g.role}
                for g in load_grants(c, p.membership_id)]
