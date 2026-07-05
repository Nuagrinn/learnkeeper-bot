from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from app.config import PROJECT_ROOT
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
        self.assertEqual(str(PROJECT_ROOT), calls[0][1]["cwd"])
        self.assertIn("--output-format", calls[0][0])
        self.assertNotIn("--permission-mode", calls[0][0])


if __name__ == "__main__":
    unittest.main()
