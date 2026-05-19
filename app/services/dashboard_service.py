import asyncpg
from datetime import date, timedelta


async def get_dashboard(user_id: str, pool: asyncpg.Pool) -> dict:
    subject_rows = await pool.fetch(
        """
        SELECT
            CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END AS subject,
            COUNT(DISTINCT topic) AS total,
            COUNT(DISTINCT topic) FILTER (WHERE is_done = true) AS done
        FROM prepvicta_data.student_planner_tasks
        WHERE user_id = $1
        GROUP BY CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END
        ORDER BY subject
        """,
        user_id,
    )

    subject_progress = []
    overall_total = overall_done = 0
    for r in subject_rows:
        total, done = r["total"], r["done"]
        overall_total += total
        overall_done += done
        subject_progress.append({
            "subject": r["subject"],
            "total": total,
            "completed": done,
            "percentage": round(done / total * 100) if total else 0,
        })

    today = date.today()
    today_rows = await pool.fetch(
        """
        SELECT DISTINCT ON (chapter, topic)
            chapter, topic AS section, subject, priority,
            duration_min AS estimated_minutes, activity, is_done AS completed
        FROM prepvicta_data.student_planner_tasks
        WHERE user_id = $1 AND plan_date = $2
        ORDER BY chapter, topic,
                 CASE WHEN priority LIKE '%MUST%' THEN 1 WHEN priority LIKE '%HIGH%' THEN 2 ELSE 3 END
        """,
        user_id, today,
    )
    today_tasks = [
        {
            "chapter": r["chapter"], "section": r["section"],
            "subject": r["subject"], "priority": r["priority"],
            "estimated_minutes": r["estimated_minutes"],
            "activity": r["activity"], "completed": r["completed"],
        }
        for r in today_rows
    ]

    streak_rows = await pool.fetch(
        """
        SELECT DISTINCT DATE(completed_at) AS day
        FROM prepvicta_data.student_planner_tasks
        WHERE user_id = $1 AND is_done = true AND completed_at IS NOT NULL
        ORDER BY day DESC LIMIT 30
        """,
        user_id,
    )
    streak = 0
    check = today
    for r in streak_rows:
        if r["day"] == check:
            streak += 1
            check = check - timedelta(days=1)
        else:
            break

    recent_rows = await pool.fetch(
        """
        SELECT DISTINCT ON (chapter, topic) chapter, topic AS section, subject, completed_at
        FROM prepvicta_data.student_planner_tasks
        WHERE user_id = $1 AND is_done = true AND completed_at IS NOT NULL
        ORDER BY chapter, topic, completed_at DESC
        LIMIT 5
        """,
        user_id,
    )
    recent = [
        {
            "chapter": r["chapter"], "section": r["section"],
            "subject": r["subject"], "completed_at": r["completed_at"].isoformat(),
        }
        for r in recent_rows
    ]

    return {
        "subject_progress": subject_progress,
        "overall": {
            "total": overall_total, "completed": overall_done,
            "percentage": round(overall_done / overall_total * 100) if overall_total else 0,
        },
        "today_tasks": today_tasks,
        "streak_days": streak,
        "recent_completions": recent,
    }
