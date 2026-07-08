CREATE TABLE IF NOT EXISTS explanation_checks (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL,
    topic_title TEXT NOT NULL,
    section TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'text',
    explanation_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    priority TEXT NOT NULL DEFAULT 'normal',
    layer_reached INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    covered_concepts_json TEXT NOT NULL DEFAULT '[]',
    missing_concepts_json TEXT NOT NULL DEFAULT '[]',
    false_models_json TEXT NOT NULL DEFAULT '[]',
    follow_up_question TEXT NOT NULL DEFAULT '',
    material_fingerprint TEXT NOT NULL DEFAULT '',
    agent_provider TEXT NOT NULL DEFAULT '',
    agent_model TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    done_at TEXT,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_explanation_checks_status_created
    ON explanation_checks(status, created_at);

CREATE INDEX IF NOT EXISTS idx_explanation_checks_topic_status
    ON explanation_checks(topic_id, status);
