from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from app.features.open_questions.agent import (
    ClaudeCliOpenQuestionAgent,
    OpenQuestionCheckInput,
    OpenQuestionGenerationInput,
)


class RecordingUsageRecorder:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def record(self, **kwargs):
        self.calls.append(kwargs)
        return None


def _generation_request() -> OpenQuestionGenerationInput:
    return OpenQuestionGenerationInput(
        topic_id="db05",
        topic_title="Модели данных",
        section="Базы данных",
        origin="instant",
        material_context=[
            {
                "source_path": "database/review.md",
                "excerpt": "Document, relational and graph models.",
                "challenge_helper": "Дай мини-кейс на выбор модели данных.",
            }
        ],
    )


def _check_request() -> OpenQuestionCheckInput:
    return OpenQuestionCheckInput(
        open_question_id="q1",
        topic_id="db05",
        topic_title="Модели данных",
        section="Базы данных",
        question_kind="mini_case",
        question_text="Выбери модель данных.",
        answer_format_hint="Кратко.",
        expected_points=["workload fit"],
        rubric=[{"criterion": "trade-off", "weight": 3}],
        source_refs=["database/review.md"],
        answer_text="A hybrid design fits different workloads.",
        answer_source="text",
        material_context=[],
    )


class ClaudeCliOpenQuestionAgentTest(unittest.TestCase):
    def test_generation_repairs_markdown_json_without_source_refs(self) -> None:
        def run_command(cmd, **kwargs):
            payload = {
                "question_kind": "mini_case",
                "question": "Мини-кейс?",
                "answer_format_hint": "Ответь кратко.",
                "expected_points": ["workload fit"],
                "rubric": [{"criterion": "trade-off", "weight": 3}],
            }
            return SimpleNamespace(
                returncode=0,
                stdout="```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```",
                stderr="",
            )

        agent = ClaudeCliOpenQuestionAgent(allow_paid_api=True, run_command=run_command)

        result = agent.generate(_generation_request())

        self.assertEqual("mini_case", result.question_kind)
        self.assertEqual(["database/review.md"], result.source_refs)

    def test_check_accepts_score_ratio_string(self) -> None:
        def run_command(cmd, **kwargs):
            payload = {
                "score": "7.5/10",
                "summary": "Хороший ответ.",
                "strong_points": ["есть trade-off"],
                "missing_points": [],
                "false_models": [],
                "better_answer": "Сильный ответ.",
                "next_drill": "Еще один кейс.",
            }
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(payload, ensure_ascii=False),
                stderr="",
            )

        usage_recorder = RecordingUsageRecorder()
        agent = ClaudeCliOpenQuestionAgent(
            allow_paid_api=True,
            run_command=run_command,
            usage_recorder=usage_recorder,
        )

        result = agent.check(_check_request())

        self.assertEqual(75.0, result.score_percent)
        self.assertEqual(3, result.layer_reached)
        self.assertEqual("open_question_check", usage_recorder.calls[0]["feature"])


if __name__ == "__main__":
    unittest.main()
