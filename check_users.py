import asyncio, asyncpg, ssl
from app.config import get_settings

async def main():
    s = get_settings()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = await asyncpg.connect(
        host=s.db_host, port=s.db_port, database=s.db_name,
        user=s.db_user, password=s.db_password, ssl=ctx
    )

    # Find which schema users table is in
    schemas = await conn.fetch(
        "SELECT table_schema, table_name FROM information_schema.tables WHERE table_name = 'users'"
    )
    print("=== users table location ===")
    for r in schemas:
        print("  schema=%s table=%s" % (r["table_schema"], r["table_name"]))

    # Query users
    rows = await conn.fetch(
        "SELECT id, email, name, role, created_at FROM prepvicta_data.users ORDER BY created_at DESC LIMIT 10"
    )
    print("\n=== users (prepvicta_data.users) ===")
    for r in rows:
        print("  email=%s | name=%s | role=%s" % (r["email"], r["name"], r["role"]))

    await conn.close()

asyncio.run(main())
