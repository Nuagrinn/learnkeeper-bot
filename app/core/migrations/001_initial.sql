CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    tags_json TEXT NOT NULL DEFAULT '[]',
    source_paths_json TEXT NOT NULL DEFAULT '[]',
    last_seen_commit TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_tasks (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(id),
    created_at TEXT NOT NULL,
    due_at TEXT NOT NULL,
    stage INTEGER NOT NULL,
    status TEXT NOT NULL,
    interval_days INTEGER NOT NULL,
    last_result_percent REAL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_review_tasks_due
    ON review_tasks(status, due_at);

CREATE INDEX IF NOT EXISTS idx_review_tasks_topic
    ON review_tasks(topic_id, status);

