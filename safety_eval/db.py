import json
from importlib.resources import files

import asyncpg


async def configure_connection(connection):
    await connection.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def open_pool(url):
    return await asyncpg.create_pool(
        url, min_size=1, max_size=5, init=configure_connection, command_timeout=30
    )


async def migrate(pool):
    sql = files("safety_eval").joinpath("data/001_initial.sql").read_text()
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute("SELECT pg_advisory_xact_lock(782913004)")
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations(version integer PRIMARY KEY)"
        )
        applied = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM schema_migrations WHERE version=1)"
        )
        if not applied:
            await connection.execute(sql)
