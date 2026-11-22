import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import jwt
import pytest
from sqlalchemy import text

from ueos.platform import authz, billing
from ueos.platform.db import tx
from ueos.platform.errors import Forbidden, Invalid
from ueos.platform.principal import Principal

FIN = "finance.chart_of_accounts.accounts"


def uid() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def bill_admin(make_staff):
    return make_staff("subscription_admin")["h"]


def mk_plan(client, h, *, price="0", per_user="0", features=("finance.*",), limits=None, trial=0, period="monthly",
            kind="base", publish=True, default=False):
    slug = f"p_{uid()}"
    r = client.post("/api/v1/platform/plans", headers=h, json={
        "slug": slug, "name": slug.upper(), "kind": kind, "billing_period": period, "base_price": price, "per_user_price": per_user,
        "trial_days": trial, "features": list(features), "limits": limits or {}, "is_default": default})
    assert r.status_code == 201, r.text
    if publish:
        assert client.patch(f"/api/v1/platform/plans/{r.json()['id']}/status", json={"status": "published"}, headers=h).status_code == 204
    return r.json()


def principal(t) -> Principal:
    c = jwt.decode(t["tokens"]["access_token"], options={"verify_signature": False, "verify_aud": False})
    return Principal(UUID(c["sub"]), UUID(c["tid"]), UUID(c["mid"]), UUID(c["sid"]), c["role"])


def entitled(t) -> bool:
    try:
        authz.authorize(principal(t), FIN, "view")
        return True
    except Forbidden as e:
        assert "not_entitled" in str(e)
        return False


def overview(client, t):
    return client.get("/api/v1/billing/overview", headers=t["h"]).json()


def subscribe(client, t, plan):
    return client.post("/api/v1/billing/subscriptions", json={"plan": plan["slug"]}, headers=t["h"])


def pay(client, t, invoice_id, method="test_ok", **headers):
    return client.post(f"/api/v1/billing/invoices/{invoice_id}/pay", json={"payment_method": method}, headers={**t["h"], **headers})


def sub_row(t):
    with tx(t["tenant_id"]) as c:
        return c.execute(text("select * from platform.subscriptions order by started_at desc limit 1")).mappings().first()


# ------------------------------------------------------------------ plans
def test_plan_validation_immutability_and_staff_roles(client, bill_admin, make_staff):
    p = mk_plan(client, bill_admin, publish=False)
    assert p["status"] == "draft" and p["base_price"] == "0.00"
    bad = {"slug": f"x_{uid()}", "name": "x", "features": ["nope.nothing"]}
    assert client.post("/api/v1/platform/plans", json=bad, headers=bill_admin).status_code == 422
    assert client.post("/api/v1/platform/plans", json={**bad, "features": [], "limits": {"bogus": 1}}, headers=bill_admin).status_code == 422
    assert client.post("/api/v1/platform/plans", json={**bad, "features": [], "base_price": "-1"}, headers=bill_admin).status_code == 422
    assert client.put(f"/api/v1/platform/plans/{p['id']}/items", json={"features": ["finance.*"], "limits": {"users": 3}}, headers=bill_admin).status_code == 204
    assert client.patch(f"/api/v1/platform/plans/{p['id']}/status", json={"status": "published"}, headers=bill_admin).status_code == 204
    assert client.put(f"/api/v1/platform/plans/{p['id']}/items", json={"features": [], "limits": {}}, headers=bill_admin).status_code == 409  # immutable
    assert client.patch(f"/api/v1/platform/plans/{p['id']}/status", json={"status": "draft"}, headers=bill_admin).status_code == 422
    reg = make_staff("registry_admin")["h"]
    assert client.post("/api/v1/platform/plans", json={**bad, "features": []}, headers=reg).status_code == 403
    pub = client.get("/api/v1/platform/plans", headers=reg).json()  # staff may read
    assert any(x["slug"] == p["slug"] for x in pub)


def test_unpublished_plans_are_not_visible_or_purchasable(client, bill_admin, make_tenant):
    draft = mk_plan(client, bill_admin, publish=False)
    t = make_tenant()
    assert draft["slug"] not in [p["slug"] for p in client.get("/api/v1/billing/plans", headers=t["h"]).json()]
    assert subscribe(client, t, draft).status_code == 404


# ------------------------------------------------------------------ free plan, entitlements, limits
def test_free_plan_activates_immediately_and_grants_entitlements(client, bill_admin, make_tenant):
    t = make_tenant()
    assert not entitled(t)
    r = subscribe(client, t, mk_plan(client, bill_admin))
    assert r.status_code == 201 and r.json()["status"] == "active" and r.json()["invoice_id"] is None
    assert entitled(t)
    assert subscribe(client, t, mk_plan(client, bill_admin)).status_code == 409  # one live base plan


def test_limits_enforced_for_users_companies_branches(client, bill_admin, make_tenant, invite_user):
    t = make_tenant()
    subscribe(client, t, mk_plan(client, bill_admin, limits={"users": 2, "companies": 1, "branches": 1}))
    invite_user(t, "member")  # owner + 1 = 2
    r = client.post("/api/v1/users/invitations", json={"email": "third@example.com"}, headers=t["h"])
    assert r.status_code == 403 and "users limit reached (2/2)" in r.json()["detail"]
    co = client.post("/api/v1/organizations/companies", json={"name": "A"}, headers=t["h"])
    assert co.status_code == 201
    assert client.post("/api/v1/organizations/companies", json={"name": "B"}, headers=t["h"]).status_code == 403
    assert client.post("/api/v1/organizations/branches", json={"company_id": co.json()["id"], "name": "b1"}, headers=t["h"]).status_code == 201
    assert client.post("/api/v1/organizations/branches", json={"company_id": co.json()["id"], "name": "b2"}, headers=t["h"]).status_code == 403
    lim = overview(client, t)["limits"]
    assert lim["users"] == {"used": 2, "limit": 2} and lim["companies"]["limit"] == 1


def test_addon_adds_limits_and_features(client, bill_admin, make_tenant):
    t = make_tenant()
    subscribe(client, t, mk_plan(client, bill_admin, features=(), limits={"companies": 1}))
    addon = mk_plan(client, bill_admin, kind="addon", features=("finance.*",), limits={"companies": 2})
    assert not entitled(t)
    assert subscribe(client, t, addon).status_code == 201
    assert entitled(t) and overview(client, t)["limits"]["companies"]["limit"] == 3
    assert subscribe(client, t, addon).status_code == 409  # same add-on twice


# ------------------------------------------------------------------ paid flow, payments
def test_paid_plan_requires_payment_and_payment_is_safe(client, bill_admin, make_tenant):
    t = make_tenant()
    plan = mk_plan(client, bill_admin, price="29.00")
    r = subscribe(client, t, plan).json()
    assert r["status"] == "pending" and r["amount_due"] == "29.00" and not entitled(t)
    assert pay(client, t, r["invoice_id"], "test_fail").status_code == 402
    assert overview(client, t)["subscriptions"][0]["status"] == "pending" and not entitled(t)
    ok = pay(client, t, r["invoice_id"], "test_ok", **{"Idempotency-Key": "k1"})
    assert ok.status_code == 200 and ok.json()["status"] == "paid"
    assert entitled(t) and overview(client, t)["subscriptions"][0]["status"] == "active"
    assert pay(client, t, r["invoice_id"]).status_code == 409  # cannot pay twice
    replay = pay(client, t, r["invoice_id"], "test_ok", **{"Idempotency-Key": "k1"})
    assert replay.status_code == 200 and replay.json().get("replayed") is True
    with tx(t["tenant_id"]) as c:
        assert c.execute(text("select count(*) from platform.payment_transactions where status='succeeded'")).scalar() == 1
        assert c.execute(text("select count(*) from platform.payment_transactions where status='failed'")).scalar() == 1


def test_per_user_pricing_uses_exact_decimal_arithmetic(client, bill_admin, make_tenant, invite_user):
    t = make_tenant()
    invite_user(t, "member")
    invite_user(t, "member")  # 3 members
    r = subscribe(client, t, mk_plan(client, bill_admin, price="10.00", per_user="4.99")).json()
    assert r["amount_due"] == "24.97"
    inv = overview(client, t)["invoices"][0]
    assert inv["total"] == "24.97" and [ln["amount"] for ln in inv["lines"]] == ["10.00", "14.97"]


def test_invoice_numbers_are_sequential_per_tenant(client, bill_admin, make_tenant):
    t = make_tenant()
    r = subscribe(client, t, mk_plan(client, bill_admin, price="5")).json()
    assert overview(client, t)["invoices"][0]["number"] == "INV-000001"
    pay(client, t, r["invoice_id"])


# ------------------------------------------------------------------ trial, renewal, grace, expiry
def test_trial_then_invoice_then_grace_then_pay(client, bill_admin, make_tenant):
    t = make_tenant()
    plan = mk_plan(client, bill_admin, price="10.00", trial=14)
    assert subscribe(client, t, plan).json()["status"] == "trialing" and entitled(t)
    start = datetime.now(UTC)
    rep = billing.run_billing(start + timedelta(days=7))
    assert rep["invoiced"] == 0  # still in trial
    rep = billing.run_billing(start + timedelta(days=15))
    assert rep["invoiced"] >= 1
    ov = overview(client, t)
    assert ov["subscriptions"][0]["status"] == "past_due" and ov["invoices"][0]["status"] == "open"
    assert entitled(t)  # grace keeps access
    again = billing.run_billing(start + timedelta(days=15))  # idempotent: no second invoice
    assert len(overview(client, t)["invoices"]) == 1 and again["invoiced"] == 0
    assert pay(client, t, ov["invoices"][0]["id"]).status_code == 200
    s = sub_row(t)
    assert s["status"] == "active" and s["grace_end"] is None and s["current_period_end"] > s["current_period_start"]
    assert entitled(t)


def test_unpaid_after_grace_expires_and_restricts(client, bill_admin, make_tenant):
    t = make_tenant()
    plan = mk_plan(client, bill_admin, price="10.00", limits={"companies": 5})
    inv = subscribe(client, t, plan).json()["invoice_id"]
    pay(client, t, inv)
    end = sub_row(t)["current_period_end"]
    billing.run_billing(end + timedelta(minutes=1))
    assert sub_row(t)["status"] == "past_due" and entitled(t)
    billing.run_billing(end + timedelta(days=8))  # beyond the 7-day grace
    assert sub_row(t)["status"] == "expired" and not entitled(t)
    open_invoices = [i for i in overview(client, t)["invoices"] if i["status"] == "open"]
    assert open_invoices == []  # unpaid renewal invoice was voided
    # restricted mode: lapsing never removes limits — nothing new can be created
    r = client.post("/api/v1/organizations/companies", json={"name": "Late"}, headers=t["h"])
    assert r.status_code == 403 and r.json()["type"] == "limit_exceeded"


def test_renewal_extends_period_by_one_month(client, bill_admin, make_tenant):
    t = make_tenant()
    inv = subscribe(client, t, mk_plan(client, bill_admin, price="10.00")).json()["invoice_id"]
    pay(client, t, inv)
    first_end = sub_row(t)["current_period_end"]
    billing.run_billing(first_end + timedelta(seconds=1))
    renewal = overview(client, t)["invoices"][0]
    assert renewal["status"] == "open" and renewal["total"] == "10.00"
    assert pay(client, t, renewal["id"]).status_code == 200
    s = sub_row(t)
    assert s["status"] == "active" and s["current_period_start"] == first_end
    assert s["current_period_end"] == billing.add_period(first_end, "monthly")


def test_free_plan_renews_without_invoice(client, bill_admin, make_tenant):
    t = make_tenant()
    subscribe(client, t, mk_plan(client, bill_admin))
    end = sub_row(t)["current_period_end"]
    rep = billing.run_billing(end + timedelta(seconds=1))
    assert rep["renewed_free"] >= 1 and overview(client, t)["invoices"] == []
    assert sub_row(t)["current_period_end"] > end


def test_cancel_at_period_end_and_resume(client, bill_admin, make_tenant):
    t = make_tenant()
    inv = subscribe(client, t, mk_plan(client, bill_admin, price="10.00")).json()["invoice_id"]
    pay(client, t, inv)
    sid = overview(client, t)["subscriptions"][0]["id"]
    assert client.post(f"/api/v1/billing/subscriptions/{sid}/cancel", headers=t["h"]).status_code == 204
    assert overview(client, t)["subscriptions"][0]["cancel_at_period_end"] and entitled(t)  # access until period end
    assert client.post(f"/api/v1/billing/subscriptions/{sid}/resume", headers=t["h"]).status_code == 204
    assert not overview(client, t)["subscriptions"][0]["cancel_at_period_end"]
    client.post(f"/api/v1/billing/subscriptions/{sid}/cancel", headers=t["h"])
    billing.run_billing(sub_row(t)["current_period_end"] + timedelta(seconds=1))
    assert sub_row(t)["status"] == "canceled" and not entitled(t)


# ------------------------------------------------------------------ plan changes
def test_upgrade_is_prorated_and_downgrade_waits_for_period_end(client, bill_admin, make_tenant):
    t = make_tenant()
    cheap = mk_plan(client, bill_admin, price="10.00", features=())
    dear = mk_plan(client, bill_admin, price="30.00", features=("finance.*",))
    pay(client, t, subscribe(client, t, cheap).json()["invoice_id"])
    s = sub_row(t)
    sid = s["id"]
    assert not entitled(t)
    half = s["current_period_start"] + (s["current_period_end"] - s["current_period_start"]) / 2
    out = billing.change_plan(UUID(t["tenant_id"]), None, sid, dear["slug"], now=half)
    assert out["applied"] == "immediately" and out["amount_due"] == "10.00"  # (30-10) * 0.5
    assert entitled(t)  # features switch immediately
    assert pay(client, t, out["invoice_id"]).status_code == 200
    down = billing.change_plan(UUID(t["tenant_id"]), None, sid, cheap["slug"], now=half)
    assert down["applied"] == "at_period_end" and entitled(t)
    assert overview(client, t)["subscriptions"][0]["pending_plan"] == cheap["slug"]
    billing.run_billing(s["current_period_end"] + timedelta(seconds=1))
    ov = overview(client, t)
    assert ov["subscriptions"][0]["plan"] == cheap["slug"] and ov["invoices"][0]["total"] == "10.00"


def test_downgrade_blocked_when_usage_exceeds_new_limits(client, bill_admin, make_tenant, invite_user):
    t = make_tenant()
    big = mk_plan(client, bill_admin, features=("finance.*",), limits={"users": 10})
    small = mk_plan(client, bill_admin, features=("finance.*",), limits={"users": 1})
    subscribe(client, t, big)
    invite_user(t, "member")
    with pytest.raises(Invalid, match="exceeds"):
        billing.change_plan(UUID(t["tenant_id"]), None, sub_row(t)["id"], small["slug"])


# ------------------------------------------------------------------ authz, isolation, staff
def test_members_cannot_manage_billing_but_admins_can(client, bill_admin, make_tenant, invite_user):
    t = make_tenant()
    plan = mk_plan(client, bill_admin)
    m = invite_user(t, "member")
    assert client.get("/api/v1/billing/overview", headers=m["h"]).status_code == 403
    assert client.post("/api/v1/billing/subscriptions", json={"plan": plan["slug"]}, headers=m["h"]).status_code == 403
    a = invite_user(t, "admin")
    assert client.post("/api/v1/billing/subscriptions", json={"plan": plan["slug"]}, headers=a["h"]).status_code == 201


def test_billing_data_is_tenant_isolated(client, bill_admin, make_tenant):
    a, b = make_tenant("a"), make_tenant("b")
    plan = mk_plan(client, bill_admin, price="9.00")
    inv = subscribe(client, a, plan).json()["invoice_id"]
    assert overview(client, b)["invoices"] == [] and overview(client, b)["subscriptions"] == []
    assert pay(client, b, inv).status_code == 404  # cannot pay (or see) another tenant's invoice
    assert pay(client, a, inv).status_code == 200


def test_staff_assign_comped_manual_payment_and_run(client, bill_admin, admin, make_tenant, make_staff):
    t = make_tenant()
    plan = mk_plan(client, bill_admin, price="50.00")
    comp = client.post(f"/api/v1/platform/tenants/{t['tenant_id']}/subscriptions", json={"plan": plan["slug"], "comped": True}, headers=bill_admin)
    assert comp.status_code == 201 and comp.json()["status"] == "active" and entitled(t)
    t2 = make_tenant()
    r = client.post(f"/api/v1/platform/tenants/{t2['tenant_id']}/subscriptions", json={"plan": plan["slug"]}, headers=bill_admin).json()
    assert r["status"] == "pending"
    url = f"/api/v1/platform/tenants/{t2['tenant_id']}/invoices/{r['invoice_id']}/mark-paid"
    assert client.post(url, json={"reference": ""}, headers=bill_admin).status_code == 422
    assert client.post(url, json={"reference": "WIRE-123"}, headers=bill_admin).status_code == 200 and entitled(t2)
    sup = make_staff("support_admin")["h"]
    assert client.post(f"/api/v1/platform/tenants/{t2['tenant_id']}/subscriptions", json={"plan": plan["slug"]}, headers=sup).status_code == 403
    assert client.post("/api/v1/platform/billing/run", json={}, headers=sup).status_code == 403
    subs = client.get("/api/v1/platform/subscriptions", headers=sup).json()
    assert any(s["tenant_slug"] == t["slug"] for s in subs) and "lines" not in subs[0]
    assert client.get("/api/v1/platform/audit/verify", headers=admin).json()["ok"]


def test_default_plan_is_applied_at_registration(client, bill_admin, make_tenant):
    p = mk_plan(client, bill_admin, limits={"users": 1}, default=True)
    try:
        t = make_tenant()
        assert overview(client, t)["subscriptions"][0]["plan"] == p["slug"]
        assert client.post("/api/v1/users/invitations", json={"email": "x@example.com"}, headers=t["h"]).status_code == 403
        r = client.post("/api/v1/platform/plans", json={"slug": f"d_{uid()}", "name": "d", "is_default": True}, headers=bill_admin)
        assert r.status_code == 409  # only one default at a time
    finally:
        client.patch(f"/api/v1/platform/plans/{p['id']}/status", json={"status": "archived"}, headers=bill_admin)


def test_test_payment_provider_is_disabled_outside_dev(monkeypatch):
    from ueos.platform import payments
    from ueos.platform.config import get_settings

    monkeypatch.setattr(get_settings(), "env", "prod")
    with pytest.raises(NotImplementedError):
        payments.get_provider("test")
    with pytest.raises(NotImplementedError):
        payments.get_provider("stripe")


def test_money_and_period_helpers():
    assert billing.money(Decimal("0.005")) == "0.01" and billing.money(Decimal("2.675")) == "2.68"
    assert billing.add_period(datetime(2026, 1, 31, tzinfo=UTC), "monthly") == datetime(2026, 2, 28, tzinfo=UTC)
    assert billing.add_period(datetime(2026, 3, 15, tzinfo=UTC), "annual") == datetime(2027, 3, 15, tzinfo=UTC)
