from __future__ import annotations

import json
import os
import subprocess
import unittest

from app.core.repo import RepoTopic, TopicMaterial, TopicMaterials
from app.features.quiz.generator import ClaudeCliQuizGenerator, QuizGenerationError


class RecordingRunner:
    def __init__(self, stdout: str):
        self.stdout = stdout
        self.calls: list[dict[str, object]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, 0, stdout=self.stdout, stderr="")


class RecordingUsageRecorder:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def record(self, **kwargs):
        self.calls.append(kwargs)
        return None


class ClaudeCliQuizGeneratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.topic = RepoTopic(
            id="go1",
            title="Слайсы в Go",
            source_paths=["base-go/slices.md"],
        )
        self.materials = TopicMaterials(
            topic=self.topic,
            files=[
                TopicMaterial(
                    source_path="base-go/slices.md",
                    content="# Слайсы\n\nlen, cap, append.",
                )
            ],
            fingerprint="abc",
        )

    def test_generates_questions_and_strips_paid_api_env(self) -> None:
        payload = {
            "questions": [
                {
                    "text": "Что возвращает len(slice)?",
                    "options": ["Длину", "Емкость", "Адрес", "Тип"],
                    "correct_index": 0,
                    "explanation": "len возвращает текущую длину слайса.",
                    "source_refs": ["base-go/slices.md"],
                }
            ]
        }
        runner = RecordingRunner(json.dumps(payload, ensure_ascii=False))
        old_key = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = "paid-api-key"
        try:
            generator = ClaudeCliQuizGenerator(
                oauth_token="oauth-token",
                run_command=runner,
                allow_paid_api=False,
            )

            questions = generator.generate(
                topic=self.topic,
                materials=self.materials,
                question_count=1,
            )
        finally:
            if old_key is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = old_key

        self.assertEqual("Что возвращает len(slice)?", questions[0].text)
        self.assertEqual(["base-go/slices.md"], questions[0].source_refs)
        call = runner.calls[0]
        self.assertEqual("--print", call["cmd"][1])
        self.assertIn("--append-system-prompt", call["cmd"])
        self.assertIn("--output-format", call["cmd"])
        self.assertIn("--json-schema", call["cmd"])
        self.assertIn("--no-session-persistence", call["cmd"])
        self.assertNotIn("--permission-mode", call["cmd"])
        self.assertNotIn("--disallowedTools", call["cmd"])
        self.assertIn("Сгенерируй тест", call["input"])
        self.assertIn("len, cap, append", call["input"])
        env = call["env"]
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual("oauth-token", env["CLAUDE_CODE_OAUTH_TOKEN"])

    def test_parses_claude_json_output_wrapper(self) -> None:
        payload = {
            "questions": [
                {
                    "text": "Что возвращает len(slice)?",
                    "options": ["Длину", "Емкость", "Адрес", "Тип"],
                    "correct_index": 0,
                    "explanation": "len возвращает текущую длину слайса.",
                    "source_refs": ["base-go/slices.md"],
                }
            ]
        }
        wrapper = {
            "type": "result",
            "subtype": "success",
            "result": json.dumps(payload, ensure_ascii=False),
        }
        generator = ClaudeCliQuizGenerator(
            oauth_token="oauth-token",
            run_command=RecordingRunner(json.dumps(wrapper, ensure_ascii=False)),
            allow_paid_api=False,
        )

        questions = generator.generate(
            topic=self.topic,
            materials=self.materials,
            question_count=1,
        )

        self.assertEqual("Что возвращает len(slice)?", questions[0].text)

    def test_records_claude_cli_reported_usage(self) -> None:
        payload = {
            "questions": [
                {
                    "text": "Что возвращает len(slice)?",
                    "options": ["Длину", "Емкость", "Адрес", "Тип"],
                    "correct_index": 0,
                    "explanation": "len возвращает текущую длину слайса.",
                    "source_refs": ["base-go/slices.md"],
                }
            ]
        }
        wrapper = {
            "type": "result",
            "subtype": "success",
            "result": json.dumps(payload, ensure_ascii=False),
            "total_cost_usd": 0.4691918,
            "duration_ms": 106346,
            "duration_api_ms": 108185,
            "usage": {
                "input_tokens": 7,
                "cache_creation_input_tokens": 45341,
                "cache_read_input_tokens": 106656,
                "output_tokens": 9937,
                "service_tier": "standard",
            },
        }
        usage_recorder = RecordingUsageRecorder()
        generator = ClaudeCliQuizGenerator(
            oauth_token="oauth-token",
            run_command=RecordingRunner(json.dumps(wrapper, ensure_ascii=False)),
            allow_paid_api=False,
            usage_recorder=usage_recorder,
        )

        generator.generate(
            topic=self.topic,
            materials=self.materials,
            question_count=1,
        )

        call = usage_recorder.calls[0]
        self.assertEqual("claude_cli_reported", call["usage_source"])
        self.assertEqual(152004, call["input_tokens"])
        self.assertEqual(9937, call["output_tokens"])
        self.assertEqual(161941, call["total_tokens"])
        self.assertEqual(0.4691918, call["estimated_usd"])
        metadata = call["metadata"]
        self.assertEqual(45341, metadata["claude_cache_creation_input_tokens"])
        self.assertEqual("standard", metadata["claude_service_tier"])

    def test_parses_claude_content_list_wrapper(self) -> None:
        payload = {
            "questions": [
                {
                    "text": "Что делает append?",
                    "options": ["Добавляет", "Удаляет", "Сортирует", "Блокирует"],
                    "correct_index": 0,
                    "explanation": "append добавляет элементы в слайс.",
                    "source_refs": ["base-go/slices.md"],
                }
            ]
        }
        wrapper = {
            "content": [
                {"type": "text", "text": json.dumps(payload, ensure_ascii=False)}
            ]
        }
        generator = ClaudeCliQuizGenerator(
            oauth_token="oauth-token",
            run_command=RecordingRunner(json.dumps(wrapper, ensure_ascii=False)),
            allow_paid_api=False,
        )

        questions = generator.generate(
            topic=self.topic,
            materials=self.materials,
            question_count=1,
        )

        self.assertEqual("Что делает append?", questions[0].text)

    def test_reports_structured_output_denial(self) -> None:
        wrapper = {
            "type": "result",
            "subtype": "success",
            "result": (
                "The tool call was denied. I'm currently restricted to plan mode, "
                "which blocks non-plan tool calls including `StructuredOutput`."
            ),
        }
        generator = ClaudeCliQuizGenerator(
            oauth_token="oauth-token",
            run_command=RecordingRunner(json.dumps(wrapper, ensure_ascii=False)),
            allow_paid_api=False,
        )

        with self.assertRaisesRegex(QuizGenerationError, "StructuredOutput was denied"):
            generator.generate(
                topic=self.topic,
                materials=self.materials,
                question_count=1,
            )

    def test_requires_oauth_token_when_paid_api_is_disabled(self) -> None:
        generator = ClaudeCliQuizGenerator(
            oauth_token="",
            run_command=RecordingRunner("{}"),
            allow_paid_api=False,
        )

        with self.assertRaises(QuizGenerationError):
            generator.generate(
                topic=self.topic,
                materials=self.materials,
                question_count=1,
            )

    def test_rejects_source_refs_outside_topic_materials(self) -> None:
        payload = {
            "questions": [
                {
                    "text": "Что возвращает len(slice)?",
                    "options": ["Длину", "Емкость", "Адрес", "Тип"],
                    "correct_index": 0,
                    "explanation": "len возвращает текущую длину слайса.",
                    "source_refs": ["other.md"],
                }
            ]
        }
        generator = ClaudeCliQuizGenerator(
            oauth_token="oauth-token",
            run_command=RecordingRunner(json.dumps(payload, ensure_ascii=False)),
            allow_paid_api=False,
        )

        with self.assertRaises(QuizGenerationError):
            generator.generate(
                topic=self.topic,
                materials=self.materials,
                question_count=1,
            )


if __name__ == "__main__":
    unittest.main()
