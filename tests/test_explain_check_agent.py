from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from app.core.claude_cli import sandbox_cwd
from app.features.explain_check.agent import (
    ClaudeCliExplainCheckAgent,
    ExplainCheckAgentError,
    ExplainCheckInput,
    FakeExplainCheckAgent,
)


class RecordingUsageRecorder:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def record(self, **kwargs):
        self.calls.append(kwargs)
        return None


def _request(explanation: str = "Строки в Go неизменяемы, байты нельзя менять напрямую.") -> ExplainCheckInput:
    return ExplainCheckInput(
        topic_id="b08",
        topic_title="Строки в Go",
        section="Базовый Go",
        source="text",
        explanation_text=explanation,
        material_context=[
            {"source_path": "base-go/08-strings/review.md", "excerpt": "string is immutable in Go."}
        ],
    )


class FakeExplainCheckAgentTest(unittest.TestCase):
    def test_short_explanation_gets_layer_one(self) -> None:
        result = FakeExplainCheckAgent().check(_request("не помню"))

        self.assertEqual("fake", result.provider)
        self.assertEqual(1, result.layer_reached)
        self.assertEqual("normal", result.priority)

    def test_longer_explanation_gets_layer_two(self) -> None:
        explanation = (
            "Строки в Go неизменяемы, потому что рантайм может их безопасно шарить "
            "между разными частями программы без лишних копий данных"
        )
        result = FakeExplainCheckAgent().check(_request(explanation))

        self.assertEqual(2, result.layer_reached)


class ClaudeCliExplainCheckAgentTest(unittest.TestCase):
    def test_claude_agent_parses_wrapper_output(self) -> None:
        calls = []

        def run_command(cmd, **kwargs):
            calls.append((cmd, kwargs))
            payload = {
                "layer_reached": 3,
                "priority": "low",
                "summary": "Точно объяснил immutability и привел пример.",
                "covered_concepts": ["string immutable", "[]byte copy on conversion"],
                "missing_concepts": ["rune vs byte в range"],
                "false_models": [
                    {
                        "false_model": "len(string) считает символы",
                        "correct_model": "len(string) считает байты UTF-8",
                    }
                ],
                "follow_up_question": "Что выведет len(\"привет\")?",
            }
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "result": json.dumps(payload, ensure_ascii=False),
                        "total_cost_usd": 0.2211,
                        "usage": {
                            "input_tokens": 5,
                            "cache_creation_input_tokens": 15,
                            "cache_read_input_tokens": 0,
                            "output_tokens": 25,
                            "service_tier": "standard",
                        },
                    },
                    ensure_ascii=False,
                ),
                stderr="",
            )

        usage_recorder = RecordingUsageRecorder()
        agent = ClaudeCliExplainCheckAgent(
            claude_bin="claude",
            allow_paid_api=True,
            run_command=run_command,
            usage_recorder=usage_recorder,
        )

        result = agent.check(_request())

        self.assertEqual(3, result.layer_reached)
        self.assertEqual("low", result.priority)
        self.assertEqual(1, len(result.false_models))
        self.assertEqual("len(string) считает символы", result.false_models[0]["false_model"])
        self.assertEqual(sandbox_cwd(), calls[0][1]["cwd"])
        self.assertIn("--json-schema", calls[0][0])
        self.assertNotIn("--permission-mode", calls[0][0])
        self.assertIn("--disallowedTools", calls[0][0])
        usage_call = usage_recorder.calls[0]
        self.assertEqual("explain_check_analysis", usage_call["feature"])
        self.assertEqual("claude_cli_reported", usage_call["usage_source"])
        self.assertEqual(20, usage_call["input_tokens"])
        self.assertEqual(25, usage_call["output_tokens"])
        self.assertEqual(0.2211, usage_call["estimated_usd"])

    def test_clamps_out_of_range_layer(self) -> None:
        def run_command(cmd, **kwargs):
            payload = {
                "layer_reached": 9,
                "priority": "unknown-value",
                "summary": "x",
                "covered_concepts": [],
                "missing_concepts": [],
                "false_models": [],
                "follow_up_question": "",
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        agent = ClaudeCliExplainCheckAgent(
            claude_bin="claude", allow_paid_api=True, run_command=run_command,
        )

        result = agent.check(_request())

        self.assertEqual(4, result.layer_reached)
        self.assertEqual("normal", result.priority)

    def test_requires_oauth_token_when_paid_api_disabled(self) -> None:
        agent = ClaudeCliExplainCheckAgent(
            oauth_token="",
            run_command=lambda *a, **k: SimpleNamespace(returncode=0, stdout="{}", stderr=""),
            allow_paid_api=False,
        )

        with self.assertRaises(ExplainCheckAgentError):
            agent.check(_request())


if __name__ == "__main__":
    unittest.main()
