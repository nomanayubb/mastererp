"""Plans, subscriptions, invoices, renewals, proration, entitlement materialization.

Lifecycle: pending -> (paid) -> active ... renewal -> past_due (grace) -> (paid) active | expired
           trialing -> first invoice -> past_due -> (paid) active | expired
           active --cancel--> canceled at period end.
Access (entitlements) exists only while status in (trialing, active, past_due) and `access_until` is in the future.
All money is Decimal (NUMERIC(12,2)). Every function takes `now` so the clock can be simulated in tests.
"""

import calendar
import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from ueos.platform import audit, limits, payments, registry
from ueos.platform.config import get_settings
from ueos.platform.db import tx
from ueos.platform.errors import Conflict, Forbidden, Invalid, NotFound, PaymentFailed
from ueos.platform.limits import GOOD, access_until

LIVE = ("pending", *GOOD)
LIMIT_KEYS = ("users", "companies", "branches", "storage_mb", "api_calls")
CENT = Decimal("0.01")


def q(x: Decimal | int | str) -> Decimal:
    return Decimal(x).quantize(CENT, ROUND_HALF_UP)


def money(x: Decimal) -> str:
    return format(q(x), "f")


def add_period(dt: datetime, period: str) -> datetime:
    months = 1 if period == "monthly" else 12
    y, m = divmod(dt.month - 1 + months, 12)
    year, month = dt.year + y, m + 1
    return dt.replace(year=year, month=month, day=min(dt.day, calendar.monthrange(year, month)[1]))


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


# ------------------------------------------------------------------ plans (staff)
def _plan_dict(c: Connection, r: Any) -> dict[str, Any]:
    items = c.execute(text("select kind, feature_pattern, limit_key, limit_value from platform.plan_items where plan_id=:p"),
                      {"p": r.id}).all()
    return {"id": str(r.id), "slug": r.slug, "name": r.name, "description": r.description, "kind": r.kind, "status": r.status,
            "billing_period": r.billing_period, "currency": r.currency.strip(), "base_price": money(r.base_price),
            "per_user_price": money(r.per_user_price), "trial_days": r.trial_days, "is_default": r.is_default,
            "is_public": r.is_public,
            "features": sorted(i.feature_pattern for i in items if i.kind == "feature"),
            "limits": {i.limit_key: i.limit_value for i in items if i.kind == "limit"}}


def _write_items(c: Connection, plan_id: UUID, features: list[str], lim: dict[str, int | None]) -> None:
    c.execute(text("delete from platform.plan_items where plan_id=:p"), {"p": plan_id})
    for f in sorted(set(features)):
        registry.validate_permission(c, f, "*")
        c.execute(text("insert into platform.plan_items (id, plan_id, kind, feature_pattern) values (:i,:p,'feature',:f)"),
                  {"i": uuid4(), "p": plan_id, "f": f})
    for k, v in lim.items():
        if k not in LIMIT_KEYS:
            raise Invalid(f"unknown limit '{k}' (allowed: {', '.join(LIMIT_KEYS)})")
        if v is not None and v < 0:
            raise Invalid("limits cannot be negative")
        c.execute(text("insert into platform.plan_items (id, plan_id, kind, limit_key, limit_value) values (:i,:p,'limit',:k,:v)"),
                  {"i": uuid4(), "p": plan_id, "k": k, "v": v})


def create_plan(staff_id: UUID, d: dict[str, Any]) -> dict[str, Any]:
    if not d["slug"].replace("_", "").isalnum() or not d["slug"][0].isalpha() or d["slug"] != d["slug"].lower():
        raise Invalid("slug must be lowercase letters, digits, underscores, starting with a letter")
    if d["kind"] not in ("base", "addon") or d["billing_period"] not in ("monthly", "annual"):
        raise Invalid("kind must be base|addon and billing_period monthly|annual")
    if d["is_default"] and d["kind"] != "base":
        raise Invalid("only a base plan can be the default plan")
    pid = uuid4()
    with tx(None) as c:
        try:
            with c.begin_nested():
                c.execute(text("insert into platform.plans (id, slug, name, description, kind, billing_period, currency, base_price,"
                               " per_user_price, trial_days, is_default, is_public) values (:i,:s,:n,:d,:k,:bp,:cur,:bpr,:upr,:td,:def,:pub)"),
                          {"i": pid, "s": d["slug"], "n": d["name"], "d": d["description"], "k": d["kind"], "bp": d["billing_period"],
                           "cur": d["currency"].upper(), "bpr": q(d["base_price"]), "upr": q(d["per_user_price"]),
                           "td": d["trial_days"], "def": d["is_default"], "pub": d["is_public"]})
        except Exception as e:
            st = getattr(getattr(e, "orig", None), "sqlstate", None)
            if st == "23505":
                raise Conflict("plan slug already exists or another default plan is set") from e
            if st == "23514":
                raise Invalid("invalid price or trial value") from e
            raise
        _write_items(c, pid, d["features"], d["limits"])
        audit.record_platform(c, staff_id, "plan.created", "plan", pid, {"slug": d["slug"]})
        return _plan_dict(c, c.execute(text("select * from platform.plans where id=:i"), {"i": pid}).first())


def replace_plan_items(staff_id: UUID, plan_id: UUID, features: list[str], lim: dict[str, int | None]) -> None:
    with tx(None) as c:
        st = c.execute(text("select status from platform.plans where id=:i"), {"i": plan_id}).scalar()
        if st is None:
            raise NotFound("plan not found")
        if st != "draft":
            raise Conflict("only draft plans can be edited; published plans are immutable (create a new plan instead)")
        _write_items(c, plan_id, features, lim)
        audit.record_platform(c, staff_id, "plan.items_replaced", "plan", plan_id)


def set_plan_status(staff_id: UUID, plan_id: UUID, status: str) -> None:
    allowed = {"draft": ("published",), "published": ("archived",), "archived": ()}
    with tx(None) as c:
        cur = c.execute(text("select status from platform.plans where id=:i"), {"i": plan_id}).scalar()
        if cur is None:
            raise NotFound("plan not found")
        if status not in allowed[cur]:
            raise Invalid(f"cannot move a {cur} plan to {status}")
        c.execute(text("update platform.plans set status=:s where id=:i"), {"s": status, "i": plan_id})
        audit.record_platform(c, staff_id, "plan.status_changed", "plan", plan_id, {"status": status})


def list_plans(public_only: bool) -> list[dict[str, Any]]:
    with tx(None) as c:
        where = "where status='published' and is_public" if public_only else ""
        return [_plan_dict(c, r) for r in c.execute(text(f"select * from platform.plans {where} order by base_price, slug")).all()]


# ------------------------------------------------------------------ pricing
def _users(c: Connection) -> int:
    return max(1, int(c.execute(text("select count(*) from platform.memberships where status='active'")).scalar() or 0))


def price(plan: Any, users: int) -> tuple[Decimal, list[dict[str, str]]]:
    lines = [{"description": f"{plan.name} ({plan.billing_period}) — base", "amount": money(plan.base_price)}]
    total = Decimal(plan.base_price)
    if plan.per_user_price and Decimal(plan.per_user_price) > 0:
        amt = q(Decimal(plan.per_user_price) * users)
        lines.append({"description": f"Users: {users} × {money(plan.per_user_price)}", "amount": money(amt)})
        total += amt
    return q(total), lines


# ------------------------------------------------------------------ entitlement sync
def sync_entitlements(c: Connection, tenant_id: UUID, now: datetime | None = None) -> None:
    now = _now(now)
    c.execute(text("delete from platform.entitlements where source='subscription'"))
    best: dict[str, datetime] = {}
    for s in c.execute(text("select plan_id, status, trial_end, current_period_end, grace_end from platform.subscriptions")).all():
        until = access_until(s.status, s.trial_end, s.current_period_end, s.grace_end)
        if s.status not in GOOD or until is None or until <= now:
            continue
        for it in c.execute(text("select feature_pattern from platform.plan_items where plan_id=:p and kind='feature'"), {"p": s.plan_id}):
            if it.feature_pattern not in best or until > best[it.feature_pattern]:
                best[it.feature_pattern] = until
    for pattern, until in best.items():
        c.execute(text("insert into platform.entitlements (id, tenant_id, feature_key, source, expires_at) values (:i,:t,:k,'subscription',:e)"),
                  {"i": uuid4(), "t": tenant_id, "k": pattern, "e": until})


def _event(c: Connection, tenant_id: UUID, typ: str, data: dict[str, Any]) -> None:
    c.execute(text("insert into platform.billing_events (tenant_id, type, data) values (:t,:y,cast(:d as jsonb))"),
              {"t": tenant_id, "y": typ, "d": json.dumps(data, default=str)})


# ------------------------------------------------------------------ invoices
def _new_invoice(c: Connection, tenant_id: UUID, sub_id: UUID, kind: str, start: datetime, end: datetime, currency: str,
                 lines: list[dict[str, str]], total: Decimal, now: datetime) -> UUID | None:
    c.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"invoice:{tenant_id}"})
    seq = (c.execute(text("select coalesce(max(seq),0)+1 from platform.invoices")).scalar() or 1)
    iid = uuid4()
    r = c.execute(
        text("insert into platform.invoices (id, tenant_id, subscription_id, seq, number, kind, period_start, period_end, currency,"
             " subtotal, total, lines, due_at) values (:i,:t,:s,:seq,:num,:k,:ps,:pe,:cur,:tot,:tot,cast(:l as jsonb),:due)"
             " on conflict (subscription_id, period_start) where kind = 'subscription' do nothing returning id"),
        {"i": iid, "t": tenant_id, "s": sub_id, "seq": seq, "num": f"INV-{seq:06d}", "k": kind, "ps": start, "pe": end,
         "cur": currency.strip(), "tot": total, "l": json.dumps(lines), "due": now}).first()
    return r.id if r else None


def _create_subscription(c: Connection, tenant_id: UUID, plan: Any, now: datetime, comped: bool, actor: UUID | None) -> dict[str, Any]:
    if c.execute(text("select 1 from platform.subscriptions where plan_id=:p and kind=:k and status in ('pending','trialing','active','past_due')"),
                 {"p": plan.id, "k": plan.kind}).first() and plan.kind == "addon":
        raise Conflict("this add-on is already active")
    if plan.kind == "base" and c.execute(text("select 1 from platform.subscriptions where kind='base' and status in ('pending','trialing','active','past_due')")).first():
        raise Conflict("already subscribed to a base plan — change plan instead")
    sid = uuid4()
    users = _users(c)
    total, lines = price(plan, users)
    had = c.execute(text("select 1 from platform.subscriptions where plan_id=:p"), {"p": plan.id}).first()
    status, ps, pe, te = "pending", None, None, None
    if plan.trial_days > 0 and not had and not comped:
        status, ps, te = "trialing", now, now + timedelta(days=plan.trial_days)
        pe = te
    elif total == 0 or comped:
        status, ps, pe = "active", now, add_period(now, plan.billing_period)
    c.execute(text("insert into platform.subscriptions (id, tenant_id, plan_id, kind, status, current_period_start, current_period_end,"
                   " trial_end, comped, started_at) values (:i,:t,:p,:k,:st,:ps,:pe,:te,:cm,:now)"),
              {"i": sid, "t": tenant_id, "p": plan.id, "k": plan.kind, "st": status, "ps": ps, "pe": pe, "te": te, "cm": comped, "now": now})
    inv = None
    if status == "pending":
        inv = _new_invoice(c, tenant_id, sid, "subscription", now, add_period(now, plan.billing_period), plan.currency, lines, total, now)
    sync_entitlements(c, tenant_id, now)
    audit.record(c, tenant_id, actor, "subscription.created", "subscription", sid, {"plan": plan.slug, "status": status, "comped": comped})
    _event(c, tenant_id, "subscription.created", {"subscription": str(sid), "plan": plan.slug, "status": status})
    return {"id": str(sid), "status": status, "plan": plan.slug, "invoice_id": str(inv) if inv else None, "amount_due": money(total) if inv else "0.00"}


def _published_plan(c: Connection, slug: str) -> Any:
    plan = c.execute(text("select * from platform.plans where slug=:s"), {"s": slug}).first()
    if not plan or plan.status != "published":
        raise NotFound("plan not found or not available")
    return plan


def subscribe(tenant_id: UUID, actor: UUID | None, plan_slug: str, *, comped: bool = False, now: datetime | None = None) -> dict[str, Any]:
    now = _now(now)
    with tx(tenant_id) as c:
        return _create_subscription(c, tenant_id, _published_plan(c, plan_slug), now, comped, actor)


def subscribe_default(c: Connection, tenant_id: UUID) -> None:
    """Called inside tenant registration: subscribe to the published default plan, if one is configured."""
    plan = c.execute(text("select * from platform.plans where is_default and status='published' and kind='base'")).first()
    if plan:
        _create_subscription(c, tenant_id, plan, datetime.now(UTC), comped=False, actor=None)


# ------------------------------------------------------------------ payment
def pay_invoice(tenant_id: UUID, invoice_id: UUID, actor: UUID | None, method: str, provider: str | None = None,
                idempotency_key: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = _now(now)
    prov = payments.get_provider(provider)
    failure: str | None = None
    with tx(tenant_id) as c:
        inv = c.execute(text("select * from platform.invoices where id=:i for update"), {"i": invoice_id}).first()
        if not inv:
            raise NotFound("invoice not found")
        if idempotency_key:
            prior = c.execute(text("select invoice_id, status from platform.payment_transactions where idempotency_key=:k"),
                              {"k": idempotency_key}).first()
            if prior:
                if prior.invoice_id != invoice_id:
                    raise Conflict("idempotency key already used for a different invoice")
                return {"invoice_id": str(invoice_id), "status": "paid" if prior.status == "succeeded" else "open", "replayed": True}
        if inv.status == "paid":
            raise Conflict("invoice already paid")
        if inv.status == "void":
            raise Invalid("invoice is void")
        res = prov.charge(Decimal(inv.total), inv.currency.strip(), method)
        c.execute(text("insert into platform.payment_transactions (id, tenant_id, invoice_id, amount, currency, status, provider,"
                       " provider_ref, idempotency_key) values (:i,:t,:inv,:a,:cur,:st,:pv,:ref,:k)"),
                  {"i": uuid4(), "t": tenant_id, "inv": invoice_id, "a": inv.total, "cur": inv.currency.strip(),
                   "st": "succeeded" if res.ok else "failed", "pv": prov.name, "ref": res.ref, "k": idempotency_key})
        if res.ok:
            c.execute(text("update platform.invoices set status='paid', paid_at=:n where id=:i"), {"n": now, "i": invoice_id})
            _apply_paid(c, tenant_id, inv, now)
            audit.record(c, tenant_id, actor, "invoice.paid", "invoice", invoice_id, {"number": inv.number, "amount": money(inv.total), "provider": prov.name})
            _event(c, tenant_id, "invoice.paid", {"invoice": inv.number})
            return {"invoice_id": str(invoice_id), "status": "paid", "number": inv.number}
        failure = res.reason or "declined"
        audit.record(c, tenant_id, actor, "invoice.payment_failed", "invoice", invoice_id, {"number": inv.number, "reason": failure})
        _event(c, tenant_id, "invoice.payment_failed", {"invoice": inv.number, "reason": failure})
    raise PaymentFailed(failure or "declined")


def _apply_paid(c: Connection, tenant_id: UUID, inv: Any, now: datetime) -> None:
    sub = c.execute(text("select s.*, p.billing_period from platform.subscriptions s join platform.plans p on p.id = s.plan_id"
                         " where s.id=:i for update of s"), {"i": inv.subscription_id}).first()
    if sub and inv.kind == "subscription" and sub.status in ("pending", "past_due", "trialing", "active"):
        if sub.status == "pending":
            start, end = now, add_period(now, sub.billing_period)
        else:
            start, end = inv.period_start, inv.period_end
        c.execute(text("update platform.subscriptions set status='active', current_period_start=:s, current_period_end=:e,"
                       " grace_end=null, trial_end=null where id=:i"), {"s": start, "e": end, "i": sub.id})
    sync_entitlements(c, tenant_id, now)


# ------------------------------------------------------------------ plan change / cancel
def change_plan(tenant_id: UUID, actor: UUID | None, sub_id: UUID, new_slug: str, now: datetime | None = None) -> dict[str, Any]:
    now = _now(now)
    with tx(tenant_id) as c:
        sub = c.execute(text("select s.*, p.base_price as old_base, p.per_user_price as old_pu from platform.subscriptions s"
                             " join platform.plans p on p.id = s.plan_id where s.id=:i for update of s"), {"i": sub_id}).first()
        if not sub:
            raise NotFound("subscription not found")
        if sub.status not in ("trialing", "active"):
            raise Invalid(f"cannot change plan while subscription is {sub.status}")
        new = _published_plan(c, new_slug)
        if new.id == sub.plan_id or new.kind != sub.kind:
            raise Invalid("choose a different plan of the same kind")
        for key in limits.KEYS:  # never downgrade into an immediate violation
            row = c.execute(text("select limit_value from platform.plan_items where plan_id=:p and kind='limit' and limit_key=:k"),
                            {"p": new.id, "k": key}).first()
            if row is not None and row.limit_value is not None:
                used = limits.usage_now(c, key)
                if used > row.limit_value:
                    raise Invalid(f"current usage exceeds the new plan's {key} limit ({used} > {row.limit_value})")
        users = _users(c)
        new_total, _ = price(new, users)
        old_total = q(Decimal(sub.old_base) + Decimal(sub.old_pu) * users)
        if sub.status == "trialing" or new_total > old_total:
            inv_id = None
            charge = Decimal(0)
            if sub.status == "active" and sub.current_period_end and sub.current_period_start:
                span = Decimal((sub.current_period_end - sub.current_period_start).total_seconds())
                left = max(Decimal((sub.current_period_end - now).total_seconds()), Decimal(0))
                charge = q((new_total - old_total) * (left / span if span else Decimal(0)))
            c.execute(text("update platform.subscriptions set plan_id=:p, pending_plan_id=null where id=:i"), {"p": new.id, "i": sub_id})
            if charge > 0:
                inv_id = _new_invoice(c, tenant_id, sub_id, "proration", now, sub.current_period_end, new.currency,
                                      [{"description": f"Upgrade to {new.name} — prorated difference", "amount": money(charge)}], charge, now)
            sync_entitlements(c, tenant_id, now)
            out = {"applied": "immediately", "invoice_id": str(inv_id) if inv_id else None, "amount_due": money(charge)}
        else:
            c.execute(text("update platform.subscriptions set pending_plan_id=:p where id=:i"), {"p": new.id, "i": sub_id})
            out = {"applied": "at_period_end", "invoice_id": None, "amount_due": "0.00"}
        audit.record(c, tenant_id, actor, "subscription.plan_change", "subscription", sub_id, {"to": new.slug, **out})
        _event(c, tenant_id, "subscription.plan_change", {"to": new.slug, **out})
        return out


def cancel(tenant_id: UUID, actor: UUID | None, sub_id: UUID, immediate: bool = False, now: datetime | None = None) -> None:
    now = _now(now)
    with tx(tenant_id) as c:
        s = c.execute(text("select status from platform.subscriptions where id=:i for update"), {"i": sub_id}).first()
        if not s:
            raise NotFound("subscription not found")
        if s.status in ("canceled", "expired"):
            raise Invalid(f"subscription already {s.status}")
        if immediate or s.status in ("pending", "past_due"):
            c.execute(text("update platform.subscriptions set status='canceled', ended_at=:n, cancel_at_period_end=false where id=:i"), {"n": now, "i": sub_id})
            c.execute(text("update platform.invoices set status='void' where subscription_id=:i and status='open'"), {"i": sub_id})
            sync_entitlements(c, tenant_id, now)
        else:
            c.execute(text("update platform.subscriptions set cancel_at_period_end=true where id=:i"), {"i": sub_id})
        audit.record(c, tenant_id, actor, "subscription.canceled", "subscription", sub_id, {"immediate": immediate})
        _event(c, tenant_id, "subscription.canceled", {"subscription": str(sub_id), "immediate": immediate})


def resume(tenant_id: UUID, actor: UUID | None, sub_id: UUID) -> None:
    with tx(tenant_id) as c:
        n = c.execute(text("update platform.subscriptions set cancel_at_period_end=false where id=:i and status in ('active','trialing')"),
                      {"i": sub_id}).rowcount
        if not n:
            raise Invalid("nothing to resume")
        audit.record(c, tenant_id, actor, "subscription.resumed", "subscription", sub_id)


# ------------------------------------------------------------------ billing run (renewals, trials, grace, expiry)
def _renew(c: Connection, tenant_id: UUID, sub: Any, now: datetime, grace_days: int) -> str:
    plan_id = sub.pending_plan_id or sub.plan_id
    plan = c.execute(text("select * from platform.plans where id=:i"), {"i": plan_id}).one()
    start = sub.current_period_end
    end = add_period(start, plan.billing_period)
    total, lines = price(plan, _users(c))
    if sub.pending_plan_id:
        c.execute(text("update platform.subscriptions set plan_id=pending_plan_id, pending_plan_id=null where id=:i"), {"i": sub.id})
    if total == 0 or sub.comped:
        c.execute(text("update platform.subscriptions set status='active', current_period_start=:s, current_period_end=:e,"
                       " trial_end=null, grace_end=null where id=:i"), {"s": start, "e": end, "i": sub.id})
        return "renewed_free"
    inv = _new_invoice(c, tenant_id, sub.id, "subscription", start, end, plan.currency, lines, total, now)
    if inv is None:
        return "already_invoiced"
    c.execute(text("update platform.subscriptions set status='past_due', grace_end=:g where id=:i"),
              {"g": now + timedelta(days=grace_days), "i": sub.id})
    _event(c, tenant_id, "invoice.created", {"subscription": str(sub.id), "total": money(total)})
    return "invoiced"


def run_billing(now: datetime | None = None) -> dict[str, int]:
    now = _now(now)
    grace = get_settings().grace_days
    rep = {"invoiced": 0, "renewed_free": 0, "canceled": 0, "expired": 0}
    with tx(None) as c:
        tenants = [r.id for r in c.execute(text("select id from platform.list_tenants() where status='active'")).all()]
    for tid in tenants:
        with tx(tid) as c:
            changed = False
            for sub in c.execute(text("select * from platform.subscriptions where status in ('trialing','active','past_due') for update")).all():
                if sub.status == "trialing" and sub.trial_end and sub.trial_end <= now:
                    r = _renew(c, tid, sub, now, grace)  # for trials current_period_end == trial_end
                    if r in ("invoiced", "renewed_free"):
                        rep[r] += 1
                    changed = True
                elif sub.status == "active" and sub.current_period_end and sub.current_period_end <= now:
                    if sub.cancel_at_period_end:
                        c.execute(text("update platform.subscriptions set status='canceled', ended_at=:n where id=:i"), {"n": now, "i": sub.id})
                        audit.record(c, tid, None, "subscription.ended", "subscription", sub.id, {"reason": "canceled_at_period_end"})
                        rep["canceled"] += 1
                    else:
                        r = _renew(c, tid, sub, now, grace)
                        if r in ("invoiced", "renewed_free"):
                            rep[r] += 1
                    changed = True
                elif sub.status == "past_due" and sub.grace_end and sub.grace_end <= now:
                    c.execute(text("update platform.subscriptions set status='expired', ended_at=:n where id=:i"), {"n": now, "i": sub.id})
                    c.execute(text("update platform.invoices set status='void' where subscription_id=:i and status='open'"), {"i": sub.id})
                    audit.record(c, tid, None, "subscription.expired", "subscription", sub.id, {"reason": "unpaid_after_grace"})
                    _event(c, tid, "subscription.expired", {"subscription": str(sub.id)})
                    rep["expired"] += 1
                    changed = True
            if changed:
                sync_entitlements(c, tid, now)
    return rep


# ------------------------------------------------------------------ reads
def overview(tenant_id: UUID) -> dict[str, Any]:
    with tx(tenant_id) as c:
        subs = c.execute(text("select s.*, p.slug, p.name, p.billing_period, p.currency, pp.slug as pending_slug from platform.subscriptions s"
                              " join platform.plans p on p.id = s.plan_id left join platform.plans pp on pp.id = s.pending_plan_id"
                              " order by s.started_at desc")).mappings().all()
        invs = c.execute(text("select id, number, kind, status, total, currency, due_at, paid_at, lines, subscription_id from platform.invoices"
                              " order by seq desc limit 50")).mappings().all()
        snap = limits.snapshot(c)
        usage = c.execute(text("select metric, sum(quantity) as qty from platform.usage_records group by metric")).mappings().all()
    return {
        "subscriptions": [{"id": str(s["id"]), "plan": s["slug"], "plan_name": s["name"], "kind": s["kind"], "status": s["status"],
                           "period_end": s["current_period_end"], "trial_end": s["trial_end"], "grace_end": s["grace_end"],
                           "cancel_at_period_end": s["cancel_at_period_end"], "pending_plan": s["pending_slug"],
                           "access_until": access_until(s["status"], s["trial_end"], s["current_period_end"], s["grace_end"])} for s in subs],
        "invoices": [{"id": str(i["id"]), "number": i["number"], "kind": i["kind"], "status": i["status"], "total": money(i["total"]),
                      "currency": i["currency"].strip(), "due_at": i["due_at"], "paid_at": i["paid_at"], "lines": i["lines"]} for i in invs],
        "limits": snap,
        "usage": {u["metric"]: str(u["qty"]) for u in usage},
    }


def record_usage(tenant_id: UUID, metric: str, quantity: Decimal) -> None:
    if quantity < 0:
        raise Invalid("quantity cannot be negative")
    with tx(tenant_id) as c:
        c.execute(text("insert into platform.usage_records (id, tenant_id, metric, quantity) values (:i,:t,:m,:q)"),
                  {"i": uuid4(), "t": tenant_id, "m": metric, "q": quantity})


def list_all_subscriptions() -> list[dict[str, Any]]:
    with tx(None) as c:
        return [{**r, "tenant_id": str(r["tenant_id"])} for r in c.execute(text("select * from platform.list_subscriptions()")).mappings().all()]


def staff_assign(staff_id: UUID, tenant_id: UUID, plan_slug: str, comped: bool, now: datetime | None = None) -> dict[str, Any]:
    out = subscribe(tenant_id, None, plan_slug, comped=comped, now=now)
    with tx(tenant_id) as c:
        audit.record_platform(c, staff_id, "subscription.assigned_by_staff", "tenant", tenant_id, {"plan": plan_slug, "comped": comped})
    return out


def staff_guard(role: str) -> None:
    if role not in ("super_admin", "subscription_admin"):
        raise Forbidden("requires super_admin or subscription_admin")
