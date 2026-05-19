import asyncio, asyncpg, ssl
from app.config import get_settings

async def main():
    s = get_settings()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = await asyncpg.connect(
        host=s.db_host, port=s.db_port, database=s.db_name,
        user=s.db_user, password=s.db_password, ssl=ctx,
        statement_cache_size=0
    )
    rows = await conn.fetch("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
          AND table_type = 'BASE TABLE'
        ORDER BY table_schema, table_name
    """)
    print("All tables:")
    for r in rows:
        print("  %s.%s" % (r["table_schema"], r["table_name"]))
    await conn.close()

asyncio.run(main())
