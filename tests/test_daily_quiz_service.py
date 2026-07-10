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
        self.repo_path = self.root / "lk-prep"
        self.repo_path.mkdir()
        (self.repo_path / "ROOT.md").write_text(
            "\n".join(
                [
                    "# LK Prep",
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

    def test_create_offer_starts_pending_and_is_outstanding(self) -> None:
        topic = self.service.ready_topics()[0]
        today = date(2026, 7, 5)

        offer = self.service.create_offer(topic, today)

        self.assertEqual("pending", offer.status)
        self.assertEqual(topic.id, offer.topic_id)
        self.assertEqual(topic.title, offer.topic_title)
        self.assertEqual(today.isoformat(), offer.offer_date)
        self.assertEqual(offer, self.service.get_offer(offer.id))
        self.assertEqual([offer.id], [item.id for item in self.service.list_outstanding()])

    def test_set_status_updates_offer_and_reflects_in_outstanding_list(self) -> None:
        topic = self.service.ready_topics()[0]
        offer = self.service.create_offer(topic, date(2026, 7, 5))

        started = self.service.set_status(offer.id, "started")
        self.assertEqual("started", started.status)
        self.assertEqual([offer.id], [item.id for item in self.service.list_outstanding()])

        self.service.set_status(offer.id, "done")
        self.assertEqual([], self.service.list_outstanding())

    def test_get_offer_returns_none_for_unknown_id(self) -> None:
        self.assertIsNone(self.service.get_offer("does-not-exist"))

    def test_list_outstanding_excludes_skipped_and_done(self) -> None:
        topic = self.service.ready_topics()[0]
        pending = self.service.create_offer(topic, date(2026, 7, 3))
        skipped = self.service.create_offer(topic, date(2026, 7, 4))
        done = self.service.create_offer(topic, date(2026, 7, 5))
        self.service.set_status(skipped.id, "skipped")
        self.service.set_status(done.id, "done")

        outstanding_ids = {item.id for item in self.service.list_outstanding()}

        self.assertEqual({pending.id}, outstanding_ids)


if __name__ == "__main__":
    unittest.main()
