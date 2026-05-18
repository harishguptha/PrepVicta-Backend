import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        schema = os.environ.get("SUPABASE_SCHEMA", "public")
        _pool = await asyncpg.create_pool(
            host=os.environ["SUPABASE_HOST"],
            port=int(os.environ["SUPABASE_PORT"]),
            database=os.environ["SUPABASE_DB"],
            user=os.environ["SUPABASE_USER"],
            password=os.environ["SUPABASE_PASSWORD"],
            server_settings={"search_path": schema},
            statement_cache_size=0,  # required for Supabase PgBouncer (transaction mode)
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
