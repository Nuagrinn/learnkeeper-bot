PRAGMA foreign_keys = OFF;

CREATE TABLE quiz_sessions_new (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES review_tasks(id),
    topic_id TEXT NOT NULL REFERENCES topics(id),
    topic_title TEXT NOT NULL DEFAULT '',
    session_type TEXT NOT NULL DEFAULT 'review',
    status TEXT NOT NULL,
    question_count INTEGER NOT NULL,
    current_question_no INTEGER NOT NULL DEFAULT 1,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    material_fingerprint TEXT NOT NULL DEFAULT '',
    material_snapshot_json TEXT NOT NULL DEFAULT '{}',
    generator_provider TEXT NOT NULL DEFAULT 'unknown',
    generator_model TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    generated_at TEXT,
    score_percent REAL,
    correct_count INTEGER,
    total_count INTEGER
);

INSERT INTO quiz_sessions_new (
    id,
    task_id,
    topic_id,
    topic_title,
    session_type,
    status,
    question_count,
    current_question_no,
    started_at,
    finished_at,
    material_fingerprint,
    material_snapshot_json,
    generator_provider,
    generator_model,
    prompt_version,
    generated_at,
    score_percent,
    correct_count,
    total_count
)
SELECT
    qs.id,
    qs.task_id,
    qs.topic_id,
    COALESCE(t.title, qs.topic_id),
    'review',
    qs.status,
    qs.question_count,
    qs.current_question_no,
    qs.started_at,
    qs.finished_at,
    qs.material_fingerprint,
    qs.material_snapshot_json,
    qs.generator_provider,
    qs.generator_model,
    qs.prompt_version,
    qs.generated_at,
    qs.score_percent,
    qs.correct_count,
    qs.total_count
FROM quiz_sessions qs
LEFT JOIN topics t ON t.id = qs.topic_id;

DROP TABLE quiz_sessions;
ALTER TABLE quiz_sessions_new RENAME TO quiz_sessions;

CREATE INDEX IF NOT EXISTS idx_quiz_sessions_task
    ON quiz_sessions(task_id, status);

CREATE INDEX IF NOT EXISTS idx_quiz_sessions_type_topic
    ON quiz_sessions(session_type, topic_id, started_at);

PRAGMA foreign_keys = ON;
