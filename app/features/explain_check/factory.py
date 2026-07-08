from __future__ import annotations

from app.config import Settings
from app.features.explain_check.agent import (
    ClaudeCliExplainCheckAgent,
    ExplainCheckAgent,
    FakeExplainCheckAgent,
)
from app.features.llm_usage.service import LlmUsageRecorder


def build_explain_check_agent(
    settings: Settings,
    *,
    usage_recorder: LlmUsageRecorder | None = None,
) -> ExplainCheckAgent:
    provider = settings.explain_check_agent_provider
    if provider in ("disabled", "fake"):
        return FakeExplainCheckAgent()
    if provider in ("claude_cli", "claude"):
        return ClaudeCliExplainCheckAgent(
            claude_bin=settings.claude_bin,
            oauth_token=settings.claude_code_oauth_token,
            model=settings.explain_check_agent_model or settings.claude_model,
            timeout_seconds=settings.explain_check_agent_timeout_seconds,
            allow_paid_api=settings.allow_paid_api,
            usage_recorder=usage_recorder,
        )
    raise RuntimeError(f"Unsupported EXPLAIN_CHECK_AGENT_PROVIDER: {provider}")
