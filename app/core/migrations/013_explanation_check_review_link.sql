ALTER TABLE explanation_checks ADD COLUMN linked_review_task_id TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_explanation_checks_linked_task
    ON explanation_checks(linked_review_task_id);
