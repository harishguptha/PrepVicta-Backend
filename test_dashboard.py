import asyncio, asyncpg, ssl
from app.config import get_settings
from app.services.dashboard_service import get_dashboard

async def main():
    s = get_settings()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    pool = await asyncpg.create_pool(
        host=s.db_host, port=s.db_port, database=s.db_name,
        user=s.db_user, password=s.db_password, ssl=ctx,
        statement_cache_size=0, min_size=1, max_size=2
    )

    # Check task_topic has data
    count = await pool.fetchval("SELECT COUNT(*) FROM prepvicta_data.task_topic")
    print("task_topic row count:", count)

    # Check subject breakdown
    rows = await pool.fetch("""
        SELECT CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END AS subject,
               COUNT(*) AS total
        FROM prepvicta_data.task_topic
        GROUP BY 1 ORDER BY 1
    """)
    print("Subject totals from task_topic:")
    for r in rows:
        print("  %s: %d" % (r["subject"], r["total"]))

    # Test get_dashboard with harishguptha user
    user_id = None
    row = await pool.fetchrow("SELECT id FROM prepvicta_data.users WHERE email = 'harishguptha121@gmail.com'")
    if row:
        user_id = str(row["id"])
        print("\nTesting dashboard for user:", user_id)
        try:
            data = await get_dashboard(user_id, pool)
            print("subject_progress:", data["subject_progress"])
            print("overall:", data["overall"])
        except Exception as e:
            print("ERROR in get_dashboard:", e)
    else:
        print("User not found")

    await pool.close()

asyncio.run(main())
