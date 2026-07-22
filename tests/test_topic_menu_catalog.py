from __future__ import annotations

import unittest

from app.adapters.telegram.bot import (
    TOPIC_BLOCK_PREFIX,
    _all_topics_by_section,
    _section_selection,
    _section_tree,
    _section_tree_keyboard,
    _section_tree_text,
    _section_topics,
    _topic_block_keyboard,
    _with_repo_sync_warning,
)
from app.core.repo import RepoPullResult, RepoTopic


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

    def test_section_tree_builds_nested_book_navigation(self) -> None:
        grouped = _all_topics_by_section(_Services())
        root = _section_tree(grouped)

        self.assertIn("Книги", root.children)
        self.assertIn("DDIA", root.children["Книги"].children)

        selection = _section_selection(grouped, "0.0")
        assert selection is not None
        node, _path = selection
        self.assertEqual(["db10"], [topic.id for topic in _section_topics(node)])

    def test_topic_root_keyboard_counts_books_not_book_topics(self) -> None:
        grouped = _all_topics_by_section(_Services())

        keyboard = _topic_block_keyboard(grouped)
        labels = [row[0].text for row in keyboard.inline_keyboard]

        self.assertIn("Книги (1)", labels)
        self.assertNotIn("Книги (1/1)", labels)
        self.assertNotIn("Книги / DDIA (1/1)", labels)

    def test_nested_keyboard_shows_book_children(self) -> None:
        grouped = _all_topics_by_section(_Services())
        keyboard = _section_tree_keyboard(
            grouped,
            path=(0,),
            callback_prefix=TOPIC_BLOCK_PREFIX,
            root_callback="topic_blocks",
            abort_callback="abort_topics",
        )

        labels = [row[0].text for row in keyboard.inline_keyboard]
        callbacks = [row[0].callback_data for row in keyboard.inline_keyboard]

        self.assertIn("DDIA (1/1)", labels)
        self.assertIn(f"{TOPIC_BLOCK_PREFIX}0.0", callbacks)

    def test_book_container_text_counts_books(self) -> None:
        grouped = _all_topics_by_section(_Services())

        text = _section_tree_text("Темы", grouped, path=(0,))

        self.assertIn("Книг: <b>1</b>", text)
        self.assertNotIn("Тем: <b>1</b>", text)

    def test_repo_sync_failure_warning_is_visible(self) -> None:
        text = _with_repo_sync_warning(
            "<b>Темы</b>",
            RepoPullResult("failed", "local changes would be overwritten"),
        )

        self.assertIn("Не удалось обновить lk-prep", text)
        self.assertIn("<b>Темы</b>", text)


if __name__ == "__main__":
    unittest.main()
