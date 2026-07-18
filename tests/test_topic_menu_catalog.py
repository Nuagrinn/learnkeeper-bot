from __future__ import annotations

import unittest

from app.adapters.telegram.bot import _all_topics_by_section
from app.core.repo import RepoTopic


class _Repo:
    def list_topics(self):
        return [
            RepoTopic(
                id="bk01",
                title="Designing Data-Intensive Applications",
                status="planned",
                section="Книги",
                kind="book",
                trainable=False,
            ),
            RepoTopic(
                id="db10",
                title="Storage and Retrieval",
                status="ready",
                section="Книги / DDIA",
                kind="chapter",
                trainable=True,
                source_paths=["database/10-storage-retrieval/review.md"],
            ),
            RepoTopic(
                id="b03",
                title="Runtime Go",
                status="planned",
                section="Базовый Go",
                kind="topic",
                trainable=False,
            ),
            RepoTopic(
                id="loose-note",
                title="Loose note",
                status="unknown",
                section="notes",
                kind="discovered",
                trainable=False,
            ),
        ]


class _Services:
    repo = _Repo()


class TopicMenuCatalogTest(unittest.TestCase):
    def test_topic_menu_hides_navigation_nodes_but_keeps_planned_topics(self) -> None:
        grouped = _all_topics_by_section(_Services())

        self.assertNotIn("Книги", grouped)
        self.assertNotIn("notes", grouped)
        self.assertEqual(["db10"], [topic.id for topic in grouped["Книги / DDIA"]])
        self.assertEqual(["b03"], [topic.id for topic in grouped["Базовый Go"]])


if __name__ == "__main__":
    unittest.main()
