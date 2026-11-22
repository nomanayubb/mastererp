import os
import uuid

import psycopg
import pyotp  # noqa: F401
import pytest
from fastapi.testclient import TestClient

from ueos import devdb
from ueos.platform import db as dbmod
from ueos.platform.config import get_settings

os.environ.setdefault("UEOS_ENV", "dev")


@pytest.fixture(scope="session")
def pg():
    d = devdb.start(devdb.ROOT / ".data" / "pg-test", db="ueos_test", reset=True)
    os.environ["UEOS_DATABASE_URL"] = d.app_url
    get_settings.cache_clear()
    dbmod.init_engine(d.app_url)
    from ueos.platform import registry

    registry.sync_manifests()
    yield d


@pytest.fixture()
def client(pg):
    from ueos.api import create_app

    return TestClient(create_app())


def _uniq() -> str:
    return uuid.uuid4().hex[:10]


@pytest.fixture()
def make_tenant(client):
    """Register a fresh tenant; returns dict with slug, email, password, headers."""

    def _mk(prefix: str = "acme") -> dict:
        u = _uniq()
        body = {"tenant_name": f"{prefix} {u}", "slug": f"{prefix}-{u}", "email": f"owner-{u}@example.com",
                "password": "correct-horse-battery", "display_name": "Owner"}
        r = client.post("/api/v1/auth/register", json=body)
        assert r.status_code == 201, r.text
        t = r.json()
        return {**body, "tenant_id": t["tenant_id"], "tokens": t,
                "h": {"Authorization": f"Bearer {t['access_token']}"}}

    return _mk


@pytest.fixture()
def superuser(pg):
    with psycopg.connect(pg.superuser_url, autocommit=True) as c:
        yield c


@pytest.fixture()
def make_staff(client):
    from ueos.platform import staff

    def _mk(role: str = "super_admin") -> dict:
        u = _uniq()
        email, pw = f"staff-{u}@example.com", "staff-password-123"
        staff.create_staff(email, pw, role)
        r = client.post("/api/v1/platform/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 200, r.text
        return {"email": email, "password": pw, "h": {"Authorization": f"Bearer {r.json()['access_token']}"}}

    return _mk


@pytest.fixture()
def admin(client, make_staff):
    return make_staff("super_admin")["h"]


@pytest.fixture()
def invite_user(client):
    """Invite + accept a user into a tenant with a base role; returns dict(h, membership_id, email)."""

    def _inv(owner: dict, role: str = "member") -> dict:
        u = _uniq()
        email = f"user-{u}@example.com"
        t = client.post("/api/v1/users/invitations", json={"email": email, "role": role}, headers=owner["h"]).json()
        tok = client.post("/api/v1/auth/accept-invitation", json={"token": t["token"], "password": "user-password-123"}).json()
        h = {"Authorization": f"Bearer {tok['access_token']}"}
        mid = next(x["id"] for x in client.get("/api/v1/users", headers=owner["h"]).json() if x["email"] == email)
        return {"h": h, "membership_id": mid, "email": email}

    return _inv
