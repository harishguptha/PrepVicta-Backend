import asyncio
import json
import os
import uuid

import asyncpg
from dotenv import load_dotenv

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

    await pool.execute("""
        ALTER TABLE task_topic ADD COLUMN IF NOT EXISTS class text;
    """)
    print("Column 'class' ready.")

    with open("neet_topics.json", encoding="utf-8") as f:
        topics = json.load(f)

    await pool.executemany(
        """
        INSERT INTO task_topic (id, subject, chapter, topic, priority, class)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        [
            (
                str(uuid.uuid4()),
                t["subject"],
                t["chapter"],
                t["topic"],
                t["priority"],
                t["class"],
            )
            for t in topics
        ],
    )

    print(f"Successfully inserted {len(topics)} topics into task_topic.")
    await pool.close()


asyncio.run(main())
