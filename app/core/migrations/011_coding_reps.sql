CREATE TABLE IF NOT EXISTS coding_rep_log (
    id TEXT PRIMARY KEY,
    rep_id TEXT NOT NULL,
    rep_title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'sent',
    sent_at TEXT NOT NULL,
    responded_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_coding_rep_log_status_sent
    ON coding_rep_log(status, sent_at);

CREATE INDEX IF NOT EXISTS idx_coding_rep_log_rep_sent
    ON coding_rep_log(rep_id, sent_at);

INSERT OR IGNORE INTO app_settings (key, value, updated_at)
VALUES
    ('coding_reps_enabled', 'false', CURRENT_TIMESTAMP),
    ('coding_reps_last_sent_date', '', CURRENT_TIMESTAMP);
