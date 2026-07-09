from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime

from app.adapters.telegram.bot import (
    _daily_quiz_offer_detail_text,
    _daily_quiz_outstanding_keyboard,
    _daily_quiz_outstanding_text,
)


@dataclass(frozen=True)
class _FakeOffer:
    id: str
    offer_date: str
    topic_id: str
    topic_title: str
    section: str
    status: str
    created_at: datetime
    updated_at: datetime


def _offer(**overrides) -> _FakeOffer:
    defaults = dict(
        id="abc123",
        offer_date="2026-07-09",
        topic_id="b01",
        topic_title="Слайсы и массивы",
        section="Базовый Go",
        status="pending",
        created_at=datetime(2026, 7, 9, 10, 20),
        updated_at=datetime(2026, 7, 9, 10, 20),
    )
    defaults.update(overrides)
    return _FakeOffer(**defaults)


class DailyQuizOfferTextsTest(unittest.TestCase):
    def test_detail_text_shows_human_status_label(self) -> None:
        text = _daily_quiz_offer_detail_text(_offer(status="started"))

        self.assertIn("Слайсы и массивы", text)
        self.assertIn("начат, не завершен", text)
        self.assertIn("2026-07-09", text)

    def test_outstanding_text_reports_empty_state(self) -> None:
        text = _daily_quiz_outstanding_text([])

        self.assertIn("Пусто", text)

    def test_outstanding_text_counts_offers(self) -> None:
        text = _daily_quiz_outstanding_text([_offer(), _offer(id="def456")])

        self.assertIn("Всего: <b>2</b>", text)

    def test_outstanding_keyboard_has_one_button_per_offer_plus_back(self) -> None:
        offers = [_offer(id="a"), _offer(id="b", status="postponed")]

        keyboard = _daily_quiz_outstanding_keyboard(offers)

        self.assertEqual(3, len(keyboard.inline_keyboard))
        self.assertIn("daily_quiz_open:a", keyboard.inline_keyboard[0][0].callback_data)
        self.assertIn("daily_quiz_open:b", keyboard.inline_keyboard[1][0].callback_data)
        self.assertEqual("menu_daily_settings", keyboard.inline_keyboard[2][0].callback_data)


if __name__ == "__main__":
    unittest.main()
