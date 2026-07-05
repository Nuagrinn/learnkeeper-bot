from __future__ import annotations

import json
import uuid
from datetime import datetime, time, timedelta

from app.core.db import Database
from app.core.repo import RepoService
from app.features.review_tasks.models import (
    CreateReviewTaskResult,
    ReviewTask,
    Topic,
    review_task_from_row,
    topic_from_row,
)


ACTIVE = "active"
COMPLETED = "completed"
CANCELLED = "cancelled"
STAGE_INTERVALS = {1: 1, 2: 7, 3: 30}
MIN_TOPIC_MATCH_SCORE = 50
DEFAULT_DUE_TIME = time(hour=9)


class TopicNotReadyError(ValueError):
    def __init__(self, query: str, *, reason: str, suggestions: list[str] | None = None):
        self.query = query
        self.reason = reason
        self.suggestions = suggestions or []
        super().__init__(reason)


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _task_id() -> str:
    return uuid.uuid4().hex[:12]


def _scheduled_due_at(now: datetime, interval_days: int) -> datetime:
    target_date = (now + timedelta(days=interval_days)).date()
    return datetime.combine(target_date, DEFAULT_DUE_TIME)


class ReviewTaskService:
    def __init__(self, db: Database, repo: RepoService):
        self.db = db
        self.repo = repo

    def create_review_task(
        self,
        topic_query: str,
        *,
        initial_due_days: int = 1,
        replace_existing: bool = False,
        now: datetime | None = None,
    ) -> CreateReviewTaskResult:
        clean_query = topic_query.strip()
        if not clean_query:
            raise ValueError("Topic query must not be empty")

        now = (now or _now()).replace(microsecond=0)
        repo_topic = self._resolve_ready_topic(clean_query)
        return self._create_task_for_repo_topic(
            repo_topic,
            initial_due_days=initial_due_days,
            replace_existing=replace_existing,
            now=now,
        )

    def create_review_task_for_topic_id(
        self,
        topic_id: str,
        *,
        initial_due_days: int = 1,
        replace_existing: bool = False,
        now: datetime | None = None,
    ) -> CreateReviewTaskResult:
        clean_topic_id = topic_id.strip().lower()
        if not clean_topic_id:
            raise ValueError("Topic id must not be empty")

        now = (now or _now()).replace(microsecond=0)
        repo_topic = self._resolve_ready_topic_id(clean_topic_id)
        return self._create_task_for_repo_topic(
            repo_topic,
            initial_due_days=initial_due_days,
            replace_existing=replace_existing,
            now=now,
        )

    def _create_task_for_repo_topic(
        self,
        repo_topic,
        *,
        initial_due_days: int,
        replace_existing: bool,
        now: datetime,
    ) -> CreateReviewTaskResult:
        topic = self._upsert_topic(
            Topic(
                id=repo_topic.id,
                title=repo_topic.title,
                status=repo_topic.status,
                section=repo_topic.section,
                order_index=repo_topic.order_index,
                material_fingerprint=repo_topic.material_fingerprint,
                tags=repo_topic.tags,
                source_paths=repo_topic.source_paths,
            ),
            now=now,
        )

        existing = self._active_task_for_topic(topic.id)
        if existing:
            if not replace_existing:
                return CreateReviewTaskResult(task=existing, topic=topic, created=False)
            self.cancel_task(existing.id)

        due_at = _scheduled_due_at(now, initial_due_days)
        task = ReviewTask(
            id=_task_id(),
            topic_id=topic.id,
            topic_title=topic.title,
            created_at=now,
            due_at=due_at,
            stage=1,
            status=ACTIVE,
            interval_days=initial_due_days,
        )
        self._insert_task(task)
        return CreateReviewTaskResult(task=task, topic=topic, created=True)

    def _resolve_ready_topic(self, query: str):
        matches = self.repo.search_topics(query, limit=5)
        suggestions = [
            f"{topic.id} | {topic.title}"
            for topic in self._suggest_ready_topics(query, matches=matches)
        ]
        if not matches or matches[0].score < MIN_TOPIC_MATCH_SCORE:
            raise TopicNotReadyError(
                query,
                reason=(
                    f"Тема \"{query}\" не найдена в interview-review "
                    "с готовыми материалами."
                ),
                suggestions=suggestions,
            )

        topic = matches[0]
        materials = self.repo.get_topic_materials(topic)
        if not materials.files:
            raise TopicNotReadyError(
                query,
                reason=(
                    f"Тема \"{topic.title}\" найдена, но к ней пока не привязаны "
                    "читаемые материалы."
                ),
                suggestions=suggestions,
            )
        return topic

    def _resolve_ready_topic_id(self, topic_id: str):
        topic = self.repo.get_topic(topic_id)
        if not topic:
            raise TopicNotReadyError(
                topic_id,
                reason=f"Тема с id \"{topic_id}\" не найдена в interview-review.",
                suggestions=[],
            )
        materials = self.repo.get_topic_materials(topic)
        if not materials.files:
            raise TopicNotReadyError(
                topic_id,
                reason=(
                    f"Тема \"{topic.title}\" найдена, но к ней пока не привязаны "
                    "читаемые материалы."
                ),
                suggestions=[],
            )
        return topic

    def _suggest_ready_topics(self, query: str, *, matches) -> list:
        seen: set[str] = set()
        suggestions: list = []
        for topic in matches:
            if topic.id in seen:
                continue
            if self.repo.get_topic_materials(topic).files:
                suggestions.append(topic)
                seen.add(topic.id)
        for topic in self.repo.list_topics():
            if len(suggestions) >= 5:
                break
            if topic.id in seen:
                continue
            if not self.repo.get_topic_materials(topic).files:
                continue
            suggestions.append(topic)
            seen.add(topic.id)
        return suggestions[:5]

    def upcoming(self, *, limit: int = 20) -> list[ReviewTask]:
        return self._select_tasks(
            "WHERE rt.status = ? ORDER BY rt.due_at ASC LIMIT ?",
            (ACTIVE, limit),
        )

    def due_tasks(self, *, now: datetime | None = None, limit: int = 20) -> list[ReviewTask]:
        now = (now or _now()).replace(microsecond=0)
        return self._select_tasks(
            "WHERE rt.status = ? AND rt.due_at <= ? ORDER BY rt.due_at ASC LIMIT ?",
            (ACTIVE, now.isoformat(timespec="seconds"), limit),
        )

    def due_for_notification(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
    ) -> list[ReviewTask]:
        now = (now or _now()).replace(microsecond=0)
        today = now.date().isoformat()
        return self._select_tasks(
            """
            WHERE rt.status = ?
              AND rt.due_at <= ?
              AND (
                    rt.last_notified_at IS NULL
                    OR substr(rt.last_notified_at, 1, 10) < ?
                  )
            ORDER BY rt.due_at ASC
            LIMIT ?
            """,
            (ACTIVE, now.isoformat(timespec="seconds"), today, limit),
        )

    def mark_notified(self, task_id: str, *, now: datetime | None = None) -> ReviewTask:
        now = (now or _now()).replace(microsecond=0)
        with self.db.session() as conn:
            conn.execute(
                "UPDATE review_tasks SET last_notified_at = ? WHERE id = ?",
                (now.isoformat(timespec="seconds"), task_id),
            )
        return self.get_task(task_id)

    def complete_task(
        self,
        task_id: str,
        score_percent: float,
        *,
        now: datetime | None = None,
    ) -> ReviewTask:
        if score_percent < 0 or score_percent > 100:
            raise ValueError("Score percent must be between 0 and 100")

        task = self._get_task(task_id)
        if task.status != ACTIVE:
            raise ValueError(f"Task {task_id} is not active")

        now = (now or _now()).replace(microsecond=0)

        if score_percent >= 80:
            if task.stage >= 3:
                self._mark_completed(task.id, score_percent, now)
            else:
                next_stage = task.stage + 1
                interval = STAGE_INTERVALS[next_stage]
                self._reschedule(task.id, next_stage, interval, score_percent, now)
        elif score_percent >= 60:
            self._reschedule(task.id, task.stage, 3, score_percent, now)
        else:
            self._reschedule(task.id, task.stage, 1, score_percent, now)

        return self._get_task(task_id)

    def get_task(self, task_id: str) -> ReviewTask:
        return self._get_task(task_id)

    def cancel_task(self, task_id: str) -> ReviewTask:
        task = self._get_task(task_id)
        if task.status != ACTIVE:
            raise ValueError(f"Task {task_id} is not active")
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE review_tasks
                SET status = ?,
                    last_notified_at = NULL
                WHERE id = ?
                """,
                (CANCELLED, task_id),
            )
        return self._get_task(task_id)

    def _upsert_topic(self, topic: Topic, *, now: datetime) -> Topic:
        stamp = now.isoformat(timespec="seconds")
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO topics (
                    id, title, status, tags_json, source_paths_json,
                    last_seen_commit, section, order_index, material_fingerprint,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    status = excluded.status,
                    tags_json = excluded.tags_json,
                    source_paths_json = excluded.source_paths_json,
                    section = excluded.section,
                    order_index = excluded.order_index,
                    material_fingerprint = excluded.material_fingerprint,
                    updated_at = excluded.updated_at
                """,
                (
                    topic.id,
                    topic.title,
                    topic.status,
                    json.dumps(topic.tags, ensure_ascii=False),
                    json.dumps(topic.source_paths, ensure_ascii=False),
                    topic.last_seen_commit,
                    topic.section,
                    topic.order_index,
                    topic.material_fingerprint,
                    stamp,
                    stamp,
                ),
            )
            row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic.id,)).fetchone()
        return topic_from_row(row)

    def _active_task_for_topic(self, topic_id: str) -> ReviewTask | None:
        tasks = self._select_tasks(
            "WHERE rt.topic_id = ? AND rt.status = ? ORDER BY rt.due_at ASC LIMIT 1",
            (topic_id, ACTIVE),
        )
        return tasks[0] if tasks else None

    def _insert_task(self, task: ReviewTask) -> None:
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO review_tasks (
                    id, topic_id, created_at, due_at, stage, status,
                    interval_days, last_result_percent, completed_at, last_notified_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.topic_id,
                    task.created_at.isoformat(timespec="seconds"),
                    task.due_at.isoformat(timespec="seconds"),
                    task.stage,
                    task.status,
                    task.interval_days,
                    task.last_result_percent,
                    task.completed_at.isoformat(timespec="seconds")
                    if task.completed_at
                    else None,
                    task.last_notified_at.isoformat(timespec="seconds")
                    if task.last_notified_at
                    else None,
                ),
            )

    def _get_task(self, task_id: str) -> ReviewTask:
        rows = self._select_tasks("WHERE rt.id = ?", (task_id,))
        if not rows:
            raise ValueError(f"Review task not found: {task_id}")
        return rows[0]

    def _select_tasks(self, where_sql: str, params: tuple[object, ...]) -> list[ReviewTask]:
        sql = f"""
            SELECT
                rt.*,
                t.title AS topic_title
            FROM review_tasks rt
            JOIN topics t ON t.id = rt.topic_id
            {where_sql}
        """
        with self.db.session() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [review_task_from_row(row) for row in rows]

    def _reschedule(
        self,
        task_id: str,
        stage: int,
        interval_days: int,
        score_percent: float,
        now: datetime,
    ) -> None:
        due_at = _scheduled_due_at(now, interval_days)
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE review_tasks
                SET stage = ?,
                    interval_days = ?,
                    due_at = ?,
                    last_result_percent = ?,
                    last_notified_at = NULL
                WHERE id = ?
                """,
                (
                    stage,
                    interval_days,
                    due_at.isoformat(timespec="seconds"),
                    score_percent,
                    task_id,
                ),
            )

    def _mark_completed(self, task_id: str, score_percent: float, now: datetime) -> None:
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE review_tasks
                SET status = ?,
                    last_result_percent = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (COMPLETED, score_percent, now.isoformat(timespec="seconds"), task_id),
            )
