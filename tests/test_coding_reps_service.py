from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.core.db import Database
from app.features.coding_reps.models import CODING_REPS, get_coding_rep
from app.features.coding_reps.service import CodingRepsService


class CodingRepsServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.sqlite3")
        self.db.initialize()
        self.service = CodingRepsService(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_toggle_and_sent_guard(self) -> None:
        today = date(2026, 7, 8)

        self.assertFalse(self.service.is_enabled())
        self.assertFalse(self.service.should_send_today(today))

        self.service.set_enabled(True)
        self.assertTrue(self.service.is_enabled())
        self.assertTrue(self.service.should_send_today(today))

        self.service.mark_sent(today)
        self.assertFalse(self.service.should_send_today(today))

    def test_random_rep_returns_one_of_the_static_list(self) -> None:
        rep = self.service.random_rep()

        self.assertIn(rep, CODING_REPS)

    def test_random_rep_avoids_immediate_repeat(self) -> None:
        first = self.service.random_rep()
        self.service.log_sent(first)

        for _ in range(20):
            self.assertNotEqual(first.id, self.service.random_rep().id)

    def test_log_sent_and_mark_responded_round_trip(self) -> None:
        rep = get_coding_rep("lru-cache")
        assert rep is not None

        log_id = self.service.log_sent(rep)
        entries = self.service.recent_log()

        self.assertEqual(1, len(entries))
        self.assertEqual(rep.id, entries[0].rep_id)
        self.assertEqual("sent", entries[0].status)
        self.assertIsNone(entries[0].responded_at)

        self.service.mark_responded(log_id, "done")
        entries = self.service.recent_log()

        self.assertEqual("done", entries[0].status)
        self.assertIsNotNone(entries[0].responded_at)

    def test_all_reps_have_unique_ids(self) -> None:
        ids = [rep.id for rep in CODING_REPS]

        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
