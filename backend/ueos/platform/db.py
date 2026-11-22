"""Database access. Every tenant-scoped transaction sets app.tenant_id (transaction-local) so RLS applies."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text

_engine: Engine | None = None


def init_engine(url: str) -> Engine:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        from ueos.platform.config import get_settings

        init_engine(get_settings().database_url)
    assert _engine is not None
    return _engine


@contextmanager
def tx(tenant_id: UUID | str | None) -> Iterator[Connection]:
    """One transaction. tenant_id=None means *no* tenant context (RLS tables return nothing)."""
    with get_engine().begin() as conn:
        conn.execute(
            text("select set_config('app.tenant_id', :t, true)"),
            {"t": str(tenant_id) if tenant_id else ""},
        )
        yield conn
