# test_tables.py (run once to explore)
import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv()

async def main():
    pool = await asyncpg.create_pool(
        host=os.environ["SUPABASE_HOST"],
        port=int(os.environ["SUPABASE_PORT"]),
        database=os.environ["SUPABASE_DB"],
        user=os.environ["SUPABASE_USER"],
        password=os.environ["SUPABASE_PASSWORD"],
        server_settings={"search_path": os.environ["SUPABASE_SCHEMA"]},
        statement_cache_size=0,
    )
    
    schema = os.environ["SUPABASE_SCHEMA"]

    tables = await pool.fetch("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = $1
    """, schema)

    for t in tables:
        table_name = t["table_name"]
        columns = await pool.fetch("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position
        """, schema, table_name)

        print(f"\n[{table_name}]")
        for col in columns:
            nullable = "NULL" if col["is_nullable"] == "YES" else "NOT NULL"
            print(f"  {col['column_name']} ({col['data_type']}, {nullable})")
    
    await pool.close()

asyncio.run(main())
