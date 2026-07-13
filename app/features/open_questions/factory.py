from __future__ import annotations

from app.config import Settings
from app.features.llm_usage.service import LlmUsageRecorder
from app.features.open_questions.agent import (
    ClaudeCliOpenQuestionAgent,
    FakeOpenQuestionAgent,
    OpenQuestionAgent,
)


def build_open_question_agent(
    settings: Settings,
    *,
    usage_recorder: LlmUsageRecorder | None = None,
) -> OpenQuestionAgent:
    provider = settings.open_question_agent_provider
    if provider in ("disabled", "fake"):
        return FakeOpenQuestionAgent()
    if provider in ("claude_cli", "claude"):
        return ClaudeCliOpenQuestionAgent(
            claude_bin=settings.claude_bin,
            oauth_token=settings.claude_code_oauth_token,
            model=settings.open_question_agent_model or settings.claude_model,
            timeout_seconds=settings.open_question_agent_timeout_seconds,
            allow_paid_api=settings.allow_paid_api,
            usage_recorder=usage_recorder,
        )
    raise RuntimeError(f"Unsupported OPEN_QUESTION_AGENT_PROVIDER: {provider}")
