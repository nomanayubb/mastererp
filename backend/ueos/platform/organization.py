"""Company -> branch -> department tree. Composite FKs (tenant_id, id) make cross-tenant references impossible."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from ueos.platform import audit
from ueos.platform.authz import Scope
from ueos.platform.db import tx
from ueos.platform.errors import Conflict, Invalid


def _insert(tenant_id: UUID, actor: UUID, table: str, entity: str, cols: dict[str, Any]) -> dict[str, Any]:
    eid = uuid4()
    names = ["id", "tenant_id", *cols]
    sql = f"insert into platform.{table} ({','.join(names)}) values ({','.join(':' + n for n in names)})"
    with tx(tenant_id) as c:
        try:
            with c.begin_nested():
                c.execute(text(sql), {"id": eid, "tenant_id": tenant_id, **cols})
        except Exception as e:
            state = getattr(getattr(e, "orig", None), "sqlstate", None)
            if state == "23505":
                raise Conflict(f"{entity} already exists") from e
            if state == "23503":
                raise Invalid("referenced record does not exist") from e
            raise
        audit.record(c, tenant_id, actor, f"{entity}.created", entity, eid, {k: v for k, v in cols.items() if v is not None})
    return {"id": str(eid), **{k: (str(v) if isinstance(v, UUID) else v) for k, v in cols.items()}}


def _list(tenant_id: UUID, table: str, scope: Scope | None, cols: dict[str, str | None]) -> list[dict[str, Any]]:
    where, params = scope.where(**cols) if scope else ("true", {})
    with tx(tenant_id) as c:
        rows = c.execute(text(f"select * from platform.{table} where {where} order by name"), params).mappings().all()
    return [{k: (str(v) if isinstance(v, UUID) else v) for k, v in r.items() if k != "tenant_id"} for r in rows]


def create_company(tenant_id: UUID, actor: UUID, name: str, legal_name: str | None, country: str | None, base_currency: str) -> dict[str, Any]:
    return _insert(tenant_id, actor, "companies", "company",
                   {"name": name, "legal_name": legal_name, "country": country, "base_currency": base_currency.upper()})


def create_branch(tenant_id: UUID, actor: UUID, company_id: UUID, name: str) -> dict[str, Any]:
    return _insert(tenant_id, actor, "branches", "branch", {"company_id": company_id, "name": name})


def create_department(tenant_id: UUID, actor: UUID, company_id: UUID, branch_id: UUID | None,
                      parent_id: UUID | None, name: str) -> dict[str, Any]:
    return _insert(tenant_id, actor, "departments", "department",
                   {"company_id": company_id, "branch_id": branch_id, "parent_id": parent_id, "name": name})


def list_companies(t: UUID, scope: Scope | None = None) -> list[dict[str, Any]]:
    return _list(t, "companies", scope, {"company": "id"})


def list_branches(t: UUID, scope: Scope | None = None) -> list[dict[str, Any]]:
    return _list(t, "branches", scope, {"company": "company_id", "branch": "id"})


def list_departments(t: UUID, scope: Scope | None = None) -> list[dict[str, Any]]:
    return _list(t, "departments", scope, {"company": "company_id", "branch": "branch_id", "department": "id"})


def get_tenant(tenant_id: UUID) -> dict[str, Any]:
    with tx(tenant_id) as c:
        r = c.execute(text("select id, slug, name, status, data_region, created_at from platform.tenants")).mappings().one()
    return {**r, "id": str(r["id"])}


def audit_list(tenant_id: UUID, limit: int = 100) -> list[dict[str, Any]]:
    with tx(tenant_id) as c:
        rows = c.execute(text("select seq, ts, actor_user_id, action, entity_type, entity_id, data from platform.audit_log"
                              " order by seq desc limit :l"), {"l": min(limit, 500)}).mappings().all()
    return [{k: (str(v) if isinstance(v, UUID) else v) for k, v in r.items()} for r in rows]


def audit_verify(tenant_id: UUID) -> dict[str, Any]:
    with tx(tenant_id) as c:
        return audit.verify(c, tenant_id)
