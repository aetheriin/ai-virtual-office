"""Alembic environment. Uses the connection handed over by app.projects.migrate when present,
otherwise connects with DATABASE_URL (CLI: `alembic upgrade head` from backend/)."""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.projects.models import Base
from app.projects.store import normalize_url

config = context.config
if config.config_file_name and config.attributes.get("connection") is None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",  # ALTER TABLE support on SQLite
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _url() -> str:
    from app.config import settings
    return normalize_url(config.get_main_option("sqlalchemy.url") or settings.database_url)


async def _run_async() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as conn:
        await conn.run_sync(_configure)
        await conn.commit()
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
elif (conn := config.attributes.get("connection")) is not None:
    _configure(conn)
else:
    asyncio.run(_run_async())
