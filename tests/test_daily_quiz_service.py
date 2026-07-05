from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.core.db import Database
from app.core.repo import RepoService
from app.features.daily_quiz.service import DailyQuizService


class DailyQuizServiceTest(unittest.TestCase):
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
                    "## Go",
                    "",
                    "| # | Тема | Материалы | Статус |",
                    "|---|---|---|---|",
                    "| GO1 | Слайсы | [review](go-slices.md) | Готово |",
                    "| GO2 | GC | - | Планируется |",
                ]
            ),
            encoding="utf-8",
        )
        (self.repo_path / "go-slices.md").write_text("# Слайсы\n", encoding="utf-8")
        self.db = Database(self.root / "test.sqlite3")
        self.db.initialize()
        self.service = DailyQuizService(self.db, RepoService(self.repo_path))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_toggle_and_sent_guard(self) -> None:
        today = date(2026, 7, 5)

        self.assertFalse(self.service.is_enabled())
        self.assertFalse(self.service.should_send_today(today))

        self.service.set_enabled(True)
        self.assertTrue(self.service.is_enabled())
        self.assertTrue(self.service.should_send_today(today))

        self.service.mark_sent(today)
        self.assertFalse(self.service.should_send_today(today))

    def test_ready_topics_only_include_ready_topics_with_materials(self) -> None:
        topics = self.service.ready_topics()

        self.assertEqual(["go1"], [topic.id for topic in topics])


if __name__ == "__main__":
    unittest.main()
