"""Run Alembic migrations programmatically (used on app startup and by tests)."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def alembic_config(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


async def upgrade_head(engine: AsyncEngine) -> None:
    def _run(sync_conn):
        cfg = alembic_config()
        cfg.attributes["connection"] = sync_conn
        command.upgrade(cfg, "head")

    async with engine.begin() as conn:
        await conn.run_sync(_run)
