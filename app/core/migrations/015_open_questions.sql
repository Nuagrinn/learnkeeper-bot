CREATE TABLE IF NOT EXISTS open_questions (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL,
    topic_title TEXT NOT NULL,
    section TEXT NOT NULL DEFAULT '',
    quiz_session_id TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'instant',
    status TEXT NOT NULL DEFAULT 'active',
    question_kind TEXT NOT NULL DEFAULT 'mini_case',
    question_text TEXT NOT NULL,
    answer_format_hint TEXT NOT NULL DEFAULT '',
    expected_points_json TEXT NOT NULL DEFAULT '[]',
    rubric_json TEXT NOT NULL DEFAULT '[]',
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    material_fingerprint TEXT NOT NULL DEFAULT '',
    material_snapshot_json TEXT NOT NULL DEFAULT '{}',
    generator_provider TEXT NOT NULL DEFAULT '',
    generator_model TEXT NOT NULL DEFAULT '',
    generate_prompt_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    answered_at TEXT,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_open_questions_status_created
    ON open_questions(status, created_at);

CREATE INDEX IF NOT EXISTS idx_open_questions_topic_status
    ON open_questions(topic_id, status);

CREATE INDEX IF NOT EXISTS idx_open_questions_quiz_session
    ON open_questions(quiz_session_id);

CREATE TABLE IF NOT EXISTS open_question_attempts (
    id TEXT PRIMARY KEY,
    open_question_id TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    answer_source TEXT NOT NULL DEFAULT 'text',
    score_percent REAL NOT NULL DEFAULT 0,
    layer_reached INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    strong_points_json TEXT NOT NULL DEFAULT '[]',
    missing_points_json TEXT NOT NULL DEFAULT '[]',
    false_models_json TEXT NOT NULL DEFAULT '[]',
    better_answer TEXT NOT NULL DEFAULT '',
    next_drill TEXT NOT NULL DEFAULT '',
    should_create_mistake_work INTEGER NOT NULL DEFAULT 0,
    checker_provider TEXT NOT NULL DEFAULT '',
    checker_model TEXT NOT NULL DEFAULT '',
    check_prompt_version TEXT NOT NULL DEFAULT '',
    raw_report_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (open_question_id) REFERENCES open_questions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_open_question_attempts_question_created
    ON open_question_attempts(open_question_id, created_at);
