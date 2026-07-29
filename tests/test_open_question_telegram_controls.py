from __future__ import annotations

import unittest
from datetime import datetime

from app.adapters.telegram.bot import (
    HIDE_MESSAGE_PREFIX,
    OPEN_QUESTION_CANCEL_PREVIEW_PREFIX,
    OPEN_QUESTION_CONFIRM_PREFIX,
    OPEN_QUESTION_EDIT_PREFIX,
    _open_question_answer_preview_keyboard,
    _open_question_item_keyboard,
    _parse_open_question_preview_payload,
)
from app.features.open_questions.models import OpenQuestion


def _open_question(status: str = "answered") -> OpenQuestion:
    return OpenQuestion(
        id="oq1",
        topic_id="db05",
        topic_title="Модели данных",
        section="Базы данных",
        quiz_session_id="s1",
        origin="instant",
        status=status,
        question_kind="mini_case",
        question_text="Вопрос",
        answer_format_hint="",
        expected_points=[],
        rubric=[],
        source_refs=["database/review.md"],
        material_fingerprint="fp",
        material_snapshot={},
        generator_provider="fake",
        generator_model="fake",
        generate_prompt_version="fake",
        created_at=datetime(2026, 7, 14, 10, 0),
        updated_at=datetime(2026, 7, 14, 10, 0),
    )


class OpenQuestionTelegramControlsTest(unittest.TestCase):
    def test_answer_preview_keyboard_requires_explicit_confirmation(self) -> None:
        keyboard = _open_question_answer_preview_keyboard("draft1")

        rows = keyboard.inline_keyboard
        self.assertEqual("Отправить на проверку", rows[0][0].text)
        self.assertEqual(f"{OPEN_QUESTION_CONFIRM_PREFIX}draft1", rows[0][0].callback_data)
        self.assertEqual("Редактировать", rows[1][0].text)
        self.assertEqual(f"{OPEN_QUESTION_EDIT_PREFIX}draft1", rows[1][0].callback_data)
        self.assertEqual("Отменить", rows[2][0].text)
        self.assertEqual(
            f"{OPEN_QUESTION_CANCEL_PREVIEW_PREFIX}draft1",
            rows[2][0].callback_data,
        )

    def test_preview_payload_parser_reads_short_draft_id(self) -> None:
        question_id, draft_id = _parse_open_question_preview_payload(
            f"{OPEN_QUESTION_CONFIRM_PREFIX}draft1",
            OPEN_QUESTION_CONFIRM_PREFIX,
        )

        self.assertEqual("", question_id)
        self.assertEqual("draft1", draft_id)

    def test_preview_payload_parser_keeps_legacy_question_and_draft_ids(self) -> None:
        question_id, draft_id = _parse_open_question_preview_payload(
            f"{OPEN_QUESTION_CONFIRM_PREFIX}oq1:draft1",
            OPEN_QUESTION_CONFIRM_PREFIX,
        )

        self.assertEqual("oq1", question_id)
        self.assertEqual("draft1", draft_id)

    def test_open_question_item_keyboard_has_hide_button(self) -> None:
        keyboard = _open_question_item_keyboard(
            _open_question(),
            hide_callback_data=f"{HIDE_MESSAGE_PREFIX}group1",
        )

        button = keyboard.inline_keyboard[-1][0]
        self.assertEqual("Скрыть", button.text)
        self.assertEqual(f"{HIDE_MESSAGE_PREFIX}group1", button.callback_data)


if __name__ == "__main__":
    unittest.main()
