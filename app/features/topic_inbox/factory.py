from __future__ import annotations

from app.config import Settings
from app.features.llm_usage.service import LlmUsageRecorder
from app.features.topic_inbox.agent import (
    ClaudeCliTopicInboxAgent,
    FakeTopicInboxAgent,
    TopicInboxAgent,
)


def build_topic_inbox_agent(
    settings: Settings,
    *,
    usage_recorder: LlmUsageRecorder | None = None,
) -> TopicInboxAgent:
    provider = settings.topic_inbox_agent_provider
    if provider in ("disabled", "fake"):
        return FakeTopicInboxAgent()
    if provider in ("claude_cli", "claude"):
        return ClaudeCliTopicInboxAgent(
            claude_bin=settings.claude_bin,
            oauth_token=settings.claude_code_oauth_token,
            model=settings.topic_inbox_agent_model or settings.claude_model,
            timeout_seconds=settings.topic_inbox_agent_timeout_seconds,
            allow_paid_api=settings.allow_paid_api,
            usage_recorder=usage_recorder,
        )
    raise RuntimeError(f"Unsupported TOPIC_INBOX_AGENT_PROVIDER: {provider}")
