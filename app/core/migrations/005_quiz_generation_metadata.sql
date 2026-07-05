ALTER TABLE quiz_sessions ADD COLUMN generator_provider TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE quiz_sessions ADD COLUMN generator_model TEXT NOT NULL DEFAULT '';
ALTER TABLE quiz_sessions ADD COLUMN prompt_version TEXT NOT NULL DEFAULT '';
ALTER TABLE quiz_sessions ADD COLUMN generated_at TEXT;
