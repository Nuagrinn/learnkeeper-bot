from __future__ import annotations

from app.config import PROJECT_ROOT, Settings
from app.features.llm_usage.service import LlmUsageRecorder
from app.features.quiz.generator import ClaudeCliQuizGenerator, FakeQuizGenerator, QuizGenerator


def build_quiz_generator(
    settings: Settings,
    *,
    usage_recorder: LlmUsageRecorder | None = None,
) -> QuizGenerator:
    if settings.llm_provider == "fake":
        return FakeQuizGenerator()
    if settings.llm_provider == "claude_cli":
        return ClaudeCliQuizGenerator(
            claude_bin=settings.claude_bin,
            oauth_token=settings.claude_code_oauth_token,
            model=settings.claude_model,
            timeout_seconds=settings.claude_timeout_seconds,
            allow_paid_api=settings.allow_paid_api,
            cwd=PROJECT_ROOT,
            usage_recorder=usage_recorder,
        )
    raise RuntimeError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
