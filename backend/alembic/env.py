from __future__ import annotations

import asyncio
import os
from typing import Any

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.models import Base

target_metadata = Base.metadata


def _url() -> str:
    return os.environ.get(
        "FOXGRID_DATABASE_URL",
        "postgresql+asyncpg://foxgrid:foxgrid@localhost:5432/foxgrid",
    )


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    # Tables owned by PostGIS extensions (spatial_ref_sys, tiger, ...) are not ours.
    if type_ == "table" and reflected and name not in target_metadata.tables:
        return False
    # Generated `geom` columns and their GiST indexes live in SQL only (see migration 0001).
    sql_only = (type_ == "column" and name == "geom") or (
        type_ == "index" and (name or "").endswith("_geom")
    )
    return not (reflected and compare_to is None and sql_only)


def _do_run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
