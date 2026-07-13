from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.db import Database
from app.core.repo import RepoService
from app.features.open_questions.agent import FakeOpenQuestionAgent
from app.features.open_questions.service import ACTIVE, ANSWERED, OpenQuestionService


class OpenQuestionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "learnkeeper.sqlite3")
        self.db.migrate()
        self.repo = self.root / "lk-prep"
        self.repo.mkdir()
        (self.repo / "ROOT.md").write_text(
            """
# LK Prep

## Базы данных

| # | Тема | Материал | Практика | Статус |
|---|---|---|---|---|
| DB05 | Модели данных | [review.md](database/review.md) | - | Готово |
""".strip(),
            encoding="utf-8",
        )
        (self.repo / "database").mkdir()
        (self.repo / "database" / "review.md").write_text(
            """---
lk:
  source_role: primary_source_artifact
  challenge_helper: |
    Дай мини-кейс на выбор модели данных.
---

# Модели данных

Relational, document, graph.
""",
            encoding="utf-8",
        )
        self.service = OpenQuestionService(
            self.db,
            RepoService(self.repo),
            FakeOpenQuestionAgent(),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_generate_and_check_answer(self) -> None:
        question = self.service.generate_for_topic("db05")

        self.assertEqual(ACTIVE, question.status)
        self.assertEqual("db05", question.topic_id)
        self.assertIn("database/review.md", question.source_refs)
        self.assertTrue(question.material_snapshot["metadata"][0]["challenge_helper_hash"])

        updated, attempt = self.service.check_answer(
            question.id,
            "Relational fits joins, document fits aggregate reads, graph fits traversal.",
        )

        self.assertEqual(ANSWERED, updated.status)
        self.assertEqual(question.id, attempt.open_question_id)
        self.assertGreaterEqual(attempt.score_percent, 0)
        self.assertIsNotNone(self.service.latest_attempt(question.id))


if __name__ == "__main__":
    unittest.main()
