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
    result = await conn.execute(
        "UPDATE prepvicta_data.users SET name = 'Harish Guptha' WHERE email = 'harishguptha121@gmail.com'"
    )
    print("Result:", result)
    row = await conn.fetchrow(
        "SELECT email, name FROM prepvicta_data.users WHERE email = 'harishguptha121@gmail.com'"
    )
    print("Updated row -> email=%s | name=%s" % (row["email"], row["name"]))
    await conn.close()

asyncio.run(main())
