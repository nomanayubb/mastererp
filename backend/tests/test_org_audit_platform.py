import psycopg
import pytest
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ueos import devdb
from ueos.platform.db import tx


def test_org_tree_and_validation(client, make_tenant):
    t = make_tenant()
    co = client.post("/api/v1/organizations/companies", json={"name": "HQ", "country": "PK", "base_currency": "pkr"}, headers=t["h"]).json()
    assert co["base_currency"] == "PKR"
    assert client.post("/api/v1/organizations/companies", json={"name": "HQ"}, headers=t["h"]).status_code == 409
    br = client.post("/api/v1/organizations/branches", json={"company_id": co["id"], "name": "Lahore"}, headers=t["h"]).json()
    d1 = client.post("/api/v1/organizations/departments", json={"company_id": co["id"], "branch_id": br["id"], "name": "Finance"}, headers=t["h"]).json()
    d2 = client.post("/api/v1/organizations/departments", json={"company_id": co["id"], "parent_id": d1["id"], "name": "AP"}, headers=t["h"])
    assert d2.status_code == 201
    assert len(client.get("/api/v1/organizations/departments", headers=t["h"]).json()) == 2
    bad = client.post("/api/v1/organizations/branches", json={"company_id": "00000000-0000-0000-0000-000000000000", "name": "X"}, headers=t["h"])
    assert bad.status_code == 422


def test_audit_chain_verifies_and_is_append_only(client, make_tenant):
    t = make_tenant()
    client.post("/api/v1/organizations/companies", json={"name": "C1"}, headers=t["h"])
    v = client.get("/api/v1/audit/verify", headers=t["h"]).json()
    assert v["ok"] and v["count"] >= 2
    actions = [a["action"] for a in client.get("/api/v1/audit", headers=t["h"]).json()]
    assert "company.created" in actions and "tenant.registered" in actions
    # the app role cannot rewrite history ...
    for sql in ("update platform.audit_log set action='x'", "delete from platform.audit_log", "truncate platform.audit_log"):
        with pytest.raises(DBAPIError), tx(t["tenant_id"]) as c:
            c.execute(text(sql))


def test_audit_tamper_detected(client, make_tenant, superuser):
    t = make_tenant()
    client.post("/api/v1/organizations/companies", json={"name": "C1"}, headers=t["h"])
    superuser.execute("alter table platform.audit_log disable trigger audit_no_update_delete")
    try:
        superuser.execute("update platform.audit_log set data = '{\"slug\":\"forged\"}' where tenant_id=%s and seq=1", (t["tenant_id"],))
    finally:
        superuser.execute("alter table platform.audit_log enable trigger audit_no_update_delete")
    v = client.get("/api/v1/audit/verify", headers=t["h"]).json()
    assert v == {"ok": False, "count": v["count"], "first_bad_seq": 1}


def test_audit_chains_are_per_tenant_and_concurrency_safe(client, make_tenant):
    import concurrent.futures as cf

    t = make_tenant()
    with cf.ThreadPoolExecutor(8) as ex:
        rs = list(ex.map(lambda i: client.post("/api/v1/organizations/companies", json={"name": f"C{i}"}, headers=t["h"]), range(16)))
    assert all(r.status_code == 201 for r in rs)
    assert client.get("/api/v1/audit/verify", headers=t["h"]).json()["ok"]


def test_every_route_declares_an_access_policy(client):
    from ueos.api import app

    def marks(dep) -> set[str]:
        out = {getattr(dep.call, "__ueos_access__", None)} - {None}
        for d in dep.dependencies:
            out |= marks(d)
        return out

    missing = [r.path for r in app.routes if isinstance(r, APIRoute) and not marks(r.dependant)]
    assert not missing, f"routes without access policy: {missing}"


def test_migration_downgrade_and_upgrade_roundtrip(tmp_path):
    d = devdb.start(devdb.ROOT / ".data" / "pg-test", db="ueos_migcheck", reset=True)
    devdb.downgrade_base(d)
    with psycopg.connect(d.superuser_url, autocommit=True) as c:
        assert c.execute("select count(*) from pg_namespace where nspname='platform'").fetchone()[0] == 0
    import os

    from alembic import command
    from alembic.config import Config

    os.environ["UEOS_OWNER_DATABASE_URL"] = d.owner_url
    cfg = Config(str(devdb.ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(devdb.ROOT / "backend" / "migrations"))
    command.upgrade(cfg, "head")
    with psycopg.connect(d.superuser_url, autocommit=True) as c:
        assert c.execute("select count(*) from pg_namespace where nspname='platform'").fetchone()[0] == 1
