from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime

from app.adapters.telegram.bot import START_REVIEW_PREFIX, _due_tasks_keyboard


@dataclass(frozen=True)
class _FakeTask:
    id: str
    topic_title: str
    stage: int
    due_at: datetime


class DueTasksKeyboardTest(unittest.TestCase):
    def test_one_start_button_per_task(self) -> None:
        tasks = [
            _FakeTask(id="t1", topic_title="Слайсы", stage=1, due_at=datetime(2026, 7, 9)),
            _FakeTask(id="t2", topic_title="Мапы", stage=2, due_at=datetime(2026, 7, 8)),
        ]

        keyboard = _due_tasks_keyboard(tasks)

        self.assertEqual(2, len(keyboard.inline_keyboard))
        self.assertEqual(
            f"{START_REVIEW_PREFIX}t1",
            keyboard.inline_keyboard[0][0].callback_data,
        )
        self.assertEqual(
            f"{START_REVIEW_PREFIX}t2",
            keyboard.inline_keyboard[1][0].callback_data,
        )
        self.assertIn("Слайсы", keyboard.inline_keyboard[0][0].text)


if __name__ == "__main__":
    unittest.main()
