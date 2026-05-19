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

    print("task_topic topics for 'Animal Kingdom':")
    rows = await conn.fetch("""
        SELECT topic FROM prepvicta_data.task_topic WHERE chapter = 'Animal Kingdom' LIMIT 10
    """)
    for r in rows:
        print("  topic=%r" % r["topic"])

    print("\ntopic_progress sections for 'Animal Kingdom':")
    rows2 = await conn.fetch("""
        SELECT section FROM prepvicta_data.topic_progress WHERE chapter = 'Animal Kingdom' LIMIT 10
    """)
    for r in rows2:
        print("  section=%r" % r["section"])

    await conn.close()

asyncio.run(main())
