from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.db import Database
from app.features.topic_inbox.agent import TopicInboxAgentError
from app.features.topic_inbox.service import ACTIVE, DELETED, TopicInboxService


class StubTopicAgent:
    provider = "stub"
    model = "stub-model"
    prompt_version = "stub"

    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error

    def normalize(self, request: str):
        if self.error:
            raise self.error
        return self.result


class TopicInboxServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "test.sqlite3")
        self.db.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_item_from_agent_result(self) -> None:
        agent = StubTopicAgent(
            SimpleNamespace(
                title="System Design: Transactional Outbox",
                section="",
                summary="Нормализовано агентом.",
                provider="stub",
                model="stub-model",
            )
        )
        service = TopicInboxService(self.db, agent)

        item = service.create_item(
            "добавь отдельный блок System Design: Transactional Outbox",
            source="text",
        )

        self.assertEqual(ACTIVE, item.status)
        self.assertEqual("Transactional Outbox", item.title)
        self.assertEqual("System Design", item.section)
        self.assertEqual("добавь отдельный блок System Design: Transactional Outbox", item.raw_text)
        self.assertEqual([item], service.list_active())

    def test_delete_item_hides_it_from_active_list(self) -> None:
        agent = StubTopicAgent(
            SimpleNamespace(
                title="Transactional Outbox",
                section="System Design",
                summary="Нормализовано агентом.",
                provider="stub",
                model="stub-model",
            )
        )
        service = TopicInboxService(self.db, agent)
        item = service.create_item("System Design: Transactional Outbox", source="voice")

        deleted = service.delete_item(item.id)

        self.assertEqual(DELETED, deleted.status)
        self.assertEqual([], service.list_active())

    def test_create_item_falls_back_when_agent_fails(self) -> None:
        agent = StubTopicAgent(error=TopicInboxAgentError("agent unavailable"))
        service = TopicInboxService(self.db, agent)

        item = service.create_item("CAP теорема", source="text")

        self.assertEqual("CAP теорема", item.title)
        self.assertIn("Agent failed", item.agent_summary)
        self.assertEqual("stub", item.agent_provider)


if __name__ == "__main__":
    unittest.main()
