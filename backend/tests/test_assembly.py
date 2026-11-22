import uuid

import pytest

from ueos.platform import registry


def uid() -> str:
    return uuid.uuid4().hex[:8].replace("-", "")


@pytest.fixture()
def reg(make_staff):
    return make_staff("registry_admin")["h"]


@pytest.fixture()
def grant_finance(client, admin):
    def _g(t):
        assert client.post(f"/api/v1/platform/tenants/{t['tenant_id']}/entitlements", json={"feature_key": "finance.*"}, headers=admin).status_code == 204
    return _g


DEMO: list[dict] = []


@pytest.fixture()
def demo_apps(pg):
    """Inject extra code manifests (kept alongside the real ones); restored after the test."""
    DEMO.clear()

    def add(slug, modules, sync=True):
        DEMO.append({"application": {"slug": slug, "name": slug.title()}, "modules": modules, "_path": "mem"})
        if sync:
            registry.sync_manifests([*registry.load_manifests(), *DEMO])

    yield add
    DEMO.clear()
    registry.sync_manifests()


def industry(client, h, slug=None):
    slug = slug or f"ind_{uid()}"
    assert client.post("/api/v1/platform/registry/industries", json={"slug": slug, "name": slug}, headers=h).status_code == 201
    return slug


def tpl(client, h, ind, slug, config, parent=None, publish=True):
    r = client.post("/api/v1/platform/templates", json={"industry": ind, "slug": slug, "name": slug, "parent": parent, "config": config}, headers=h)
    assert r.status_code == 201, r.text
    if publish:
        assert client.patch(f"/api/v1/platform/templates/{r.json()['id']}/status", json={"status": "published"}, headers=h).status_code == 204
    return r.json()


def apply(client, t, slug):
    return client.post(f"/api/v1/config/templates/{slug}/apply", headers=t["h"])


def nav(client, t):
    return client.get("/api/v1/navigation", headers=t["h"]).json()


def field(entity="platform.company", key="tax_id", label="Tax ID", type="text", required=False, options=None):
    return {"entity": entity, "key": key, "label": label, "type": type, "required": required, "options": options or []}


# ------------------------------------------------------------------ template inheritance & provenance
def test_inheritance_merges_with_provenance_and_overrides(client, reg):
    ind = industry(client, reg)
    base = f"food_{uid()}"
    child = f"rest_{uid()}"
    tpl(client, reg, ind, base, {"modules": ["finance.chart_of_accounts"], "terminology": {"customer": "Customer", "order": "Order"},
                                  "custom_fields": [field(key="tax_id")], "compliance": ["food_safety"]})
    tpl(client, reg, ind, child, {"modules": ["finance.accounts_receivable"], "terminology": {"customer": "Guest"},
                                  "custom_fields": [field(key="tax_id", label="Business tax number"), field(key="seats", label="Seats", type="number")]}, parent=base)
    r = client.get(f"/api/v1/platform/templates/{child}/resolved", headers=reg).json()
    cfg = r["config"]
    assert r["chain"] == [f"{base}@1", f"{child}@1"]
    assert cfg["modules"] == ["finance.chart_of_accounts", "finance.accounts_receivable"]  # union, parent first
    assert cfg["terminology"] == {"customer": "Guest", "order": "Order"}  # child overrides, parent kept
    assert {f["key"]: f["label"] for f in cfg["custom_fields"]} == {"tax_id": "Business tax number", "seats": "Seats"}
    prov = r["provenance"]
    assert prov["modules:finance.chart_of_accounts"] == f"{base}@1" and prov["modules:finance.accounts_receivable"] == f"{child}@1"
    assert prov["terminology:customer"] == f"{child}@1" and prov["terminology:order"] == f"{base}@1"
    assert {"path": "terminology:customer", "from": f"{base}@1", "by": f"{child}@1"} in r["overrides"]
    assert {"path": "custom_fields:platform.company.tax_id", "from": f"{base}@1", "by": f"{child}@1"} in r["overrides"]


def test_template_validation_and_lifecycle(client, reg, make_staff):
    ind = industry(client, reg)
    slug = f"t_{uid()}"
    post = lambda cfg, **kw: client.post("/api/v1/platform/templates", json={"industry": ind, "slug": f"x_{uid()}", "name": "x", "config": cfg, **kw}, headers=reg)
    assert post({"bogus": 1}).status_code == 422
    assert post({"applications": ["no_such_app"]}).status_code == 422
    assert post({"modules": ["finance.nope"]}).status_code == 422
    assert post({"custom_fields": [{"entity": "x", "key": "k", "label": "l", "type": "text"}]}).status_code == 422
    assert post({"dashboards": [{"name": "d", "widgets": [{"type": "count", "source": "secrets"}]}]}).status_code == 422
    assert post({"roles": [{"name": "R", "permissions": [{"feature_key": "nope.nope", "action": "view"}]}]}).status_code == 422
    assert post({}, parent="missing_parent").status_code == 404
    unpublished = tpl(client, reg, ind, f"draft_{uid()}", {}, publish=False)
    assert post({}, parent=unpublished["slug"]).status_code == 404  # can only inherit from a published template
    t = tpl(client, reg, ind, slug, {"modules": ["finance.chart_of_accounts"]}, publish=False)
    assert client.put(f"/api/v1/platform/templates/{t['id']}/config", json={"config": {"modules": []}}, headers=reg).status_code == 204
    assert client.patch(f"/api/v1/platform/templates/{t['id']}/status", json={"status": "published"}, headers=reg).status_code == 204
    assert client.put(f"/api/v1/platform/templates/{t['id']}/config", json={"config": {}}, headers=reg).status_code == 409  # immutable
    assert client.post(f"/api/v1/platform/templates/{slug}/versions", headers=reg).json()["version"] == 2
    assert client.post(f"/api/v1/platform/templates/{slug}/versions", headers=reg).status_code == 409  # one draft at a time
    sup = make_staff("support_admin")["h"]
    assert client.post("/api/v1/platform/templates", json={"industry": ind, "slug": f"y_{uid()}", "name": "y", "config": {}}, headers=sup).status_code == 403


# ------------------------------------------------------------------ applying to a tenant
def test_apply_template_activates_modules_with_dependencies_and_configures_tenant(client, reg, make_tenant, grant_finance):
    ind = industry(client, reg)
    slug = f"shop_{uid()}"
    tpl(client, reg, ind, slug, {
        "modules": ["finance.general_ledger"],  # depends on chart_of_accounts -> auto-added
        "terminology": {"companies": "Stores"},
        "custom_fields": [field(key="region", label="Region", type="select", options=["north", "south"], required=True)],
        "roles": [{"name": "Cashier", "permissions": [{"feature_key": "platform.org.companies", "action": "view"}]}],
        "dashboards": [{"name": "Main", "widgets": [{"type": "count", "source": "companies", "title": "Stores"}]}],
    })
    t = make_tenant()
    r = apply(client, t, slug)
    assert r.status_code == 200, r.text
    out = r.json()
    assert sorted(out["activated_modules"]) == ["finance.chart_of_accounts", "finance.general_ledger"]
    assert out["added_dependencies"] == ["finance.chart_of_accounts"]
    assert set(out["not_entitled"]) == set(out["activated_modules"])  # no subscription yet -> warned, not silently ignored
    assert client.get("/api/v1/config/terminology", headers=t["h"]).json() == {"companies": "Stores"}
    assert [f["key"] for f in client.get("/api/v1/config/fields/for/platform.company", headers=t["h"]).json()] == ["region"]
    assert "Cashier" in [r["name"] for r in client.get("/api/v1/authz/roles", headers=t["h"]).json()]
    assert client.get("/api/v1/config/settings", headers=t["h"]).json()["applied_template"] == slug
    assert nav(client, t) == []  # activated but not entitled -> not shown
    grant_finance(t)
    names = [m["slug"] for a in nav(client, t) for m in a["modules"]]
    assert names == ["chart_of_accounts", "general_ledger"]
    assert any(e["action"] == "template.applied" for e in client.get("/api/v1/audit", headers=t["h"]).json())


def test_template_updates_never_overwrite_tenant_customisation(client, reg, make_tenant):
    ind = industry(client, reg)
    slug = f"keep_{uid()}"
    tpl(client, reg, ind, slug, {"terminology": {"customer": "Customer"}, "custom_fields": [field(key="vat", label="VAT")]})
    t = make_tenant()
    assert apply(client, t, slug).status_code == 200
    assert client.put("/api/v1/config/terminology", json={"term": "customer", "label": "Patron"}, headers=t["h"]).status_code == 204
    # new template version changes the label and adds a field
    v2 = client.post(f"/api/v1/platform/templates/{slug}/versions", headers=reg).json()
    tid = next(x["id"] for x in client.get("/api/v1/platform/templates", headers=reg).json() if x["slug"] == slug and x["version"] == 2)
    assert v2["version"] == 2
    client.put(f"/api/v1/platform/templates/{tid}/config", json={"config": {"terminology": {"customer": "Client"}, "custom_fields": [field(key="vat", label="VAT No."), field(key="ref", label="Ref")]}}, headers=reg)
    client.patch(f"/api/v1/platform/templates/{tid}/status", json={"status": "published"}, headers=reg)
    out = apply(client, t, slug).json()
    assert client.get("/api/v1/config/terminology", headers=t["h"]).json()["customer"] == "Patron"  # tenant's choice survives
    labels = {f["key"]: f["label"] for f in client.get("/api/v1/config/fields/for/platform.company", headers=t["h"]).json()}
    assert labels == {"vat": "VAT", "ref": "Ref"}  # existing kept, new added
    assert "customer" in out["skipped_existing"]["terminology"] and out["created"]["custom_fields"] == ["platform.company.ref"]


def test_template_roles_cannot_exceed_the_appliers_permissions(client, reg, make_tenant, invite_user):
    ind = industry(client, reg)
    slug = f"esc_{uid()}"
    tpl(client, reg, ind, slug, {"roles": [{"name": "Superuser", "permissions": [{"feature_key": "platform.authz.roles", "action": "manage_permissions"}]}]})
    t = make_tenant()
    # a limited user who may apply templates but holds no role-management permission
    r = client.post("/api/v1/authz/roles", json={"name": "Applier", "permissions": [{"feature_key": "platform.config.templates", "action": "apply"},
                                                                                  {"feature_key": "platform.config.templates", "action": "view"}]}, headers=t["h"]).json()
    u = invite_user(t, "member")
    client.post("/api/v1/authz/assignments", json={"membership_id": u["membership_id"], "role_id": r["id"]}, headers=t["h"])
    assert apply(client, u, slug).status_code == 403
    assert "Superuser" not in [x["name"] for x in client.get("/api/v1/authz/roles", headers=t["h"]).json()]  # nothing half-applied


# ------------------------------------------------------------------ modules: dependencies and conflicts
def test_module_dependencies_are_resolved_and_protected(client, make_tenant):
    t = make_tenant()
    act = lambda mods, deps=False: client.post("/api/v1/config/modules/activate", json={"modules": mods, "with_dependencies": deps}, headers=t["h"])
    r = act(["finance.general_ledger"])
    assert r.status_code == 422 and "chart_of_accounts" in r.json()["detail"]
    assert act(["platform.org"]).status_code == 422 and act(["finance.nope"]).status_code == 422
    ok = act(["finance.general_ledger"], True).json()
    assert ok["added_dependencies"] == ["finance.chart_of_accounts"]
    deact = lambda m: client.post("/api/v1/config/modules/deactivate", json={"module": m}, headers=t["h"])
    r = deact("finance.chart_of_accounts")
    assert r.status_code == 422 and "required by" in r.json()["detail"] and "general_ledger" in r.json()["detail"]
    assert deact("finance.general_ledger").status_code == 204 and deact("finance.chart_of_accounts").status_code == 204
    assert deact("finance.chart_of_accounts").status_code == 404
    cat = {m["key"]: m for a in client.get("/api/v1/config/modules", headers=t["h"]).json() for m in a["modules"]}
    assert cat["finance.general_ledger"]["depends_on_modules"] == ["finance.chart_of_accounts"] and not cat["finance.general_ledger"]["active"]


def test_incompatible_modules_are_prevented(client, demo_apps, make_tenant, reg):
    a, b = f"cona{uid()}", f"conb{uid()}"
    demo_apps(a, [{"slug": "m", "name": "M", "features": [{"slug": "x", "name": "X", "actions": ["view"], "conflicts_with": [f"{b}.m.y"]}]}], sync=False)
    demo_apps(b, [{"slug": "m", "name": "M", "features": [{"slug": "y", "name": "Y", "actions": ["view"]}]}])
    t = make_tenant()
    act = lambda mods: client.post("/api/v1/config/modules/activate", json={"modules": mods}, headers=t["h"])
    r = act([f"{a}.m", f"{b}.m"])
    assert r.status_code == 422 and "incompatible" in r.json()["detail"]
    assert act([f"{a}.m"]).status_code == 200
    r = act([f"{b}.m"])  # conflicts with an already-active module
    assert r.status_code == 422 and "incompatible" in r.json()["detail"]


def test_manifest_linter_rejects_unknown_conflicts():
    bad = {"application": {"slug": "zz", "name": "zz"}, "modules": [{"slug": "m", "name": "M", "features": [
        {"slug": "x", "name": "X", "actions": ["view"], "conflicts_with": ["zz.m.nope"]}]}], "_path": "mem"}
    with pytest.raises(registry.ManifestError, match="conflicts_with unknown"):
        registry.lint([bad])


# ------------------------------------------------------------------ navigation = published app + active module + entitlement + permission
def test_navigation_respects_entitlement_and_user_permissions(client, make_tenant, grant_finance, invite_user, admin):
    t = make_tenant()
    client.post("/api/v1/config/modules/activate", json={"modules": ["finance.accounts_receivable"], "with_dependencies": True}, headers=t["h"])
    assert nav(client, t) == []  # not entitled
    grant_finance(t)
    feats = {f["key"]: f["actions"] for a in nav(client, t) for m in a["modules"] for f in m["features"]}
    assert "finance.accounts_receivable.invoices" in feats and "post" in feats["finance.accounts_receivable.invoices"]
    adm = invite_user(t, "admin")  # Admin holds platform.* only -> no finance access
    assert nav(client, adm) == []
    limited = client.post("/api/v1/authz/roles", json={"name": "Clerk", "permissions": [{"feature_key": "finance.accounts_receivable.invoices", "action": "view"},
                                                                                       {"feature_key": "finance.accounts_receivable.invoices", "action": "create"}]}, headers=t["h"]).json()
    u = invite_user(t, "member")
    client.post("/api/v1/authz/assignments", json={"membership_id": u["membership_id"], "role_id": limited["id"]}, headers=t["h"])
    got = {f["key"]: f["actions"] for a in nav(client, u) for m in a["modules"] for f in m["features"]}
    assert got == {"finance.accounts_receivable.invoices": ["view", "create"]}  # only the actions they hold
    client.delete(f"/api/v1/platform/tenants/{t['tenant_id']}/entitlements", params={"feature_key": "finance.*"}, headers=admin)
    assert nav(client, t) == [] and nav(client, u) == []


# ------------------------------------------------------------------ products (software editions)
def test_product_builder_test_publish_install(client, reg, make_tenant, make_staff, grant_finance):
    ind = industry(client, reg)
    slug = f"prod_{uid()}"
    tslug = f"pt_{uid()}"
    tpl(client, reg, ind, tslug, {"terminology": {"customer": "Resident"}, "custom_fields": [field(key="unit", label="Unit")]})
    assert client.post("/api/v1/platform/products", json={"slug": slug, "name": "Property Suite", "industry": ind}, headers=reg).status_code == 201
    assert client.post("/api/v1/platform/products", json={"slug": slug, "name": "dup"}, headers=reg).status_code == 409
    base = f"/api/v1/platform/products/{slug}/versions/1"
    comp = {"modules": ["finance.accounts_receivable"], "template": tslug, "branding": {"name": "Prop", "primary_color": "#112233"}}
    r = client.put(f"{base}/composition", json={"composition": comp}, headers=reg)
    assert r.status_code == 200 and r.json()["modules"] == ["finance.accounts_receivable", "finance.chart_of_accounts"]
    assert r.json()["added_dependencies"] == ["finance.chart_of_accounts"]  # no duplication: references registry modules
    for bad in ({"modules": ["finance.nope"]}, {"modules": [], "template": "nope"}, {"modules": [], "branding": {"primary_color": "red"}},
                {"modules": [], "plans": ["nope"]}, {"bogus": 1}):
        assert client.put(f"{base}/composition", json={"composition": bad}, headers=reg).status_code in (404, 422)
    empty = f"empty_{uid()}"
    client.post("/api/v1/platform/products", json={"slug": empty, "name": "Empty"}, headers=reg)
    assert client.post(f"/api/v1/platform/products/{empty}/versions/1/publish", headers=reg).status_code == 422  # needs modules
    assert client.get("/api/v1/platform/products", headers=reg).status_code == 200
    t = make_tenant()
    assert client.post(f"/api/v1/config/products/{slug}/install", headers=t["h"]).status_code == 404  # not published yet
    test = client.post(f"{base}/test", headers=reg).json()
    assert test["warnings"] == []
    assert client.post(f"{base}/publish", headers=reg).status_code == 204
    assert client.put(f"{base}/composition", json={"composition": comp}, headers=reg).status_code == 409  # published = immutable
    assert client.post(f"/api/v1/platform/products/{slug}/versions", headers=reg).json()["version"] == 2
    sup = make_staff("support_admin")["h"]
    assert client.post("/api/v1/platform/products", json={"slug": f"q{uid()}", "name": "q"}, headers=sup).status_code == 403
    assert slug in [p["slug"] for p in client.get("/api/v1/config/products", headers=t["h"]).json()]
    out = client.post(f"/api/v1/config/products/{slug}/install", headers=t["h"]).json()
    assert sorted(out["activated_modules"]) == ["finance.accounts_receivable", "finance.chart_of_accounts"]
    s = client.get("/api/v1/config/settings", headers=t["h"]).json()
    assert s["installed_product"] == slug and s["branding"]["primary_color"] == "#112233"
    assert client.get("/api/v1/config/terminology", headers=t["h"]).json()["customer"] == "Resident"
    grant_finance(t)
    assert [a["slug"] for a in nav(client, t)] == ["finance"]


def test_product_test_warns_when_recommended_plans_do_not_cover_features(client, reg, bill_admin):
    slug = f"pw_{uid()}"
    client.post("/api/v1/platform/products", json={"slug": slug, "name": "W"}, headers=reg)
    plan = client.post("/api/v1/platform/plans", json={"slug": f"nopl_{uid()}", "name": "Empty", "features": ["platform.*"]}, headers=bill_admin).json()
    comp = {"modules": ["finance.chart_of_accounts"], "plans": [plan["slug"]]}
    r = client.put(f"/api/v1/platform/products/{slug}/versions/1/composition", json={"composition": comp}, headers=reg).json()
    assert any("finance.chart_of_accounts.accounts" in w for w in r["warnings"])


@pytest.fixture()
def bill_admin(make_staff):
    return make_staff("subscription_admin")["h"]


# ------------------------------------------------------------------ custom fields / terminology / dashboards
def test_custom_fields_drive_validation_of_company_data(client, make_tenant, invite_user):
    t = make_tenant()
    create = lambda **f: client.post("/api/v1/config/fields", json=field(**f), headers=t["h"])
    assert create(key="tax_id", label="Tax ID", required=True).status_code == 201
    assert create(key="tax_id", label="Dup").status_code == 409
    assert create(key="kind", label="Kind", type="select", options=["a", "b"]).status_code == 201
    assert create(key="employees", label="Employees", type="number").status_code == 201
    assert create(key="founded", label="Founded", type="date").status_code == 201
    assert create(key="listed", label="Listed", type="boolean").status_code == 201
    assert create(key="bad", label="Bad", type="select").status_code == 422  # select needs options
    assert create(entity="x.y", key="k", label="K").status_code == 422
    co = lambda body, **kw: client.post("/api/v1/organizations/companies", json={"name": f"C{uid()}", **body}, headers=t["h"], **kw)
    assert co({}).status_code == 422  # required field missing
    assert co({"custom": {"tax_id": "123", "kind": "z"}}).status_code == 422  # not in options
    assert co({"custom": {"tax_id": "123", "employees": "many"}}).status_code == 422
    assert co({"custom": {"tax_id": "123", "founded": "yesterday"}}).status_code == 422
    assert co({"custom": {"tax_id": "123", "listed": "yes"}}).status_code == 422
    assert co({"custom": {"tax_id": "123", "nope": 1}}).status_code == 422  # unknown field
    ok = co({"custom": {"tax_id": "123", "kind": "a", "employees": 12, "founded": "2020-05-01", "listed": True}})
    assert ok.status_code == 201
    row = next(c for c in client.get("/api/v1/organizations/companies", headers=t["h"]).json() if c["id"] == ok.json()["id"])
    assert row["custom"] == {"tax_id": "123", "kind": "a", "employees": 12.0, "founded": "2020-05-01", "listed": True}
    p = client.patch(f"/api/v1/organizations/companies/{ok.json()['id']}", json={"custom": {"kind": "b", "employees": None}}, headers=t["h"])
    assert p.status_code == 200 and p.json() == {"tax_id": "123", "kind": "b", "founded": "2020-05-01", "listed": True}
    assert client.patch(f"/api/v1/organizations/companies/{ok.json()['id']}", json={"custom": {"tax_id": ""}}, headers=t["h"]).status_code == 422
    # members can render forms but not manage definitions
    m = invite_user(t, "member")
    assert client.get("/api/v1/config/fields/for/platform.company", headers=m["h"]).status_code == 200
    assert client.get("/api/v1/config/fields", headers=m["h"]).status_code == 403
    assert client.post("/api/v1/config/fields", json=field(key="zz", label="Z"), headers=m["h"]).status_code == 403
    assert client.delete("/api/v1/config/fields/platform.company/employees", headers=t["h"]).status_code == 204
    assert client.delete("/api/v1/config/fields/platform.company/employees", headers=t["h"]).status_code == 404


def test_configuration_is_tenant_isolated(client, make_tenant):
    a, b = make_tenant("a"), make_tenant("b")
    client.post("/api/v1/config/fields", json=field(key="secret_a", label="A only"), headers=a["h"])
    client.put("/api/v1/config/terminology", json={"term": "customer", "label": "A-term"}, headers=a["h"])
    client.post("/api/v1/config/modules/activate", json={"modules": ["finance.chart_of_accounts"]}, headers=a["h"])
    assert client.get("/api/v1/config/fields/for/platform.company", headers=b["h"]).json() == []
    assert client.get("/api/v1/config/terminology", headers=b["h"]).json() == {}
    cat = {m["key"]: m for x in client.get("/api/v1/config/modules", headers=b["h"]).json() for m in x["modules"]}
    assert not cat["finance.chart_of_accounts"]["active"]
    assert client.delete("/api/v1/config/fields/platform.company/secret_a", headers=b["h"]).status_code == 404


def test_dashboard_widgets_never_reveal_counts_the_user_cannot_view(client, reg, make_tenant, invite_user):
    ind = industry(client, reg)
    slug = f"dash_{uid()}"
    tpl(client, reg, ind, slug, {"dashboards": [{"name": "Main", "widgets": [
        {"type": "count", "source": "companies", "title": "Companies"}, {"type": "count", "source": "members", "title": "People"}]}]})
    t = make_tenant()
    apply(client, t, slug)
    client.post("/api/v1/organizations/companies", json={"name": "A"}, headers=t["h"])
    d = client.get("/api/v1/config/dashboard", headers=t["h"]).json()
    assert {w["source"]: w["value"] for w in d["widgets"]} == {"companies": 1, "members": 1}
    only = client.post("/api/v1/authz/roles", json={"name": "CoOnly", "permissions": [{"feature_key": "platform.org.companies", "action": "view"}]}, headers=t["h"]).json()
    u = invite_user(t, "member")
    client.post("/api/v1/authz/assignments", json={"membership_id": u["membership_id"], "role_id": only["id"]}, headers=t["h"])
    for a in client.get("/api/v1/authz/assignments", headers=t["h"]).json():
        if a["email"] == u["email"] and a["role"] == "Member":
            client.delete(f"/api/v1/authz/assignments/{a['id']}", headers=t["h"])
    d2 = client.get("/api/v1/config/dashboard", headers=u["h"]).json()
    assert [w["source"] for w in d2["widgets"]] == ["companies"]
    assert client.get("/api/v1/config/dashboard", headers=make_tenant()["h"]).json() == {"name": None, "widgets": []}


def test_terminology_requires_permission_and_valid_input(client, make_tenant, invite_user):
    t = make_tenant()
    assert client.put("/api/v1/config/terminology", json={"term": "Bad Term", "label": "x"}, headers=t["h"]).status_code == 422
    assert client.put("/api/v1/config/terminology", json={"term": "customer", "label": " "}, headers=t["h"]).status_code == 422
    m = invite_user(t, "member")
    assert client.put("/api/v1/config/terminology", json={"term": "customer", "label": "X"}, headers=m["h"]).status_code == 403
    assert client.post("/api/v1/config/modules/activate", json={"modules": ["finance.chart_of_accounts"]}, headers=m["h"]).status_code == 403
    assert client.post("/api/v1/config/templates/anything/apply", headers=m["h"]).status_code == 403
