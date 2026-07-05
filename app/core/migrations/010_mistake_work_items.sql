CREATE TABLE IF NOT EXISTS mistake_work_items (
    id TEXT PRIMARY KEY,
    quiz_session_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    topic_title TEXT NOT NULL,
    session_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    priority TEXT NOT NULL DEFAULT 'normal',
    title TEXT NOT NULL,
    section TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    diagnosis TEXT NOT NULL DEFAULT '',
    weak_concepts_json TEXT NOT NULL DEFAULT '[]',
    questions_json TEXT NOT NULL DEFAULT '[]',
    suggestion_json TEXT NOT NULL DEFAULT '{}',
    report_json TEXT NOT NULL DEFAULT '{}',
    agent_provider TEXT NOT NULL DEFAULT '',
    agent_model TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    done_at TEXT,
    deleted_at TEXT,
    FOREIGN KEY (quiz_session_id) REFERENCES quiz_sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_mistake_work_items_status_created
    ON mistake_work_items(status, created_at);

CREATE INDEX IF NOT EXISTS idx_mistake_work_items_topic_status
    ON mistake_work_items(topic_id, status);
