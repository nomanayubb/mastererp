import pyotp
from sqlalchemy import text

from ueos.platform.db import tx


def login(client, t, **kw):
    return client.post("/api/v1/auth/login", json={"tenant_slug": t["slug"], "email": t["email"],
                                                   "password": kw.pop("password", t["password"]), **kw})


def test_register_login_me(client, make_tenant):
    t = make_tenant()
    r = login(client, t)
    assert r.status_code == 200 and r.json()["role"] == "owner"
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/v1/tenants/current", headers=h).json()["slug"] == t["slug"]


def test_weak_password_and_duplicate_slug_rejected(client, make_tenant):
    t = make_tenant()
    base = {"tenant_name": "X Co", "slug": t["slug"], "email": "new@example.com", "password": "short"}
    assert client.post("/api/v1/auth/register", json=base).status_code == 422
    assert client.post("/api/v1/auth/register", json={**base, "password": "long-enough-password"}).status_code == 409


def test_wrong_password_generic_error_and_lockout(client, make_tenant):
    t = make_tenant()
    for _ in range(5):
        assert login(client, t, password="wrong-wrong-wrong").json()["detail"] == "invalid_credentials"
    assert login(client, t).json()["detail"] == "account_locked"  # even correct password is refused


def test_unknown_tenant_same_error_as_bad_password(client, make_tenant):
    t = make_tenant()
    a = client.post("/api/v1/auth/login", json={"tenant_slug": "nope-nope", "email": t["email"], "password": t["password"]})
    b = login(client, t, password="wrong-wrong-wrong")
    assert a.status_code == b.status_code == 401 and a.json()["detail"] == b.json()["detail"]


def test_user_of_tenant_a_cannot_login_to_tenant_b(client, make_tenant):
    a, b = make_tenant("a"), make_tenant("b")
    r = client.post("/api/v1/auth/login", json={"tenant_slug": b["slug"], "email": a["email"], "password": a["password"]})
    assert r.status_code == 401


def test_refresh_rotation_and_reuse_detection(client, make_tenant):
    t = make_tenant()
    r1 = t["tokens"]["refresh_token"]
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": r1}).json()
    assert r2["refresh_token"] != r1
    # replaying the old token revokes the whole session
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": r1}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": r2["refresh_token"]}).status_code == 401
    h = {"Authorization": f"Bearer {r2['access_token']}"}
    assert client.get("/api/v1/tenants/current", headers=h).status_code == 401


def test_logout_revokes_access_immediately(client, make_tenant):
    t = make_tenant()
    assert client.post("/api/v1/auth/logout", headers=t["h"]).status_code == 204
    assert client.get("/api/v1/tenants/current", headers=t["h"]).status_code == 401


def test_mfa_flow(client, make_tenant):
    t = make_tenant()
    secret = client.post("/api/v1/auth/mfa/enroll", headers=t["h"]).json()["secret"]
    assert client.post("/api/v1/auth/mfa/confirm", json={"code": "000000"}, headers=t["h"]).status_code == 422
    assert client.post("/api/v1/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=t["h"]).status_code == 204
    assert login(client, t).json()["detail"] == "mfa_required"
    assert login(client, t, mfa_code="000000").json()["detail"] == "invalid_mfa_code"
    assert login(client, t, mfa_code=pyotp.TOTP(secret).now()).status_code == 200


def test_invitation_flow_and_role_enforcement(client, make_tenant):
    t = make_tenant()
    inv = client.post("/api/v1/users/invitations", json={"email": "Bob@Example.com", "role": "member"}, headers=t["h"])
    assert inv.status_code == 201
    tok = client.post("/api/v1/auth/accept-invitation",
                      json={"token": inv.json()["token"], "password": "bobs-long-password", "display_name": "Bob"})
    assert tok.status_code == 200 and tok.json()["role"] == "member"
    bh = {"Authorization": f"Bearer {tok.json()['access_token']}"}
    assert client.get("/api/v1/users", headers=bh).status_code == 200  # members can read
    assert client.post("/api/v1/organizations/companies", json={"name": "Nope"}, headers=bh).status_code == 403
    assert client.post("/api/v1/users/invitations", json={"email": "c@example.com"}, headers=bh).status_code == 403
    # token is single-use
    again = client.post("/api/v1/auth/accept-invitation",
                        json={"token": inv.json()["token"], "password": "bobs-long-password"})
    assert again.status_code == 404


def test_disable_member_kills_sessions(client, make_tenant):
    t = make_tenant()
    inv = client.post("/api/v1/users/invitations", json={"email": "d@example.com"}, headers=t["h"]).json()
    tok = client.post("/api/v1/auth/accept-invitation", json={"token": inv["token"], "password": "dees-long-password"}).json()
    bh = {"Authorization": f"Bearer {tok['access_token']}"}
    mid = next(u["id"] for u in client.get("/api/v1/users", headers=t["h"]).json() if u["email"] == "d@example.com")
    assert client.post(f"/api/v1/users/{mid}/disable", headers=t["h"]).status_code == 204
    assert client.get("/api/v1/users", headers=bh).status_code == 401
    owner = next(u["id"] for u in client.get("/api/v1/users", headers=t["h"]).json() if u["role"] == "owner")
    assert client.post(f"/api/v1/users/{owner}/disable", headers=t["h"]).status_code == 422


def test_tokens_and_passwords_never_stored_in_clear(make_tenant):
    t = make_tenant()
    with tx(t["tenant_id"]) as c:
        row = c.execute(text("select u.password_hash, s.refresh_hash from platform.users u, platform.sessions s limit 1")).one()
    assert row[0].startswith("$argon2id$")
    assert t["tokens"]["refresh_token"].split(".")[2] not in row[1]


def test_unauthenticated_and_tampered_tokens_rejected(client, make_tenant):
    t = make_tenant()
    assert client.get("/api/v1/organizations/companies").status_code == 401
    bad = t["tokens"]["access_token"][:-3] + "abc"
    assert client.get("/api/v1/organizations/companies", headers={"Authorization": f"Bearer {bad}"}).status_code == 401
