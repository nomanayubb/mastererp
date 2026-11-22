import os

from alembic import context
from sqlalchemy import create_engine

url = os.environ.get("UEOS_OWNER_DATABASE_URL") or context.config.get_main_option("sqlalchemy.url")
if not url:
    raise RuntimeError("Set UEOS_OWNER_DATABASE_URL")

if context.is_offline_mode():
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, version_table_schema="public")
        with context.begin_transaction():
            context.run_migrations()
