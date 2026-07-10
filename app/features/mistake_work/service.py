from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any

from app.core.db import Database
from app.features.mistake_work.agent import MistakeReviewResult
from app.features.mistake_work.models import MistakeWorkItem, mistake_work_item_from_row
from app.features.quiz.models import QuizSession


ACTIVE = "active"
DONE = "done"
DELETED = "deleted"


class MistakeWorkService:
    def __init__(self, db: Database):
        self.db = db

    def create_item(
        self,
        *,
        session: QuizSession,
        report: MistakeReviewResult,
        questions: list[dict[str, Any]],
        now: datetime | None = None,
    ) -> MistakeWorkItem:
        created = (now or _now()).replace(microsecond=0)
        item = MistakeWorkItem(
            id=uuid.uuid4().hex[:12],
            quiz_session_id=session.id,
            topic_id=session.topic_id,
            topic_title=session.topic_title or str(session.material_snapshot.get("topic_title") or session.topic_id),
            session_type=session.session_type,
            status=ACTIVE,
            priority=report.priority,
            title=report.title,
            section=report.section,
            summary=report.summary,
            diagnosis=report.diagnosis,
            weak_concepts=report.weak_concepts,
            questions=questions,
            suggestion=report.material_suggestion,
            report=_report_payload(report),
            agent_provider=report.provider,
            agent_model=report.model,
            prompt_version=report.prompt_version,
            created_at=created,
            updated_at=created,
        )
        self._insert(item)
        return item

    def list_active(self, *, limit: int = 20) -> list[MistakeWorkItem]:
        return self._list_by_status(ACTIVE, limit=limit)

    def list_done(self, *, limit: int = 20) -> list[MistakeWorkItem]:
        return self._list_by_status(DONE, limit=limit)

    def get_item(self, item_id: str) -> MistakeWorkItem | None:
        clean_id = item_id.strip()
        if not clean_id:
            return None
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT * FROM mistake_work_items WHERE id = ?",
                (clean_id,),
            ).fetchone()
        return mistake_work_item_from_row(row) if row else None

    def mark_done(self, item_id: str) -> MistakeWorkItem:
        item = self.get_item(item_id)
        if not item:
            raise ValueError("Mistake work item not found")
        now = _now()
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE mistake_work_items
                SET status = ?, updated_at = ?, done_at = ?
                WHERE id = ?
                """,
                (DONE, now.isoformat(), now.isoformat(), item.id),
            )
        updated = self.get_item(item.id)
        if not updated:
            raise ValueError("Mistake work item not found after update")
        return updated

    def delete_item(self, item_id: str) -> MistakeWorkItem:
        item = self.get_item(item_id)
        if not item:
            raise ValueError("Mistake work item not found")
        now = _now()
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE mistake_work_items
                SET status = ?, updated_at = ?, deleted_at = ?
                WHERE id = ?
                """,
                (DELETED, now.isoformat(), now.isoformat(), item.id),
            )
        updated = self.get_item(item.id)
        if not updated:
            raise ValueError("Mistake work item not found after delete")
        return updated

    def _list_by_status(self, status: str, *, limit: int) -> list[MistakeWorkItem]:
        with self.db.session() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM mistake_work_items
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        return [mistake_work_item_from_row(row) for row in rows]

    def _insert(self, item: MistakeWorkItem) -> None:
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO mistake_work_items (
                    id,
                    quiz_session_id,
                    topic_id,
                    topic_title,
                    session_type,
                    status,
                    priority,
                    title,
                    section,
                    summary,
                    diagnosis,
                    weak_concepts_json,
                    questions_json,
                    suggestion_json,
                    report_json,
                    agent_provider,
                    agent_model,
                    prompt_version,
                    created_at,
                    updated_at,
                    done_at,
                    deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.quiz_session_id,
                    item.topic_id,
                    item.topic_title,
                    item.session_type,
                    item.status,
                    item.priority,
                    item.title,
                    item.section,
                    item.summary,
                    item.diagnosis,
                    json.dumps(item.weak_concepts, ensure_ascii=False),
                    json.dumps(item.questions, ensure_ascii=False),
                    json.dumps(item.suggestion, ensure_ascii=False),
                    json.dumps(item.report, ensure_ascii=False),
                    item.agent_provider,
                    item.agent_model,
                    item.prompt_version,
                    item.created_at.isoformat(),
                    item.updated_at.isoformat(),
                    item.done_at.isoformat() if item.done_at else None,
                    item.deleted_at.isoformat() if item.deleted_at else None,
                ),
            )


def _report_payload(report: MistakeReviewResult) -> dict[str, Any]:
    payload = asdict(report)
    payload.pop("raw_payload", None)
    if report.raw_payload:
        payload["raw_payload"] = report.raw_payload
    return payload


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)
