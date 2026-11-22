"""`python -m ueos.devserver` — start the embedded Postgres (data in <project>/.data/postgres), migrate, serve the API."""

import os

import uvicorn

from ueos import devdb


def _bootstrap_staff() -> None:
    """DEV ONLY: make sure one platform super admin exists; prints a random password on first creation."""
    import secrets

    from sqlalchemy import text

    from ueos.platform import staff
    from ueos.platform.db import tx

    with tx(None) as c:
        exists = c.execute(text("select 1 from platform.staff limit 1")).first()
    if not exists:
        pw = os.environ.get("UEOS_DEV_STAFF_PASSWORD") or secrets.token_urlsafe(12) + "-Aa1"
        staff.create_staff("admin@ueos-dev.example.com", pw, "super_admin", "Dev Admin")
        print(f"DEV STAFF CREATED: admin@ueos-dev.example.com / {pw}")


def main() -> None:
    d = devdb.start(devdb.ROOT / ".data" / "postgres", db="ueos")
    os.environ["UEOS_DATABASE_URL"] = d.app_url
    os.environ["UEOS_OWNER_DATABASE_URL"] = d.owner_url
    from ueos.platform import db

    db.init_engine(d.app_url)
    from ueos.platform import registry

    print("Registry sync:", registry.sync_manifests())
    _bootstrap_staff()
    print(f"Postgres ready (data: {devdb.ROOT / '.data' / 'postgres'})")
    print("API docs: http://127.0.0.1:8000/docs")
    uvicorn.run("ueos.api:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
