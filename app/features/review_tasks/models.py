from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Row


@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    status: str
    section: str
    order_index: int | None
    material_fingerprint: str
    tags: list[str]
    source_paths: list[str]
    last_seen_commit: str | None = None


@dataclass(frozen=True)
class ReviewTask:
    id: str
    topic_id: str
    topic_title: str
    created_at: datetime
    due_at: datetime
    stage: int
    status: str
    interval_days: int
    last_result_percent: float | None = None
    completed_at: datetime | None = None
    last_notified_at: datetime | None = None


@dataclass(frozen=True)
class CreateReviewTaskResult:
    task: ReviewTask
    topic: Topic
    created: bool


def topic_from_row(row: Row) -> Topic:
    return Topic(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        section=row["section"],
        order_index=row["order_index"],
        material_fingerprint=row["material_fingerprint"],
        tags=json.loads(row["tags_json"] or "[]"),
        source_paths=json.loads(row["source_paths_json"] or "[]"),
        last_seen_commit=row["last_seen_commit"],
    )


def review_task_from_row(row: Row) -> ReviewTask:
    completed = row["completed_at"]
    notified = row["last_notified_at"]
    return ReviewTask(
        id=row["id"],
        topic_id=row["topic_id"],
        topic_title=row["topic_title"],
        created_at=datetime.fromisoformat(row["created_at"]),
        due_at=datetime.fromisoformat(row["due_at"]),
        stage=int(row["stage"]),
        status=row["status"],
        interval_days=int(row["interval_days"]),
        last_result_percent=row["last_result_percent"],
        completed_at=datetime.fromisoformat(completed) if completed else None,
        last_notified_at=datetime.fromisoformat(notified) if notified else None,
    )
