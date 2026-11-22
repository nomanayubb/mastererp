"""Tamper-evident, per-tenant hash-chained audit log (append-only; UPDATE/DELETE blocked by trigger and grants)."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

GENESIS = "0" * 64


def _hash(tenant_id: str, seq: int, ts: datetime, actor: str | None, action: str,
          etype: str | None, eid: str | None, data: dict[str, Any], prev: str) -> str:
    payload = json.dumps(
        [tenant_id, seq, ts.astimezone(UTC).isoformat(timespec="microseconds"), actor, action, etype, eid, data, prev],
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def record(conn: Connection, tenant_id: UUID | str, actor: UUID | str | None, action: str,
           entity_type: str | None = None, entity_id: UUID | str | None = None,
           data: dict[str, Any] | None = None) -> None:
    """Call inside the caller's transaction so the audit row commits atomically with the change."""
    t, a, e = str(tenant_id), (str(actor) if actor else None), (str(entity_id) if entity_id else None)
    d = json.loads(json.dumps(data or {}, default=str))
    conn.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"audit:{t}"})
    last = conn.execute(
        text("select seq, hash from platform.audit_log where tenant_id = :t order by seq desc limit 1"), {"t": t}
    ).first()
    seq = (last.seq + 1) if last else 1
    prev = last.hash if last else GENESIS
    ts = datetime.now(UTC)
    h = _hash(t, seq, ts, a, action, entity_type, e, d, prev)
    conn.execute(
        text(
            "insert into platform.audit_log (tenant_id, seq, ts, actor_user_id, action, entity_type, entity_id, data,"
            " prev_hash, hash) values (:t, :seq, :ts, :a, :action, :et, :e, cast(:d as jsonb), :prev, :h)"
        ),
        {"t": t, "seq": seq, "ts": ts, "a": a, "action": action, "et": entity_type, "e": e,
         "d": json.dumps(d), "prev": prev, "h": h},
    )


PLATFORM_SCOPE = "platform"


def record_platform(conn: Connection, actor: UUID | str | None, action: str, entity_type: str | None = None,
                    entity_id: UUID | str | None = None, data: dict[str, Any] | None = None) -> None:
    """Platform-staff audit stream (single hash chain)."""
    a, e = (str(actor) if actor else None), (str(entity_id) if entity_id else None)
    d = json.loads(json.dumps(data or {}, default=str))
    conn.execute(text("select pg_advisory_xact_lock(hashtextextended('audit:platform', 0))"))
    last = conn.execute(text("select seq, hash from platform.platform_audit_log order by seq desc limit 1")).first()
    seq = (last.seq + 1) if last else 1
    prev = last.hash if last else GENESIS
    ts = datetime.now(UTC)
    h = _hash(PLATFORM_SCOPE, seq, ts, a, action, entity_type, e, d, prev)
    conn.execute(
        text("insert into platform.platform_audit_log (seq, ts, actor_staff_id, action, entity_type, entity_id, data, prev_hash, hash)"
             " values (:seq, :ts, :a, :action, :et, :e, cast(:d as jsonb), :prev, :h)"),
        {"seq": seq, "ts": ts, "a": a, "action": action, "et": entity_type, "e": e, "d": json.dumps(d), "prev": prev, "h": h},
    )


def verify_platform(conn: Connection) -> dict[str, Any]:
    rows = conn.execute(text("select seq, ts, actor_staff_id, action, entity_type, entity_id, data, prev_hash, hash"
                             " from platform.platform_audit_log order by seq")).all()
    prev, expected = GENESIS, 1
    for r in rows:
        h = _hash(PLATFORM_SCOPE, r.seq, r.ts, str(r.actor_staff_id) if r.actor_staff_id else None, r.action,
                  r.entity_type, r.entity_id, r.data, prev)
        if r.seq != expected or r.prev_hash != prev or r.hash != h:
            return {"ok": False, "count": len(rows), "first_bad_seq": r.seq}
        prev, expected = r.hash, expected + 1
    return {"ok": True, "count": len(rows), "first_bad_seq": None}


def verify(conn: Connection, tenant_id: UUID | str) -> dict[str, Any]:
    rows = conn.execute(
        text("select seq, ts, actor_user_id, action, entity_type, entity_id, data, prev_hash, hash"
             " from platform.audit_log where tenant_id = :t order by seq"), {"t": str(tenant_id)}
    ).all()
    prev, expected = GENESIS, 1
    for r in rows:
        h = _hash(str(tenant_id), r.seq, r.ts, str(r.actor_user_id) if r.actor_user_id else None, r.action,
                  r.entity_type, str(r.entity_id) if r.entity_id else None, r.data, prev)
        if r.seq != expected or r.prev_hash != prev or r.hash != h:
            return {"ok": False, "count": len(rows), "first_bad_seq": r.seq}
        prev, expected = r.hash, expected + 1
    return {"ok": True, "count": len(rows), "first_bad_seq": None}
