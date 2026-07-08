from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.core.db import Database
from app.core.repo import RepoTopic
from app.features.explain_check.agent import ExplainCheckResult
from app.features.explain_check.service import ACTIVE, DELETED, DONE, ExplainCheckService


class ExplainCheckServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.sqlite3")
        self.db.initialize()
        self.service = ExplainCheckService(self.db)
        self.topic = RepoTopic(id="b08", title="Строки в Go", section="Базовый Go")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_mark_done_and_delete_item(self) -> None:
        result = ExplainCheckResult(
            layer_reached=2,
            priority="normal",
            summary="Верно объяснил immutability строк.",
            covered_concepts=["string immutable"],
            missing_concepts=["rune vs byte"],
            false_models=[],
            follow_up_question="Что выведет len(\"привет\")?",
            provider="fake",
            model="fake",
        )

        item = self.service.create_item(
            topic=self.topic,
            source="voice",
            explanation_text="Строки в Go неизменяемы...",
            result=result,
            material_fingerprint="fp1",
            now=datetime(2026, 7, 8, 11, 0),
        )

        self.assertEqual(ACTIVE, item.status)
        self.assertEqual("normal", item.priority)
        self.assertEqual(2, item.layer_reached)
        self.assertEqual("voice", item.source)
        self.assertEqual([item], self.service.list_active())

        done = self.service.mark_done(item.id)
        self.assertEqual(DONE, done.status)
        self.assertEqual([], self.service.list_active())
        self.assertEqual([done], self.service.list_done())

        deleted = self.service.delete_item(item.id)
        self.assertEqual(DELETED, deleted.status)
        self.assertEqual([], self.service.list_done())

    def test_get_item_returns_none_for_missing_id(self) -> None:
        self.assertIsNone(self.service.get_item("does-not-exist"))

    def test_mark_done_raises_for_missing_item(self) -> None:
        with self.assertRaises(ValueError):
            self.service.mark_done("does-not-exist")


if __name__ == "__main__":
    unittest.main()
