"""Tenant-isolation harness: structural (every tenant table has RLS) + behavioural (cross-tenant reads/writes fail)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ueos.platform.db import tx

GLOBAL_TABLES = {"users", "staff", "platform_audit_log", "capability_domains", "business_models", "industries",
                 "applications", "modules", "submodules", "features", "plans", "plan_items", "industry_templates", "products", "product_versions"}


def test_every_tenant_table_has_forced_rls_policy(superuser):
    rows = superuser.execute(
        """select c.relname, c.relrowsecurity,
                  exists(select 1 from pg_policy p where p.polrelid = c.oid) as has_policy,
                  exists(select 1 from pg_attribute a where a.attrelid=c.oid and a.attname='tenant_id') as has_tid
           from pg_class c join pg_namespace n on n.oid=c.relnamespace
           where n.nspname='platform' and c.relkind='r'"""
    ).fetchall()
    assert rows
    for name, rls, has_policy, has_tid in rows:
        if has_tid or name == "tenants":
            assert rls and has_policy, f"{name} lacks RLS"
        else:
            assert name in GLOBAL_TABLES, f"{name}: global table must be explicitly reviewed"


def test_app_role_cannot_bypass_rls(superuser):
    r = superuser.execute("select rolsuper, rolbypassrls from pg_roles where rolname='ueos_app'").fetchone()
    assert r == (False, False)
    owners = superuser.execute("select tableowner from pg_tables where schemaname='platform'").fetchall()
    assert all(o[0] != "ueos_app" for o in owners)


def test_no_context_sees_nothing(make_tenant):
    make_tenant()
    with tx(None) as c:
        for t in ("memberships", "companies", "audit_log", "sessions", "tenants"):
            assert c.execute(text(f"select count(*) from platform.{t}")).scalar() == 0, t


def test_cross_tenant_reads_and_writes_blocked(client, make_tenant):
    a, b = make_tenant("a"), make_tenant("b")
    ca = client.post("/api/v1/organizations/companies", json={"name": "A Corp"}, headers=a["h"])
    assert ca.status_code == 201
    # B cannot see A's company
    assert client.get("/api/v1/organizations/companies", headers=b["h"]).json() == []
    # Direct DB: under B's context, A's rows are invisible and inserting A's tenant_id is rejected
    with tx(b["tenant_id"]) as c:
        assert c.execute(text("select count(*) from platform.companies")).scalar() == 0
    with pytest.raises(DBAPIError), tx(b["tenant_id"]) as c:
        c.execute(text("insert into platform.companies (id, tenant_id, name) values (:i,:t,'x')"),
                  {"i": uuid.uuid4(), "t": a["tenant_id"]})
    # B cannot create a branch under A's company (composite FK includes tenant_id)
    r = client.post("/api/v1/organizations/branches", json={"company_id": ca.json()["id"], "name": "Hack"}, headers=b["h"])
    assert r.status_code == 422
    # B cannot update/delete A's rows through the DB either
    with tx(b["tenant_id"]) as c:
        assert c.execute(text("update platform.companies set name='pwn'")).rowcount == 0
        assert c.execute(text("delete from platform.companies")).rowcount == 0


def test_tenant_context_does_not_leak_across_pooled_connections(make_tenant):
    a, b = make_tenant("a"), make_tenant("b")
    for _ in range(20):
        with tx(a["tenant_id"]) as c:
            assert c.execute(text("select count(*) from platform.tenants")).scalar() == 1
        with tx(None) as c:
            assert c.execute(text("select count(*) from platform.tenants")).scalar() == 0
        with tx(b["tenant_id"]) as c:
            assert str(c.execute(text("select id from platform.tenants")).scalar()) == b["tenant_id"]
