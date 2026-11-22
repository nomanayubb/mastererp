"""Dev/test database bootstrap: embedded PostgreSQL stored inside the project folder (never on C:).

Creates the database, an owner role (migrations) and a non-owner, non-superuser app role (subject to RLS),
then applies Alembic migrations.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]
PW = "dev-only-pw"  # local embedded server only


@dataclass
class DevDb:
    server: object
    superuser_url: str
    owner_url: str
    app_url: str


def _sqla(user: str, host: str, port: int, db: str) -> str:
    return f"postgresql+psycopg://{user}:{PW}@{host}:{port}/{db}"


def start(pgdata: Path, db: str = "ueos", reset: bool = False, migrate: bool = True) -> DevDb:
    import pgserver

    pgdata.mkdir(parents=True, exist_ok=True)
    srv = pgserver.get_server(pgdata, cleanup_mode="stop")
    u = urlparse(srv.get_uri())
    host, port = u.hostname or "127.0.0.1", u.port or 5432
    su = f"postgresql://postgres:@{host}:{port}/postgres"
    with psycopg.connect(su, autocommit=True) as c:
        for role, extra in (("ueos_owner", "createdb"), ("ueos_app", "nobypassrls")):
            if not c.execute("select 1 from pg_roles where rolname=%s", (role,)).fetchone():
                c.execute(f"create role {role} login password '{PW}' nosuperuser {extra}")
        if reset:
            c.execute("select pg_terminate_backend(pid) from pg_stat_activity where datname=%s", (db,))
            c.execute(f"drop database if exists {db}")
        if not c.execute("select 1 from pg_database where datname=%s", (db,)).fetchone():
            c.execute(f"create database {db} owner ueos_owner")
    d = DevDb(srv, f"postgresql://postgres:@{host}:{port}/{db}",_sqla("ueos_owner", host, port, db), _sqla("ueos_app", host, port, db))
    if migrate:
        os.environ["UEOS_OWNER_DATABASE_URL"] = d.owner_url
        cfg = Config(str(ROOT / "backend" / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
        command.upgrade(cfg, "head")
    return d


def downgrade_base(d: DevDb) -> None:
    os.environ["UEOS_OWNER_DATABASE_URL"] = d.owner_url
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    command.downgrade(cfg, "base")
