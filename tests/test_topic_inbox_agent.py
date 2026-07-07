from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from app.core.claude_cli import sandbox_cwd
from app.features.topic_inbox.agent import (
    ClaudeCliTopicInboxAgent,
    FakeTopicInboxAgent,
)


class TopicInboxAgentTest(unittest.TestCase):
    def test_fake_agent_extracts_explicit_section(self) -> None:
        agent = FakeTopicInboxAgent()

        result = agent.normalize(
            "добавь отдельный блок System Design: Transactional Outbox"
        )

        self.assertEqual("Transactional Outbox", result.title)
        self.assertEqual("System Design", result.section)

    def test_claude_agent_parses_wrapper_output(self) -> None:
        calls = []

        def run_command(cmd, **kwargs):
            calls.append((cmd, kwargs))
            payload = {
                "title": "System Design: Transactional Outbox",
                "section": "System Design",
                "summary": "Нормализовано.",
            }
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"result": json.dumps(payload)}, ensure_ascii=False),
                stderr="",
            )

        agent = ClaudeCliTopicInboxAgent(
            claude_bin="claude",
            allow_paid_api=True,
            run_command=run_command,
        )

        result = agent.normalize("добавь блок System Design: Transactional Outbox")

        self.assertEqual("Transactional Outbox", result.title)
        self.assertEqual("System Design", result.section)
        self.assertEqual(sandbox_cwd(), calls[0][1]["cwd"])
        self.assertIn("--output-format", calls[0][0])
        self.assertNotIn("--permission-mode", calls[0][0])
        self.assertIn("--disallowedTools", calls[0][0])

    def test_claude_agent_keeps_broad_idea_and_strips_meta_prefix(self) -> None:
        def run_command(cmd, **kwargs):
            payload = {
                "title": "Нормализация темы: Изучить rate limiter как паттерн отказоустойчивости",
                "section": "inbox",
                "summary": "Разобрать назначение, алгоритмы и сценарии применения rate limiter.",
            }
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"result": json.dumps(payload, ensure_ascii=False)}, ensure_ascii=False),
                stderr="",
            )

        agent = ClaudeCliTopicInboxAgent(
            claude_bin="claude",
            allow_paid_api=True,
            run_command=run_command,
        )

        result = agent.normalize("Патерна отказа устойчивости рейт-лиметр")

        self.assertEqual("Изучить rate limiter как паттерн отказоустойчивости", result.title)
        self.assertEqual("", result.section)


if __name__ == "__main__":
    unittest.main()
