import asyncpg

from app.config import get_settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            min_size=settings.db_min_pool_size,
            max_size=settings.db_max_pool_size,
            command_timeout=settings.db_command_timeout_seconds,
            server_settings={"search_path": settings.db_schema},
            statement_cache_size=0,  # required for Supabase PgBouncer (transaction mode)
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
