CREATE TABLE IF NOT EXISTS quiz_sessions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES review_tasks(id),
    topic_id TEXT NOT NULL REFERENCES topics(id),
    status TEXT NOT NULL,
    question_count INTEGER NOT NULL,
    current_question_no INTEGER NOT NULL DEFAULT 1,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    material_fingerprint TEXT NOT NULL DEFAULT '',
    material_snapshot_json TEXT NOT NULL DEFAULT '{}',
    score_percent REAL,
    correct_count INTEGER,
    total_count INTEGER
);

CREATE INDEX IF NOT EXISTS idx_quiz_sessions_task
    ON quiz_sessions(task_id, status);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    question_no INTEGER NOT NULL,
    text TEXT NOT NULL,
    options_json TEXT NOT NULL,
    correct_index INTEGER NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(session_id, question_no)
);

CREATE INDEX IF NOT EXISTS idx_questions_session
    ON questions(session_id, question_no);

CREATE TABLE IF NOT EXISTS answers (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id),
    selected_index INTEGER NOT NULL,
    is_correct INTEGER NOT NULL,
    answered_at TEXT NOT NULL,
    UNIQUE(session_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_answers_session
    ON answers(session_id, answered_at);
