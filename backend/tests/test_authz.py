from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from ueos.platform import authz
from ueos.platform.errors import Forbidden
from ueos.platform.principal import Principal


def roles_by_name(client, h):
    return {r["name"]: r for r in client.get("/api/v1/authz/roles", headers=h).json()}


def mk_role(client, h, name, perms):
    return client.post("/api/v1/authz/roles", json={"name": name, "permissions": perms}, headers=h)


def drop_base_role(client, owner_h, email, role="Member"):
    """Invited users hold the base Member role; remove it so only explicitly assigned roles apply."""
    for a in client.get("/api/v1/authz/assignments", headers=owner_h).json():
        if a["email"] == email and a["role"] == role:
            assert client.delete(f"/api/v1/authz/assignments/{a['id']}", headers=owner_h).status_code == 204


def perm(key, action, **cons):
    return {"feature_key": key, "action": action, "constraints": cons}


# ---------------------------------------------------------------- base roles
def test_system_roles_seeded_and_cashier_style_denials(client, make_tenant, invite_user):
    t = make_tenant()
    roles = roles_by_name(client, t["h"])
    assert {"Owner", "Admin", "Member"} <= set(roles) and roles["Owner"]["is_system"]
    m = invite_user(t, "member")
    assert client.get("/api/v1/organizations/companies", headers=m["h"]).status_code == 200  # may view
    for method, url, body in [("post", "/api/v1/organizations/companies", {"name": "Z"}),
                              ("post", "/api/v1/users/invitations", {"email": "q@example.com"}),
                              ("get", "/api/v1/audit", None), ("get", "/api/v1/authz/roles", None),
                              ("post", "/api/v1/authz/roles", {"name": "xx"})]:
        r = getattr(client, method)(url, headers=m["h"], **({"json": body} if body else {}))
        assert r.status_code == 403, (url, r.status_code)
    a = invite_user(t, "admin")
    assert client.post("/api/v1/organizations/companies", json={"name": "AdminCo"}, headers=a["h"]).status_code == 201


def test_effective_permissions_endpoint(client, make_tenant):
    t = make_tenant()
    me = client.get("/api/v1/authz/me", headers=t["h"]).json()
    assert [(x["feature_key"], x["action"], x["role"]) for x in me["permissions"]] == [("*", "*", "Owner")]


# ---------------------------------------------------------------- custom roles
def test_custom_role_grants_only_what_it_lists_and_revocation_works(client, make_tenant, invite_user):
    t = make_tenant()
    r = mk_role(client, t["h"], "Auditor", [perm("platform.audit.log", "view")])
    assert r.status_code == 201
    u = invite_user(t, "member")
    assert client.get("/api/v1/audit", headers=u["h"]).status_code == 403
    a = client.post("/api/v1/authz/assignments", json={"membership_id": u["membership_id"], "role_id": r.json()["id"]}, headers=t["h"])
    assert a.status_code == 201
    assert client.get("/api/v1/audit", headers=u["h"]).status_code == 200
    assert client.get("/api/v1/audit/verify", headers=u["h"]).json()["ok"]
    assert client.post("/api/v1/organizations/companies", json={"name": "N"}, headers=u["h"]).status_code == 403
    assert client.delete(f"/api/v1/authz/assignments/{a.json()['id']}", headers=t["h"]).status_code == 204
    assert client.get("/api/v1/audit", headers=u["h"]).status_code == 403


def test_permission_validation_against_registry(client, make_tenant):
    t = make_tenant()
    assert mk_role(client, t["h"], "R1", [perm("platform.nope.nope", "view")]).status_code == 422
    assert mk_role(client, t["h"], "R2", [perm("platform.org.companies", "fly")]).status_code == 422
    assert mk_role(client, t["h"], "R3", [perm("platform.org.companies", "view", bogus=1)]).status_code == 422
    assert mk_role(client, t["h"], "R4", [perm("platform.org.companies", "view", hours={"from": "9am", "to": "5"})]).status_code == 422
    assert mk_role(client, t["h"], "R5", [perm("platform.org.*", "view")]).status_code == 201  # wildcard allowed
    assert mk_role(client, t["h"], "R5", []).status_code == 409


def test_system_roles_are_immutable_and_last_owner_protected(client, make_tenant):
    t = make_tenant()
    roles = roles_by_name(client, t["h"])
    assert client.put(f"/api/v1/authz/roles/{roles['Member']['id']}/permissions", json={"permissions": []}, headers=t["h"]).status_code == 403
    assert client.delete(f"/api/v1/authz/roles/{roles['Admin']['id']}", headers=t["h"]).status_code == 403
    assigns = client.get("/api/v1/authz/assignments", headers=t["h"]).json()
    owner_assign = next(a for a in assigns if a["role"] == "Owner")
    assert client.delete(f"/api/v1/authz/assignments/{owner_assign['id']}", headers=t["h"]).status_code == 422


# ---------------------------------------------------------------- anti-escalation
def test_admin_cannot_escalate_privileges(client, make_tenant, invite_user):
    t = make_tenant()
    adm = invite_user(t, "admin")
    mem = invite_user(t, "member")
    roles = roles_by_name(client, t["h"])
    # cannot create a role holding '*', cannot hand out Owner, cannot assign themselves Owner
    assert mk_role(client, adm["h"], "God", [perm("*", "*")]).status_code == 403
    assert client.post("/api/v1/authz/assignments", json={"membership_id": mem["membership_id"], "role_id": roles["Owner"]["id"]}, headers=adm["h"]).status_code == 403
    assert client.post("/api/v1/authz/assignments", json={"membership_id": adm["membership_id"], "role_id": roles["Owner"]["id"]}, headers=adm["h"]).status_code == 403
    # but may build roles within what they hold
    assert mk_role(client, adm["h"], "OrgViewer", [perm("platform.org.*", "view")]).status_code == 201
    # a limited manager who can manage roles cannot grant beyond their own permissions
    mgr = mk_role(client, t["h"], "RoleManager", [perm("platform.authz.roles", "create"), perm("platform.org.companies", "view")]).json()
    u = invite_user(t, "member")
    assert client.post("/api/v1/authz/assignments", json={"membership_id": u["membership_id"], "role_id": mgr["id"]}, headers=t["h"]).status_code == 201
    assert mk_role(client, u["h"], "Sneaky", [perm("platform.org.companies", "create")]).status_code == 403
    assert mk_role(client, u["h"], "Fine", [perm("platform.org.companies", "view")]).status_code == 201
    # a constrained grantor cannot hand out an unconstrained copy of the same permission
    capped = mk_role(client, t["h"], "Capped", [perm("platform.authz.roles", "create"), perm("platform.org.companies", "view", hide_fields=["legal_name"])]).json()
    v = invite_user(t, "member")
    client.post("/api/v1/authz/assignments", json={"membership_id": v["membership_id"], "role_id": capped["id"]}, headers=t["h"])
    drop_base_role(client, t["h"], v["email"])
    assert mk_role(client, v["h"], "Unmasked", [perm("platform.org.companies", "view")]).status_code == 403


# ---------------------------------------------------------------- ABAC: scope, masking, time, hours
def test_record_scope_limits_reads_and_writes(client, make_tenant, invite_user):
    t = make_tenant()
    a = client.post("/api/v1/organizations/companies", json={"name": "A"}, headers=t["h"]).json()
    b = client.post("/api/v1/organizations/companies", json={"name": "B"}, headers=t["h"]).json()
    ba = client.post("/api/v1/organizations/branches", json={"company_id": a["id"], "name": "A-1"}, headers=t["h"]).json()
    client.post("/api/v1/organizations/branches", json={"company_id": b["id"], "name": "B-1"}, headers=t["h"])
    role = mk_role(client, t["h"], "OrgManager", [perm("platform.org.*", "view"), perm("platform.org.branches", "create")]).json()
    u = invite_user(t, "member")
    r = client.post("/api/v1/authz/assignments", json={"membership_id": u["membership_id"], "role_id": role["id"], "scope": {"company_ids": [a["id"]]}}, headers=t["h"])
    assert r.status_code == 201
    assert len(client.get("/api/v1/organizations/companies", headers=u["h"]).json()) == 2  # base Member role is unscoped => union is unrestricted
    drop_base_role(client, t["h"], u["email"])
    assert [c["name"] for c in client.get("/api/v1/organizations/companies", headers=u["h"]).json()] == ["A"]
    assert [x["name"] for x in client.get("/api/v1/organizations/branches", headers=u["h"]).json()] == ["A-1"]
    assert client.post("/api/v1/organizations/branches", json={"company_id": a["id"], "name": "A-2"}, headers=u["h"]).status_code == 201
    assert client.post("/api/v1/organizations/branches", json={"company_id": b["id"], "name": "B-2"}, headers=u["h"]).status_code == 403
    # branch-level scope
    role2 = mk_role(client, t["h"], "BranchViewer", [perm("platform.org.*", "view")]).json()
    w = invite_user(t, "member")
    client.post("/api/v1/authz/assignments", json={"membership_id": w["membership_id"], "role_id": role2["id"], "scope": {"branch_ids": [ba["id"]]}}, headers=t["h"])
    drop_base_role(client, t["h"], w["email"])
    assert [x["name"] for x in client.get("/api/v1/organizations/branches", headers=w["h"]).json()] == ["A-1"]
    assert client.get("/api/v1/organizations/companies", headers=w["h"]).json() == []  # branch scope sees no company rows
    # unscoped + scoped union => unrestricted
    client.post("/api/v1/authz/assignments", json={"membership_id": u["membership_id"], "role_id": role2["id"]}, headers=t["h"])
    assert len(client.get("/api/v1/organizations/companies", headers=u["h"]).json()) == 2


def test_field_masking_requires_every_grant_to_hide(client, make_tenant, invite_user):
    t = make_tenant()
    client.post("/api/v1/organizations/companies", json={"name": "Acme", "legal_name": "Acme Holdings Ltd"}, headers=t["h"])
    masked = mk_role(client, t["h"], "Masked", [perm("platform.org.companies", "view", hide_fields=["legal_name", "country"])]).json()
    u = invite_user(t, "member")
    # member base role (unmasked org view) + masked => unmasked wins
    assert "legal_name" in client.get("/api/v1/organizations/companies", headers=u["h"]).json()[0]
    only = invite_user(t, "member")
    client.post("/api/v1/authz/assignments", json={"membership_id": only["membership_id"], "role_id": masked["id"]}, headers=t["h"])
    # remove base Member role from `only` so the masked role is the sole grant
    for a in client.get("/api/v1/authz/assignments", headers=t["h"]).json():
        if a["email"] == only["email"] and a["role"] == "Member":
            client.delete(f"/api/v1/authz/assignments/{a['id']}", headers=t["h"])
    row = client.get("/api/v1/organizations/companies", headers=only["h"]).json()[0]
    assert "legal_name" not in row and "country" not in row and row["name"] == "Acme"


def test_temporary_assignment_expires(client, make_tenant, invite_user, superuser):
    t = make_tenant()
    r = mk_role(client, t["h"], "Temp", [perm("platform.audit.log", "view")]).json()
    u = invite_user(t, "member")
    exp = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    a = client.post("/api/v1/authz/assignments", json={"membership_id": u["membership_id"], "role_id": r["id"], "expires_at": exp}, headers=t["h"]).json()
    assert client.get("/api/v1/audit", headers=u["h"]).status_code == 200
    superuser.execute("update platform.membership_roles set expires_at = now() - interval '1 minute' where id = %s", (a["id"],))
    assert client.get("/api/v1/audit", headers=u["h"]).status_code == 403
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert client.post("/api/v1/authz/assignments", json={"membership_id": u["membership_id"], "role_id": r["id"], "expires_at": past}, headers=t["h"]).status_code == 422


def test_working_hours_constraint(client, make_tenant, invite_user):
    t = make_tenant()
    h = datetime.now(UTC).hour
    outside = {"from": f"{(h + 2) % 24:02d}:00", "to": f"{(h + 3) % 24:02d}:00"}
    inside = {"from": f"{(h - 1) % 24:02d}:00", "to": f"{(h + 1) % 24:02d}:59"}
    for name, window, expected in (("Out", outside, 403), ("In", inside, 200)):
        r = mk_role(client, t["h"], name, [perm("platform.audit.log", "view", hours=window)]).json()
        u = invite_user(t, "member")
        client.post("/api/v1/authz/assignments", json={"membership_id": u["membership_id"], "role_id": r["id"]}, headers=t["h"])
        assert client.get("/api/v1/audit", headers=u["h"]).status_code == expected, name


# ---------------------------------------------------------------- dynamic ABAC via the engine (amount, SoD)
def _principal(client, t) -> Principal:
    import jwt

    c = jwt.decode(t["tokens"]["access_token"], options={"verify_signature": False, "verify_aud": False})
    return Principal(UUID(c["sub"]), UUID(c["tid"]), UUID(c["mid"]), UUID(c["sid"]), c["role"])


def test_entitlement_gate_amount_limit_and_no_self_approval(client, make_tenant, invite_user, admin):
    t = make_tenant()
    key = "finance.accounts_receivable.invoices"
    r = mk_role(client, t["h"], "Approver", []).json()
    # the platform kernel needs no entitlement, but finance does — a permission can be defined yet unusable
    role_perm = client.put(f"/api/v1/authz/roles/{r['id']}/permissions",
                           json={"permissions": [perm(key, "approve", max_amount=1000, no_self_approval=True)]}, headers=t["h"])
    assert role_perm.status_code == 204
    u = invite_user(t, "member")
    client.post("/api/v1/authz/assignments", json={"membership_id": u["membership_id"], "role_id": r["id"]}, headers=t["h"])
    import jwt

    c = jwt.decode(u["h"]["Authorization"].split()[1], options={"verify_signature": False, "verify_aud": False})
    up = Principal(UUID(c["sub"]), UUID(c["tid"]), UUID(c["mid"]), UUID(c["sid"]), c["role"])
    with pytest.raises(Forbidden, match="not_entitled"):
        authz.authorize(up, key, "approve")
    tid = t["tenant_id"]
    assert client.post(f"/api/v1/platform/tenants/{tid}/entitlements", json={"feature_key": "finance.*"}, headers=admin).status_code == 204
    other = "00000000-0000-0000-0000-0000000000aa"
    authz.authorize(up, key, "approve", {"amount": 500, "created_by": other})  # within limit, different creator
    with pytest.raises(Forbidden):
        authz.authorize(up, key, "approve", {"amount": 5000, "created_by": other})  # over limit
    with pytest.raises(Forbidden):
        authz.authorize(up, key, "approve", {"amount": 500, "created_by": str(up.user_id)})  # self-approval
    with pytest.raises(Forbidden):
        authz.authorize(up, key, "approve", {"created_by": other})  # amount missing -> deny
    with pytest.raises(Forbidden):
        authz.authorize(up, key, "post")  # action not granted
    # expired entitlement stops access again
    assert client.delete(f"/api/v1/platform/tenants/{tid}/entitlements", params={"feature_key": "finance.*"}, headers=admin).status_code == 204
    with pytest.raises(Forbidden, match="not_entitled"):
        authz.authorize(up, key, "approve", {"amount": 1, "created_by": other})


def test_entitlements_are_per_tenant(client, make_tenant, admin):
    a, b = make_tenant("a"), make_tenant("b")
    client.post(f"/api/v1/platform/tenants/{a['tenant_id']}/entitlements", json={"feature_key": "finance.*"}, headers=admin)
    pa, pb = _principal(client, a), _principal(client, b)
    assert authz.authorize(pa, "finance.chart_of_accounts.accounts", "view")
    with pytest.raises(Forbidden, match="not_entitled"):
        authz.authorize(pb, "finance.chart_of_accounts.accounts", "view")
    assert [e["feature_key"] for e in client.get(f"/api/v1/platform/tenants/{b['tenant_id']}/entitlements", headers=admin).json()] == []


def test_suspended_tenant_is_locked_out(client, make_tenant, admin):
    t = make_tenant()
    assert client.get("/api/v1/tenants/current", headers=t["h"]).status_code == 200
    assert client.post(f"/api/v1/platform/tenants/{t['tenant_id']}/status", json={"status": "suspended"}, headers=admin).status_code == 204
    assert client.get("/api/v1/tenants/current", headers=t["h"]).status_code == 403
    r = client.post("/api/v1/auth/login", json={"tenant_slug": t["slug"], "email": t["email"], "password": t["password"]})
    assert r.status_code == 401  # cannot log in either
    assert client.post(f"/api/v1/platform/tenants/{t['tenant_id']}/status", json={"status": "active"}, headers=admin).status_code == 204
    assert client.get("/api/v1/tenants/current", headers=t["h"]).status_code == 200


def test_roles_are_tenant_isolated_and_changes_are_audited(client, make_tenant):
    a, b = make_tenant("a"), make_tenant("b")
    mk_role(client, a["h"], "OnlyInA", [perm("platform.org.*", "view")])
    assert "OnlyInA" not in roles_by_name(client, b["h"])
    actions = [x["action"] for x in client.get("/api/v1/audit", headers=a["h"]).json()]
    assert "role.created" in actions and "role.assigned" not in actions  # seed assignment is part of registration
    assert client.get("/api/v1/audit/verify", headers=a["h"]).json()["ok"]
    # cross-tenant assignment attempt: B cannot assign A's role/membership
    rid = roles_by_name(client, a["h"])["OnlyInA"]["id"]
    mid = client.get("/api/v1/users", headers=b["h"]).json()[0]["id"]
    assert client.post("/api/v1/authz/assignments", json={"membership_id": mid, "role_id": rid}, headers=b["h"]).status_code == 404
