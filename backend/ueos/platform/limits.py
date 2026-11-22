"""Plan limits (users / companies / branches ...) enforced from the tenant's subscriptions.

Rules (documented in docs/MASTER_PLAN.md):
- A tenant that has never had a subscription is unrestricted (dev default; configure a default plan to change this).
- Base plan limit + sum of add-on limits. A missing or NULL limit item means unlimited.
- A tenant that has had subscriptions but none in good standing is in restricted mode: limit 0 (cannot add more),
  so letting a plan lapse can never *remove* limits.
"""

from datetime import UTC, datetime

from sqlalchemy import Connection, text

from ueos.platform.errors import LimitExceeded

GOOD = ("trialing", "active", "past_due")
KEYS = ("users", "companies", "branches")  # enforced now; storage_mb / api_calls are metered only


def access_until(status: str, trial_end: datetime | None, period_end: datetime | None, grace_end: datetime | None) -> datetime | None:
    if status == "trialing":
        return trial_end
    if status == "active":
        return period_end
    if status == "past_due":
        return grace_end
    return None


def effective_limit(conn: Connection, key: str, now: datetime | None = None) -> int | None:
    now = now or datetime.now(UTC)
    subs = conn.execute(text("select kind, plan_id, status, trial_end, current_period_end, grace_end from platform.subscriptions")).all()
    if not subs:
        return None
    base_found, base, add = False, 0, 0
    for s in subs:
        until = access_until(s.status, s.trial_end, s.current_period_end, s.grace_end)
        if s.status not in GOOD or until is None or until <= now:
            continue
        item = conn.execute(text("select limit_value from platform.plan_items where plan_id=:p and kind='limit' and limit_key=:k"),
                            {"p": s.plan_id, "k": key}).first()
        if s.kind == "base":
            base_found = True
            if item is None or item.limit_value is None:
                return None
            base = item.limit_value
        elif item is not None:
            if item.limit_value is None:
                return None
            add += item.limit_value
    return base + add if base_found else add


def usage_now(conn: Connection, key: str) -> int:
    if key == "users":
        members = conn.execute(text("select count(*) from platform.memberships where status='active'")).scalar() or 0
        pending = conn.execute(text("select count(*) from platform.invitations where accepted_at is null and expires_at > now()")).scalar() or 0
        return int(members) + int(pending)
    if key in ("companies", "branches"):
        return int(conn.execute(text(f"select count(*) from platform.{key}")).scalar() or 0)
    return 0


def enforce(conn: Connection, key: str, adding: int = 1) -> None:
    lim = effective_limit(conn, key)
    if lim is None:
        return
    cur = usage_now(conn, key)
    if cur + adding > lim:
        raise LimitExceeded(f"{key} limit reached ({cur}/{lim}) — upgrade your plan")


def snapshot(conn: Connection) -> dict[str, dict[str, int | None]]:
    return {k: {"used": usage_now(conn, k), "limit": effective_limit(conn, k)} for k in KEYS}
