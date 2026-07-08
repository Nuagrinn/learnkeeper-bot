from __future__ import annotations

import json
import uuid
from datetime import datetime

from app.core.db import Database
from app.core.repo import RepoTopic
from app.features.explain_check.agent import ExplainCheckResult
from app.features.explain_check.models import ExplanationCheck, explanation_check_from_row


ACTIVE = "active"
DONE = "done"
DELETED = "deleted"


class ExplainCheckService:
    def __init__(self, db: Database):
        self.db = db

    def create_item(
        self,
        *,
        topic: RepoTopic,
        source: str,
        explanation_text: str,
        result: ExplainCheckResult,
        material_fingerprint: str = "",
        linked_review_task_id: str = "",
        now: datetime | None = None,
    ) -> ExplanationCheck:
        created = (now or _now()).replace(microsecond=0)
        item = ExplanationCheck(
            id=uuid.uuid4().hex[:12],
            topic_id=topic.id,
            topic_title=topic.title,
            section=topic.section,
            source=source,
            explanation_text=explanation_text,
            status=ACTIVE,
            priority=result.priority,
            layer_reached=result.layer_reached,
            summary=result.summary,
            covered_concepts=result.covered_concepts,
            missing_concepts=result.missing_concepts,
            false_models=result.false_models,
            follow_up_question=result.follow_up_question,
            material_fingerprint=material_fingerprint,
            agent_provider=result.provider,
            agent_model=result.model,
            prompt_version=result.prompt_version,
            created_at=created,
            updated_at=created,
            linked_review_task_id=linked_review_task_id,
        )
        self._insert(item)
        return item

    def list_active(self, *, limit: int = 20) -> list[ExplanationCheck]:
        return self._list_by_status(ACTIVE, limit=limit)

    def list_done(self, *, limit: int = 20) -> list[ExplanationCheck]:
        return self._list_by_status(DONE, limit=limit)

    def list_by_task(self, task_id: str) -> list[ExplanationCheck]:
        """Explanation checks done right before a specific scheduled review task.

        Powers future progress stats (e.g. "did explaining first help the score?")
        by joining on review_tasks.id / quiz_sessions.task_id.
        """
        with self.db.session() as conn:
            rows = conn.execute(
                """
                SELECT * FROM explanation_checks
                WHERE linked_review_task_id = ?
                ORDER BY created_at DESC
                """,
                (task_id,),
            ).fetchall()
        return [explanation_check_from_row(row) for row in rows]

    def get_item(self, item_id: str) -> ExplanationCheck | None:
        clean_id = item_id.strip()
        if not clean_id:
            return None
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT * FROM explanation_checks WHERE id = ?",
                (clean_id,),
            ).fetchone()
        return explanation_check_from_row(row) if row else None

    def mark_done(self, item_id: str) -> ExplanationCheck:
        item = self.get_item(item_id)
        if not item:
            raise ValueError("Explanation check not found")
        now = _now()
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE explanation_checks
                SET status = ?, updated_at = ?, done_at = ?
                WHERE id = ?
                """,
                (DONE, now.isoformat(), now.isoformat(), item.id),
            )
        updated = self.get_item(item.id)
        if not updated:
            raise ValueError("Explanation check not found after update")
        return updated

    def delete_item(self, item_id: str) -> ExplanationCheck:
        item = self.get_item(item_id)
        if not item:
            raise ValueError("Explanation check not found")
        now = _now()
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE explanation_checks
                SET status = ?, updated_at = ?, deleted_at = ?
                WHERE id = ?
                """,
                (DELETED, now.isoformat(), now.isoformat(), item.id),
            )
        updated = self.get_item(item.id)
        if not updated:
            raise ValueError("Explanation check not found after delete")
        return updated

    def _list_by_status(self, status: str, *, limit: int) -> list[ExplanationCheck]:
        with self.db.session() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM explanation_checks
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        return [explanation_check_from_row(row) for row in rows]

    def _insert(self, item: ExplanationCheck) -> None:
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO explanation_checks (
                    id,
                    topic_id,
                    topic_title,
                    section,
                    source,
                    explanation_text,
                    status,
                    priority,
                    layer_reached,
                    summary,
                    covered_concepts_json,
                    missing_concepts_json,
                    false_models_json,
                    follow_up_question,
                    material_fingerprint,
                    agent_provider,
                    agent_model,
                    prompt_version,
                    created_at,
                    updated_at,
                    done_at,
                    deleted_at,
                    linked_review_task_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.topic_id,
                    item.topic_title,
                    item.section,
                    item.source,
                    item.explanation_text,
                    item.status,
                    item.priority,
                    item.layer_reached,
                    item.summary,
                    json.dumps(item.covered_concepts, ensure_ascii=False),
                    json.dumps(item.missing_concepts, ensure_ascii=False),
                    json.dumps(item.false_models, ensure_ascii=False),
                    item.follow_up_question,
                    item.material_fingerprint,
                    item.agent_provider,
                    item.agent_model,
                    item.prompt_version,
                    item.created_at.isoformat(),
                    item.updated_at.isoformat(),
                    item.done_at.isoformat() if item.done_at else None,
                    item.deleted_at.isoformat() if item.deleted_at else None,
                    item.linked_review_task_id,
                ),
            )


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)
