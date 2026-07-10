from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _resolve_path(value: str, *, default: Path) -> Path:
    if not value:
        return default
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


@dataclass(frozen=True)
class Settings:
    db_path: Path
    lk_prep_path: Path | None
    telegram_bot_token: str
    tg_user_id: int | None
    telegram_api_id: int | None
    telegram_api_hash: str
    telegram_mtproto_session: Path
    review_tick_seconds: int
    quiz_question_count: int
    daily_quiz_hour: int
    daily_quiz_minute: int
    daily_quiz_timezone: str
    coding_reps_hour: int
    coding_reps_minute: int
    llm_provider: str
    claude_bin: str
    claude_code_oauth_token: str
    claude_model: str
    claude_timeout_seconds: int
    allow_paid_api: bool
    llm_input_usd_per_1m_tokens: float
    llm_output_usd_per_1m_tokens: float
    llm_usage_budget_5h_usd: float
    llm_usage_budget_daily_usd: float
    llm_usage_budget_weekly_usd: float
    llm_usage_budget_monthly_usd: float
    llm_usage_budget_5h_tokens: int
    llm_usage_budget_daily_tokens: int
    llm_usage_budget_weekly_tokens: int
    llm_usage_budget_monthly_tokens: int
    stt_provider: str
    voice_dir: Path
    openai_api_key: str
    stt_openai_model: str
    stt_language: str
    stt_prompt: str
    stt_timeout_seconds: int
    stt_whisper_bin: str
    stt_whisper_model: str
    stt_whisper_cpp_bin: str
    stt_whisper_cpp_model: Path
    ffmpeg_bin: str
    repo_git_remote: str
    repo_git_branch: str
    repo_pull_before_quiz: bool
    repo_pull_before_read: bool
    repo_pull_timeout_seconds: int
    materials_github_base_url: str
    topic_inbox_agent_provider: str
    topic_inbox_agent_model: str
    topic_inbox_agent_timeout_seconds: int
    mistake_review_agent_provider: str
    mistake_review_agent_model: str
    mistake_review_agent_timeout_seconds: int
    explain_check_agent_provider: str
    explain_check_agent_model: str
    explain_check_agent_timeout_seconds: int


def load_settings(db_path: str | None = None, repo_path: str | None = None) -> Settings:
    env_file = _load_env_file(PROJECT_ROOT / ".env")

    raw_db = db_path or os.getenv("DB_PATH") or env_file.get("DB_PATH", "")
    resolved_db = _resolve_path(
        raw_db,
        default=PROJECT_ROOT / "data" / "learnkeeper.sqlite3",
    )

    raw_repo = (
        repo_path
        or os.getenv("LK_PREP_PATH")
        or env_file.get("LK_PREP_PATH", "")
    )
    lk_prep_path = _resolve_path(raw_repo, default=Path()) if raw_repo else None

    raw_token = os.getenv("TELEGRAM_BOT_TOKEN") or env_file.get("TELEGRAM_BOT_TOKEN", "")
    raw_user_id = os.getenv("TG_USER_ID") or env_file.get("TG_USER_ID", "")
    tg_user_id = int(raw_user_id) if raw_user_id.isdigit() else None
    raw_api_id = os.getenv("TELEGRAM_API_ID") or env_file.get("TELEGRAM_API_ID", "")
    telegram_api_id = int(raw_api_id) if raw_api_id.isdigit() else None
    telegram_api_hash = (
        os.getenv("TELEGRAM_API_HASH") or env_file.get("TELEGRAM_API_HASH", "")
    ).strip()
    raw_mtproto_session = (
        os.getenv("TELEGRAM_MTPROTO_SESSION")
        or env_file.get("TELEGRAM_MTPROTO_SESSION", "")
    )
    telegram_mtproto_session = _resolve_path(
        raw_mtproto_session,
        default=PROJECT_ROOT / "data" / "telegram-mtproto",
    )
    raw_tick = os.getenv("REVIEW_TICK_SECONDS") or env_file.get("REVIEW_TICK_SECONDS", "60")
    try:
        review_tick_seconds = max(10, int(raw_tick))
    except ValueError:
        review_tick_seconds = 60
    raw_quiz_count = os.getenv("QUIZ_QUESTION_COUNT") or env_file.get(
        "QUIZ_QUESTION_COUNT",
        "5",
    )
    try:
        quiz_question_count = min(40, max(1, int(raw_quiz_count)))
    except ValueError:
        quiz_question_count = 5
    daily_quiz_time = (
        os.getenv("DAILY_QUIZ_TIME")
        or env_file.get("DAILY_QUIZ_TIME", "10:20")
    ).strip()
    daily_quiz_hour, daily_quiz_minute = _parse_hhmm(daily_quiz_time, default=(10, 20))
    daily_quiz_timezone = (
        os.getenv("DAILY_QUIZ_TIMEZONE")
        or env_file.get("DAILY_QUIZ_TIMEZONE", "Europe/Moscow")
    ).strip() or "Europe/Moscow"
    coding_reps_time = (
        os.getenv("CODING_REPS_TIME")
        or env_file.get("CODING_REPS_TIME", "19:30")
    ).strip()
    coding_reps_hour, coding_reps_minute = _parse_hhmm(coding_reps_time, default=(19, 30))
    llm_provider = (
        os.getenv("LLM_PROVIDER") or env_file.get("LLM_PROVIDER", "fake")
    ).strip().lower()
    claude_bin = (os.getenv("CLAUDE_BIN") or env_file.get("CLAUDE_BIN", "claude")).strip()
    claude_code_oauth_token = (
        os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
        or env_file.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    ).strip()
    claude_model = (
        os.getenv("CLAUDE_MODEL") or env_file.get("CLAUDE_MODEL", "")
    ).strip()
    raw_claude_timeout = os.getenv("CLAUDE_TIMEOUT_SECONDS") or env_file.get(
        "CLAUDE_TIMEOUT_SECONDS",
        "600",
    )
    try:
        claude_timeout_seconds = max(30, int(raw_claude_timeout))
    except ValueError:
        claude_timeout_seconds = 600
    raw_allow_paid = (
        os.getenv("ALLOW_PAID_API") or env_file.get("ALLOW_PAID_API", "false")
    ).strip().lower()
    allow_paid_api = raw_allow_paid in ("1", "true", "yes", "on")
    llm_input_usd_per_1m_tokens = _env_float(
        os.getenv("LLM_INPUT_USD_PER_1M_TOKENS")
        or env_file.get("LLM_INPUT_USD_PER_1M_TOKENS", "0")
    )
    llm_output_usd_per_1m_tokens = _env_float(
        os.getenv("LLM_OUTPUT_USD_PER_1M_TOKENS")
        or env_file.get("LLM_OUTPUT_USD_PER_1M_TOKENS", "0")
    )
    llm_usage_budget_5h_usd = _env_float(
        os.getenv("LLM_USAGE_BUDGET_5H_USD")
        or env_file.get("LLM_USAGE_BUDGET_5H_USD", "0")
    )
    llm_usage_budget_daily_usd = _env_float(
        os.getenv("LLM_USAGE_BUDGET_DAILY_USD")
        or env_file.get("LLM_USAGE_BUDGET_DAILY_USD", "0")
    )
    llm_usage_budget_weekly_usd = _env_float(
        os.getenv("LLM_USAGE_BUDGET_WEEKLY_USD")
        or env_file.get("LLM_USAGE_BUDGET_WEEKLY_USD", "0")
    )
    llm_usage_budget_monthly_usd = _env_float(
        os.getenv("LLM_USAGE_BUDGET_MONTHLY_USD")
        or env_file.get("LLM_USAGE_BUDGET_MONTHLY_USD", "0")
    )
    llm_usage_budget_5h_tokens = _env_int(
        os.getenv("LLM_USAGE_BUDGET_5H_TOKENS")
        or env_file.get("LLM_USAGE_BUDGET_5H_TOKENS", "1000000")
    )
    llm_usage_budget_daily_tokens = _env_int(
        os.getenv("LLM_USAGE_BUDGET_DAILY_TOKENS")
        or env_file.get("LLM_USAGE_BUDGET_DAILY_TOKENS", "2500000")
    )
    llm_usage_budget_weekly_tokens = _env_int(
        os.getenv("LLM_USAGE_BUDGET_WEEKLY_TOKENS")
        or env_file.get("LLM_USAGE_BUDGET_WEEKLY_TOKENS", "12000000")
    )
    llm_usage_budget_monthly_tokens = _env_int(
        os.getenv("LLM_USAGE_BUDGET_MONTHLY_TOKENS")
        or env_file.get("LLM_USAGE_BUDGET_MONTHLY_TOKENS", "45000000")
    )
    stt_provider = (
        os.getenv("STT_PROVIDER") or env_file.get("STT_PROVIDER", "disabled")
    ).strip().lower()
    raw_voice_dir = os.getenv("VOICE_DIR") or env_file.get("VOICE_DIR", "")
    voice_dir = _resolve_path(raw_voice_dir, default=PROJECT_ROOT / "data" / "voice")
    openai_api_key = (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("STT_OPENAI_API_KEY")
        or env_file.get("OPENAI_API_KEY", "")
        or env_file.get("STT_OPENAI_API_KEY", "")
    ).strip()
    stt_openai_model = (
        os.getenv("STT_OPENAI_MODEL")
        or env_file.get("STT_OPENAI_MODEL", "gpt-4o-transcribe")
    ).strip()
    stt_language = (os.getenv("STT_LANGUAGE") or env_file.get("STT_LANGUAGE", "ru")).strip()
    stt_prompt = (
        os.getenv("STT_PROMPT")
        or env_file.get(
            "STT_PROMPT",
            "Go, Golang, goroutine, mutex, channel, context, runtime, слайсы, мапы",
        )
    ).strip()
    raw_stt_timeout = os.getenv("STT_TIMEOUT_SECONDS") or env_file.get(
        "STT_TIMEOUT_SECONDS",
        "180",
    )
    try:
        stt_timeout_seconds = max(10, int(raw_stt_timeout))
    except ValueError:
        stt_timeout_seconds = 180
    stt_whisper_bin = (
        os.getenv("STT_WHISPER_BIN") or env_file.get("STT_WHISPER_BIN", "whisper")
    ).strip()
    stt_whisper_model = (
        os.getenv("STT_WHISPER_MODEL") or env_file.get("STT_WHISPER_MODEL", "small")
    ).strip()
    stt_whisper_cpp_bin = (
        os.getenv("STT_WHISPER_CPP_BIN")
        or env_file.get(
            "STT_WHISPER_CPP_BIN",
            str(PROJECT_ROOT / "tools" / "whisper.cpp" / "bin" / "whisper-cli.exe"),
        )
    ).strip()
    raw_whisper_cpp_model = (
        os.getenv("STT_WHISPER_CPP_MODEL")
        or env_file.get("STT_WHISPER_CPP_MODEL", "")
    )
    stt_whisper_cpp_model = _resolve_path(
        raw_whisper_cpp_model,
        default=PROJECT_ROOT / "tools" / "whisper.cpp" / "models" / "ggml-base.bin",
    )
    ffmpeg_bin = (os.getenv("FFMPEG_BIN") or env_file.get("FFMPEG_BIN", "ffmpeg")).strip()
    repo_git_remote = (
        os.getenv("REPO_GIT_REMOTE") or env_file.get("REPO_GIT_REMOTE", "origin")
    ).strip()
    repo_git_branch = (
        os.getenv("REPO_GIT_BRANCH") or env_file.get("REPO_GIT_BRANCH", "")
    ).strip()
    repo_pull_before_quiz = _env_bool(
        os.getenv("REPO_PULL_BEFORE_QUIZ")
        or env_file.get("REPO_PULL_BEFORE_QUIZ", "false")
    )
    repo_pull_before_read = _env_bool(
        os.getenv("REPO_PULL_BEFORE_READ")
        or env_file.get(
            "REPO_PULL_BEFORE_READ",
            "true" if repo_pull_before_quiz else "false",
        )
    )
    raw_repo_pull_timeout = (
        os.getenv("REPO_PULL_TIMEOUT_SECONDS")
        or env_file.get("REPO_PULL_TIMEOUT_SECONDS", "120")
    )
    try:
        repo_pull_timeout_seconds = max(10, int(raw_repo_pull_timeout))
    except ValueError:
        repo_pull_timeout_seconds = 120
    materials_github_base_url = (
        os.getenv("MATERIALS_GITHUB_BASE_URL")
        or env_file.get(
            "MATERIALS_GITHUB_BASE_URL",
            "https://github.com/Nuagrinn/lk-prep/blob/main",
        )
    ).strip().rstrip("/")
    topic_inbox_default_provider = "claude_cli" if claude_code_oauth_token else "fake"
    topic_inbox_agent_provider = (
        os.getenv("TOPIC_INBOX_AGENT_PROVIDER")
        or env_file.get("TOPIC_INBOX_AGENT_PROVIDER", topic_inbox_default_provider)
    ).strip().lower()
    topic_inbox_agent_model = (
        os.getenv("TOPIC_INBOX_AGENT_MODEL")
        or env_file.get("TOPIC_INBOX_AGENT_MODEL", claude_model)
    ).strip()
    raw_topic_inbox_agent_timeout = (
        os.getenv("TOPIC_INBOX_AGENT_TIMEOUT_SECONDS")
        or env_file.get("TOPIC_INBOX_AGENT_TIMEOUT_SECONDS", "120")
    )
    try:
        topic_inbox_agent_timeout_seconds = max(30, int(raw_topic_inbox_agent_timeout))
    except ValueError:
        topic_inbox_agent_timeout_seconds = 120
    mistake_review_default_provider = "claude_cli" if claude_code_oauth_token else "fake"
    mistake_review_agent_provider = (
        os.getenv("MISTAKE_REVIEW_AGENT_PROVIDER")
        or env_file.get("MISTAKE_REVIEW_AGENT_PROVIDER", mistake_review_default_provider)
    ).strip().lower()
    mistake_review_agent_model = (
        os.getenv("MISTAKE_REVIEW_AGENT_MODEL")
        or env_file.get("MISTAKE_REVIEW_AGENT_MODEL", claude_model)
    ).strip()
    raw_mistake_review_agent_timeout = (
        os.getenv("MISTAKE_REVIEW_AGENT_TIMEOUT_SECONDS")
        or env_file.get("MISTAKE_REVIEW_AGENT_TIMEOUT_SECONDS", "180")
    )
    try:
        mistake_review_agent_timeout_seconds = max(30, int(raw_mistake_review_agent_timeout))
    except ValueError:
        mistake_review_agent_timeout_seconds = 180
    explain_check_default_provider = "claude_cli" if claude_code_oauth_token else "fake"
    explain_check_agent_provider = (
        os.getenv("EXPLAIN_CHECK_AGENT_PROVIDER")
        or env_file.get("EXPLAIN_CHECK_AGENT_PROVIDER", explain_check_default_provider)
    ).strip().lower()
    explain_check_agent_model = (
        os.getenv("EXPLAIN_CHECK_AGENT_MODEL")
        or env_file.get("EXPLAIN_CHECK_AGENT_MODEL", claude_model)
    ).strip()
    raw_explain_check_agent_timeout = (
        os.getenv("EXPLAIN_CHECK_AGENT_TIMEOUT_SECONDS")
        or env_file.get("EXPLAIN_CHECK_AGENT_TIMEOUT_SECONDS", "180")
    )
    try:
        explain_check_agent_timeout_seconds = max(30, int(raw_explain_check_agent_timeout))
    except ValueError:
        explain_check_agent_timeout_seconds = 180

    return Settings(
        db_path=resolved_db,
        lk_prep_path=lk_prep_path,
        telegram_bot_token=raw_token.strip(),
        tg_user_id=tg_user_id,
        telegram_api_id=telegram_api_id,
        telegram_api_hash=telegram_api_hash,
        telegram_mtproto_session=telegram_mtproto_session,
        review_tick_seconds=review_tick_seconds,
        quiz_question_count=quiz_question_count,
        daily_quiz_hour=daily_quiz_hour,
        daily_quiz_minute=daily_quiz_minute,
        daily_quiz_timezone=daily_quiz_timezone,
        coding_reps_hour=coding_reps_hour,
        coding_reps_minute=coding_reps_minute,
        llm_provider=llm_provider,
        claude_bin=claude_bin,
        claude_code_oauth_token=claude_code_oauth_token,
        claude_model=claude_model,
        claude_timeout_seconds=claude_timeout_seconds,
        allow_paid_api=allow_paid_api,
        llm_input_usd_per_1m_tokens=llm_input_usd_per_1m_tokens,
        llm_output_usd_per_1m_tokens=llm_output_usd_per_1m_tokens,
        llm_usage_budget_5h_usd=llm_usage_budget_5h_usd,
        llm_usage_budget_daily_usd=llm_usage_budget_daily_usd,
        llm_usage_budget_weekly_usd=llm_usage_budget_weekly_usd,
        llm_usage_budget_monthly_usd=llm_usage_budget_monthly_usd,
        llm_usage_budget_5h_tokens=llm_usage_budget_5h_tokens,
        llm_usage_budget_daily_tokens=llm_usage_budget_daily_tokens,
        llm_usage_budget_weekly_tokens=llm_usage_budget_weekly_tokens,
        llm_usage_budget_monthly_tokens=llm_usage_budget_monthly_tokens,
        stt_provider=stt_provider,
        voice_dir=voice_dir,
        openai_api_key=openai_api_key,
        stt_openai_model=stt_openai_model,
        stt_language=stt_language,
        stt_prompt=stt_prompt,
        stt_timeout_seconds=stt_timeout_seconds,
        stt_whisper_bin=stt_whisper_bin,
        stt_whisper_model=stt_whisper_model,
        stt_whisper_cpp_bin=stt_whisper_cpp_bin,
        stt_whisper_cpp_model=stt_whisper_cpp_model,
        ffmpeg_bin=ffmpeg_bin,
        repo_git_remote=repo_git_remote,
        repo_git_branch=repo_git_branch,
        repo_pull_before_quiz=repo_pull_before_quiz,
        repo_pull_before_read=repo_pull_before_read,
        repo_pull_timeout_seconds=repo_pull_timeout_seconds,
        materials_github_base_url=materials_github_base_url,
        topic_inbox_agent_provider=topic_inbox_agent_provider,
        topic_inbox_agent_model=topic_inbox_agent_model,
        topic_inbox_agent_timeout_seconds=topic_inbox_agent_timeout_seconds,
        mistake_review_agent_provider=mistake_review_agent_provider,
        mistake_review_agent_model=mistake_review_agent_model,
        mistake_review_agent_timeout_seconds=mistake_review_agent_timeout_seconds,
        explain_check_agent_provider=explain_check_agent_provider,
        explain_check_agent_model=explain_check_agent_model,
        explain_check_agent_timeout_seconds=explain_check_agent_timeout_seconds,
    )


def _env_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_float(value: str) -> float:
    try:
        return max(0, float(value.strip().replace(",", ".")))
    except (AttributeError, ValueError):
        return 0


def _env_int(value: str) -> int:
    try:
        return max(0, int(float(value.strip().replace(",", "").replace("_", ""))))
    except (AttributeError, ValueError):
        return 0


def _parse_hhmm(value: str, *, default: tuple[int, int]) -> tuple[int, int]:
    try:
        raw_hour, raw_minute = value.split(":", 1)
        hour = int(raw_hour)
        minute = int(raw_minute)
    except (ValueError, TypeError):
        return default
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return default
    return hour, minute
