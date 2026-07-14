from __future__ import annotations

import unittest

from app.core.claude_cli import DISALLOWED_AGENT_TOOLS


class ClaudeCliToolPolicyTest(unittest.TestCase):
    def test_disallowed_tools_do_not_include_removed_claude_tools(self) -> None:
        tools = {
            item.strip()
            for item in DISALLOWED_AGENT_TOOLS.split(",")
            if item.strip()
        }

        self.assertNotIn("MultiEdit", tools)


if __name__ == "__main__":
    unittest.main()
