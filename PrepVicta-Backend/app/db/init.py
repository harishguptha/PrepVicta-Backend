import asyncpg

_DDL = """
CREATE TABLE IF NOT EXISTS prepvicta_data.revision_summary (
    id         BIGSERIAL PRIMARY KEY,
    chapter    TEXT NOT NULL,
    section    TEXT NOT NULL,
    subject    TEXT NOT NULL,
    summary    JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (chapter, section)
);

CREATE TABLE IF NOT EXISTS prepvicta_data.revision_quiz (
    id         BIGSERIAL PRIMARY KEY,
    user_id    TEXT NOT NULL,
    subject    TEXT NOT NULL,
    chapter    TEXT NOT NULL,
    section    TEXT NOT NULL,
    questions  JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, chapter, section)
);

CREATE TABLE IF NOT EXISTS prepvicta_data.revision_attempt (
    id           BIGSERIAL PRIMARY KEY,
    user_id      TEXT NOT NULL,
    chapter      TEXT NOT NULL,
    section      TEXT NOT NULL,
    score        INTEGER NOT NULL,
    total        INTEGER NOT NULL,
    answers      JSONB NOT NULL,
    attempted_at TIMESTAMPTZ DEFAULT now()
);
"""


async def init_db(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_DDL)
