import pytest
from fastapi.routing import APIRoute

from ueos.platform import registry
from ueos.platform.errors import AuthError  # noqa: F401


def mf(app="demo", modules=None):
    return {"application": {"slug": app, "name": app.title()}, "modules": modules or [], "_path": "mem"}


def feat(slug, actions=("view",), **kw):
    return {"slug": slug, "name": slug, "actions": list(actions), **kw}


# ---------------------------------------------------------------- manifest linter
def test_real_manifests_lint_clean():
    feats = registry.lint(registry.load_manifests())
    assert "platform.org.companies" in feats and "finance.general_ledger.journals.posting" in feats


def test_lint_rejects_duplicates_dangling_deps_cycles_and_bad_slugs():
    bad_dup = mf(modules=[{"slug": "m", "name": "M", "features": [feat("a"), feat("a")]}])
    with pytest.raises(registry.ManifestError, match="duplicate feature key"):
        registry.lint([bad_dup])
    dangling = mf(modules=[{"slug": "m", "name": "M", "features": [feat("a", depends_on=["demo.m.zzz"])]}])
    with pytest.raises(registry.ManifestError, match="unknown feature"):
        registry.lint([dangling])
    cyc = mf(modules=[{"slug": "m", "name": "M", "features": [feat("a", depends_on=["demo.m.b"]), feat("b", depends_on=["demo.m.a"])]}])
    with pytest.raises(registry.ManifestError, match="cycle"):
        registry.lint([cyc])
    with pytest.raises(registry.ManifestError):
        registry.lint([mf(modules=[{"slug": "Bad Slug", "name": "x", "features": []}])])
    with pytest.raises(registry.ManifestError, match="actions"):
        registry.lint([mf(modules=[{"slug": "m", "name": "M", "features": [feat("a", actions=())]}])])
    with pytest.raises(registry.ManifestError, match="duplicate application"):
        registry.lint([mf("x"), mf("x")])


def test_sync_is_idempotent_and_never_overwrites_config_rows(pg, client, admin):
    again = registry.sync_manifests()
    assert again["applications"] == again["modules"] == again["features"] == 0
    # an admin-created (config) application cannot be hijacked by a code manifest with the same slug
    assert client.post("/api/v1/platform/registry/applications", json={"slug": "hijack", "name": "Mine"}, headers=admin).status_code == 201
    with pytest.raises(registry.ManifestError, match="config-defined"):
        registry.sync_manifests([mf("hijack", [{"slug": "m", "name": "M", "features": [feat("a")]}])])


def test_features_removed_from_manifest_become_deprecated(pg):
    m = mf("ephemeral", [{"slug": "m", "name": "M", "features": [feat("a"), feat("b")]}])
    registry.sync_manifests([*registry.load_manifests(), m])
    m2 = mf("ephemeral", [{"slug": "m", "name": "M", "features": [feat("a")]}])
    rep = registry.sync_manifests([*registry.load_manifests(), m2])
    assert rep["deprecated"] == 1
    # restore real state for other tests
    registry.sync_manifests()


# ---------------------------------------------------------------- registry admin API
def test_admin_builds_application_tree_and_catalog_visibility(client, admin, make_tenant):
    h = admin
    assert client.post("/api/v1/platform/registry/capabilities", json={"slug": "farming", "name": "Farming"}, headers=h).status_code == 201
    r = client.post("/api/v1/platform/registry/applications",
                    json={"slug": "farm_mgmt", "name": "Farm Management", "capability_slug": "farming", "status": "draft"}, headers=h)
    assert r.status_code == 201
    assert client.post("/api/v1/platform/registry/modules", json={"application_slug": "farm_mgmt", "slug": "crops", "name": "Crops"}, headers=h).status_code == 201
    assert client.post("/api/v1/platform/registry/submodules", json={"application_slug": "farm_mgmt", "module_slug": "crops", "slug": "cycles", "name": "Cycles"}, headers=h).status_code == 201
    f = client.post("/api/v1/platform/registry/features",
                    json={"application_slug": "farm_mgmt", "module_slug": "crops", "submodule_slug": "cycles", "slug": "plan",
                          "name": "Plan cycle", "actions": ["view", "create"]}, headers=h)
    assert f.status_code == 201 and f.json()["key"] == "farm_mgmt.crops.cycles.plan"
    # dependency validation
    bad = client.post("/api/v1/platform/registry/features",
                      json={"application_slug": "farm_mgmt", "module_slug": "crops", "slug": "x", "name": "X", "actions": ["view"],
                            "depends_on": ["nope.nope.nope"]}, headers=h)
    assert bad.status_code == 422
    dup = client.post("/api/v1/platform/registry/features",
                      json={"application_slug": "farm_mgmt", "module_slug": "crops", "submodule_slug": "cycles", "slug": "plan",
                            "name": "Plan cycle", "actions": ["view"]}, headers=h)
    assert dup.status_code == 409
    t = make_tenant()
    slugs = lambda: [a["slug"] for a in client.get("/api/v1/registry/catalog", headers=t["h"]).json()]
    assert "farm_mgmt" not in slugs() and "platform" in slugs()  # draft hidden from tenants
    assert client.patch("/api/v1/platform/registry/applications/farm_mgmt", json={"status": "published"}, headers=h).status_code == 204
    assert "farm_mgmt" in slugs()
    assert client.patch("/api/v1/platform/registry/applications/farm_mgmt", json={"status": "bogus"}, headers=h).status_code == 422


def test_industry_hierarchy_and_business_models(client, admin):
    h = admin
    assert client.post("/api/v1/platform/registry/industries", json={"slug": "food_hospitality", "name": "Food & Hospitality"}, headers=h).status_code == 201
    assert client.post("/api/v1/platform/registry/industries", json={"slug": "restaurant", "name": "Restaurant", "parent_slug": "food_hospitality"}, headers=h).status_code == 201
    assert client.post("/api/v1/platform/registry/industries", json={"slug": "x1", "name": "X", "parent_slug": "missing"}, headers=h).status_code == 404
    inds = {i["slug"]: i for i in client.get("/api/v1/platform/registry/industries", headers=h).json()}
    assert inds["restaurant"]["parent"] == "food_hospitality"
    assert client.post("/api/v1/platform/registry/business-models", json={"slug": "b2b", "name": "B2B"}, headers=h).status_code == 201
    assert client.post("/api/v1/platform/registry/business-models", json={"slug": "b2b", "name": "B2B"}, headers=h).status_code == 409


# ---------------------------------------------------------------- staff realm
def test_staff_and_tenant_realms_are_separate(client, admin, make_tenant):
    t = make_tenant()
    assert client.get("/api/v1/platform/tenants", headers=t["h"]).status_code == 401  # tenant token on staff route
    assert client.get("/api/v1/tenants/current", headers=admin).status_code == 401  # staff token on tenant route
    assert client.get("/api/v1/platform/tenants").status_code == 401


def test_staff_login_failures_and_lockout(client, make_staff):
    s = make_staff()
    for _ in range(5):
        r = client.post("/api/v1/platform/auth/login", json={"email": s["email"], "password": "wrong-wrong-wrong"})
        assert r.status_code == 401
    assert client.post("/api/v1/platform/auth/login", json={"email": s["email"], "password": s["password"]}).json()["detail"] == "account_locked"


def test_staff_role_limits(client, make_staff):
    reg = make_staff("registry_admin")["h"]
    sup = make_staff("support_admin")["h"]
    assert client.post("/api/v1/platform/registry/capabilities", json={"slug": "ok_cap", "name": "ok"}, headers=reg).status_code == 201
    assert client.post("/api/v1/platform/registry/capabilities", json={"slug": "no_cap", "name": "no"}, headers=sup).status_code == 403
    assert client.get("/api/v1/platform/registry/applications", headers=sup).status_code == 200
    t = client.get("/api/v1/platform/tenants", headers=sup)
    assert t.status_code == 200
    assert set(t.json()[0]) == {"id", "slug", "name", "status", "created_at"}  # metadata only, never business data
    # registry admins cannot suspend tenants or grant entitlements
    tid = t.json()[0]["id"]
    assert client.post(f"/api/v1/platform/tenants/{tid}/status", json={"status": "suspended"}, headers=reg).status_code == 403
    assert client.post(f"/api/v1/platform/tenants/{tid}/entitlements", json={"feature_key": "finance.*"}, headers=reg).status_code == 403


def test_platform_audit_chain(client, admin, superuser):
    client.post("/api/v1/platform/registry/capabilities", json={"slug": "audit_cap", "name": "x"}, headers=admin)
    assert client.get("/api/v1/platform/audit/verify", headers=admin).json()["ok"]
    superuser.execute("alter table platform.platform_audit_log disable trigger platform_audit_no_update_delete")
    try:
        superuser.execute("update platform.platform_audit_log set action='forged' where seq = (select min(seq) from platform.platform_audit_log)")
    finally:
        superuser.execute("alter table platform.platform_audit_log enable trigger platform_audit_no_update_delete")
    assert client.get("/api/v1/platform/audit/verify", headers=admin).json()["ok"] is False


def test_staff_mfa_flow(client, make_staff):
    import pyotp

    s = make_staff()
    sec = client.post("/api/v1/platform/auth/mfa/enroll", headers=s["h"]).json()["secret"]
    assert client.post("/api/v1/platform/auth/mfa/confirm", json={"code": pyotp.TOTP(sec).now()}, headers=s["h"]).status_code == 204
    r = client.post("/api/v1/platform/auth/login", json={"email": s["email"], "password": s["password"]})
    assert r.json()["detail"] == "mfa_required"
    ok = client.post("/api/v1/platform/auth/login", json={"email": s["email"], "password": s["password"], "mfa_code": pyotp.TOTP(sec).now()})
    assert ok.status_code == 200


# ---------------------------------------------------------------- route policy coverage
def test_every_route_has_policy_and_every_required_feature_exists(client):
    from ueos.api import app

    feats = registry.lint(registry.load_manifests())

    def collect(dep, acc):
        mark = getattr(dep.call, "__ueos_access__", None)
        if mark:
            acc["marks"].add(mark)
        ft = getattr(dep.call, "__ueos_feature__", None)
        if ft:
            acc["features"].add(ft)
        for d in dep.dependencies:
            collect(d, acc)

    missing, bad = [], []
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        acc = {"marks": set(), "features": set()}
        collect(r.dependant, acc)
        if not acc["marks"]:
            missing.append(r.path)
        for key, action in acc["features"]:
            if key not in feats or action not in feats[key]["actions"]:
                bad.append((r.path, key, action))
    assert not missing, f"routes without access policy: {missing}"
    assert not bad, f"Requires() references unregistered feature/action: {bad}"


def test_staff_creation_rejects_emails_the_login_form_would_reject():
    from ueos.platform import staff
    from ueos.platform.errors import Invalid

    for bad in ("admin@ueos.local", "x@y.test", "not-an-email"):
        with pytest.raises(Invalid):
            staff.create_staff(bad, "long-enough-password-1", "super_admin")
