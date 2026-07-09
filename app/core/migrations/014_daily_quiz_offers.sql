CREATE TABLE IF NOT EXISTS daily_quiz_offers (
    id TEXT PRIMARY KEY,
    offer_date TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    topic_title TEXT NOT NULL,
    section TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_daily_quiz_offers_status_created
    ON daily_quiz_offers(status, created_at);

CREATE INDEX IF NOT EXISTS idx_daily_quiz_offers_date
    ON daily_quiz_offers(offer_date);
