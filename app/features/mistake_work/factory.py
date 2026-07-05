from __future__ import annotations

from app.config import Settings
from app.features.llm_usage.service import LlmUsageRecorder
from app.features.mistake_work.agent import (
    ClaudeCliMistakeReviewAgent,
    FakeMistakeReviewAgent,
    MistakeReviewAgent,
)


def build_mistake_review_agent(
    settings: Settings,
    *,
    usage_recorder: LlmUsageRecorder | None = None,
) -> MistakeReviewAgent:
    provider = settings.mistake_review_agent_provider
    if provider in ("disabled", "fake"):
        return FakeMistakeReviewAgent()
    if provider in ("claude_cli", "claude"):
        return ClaudeCliMistakeReviewAgent(
            claude_bin=settings.claude_bin,
            oauth_token=settings.claude_code_oauth_token,
            model=settings.mistake_review_agent_model or settings.claude_model,
            timeout_seconds=settings.mistake_review_agent_timeout_seconds,
            allow_paid_api=settings.allow_paid_api,
            usage_recorder=usage_recorder,
        )
    raise RuntimeError(f"Unsupported MISTAKE_REVIEW_AGENT_PROVIDER: {provider}")
