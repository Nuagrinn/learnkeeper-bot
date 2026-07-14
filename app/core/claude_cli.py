from __future__ import annotations

import tempfile
from pathlib import Path


# Tools Claude Code could use to explore the filesystem or run code. We deny them
# so quiz/mistake/inbox generation stays a single-shot structured-output call
# instead of an agentic loop that reads repo files and explodes token usage.
#
# StructuredOutput (used by --json-schema) is intentionally NOT listed, so it stays
# available. A bare "*" would also block StructuredOutput and break generation on
# some models (verified: haiku returns a permission error), so we name tools
# explicitly instead.
DISALLOWED_AGENT_TOOLS = (
    "Bash,Read,Edit,Write,Glob,Grep,WebFetch,WebSearch,"
    "Task,NotebookEdit,TodoWrite,BashOutput,KillShell"
)


_SANDBOX_CWD: Path | None = None


def sandbox_cwd() -> str:
    """Return a stable empty directory to run the Claude CLI in.

    Running in an empty dir means the agent has no repo files to explore and does
    not auto-load a CLAUDE.md into context, which keeps token usage predictable.
    """
    global _SANDBOX_CWD
    if _SANDBOX_CWD is None or not _SANDBOX_CWD.is_dir():
        _SANDBOX_CWD = Path(tempfile.mkdtemp(prefix="learnkeeper-agent-cwd-"))
    return str(_SANDBOX_CWD)
