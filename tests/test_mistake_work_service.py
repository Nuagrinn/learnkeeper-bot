from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.core.db import Database
from app.features.mistake_work.agent import MistakeReviewResult
from app.features.mistake_work.service import ACTIVE, DELETED, DONE, MistakeWorkService
from app.features.quiz.models import QuizSession


class MistakeWorkServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "test.sqlite3")
        self.db.initialize()
        self.session = QuizSession(
            id="s1",
            task_id=None,
            topic_id="db01",
            topic_title="Индексы PostgreSQL",
            session_type="instant",
            status="finished",
            question_count=2,
            current_question_no=2,
            started_at=datetime(2026, 7, 5, 10, 0),
            finished_at=datetime(2026, 7, 5, 10, 5),
            material_fingerprint="abc",
            material_snapshot={"topic_title": "Индексы PostgreSQL"},
            score_percent=50,
            correct_count=1,
            total_count=2,
        )
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO topics (
                    id, title, status, tags_json, source_paths_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.session.topic_id,
                    self.session.topic_title,
                    "ready",
                    "[]",
                    "[]",
                    self.session.started_at.isoformat(),
                    self.session.started_at.isoformat(),
                ),
            )
            conn.execute(
                """
                INSERT INTO quiz_sessions (
                    id, task_id, topic_id, topic_title, session_type, status,
                    question_count, current_question_no, started_at, finished_at,
                    material_fingerprint, material_snapshot_json,
                    generator_provider, generator_model, prompt_version, generated_at,
                    score_percent, correct_count, total_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.session.id,
                    self.session.task_id,
                    self.session.topic_id,
                    self.session.topic_title,
                    self.session.session_type,
                    self.session.status,
                    self.session.question_count,
                    self.session.current_question_no,
                    self.session.started_at.isoformat(),
                    self.session.finished_at.isoformat(),
                    self.session.material_fingerprint,
                    '{"topic_title":"Индексы PostgreSQL"}',
                    "",
                    "",
                    "",
                    None,
                    self.session.score_percent,
                    self.session.correct_count,
                    self.session.total_count,
                ),
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_mark_done_and_delete_item(self) -> None:
        service = MistakeWorkService(self.db)
        report = MistakeReviewResult(
            title="Разбор индексов",
            section="Базы данных",
            priority="high",
            summary="Пробел в INCLUDE.",
            diagnosis="Нужно доразобрать устройство индекса.",
            weak_concepts=["INCLUDE", "index-only scan"],
            interview_review_suggestion={
                "title": "Индексы PostgreSQL: INCLUDE",
                "target_section": "Базы данных",
                "details": "Добавить примеры.",
            },
            questions_to_revisit=[
                {
                    "question_no": 2,
                    "missed_point": "INCLUDE не ключ.",
                    "correct_idea": "INCLUDE хранится отдельно от key columns.",
                    "practice_prompt": "Объяснить на примере.",
                }
            ],
            provider="fake",
            model="fake",
        )

        item = service.create_item(
            session=self.session,
            report=report,
            questions=[{"question_no": 2, "question": "Что такое INCLUDE?"}],
            now=datetime(2026, 7, 5, 11, 0),
        )

        self.assertEqual(ACTIVE, item.status)
        self.assertEqual("high", item.priority)
        self.assertEqual([item], service.list_active())

        done = service.mark_done(item.id)
        self.assertEqual(DONE, done.status)
        self.assertEqual([], service.list_active())
        self.assertEqual([done], service.list_done())

        deleted = service.delete_item(item.id)
        self.assertEqual(DELETED, deleted.status)
        self.assertEqual([], service.list_done())


if __name__ == "__main__":
    unittest.main()
