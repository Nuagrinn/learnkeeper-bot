from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from app.config import PROJECT_ROOT
from app.features.mistake_work.agent import (
    ClaudeCliMistakeReviewAgent,
    FakeMistakeReviewAgent,
    MistakeReviewInput,
)


def _request() -> MistakeReviewInput:
    return MistakeReviewInput(
        quiz_session_id="s1",
        topic_id="db01",
        topic_title="Индексы PostgreSQL",
        section="Базы данных",
        session_type="instant",
        score_percent=50,
        correct_count=1,
        total_count=2,
        mistakes=[
            {
                "question_no": 2,
                "question": "Как работает INCLUDE в PostgreSQL index?",
                "selected_label": "A",
                "selected_text": "Как часть ключа",
                "correct_label": "C",
                "correct_text": "Как покрывающая некластеризуемая колонка",
                "explanation": "INCLUDE хранится в leaf tuples и не участвует в сортировке.",
                "source_refs": ["db/indexes.md"],
            }
        ],
        material_context=[],
    )


class MistakeReviewAgentTest(unittest.TestCase):
    def test_fake_agent_returns_full_report(self) -> None:
        result = FakeMistakeReviewAgent().analyze(_request())

        self.assertEqual("fake", result.provider)
        self.assertEqual("normal", result.priority)
        self.assertIn("Индексы PostgreSQL", result.title)
        self.assertTrue(result.weak_concepts)
        self.assertTrue(result.questions_to_revisit)

    def test_claude_agent_parses_wrapper_output(self) -> None:
        calls = []

        def run_command(cmd, **kwargs):
            calls.append((cmd, kwargs))
            payload = {
                "title": "Разбор индексов PostgreSQL",
                "section": "Базы данных",
                "priority": "high",
                "summary": "Путается INCLUDE и ключ индекса.",
                "diagnosis": "Нужно доразобрать устройство B-tree leaf pages.",
                "weak_concepts": ["INCLUDE", "index-only scan"],
                "interview_review_suggestion": {
                    "title": "Индексы PostgreSQL: INCLUDE",
                    "target_section": "Базы данных",
                    "details": "Добавить материал про leaf tuples и visibility map.",
                },
                "questions_to_revisit": [
                    {
                        "question_no": 2,
                        "missed_point": "INCLUDE не часть ключа.",
                        "correct_idea": "INCLUDE колонки хранятся для покрытия запроса.",
                        "practice_prompt": "Объяснить index-only scan на примере.",
                    }
                ],
            }
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"result": json.dumps(payload)}, ensure_ascii=False),
                stderr="",
            )

        agent = ClaudeCliMistakeReviewAgent(
            claude_bin="claude",
            allow_paid_api=True,
            run_command=run_command,
        )

        result = agent.analyze(_request())

        self.assertEqual("high", result.priority)
        self.assertEqual("Разбор индексов PostgreSQL", result.title)
        self.assertEqual(str(PROJECT_ROOT), calls[0][1]["cwd"])
        self.assertIn("--json-schema", calls[0][0])
        self.assertIn("--permission-mode", calls[0][0])


if __name__ == "__main__":
    unittest.main()
