from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.core.db import Database
from app.core.repo import RepoPullResult, RepoService
from app.features.quiz.generator import FakeQuizGenerator
from app.features.quiz.service import (
    FINISHED,
    IN_PROGRESS,
    SESSION_INSTANT,
    QuestionClosedError,
    QuizService,
)
from app.features.review_tasks.service import ReviewTaskService


class QuizServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo_path = self.root / "interview-review"
        self.repo_path.mkdir()
        (self.repo_path / "ROOT.md").write_text(
            "\n".join(
                [
                    "# Interview Review",
                    "",
                    "## Python",
                    "",
                    "| # | Тема | Материалы | Статус |",
                    "|---|---|---|---|",
                    "| PY1 | Python GIL | [notes](python-gil.md) | Готово |",
                ]
            ),
            encoding="utf-8",
        )
        (self.repo_path / "python-gil.md").write_text(
            "# Python GIL\n\nGlobal interpreter lock notes.\n",
            encoding="utf-8",
        )
        self.db = Database(self.root / "test.sqlite3")
        self.db.initialize()
        self.repo = RepoService(self.repo_path)
        self.review_tasks = ReviewTaskService(self.db, self.repo)
        self.quiz = QuizService(
            self.db,
            self.repo,
            self.review_tasks,
            FakeQuizGenerator(),
        )
        self.now = datetime(2026, 7, 3, 10, 0, 0)
        self.task = self.review_tasks.create_review_task(
            "Python GIL",
            now=self.now,
            initial_due_days=-1,
        ).task

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_start_session_generates_questions_from_current_materials(self) -> None:
        result = self.quiz.start_session(
            self.task.id,
            question_count=3,
            now=self.now + timedelta(days=1),
        )

        self.assertTrue(result.created)
        self.assertEqual(IN_PROGRESS, result.session.status)
        self.assertEqual(3, result.session.question_count)
        self.assertEqual(1, result.question.question_no)
        self.assertEqual(["python-gil.md"], result.session.material_snapshot["source_paths"])
        self.assertTrue(result.session.material_fingerprint)
        self.assertEqual(3, len(self.quiz.questions(result.session.id)))

    def test_start_session_reuses_active_session(self) -> None:
        first = self.quiz.start_session(self.task.id, question_count=3, now=self.now)
        second = self.quiz.start_session(self.task.id, question_count=5, now=self.now)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.session.id, second.session.id)
        self.assertEqual(3, second.session.question_count)

    def test_pull_before_quiz_refreshes_repo_on_start(self) -> None:
        quiz = QuizService(
            self.db,
            self.repo,
            self.review_tasks,
            FakeQuizGenerator(),
            pull_before_quiz=True,
            git_remote="origin",
            git_branch="main",
            pull_timeout_seconds=42,
        )
        calls: list[dict] = []

        def spy(**kwargs):
            calls.append(kwargs)
            return RepoPullResult("up_to_date")

        self.repo.pull_latest = spy

        quiz.start_session(self.task.id, question_count=2, now=self.now)

        self.assertEqual(1, len(calls))
        self.assertEqual("origin", calls[0]["remote"])
        self.assertEqual("main", calls[0]["branch"])
        self.assertEqual(42, calls[0]["timeout_seconds"])

    def test_pull_before_quiz_disabled_does_not_touch_repo(self) -> None:
        calls: list[dict] = []
        self.repo.pull_latest = lambda **kwargs: calls.append(kwargs)

        self.quiz.start_session(self.task.id, question_count=2, now=self.now)

        self.assertEqual([], calls)

    def test_answering_old_question_is_rejected(self) -> None:
        started = self.quiz.start_session(self.task.id, question_count=2, now=self.now)
        first_question = started.question

        self.quiz.answer_current(
            started.session.id,
            first_question.id,
            first_question.correct_index,
            now=self.now,
        )

        with self.assertRaises(QuestionClosedError):
            self.quiz.answer_current(
                started.session.id,
                first_question.id,
                first_question.correct_index,
                now=self.now,
            )

    def test_finishing_session_updates_score_and_review_task(self) -> None:
        started = self.quiz.start_session(self.task.id, question_count=2, now=self.now)
        current = started.question

        first = self.quiz.answer_current(
            started.session.id,
            current.id,
            current.correct_index,
            now=self.now,
        )
        self.assertIsNotNone(first.next_question)

        second_question = first.next_question
        self.assertIsNotNone(second_question)
        finished = self.quiz.answer_current(
            started.session.id,
            second_question.id,
            second_question.correct_index,
            now=self.now,
        )

        self.assertIsNone(finished.next_question)
        self.assertEqual(FINISHED, finished.session.status)
        self.assertEqual(100, finished.session.score_percent)
        self.assertIsNotNone(finished.finished_task)
        self.assertEqual(2, finished.finished_task.stage)
        self.assertEqual(datetime(2026, 7, 10, 9, 0, 0), finished.finished_task.due_at)

    def test_instant_topic_session_does_not_update_review_task(self) -> None:
        started = self.quiz.start_instant_topic_session(
            "py1",
            question_count=2,
            now=self.now,
        )

        self.assertEqual(SESSION_INSTANT, started.session.session_type)
        self.assertIsNone(started.session.task_id)
        self.assertEqual("Python GIL", started.session.topic_title)

        first = self.quiz.answer_current(
            started.session.id,
            started.question.id,
            started.question.correct_index,
            now=self.now,
        )
        self.assertIsNotNone(first.next_question)
        second_question = first.next_question
        self.assertIsNotNone(second_question)
        finished = self.quiz.answer_current(
            started.session.id,
            second_question.id,
            second_question.correct_index,
            now=self.now,
        )

        self.assertEqual(FINISHED, finished.session.status)
        self.assertIsNone(finished.finished_task)
        unchanged_task = self.review_tasks.get_task(self.task.id)
        self.assertEqual(1, unchanged_task.stage)
        self.assertEqual(self.task.due_at, unchanged_task.due_at)

    def test_instant_block_session_uses_section_materials(self) -> None:
        started = self.quiz.start_instant_block_session(
            "Python",
            question_count=1,
            now=self.now,
        )

        self.assertEqual(SESSION_INSTANT, started.session.session_type)
        self.assertIsNone(started.session.task_id)
        self.assertEqual("Блок: Python", started.session.topic_title)
        self.assertEqual(["python-gil.md"], started.session.material_snapshot["source_paths"])


if __name__ == "__main__":
    unittest.main()
