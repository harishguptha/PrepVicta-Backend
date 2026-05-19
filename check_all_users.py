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
    rows = await conn.fetch(
        "SELECT email, name FROM prepvicta_data.users ORDER BY created_at ASC"
    )
    print("%-40s | %s" % ("email", "name"))
    print("-" * 60)
    for r in rows:
        print("%-40s | %s" % (r["email"], r["name"] or "NULL"))
    await conn.close()

asyncio.run(main())
