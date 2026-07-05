CREATE TABLE IF NOT EXISTS study_topic_inbox (
    id TEXT PRIMARY KEY,
    raw_text TEXT NOT NULL,
    title TEXT NOT NULL,
    section TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    agent_summary TEXT NOT NULL DEFAULT '',
    agent_provider TEXT NOT NULL DEFAULT '',
    agent_model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_study_topic_inbox_status_created
    ON study_topic_inbox(status, created_at);
