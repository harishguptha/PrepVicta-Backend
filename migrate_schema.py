"""Run once: adds missing columns and populates pyq_qs/weight_pct in task_topic."""
import asyncio
import os
import sys

sys.path.insert(0, ".")
from dotenv import load_dotenv
import asyncpg
from app.data.neet_syllabus import SYLLABUS_CHAPTERS

load_dotenv()

# Chapters whose names differ between neet_syllabus.py and task_topic
CHAPTER_NAME_FIXES = {
    "Biotechnology - Principles & Processes": "Biotechnology – Principles & Processes",
    "Cell - Structure & Functions": "Cell – Structure & Functions",
    "Organic Chemistry - Basic Principles": "Organic Chemistry – Basic Principles",
    "Thermodynamics (Chemistry)": "Thermodynamics",
    "Biomolecules": None,  # handled per-subject below
}

CHEMISTRY_BIOMOLECULES_DB_NAME = "Biomolecules (Chemistry)"


async def main() -> None:
    pool = await asyncpg.create_pool(
        host=os.environ["SUPABASE_HOST"],
        port=int(os.environ["SUPABASE_PORT"]),
        database=os.environ["SUPABASE_DB"],
        user=os.environ["SUPABASE_USER"],
        password=os.environ["SUPABASE_PASSWORD"],
        server_settings={"search_path": os.environ["SUPABASE_SCHEMA"]},
        statement_cache_size=0,
    )

    print("Adding columns to task_topic …")
    await pool.execute("ALTER TABLE task_topic ADD COLUMN IF NOT EXISTS pyq_qs integer")
    await pool.execute("ALTER TABLE task_topic ADD COLUMN IF NOT EXISTS weight_pct integer")

    print("Adding columns to student_planner_tasks …")
    await pool.execute("ALTER TABLE student_planner_tasks ADD COLUMN IF NOT EXISTS chapter text")
    await pool.execute("ALTER TABLE student_planner_tasks ADD COLUMN IF NOT EXISTS topic text")
    await pool.execute("ALTER TABLE student_planner_tasks ADD COLUMN IF NOT EXISTS activity text")

    print("Populating pyq_qs / weight_pct in task_topic …")
    for ch in SYLLABUS_CHAPTERS:
        raw_name = ch["chapter"]

        if ch["subject"] == "Chemistry" and raw_name == "Biomolecules":
            db_name = CHEMISTRY_BIOMOLECULES_DB_NAME
        elif raw_name in CHAPTER_NAME_FIXES and CHAPTER_NAME_FIXES[raw_name] is not None:
            db_name = CHAPTER_NAME_FIXES[raw_name]
        else:
            db_name = raw_name

        if ch["subject"] == "Biology":
            result = await pool.execute(
                "UPDATE task_topic SET pyq_qs=$1, weight_pct=$2 WHERE chapter=$3 AND subject IN ('Botany','Zoology')",
                ch["pyq_qs"], ch["weight_pct"], db_name,
            )
        else:
            result = await pool.execute(
                "UPDATE task_topic SET pyq_qs=$1, weight_pct=$2 WHERE chapter=$3 AND subject=$4",
                ch["pyq_qs"], ch["weight_pct"], db_name, ch["subject"],
            )
        print(f"  {ch['subject']} / {db_name}: {result}")

    remaining = await pool.fetchval("SELECT COUNT(*) FROM task_topic WHERE pyq_qs IS NULL")
    if remaining:
        print(f"  {remaining} rows still NULL — filling with defaults (pyq_qs=2, weight_pct=4)")
        await pool.execute("UPDATE task_topic SET pyq_qs=2 WHERE pyq_qs IS NULL")
        await pool.execute("UPDATE task_topic SET weight_pct=4 WHERE weight_pct IS NULL")

    print("Migration complete.")
    await pool.close()


asyncio.run(main())
