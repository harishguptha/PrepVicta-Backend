"""Run once: creates the topic_llm_cache table for caching LLM-enriched topic content."""
import asyncio
import os
import sys

sys.path.insert(0, ".")
from dotenv import load_dotenv
import asyncpg

load_dotenv()


async def main() -> None:
    pool = await asyncpg.create_pool(
        host=os.environ["SUPABASE_HOST"],
        port=int(os.environ["SUPABASE_PORT"]),
        database=os.environ["SUPABASE_DB"],
        user=os.environ["SUPABASE_USER"],
        password=os.environ["SUPABASE_PASSWORD"],
        server_settings={"search_path": os.environ.get("SUPABASE_SCHEMA", "public")},
        statement_cache_size=0,
    )

    print("Creating topic_llm_cache table …")
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS topic_llm_cache (
            chapter     TEXT NOT NULL,
            section     TEXT NOT NULL,
            llm_context TEXT NOT NULL,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (chapter, section)
        )
    """)
    print("Done. topic_llm_cache table is ready.")
    await pool.close()


asyncio.run(main())
