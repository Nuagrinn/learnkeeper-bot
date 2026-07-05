CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO app_settings (key, value, updated_at)
VALUES
    ('daily_quiz_enabled', 'false', CURRENT_TIMESTAMP),
    ('daily_quiz_last_sent_date', '', CURRENT_TIMESTAMP);
