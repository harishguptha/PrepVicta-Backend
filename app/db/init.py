import asyncpg

_CREATE_TOPIC_PROGRESS = """
CREATE TABLE IF NOT EXISTS prepvicta_data.topic_progress (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID         NOT NULL,
    chapter     TEXT         NOT NULL,
    section     TEXT         NOT NULL,
    subject     TEXT         NOT NULL DEFAULT 'Biology',
    viewed_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, chapter, section)
);
"""

_CREATE_REVISION_SUMMARY = """
CREATE TABLE IF NOT EXISTS prepvicta_data.revision_summary (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter     TEXT         NOT NULL,
    section     TEXT         NOT NULL,
    subject     TEXT         NOT NULL DEFAULT 'Biology',
    summary     JSONB        NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (chapter, section)
);
"""

_CREATE_REVISION_QUIZ = """
CREATE TABLE IF NOT EXISTS prepvicta_data.revision_quiz (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    subject     TEXT         NOT NULL DEFAULT 'Biology',
    chapter     TEXT         NOT NULL,
    section     TEXT         NOT NULL,
    questions   JSONB        NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (chapter, section)
);
"""

_CREATE_REVISION_ATTEMPT = """
CREATE TABLE IF NOT EXISTS prepvicta_data.revision_attempt (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID         NOT NULL,
    chapter      TEXT         NOT NULL,
    section      TEXT         NOT NULL,
    score        INTEGER      NOT NULL DEFAULT 0,
    total        INTEGER      NOT NULL DEFAULT 0,
    answers      JSONB        NOT NULL DEFAULT '[]',
    attempted_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
"""

_CREATE_PERFORMANCE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_topic_progress_user_subject
    ON prepvicta_data.topic_progress (user_id, subject);

CREATE INDEX IF NOT EXISTS idx_revision_attempt_user_chapter_section_attempted
    ON prepvicta_data.revision_attempt (user_id, chapter, section, attempted_at DESC);

CREATE INDEX IF NOT EXISTS idx_revision_quiz_chapter_section
    ON prepvicta_data.revision_quiz (chapter, section);

CREATE INDEX IF NOT EXISTS idx_revision_summary_chapter_section
    ON prepvicta_data.revision_summary (chapter, section);
"""


_CREATE_TOPIC_MINDMAP = """
CREATE TABLE IF NOT EXISTS prepvicta_data.topic_mindmap (
    id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter    TEXT         NOT NULL,
    section    TEXT         NOT NULL,
    subject    TEXT         NOT NULL DEFAULT 'Biology',
    mindmap    JSONB        NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (chapter, section)
);
"""


_CREATE_TOPIC_INFOGRAPHIC = """
CREATE TABLE IF NOT EXISTS prepvicta_data.topic_infographic (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter      TEXT         NOT NULL,
    section      TEXT         NOT NULL,
    subject      TEXT         NOT NULL DEFAULT 'Biology',
    infographic  JSONB        NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (chapter, section)
);
"""


async def init_db(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_CREATE_REVISION_SUMMARY)
        await conn.execute(_CREATE_REVISION_QUIZ)
        await conn.execute(_CREATE_REVISION_ATTEMPT)
        await conn.execute(_CREATE_TOPIC_PROGRESS)
        await conn.execute(_CREATE_TOPIC_MINDMAP)
        await conn.execute(_CREATE_TOPIC_INFOGRAPHIC)
        await conn.execute(_CREATE_PERFORMANCE_INDEXES)
