from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.core.db import Database
from app.core.repo import RepoService
from app.features.review_tasks.service import (
    CANCELLED,
    COMPLETED,
    ReviewTaskService,
    TopicNotReadyError,
)


class ReviewTaskServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "lk-prep"
        self.repo.mkdir()
        (self.repo / "python-gil.md").write_text(
            "# Python GIL\n\nNotes about global interpreter lock.\n",
            encoding="utf-8",
        )
        (self.repo / "topics.json").write_text(
            """
            {
              "topics": [
                {
                  "id": "planned1",
                  "title": "Planned topic without materials",
                  "status": "planned",
                  "paths": []
                }
              ]
            }
            """,
            encoding="utf-8",
        )
        self.db = Database(self.root / "test.sqlite3")
        self.db.initialize()
        self.service = ReviewTaskService(self.db, RepoService(self.repo))
        self.now = datetime(2026, 7, 3, 10, 0, 0)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_review_task_from_repo_topic(self) -> None:
        result = self.service.create_review_task("Python GIL", now=self.now)

        self.assertTrue(result.created)
        self.assertEqual("Python GIL", result.topic.title)
        self.assertEqual(["python-gil.md"], result.topic.source_paths)
        self.assertTrue(result.topic.material_fingerprint)
        self.assertEqual(1, result.task.stage)
        self.assertEqual(datetime(2026, 7, 4, 9, 0, 0), result.task.due_at)

    def test_create_review_task_from_topic_id(self) -> None:
        result = self.service.create_review_task_for_topic_id(
            "python-gil",
            now=self.now,
        )

        self.assertTrue(result.created)
        self.assertEqual("python-gil", result.topic.id)
        self.assertEqual("Python GIL", result.topic.title)
        self.assertEqual(datetime(2026, 7, 4, 9, 0, 0), result.task.due_at)

    def test_create_review_task_ignores_query_punctuation(self) -> None:
        result = self.service.create_review_task("PYTHON GIL!", now=self.now)

        self.assertTrue(result.created)
        self.assertEqual("Python GIL", result.topic.title)

    def test_create_review_task_ignores_voice_command_words(self) -> None:
        result = self.service.create_review_task(
            "давай python gil на повторение!",
            now=self.now,
        )

        self.assertTrue(result.created)
        self.assertEqual("Python GIL", result.topic.title)

    def test_duplicate_active_task_is_not_created(self) -> None:
        first = self.service.create_review_task("Python GIL", now=self.now)
        second = self.service.create_review_task("Python GIL", now=self.now)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.task.id, second.task.id)

    def test_replace_existing_active_task(self) -> None:
        first = self.service.create_review_task("Python GIL", now=self.now)
        second = self.service.create_review_task(
            "Python GIL",
            initial_due_days=-1,
            replace_existing=True,
            now=self.now + timedelta(hours=1),
        )

        self.assertTrue(first.created)
        self.assertTrue(second.created)
        self.assertNotEqual(first.task.id, second.task.id)
        self.assertEqual(datetime(2026, 7, 2, 9, 0, 0), second.task.due_at)
        upcoming = self.service.upcoming()
        self.assertEqual([second.task.id], [task.id for task in upcoming])
        old = self.service.get_task(first.task.id)
        self.assertEqual(CANCELLED, old.status)

    def test_replace_existing_active_task_by_topic_id(self) -> None:
        first = self.service.create_review_task_for_topic_id("python-gil", now=self.now)
        second = self.service.create_review_task_for_topic_id(
            "python-gil",
            replace_existing=True,
            now=self.now + timedelta(hours=1),
        )

        self.assertTrue(first.created)
        self.assertTrue(second.created)
        self.assertNotEqual(first.task.id, second.task.id)
        self.assertEqual(1, second.task.stage)
        self.assertEqual(datetime(2026, 7, 4, 9, 0, 0), second.task.due_at)
        self.assertEqual(CANCELLED, self.service.get_task(first.task.id).status)

    def test_unknown_topic_is_not_created_without_materials(self) -> None:
        with self.assertRaises(TopicNotReadyError) as ctx:
            self.service.create_review_task("Unknown Topic", now=self.now)

        self.assertIn("не найдена", ctx.exception.reason)
        self.assertTrue(ctx.exception.suggestions)

    def test_planned_topic_without_materials_is_not_created(self) -> None:
        with self.assertRaises(TopicNotReadyError) as ctx:
            self.service.create_review_task(
                "Planned topic without materials",
                now=self.now,
            )

        self.assertIn("не привязаны", ctx.exception.reason)
        self.assertTrue(ctx.exception.suggestions)

    def test_due_tasks(self) -> None:
        self.service.create_review_task("Python GIL", now=self.now)

        before_due = self.service.due_tasks(now=self.now + timedelta(hours=12))
        after_due = self.service.due_tasks(now=self.now + timedelta(days=1, minutes=1))

        self.assertEqual([], before_due)
        self.assertEqual(1, len(after_due))

    def test_due_for_notification_once_per_day(self) -> None:
        task = self.service.create_review_task(
            "Python GIL",
            now=self.now,
            initial_due_days=-1,
        ).task
        notify_at = self.now + timedelta(days=1)

        first = self.service.due_for_notification(now=notify_at)
        self.assertEqual([task.id], [item.id for item in first])

        marked = self.service.mark_notified(task.id, now=notify_at)
        self.assertEqual(notify_at, marked.last_notified_at)

        same_day = self.service.due_for_notification(now=notify_at + timedelta(hours=1))
        next_day = self.service.due_for_notification(now=notify_at + timedelta(days=1))

        self.assertEqual([], same_day)
        self.assertEqual([task.id], [item.id for item in next_day])

    def test_complete_success_advances_stage(self) -> None:
        task = self.service.create_review_task("Python GIL", now=self.now).task

        updated = self.service.complete_task(task.id, 85, now=self.now)

        self.assertEqual(2, updated.stage)
        self.assertEqual(7, updated.interval_days)
        self.assertEqual(datetime(2026, 7, 10, 9, 0, 0), updated.due_at)

    def test_complete_low_score_repeats_tomorrow(self) -> None:
        task = self.service.create_review_task("Python GIL", now=self.now).task

        updated = self.service.complete_task(task.id, 45, now=self.now)

        self.assertEqual(1, updated.stage)
        self.assertEqual(1, updated.interval_days)
        self.assertEqual(datetime(2026, 7, 4, 9, 0, 0), updated.due_at)

    def test_stage_three_success_completes_task(self) -> None:
        task = self.service.create_review_task("Python GIL", now=self.now).task
        stage_two = self.service.complete_task(task.id, 90, now=self.now)
        stage_three = self.service.complete_task(stage_two.id, 90, now=self.now)

        completed = self.service.complete_task(stage_three.id, 90, now=self.now)

        self.assertEqual(COMPLETED, completed.status)
        self.assertIsNotNone(completed.completed_at)

    def test_cancel_task(self) -> None:
        task = self.service.create_review_task("Python GIL", now=self.now).task

        cancelled = self.service.cancel_task(task.id)

        self.assertEqual(CANCELLED, cancelled.status)
        self.assertEqual([], self.service.upcoming())


if __name__ == "__main__":
    unittest.main()
