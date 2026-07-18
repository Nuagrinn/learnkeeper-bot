from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, time as datetime_time
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.adapters.telegram.formatters import (
    ANSWER_LABELS,
    format_cancel_review_confirm,
    format_cancel_review_done,
    format_cancel_review_list,
    format_explain_check_created,
    format_explain_check_list,
    format_explain_check_report,
    format_mistake_review_preview,
    format_mistake_work_created,
    format_mistake_work_item,
    format_mistake_work_list,
    format_open_question_check_report,
    format_open_question_item,
    format_open_question_list,
    format_open_question_prompt,
    format_topic_inbox_created,
    format_topic_inbox_list,
    format_study_topic_prompt,
    format_review_created,
    format_review_creation_started,
    format_tasks,
    format_topics,
    format_due_notification,
    format_task,
    format_topic_not_ready,
    format_instant_quiz_report,
    format_llm_budget_alert,
    format_llm_usage_report,
    format_quiz_question,
    format_quiz_report,
    split_message,
)
from app.config import PROJECT_ROOT, Settings, load_settings
from app.core.db import Database
from app.core.repo import RepoService
from app.features.llm_usage.service import (
    LlmUsageBudgetConfig,
    LlmUsagePriceConfig,
    LlmUsageService,
)
from app.features.mistake_work.agent import MistakeReviewAgentError, MistakeReviewInput
from app.features.mistake_work.factory import build_mistake_review_agent
from app.features.mistake_work.service import MistakeWorkService
from app.features.open_questions.agent import OpenQuestionAgentError
from app.features.open_questions.factory import build_open_question_agent
from app.features.open_questions.models import OpenQuestion, OpenQuestionAttempt
from app.features.open_questions.service import OpenQuestionService
from app.features.quiz.factory import build_quiz_generator
from app.features.quiz.generator import CODE_FILE_EXTENSIONS, MATERIAL_CHAR_LIMIT, QuizGenerationError
from app.features.quiz.models import QuizQuestion, QuizSession
from app.features.quiz.service import QuestionClosedError, QuizService
from app.features.coding_reps.service import CodingRepsService
from app.features.daily_quiz.models import DONE, PENDING, POSTPONED, SKIPPED, STARTED
from app.features.daily_quiz.service import DailyQuizService
from app.features.explain_check.agent import ExplainCheckAgentError, ExplainCheckInput
from app.features.explain_check.factory import build_explain_check_agent
from app.features.explain_check.service import ExplainCheckService
from app.features.review_tasks.service import ReviewTaskService, TopicNotReadyError
from app.features.speech.factory import build_speech_to_text
from app.features.speech.service import SpeechToTextError
from app.features.topic_inbox.factory import build_topic_inbox_agent
from app.features.topic_inbox.service import TopicInboxService


log = logging.getLogger(__name__)
START_REVIEW_PREFIX = "start_review:"
POSTPONE_DUE_PREFIX = "postpone_due:"
EXPLAIN_THEN_REVIEW_PREFIX = "explain_then_review:"
SKIP_EXPLAIN_REVIEW_PREFIX = "skip_explain_review:"
QUIZ_ANSWER_PREFIX = "quiz_answer:"
INSTANT_BLOCKS = "instant_blocks"
INSTANT_BLOCK_PREFIX = "instant_block:"
INSTANT_BLOCK_ALL_PREFIX = "instant_block_all:"
INSTANT_TOPIC_PREFIX = "instant_topic:"
ABORT_INSTANT_QUIZ = "abort_instant_quiz"
DAILY_QUIZ_TOGGLE_PREFIX = "daily_quiz_toggle:"
DAILY_QUIZ_START_PREFIX = "daily_quiz_start:"
DAILY_QUIZ_SKIP_PREFIX = "daily_quiz_skip:"
DAILY_QUIZ_POSTPONE_PREFIX = "daily_quiz_postpone:"
DAILY_QUIZ_DONE_PREFIX = "daily_quiz_done:"
DAILY_QUIZ_OPEN_PREFIX = "daily_quiz_open:"
MENU_DAILY_QUIZ_OUTSTANDING = "menu_daily_quiz_outstanding"
CODING_REPS_TOGGLE_PREFIX = "coding_reps_toggle:"
CODING_REPS_DONE_PREFIX = "coding_reps_done:"
CODING_REPS_SKIP_PREFIX = "coding_reps_skip:"
QUIZ_SIZE_PREFIX = "quiz_size:"
ABORT_QUIZ_SIZE = "abort_quiz_size"
MENU_REVIEW = "menu_review"
MENU_TESTS = "menu_tests"
MENU_PROCESSING = "menu_processing"
MENU_IDEAS = "menu_ideas"
MENU_SETTINGS = "menu_settings"
MENU_SCHEDULE = "menu_schedule"
MENU_DUE = "menu_due"
TOPIC_BLOCKS = "topic_blocks"
TOPIC_BLOCK_PREFIX = "topic_block:"
ABORT_TOPICS = "abort_topics"
MENU_CANCEL_REVIEWS = "menu_cancel_reviews"
MENU_STUDY_TOPICS = "menu_study_topics"
MENU_TOPIC_ADD = "menu_topic_add"
MENU_TOPIC_INBOX = "menu_topic_inbox"
MENU_MISTAKE_WORK = "menu_mistake_work"
MENU_MISTAKE_WORK_DONE = "menu_mistake_work_done"
MENU_EXPLAIN_CHECK = "menu_explain_check"
MENU_EXPLAIN_CHECK_LIST = "menu_explain_check_list"
MENU_EXPLAIN_CHECK_DONE = "menu_explain_check_done"
MENU_DAILY_SETTINGS = "menu_daily_settings"
MENU_CODING_REPS_SETTINGS = "menu_coding_reps_settings"
MENU_LLM_USAGE = "menu_llm_usage"
MENU_CHANGELOG = "menu_changelog"
CANCEL_REVIEW_PREFIX = "cancel_review:"
CONFIRM_CANCEL_REVIEW_PREFIX = "confirm_cancel_review:"
ABORT_CANCEL_REVIEW = "abort_cancel_review"
REVIEW_ADD_BLOCKS = "review_add_blocks"
REVIEW_BLOCK_PREFIX = "review_block:"
REVIEW_TOPIC_PREFIX = "review_topic:"
RESET_REVIEW_PREFIX = "reset_review:"
ABORT_REVIEW_ADD = "abort_review_add"
TOPIC_INBOX_DELETE_PREFIX = "topic_inbox_delete:"
MISTAKE_REVIEW_PREFIX = "mistake_review:"
SAVE_MISTAKE_REPORT_PREFIX = "save_mistake_report:"
MISTAKE_WORK_OPEN_PREFIX = "mistake_work_open:"
MISTAKE_WORK_DONE_PREFIX = "mistake_work_done:"
MISTAKE_WORK_DELETE_PREFIX = "mistake_work_delete:"
EXPLAIN_CHECK_BLOCKS = "explain_check_blocks"
EXPLAIN_CHECK_BLOCK_PREFIX = "explain_check_block:"
EXPLAIN_CHECK_TOPIC_PREFIX = "explain_check_topic:"
ABORT_EXPLAIN_CHECK = "abort_explain_check"
EXPLAIN_CHECK_OPEN_PREFIX = "explain_check_open:"
EXPLAIN_CHECK_DONE_PREFIX = "explain_check_done:"
EXPLAIN_CHECK_DELETE_PREFIX = "explain_check_delete:"
OPEN_QUESTION_BLOCKS = "open_question_blocks"
OPEN_QUESTION_BLOCK_PREFIX = "open_question_block:"
OPEN_QUESTION_TOPIC_PREFIX = "open_question_topic:"
OPEN_QUESTION_FROM_QUIZ_PREFIX = "open_question_quiz:"
OPEN_QUESTION_SKIP_PREFIX = "open_question_skip:"
OPEN_QUESTION_OPEN_PREFIX = "open_question_open:"
OPEN_QUESTION_DELETE_PREFIX = "open_question_delete:"
ABORT_OPEN_QUESTION = "abort_open_question"
MENU_OPEN_QUESTIONS = "menu_open_questions"
MENU_OPEN_QUESTIONS_ANSWERED = "menu_open_questions_answered"
READ_MATERIAL_BLOCKS = "read_material_blocks"
READ_MATERIAL_BLOCK_PREFIX = "read_material_block:"
READ_MATERIAL_TOPIC_PREFIX = "read_material_topic:"
ABORT_READ_MATERIAL = "abort_read_material"
GENERATION_FRAMES = ("⏳", "⌛")
QUIZ_SIZE_OPTIONS = (5, 10, 20, 30)
QUIZ_SIZE_REVIEW = "review"
QUIZ_SIZE_INSTANT_TOPIC = "instant_topic"
QUIZ_SIZE_INSTANT_BLOCK = "instant_block"
QUIZ_SIZE_DAILY_TOPIC = "daily_topic"
BTN_TOPICS = "📚 Темы"
BTN_READ_MATERIAL = "📖 Читать материал"
BTN_REVIEW_MENU = "🔁 Повторы"
BTN_TEST_MENU = "🎯 Тренировки"
BTN_IDEAS_MENU = "🗂 Проработка"
BTN_SETTINGS_MENU = "⚙️ Настройки"
BTN_REVIEW_ADD = "➕ Добавить повтор"
BTN_INSTANT_QUIZ = "▶️ Пройти тест сейчас"
BTN_DAILY_QUIZ = "🌅 Ежедневные тесты"
BTN_CODING_REPS = "🏋️ Кодинг-репы"
BTN_LLM_USAGE = "📊 Токены LLM"
BTN_CHANGELOG = "📝 Changelog"
BTN_REVIEW_CANCEL = "🗑 Удалить повтор"
BTN_STUDY_TOPICS = "💡 Inbox идей"
BTN_TOPIC_ADD = "➕ Добавить идею"
BTN_TOPIC_INBOX = "📥 Список идей"
BTN_MISTAKE_WORK = "🧩 Работа над ошибками"
BTN_MISTAKE_WORK_ACTIVE = "📋 Активные отчеты"
BTN_MISTAKE_WORK_DONE = "✅ Проработанные"
BTN_EXPLAIN_CHECK = "🗣 Объяснить тему"
BTN_EXPLAIN_CHECK_START = "▶️ Объяснить новую тему"
BTN_EXPLAIN_CHECK_LIST = "📋 Мои объяснения"
BTN_EXPLAIN_CHECK_DONE = "✅ Разобранные"
BTN_OPEN_QUESTION = "🎯 Открытый вопрос"
BTN_OPEN_QUESTION_LIST = "📋 Открытые вопросы"
BTN_OPEN_QUESTION_ANSWERED = "✅ Проверенные ответы"
BTN_SCHEDULE = "🗓 Расписание"
BTN_DUE = "⏰ Пора повторять"
BTN_HELP = "❔ Помощь"
LEGACY_MENU_BUTTONS = {
    "Темы",
    "Добавить повтор",
    "Пройти тест сейчас",
    "Тесты",
    "Тренировки",
    "Открытый вопрос",
    "Открытые вопросы",
    "Проверенные ответы",
    "Ежедневные тесты",
    "Кодинг-репы",
    "Токены LLM",
    "Changelog",
    "Удалить повтор",
    "Идеи",
    "Темы на изучение",
    "Добавить тему",
    "Inbox идей",
    "Добавить идею",
    "Идеи тем",
    "Список идей",
    "Работа над ошибками",
    "Активные отчеты",
    "Проработанные",
    "Объяснить тему",
    "Объяснить новую тему",
    "Мои объяснения",
    "Разобранные",
    "Расписание",
    "Пора повторять",
    "Помощь",
}
MENU_BUTTONS = {
    BTN_TOPICS,
    BTN_READ_MATERIAL,
    BTN_REVIEW_MENU,
    BTN_TEST_MENU,
    BTN_IDEAS_MENU,
    BTN_SETTINGS_MENU,
    BTN_REVIEW_ADD,
    BTN_INSTANT_QUIZ,
    BTN_DAILY_QUIZ,
    BTN_CODING_REPS,
    BTN_LLM_USAGE,
    BTN_CHANGELOG,
    BTN_REVIEW_CANCEL,
    BTN_STUDY_TOPICS,
    BTN_TOPIC_ADD,
    BTN_TOPIC_INBOX,
    BTN_MISTAKE_WORK,
    BTN_MISTAKE_WORK_ACTIVE,
    BTN_MISTAKE_WORK_DONE,
    BTN_EXPLAIN_CHECK,
    BTN_EXPLAIN_CHECK_START,
    BTN_EXPLAIN_CHECK_LIST,
    BTN_EXPLAIN_CHECK_DONE,
    BTN_OPEN_QUESTION,
    BTN_OPEN_QUESTION_LIST,
    BTN_OPEN_QUESTION_ANSWERED,
    BTN_SCHEDULE,
    BTN_DUE,
    BTN_HELP,
} | LEGACY_MENU_BUTTONS


LAST_NOTIFIED_VERSION_KEY = "app_version_last_notified"
LLM_BUDGET_ALERT_KEY = "llm_budget_alert_level"
CHANGELOG_LIMIT = 8


class AppServices:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.db_path)
        self.db.migrate()
        self.repo = RepoService(settings.lk_prep_path)
        self.llm_usage = LlmUsageService(
            self.db,
            price_config=LlmUsagePriceConfig(
                input_usd_per_1m_tokens=settings.llm_input_usd_per_1m_tokens,
                output_usd_per_1m_tokens=settings.llm_output_usd_per_1m_tokens,
            ),
            budget_config=LlmUsageBudgetConfig(
                rolling_5h_usd=settings.llm_usage_budget_5h_usd,
                daily_usd=settings.llm_usage_budget_daily_usd,
                weekly_usd=settings.llm_usage_budget_weekly_usd,
                monthly_usd=settings.llm_usage_budget_monthly_usd,
                rolling_5h_tokens=settings.llm_usage_budget_5h_tokens,
                daily_tokens=settings.llm_usage_budget_daily_tokens,
                weekly_tokens=settings.llm_usage_budget_weekly_tokens,
                monthly_tokens=settings.llm_usage_budget_monthly_tokens,
            ),
        )
        self.review_tasks = ReviewTaskService(self.db, self.repo)
        self.daily_quiz = DailyQuizService(self.db, self.repo)
        self.coding_reps = CodingRepsService(self.db)
        self.topic_inbox = TopicInboxService(
            self.db,
            build_topic_inbox_agent(settings, usage_recorder=self.llm_usage),
        )
        self.mistake_work = MistakeWorkService(self.db)
        self.mistake_review_agent = build_mistake_review_agent(
            settings,
            usage_recorder=self.llm_usage,
        )
        self.explain_check = ExplainCheckService(self.db)
        self.explain_check_agent = build_explain_check_agent(
            settings,
            usage_recorder=self.llm_usage,
        )
        self.open_questions = OpenQuestionService(
            self.db,
            self.repo,
            build_open_question_agent(settings, usage_recorder=self.llm_usage),
            pull_before_question=settings.repo_pull_before_quiz,
            git_remote=settings.repo_git_remote,
            git_branch=settings.repo_git_branch,
            pull_timeout_seconds=settings.repo_pull_timeout_seconds,
        )
        self.speech = build_speech_to_text(settings)
        self.voice_dir = settings.voice_dir
        self.quiz = QuizService(
            self.db,
            self.repo,
            self.review_tasks,
            build_quiz_generator(settings, usage_recorder=self.llm_usage),
            pull_before_quiz=settings.repo_pull_before_quiz,
            git_remote=settings.repo_git_remote,
            git_branch=settings.repo_git_branch,
            pull_timeout_seconds=settings.repo_pull_timeout_seconds,
        )
        self.quiz_question_count = settings.quiz_question_count


def _require_telegram_settings(settings: Settings) -> None:
    missing: list[str] = []
    if not settings.telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if settings.tg_user_id is None:
        missing.append("TG_USER_ID")
    if missing:
        raise RuntimeError(f"Missing required Telegram settings: {', '.join(missing)}")


def _is_owner(update: Update, owner_id: int) -> bool:
    return bool(update.effective_user and update.effective_user.id == owner_id)


def _services(context: ContextTypes.DEFAULT_TYPE) -> AppServices:
    return context.application.bot_data["services"]


async def _sync_materials_repo(context: ContextTypes.DEFAULT_TYPE, reason: str) -> None:
    services = _services(context)
    settings = services.settings
    if not settings.repo_pull_before_read:
        return

    try:
        result = await asyncio.to_thread(
            services.repo.pull_latest,
            remote=settings.repo_git_remote,
            branch=settings.repo_git_branch,
            timeout_seconds=settings.repo_pull_timeout_seconds,
        )
    except Exception:
        log.exception("Repo pull before %s failed unexpectedly", reason)
        return

    detail = result.detail.replace("\n", " ")[:240] if result.detail else ""
    log.info(
        "Repo pull before %s status=%s detail=%s",
        reason,
        result.status,
        detail,
    )


def _owner_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return int(context.application.bot_data["owner_id"])


def _get_app_setting(services: AppServices, key: str, default: str = "") -> str:
    with services.db.session() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (key,),
        ).fetchone()
    return row["value"] if row else default


def _set_app_setting(services: AppServices, key: str, value: str) -> None:
    now = datetime.now().replace(microsecond=0).isoformat(timespec="seconds")
    with services.db.session() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now),
        )


_LIMIT_ERROR_MARKERS = (
    "usage limit",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "limit reached",
    "limit will reset",
    "5-hour limit",
    "5 hour limit",
    "weekly limit",
    "too many requests",
    "429",
    "overloaded",
    "try again later",
    "quota",
)
LIMIT_NOTICE = (
    "⚠️ <b>Похоже, достигнут лимит Claude</b>\n\n"
    "Claude вернул ошибку про лимит/квоту использования. Это лимит подписки Anthropic — "
    "он общий на все сессии Claude Code, а не только на бота.\n\n"
    "Попробуй позже: лимит обычно сбрасывается в течение нескольких часов."
)


def _is_limit_error(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in _LIMIT_ERROR_MARKERS)


def _generation_error_text(exc: Exception, fallback: str) -> str:
    """Return a clear limit notice when the CLI failed on a usage/rate limit,
    otherwise the generic fallback message."""
    if _is_limit_error(str(exc)):
        log.warning("LLM usage/rate limit likely hit: %s", exc)
        return LIMIT_NOTICE
    return fallback


def _git_output(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), *args],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _current_version() -> str:
    return _git_output("rev-parse", "--short=12", "HEAD") or "unknown"


def _current_version_subject() -> str:
    return _git_output("show", "-s", "--format=%s", "HEAD") or "локальная версия"


def _current_version_date() -> str:
    return _git_output("show", "-s", "--format=%ci", "HEAD") or ""


def _format_changelog_text() -> str:
    version = _current_version()
    subject = _current_version_subject()
    date = _current_version_date()
    lines = [
        "<b>Changelog</b>",
        "",
        f"<b>Текущая версия:</b> <code>{html.escape(version, quote=False)}</code>",
        f"<b>Коммит:</b> {html.escape(subject, quote=False)}",
    ]
    if date:
        lines.append(f"<b>Дата:</b> <code>{html.escape(date, quote=False)}</code>")

    raw_log = _git_output(
        "log",
        f"-n{CHANGELOG_LIMIT}",
        "--date=short",
        "--pretty=format:%h%x09%ad%x09%s",
    )
    if raw_log:
        lines.extend(["", "<b>Последние изменения</b>"])
        for raw_line in raw_log.splitlines():
            parts = raw_line.split("\t", 2)
            if len(parts) == 3:
                commit, commit_date, message = parts
                lines.append(
                    f"• <code>{html.escape(commit, quote=False)}</code> "
                    f"<code>{html.escape(commit_date, quote=False)}</code> "
                    f"{html.escape(message, quote=False)}"
                )
    else:
        lines.extend(["", "Git-история недоступна в текущем окружении."])

    return "\n".join(lines)


def _format_version_update_text() -> str:
    version = _current_version()
    subject = _current_version_subject()
    date = _current_version_date()
    lines = [
        "<b>LearnKeeper обновлен и перезапущен</b>",
        "",
        f"<b>Версия:</b> <code>{html.escape(version, quote=False)}</code>",
        f"<b>Коммит:</b> {html.escape(subject, quote=False)}",
    ]
    if date:
        lines.append(f"<b>Дата:</b> <code>{html.escape(date, quote=False)}</code>")
    return "\n".join(lines)


def _main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [BTN_TOPICS, BTN_READ_MATERIAL],
            [BTN_REVIEW_MENU, BTN_TEST_MENU],
            [BTN_IDEAS_MENU, BTN_SETTINGS_MENU],
            [BTN_HELP],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выбери раздел",
    )


def _review_topic_prompt() -> str:
    return (
        "<b>Какую тему поставить на повторение?</b>\n\n"
        "Напиши название или id темы следующим сообщением, либо отправь голосовое.\n"
        "Например: <code>слайсы</code>, <code>b02</code>, <code>data race</code>."
    )


async def _answer_long(
    update: Update,
    text: str,
    *,
    parse_mode: str | None = ParseMode.HTML,
) -> None:
    if not update.message:
        return
    for chunk in split_message(text):
        await update.message.reply_text(
            chunk,
            parse_mode=parse_mode,
            reply_markup=_main_keyboard(),
        )


async def _edit_or_reply(
    update: Update,
    message,
    text: str,
    *,
    parse_mode: str | None = None,
):
    try:
        return await message.edit_text(text, parse_mode=parse_mode)
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            return message
        log.warning("Could not edit Telegram message, sending a new one: %s", exc)
        if not update.message:
            return message
        return await update.message.reply_text(
            text,
            parse_mode=parse_mode,
            reply_markup=_main_keyboard(),
        )


async def _safe_query_answer(query, text: str | None = None, *, show_alert: bool = False) -> None:
    try:
        await query.answer(text, show_alert=show_alert)
    except BadRequest as exc:
        log.warning("Could not answer callback query, probably expired: %s", exc)


async def _safe_query_edit(query, text: str, *, parse_mode: str | None = None, reply_markup=None) -> None:
    try:
        await query.edit_message_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    except BadRequest as exc:
        log.warning("Could not edit callback message, probably stale: %s", exc)


async def _reject_non_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if _is_owner(update, _owner_id(context)):
        return False
    user_id = update.effective_user.id if update.effective_user else None
    log.warning("Ignoring non-owner message from user_id=%s", user_id)
    if update.message:
        await update.message.reply_text("Это личный бот LearnKeeper.")
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_non_owner(update, context):
        return
    await _answer_long(
        update,
        "<b>LearnKeeper на связи</b>\n\n"
        "Основные действия собраны в разделы снизу.\n\n"
        f"<b>{BTN_TOPICS}</b> - список тем из lk-prep\n"
        f"<b>{BTN_READ_MATERIAL}</b> - прислать материал темы файлом (Telegram сам красиво его отрендерит)\n"
        f"<b>{BTN_REVIEW_MENU}</b> - добавить, посмотреть или отменить повторы\n"
        f"<b>{BTN_TEST_MENU}</b> - тесты, открытые вопросы и ежедневные тренировки\n"
        f"<b>{BTN_IDEAS_MENU}</b> - идеи тем, отчеты по ошибкам и сохраненные разборы\n"
        f"<b>{BTN_SETTINGS_MENU}</b> - переключатели и статистика LLM\n\n"
        "Slash-команды тоже работают, если они удобнее: "
        "<code>/topics</code>, <code>/review_add</code>, "
        "<code>/instant_quiz</code>, <code>/topic_add</code>, <code>/topic_ideas</code>, "
        "<code>/schedule</code>, <code>/due</code>.",
    )


async def topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_non_owner(update, context):
        return
    query = " ".join(context.args).strip()
    await _show_topics(update, context, query=query)


async def topic_blocks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    await _sync_materials_repo(context, "topic-blocks")
    grouped = _all_topics_by_section(_services(context))
    if not grouped:
        await query.edit_message_text(
            "<b>Темы</b>\n\nВ lk-prep пока нет тем.",
            parse_mode=ParseMode.HTML,
        )
        return
    await query.edit_message_text(
        _topic_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_topic_block_keyboard(grouped),
    )


async def topic_block_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    raw_path = (query.data or "").removeprefix(TOPIC_BLOCK_PREFIX)
    grouped = _all_topics_by_section(_services(context))
    selection = _section_selection(grouped, raw_path)
    if not selection:
        await query.edit_message_text("Список блоков устарел. Нажми «Темы» еще раз.")
        return

    node, path = selection
    if node.children:
        await query.edit_message_text(
            _topic_blocks_text(grouped, path=path),
            parse_mode=ParseMode.HTML,
            reply_markup=_topic_block_keyboard(grouped, path=path),
        )
        return

    root = _section_tree(grouped)
    topics = _section_topics(node)
    await query.edit_message_text(
        _topic_list_text(_section_leaf_title(root, path), topics),
        parse_mode=ParseMode.HTML,
        reply_markup=_topic_section_keyboard(),
    )


async def abort_topics_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer("Закрыто")
    await query.edit_message_text("Список тем закрыт.")


async def review_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_non_owner(update, context):
        return
    query = " ".join(context.args).strip()
    if not query:
        context.user_data["awaiting_review_topic"] = False
        await _show_review_blocks(update, context)
        return

    await _create_review_task_from_query(update, context, query)


async def instant_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_non_owner(update, context):
        return
    await _show_instant_blocks(update, context)


async def topic_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_non_owner(update, context):
        return
    query = " ".join(context.args).strip()
    if not query:
        context.user_data["awaiting_study_topic"] = True
        context.user_data["awaiting_review_topic"] = False
        await _answer_long(update, format_study_topic_prompt())
        return

    await _create_topic_inbox_item(update, context, query, source="command")


async def topic_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_non_owner(update, context):
        return
    await _show_topic_inbox(update, context)


async def _show_topics(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query: str = "",
) -> None:
    if not query:
        await _show_topic_blocks(update, context)
        return

    services = _services(context)
    await _sync_materials_repo(context, "topics")
    items = services.repo.search_topics(query, limit=30)
    await _answer_long(update, format_topics(items))


async def _show_topic_blocks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _services(context)
    await _sync_materials_repo(context, "topic-blocks")
    grouped = _all_topics_by_section(services)
    if not grouped:
        await _answer_long(update, "<b>Темы</b>\n\nВ lk-prep пока нет тем.")
        return
    if not update.message:
        return
    await update.message.reply_text(
        _topic_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_topic_block_keyboard(grouped),
    )


async def _send_section_menu(
    update: Update,
    title: str,
    description: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        f"<b>{title}</b>\n\n{description}",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _show_review_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_section_menu(
        update,
        "🔁 Повторы",
        "Отложенные повторения, расписание и задачи, которые уже пора пройти.",
        _review_menu_keyboard(),
    )


async def _show_tests_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_section_menu(
        update,
        "🎯 Тренировки",
        "Быстрые проверки без изменения расписания: A/B/C/D тесты, открытые вопросы и ежедневный случайный тест.",
        _tests_menu_keyboard(),
    )


async def _show_ideas_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_section_menu(
        update,
        "🗂 Проработка",
        "Inbox идей, отчеты после ошибок, открытые вопросы и сохраненные объяснения.",
        _ideas_menu_keyboard(),
    )


async def _show_study_topics_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_section_menu(
        update,
        "💡 Inbox идей",
        "Голосовые и текстовые мысли: что изучить, почитать, реализовать, написать или доработать.",
        _study_topics_menu_keyboard(),
    )


async def _show_mistake_work_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_section_menu(
        update,
        "🧩 Работа над ошибками",
        "Отчеты, которые агент собрал после неправильных ответов в тестах.",
        _mistake_work_menu_keyboard(),
    )


async def _show_explain_check_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_section_menu(
        update,
        "🗣 Объяснить тему",
        "Расскажи тему своими словами без подглядывания в материал — агент "
        "сверит с эталоном и покажет, что упущено.",
        _explain_check_menu_keyboard(),
    )


async def _show_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_section_menu(
        update,
        "⚙️ Настройки",
        "Переключатели поведения бота и локальная статистика LLM.",
        _settings_menu_keyboard(),
    )


def _review_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_REVIEW_ADD, callback_data=REVIEW_ADD_BLOCKS)],
            [
                InlineKeyboardButton(BTN_SCHEDULE, callback_data=MENU_SCHEDULE),
                InlineKeyboardButton(BTN_DUE, callback_data=MENU_DUE),
            ],
            [InlineKeyboardButton(BTN_REVIEW_CANCEL, callback_data=MENU_CANCEL_REVIEWS)],
        ]
    )


def _tests_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_INSTANT_QUIZ, callback_data=INSTANT_BLOCKS)],
            [InlineKeyboardButton(BTN_OPEN_QUESTION, callback_data=OPEN_QUESTION_BLOCKS)],
            [InlineKeyboardButton(BTN_EXPLAIN_CHECK, callback_data=MENU_EXPLAIN_CHECK)],
            [InlineKeyboardButton(BTN_DAILY_QUIZ, callback_data=MENU_DAILY_SETTINGS)],
        ]
    )


def _ideas_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_STUDY_TOPICS, callback_data=MENU_STUDY_TOPICS)],
            [InlineKeyboardButton(BTN_MISTAKE_WORK, callback_data=MENU_MISTAKE_WORK)],
            [InlineKeyboardButton(BTN_OPEN_QUESTION_LIST, callback_data=MENU_OPEN_QUESTIONS)],
            [InlineKeyboardButton(BTN_EXPLAIN_CHECK_LIST, callback_data=MENU_EXPLAIN_CHECK_LIST)],
        ]
    )


def _study_topics_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_TOPIC_ADD, callback_data=MENU_TOPIC_ADD)],
            [InlineKeyboardButton(BTN_TOPIC_INBOX, callback_data=MENU_TOPIC_INBOX)],
        ]
    )


def _explain_check_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_EXPLAIN_CHECK_START, callback_data=EXPLAIN_CHECK_BLOCKS)],
            [InlineKeyboardButton(BTN_EXPLAIN_CHECK_LIST, callback_data=MENU_EXPLAIN_CHECK_LIST)],
            [InlineKeyboardButton(BTN_EXPLAIN_CHECK_DONE, callback_data=MENU_EXPLAIN_CHECK_DONE)],
        ]
    )


def _open_question_list_keyboard(
    items: list[OpenQuestion],
    *,
    show_answered_link: bool = True,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(f"{item.topic_id} · {item.topic_title}"),
                    callback_data=f"{OPEN_QUESTION_OPEN_PREFIX}{item.id}",
                )
            ]
        )
    if show_answered_link:
        rows.append([InlineKeyboardButton("Проверенные", callback_data=MENU_OPEN_QUESTIONS_ANSWERED)])
    else:
        rows.append([InlineKeyboardButton("Без ответа", callback_data=MENU_OPEN_QUESTIONS)])
    return InlineKeyboardMarkup(rows)


def _open_question_item_keyboard(item: OpenQuestion) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if item.status == "active":
        rows.append(
            [
                InlineKeyboardButton(
                    "Ответить",
                    callback_data=f"{OPEN_QUESTION_OPEN_PREFIX}{item.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "Удалить",
                callback_data=f"{OPEN_QUESTION_DELETE_PREFIX}{item.id}",
            )
        ]
    )
    rows.append([InlineKeyboardButton("К открытым вопросам", callback_data=MENU_OPEN_QUESTIONS)])
    return InlineKeyboardMarkup(rows)


def _mistake_work_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_MISTAKE_WORK_ACTIVE, callback_data=MENU_MISTAKE_WORK)],
            [InlineKeyboardButton(BTN_MISTAKE_WORK_DONE, callback_data=MENU_MISTAKE_WORK_DONE)],
        ]
    )


def _settings_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_DAILY_QUIZ, callback_data=MENU_DAILY_SETTINGS)],
            [InlineKeyboardButton(BTN_CODING_REPS, callback_data=MENU_CODING_REPS_SETTINGS)],
            [InlineKeyboardButton(BTN_LLM_USAGE, callback_data=MENU_LLM_USAGE)],
            [InlineKeyboardButton(BTN_CHANGELOG, callback_data=MENU_CHANGELOG)],
        ]
    )


async def _create_topic_inbox_item(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str,
    *,
    source: str,
) -> None:
    clean_query = query.strip()
    if not clean_query:
        await _answer_long(update, "Не вижу идею. Попробуй написать или надиктовать еще раз.")
        return

    log.info(
        "Topic inbox creation started source=%s query_len=%s",
        source,
        len(clean_query),
    )
    wait_message = None
    if update.message:
        wait_message = await update.message.reply_text(
            "<b>Принял идею</b>\n\n"
            "Формулирую через агента и сохраняю в inbox.",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_keyboard(),
        )

    started_at = perf_counter()
    try:
        item = await asyncio.to_thread(
            _services(context).topic_inbox.create_item,
            clean_query,
            source=source,
        )
    except Exception:
        log.exception(
            "Topic inbox creation failed source=%s elapsed=%.2fs",
            source,
            perf_counter() - started_at,
        )
        text = "Не смог сохранить идею.\n\nПроверь логи локального запуска."
        if wait_message:
            await _edit_or_reply(update, wait_message, text, parse_mode=ParseMode.HTML)
        else:
            await _answer_long(update, text)
        return

    log.info(
        "Topic inbox item created id=%s source=%s elapsed=%.2fs",
        item.id,
        source,
        perf_counter() - started_at,
    )
    text = format_topic_inbox_created(item)
    if wait_message:
        await _edit_or_reply(update, wait_message, text, parse_mode=ParseMode.HTML)
    else:
        await _answer_long(update, text)


async def _show_topic_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = _services(context).topic_inbox.list_active(limit=20)
    if not update.message:
        return
    await update.message.reply_text(
        format_topic_inbox_list(items),
        parse_mode=ParseMode.HTML,
        reply_markup=_topic_inbox_keyboard(items) if items else _main_keyboard(),
    )


def _topic_inbox_keyboard(items) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(f"Удалить: {item.title}"),
                    callback_data=f"{TOPIC_INBOX_DELETE_PREFIX}{item.id}",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


async def _show_mistake_work_active(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = _services(context).mistake_work.list_active(limit=20)
    if not update.message:
        return
    await update.message.reply_text(
        format_mistake_work_list(items, status_title="Активные отчеты"),
        parse_mode=ParseMode.HTML,
        reply_markup=_mistake_work_list_keyboard(items) if items else _main_keyboard(),
    )


async def _show_mistake_work_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = _services(context).mistake_work.list_done(limit=20)
    if not update.message:
        return
    await update.message.reply_text(
        format_mistake_work_list(items, status_title="Проработанные отчеты"),
        parse_mode=ParseMode.HTML,
        reply_markup=_mistake_work_list_keyboard(items) if items else _main_keyboard(),
    )


async def _show_open_questions_active(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = _services(context).open_questions.list_active(limit=20)
    if not update.message:
        return
    await update.message.reply_text(
        format_open_question_list(items, status_title="Открытые вопросы без ответа"),
        parse_mode=ParseMode.HTML,
        reply_markup=_open_question_list_keyboard(items) if items else _main_keyboard(),
    )


async def _show_open_questions_answered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = _services(context).open_questions.list_answered(limit=20)
    if not update.message:
        return
    await update.message.reply_text(
        format_open_question_list(items, status_title="Проверенные открытые вопросы"),
        parse_mode=ParseMode.HTML,
        reply_markup=(
            _open_question_list_keyboard(items, show_answered_link=False)
            if items
            else _main_keyboard()
        ),
    )


async def _show_explain_check_active(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = _services(context).explain_check.list_active(limit=20)
    if not update.message:
        return
    await update.message.reply_text(
        format_explain_check_list(items, status_title="Мои объяснения"),
        parse_mode=ParseMode.HTML,
        reply_markup=_explain_check_list_keyboard(items) if items else _main_keyboard(),
    )


async def _show_explain_check_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = _services(context).explain_check.list_done(limit=20)
    if not update.message:
        return
    await update.message.reply_text(
        format_explain_check_list(items, status_title="Разобранные объяснения"),
        parse_mode=ParseMode.HTML,
        reply_markup=_explain_check_list_keyboard(items) if items else _main_keyboard(),
    )


def _mistake_work_list_keyboard(items) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(f"Открыть: {item.title}"),
                    callback_data=f"{MISTAKE_WORK_OPEN_PREFIX}{item.id}",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def _mistake_work_item_keyboard(item_id: str, *, status: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if status == "active":
        rows.append(
            [
                InlineKeyboardButton(
                    "Отметить проработанным",
                    callback_data=f"{MISTAKE_WORK_DONE_PREFIX}{item_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "Удалить",
                callback_data=f"{MISTAKE_WORK_DELETE_PREFIX}{item_id}",
            )
        ]
    )
    rows.append([InlineKeyboardButton("К активным", callback_data=MENU_MISTAKE_WORK)])
    return InlineKeyboardMarkup(rows)


def _explain_check_list_keyboard(items) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(f"Открыть: {item.topic_title}"),
                    callback_data=f"{EXPLAIN_CHECK_OPEN_PREFIX}{item.id}",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def _explain_check_item_keyboard(item_id: str, *, status: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if status == "active":
        rows.append(
            [
                InlineKeyboardButton(
                    "Отметить разобранным",
                    callback_data=f"{EXPLAIN_CHECK_DONE_PREFIX}{item_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "Удалить",
                callback_data=f"{EXPLAIN_CHECK_DELETE_PREFIX}{item_id}",
            )
        ]
    )
    rows.append([InlineKeyboardButton("К моим объяснениям", callback_data=MENU_EXPLAIN_CHECK_LIST)])
    return InlineKeyboardMarkup(rows)


def _mistake_report_keyboard(session_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Сохранить отчет",
                    callback_data=f"{SAVE_MISTAKE_REPORT_PREFIX}{session_id}",
                )
            ],
            [InlineKeyboardButton("Не сохранять", callback_data=MENU_MISTAKE_WORK)],
        ]
    )


def _quiz_report_keyboard(
    session_id: str,
    questions,
    answers,
    *,
    include_open_question: bool = True,
) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    if _mistake_questions(questions, answers):
        rows.append(
            [
                InlineKeyboardButton(
                    "Разобрать ошибки",
                    callback_data=f"{MISTAKE_REVIEW_PREFIX}{session_id}",
                )
            ],
        )
    if include_open_question:
        rows.append(
            [
                InlineKeyboardButton(
                    "Открытый вопрос",
                    callback_data=f"{OPEN_QUESTION_FROM_QUIZ_PREFIX}{session_id}",
                ),
                InlineKeyboardButton(
                    "Пропустить",
                    callback_data=f"{OPEN_QUESTION_SKIP_PREFIX}{session_id}",
                ),
            ]
        )
    return InlineKeyboardMarkup(rows) if rows else None


async def _show_review_blocks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _services(context)
    await _sync_materials_repo(context, "review-blocks")
    grouped = _ready_review_topics_by_section(services)
    if not grouped:
        await _answer_long(
            update,
            "<b>Добавить повтор</b>\n\n"
            "В lk-prep пока нет ready-тем с читаемыми материалами.",
        )
        return
    if not update.message:
        return
    await update.message.reply_text(
        _review_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_review_block_keyboard(grouped),
    )


async def _edit_review_blocks(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _sync_materials_repo(context, "review-blocks")
    grouped = _ready_review_topics_by_section(_services(context))
    if not grouped:
        await query.edit_message_text(
            "<b>Добавить повтор</b>\n\n"
            "В lk-prep пока нет ready-тем с читаемыми материалами.",
            parse_mode=ParseMode.HTML,
        )
        return
    await query.edit_message_text(
        _review_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_review_block_keyboard(grouped),
    )


def _ready_review_topics_by_section(services: AppServices) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for topic in services.repo.list_trainable_topics():
        section = topic.section or "Без блока"
        grouped.setdefault(section, []).append(topic)
    for topics in grouped.values():
        topics.sort(key=lambda item: (item.order_index or 10_000, item.title.lower()))
    return grouped


def _all_topics_by_section(services: AppServices) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for topic in services.repo.list_topics():
        if not _is_visible_catalog_topic(topic):
            continue
        section = topic.section or "Без блока"
        grouped.setdefault(section, []).append(topic)
    for topics in grouped.values():
        topics.sort(key=lambda item: (item.order_index or 10_000, item.title.lower()))
    return grouped


def _is_visible_catalog_topic(topic) -> bool:
    if topic.kind in ("book", "index", "reference"):
        return False
    if topic.kind == "discovered" and not topic.trainable:
        return False
    return True


@dataclass
class _SectionNode:
    label: str
    topics: list = field(default_factory=list)
    children: dict[str, "_SectionNode"] = field(default_factory=dict)


def _section_tree(grouped: dict[str, list]) -> _SectionNode:
    root = _SectionNode("")
    for section, topics in grouped.items():
        node = root
        for part in _section_parts(section):
            node = node.children.setdefault(part, _SectionNode(part))
        node.topics.extend(topics)
    return root


def _section_parts(section: str) -> list[str]:
    parts = [part.strip() for part in section.split("/") if part.strip()]
    return parts or ["Без блока"]


def _section_node_at(root: _SectionNode, path: tuple[int, ...]) -> _SectionNode | None:
    node = root
    for index in path:
        children = list(node.children.values())
        if index < 0 or index >= len(children):
            return None
        node = children[index]
    return node


def _section_path(raw_path: str) -> tuple[int, ...] | None:
    clean = raw_path.strip()
    if not clean:
        return ()
    parts = clean.split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def _section_path_data(path: tuple[int, ...]) -> str:
    return ".".join(str(index) for index in path)


def _section_child_path(path: tuple[int, ...], child_index: int) -> tuple[int, ...]:
    return (*path, child_index)


def _section_parent_path(path: tuple[int, ...]) -> tuple[int, ...]:
    return path[:-1]


def _section_total(node: _SectionNode) -> int:
    return len(node.topics) + sum(_section_total(child) for child in node.children.values())


def _section_ready_count(node: _SectionNode) -> int:
    return sum(1 for topic in node.topics if topic.status == "ready") + sum(
        _section_ready_count(child) for child in node.children.values()
    )


def _section_planned_count(node: _SectionNode) -> int:
    return sum(1 for topic in node.topics if topic.status == "planned") + sum(
        _section_planned_count(child) for child in node.children.values()
    )


def _section_topics(node: _SectionNode) -> list:
    topics = list(node.topics)
    for child in node.children.values():
        topics.extend(_section_topics(child))
    topics.sort(key=lambda item: (item.order_index or 10_000, item.title.lower()))
    return topics


def _section_title(root: _SectionNode, path: tuple[int, ...]) -> str:
    labels: list[str] = []
    node = root
    for index in path:
        children = list(node.children.values())
        if index < 0 or index >= len(children):
            break
        node = children[index]
        labels.append(node.label)
    return " / ".join(labels) if labels else "Блоки"


def _section_leaf_title(root: _SectionNode, path: tuple[int, ...]) -> str:
    node = _section_node_at(root, path)
    if not node:
        return "Блок"
    if len(path) <= 1:
        return node.label
    parent_title = _section_title(root, _section_parent_path(path))
    return f"{node.label} · {parent_title}"


def _section_tree_keyboard(
    grouped: dict[str, list],
    *,
    path: tuple[int, ...] = (),
    callback_prefix: str,
    root_callback: str,
    abort_callback: str,
) -> InlineKeyboardMarkup:
    root = _section_tree(grouped)
    node = _section_node_at(root, path) or root
    rows: list[list[InlineKeyboardButton]] = []
    for index, child in enumerate(node.children.values()):
        child_path = _section_child_path(path, index)
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(
                        f"{child.label} ({_section_ready_count(child)}/{_section_total(child)})"
                    ),
                    callback_data=f"{callback_prefix}{_section_path_data(child_path)}",
                )
            ]
        )
    if path:
        parent = _section_parent_path(path)
        rows.append(
            [
                InlineKeyboardButton(
                    "Назад",
                    callback_data=(
                        root_callback
                        if not parent
                        else f"{callback_prefix}{_section_path_data(parent)}"
                    ),
                )
            ]
        )
    rows.append([InlineKeyboardButton("Отмена", callback_data=abort_callback)])
    return InlineKeyboardMarkup(rows)


def _section_tree_text(title: str, grouped: dict[str, list], *, path: tuple[int, ...] = ()) -> str:
    root = _section_tree(grouped)
    node = _section_node_at(root, path) or root
    if not path:
        return (
            f"<b>{html.escape(title, quote=False)}</b>\n\n"
            f"Всего тем: <b>{_section_total(root)}</b>\n"
            f"Готово: <b>{_section_ready_count(root)}</b> · "
            f"В плане: <b>{_section_planned_count(root)}</b>\n\n"
            "Выбери блок."
        )
    return (
        f"<b>{html.escape(title, quote=False)}</b>\n\n"
        f"<b>{html.escape(_section_title(root, path), quote=False)}</b>\n"
        f"Тем: <b>{_section_total(node)}</b>\n\n"
        "Выбери раздел."
    )


def _section_selection(
    grouped: dict[str, list],
    raw_path: str,
) -> tuple[_SectionNode, tuple[int, ...]] | None:
    path = _section_path(raw_path)
    if path is None:
        return None
    root = _section_tree(grouped)
    node = _section_node_at(root, path)
    if node is None:
        return None
    return node, path


def _topic_blocks_text(grouped: dict[str, list], *, path: tuple[int, ...] = ()) -> str:
    return _section_tree_text("Темы", grouped, path=path)


def _topic_block_keyboard(
    grouped: dict[str, list],
    *,
    path: tuple[int, ...] = (),
) -> InlineKeyboardMarkup:
    return _section_tree_keyboard(
        grouped,
        path=path,
        callback_prefix=TOPIC_BLOCK_PREFIX,
        root_callback=TOPIC_BLOCKS,
        abort_callback=ABORT_TOPICS,
    )


def _topic_list_text(title: str, topics: list) -> str:
    if not topics:
        return "Темы не найдены."
    lines = [
        "<b>Темы</b>",
        f"Найдено: <b>{len(topics)}</b>",
        "",
        f"<b>{html.escape(title, quote=False)}</b>",
    ]
    lines.extend(_topic_menu_row(topic) for topic in topics)
    return "\n".join(lines)


def _topic_menu_row(topic) -> str:
    return (
        f"<code>{html.escape(topic.id, quote=False)}</code> · "
        f"{_topic_status_icon(topic.status)} "
        f"{html.escape(topic.title, quote=False)}"
    )


def _topic_status_icon(status: str) -> str:
    return {
        "ready": "✅",
        "planned": "⚪",
        "learning": "🕓",
    }.get(status, "•")


def _topic_section_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("К блокам", callback_data=TOPIC_BLOCKS)],
            [InlineKeyboardButton("Закрыть", callback_data=ABORT_TOPICS)],
        ]
    )


def _review_blocks_text(grouped: dict[str, list], *, path: tuple[int, ...] = ()) -> str:
    return _section_tree_text("Добавить повтор", grouped, path=path)


def _review_topics_text(section: str, topics: list) -> str:
    return (
        "<b>Добавить повтор</b>\n\n"
        f"<b>{html.escape(section, quote=False)}</b>\n"
        f"Тем: <b>{len(topics)}</b>\n\n"
        "Выбери тему."
    )


def _review_block_keyboard(
    grouped: dict[str, list],
    *,
    path: tuple[int, ...] = (),
) -> InlineKeyboardMarkup:
    return _section_tree_keyboard(
        grouped,
        path=path,
        callback_prefix=REVIEW_BLOCK_PREFIX,
        root_callback=REVIEW_ADD_BLOCKS,
        abort_callback=ABORT_REVIEW_ADD,
    )


def _review_topic_keyboard(topics: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for topic in topics:
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(f"{topic.id} · {topic.title}"),
                    callback_data=f"{REVIEW_TOPIC_PREFIX}{topic.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("К блокам", callback_data=REVIEW_ADD_BLOCKS)])
    rows.append([InlineKeyboardButton("Отмена", callback_data=ABORT_REVIEW_ADD)])
    return InlineKeyboardMarkup(rows)


def _explain_check_blocks_text(grouped: dict[str, list], *, path: tuple[int, ...] = ()) -> str:
    return _section_tree_text("Объяснить тему", grouped, path=path)


def _explain_check_topics_text(section: str, topics: list) -> str:
    return (
        "<b>Объяснить тему</b>\n\n"
        f"<b>{html.escape(section, quote=False)}</b>\n"
        f"Тем: <b>{len(topics)}</b>\n\n"
        "Выбери тему, которую расскажешь своими словами."
    )


def _explain_check_block_keyboard(
    grouped: dict[str, list],
    *,
    path: tuple[int, ...] = (),
) -> InlineKeyboardMarkup:
    return _section_tree_keyboard(
        grouped,
        path=path,
        callback_prefix=EXPLAIN_CHECK_BLOCK_PREFIX,
        root_callback=EXPLAIN_CHECK_BLOCKS,
        abort_callback=ABORT_EXPLAIN_CHECK,
    )


def _explain_check_topic_keyboard(topics: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for topic in topics:
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(f"{topic.id} · {topic.title}"),
                    callback_data=f"{EXPLAIN_CHECK_TOPIC_PREFIX}{topic.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("К блокам", callback_data=EXPLAIN_CHECK_BLOCKS)])
    rows.append([InlineKeyboardButton("Отмена", callback_data=ABORT_EXPLAIN_CHECK)])
    return InlineKeyboardMarkup(rows)


def _read_material_blocks_text(grouped: dict[str, list], *, path: tuple[int, ...] = ()) -> str:
    return _section_tree_text("Читать материал", grouped, path=path)


def _read_material_topics_text(section: str, topics: list) -> str:
    return (
        "<b>Читать материал</b>\n\n"
        f"<b>{html.escape(section, quote=False)}</b>\n"
        f"Тем: <b>{len(topics)}</b>\n\n"
        "Выбери тему."
    )


def _read_material_block_keyboard(
    grouped: dict[str, list],
    *,
    path: tuple[int, ...] = (),
) -> InlineKeyboardMarkup:
    return _section_tree_keyboard(
        grouped,
        path=path,
        callback_prefix=READ_MATERIAL_BLOCK_PREFIX,
        root_callback=READ_MATERIAL_BLOCKS,
        abort_callback=ABORT_READ_MATERIAL,
    )


def _read_material_topic_keyboard(topics: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for topic in topics:
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(f"{topic.id} · {topic.title}"),
                    callback_data=f"{READ_MATERIAL_TOPIC_PREFIX}{topic.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("К блокам", callback_data=READ_MATERIAL_BLOCKS)])
    rows.append([InlineKeyboardButton("Отмена", callback_data=ABORT_READ_MATERIAL)])
    return InlineKeyboardMarkup(rows)


def _material_github_url(base_url: str, source_path: str) -> str:
    return f"{base_url}/{source_path.lstrip('/')}"


def _read_material_links_text(topic_title: str, links: list[tuple[str, str]]) -> str:
    lines = [f"<b>{html.escape(topic_title, quote=False)}</b>", ""]
    for label, url in links:
        lines.append(f'📄 <a href="{html.escape(url)}">{html.escape(label, quote=False)}</a>')
    lines.append("")
    lines.append(
        "Открой ссылку в Telegram — материал отрендерится прямо во встроенном браузере."
    )
    return "\n".join(lines)


def _explain_check_prompt_text(topic_title: str) -> str:
    return (
        "<b>Расскажи своими словами</b>\n\n"
        f"Тема: <b>{html.escape(topic_title, quote=False)}</b>\n\n"
        "Без подглядывания в материал объясни, что помнишь: определения, "
        "нюансы, где встречается, где легко ошибиться.\n\n"
        "Ответь голосом или текстом следующим сообщением."
    )


def _review_explain_choice_text(topic_title: str) -> str:
    return (
        "<b>Пора повторить тему</b>\n\n"
        f"Тема: <b>{html.escape(topic_title, quote=False)}</b>\n\n"
        "Сначала объяснить своими словами без подглядывания в материал, а "
        "потом пройти тест? Так вспоминать активнее, чем сразу отвечать на "
        "вопросы теста."
    )


def _postpone_cancel_row(task_id: str) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton("Отложить", callback_data=f"{POSTPONE_DUE_PREFIX}{task_id}"),
        InlineKeyboardButton("Отменить", callback_data=f"{CANCEL_REVIEW_PREFIX}{task_id}"),
    ]


def _review_explain_choice_keyboard(task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🗣 Объяснить сначала",
                    callback_data=f"{EXPLAIN_THEN_REVIEW_PREFIX}{task_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "▶️ Сразу тест",
                    callback_data=f"{SKIP_EXPLAIN_REVIEW_PREFIX}{task_id}",
                )
            ],
            _postpone_cancel_row(task_id),
        ]
    )


def _review_ready_after_explain_text(topic_title: str) -> str:
    return (
        "<b>Объяснение готово</b>\n\n"
        f"Можно начинать тест по теме «{html.escape(topic_title, quote=False)}»."
    )


def _review_ready_after_explain_keyboard(task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "▶️ Начать тест",
                    callback_data=f"{SKIP_EXPLAIN_REVIEW_PREFIX}{task_id}",
                )
            ],
            _postpone_cancel_row(task_id),
        ]
    )


def _review_existing_keyboard(topic_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Сбросить повтор",
                    callback_data=f"{RESET_REVIEW_PREFIX}{topic_id}",
                )
            ],
            [InlineKeyboardButton("Оставить как есть", callback_data=ABORT_REVIEW_ADD)],
        ]
    )


async def _show_instant_blocks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _sync_materials_repo(context, "instant-blocks")
    grouped = _ready_review_topics_by_section(_services(context))
    if not grouped:
        await _answer_long(
            update,
            "<b>Пройти тест сейчас</b>\n\n"
            "В lk-prep пока нет ready-тем с читаемыми материалами.",
        )
        return
    if not update.message:
        return
    await update.message.reply_text(
        _instant_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_instant_block_keyboard(grouped),
    )


async def _show_open_question_blocks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _sync_materials_repo(context, "open-question-blocks")
    grouped = _ready_review_topics_by_section(_services(context))
    if not grouped:
        await _answer_long(
            update,
            "<b>Открытый вопрос</b>\n\n"
            "В lk-prep пока нет ready-тем с читаемыми материалами.",
        )
        return
    if not update.message:
        return
    await update.message.reply_text(
        _open_question_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_open_question_block_keyboard(grouped),
    )


async def _show_explain_check_blocks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _sync_materials_repo(context, "explain-check-blocks")
    grouped = _ready_review_topics_by_section(_services(context))
    if not grouped:
        await _answer_long(
            update,
            "<b>Объяснить тему</b>\n\n"
            "В lk-prep пока нет ready-тем с читаемыми материалами.",
        )
        return
    if not update.message:
        return
    await update.message.reply_text(
        _explain_check_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_explain_check_block_keyboard(grouped),
    )


async def _show_read_material_blocks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _sync_materials_repo(context, "read-material-blocks")
    grouped = _ready_review_topics_by_section(_services(context))
    if not grouped:
        await _answer_long(
            update,
            "<b>Читать материал</b>\n\n"
            "В lk-prep пока нет ready-тем с читаемыми материалами.",
        )
        return
    if not update.message:
        return
    await update.message.reply_text(
        _read_material_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_read_material_block_keyboard(grouped),
    )


async def _edit_instant_blocks(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _sync_materials_repo(context, "instant-blocks")
    grouped = _ready_review_topics_by_section(_services(context))
    if not grouped:
        await query.edit_message_text(
            "<b>Пройти тест сейчас</b>\n\n"
            "В lk-prep пока нет ready-тем с читаемыми материалами.",
            parse_mode=ParseMode.HTML,
        )
        return
    await query.edit_message_text(
        _instant_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_instant_block_keyboard(grouped),
    )


def _instant_blocks_text(grouped: dict[str, list], *, path: tuple[int, ...] = ()) -> str:
    return _section_tree_text("Пройти тест сейчас", grouped, path=path)


def _instant_topics_text(section: str, topics: list) -> str:
    return (
        "<b>Пройти тест сейчас</b>\n\n"
        f"<b>{html.escape(section, quote=False)}</b>\n"
        f"Тем: <b>{len(topics)}</b>\n\n"
        "Можно пройти тест по всему блоку или выбрать конкретную тему."
    )


def _open_question_blocks_text(grouped: dict[str, list], *, path: tuple[int, ...] = ()) -> str:
    return _section_tree_text("Открытый вопрос", grouped, path=path)


def _open_question_topics_text(section: str, topics: list) -> str:
    return (
        "<b>Открытый вопрос</b>\n\n"
        f"<b>{html.escape(section, quote=False)}</b>\n"
        f"Тем: <b>{len(topics)}</b>\n\n"
        "Выбери тему. Я сгенерирую один мини-кейс или открытый вопрос."
    )


def _instant_block_keyboard(
    grouped: dict[str, list],
    *,
    path: tuple[int, ...] = (),
) -> InlineKeyboardMarkup:
    return _section_tree_keyboard(
        grouped,
        path=path,
        callback_prefix=INSTANT_BLOCK_PREFIX,
        root_callback=INSTANT_BLOCKS,
        abort_callback=ABORT_INSTANT_QUIZ,
    )


def _open_question_block_keyboard(
    grouped: dict[str, list],
    *,
    path: tuple[int, ...] = (),
) -> InlineKeyboardMarkup:
    return _section_tree_keyboard(
        grouped,
        path=path,
        callback_prefix=OPEN_QUESTION_BLOCK_PREFIX,
        root_callback=OPEN_QUESTION_BLOCKS,
        abort_callback=ABORT_OPEN_QUESTION,
    )


def _instant_topic_keyboard(section_path: str, topics: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                "Весь блок",
                callback_data=f"{INSTANT_BLOCK_ALL_PREFIX}{section_path}",
            )
        ]
    ]
    for topic in topics:
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(f"{topic.id} · {topic.title}"),
                    callback_data=f"{INSTANT_TOPIC_PREFIX}{topic.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("К блокам", callback_data=INSTANT_BLOCKS)])
    rows.append([InlineKeyboardButton("Отмена", callback_data=ABORT_INSTANT_QUIZ)])
    return InlineKeyboardMarkup(rows)


def _open_question_topic_keyboard(topics: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for topic in topics:
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(f"{topic.id} · {topic.title}"),
                    callback_data=f"{OPEN_QUESTION_TOPIC_PREFIX}{topic.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("К блокам", callback_data=OPEN_QUESTION_BLOCKS)])
    rows.append([InlineKeyboardButton("Отмена", callback_data=ABORT_OPEN_QUESTION)])
    return InlineKeyboardMarkup(rows)


async def _show_daily_quiz_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _services(context)
    if not update.message:
        return
    await update.message.reply_text(
        _daily_quiz_settings_text(services, context),
        parse_mode=ParseMode.HTML,
        reply_markup=_daily_quiz_settings_keyboard(
            services.daily_quiz.is_enabled(),
            len(services.daily_quiz.list_outstanding()),
        ),
    )


async def _show_coding_reps_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _services(context)
    if not update.message:
        return
    await update.message.reply_text(
        _coding_reps_settings_text(services),
        parse_mode=ParseMode.HTML,
        reply_markup=_coding_reps_settings_keyboard(services.coding_reps.is_enabled()),
    )


async def _show_llm_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _services(context)
    if not update.message:
        return
    await update.message.reply_text(
        format_llm_usage_report(
            services.llm_usage.stats_for_periods(),
            prices_configured=services.llm_usage.prices_configured,
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=_settings_menu_keyboard(),
    )


async def _show_changelog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        _format_changelog_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=_settings_menu_keyboard(),
    )


def _daily_quiz_settings_text(
    services: AppServices,
    context: ContextTypes.DEFAULT_TYPE,
) -> str:
    settings = services.settings
    enabled = services.daily_quiz.is_enabled()
    status = "включены" if enabled else "выключены"
    ready_count = len(services.daily_quiz.ready_topics())
    outstanding_count = len(services.daily_quiz.list_outstanding())
    last_sent = services.daily_quiz.last_sent_date() or "еще не отправлялся"
    return "\n".join(
        [
            "<b>Ежедневные тесты</b>",
            "",
            f"<b>Статус:</b> {html.escape(status, quote=False)}",
            f"<b>Время:</b> <code>{settings.daily_quiz_hour:02d}:{settings.daily_quiz_minute:02d}</code>",
            f"<b>Таймзона:</b> <code>{html.escape(settings.daily_quiz_timezone, quote=False)}</code>",
            f"<b>Готовых тем:</b> {ready_count}",
            f"<b>Незавершено:</b> {outstanding_count}",
            f"<b>Последняя отправка:</b> <code>{html.escape(last_sent, quote=False)}</code>",
            "",
            "Если режим включен, утром бот пришлет случайную ready-тему с кнопками: "
            "пройти тест, отложить или пропустить. Отложенные и начатые тесты не "
            "теряются — их можно найти в «Незавершенные тесты» ниже.",
        ]
    )


def _daily_quiz_settings_keyboard(enabled: bool, outstanding_count: int) -> InlineKeyboardMarkup:
    next_value = "false" if enabled else "true"
    label = "Выключить" if enabled else "Включить"
    outstanding_label = "📋 Незавершенные тесты"
    if outstanding_count:
        outstanding_label = f"{outstanding_label} ({outstanding_count})"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=f"{DAILY_QUIZ_TOGGLE_PREFIX}{next_value}")],
            [InlineKeyboardButton(outstanding_label, callback_data=MENU_DAILY_QUIZ_OUTSTANDING)],
        ]
    )


def _daily_quiz_offer_text(topic) -> str:
    lines = [
        "<b>Ежедневный случайный тест</b>",
        "",
        f"<b>Тема:</b> {html.escape(topic.title, quote=False)}",
    ]
    if topic.section:
        lines.append(f"<b>Блок:</b> {html.escape(topic.section, quote=False)}")
    lines.extend(
        [
            "",
            "Можно пройти сейчас, отложить на потом или пропустить сегодня.",
        ]
    )
    return "\n".join(lines)


def _daily_quiz_offer_keyboard(offer_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Пройти", callback_data=f"{DAILY_QUIZ_START_PREFIX}{offer_id}"),
                InlineKeyboardButton("Отложить", callback_data=f"{DAILY_QUIZ_POSTPONE_PREFIX}{offer_id}"),
            ],
            [InlineKeyboardButton("Пропустить", callback_data=f"{DAILY_QUIZ_SKIP_PREFIX}{offer_id}")],
        ]
    )


_DAILY_QUIZ_STATUS_LABELS = {
    PENDING: "новый",
    STARTED: "начат, не завершен",
    POSTPONED: "отложен",
    SKIPPED: "пропущен",
    DONE: "пройден",
}


def _daily_quiz_offer_detail_text(offer) -> str:
    lines = [
        "<b>Ежедневный тест</b>",
        "",
        f"<b>Тема:</b> {html.escape(offer.topic_title, quote=False)}",
    ]
    if offer.section:
        lines.append(f"<b>Блок:</b> {html.escape(offer.section, quote=False)}")
    lines.extend(
        [
            f"<b>Дата:</b> <code>{html.escape(offer.offer_date, quote=False)}</code>",
            f"<b>Статус:</b> {_DAILY_QUIZ_STATUS_LABELS.get(offer.status, offer.status)}",
        ]
    )
    return "\n".join(lines)


def _daily_quiz_offer_detail_keyboard(offer_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Пройти", callback_data=f"{DAILY_QUIZ_START_PREFIX}{offer_id}"),
                InlineKeyboardButton("Отложить", callback_data=f"{DAILY_QUIZ_POSTPONE_PREFIX}{offer_id}"),
            ],
            [
                InlineKeyboardButton("Готово", callback_data=f"{DAILY_QUIZ_DONE_PREFIX}{offer_id}"),
                InlineKeyboardButton("Пропустить", callback_data=f"{DAILY_QUIZ_SKIP_PREFIX}{offer_id}"),
            ],
            [InlineKeyboardButton("К списку", callback_data=MENU_DAILY_QUIZ_OUTSTANDING)],
        ]
    )


def _daily_quiz_outstanding_text(offers: list) -> str:
    if not offers:
        return "<b>Незавершенные ежедневные тесты</b>\n\nПусто — все разобрано."
    return "\n".join(
        [
            "<b>Незавершенные ежедневные тесты</b>",
            "",
            f"Всего: <b>{len(offers)}</b>",
            "",
            "Выбери, чтобы открыть.",
        ]
    )


_DAILY_QUIZ_STATUS_ICONS = {PENDING: "🆕", STARTED: "▶️", POSTPONED: "⏸"}


def _daily_quiz_outstanding_keyboard(offers: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for offer in offers:
        icon = _DAILY_QUIZ_STATUS_ICONS.get(offer.status, "•")
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(f"{icon} {offer.offer_date} · {offer.topic_title}"),
                    callback_data=f"{DAILY_QUIZ_OPEN_PREFIX}{offer.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("К настройкам", callback_data=MENU_DAILY_SETTINGS)])
    return InlineKeyboardMarkup(rows)


def _coding_reps_settings_text(services: AppServices) -> str:
    settings = services.settings
    enabled = services.coding_reps.is_enabled()
    status = "включены" if enabled else "выключены"
    last_sent = services.coding_reps.last_sent_date() or "еще не отправлялся"
    return "\n".join(
        [
            "<b>Кодинг-репы</b>",
            "",
            f"<b>Статус:</b> {html.escape(status, quote=False)}",
            f"<b>Время:</b> <code>{settings.coding_reps_hour:02d}:{settings.coding_reps_minute:02d}</code>",
            f"<b>Таймзона:</b> <code>{html.escape(settings.daily_quiz_timezone, quote=False)}</code>",
            f"<b>Последняя отправка:</b> <code>{html.escape(last_sent, quote=False)}</code>",
            "",
            "Если режим включен, бот раз в день присылает короткое "
            "упражнение на 20-30 минут — написать руками, не в боте. "
            "Бот не пишет и не проверяет код, только напоминает.",
        ]
    )


def _coding_reps_settings_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    next_value = "false" if enabled else "true"
    label = "Выключить" if enabled else "Включить"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"{CODING_REPS_TOGGLE_PREFIX}{next_value}")]]
    )


def _coding_rep_offer_text(rep) -> str:
    return "\n".join(
        [
            "<b>Кодинг-реп на сегодня</b>",
            "",
            f"<b>{html.escape(rep.title, quote=False)}</b>",
            "",
            html.escape(rep.prompt, quote=False),
            "",
            "Отметь, когда сделаешь или если сегодня решил пропустить.",
        ]
    )


def _coding_rep_offer_keyboard(log_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Сделал",
                    callback_data=f"{CODING_REPS_DONE_PREFIX}{log_id}",
                ),
                InlineKeyboardButton(
                    "Пропустить",
                    callback_data=f"{CODING_REPS_SKIP_PREFIX}{log_id}",
                ),
            ]
        ]
    )


def _button_label(value: str, *, limit: int = 58) -> str:
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


def _format_existing_review_prompt(task) -> str:
    return "\n".join(
        [
            "<b>Такая активная задача уже есть</b>",
            "",
            format_task(task),
            "",
            "Можно оставить текущий график или сбросить повтор: начать снова с этапа 1.",
        ]
    )


def _format_review_reset_done(task) -> str:
    return "\n".join(
        [
            "<b>Повтор сброшен</b>",
            "",
            format_task(task),
            "",
            "Новая цепочка началась с этапа 1.",
        ]
    )


async def _create_review_task_from_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str,
    *,
    source: str = "text",
) -> None:
    services = _services(context)
    clean_query = query.strip()
    if not clean_query:
        await _answer_long(update, "Не вижу название темы. Попробуй написать или надиктовать еще раз.")
        return

    started_at = perf_counter()
    log.info(
        "Review task creation started source=%s query_len=%s",
        source,
        len(clean_query),
    )
    await _answer_long(update, format_review_creation_started(clean_query))
    try:
        result = await asyncio.to_thread(services.review_tasks.create_review_task, clean_query)
    except TopicNotReadyError as exc:
        log.info(
            "Review task creation not created source=%s elapsed=%.2fs reason=%s",
            source,
            perf_counter() - started_at,
            exc.reason,
        )
        await _answer_long(update, format_topic_not_ready(exc))
        return
    except Exception:
        log.exception(
            "Review task creation failed source=%s elapsed=%.2fs",
            source,
            perf_counter() - started_at,
        )
        await _answer_long(
            update,
            "Не смог создать задачу на повторение.\n\n"
            "Попробуй еще раз или проверь логи локального запуска.",
        )
        return
    log.info(
        "Review task creation finished source=%s task_id=%s created=%s elapsed=%.2fs",
        source,
        result.task.id,
        result.created,
        perf_counter() - started_at,
    )
    await _answer_long(
        update,
        format_review_created(
            result.task,
            created=result.created,
            source_paths=result.topic.source_paths,
        ),
    )


async def _edit_wait_target(
    target,
    text: str,
    *,
    parse_mode: str | None = None,
    reply_markup=None,
):
    try:
        if hasattr(target, "edit_text"):
            return await target.edit_text(
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        return await target.edit_message_text(
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            return target
        if "Message can't be edited" in str(exc) and hasattr(target, "reply_text"):
            log.warning("Telegram refused to edit wait message, sending fallback reply: %s", exc)
            return await target.reply_text(
                text,
                parse_mode=parse_mode,
                reply_markup=reply_markup or _main_keyboard(),
            )
        raise


async def _stop_animation_task(task) -> None:
    if not task or task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _format_wait_elapsed(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} сек."
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} мин. {rest:02d} сек."


async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_non_owner(update, context):
        return
    await _show_schedule(update, context)


async def due(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_non_owner(update, context):
        return
    await _show_due(update, context)


async def _show_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tasks = _services(context).review_tasks.upcoming(limit=20)
    await _answer_long(
        update,
        format_tasks(
            tasks,
            empty_text="Активных задач на повторение нет.",
            title="Ближайшие повторы",
        ),
    )


async def _show_due(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tasks = _services(context).review_tasks.due_tasks(now=datetime.now(), limit=20)
    text = format_tasks(
        tasks,
        empty_text="Сейчас нет задач, которые пора повторять.",
        title="Пора повторять",
    )
    if not tasks:
        await _answer_long(update, text)
        return
    if not update.message:
        return
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=_due_tasks_keyboard(tasks),
    )


async def _show_cancel_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tasks = _services(context).review_tasks.upcoming(limit=20)
    text = format_cancel_review_list(tasks)
    if not update.message:
        return
    if not tasks:
        await _answer_long(update, text)
        return
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=_cancel_review_keyboard(tasks),
    )


def _answer_keyboard(session: QuizSession, question: QuizQuestion) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            ANSWER_LABELS[index],
            callback_data=f"{QUIZ_ANSWER_PREFIX}{session.id}:{question.id}:{index}",
        )
        for index in range(len(question.options))
    ]
    return InlineKeyboardMarkup([buttons])


def _mistake_questions(questions, answers) -> list[tuple[QuizQuestion, object | None]]:
    answer_by_question = {answer.question_id: answer for answer in answers}
    mistakes: list[tuple[QuizQuestion, object | None]] = []
    for question in questions:
        answer = answer_by_question.get(question.id)
        if not answer or not answer.is_correct:
            mistakes.append((question, answer))
    return mistakes


def _mistake_review_input(
    services: AppServices,
    session: QuizSession,
    questions,
    answers,
) -> MistakeReviewInput:
    mistakes = []
    for question, answer in _mistake_questions(questions, answers):
        selected_index = answer.selected_index if answer else -1
        selected_label = (
            ANSWER_LABELS[selected_index]
            if 0 <= selected_index < len(ANSWER_LABELS)
            else "-"
        )
        selected_text = (
            question.options[selected_index]
            if 0 <= selected_index < len(question.options)
            else "нет ответа"
        )
        correct_label = ANSWER_LABELS[question.correct_index]
        correct_text = question.options[question.correct_index]
        mistakes.append(
            {
                "question_no": question.question_no,
                "question": question.text,
                "selected_label": selected_label,
                "selected_text": selected_text,
                "correct_label": correct_label,
                "correct_text": correct_text,
                "explanation": question.explanation,
                "source_refs": question.source_refs,
            }
        )
    topic_title = session.topic_title or str(session.material_snapshot.get("topic_title") or session.topic_id)
    return MistakeReviewInput(
        quiz_session_id=session.id,
        topic_id=session.topic_id,
        topic_title=topic_title,
        section=_session_section(services, session),
        session_type=session.session_type,
        score_percent=float(session.score_percent or 0),
        correct_count=int(session.correct_count or 0),
        total_count=int(session.total_count or len(questions)),
        mistakes=mistakes,
        material_context=_material_context(services, session),
    )


def _session_section(services: AppServices, session: QuizSession) -> str:
    topic = services.repo.get_topic(session.topic_id)
    if topic and topic.section:
        return topic.section
    title = str(session.material_snapshot.get("topic_title") or "")
    if title.startswith("Блок: "):
        return title.removeprefix("Блок: ").strip()
    return ""


def _material_context(services: AppServices, session: QuizSession) -> list[dict[str, object]]:
    repo_path = services.repo.repo_path
    raw_paths = session.material_snapshot.get("source_paths")
    if not repo_path or not isinstance(raw_paths, list):
        return []
    context: list[dict[str, object]] = []
    total_chars = 0
    for raw_path in raw_paths[:8]:
        rel = str(raw_path).strip()
        if not rel:
            continue
        material = services.repo.read_material(rel)
        if material is None:
            continue
        excerpt = material.content[:3000]
        total_chars += len(excerpt)
        context.append(_material_context_entry(material, excerpt))
        if total_chars >= 10000:
            break
    return context


def _cancel_review_keyboard(tasks) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for task in tasks:
        label = f"{task.due_at:%d-%m-%Y} · {task.stage}/3 · {task.topic_title}"
        if len(label) > 58:
            label = f"{label[:55]}..."
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"{CANCEL_REVIEW_PREFIX}{task.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("Отмена", callback_data=ABORT_CANCEL_REVIEW)])
    return InlineKeyboardMarkup(rows)


def _due_tasks_keyboard(tasks) -> InlineKeyboardMarkup:
    """One "Начать" button per due task - reuses START_REVIEW_PREFIX, the same
    entry point as the due-notification message, so a postponed/ignored task
    is not just visible here but actually actionable."""
    rows: list[list[InlineKeyboardButton]] = []
    for task in tasks:
        label = f"{task.due_at:%d-%m-%Y} · {task.stage}/3 · {task.topic_title}"
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(label),
                    callback_data=f"{START_REVIEW_PREFIX}{task.id}",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def _confirm_cancel_review_keyboard(task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Удалить",
                    callback_data=f"{CONFIRM_CANCEL_REVIEW_PREFIX}{task_id}",
                )
            ],
            [InlineKeyboardButton("Не удалять", callback_data=ABORT_CANCEL_REVIEW)],
        ]
    )


def _generation_wait_text(
    *,
    topic_title: str,
    question_count: int,
    frame: str,
    elapsed_seconds: int = 0,
) -> str:
    return (
        f"{frame} Запрос на генерацию теста отправлен агенту. Жду ответ...\n\n"
        f"Тема: {topic_title}\n"
        f"Вопросов: {question_count}\n"
        f"Ожидание: {_format_wait_elapsed(elapsed_seconds)}\n\n"
        "Это может занять 1-3 минуты."
    )


def _open_question_wait_text(
    *,
    title: str,
    action: str,
    frame: str,
    elapsed_seconds: int = 0,
) -> str:
    return (
        f"{frame} <b>{html.escape(action, quote=False)}</b>\n\n"
        f"Тема: {html.escape(title, quote=False)}\n"
        f"Ожидание: {_format_wait_elapsed(elapsed_seconds)}\n\n"
        "Агент читает материалы и рубрику, это может занять немного времени."
    )


async def _animate_open_question_message(query, *, title: str, action: str) -> None:
    index = 0
    started_at = perf_counter()
    while True:
        await asyncio.sleep(3)
        index += 1
        elapsed = int(perf_counter() - started_at)
        if index == 1 or index % 4 == 0:
            log.info("Open question still waiting action=%s title=%s elapsed=%ss", action, title, elapsed)
        with contextlib.suppress(Exception):
            await query.edit_message_text(
                _open_question_wait_text(
                    title=title,
                    action=action,
                    frame=GENERATION_FRAMES[index % len(GENERATION_FRAMES)],
                    elapsed_seconds=elapsed,
                ),
                parse_mode=ParseMode.HTML,
            )


async def _animate_open_question_reply_message(message, *, title: str, action: str) -> None:
    index = 0
    started_at = perf_counter()
    while True:
        await asyncio.sleep(3)
        index += 1
        elapsed = int(perf_counter() - started_at)
        if index == 1 or index % 4 == 0:
            log.info("Open question reply still waiting action=%s title=%s elapsed=%ss", action, title, elapsed)
        with contextlib.suppress(Exception):
            await message.edit_text(
                _open_question_wait_text(
                    title=title,
                    action=action,
                    frame=GENERATION_FRAMES[index % len(GENERATION_FRAMES)],
                    elapsed_seconds=elapsed,
                ),
                parse_mode=ParseMode.HTML,
            )


def _quiz_size_text(*, title: str, scope: str) -> str:
    return "\n".join(
        [
            f"<b>{html.escape(scope, quote=False)}</b>",
            "",
            f"<b>Тема:</b> {html.escape(title, quote=False)}",
            "",
            "Сколько вопросов сделать?",
        ]
    )


def _quiz_size_keyboard(mode: str, target: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for left, right in zip(QUIZ_SIZE_OPTIONS[::2], QUIZ_SIZE_OPTIONS[1::2]):
        rows.append(
            [
                InlineKeyboardButton(
                    f"{left} вопросов",
                    callback_data=f"{QUIZ_SIZE_PREFIX}{mode}:{target}:{left}",
                ),
                InlineKeyboardButton(
                    f"{right} вопросов",
                    callback_data=f"{QUIZ_SIZE_PREFIX}{mode}:{target}:{right}",
                ),
            ]
        )
    rows.append([InlineKeyboardButton("Отмена", callback_data=ABORT_QUIZ_SIZE)])
    return InlineKeyboardMarkup(rows)


async def _show_quiz_size_choice(
    query,
    *,
    title: str,
    scope: str,
    mode: str,
    target: str,
) -> None:
    await query.edit_message_text(
        _quiz_size_text(title=title, scope=scope),
        parse_mode=ParseMode.HTML,
        reply_markup=_quiz_size_keyboard(mode, target),
    )


async def _animate_generation_message(query, *, topic_title: str, question_count: int) -> None:
    index = 0
    started_at = perf_counter()
    while True:
        await asyncio.sleep(3)
        index += 1
        elapsed = int(perf_counter() - started_at)
        if index == 1 or index % 4 == 0:
            log.info(
                "Quiz generation still waiting topic_title=%s question_count=%s elapsed=%ss",
                topic_title,
                question_count,
                elapsed,
            )
        with contextlib.suppress(Exception):
            await query.edit_message_text(
                _generation_wait_text(
                    topic_title=topic_title,
                    question_count=question_count,
                    frame=GENERATION_FRAMES[index % len(GENERATION_FRAMES)],
                    elapsed_seconds=elapsed,
                )
            )


async def _start_instant_quiz(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    topic_title: str,
    question_count: int,
    start_call,
) -> None:
    log.info(
        "Starting instant quiz from Telegram topic_title=%s questions=%s",
        topic_title,
        question_count,
    )
    await query.edit_message_text(
        _generation_wait_text(
            topic_title=topic_title,
            question_count=question_count,
            frame=GENERATION_FRAMES[0],
        )
    )
    animation_task = asyncio.create_task(
        _animate_generation_message(
            query,
            topic_title=topic_title,
            question_count=question_count,
        )
    )
    try:
        result = await asyncio.to_thread(
            start_call,
            question_count=question_count,
        )
    except QuizGenerationError as exc:
        log.exception("Instant quiz generation failed topic_title=%s", topic_title)
        await query.edit_message_text(
            _generation_error_text(
                exc,
                "Не удалось сгенерировать моментальный тест.\n\n"
                f"Причина: {html.escape(str(exc), quote=False)}\n\n"
                "Попробуй позже.",
            ),
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as exc:
        log.exception("Failed to start instant quiz topic_title=%s", topic_title)
        await query.edit_message_text(
            "Не удалось запустить моментальный тест.\n\n"
            f"Причина: {html.escape(str(exc), quote=False)}"
        )
        return
    finally:
        if not animation_task.done():
            animation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await animation_task

    log.info(
        "Instant quiz session ready session_id=%s topic_id=%s questions=%s",
        result.session.id,
        result.session.topic_id,
        result.session.question_count,
    )
    await query.edit_message_text(
        text=format_quiz_question(result.session, result.question),
        reply_markup=_answer_keyboard(result.session, result.question),
        parse_mode=ParseMode.HTML,
    )


async def _start_review_quiz(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    task_id: str,
    question_count: int,
) -> None:
    services = _services(context)
    try:
        task = services.review_tasks.get_task(task_id)
    except ValueError:
        await query.edit_message_text("Задача не найдена. Возможно, она уже устарела.")
        return

    log.info(
        "Starting quiz from Telegram callback task_id=%s topic_id=%s questions=%s",
        task.id,
        task.topic_id,
        question_count,
    )
    await query.edit_message_text(
        _generation_wait_text(
            topic_title=task.topic_title,
            question_count=question_count,
            frame=GENERATION_FRAMES[0],
        )
    )
    animation_task = asyncio.create_task(
        _animate_generation_message(
            query,
            topic_title=task.topic_title,
            question_count=question_count,
        )
    )
    try:
        result = await asyncio.to_thread(
            services.quiz.start_session,
            task_id,
            question_count=question_count,
        )
    except QuizGenerationError as exc:
        animation_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await animation_task
        log.exception("Quiz generation failed for task_id=%s", task_id)
        await query.edit_message_text(
            _generation_error_text(
                exc,
                "Не удалось сгенерировать тест.\n\n"
                f"Причина: {html.escape(str(exc), quote=False)}\n\n"
                "Попробуй позже.",
            ),
            parse_mode=ParseMode.HTML,
        )
        return
    except ValueError:
        animation_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await animation_task
        log.exception("Failed to start quiz session for task_id=%s", task_id)
        await query.edit_message_text("Задача не найдена. Возможно, она уже устарела.")
        return
    finally:
        if not animation_task.done():
            animation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await animation_task

    log.info(
        "Quiz session ready task_id=%s session_id=%s questions=%s",
        task_id,
        result.session.id,
        result.session.question_count,
    )
    await query.edit_message_text(
        text=format_quiz_question(result.session, result.question),
        reply_markup=_answer_keyboard(result.session, result.question),
        parse_mode=ParseMode.HTML,
    )


async def instant_blocks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    await _edit_instant_blocks(query, context)


async def open_question_blocks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    await _sync_materials_repo(context, "open-question-blocks")
    grouped = _ready_review_topics_by_section(_services(context))
    if not grouped:
        await query.edit_message_text(
            "<b>Открытый вопрос</b>\n\n"
            "В lk-prep пока нет ready-тем с читаемыми материалами.",
            parse_mode=ParseMode.HTML,
        )
        return
    await query.edit_message_text(
        _open_question_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_open_question_block_keyboard(grouped),
    )


async def menu_schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    tasks = _services(context).review_tasks.upcoming(limit=20)
    await query.edit_message_text(
        format_tasks(
            tasks,
            empty_text="Активных задач на повторение нет.",
            title="Ближайшие повторы",
        ),
        parse_mode=ParseMode.HTML,
    )


async def menu_due_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    tasks = _services(context).review_tasks.due_tasks(now=datetime.now(), limit=20)
    await query.edit_message_text(
        format_tasks(
            tasks,
            empty_text="Сейчас нет задач, которые пора повторять.",
            title="Пора повторять",
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=_due_tasks_keyboard(tasks) if tasks else None,
    )


async def menu_cancel_reviews_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    tasks = _services(context).review_tasks.upcoming(limit=20)
    await query.edit_message_text(
        format_cancel_review_list(tasks),
        parse_mode=ParseMode.HTML,
        reply_markup=_cancel_review_keyboard(tasks) if tasks else None,
    )


async def menu_topic_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    context.user_data["awaiting_study_topic"] = True
    context.user_data["awaiting_review_topic"] = False
    await query.answer()
    await query.edit_message_text(
        format_study_topic_prompt(),
        parse_mode=ParseMode.HTML,
    )


async def menu_study_topics_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    await query.edit_message_text(
        "<b>💡 Inbox идей</b>\n\n"
        "Сохраняй сюда голосовые и текстовые мысли: что изучить, почитать, реализовать, написать или доработать.",
        parse_mode=ParseMode.HTML,
        reply_markup=_study_topics_menu_keyboard(),
    )


async def menu_topic_inbox_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    items = _services(context).topic_inbox.list_active(limit=20)
    await query.edit_message_text(
        format_topic_inbox_list(items),
        parse_mode=ParseMode.HTML,
        reply_markup=_topic_inbox_keyboard(items) if items else None,
    )


async def menu_mistake_work_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    items = _services(context).mistake_work.list_active(limit=20)
    await query.edit_message_text(
        format_mistake_work_list(items, status_title="Активные отчеты"),
        parse_mode=ParseMode.HTML,
        reply_markup=_mistake_work_list_keyboard(items) if items else _mistake_work_menu_keyboard(),
    )


async def menu_mistake_work_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    items = _services(context).mistake_work.list_done(limit=20)
    await query.edit_message_text(
        format_mistake_work_list(items, status_title="Проработанные отчеты"),
        parse_mode=ParseMode.HTML,
        reply_markup=_mistake_work_list_keyboard(items) if items else _mistake_work_menu_keyboard(),
    )


async def mistake_work_open_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    item_id = (query.data or "").removeprefix(MISTAKE_WORK_OPEN_PREFIX).strip()
    item = _services(context).mistake_work.get_item(item_id)
    if not item:
        await query.answer("Отчет не найден.", show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(
        format_mistake_work_item(item),
        parse_mode=ParseMode.HTML,
        reply_markup=_mistake_work_item_keyboard(item.id, status=item.status),
    )


async def mistake_work_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    item_id = (query.data or "").removeprefix(MISTAKE_WORK_DONE_PREFIX).strip()
    try:
        item = _services(context).mistake_work.mark_done(item_id)
    except ValueError:
        await query.answer("Отчет не найден.", show_alert=True)
        return
    await query.answer("Готово")
    await query.edit_message_text(
        format_mistake_work_item(item),
        parse_mode=ParseMode.HTML,
        reply_markup=_mistake_work_item_keyboard(item.id, status=item.status),
    )


async def mistake_work_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    item_id = (query.data or "").removeprefix(MISTAKE_WORK_DELETE_PREFIX).strip()
    try:
        _services(context).mistake_work.delete_item(item_id)
    except ValueError:
        await query.answer("Отчет не найден.", show_alert=True)
        return
    await query.answer("Удалено")
    items = _services(context).mistake_work.list_active(limit=20)
    await query.edit_message_text(
        format_mistake_work_list(items, status_title="Активные отчеты"),
        parse_mode=ParseMode.HTML,
        reply_markup=_mistake_work_list_keyboard(items) if items else _mistake_work_menu_keyboard(),
    )


async def menu_open_questions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    items = _services(context).open_questions.list_active(limit=20)
    await query.edit_message_text(
        format_open_question_list(items, status_title="Открытые вопросы без ответа"),
        parse_mode=ParseMode.HTML,
        reply_markup=_open_question_list_keyboard(items) if items else _ideas_menu_keyboard(),
    )


async def menu_open_questions_answered_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    items = _services(context).open_questions.list_answered(limit=20)
    await query.edit_message_text(
        format_open_question_list(items, status_title="Проверенные открытые вопросы"),
        parse_mode=ParseMode.HTML,
        reply_markup=(
            _open_question_list_keyboard(items, show_answered_link=False)
            if items
            else _ideas_menu_keyboard()
        ),
    )


async def menu_explain_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    await query.edit_message_text(
        "<b>🗣 Объяснить тему</b>\n\n"
        "Расскажи тему своими словами без подглядывания в материал — агент "
        "сверит с эталоном и покажет, что упущено.",
        parse_mode=ParseMode.HTML,
        reply_markup=_explain_check_menu_keyboard(),
    )


async def menu_explain_check_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    items = _services(context).explain_check.list_active(limit=20)
    await query.edit_message_text(
        format_explain_check_list(items, status_title="Мои объяснения"),
        parse_mode=ParseMode.HTML,
        reply_markup=_explain_check_list_keyboard(items) if items else _explain_check_menu_keyboard(),
    )


async def menu_explain_check_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    items = _services(context).explain_check.list_done(limit=20)
    await query.edit_message_text(
        format_explain_check_list(items, status_title="Разобранные объяснения"),
        parse_mode=ParseMode.HTML,
        reply_markup=_explain_check_list_keyboard(items) if items else _explain_check_menu_keyboard(),
    )


async def explain_check_open_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    item_id = (query.data or "").removeprefix(EXPLAIN_CHECK_OPEN_PREFIX).strip()
    item = _services(context).explain_check.get_item(item_id)
    if not item:
        await query.answer("Запись не найдена.", show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(
        format_explain_check_report(item),
        parse_mode=ParseMode.HTML,
        reply_markup=_explain_check_item_keyboard(item.id, status=item.status),
    )


async def explain_check_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    item_id = (query.data or "").removeprefix(EXPLAIN_CHECK_DONE_PREFIX).strip()
    try:
        item = _services(context).explain_check.mark_done(item_id)
    except ValueError:
        await query.answer("Запись не найдена.", show_alert=True)
        return
    await query.answer("Готово")
    await query.edit_message_text(
        format_explain_check_report(item),
        parse_mode=ParseMode.HTML,
        reply_markup=_explain_check_item_keyboard(item.id, status=item.status),
    )


async def explain_check_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    item_id = (query.data or "").removeprefix(EXPLAIN_CHECK_DELETE_PREFIX).strip()
    try:
        _services(context).explain_check.delete_item(item_id)
    except ValueError:
        await query.answer("Запись не найдена.", show_alert=True)
        return
    await query.answer("Удалено")
    items = _services(context).explain_check.list_active(limit=20)
    await query.edit_message_text(
        format_explain_check_list(items, status_title="Мои объяснения"),
        parse_mode=ParseMode.HTML,
        reply_markup=_explain_check_list_keyboard(items) if items else _explain_check_menu_keyboard(),
    )


async def menu_daily_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    services = _services(context)
    await query.answer()
    await query.edit_message_text(
        _daily_quiz_settings_text(services, context),
        parse_mode=ParseMode.HTML,
        reply_markup=_daily_quiz_settings_keyboard(
            services.daily_quiz.is_enabled(),
            len(services.daily_quiz.list_outstanding()),
        ),
    )


async def menu_coding_reps_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    services = _services(context)
    await query.answer()
    await query.edit_message_text(
        _coding_reps_settings_text(services),
        parse_mode=ParseMode.HTML,
        reply_markup=_coding_reps_settings_keyboard(services.coding_reps.is_enabled()),
    )


async def menu_llm_usage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    services = _services(context)
    await query.answer()
    await query.edit_message_text(
        format_llm_usage_report(
            services.llm_usage.stats_for_periods(),
            prices_configured=services.llm_usage.prices_configured,
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=_settings_menu_keyboard(),
    )


async def menu_changelog_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    await query.edit_message_text(
        _format_changelog_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=_settings_menu_keyboard(),
    )


async def daily_quiz_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    raw_value = (query.data or "").removeprefix(DAILY_QUIZ_TOGGLE_PREFIX)
    enabled = raw_value == "true"
    services = _services(context)
    services.daily_quiz.set_enabled(enabled)
    await query.answer("Включено" if enabled else "Выключено")
    log.info("Daily quiz toggled enabled=%s", enabled)
    await query.edit_message_text(
        _daily_quiz_settings_text(services, context),
        parse_mode=ParseMode.HTML,
        reply_markup=_daily_quiz_settings_keyboard(
            enabled,
            len(services.daily_quiz.list_outstanding()),
        ),
    )


async def daily_quiz_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    services = _services(context)
    payload = (query.data or "").removeprefix(DAILY_QUIZ_START_PREFIX).strip()
    offer = services.daily_quiz.get_offer(payload)
    if offer:
        topic = services.repo.get_topic(offer.topic_id)
        if topic:
            services.daily_quiz.set_status(offer.id, STARTED)
    else:
        # Pre-migration offer message: payload is a bare topic_id, no DB row.
        topic = services.repo.get_topic(payload.lower())

    if not topic:
        await query.edit_message_text("Тема ежедневного теста уже не найдена. Завтра выберу новую.")
        return

    await _show_quiz_size_choice(
        query,
        title=topic.title,
        scope="Ежедневный тест",
        mode=QUIZ_SIZE_DAILY_TOPIC,
        target=topic.id,
    )


async def daily_quiz_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    services = _services(context)
    payload = (query.data or "").removeprefix(DAILY_QUIZ_SKIP_PREFIX).strip()
    offer = services.daily_quiz.get_offer(payload)
    await query.answer("Пропущено")
    if offer:
        services.daily_quiz.set_status(offer.id, SKIPPED)
        await query.edit_message_text(
            "<b>Ежедневный тест пропущен</b>\n\n"
            f"{html.escape(offer.topic_title, quote=False)}",
            parse_mode=ParseMode.HTML,
        )
        return

    # Pre-migration offer message: payload is a bare date string, no DB row.
    await query.edit_message_text(
        "<b>Ежедневный тест пропущен</b>\n\n"
        f"Дата: <code>{html.escape(payload, quote=False)}</code>",
        parse_mode=ParseMode.HTML,
    )


async def daily_quiz_postpone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    services = _services(context)
    offer_id = (query.data or "").removeprefix(DAILY_QUIZ_POSTPONE_PREFIX).strip()
    offer = services.daily_quiz.get_offer(offer_id)
    if not offer:
        await query.answer("Запись не найдена.", show_alert=True)
        return

    services.daily_quiz.set_status(offer.id, POSTPONED)
    await query.answer("Отложено")
    await query.edit_message_text(
        "<b>Отложено</b>\n\n"
        f"{html.escape(offer.topic_title, quote=False)}\n\n"
        "Найдешь в «🌅 Ежедневные тесты» → «📋 Незавершенные тесты».",
        parse_mode=ParseMode.HTML,
    )


async def daily_quiz_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    services = _services(context)
    offer_id = (query.data or "").removeprefix(DAILY_QUIZ_DONE_PREFIX).strip()
    offer = services.daily_quiz.get_offer(offer_id)
    if not offer:
        await query.answer("Запись не найдена.", show_alert=True)
        return

    services.daily_quiz.set_status(offer.id, DONE)
    await query.answer("Отмечено")
    await query.edit_message_text(
        "<b>Ежедневный тест пройден ✅</b>\n\n"
        f"{html.escape(offer.topic_title, quote=False)}",
        parse_mode=ParseMode.HTML,
    )


async def daily_quiz_open_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    services = _services(context)
    offer_id = (query.data or "").removeprefix(DAILY_QUIZ_OPEN_PREFIX).strip()
    offer = services.daily_quiz.get_offer(offer_id)
    if not offer:
        await query.answer("Запись не найдена.", show_alert=True)
        return

    await query.answer()
    await query.edit_message_text(
        _daily_quiz_offer_detail_text(offer),
        parse_mode=ParseMode.HTML,
        reply_markup=_daily_quiz_offer_detail_keyboard(offer.id),
    )


async def menu_daily_quiz_outstanding_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    services = _services(context)
    offers = services.daily_quiz.list_outstanding()
    await query.edit_message_text(
        _daily_quiz_outstanding_text(offers),
        parse_mode=ParseMode.HTML,
        reply_markup=_daily_quiz_outstanding_keyboard(offers),
    )


async def coding_reps_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    raw_value = (query.data or "").removeprefix(CODING_REPS_TOGGLE_PREFIX)
    enabled = raw_value == "true"
    services = _services(context)
    services.coding_reps.set_enabled(enabled)
    await query.answer("Включено" if enabled else "Выключено")
    log.info("Coding reps toggled enabled=%s", enabled)
    await query.edit_message_text(
        _coding_reps_settings_text(services),
        parse_mode=ParseMode.HTML,
        reply_markup=_coding_reps_settings_keyboard(enabled),
    )


async def coding_reps_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    log_id = (query.data or "").removeprefix(CODING_REPS_DONE_PREFIX).strip()
    services = _services(context)
    entry = services.coding_reps.get_log_entry(log_id)
    if not entry:
        await query.answer("Запись не найдена.", show_alert=True)
        return

    services.coding_reps.mark_responded(log_id, "done")
    await query.answer("Отлично!")
    await query.edit_message_text(
        "<b>Кодинг-реп выполнен ✅</b>\n\n"
        f"{html.escape(entry.rep_title, quote=False)}\n\n"
        "Записал в журнал.",
        parse_mode=ParseMode.HTML,
    )


async def coding_reps_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    log_id = (query.data or "").removeprefix(CODING_REPS_SKIP_PREFIX).strip()
    services = _services(context)
    entry = services.coding_reps.get_log_entry(log_id)
    if not entry:
        await query.answer("Запись не найдена.", show_alert=True)
        return

    services.coding_reps.mark_responded(log_id, "skipped")
    await query.answer("Пропущено")
    await query.edit_message_text(
        "<b>Кодинг-реп пропущен</b>\n\n"
        f"{html.escape(entry.rep_title, quote=False)}",
        parse_mode=ParseMode.HTML,
    )


async def instant_block_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    raw_path = (query.data or "").removeprefix(INSTANT_BLOCK_PREFIX)
    grouped = _ready_review_topics_by_section(_services(context))
    selection = _section_selection(grouped, raw_path)
    if not selection:
        await query.edit_message_text("Список блоков устарел. Нажми «Пройти тест сейчас» еще раз.")
        return

    node, path = selection
    if node.children:
        await query.edit_message_text(
            _instant_blocks_text(grouped, path=path),
            parse_mode=ParseMode.HTML,
            reply_markup=_instant_block_keyboard(grouped, path=path),
        )
        return

    root = _section_tree(grouped)
    topics = _section_topics(node)
    await query.edit_message_text(
        _instant_topics_text(_section_leaf_title(root, path), topics),
        parse_mode=ParseMode.HTML,
        reply_markup=_instant_topic_keyboard(_section_path_data(path), topics),
    )


async def instant_topic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    services = _services(context)
    topic_id = (query.data or "").removeprefix(INSTANT_TOPIC_PREFIX).strip().lower()
    topic = services.repo.get_topic(topic_id)
    if not topic:
        await query.edit_message_text("Тема не найдена. Нажми «Пройти тест сейчас» еще раз.")
        return

    await _show_quiz_size_choice(
        query,
        title=topic.title,
        scope="Пройти тест сейчас",
        mode=QUIZ_SIZE_INSTANT_TOPIC,
        target=topic.id,
    )


async def instant_block_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    # Whole-block instant quizzes are temporarily disabled: combining every
    # topic's material in one section can total hundreds of thousands of chars
    # (e.g. all of "Code Review Go" is ~330k), which either blows past
    # MATERIAL_CHAR_LIMIT (heavy truncation) or costs an outsized share of the
    # 5h token budget for one test. Re-enable once section-wide material gets a
    # proportional/structural sampling strategy instead of naive truncation.
    await query.answer(
        "Тест по всему блоку сразу сейчас отключен — материалов в блоке "
        "слишком много для одного теста. Выбери конкретную тему ниже.",
        show_alert=True,
    )


async def abort_instant_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer("Ок")
    await query.edit_message_text("Моментальный тест отменен.")


async def open_question_block_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    raw_path = (query.data or "").removeprefix(OPEN_QUESTION_BLOCK_PREFIX)
    grouped = _ready_review_topics_by_section(_services(context))
    selection = _section_selection(grouped, raw_path)
    if not selection:
        await query.edit_message_text("Список блоков устарел. Нажми «Открытый вопрос» еще раз.")
        return

    node, path = selection
    if node.children:
        await query.edit_message_text(
            _open_question_blocks_text(grouped, path=path),
            parse_mode=ParseMode.HTML,
            reply_markup=_open_question_block_keyboard(grouped, path=path),
        )
        return

    root = _section_tree(grouped)
    topics = _section_topics(node)
    await query.edit_message_text(
        _open_question_topics_text(_section_leaf_title(root, path), topics),
        parse_mode=ParseMode.HTML,
        reply_markup=_open_question_topic_keyboard(topics),
    )


async def open_question_topic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    services = _services(context)
    topic_id = (query.data or "").removeprefix(OPEN_QUESTION_TOPIC_PREFIX).strip().lower()
    topic = services.repo.get_topic(topic_id)
    if not topic:
        await query.answer("Тема не найдена.", show_alert=True)
        return
    await _generate_open_question_for_topic(query, context, topic.id, title=topic.title)


async def open_question_from_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    session_id = (query.data or "").removeprefix(OPEN_QUESTION_FROM_QUIZ_PREFIX).strip()
    services = _services(context)
    try:
        session = services.quiz.get_session(session_id)
        questions = services.quiz.questions(session.id)
        answers = services.quiz.answers(session.id)
    except ValueError:
        await query.answer("Сессия теста не найдена.", show_alert=True)
        return

    title = session.topic_title or str(session.material_snapshot.get("topic_title") or session.topic_id)
    await query.answer("Генерирую вопрос")
    await _safe_query_edit(
        query,
        _open_question_wait_text(title=title, action="Генерирую открытый вопрос", frame=GENERATION_FRAMES[0]),
        parse_mode=ParseMode.HTML,
    )
    animation_task = asyncio.create_task(
        _animate_open_question_message(query, title=title, action="Генерирую открытый вопрос")
    )
    try:
        item = await asyncio.to_thread(
            services.open_questions.generate_for_quiz,
            session=session,
            questions=questions,
            answers=answers,
        )
    except (OpenQuestionAgentError, ValueError) as exc:
        await _stop_animation_task(animation_task)
        log.warning("Open question after quiz failed session_id=%s error=%s", session.id, exc)
        await _safe_query_edit(
            query,
            _generation_error_text(
                exc,
                "<b>Не удалось сгенерировать открытый вопрос</b>\n\n"
                f"Причина: {html.escape(str(exc), quote=False)}",
            ),
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as exc:
        await _stop_animation_task(animation_task)
        log.exception("Open question after quiz failed unexpectedly session_id=%s", session.id)
        await _safe_query_edit(
            query,
            "<b>Не удалось сгенерировать открытый вопрос</b>\n\n"
            f"Причина: {html.escape(str(exc), quote=False)}",
            parse_mode=ParseMode.HTML,
        )
        return
    finally:
        await _stop_animation_task(animation_task)

    context.user_data["awaiting_open_question_id"] = item.id
    await _safe_query_edit(
        query,
        format_open_question_prompt(item),
        parse_mode=ParseMode.HTML,
    )


async def open_question_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    session_id = (query.data or "").removeprefix(OPEN_QUESTION_SKIP_PREFIX).strip()
    services = _services(context)
    try:
        questions = services.quiz.questions(session_id)
        answers = services.quiz.answers(session_id)
    except ValueError:
        await query.answer("Сессия теста не найдена.", show_alert=True)
        return

    context.user_data["awaiting_open_question_id"] = ""
    await query.answer("Открытый вопрос пропущен")
    with contextlib.suppress(BadRequest):
        await query.edit_message_reply_markup(
            reply_markup=_quiz_report_keyboard(
                session_id,
                questions,
                answers,
                include_open_question=False,
            )
        )


async def _generate_open_question_for_topic(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    topic_id: str,
    *,
    title: str,
) -> None:
    services = _services(context)
    await query.answer("Генерирую вопрос")
    await _safe_query_edit(
        query,
        _open_question_wait_text(title=title, action="Генерирую открытый вопрос", frame=GENERATION_FRAMES[0]),
        parse_mode=ParseMode.HTML,
    )
    animation_task = asyncio.create_task(
        _animate_open_question_message(query, title=title, action="Генерирую открытый вопрос")
    )
    try:
        item = await asyncio.to_thread(services.open_questions.generate_for_topic, topic_id)
    except (OpenQuestionAgentError, ValueError) as exc:
        await _stop_animation_task(animation_task)
        log.warning("Open question generation failed topic_id=%s error=%s", topic_id, exc)
        await _safe_query_edit(
            query,
            _generation_error_text(
                exc,
                "<b>Не удалось сгенерировать открытый вопрос</b>\n\n"
                f"Причина: {html.escape(str(exc), quote=False)}",
            ),
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as exc:
        await _stop_animation_task(animation_task)
        log.exception("Open question generation failed unexpectedly topic_id=%s", topic_id)
        await _safe_query_edit(
            query,
            "<b>Не удалось сгенерировать открытый вопрос</b>\n\n"
            f"Причина: {html.escape(str(exc), quote=False)}",
            parse_mode=ParseMode.HTML,
        )
        return
    finally:
        await _stop_animation_task(animation_task)

    context.user_data["awaiting_open_question_id"] = item.id
    await _safe_query_edit(
        query,
        format_open_question_prompt(item),
        parse_mode=ParseMode.HTML,
    )


async def open_question_open_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    question_id = (query.data or "").removeprefix(OPEN_QUESTION_OPEN_PREFIX).strip()
    services = _services(context)
    item = services.open_questions.get_question(question_id)
    if not item:
        await query.answer("Вопрос не найден.", show_alert=True)
        return
    attempt = services.open_questions.latest_attempt(item.id)
    await query.answer()
    if item.status == "active":
        context.user_data["awaiting_open_question_id"] = item.id
        await query.edit_message_text(
            format_open_question_prompt(item),
            parse_mode=ParseMode.HTML,
        )
        return
    await _send_long_preview(
        query,
        split_message(format_open_question_item(item, attempt)),
        reply_markup=_open_question_item_keyboard(item),
    )


async def open_question_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return
    question_id = (query.data or "").removeprefix(OPEN_QUESTION_DELETE_PREFIX).strip()
    try:
        item = _services(context).open_questions.delete_question(question_id)
    except ValueError:
        await query.answer("Вопрос не найден.", show_alert=True)
        return
    await query.answer("Удалено")
    await query.edit_message_text(
        "<b>Открытый вопрос удален</b>\n\n"
        f"{html.escape(item.topic_title, quote=False)}",
        parse_mode=ParseMode.HTML,
    )


async def abort_open_question_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return
    context.user_data["awaiting_open_question_id"] = ""
    await query.answer("Ок")
    await query.edit_message_text("Открытый вопрос отменен.")


async def start_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    data = query.data or ""
    task_id = data.removeprefix(START_REVIEW_PREFIX)
    services = _services(context)
    try:
        task = services.review_tasks.get_task(task_id)
    except ValueError:
        await query.edit_message_text("Задача не найдена. Возможно, она уже устарела.")
        return

    await query.edit_message_text(
        _review_explain_choice_text(task.topic_title),
        parse_mode=ParseMode.HTML,
        reply_markup=_review_explain_choice_keyboard(task.id),
    )


async def postpone_due_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dismiss a due-notification message without touching the task itself.

    The task stays "active" with its due_at in the past, so it keeps showing
    up in due_tasks() ("Пора повторять") and gets re-notified tomorrow
    (due_for_notification() only suppresses same-day repeats) - postponing
    needs no new state, just acknowledging that this particular message is
    handled.
    """
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    task_id = (query.data or "").removeprefix(POSTPONE_DUE_PREFIX)
    services = _services(context)
    try:
        task = services.review_tasks.get_task(task_id)
    except ValueError:
        await query.answer("Задача не найдена.", show_alert=True)
        await query.edit_message_text("Задача не найдена. Возможно, она уже устарела.")
        return

    await query.answer("Отложено")
    await query.edit_message_text(
        "<b>Отложено</b>\n\n"
        f"{html.escape(task.topic_title, quote=False)}\n\n"
        "Задача остается активной и будет в «⏰ Пора повторять», пока не пройдешь тест. "
        "Если пропустишь сегодня — напомню завтра.",
        parse_mode=ParseMode.HTML,
    )


async def explain_then_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    task_id = (query.data or "").removeprefix(EXPLAIN_THEN_REVIEW_PREFIX).strip()
    services = _services(context)
    try:
        task = services.review_tasks.get_task(task_id)
    except ValueError:
        await query.answer("Задача не найдена.", show_alert=True)
        await query.edit_message_text("Задача не найдена. Возможно, она уже устарела.")
        return

    await query.answer()
    context.user_data["awaiting_review_topic"] = False
    context.user_data["awaiting_study_topic"] = False
    context.user_data["awaiting_explanation_topic_id"] = task.topic_id
    context.user_data["awaiting_explanation_then_task_id"] = task.id
    log.info("Explain-before-review started task_id=%s topic_id=%s", task.id, task.topic_id)
    await query.edit_message_text(
        _explain_check_prompt_text(task.topic_title),
        parse_mode=ParseMode.HTML,
    )


async def skip_explain_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    task_id = (query.data or "").removeprefix(SKIP_EXPLAIN_REVIEW_PREFIX).strip()
    services = _services(context)
    try:
        task = services.review_tasks.get_task(task_id)
    except ValueError:
        await query.edit_message_text("Задача не найдена. Возможно, она уже устарела.")
        return

    await _show_quiz_size_choice(
        query,
        title=task.topic_title,
        scope="Повторение",
        mode=QUIZ_SIZE_REVIEW,
        target=task.id,
    )


async def quiz_size_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    payload = (query.data or "").removeprefix(QUIZ_SIZE_PREFIX)
    try:
        mode, target, raw_count = payload.split(":", 2)
        question_count = int(raw_count)
    except ValueError:
        await query.answer("Не понял размер теста.", show_alert=True)
        return
    if question_count not in QUIZ_SIZE_OPTIONS:
        await query.answer("Неподдерживаемое количество вопросов.", show_alert=True)
        return

    await query.answer(f"{question_count} вопросов")
    services = _services(context)
    if mode == QUIZ_SIZE_REVIEW:
        await _start_review_quiz(
            query,
            context,
            task_id=target,
            question_count=question_count,
        )
        return

    if mode in (QUIZ_SIZE_INSTANT_TOPIC, QUIZ_SIZE_DAILY_TOPIC):
        topic = services.repo.get_topic(target.strip().lower())
        if not topic:
            await query.edit_message_text("Тема не найдена. Попробуй выбрать тест заново.")
            return
        await _start_instant_quiz(
            query,
            context,
            topic_title=topic.title,
            question_count=question_count,
            start_call=lambda *, question_count: services.quiz.start_instant_topic_session(
                topic.id,
                question_count=question_count,
            ),
        )
        return

    if mode == QUIZ_SIZE_INSTANT_BLOCK:
        try:
            index = int(target)
        except ValueError:
            await query.edit_message_text("Не понял выбранный блок. Нажми «Пройти тест сейчас» еще раз.")
            return
        grouped = _ready_review_topics_by_section(services)
        sections = list(grouped.items())
        if index < 0 or index >= len(sections):
            await query.edit_message_text("Список блоков устарел. Нажми «Пройти тест сейчас» еще раз.")
            return
        section, _topics = sections[index]
        await _start_instant_quiz(
            query,
            context,
            topic_title=f"Блок: {section}",
            question_count=question_count,
            start_call=lambda *, question_count: services.quiz.start_instant_block_session(
                section,
                question_count=question_count,
            ),
        )
        return

    await query.edit_message_text("Не понял тип теста. Попробуй начать заново.")


async def abort_quiz_size_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer("Ок")
    await query.edit_message_text("Тест не запущен.")


async def quiz_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    data = query.data or ""
    payload = data.removeprefix(QUIZ_ANSWER_PREFIX)
    try:
        session_id, question_id, selected_raw = payload.split(":", 2)
        selected_index = int(selected_raw)
    except ValueError:
        await query.answer("Не понял кнопку ответа.", show_alert=True)
        return

    services = _services(context)
    try:
        result = services.quiz.answer_current(
            session_id,
            question_id,
            selected_index,
        )
    except QuestionClosedError:
        await query.answer("Этот вопрос уже закрыт.")
        return
    except ValueError:
        await query.answer("Не удалось сохранить ответ.", show_alert=True)
        return

    await query.answer("Ответ принят")
    if result.next_question:
        await query.edit_message_text(
            text=format_quiz_question(result.session, result.next_question),
            reply_markup=_answer_keyboard(result.session, result.next_question),
            parse_mode=ParseMode.HTML,
        )
        return

    questions = services.quiz.questions(result.session.id)
    answers = services.quiz.answers(result.session.id)
    if result.session.session_type == "instant":
        await _finish_quiz_and_send_report(
            query,
            report_text=format_instant_quiz_report(result.session, questions, answers),
            reply_markup=_quiz_report_keyboard(result.session.id, questions, answers),
        )
        return

    if not result.session.task_id:
        await query.edit_message_text("Тест завершен, но не удалось найти связанную задачу.")
        return

    task = result.finished_task or services.review_tasks.get_task(result.session.task_id)
    await _finish_quiz_and_send_report(
        query,
        report_text=format_quiz_report(result.session, questions, answers, task),
        reply_markup=_quiz_report_keyboard(result.session.id, questions, answers),
    )


async def _finish_quiz_and_send_report(query, *, report_text: str, reply_markup=None) -> None:
    """Keep the finished quiz as its own message and send the report separately.

    The quiz message (last question) loses its answer buttons; the report is sent
    as a new message (split into several if long) so test-taking and the report do
    not overwrite each other. The report keyboard goes on the last report chunk.
    """
    with contextlib.suppress(BadRequest):
        await query.edit_message_reply_markup(reply_markup=None)
    message = query.message
    if message is None:
        await _safe_query_edit(
            query,
            report_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        return
    chunks = split_message(report_text)
    last = len(chunks) - 1
    for index, chunk in enumerate(chunks):
        with contextlib.suppress(Exception):
            await message.reply_text(
                chunk,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup if index == last else None,
            )


async def _send_long_preview(query, chunks: list[str], *, reply_markup=None) -> None:
    """Show a possibly long HTML preview without hitting Telegram's 4096 limit.

    The first chunk edits the callback message in place; any remaining chunks are
    sent as follow-up messages. The inline keyboard is attached to the last chunk
    only. Without this a long report fails the edit with Message_too_long and the
    user is left staring at the stale "waiting" message.
    """
    if not chunks:
        return
    last = len(chunks) - 1
    await _safe_query_edit(
        query,
        chunks[0],
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup if last == 0 else None,
    )
    message = query.message
    if message is None:
        return
    for index in range(1, len(chunks)):
        with contextlib.suppress(Exception):
            await message.reply_text(
                chunks[index],
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup if index == last else None,
            )


def _mistake_review_wait_text(*, frame: str, elapsed_seconds: int = 0) -> str:
    return (
        f"{frame} <b>Разбираю ошибки</b>\n\n"
        "Отправил отчет агенту. Жду ответ...\n"
        f"Ожидание: {_format_wait_elapsed(elapsed_seconds)}\n\n"
        "Это может занять немного времени."
    )


async def _animate_mistake_review_message(query) -> None:
    index = 0
    started_at = perf_counter()
    while True:
        await asyncio.sleep(3)
        index += 1
        elapsed = int(perf_counter() - started_at)
        if index == 1 or index % 4 == 0:
            log.info("Mistake review still waiting elapsed=%ss", elapsed)
        with contextlib.suppress(Exception):
            await query.edit_message_text(
                _mistake_review_wait_text(
                    frame=GENERATION_FRAMES[index % len(GENERATION_FRAMES)],
                    elapsed_seconds=elapsed,
                ),
                parse_mode=ParseMode.HTML,
            )


async def mistake_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await _safe_query_answer(query, "Это личный бот LearnKeeper.", show_alert=True)
        return

    session_id = (query.data or "").removeprefix(MISTAKE_REVIEW_PREFIX).strip()
    services = _services(context)
    try:
        session = services.quiz.get_session(session_id)
        questions = services.quiz.questions(session.id)
        answers = services.quiz.answers(session.id)
    except ValueError:
        await _safe_query_answer(query, "Сессия теста не найдена.", show_alert=True)
        return

    if not _mistake_questions(questions, answers):
        await _safe_query_answer(query, "Ошибок в этом тесте нет.")
        return

    await _safe_query_answer(query, "Запустил разбор")
    await _safe_query_edit(
        query,
        _mistake_review_wait_text(frame=GENERATION_FRAMES[0]),
        parse_mode=ParseMode.HTML,
    )
    request = _mistake_review_input(services, session, questions, answers)
    log.info(
        "Mistake review queued session_id=%s mistakes=%s topic_id=%s",
        session.id,
        len(request.mistakes),
        session.topic_id,
    )
    animation_task = asyncio.create_task(_animate_mistake_review_message(query))
    try:
        report = await asyncio.to_thread(services.mistake_review_agent.analyze, request)
    except MistakeReviewAgentError as exc:
        await _stop_animation_task(animation_task)
        log.warning("Mistake review failed session_id=%s error=%s", session.id, exc)
        await _safe_query_edit(
            query,
            _generation_error_text(
                exc,
                "<b>Не удалось разобрать ошибки</b>\n\n"
                f"Причина: {html.escape(str(exc), quote=False)}",
            ),
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as exc:
        await _stop_animation_task(animation_task)
        log.exception("Mistake review failed unexpectedly session_id=%s", session.id)
        await _safe_query_edit(
            query,
            "<b>Не удалось разобрать ошибки</b>\n\n"
            f"Причина: {html.escape(str(exc), quote=False)}",
            parse_mode=ParseMode.HTML,
        )
        return
    finally:
        await _stop_animation_task(animation_task)

    pending = context.user_data.setdefault("pending_mistake_reports", {})
    pending[session.id] = {"report": report, "questions": request.mistakes}
    await _send_long_preview(
        query,
        split_message(format_mistake_review_preview(report)),
        reply_markup=_mistake_report_keyboard(session.id),
    )


async def save_mistake_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await _safe_query_answer(query, "Это личный бот LearnKeeper.", show_alert=True)
        return

    session_id = (query.data or "").removeprefix(SAVE_MISTAKE_REPORT_PREFIX).strip()
    pending = context.user_data.get("pending_mistake_reports", {})
    payload = pending.get(session_id) if isinstance(pending, dict) else None
    if not payload:
        await _safe_query_answer(
            query,
            "Черновик отчета не найден. Запусти разбор ошибок еще раз.",
            show_alert=True,
        )
        return

    services = _services(context)
    try:
        session = services.quiz.get_session(session_id)
        item = services.mistake_work.create_item(
            session=session,
            report=payload["report"],
            questions=payload["questions"],
        )
    except Exception as exc:
        log.exception("Failed to save mistake work item session_id=%s", session_id)
        await _safe_query_answer(query, "Не удалось сохранить отчет.", show_alert=True)
        await _safe_query_edit(
            query,
            "<b>Не удалось сохранить отчет</b>\n\n"
            f"Причина: {html.escape(str(exc), quote=False)}",
            parse_mode=ParseMode.HTML,
        )
        return

    pending.pop(session_id, None)
    await _safe_query_answer(query, "Сохранил")
    await _safe_query_edit(
        query,
        format_mistake_work_created(item),
        parse_mode=ParseMode.HTML,
        reply_markup=_mistake_work_item_keyboard(item.id, status=item.status),
    )


async def cancel_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    task_id = (query.data or "").removeprefix(CANCEL_REVIEW_PREFIX)
    services = _services(context)
    try:
        task = services.review_tasks.get_task(task_id)
    except ValueError:
        await query.edit_message_text("Задача не найдена. Возможно, список уже устарел.")
        return

    if task.status != "active":
        await query.edit_message_text("Эта задача уже не активна.")
        return

    await query.edit_message_text(
        text=format_cancel_review_confirm(task),
        reply_markup=_confirm_cancel_review_keyboard(task.id),
        parse_mode=ParseMode.HTML,
    )


async def confirm_cancel_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    task_id = (query.data or "").removeprefix(CONFIRM_CANCEL_REVIEW_PREFIX)
    services = _services(context)
    try:
        task = services.review_tasks.cancel_task(task_id)
    except ValueError:
        await query.answer("Эта задача уже не активна.", show_alert=True)
        await query.edit_message_text("Эта задача уже не активна.")
        return

    await query.answer("Повтор отменен")
    log.info("Review task cancelled from Telegram task_id=%s", task.id)
    await query.edit_message_text(
        text=format_cancel_review_done(task),
        parse_mode=ParseMode.HTML,
    )


async def abort_cancel_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer("Не удаляю")
    await query.edit_message_text("Удаление повтора отменено.")


async def review_add_blocks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    await _edit_review_blocks(query, context)


async def review_block_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    raw_path = (query.data or "").removeprefix(REVIEW_BLOCK_PREFIX)
    grouped = _ready_review_topics_by_section(_services(context))
    selection = _section_selection(grouped, raw_path)
    if not selection:
        await query.edit_message_text("Список блоков устарел. Нажми «Добавить повтор» еще раз.")
        return

    node, path = selection
    if node.children:
        await query.edit_message_text(
            _review_blocks_text(grouped, path=path),
            parse_mode=ParseMode.HTML,
            reply_markup=_review_block_keyboard(grouped, path=path),
        )
        return

    root = _section_tree(grouped)
    topics = _section_topics(node)
    await query.edit_message_text(
        _review_topics_text(_section_leaf_title(root, path), topics),
        parse_mode=ParseMode.HTML,
        reply_markup=_review_topic_keyboard(topics),
    )


async def review_topic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    topic_id = (query.data or "").removeprefix(REVIEW_TOPIC_PREFIX).strip().lower()
    if not topic_id:
        await query.edit_message_text("Не понял выбранную тему. Нажми «Добавить повтор» еще раз.")
        return

    services = _services(context)
    try:
        result = await asyncio.to_thread(
            services.review_tasks.create_review_task_for_topic_id,
            topic_id,
        )
    except TopicNotReadyError as exc:
        await query.edit_message_text(
            format_topic_not_ready(exc),
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception:
        log.exception("Review task creation by topic_id failed topic_id=%s", topic_id)
        await query.edit_message_text("Не смог создать повтор. Проверь логи локального запуска.")
        return

    if not result.created:
        await query.edit_message_text(
            _format_existing_review_prompt(result.task),
            parse_mode=ParseMode.HTML,
            reply_markup=_review_existing_keyboard(result.topic.id),
        )
        return

    log.info("Review task created from topic button task_id=%s topic_id=%s", result.task.id, topic_id)
    await query.edit_message_text(
        format_review_created(
            result.task,
            created=True,
            source_paths=result.topic.source_paths,
        ),
        parse_mode=ParseMode.HTML,
    )


async def explain_check_blocks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    await _sync_materials_repo(context, "explain-check-blocks")
    grouped = _ready_review_topics_by_section(_services(context))
    if not grouped:
        await query.edit_message_text(
            "<b>Объяснить тему</b>\n\n"
            "В lk-prep пока нет ready-тем с читаемыми материалами.",
            parse_mode=ParseMode.HTML,
        )
        return
    await query.edit_message_text(
        _explain_check_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_explain_check_block_keyboard(grouped),
    )


async def explain_check_block_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    raw_path = (query.data or "").removeprefix(EXPLAIN_CHECK_BLOCK_PREFIX)
    grouped = _ready_review_topics_by_section(_services(context))
    selection = _section_selection(grouped, raw_path)
    if not selection:
        await query.edit_message_text("Список блоков устарел. Нажми «Объяснить тему» еще раз.")
        return

    node, path = selection
    if node.children:
        await query.edit_message_text(
            _explain_check_blocks_text(grouped, path=path),
            parse_mode=ParseMode.HTML,
            reply_markup=_explain_check_block_keyboard(grouped, path=path),
        )
        return

    root = _section_tree(grouped)
    topics = _section_topics(node)
    await query.edit_message_text(
        _explain_check_topics_text(_section_leaf_title(root, path), topics),
        parse_mode=ParseMode.HTML,
        reply_markup=_explain_check_topic_keyboard(topics),
    )


async def explain_check_topic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    services = _services(context)
    topic_id = (query.data or "").removeprefix(EXPLAIN_CHECK_TOPIC_PREFIX).strip().lower()
    topic = services.repo.get_topic(topic_id)
    if not topic:
        await query.edit_message_text("Тема не найдена. Нажми «Объяснить тему» еще раз.")
        return

    context.user_data["awaiting_review_topic"] = False
    context.user_data["awaiting_study_topic"] = False
    context.user_data["awaiting_explanation_topic_id"] = topic.id
    context.user_data["awaiting_explanation_then_task_id"] = ""
    log.info("Explain check topic selected topic_id=%s", topic.id)
    await query.edit_message_text(
        _explain_check_prompt_text(topic.title),
        parse_mode=ParseMode.HTML,
    )


async def abort_explain_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    context.user_data["awaiting_explanation_topic_id"] = ""
    context.user_data["awaiting_explanation_then_task_id"] = ""
    await query.answer("Ок")
    await query.edit_message_text("Проверка объяснения отменена.")


async def read_material_blocks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    await _sync_materials_repo(context, "read-material-blocks")
    grouped = _ready_review_topics_by_section(_services(context))
    if not grouped:
        await query.edit_message_text(
            "<b>Читать материал</b>\n\n"
            "В lk-prep пока нет ready-тем с читаемыми материалами.",
            parse_mode=ParseMode.HTML,
        )
        return
    await query.edit_message_text(
        _read_material_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_read_material_block_keyboard(grouped),
    )


async def read_material_block_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    raw_path = (query.data or "").removeprefix(READ_MATERIAL_BLOCK_PREFIX)
    grouped = _ready_review_topics_by_section(_services(context))
    selection = _section_selection(grouped, raw_path)
    if not selection:
        await query.edit_message_text("Список блоков устарел. Нажми «Читать материал» еще раз.")
        return

    node, path = selection
    if node.children:
        await query.edit_message_text(
            _read_material_blocks_text(grouped, path=path),
            parse_mode=ParseMode.HTML,
            reply_markup=_read_material_block_keyboard(grouped, path=path),
        )
        return

    root = _section_tree(grouped)
    topics = _section_topics(node)
    await query.edit_message_text(
        _read_material_topics_text(_section_leaf_title(root, path), topics),
        parse_mode=ParseMode.HTML,
        reply_markup=_read_material_topic_keyboard(topics),
    )


async def read_material_topic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    services = _services(context)
    topic_id = (query.data or "").removeprefix(READ_MATERIAL_TOPIC_PREFIX).strip().lower()
    topic = services.repo.get_topic(topic_id)
    if not topic:
        await query.edit_message_text("Тема не найдена. Нажми «Читать материал» еще раз.")
        return

    await _sync_materials_repo(context, "read-material-topic")
    materials = services.repo.get_topic_materials(topic)
    readable_paths = [
        material.source_path
        for material in materials.files
        if Path(material.source_path).suffix.lower() not in CODE_FILE_EXTENSIONS
    ]
    if not readable_paths:
        await query.edit_message_text(f"Читаемые материалы для темы «{topic.title}» не найдены.")
        return

    links = [
        (
            Path(source_path).name,
            _material_github_url(services.settings.materials_github_base_url, source_path),
        )
        for source_path in readable_paths
    ]
    log.info("Read material requested topic_id=%s files=%d", topic.id, len(links))
    await query.edit_message_text(
        _read_material_links_text(topic.title, links),
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def abort_read_material_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer("Ок")
    await query.edit_message_text("Чтение материала отменено.")


async def reset_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    topic_id = (query.data or "").removeprefix(RESET_REVIEW_PREFIX).strip().lower()
    if not topic_id:
        await query.edit_message_text("Не понял тему для сброса. Нажми «Добавить повтор» еще раз.")
        return

    services = _services(context)
    try:
        result = await asyncio.to_thread(
            services.review_tasks.create_review_task_for_topic_id,
            topic_id,
            replace_existing=True,
        )
    except Exception:
        log.exception("Review task reset failed topic_id=%s", topic_id)
        await query.edit_message_text("Не смог сбросить повтор. Проверь логи локального запуска.")
        return

    log.info("Review task reset from Telegram task_id=%s topic_id=%s", result.task.id, topic_id)
    await query.edit_message_text(
        _format_review_reset_done(result.task),
        parse_mode=ParseMode.HTML,
    )


async def abort_review_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer("Ок")
    await query.edit_message_text("Добавление повтора отменено.")


async def topic_inbox_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    item_id = (query.data or "").removeprefix(TOPIC_INBOX_DELETE_PREFIX).strip()
    if not item_id:
        await query.answer("Не понял, что удалить.", show_alert=True)
        return

    try:
        deleted = _services(context).topic_inbox.delete_item(item_id)
    except Exception:
        log.exception("Topic inbox delete failed item_id=%s", item_id)
        await query.answer("Не смог удалить.", show_alert=True)
        return

    await query.answer("Удалено")
    items = _services(context).topic_inbox.list_active(limit=20)
    log.info("Topic inbox item deleted id=%s title=%s", deleted.id, deleted.title)
    await query.edit_message_text(
        format_topic_inbox_list(items),
        parse_mode=ParseMode.HTML,
        reply_markup=_topic_inbox_keyboard(items) if items else None,
    )


async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_non_owner(update, context):
        return
    await _answer_long(
        update,
        "Не понял действие.\n\n"
        "Выбери кнопку снизу или нажми <b>Помощь</b>.",
    )


async def telegram_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    if isinstance(error, BadRequest):
        log.warning("Telegram BadRequest while handling update=%s error=%s", update, error)
        return
    log.exception("Unhandled Telegram error while handling update=%s", update, exc_info=error)


def _explain_check_material(services: AppServices, topic) -> list[dict[str, object]]:
    """Doc-only, capped material for the explain-check agent.

    Deliberately a local copy of quiz.generator's doc-file selection + char cap
    (reusing its public CODE_FILE_EXTENSIONS/MATERIAL_CHAR_LIMIT constants but not
    its private helpers), so this feature has no code dependency on the quiz
    module beyond two shared constants.
    """
    materials = services.repo.get_topic_materials(topic)
    doc_files = [
        file
        for file in materials.files
        if Path(file.source_path).suffix.lower() not in CODE_FILE_EXTENSIONS
    ]
    if not doc_files:
        doc_files = materials.files
    remaining = MATERIAL_CHAR_LIMIT
    context: list[dict[str, object]] = []
    for file in doc_files:
        if remaining <= 0:
            break
        excerpt = file.content[:remaining]
        remaining -= len(excerpt)
        context.append(_material_context_entry(file, excerpt))
    return context


def _material_context_entry(material, excerpt: str) -> dict[str, object]:
    metadata = material.metadata
    entry: dict[str, object] = {
        "source_path": material.source_path,
        "excerpt": excerpt,
    }
    if metadata.source_role:
        entry["source_role"] = metadata.source_role
    if metadata.source_refs:
        entry["source_refs"] = metadata.source_refs
    if metadata.prompt_helper:
        entry["prompt_helper"] = metadata.prompt_helper
    return entry


def _explain_check_wait_text(*, frame: str, elapsed_seconds: int = 0) -> str:
    return (
        f"{frame} <b>Проверяю объяснение</b>\n\n"
        "Сверяю с материалом темы. Жду ответ агента...\n"
        f"Ожидание: {_format_wait_elapsed(elapsed_seconds)}\n\n"
        "Это может занять до пары минут."
    )


async def _animate_explain_check_message(message) -> None:
    index = 0
    started_at = perf_counter()
    while True:
        await asyncio.sleep(3)
        index += 1
        elapsed = int(perf_counter() - started_at)
        if index == 1 or index % 4 == 0:
            log.info("Explain check still waiting elapsed=%ss", elapsed)
        with contextlib.suppress(Exception):
            await message.edit_text(
                _explain_check_wait_text(
                    frame=GENERATION_FRAMES[index % len(GENERATION_FRAMES)],
                    elapsed_seconds=elapsed,
                ),
                parse_mode=ParseMode.HTML,
            )


async def _finish_explain_check_message(
    update: Update,
    message,
    text: str,
    *,
    reply_markup=None,
) -> None:
    """Edit the wait message into the final result, without touching the shared
    _edit_or_reply helper other flows rely on."""
    try:
        await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        return
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            return
        log.warning("Could not edit explain-check message, sending a new one: %s", exc)
    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)


async def _process_explanation_check(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    topic_id: str,
    explanation_text: str,
    *,
    source: str,
    follow_up_task_id: str = "",
) -> None:
    if not update.message:
        return
    services = _services(context)
    topic = services.repo.get_topic(topic_id)
    if not topic:
        await _answer_long(
            update,
            "Тема для объяснения уже не найдена. Открой «Объяснить тему» заново.",
        )
        return

    material_context = _explain_check_material(services, topic)
    if not material_context:
        await _answer_long(update, "У темы нет читаемых материалов для проверки.")
        return

    wait_message = await update.message.reply_text(
        _explain_check_wait_text(frame=GENERATION_FRAMES[0]),
        parse_mode=ParseMode.HTML,
    )
    animation_task = asyncio.create_task(_animate_explain_check_message(wait_message))
    request = ExplainCheckInput(
        topic_id=topic.id,
        topic_title=topic.title,
        section=topic.section,
        source=source,
        explanation_text=explanation_text,
        material_context=material_context,
    )
    log.info(
        "Explain check queued topic_id=%s source=%s explanation_len=%s",
        topic.id,
        source,
        len(explanation_text),
    )
    try:
        result = await asyncio.to_thread(services.explain_check_agent.check, request)
    except ExplainCheckAgentError as exc:
        await _stop_animation_task(animation_task)
        log.warning("Explain check failed topic_id=%s error=%s", topic.id, exc)
        await _finish_explain_check_message(
            update,
            wait_message,
            _generation_error_text(
                exc,
                "<b>Не удалось проверить объяснение</b>\n\n"
                f"Причина: {html.escape(str(exc), quote=False)}",
            ),
        )
        return
    except Exception as exc:
        await _stop_animation_task(animation_task)
        log.exception("Explain check failed unexpectedly topic_id=%s", topic.id)
        await _finish_explain_check_message(
            update,
            wait_message,
            "<b>Не удалось проверить объяснение</b>\n\n"
            f"Причина: {html.escape(str(exc), quote=False)}",
        )
        return
    finally:
        await _stop_animation_task(animation_task)

    materials = services.repo.get_topic_materials(topic)
    item = services.explain_check.create_item(
        topic=topic,
        source=source,
        explanation_text=explanation_text,
        result=result,
        material_fingerprint=materials.fingerprint,
        linked_review_task_id=follow_up_task_id,
    )
    log.info(
        "Explain check saved id=%s topic_id=%s layer=%s priority=%s",
        item.id,
        topic.id,
        item.layer_reached,
        item.priority,
    )
    chunks = split_message(format_explain_check_report(item))
    last = len(chunks) - 1
    await _finish_explain_check_message(
        update,
        wait_message,
        chunks[0],
        reply_markup=_explain_check_item_keyboard(item.id, status=item.status) if last == 0 else None,
    )
    for index in range(1, len(chunks)):
        with contextlib.suppress(Exception):
            await update.message.reply_text(
                chunks[index],
                parse_mode=ParseMode.HTML,
                reply_markup=_explain_check_item_keyboard(item.id, status=item.status)
                if index == last
                else None,
            )

    if follow_up_task_id:
        with contextlib.suppress(Exception):
            await update.message.reply_text(
                _review_ready_after_explain_text(item.topic_title),
                parse_mode=ParseMode.HTML,
                reply_markup=_review_ready_after_explain_keyboard(follow_up_task_id),
            )


async def _process_open_question_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    question_id: str,
    answer_text: str,
    *,
    source: str,
) -> None:
    if not update.message:
        return
    services = _services(context)
    item = services.open_questions.get_question(question_id)
    if not item:
        await _answer_long(update, "Открытый вопрос уже не найден. Создай новый вопрос.")
        return
    if item.status != "active":
        attempt = services.open_questions.latest_attempt(item.id)
        await _answer_long(update, format_open_question_item(item, attempt))
        return

    wait_message = await update.message.reply_text(
        _open_question_wait_text(
            title=item.topic_title,
            action="Проверяю открытый ответ",
            frame=GENERATION_FRAMES[0],
        ),
        parse_mode=ParseMode.HTML,
    )
    animation_task = asyncio.create_task(
        _animate_open_question_reply_message(
            wait_message,
            title=item.topic_title,
            action="Проверяю открытый ответ",
        )
    )
    log.info(
        "Open question answer queued question_id=%s topic_id=%s source=%s answer_len=%s",
        item.id,
        item.topic_id,
        source,
        len(answer_text),
    )
    try:
        question, attempt = await asyncio.to_thread(
            services.open_questions.check_answer,
            item.id,
            answer_text,
            answer_source=source,
        )
    except (OpenQuestionAgentError, ValueError) as exc:
        await _stop_animation_task(animation_task)
        log.warning("Open question check failed question_id=%s error=%s", item.id, exc)
        await _finish_explain_check_message(
            update,
            wait_message,
            _generation_error_text(
                exc,
                "<b>Не удалось проверить открытый ответ</b>\n\n"
                f"Причина: {html.escape(str(exc), quote=False)}",
            ),
        )
        return
    except Exception as exc:
        await _stop_animation_task(animation_task)
        log.exception("Open question check failed unexpectedly question_id=%s", item.id)
        await _finish_explain_check_message(
            update,
            wait_message,
            "<b>Не удалось проверить открытый ответ</b>\n\n"
            f"Причина: {html.escape(str(exc), quote=False)}",
        )
        return
    finally:
        await _stop_animation_task(animation_task)

    log.info(
        "Open question checked question_id=%s score=%.1f layer=%s",
        question.id,
        attempt.score_percent,
        attempt.layer_reached,
    )
    chunks = split_message(format_open_question_check_report(question, attempt))
    last = len(chunks) - 1
    await _finish_explain_check_message(
        update,
        wait_message,
        chunks[0],
        reply_markup=_open_question_item_keyboard(question) if last == 0 else None,
    )
    for index in range(1, len(chunks)):
        with contextlib.suppress(Exception):
            await update.message.reply_text(
                chunks[index],
                parse_mode=ParseMode.HTML,
                reply_markup=_open_question_item_keyboard(question) if index == last else None,
            )


def _voice_audio_path(services: AppServices, file_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    token = "".join(ch if ch.isalnum() else "-" for ch in file_id)[:16] or "voice"
    services.voice_dir.mkdir(parents=True, exist_ok=True)
    return services.voice_dir / f"{stamp}-{token}.oga"


async def menu_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_non_owner(update, context):
        return
    if not update.message or not update.message.voice:
        return

    voice = update.message.voice
    awaiting_review = bool(context.user_data.get("awaiting_review_topic"))
    awaiting_study = bool(context.user_data.get("awaiting_study_topic"))
    awaiting_explanation_topic_id = str(context.user_data.get("awaiting_explanation_topic_id") or "")
    awaiting_open_question_id = str(context.user_data.get("awaiting_open_question_id") or "")
    if awaiting_review and not awaiting_study and not awaiting_explanation_topic_id and not awaiting_open_question_id:
        context.user_data["awaiting_review_topic"] = False
        log.info(
            "Voice message rejected for review flow duration=%s file_id=%s",
            voice.duration,
            voice.file_id,
        )
        await _answer_long(
            update,
            "Для повтора голос больше не нужен.\n\n"
            f"Открой <b>{BTN_REVIEW_MENU}</b> → <b>{BTN_REVIEW_ADD}</b>, затем выбери блок и тему кнопками.",
        )
        return
    if not awaiting_review and not awaiting_study and not awaiting_explanation_topic_id and not awaiting_open_question_id:
        log.info(
            "Voice message rejected outside command flow duration=%s file_id=%s",
            voice.duration,
            voice.file_id,
        )
        await _answer_long(
            update,
            "Голосовое не обработал: сейчас я не жду команду.\n\n"
            "Распознавание не запускал, чтобы не делать лишнюю работу.\n"
            f"Для повтора открой <b>{BTN_REVIEW_MENU}</b>.\n"
            f"Голосом сейчас можно пользоваться после <b>{BTN_IDEAS_MENU}</b> → <b>{BTN_TOPIC_ADD}</b>, "
            f"после <b>{BTN_TEST_MENU}</b> → <b>{BTN_OPEN_QUESTION}</b> "
            f"или после <b>{BTN_TEST_MENU}</b> → <b>{BTN_EXPLAIN_CHECK}</b>.",
        )
        return

    services = _services(context)
    started_at = perf_counter()
    log.info(
        "Voice processing started duration=%s file_id=%s provider=%s",
        voice.duration,
        voice.file_id,
        services.speech.provider,
    )
    wait_message = await update.message.reply_text(
        "Распознаю голосовое...",
    )
    audio_path = _voice_audio_path(services, voice.file_id)
    try:
        download_started_at = perf_counter()
        tg_file = await context.bot.get_file(voice.file_id)
        await tg_file.download_to_drive(str(audio_path))
        log.info(
            "Voice audio downloaded path=%s elapsed=%.2fs total=%.2fs",
            audio_path,
            perf_counter() - download_started_at,
            perf_counter() - started_at,
        )
        stt_started_at = perf_counter()
        text = await asyncio.to_thread(services.speech.transcribe, audio_path)
        log.info(
            "Voice transcription finished chars=%s elapsed=%.2fs total=%.2fs",
            len(text.strip()),
            perf_counter() - stt_started_at,
            perf_counter() - started_at,
        )
    except SpeechToTextError as exc:
        log.warning(
            "Voice processing failed at STT elapsed=%.2fs error=%s",
            perf_counter() - started_at,
            exc,
        )
        await _edit_or_reply(
            update,
            wait_message,
            f"Не смог распознать голосовое.\n\n{html.escape(str(exc), quote=False)}",
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception:
        log.exception(
            "Voice processing failed unexpectedly elapsed=%.2fs",
            perf_counter() - started_at,
        )
        await _edit_or_reply(
            update,
            wait_message,
            "Не смог обработать голосовое. Попробуй еще раз или напиши тему текстом.",
        )
        return

    query = text.strip()
    if not query:
        log.warning("Voice processing returned empty transcript elapsed=%.2fs", perf_counter() - started_at)
        await _edit_or_reply(
            update,
            wait_message,
            "Распознавание вернуло пустой текст. Попробуй сказать тему четче.",
        )
        return

    follow_up_task_id = str(context.user_data.get("awaiting_explanation_then_task_id") or "")
    context.user_data["awaiting_review_topic"] = False
    context.user_data["awaiting_study_topic"] = False
    context.user_data["awaiting_explanation_topic_id"] = ""
    context.user_data["awaiting_explanation_then_task_id"] = ""
    context.user_data["awaiting_open_question_id"] = ""
    await _edit_or_reply(
        update,
        wait_message,
        f"<b>Распознал:</b> {html.escape(query, quote=False)}\n\nОбрабатываю...",
        parse_mode=ParseMode.HTML,
    )
    if awaiting_study:
        await _create_topic_inbox_item(update, context, query, source="voice")
    elif awaiting_explanation_topic_id:
        await _process_explanation_check(
            update,
            context,
            awaiting_explanation_topic_id,
            query,
            source="voice",
            follow_up_task_id=follow_up_task_id,
        )
    elif awaiting_open_question_id:
        await _process_open_question_answer(
            update,
            context,
            awaiting_open_question_id,
            query,
            source="voice",
        )
    else:
        await _show_review_blocks(update, context)
    log.info("Voice processing finished elapsed=%.2fs", perf_counter() - started_at)


async def menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _reject_non_owner(update, context):
        return
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if context.user_data.get("awaiting_review_topic") and text not in MENU_BUTTONS:
        context.user_data["awaiting_review_topic"] = False
        await _show_review_blocks(update, context)
        return
    if context.user_data.get("awaiting_study_topic") and text not in MENU_BUTTONS:
        context.user_data["awaiting_study_topic"] = False
        await _create_topic_inbox_item(update, context, text, source="text_after_button")
        return
    awaiting_explanation_topic_id = str(context.user_data.get("awaiting_explanation_topic_id") or "")
    awaiting_open_question_id = str(context.user_data.get("awaiting_open_question_id") or "")
    if awaiting_explanation_topic_id and text not in MENU_BUTTONS:
        follow_up_task_id = str(context.user_data.get("awaiting_explanation_then_task_id") or "")
        context.user_data["awaiting_explanation_topic_id"] = ""
        context.user_data["awaiting_explanation_then_task_id"] = ""
        await _process_explanation_check(
            update,
            context,
            awaiting_explanation_topic_id,
            text,
            source="text",
            follow_up_task_id=follow_up_task_id,
        )
        return
    if awaiting_open_question_id and text not in MENU_BUTTONS:
        context.user_data["awaiting_open_question_id"] = ""
        await _process_open_question_answer(
            update,
            context,
            awaiting_open_question_id,
            text,
            source="text",
        )
        return

    context.user_data["awaiting_review_topic"] = False
    context.user_data["awaiting_study_topic"] = False
    context.user_data["awaiting_explanation_topic_id"] = ""
    context.user_data["awaiting_explanation_then_task_id"] = ""
    context.user_data["awaiting_open_question_id"] = ""
    if text in (BTN_TOPICS, "Темы"):
        await _show_topics(update, context)
        return
    if text == BTN_READ_MATERIAL:
        await _show_read_material_blocks(update, context)
        return
    if text == BTN_REVIEW_MENU:
        await _show_review_menu(update, context)
        return
    if text in (BTN_TEST_MENU, "Тесты", "Тренировки"):
        await _show_tests_menu(update, context)
        return
    if text in (BTN_IDEAS_MENU, "Идеи"):
        await _show_ideas_menu(update, context)
        return
    if text == BTN_SETTINGS_MENU:
        await _show_settings_menu(update, context)
        return
    if text in (BTN_SCHEDULE, "Расписание"):
        await _show_schedule(update, context)
        return
    if text in (BTN_DUE, "Пора повторять"):
        await _show_due(update, context)
        return
    if text in (BTN_REVIEW_ADD, "Добавить повтор"):
        context.user_data["awaiting_review_topic"] = False
        await _show_review_blocks(update, context)
        return
    if text in (BTN_INSTANT_QUIZ, "Пройти тест сейчас"):
        await _show_instant_blocks(update, context)
        return
    if text in (BTN_OPEN_QUESTION, "Открытый вопрос"):
        await _show_open_question_blocks(update, context)
        return
    if text in (BTN_DAILY_QUIZ, "Ежедневные тесты"):
        await _show_daily_quiz_settings(update, context)
        return
    if text in (BTN_CODING_REPS, "Кодинг-репы"):
        await _show_coding_reps_settings(update, context)
        return
    if text in (BTN_LLM_USAGE, "Токены LLM"):
        await _show_llm_usage(update, context)
        return
    if text in (BTN_CHANGELOG, "Changelog"):
        await _show_changelog(update, context)
        return
    if text in (BTN_STUDY_TOPICS, "Темы на изучение", "Inbox идей"):
        await _show_study_topics_menu(update, context)
        return
    if text in (BTN_TOPIC_ADD, "Добавить тему", "Добавить идею"):
        context.user_data["awaiting_study_topic"] = True
        await _answer_long(update, format_study_topic_prompt())
        return
    if text in (BTN_TOPIC_INBOX, "Идеи тем", "Список идей"):
        await _show_topic_inbox(update, context)
        return
    if text in (BTN_MISTAKE_WORK, BTN_MISTAKE_WORK_ACTIVE, "Работа над ошибками", "Активные отчеты"):
        await _show_mistake_work_active(update, context)
        return
    if text in (BTN_MISTAKE_WORK_DONE, "Проработанные"):
        await _show_mistake_work_done(update, context)
        return
    if text in (BTN_OPEN_QUESTION_LIST, "Открытые вопросы"):
        await _show_open_questions_active(update, context)
        return
    if text in (BTN_OPEN_QUESTION_ANSWERED, "Проверенные ответы"):
        await _show_open_questions_answered(update, context)
        return
    if text in (BTN_EXPLAIN_CHECK_START, "Объяснить новую тему"):
        await _show_explain_check_blocks(update, context)
        return
    if text in (BTN_EXPLAIN_CHECK, "Объяснить тему"):
        await _show_explain_check_menu(update, context)
        return
    if text in (BTN_EXPLAIN_CHECK_LIST, "Мои объяснения"):
        await _show_explain_check_active(update, context)
        return
    if text in (BTN_EXPLAIN_CHECK_DONE, "Разобранные"):
        await _show_explain_check_done(update, context)
        return
    if text in (BTN_REVIEW_CANCEL, "Удалить повтор"):
        await _show_cancel_reviews(update, context)
        return
    if text in (BTN_HELP, "Помощь"):
        await start(update, context)
        return

    await _answer_long(
        update,
        "Я пока не обрабатываю свободный текст как команду.\n\n"
        f"Повторы лежат в разделе <b>{BTN_REVIEW_MENU}</b>.\n"
        f"Быстрые и ежедневные тесты лежат в разделе <b>{BTN_TEST_MENU}</b>.\n"
        f"Новые идеи лежат в разделе <b>{BTN_IDEAS_MENU}</b>.",
    )


async def notify_due_reviews(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _services(context)
    owner_id = _owner_id(context)
    tasks = services.review_tasks.due_for_notification(now=datetime.now(), limit=10)
    if not tasks:
        return

    for task in tasks:
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Начать тест", callback_data=f"{START_REVIEW_PREFIX}{task.id}")],
                _postpone_cancel_row(task.id),
            ]
        )
        try:
            await context.bot.send_message(
                chat_id=owner_id,
                text=format_due_notification(task),
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception("Failed to send due notification for task_id=%s", task.id)
            continue
        services.review_tasks.mark_notified(task.id, now=datetime.now())
        log.info("Sent due notification for task_id=%s", task.id)


async def send_daily_quiz_offer(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _services(context)
    owner_id = _owner_id(context)
    now = datetime.now(_daily_quiz_timezone(services.settings))
    today = now.date()
    if not services.daily_quiz.should_send_today(today):
        log.info(
            "Daily quiz skipped enabled=%s last_sent=%s today=%s",
            services.daily_quiz.is_enabled(),
            services.daily_quiz.last_sent_date() or "-",
            today.isoformat(),
        )
        return

    await _sync_materials_repo(context, "daily-quiz")
    topic = services.daily_quiz.random_ready_topic()
    if not topic:
        log.warning("Daily quiz enabled, but no ready topics with materials found")
        return

    offer = services.daily_quiz.create_offer(topic, today)
    try:
        await context.bot.send_message(
            chat_id=owner_id,
            text=_daily_quiz_offer_text(topic),
            reply_markup=_daily_quiz_offer_keyboard(offer.id),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        log.exception("Failed to send daily quiz offer topic_id=%s", topic.id)
        return

    services.daily_quiz.mark_sent(today)
    log.info(
        "Daily quiz offer sent topic_id=%s offer_id=%s date=%s",
        topic.id,
        offer.id,
        today.isoformat(),
    )


async def send_coding_rep_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _services(context)
    owner_id = _owner_id(context)
    now = datetime.now(_daily_quiz_timezone(services.settings))
    today = now.date()
    if not services.coding_reps.should_send_today(today):
        log.info(
            "Coding rep reminder skipped enabled=%s last_sent=%s today=%s",
            services.coding_reps.is_enabled(),
            services.coding_reps.last_sent_date() or "-",
            today.isoformat(),
        )
        return

    rep = services.coding_reps.random_rep()
    log_id = services.coding_reps.log_sent(rep)

    try:
        await context.bot.send_message(
            chat_id=owner_id,
            text=_coding_rep_offer_text(rep),
            reply_markup=_coding_rep_offer_keyboard(log_id),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        log.exception("Failed to send coding rep reminder rep_id=%s", rep.id)
        return

    services.coding_reps.mark_sent(today)
    log.info("Coding rep reminder sent rep_id=%s date=%s", rep.id, today.isoformat())


async def notify_version_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _services(context)
    owner_id = _owner_id(context)
    version = _current_version()
    if version == "unknown":
        log.info("Version notification skipped: git version is unknown")
        return

    last_notified = _get_app_setting(services, LAST_NOTIFIED_VERSION_KEY, "")
    if last_notified == version:
        log.info("Version notification skipped: version=%s already notified", version)
        return

    try:
        await context.bot.send_message(
            chat_id=owner_id,
            text=_format_version_update_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_keyboard(),
        )
    except Exception:
        log.exception("Failed to send version update notification version=%s", version)
        return

    _set_app_setting(services, LAST_NOTIFIED_VERSION_KEY, version)
    log.info("Version update notification sent version=%s previous=%s", version, last_notified or "-")


async def notify_llm_budget(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Warn the owner when the rolling 5h LLM usage crosses the local benchmark.

    Fires once when it crosses 80% and once at 100%; resets when the rolling
    window drops back below 80%, so it does not spam.
    """
    services = _services(context)
    owner_id = _owner_id(context)
    five_h = services.llm_usage.stats_for_periods()[0]
    if five_h.budget_usd <= 0 and five_h.budget_tokens <= 0:
        return

    percent = max(five_h.budget_percent, five_h.token_budget_percent)
    level = 100 if percent >= 100 else (80 if percent >= 80 else 0)
    last_level = int(_get_app_setting(services, LLM_BUDGET_ALERT_KEY, "0") or "0")

    if level <= last_level:
        if level < last_level:
            _set_app_setting(services, LLM_BUDGET_ALERT_KEY, str(level))
        return

    try:
        await context.bot.send_message(
            chat_id=owner_id,
            text=format_llm_budget_alert(five_h, level),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        log.exception("Failed to send LLM budget alert level=%s", level)
        return
    _set_app_setting(services, LLM_BUDGET_ALERT_KEY, str(level))
    log.warning("LLM budget alert sent level=%s percent=%.1f", level, percent)


def _daily_quiz_timezone(settings: Settings) -> ZoneInfo:
    try:
        return ZoneInfo(settings.daily_quiz_timezone)
    except ZoneInfoNotFoundError:
        log.warning(
            "Unknown DAILY_QUIZ_TIMEZONE=%s, falling back to Europe/Moscow",
            settings.daily_quiz_timezone,
        )
        return ZoneInfo("Europe/Moscow")


def build_application(settings: Settings, services: AppServices) -> Application:
    _require_telegram_settings(settings)
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data["services"] = services
    app.bot_data["owner_id"] = settings.tg_user_id

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("topics", topics))
    app.add_handler(CommandHandler("review_add", review_add))
    app.add_handler(CommandHandler("instant_quiz", instant_quiz))
    app.add_handler(CommandHandler("topic_add", topic_add))
    app.add_handler(CommandHandler("topic_ideas", topic_ideas))
    app.add_handler(CommandHandler("schedule", schedule))
    app.add_handler(CommandHandler("due", due))
    app.add_handler(CallbackQueryHandler(topic_blocks_callback, pattern=f"^{TOPIC_BLOCKS}$"))
    app.add_handler(CallbackQueryHandler(topic_block_callback, pattern=f"^{TOPIC_BLOCK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(abort_topics_callback, pattern=f"^{ABORT_TOPICS}$"))
    app.add_handler(CallbackQueryHandler(review_add_blocks_callback, pattern=f"^{REVIEW_ADD_BLOCKS}$"))
    app.add_handler(CallbackQueryHandler(review_block_callback, pattern=f"^{REVIEW_BLOCK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(review_topic_callback, pattern=f"^{REVIEW_TOPIC_PREFIX}"))
    app.add_handler(CallbackQueryHandler(reset_review_callback, pattern=f"^{RESET_REVIEW_PREFIX}"))
    app.add_handler(CallbackQueryHandler(abort_review_add_callback, pattern=f"^{ABORT_REVIEW_ADD}$"))
    app.add_handler(CallbackQueryHandler(explain_check_blocks_callback, pattern=f"^{EXPLAIN_CHECK_BLOCKS}$"))
    app.add_handler(CallbackQueryHandler(explain_check_block_callback, pattern=f"^{EXPLAIN_CHECK_BLOCK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(explain_check_topic_callback, pattern=f"^{EXPLAIN_CHECK_TOPIC_PREFIX}"))
    app.add_handler(CallbackQueryHandler(abort_explain_check_callback, pattern=f"^{ABORT_EXPLAIN_CHECK}$"))
    app.add_handler(CallbackQueryHandler(read_material_blocks_callback, pattern=f"^{READ_MATERIAL_BLOCKS}$"))
    app.add_handler(CallbackQueryHandler(read_material_block_callback, pattern=f"^{READ_MATERIAL_BLOCK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(read_material_topic_callback, pattern=f"^{READ_MATERIAL_TOPIC_PREFIX}"))
    app.add_handler(CallbackQueryHandler(abort_read_material_callback, pattern=f"^{ABORT_READ_MATERIAL}$"))
    app.add_handler(CallbackQueryHandler(menu_schedule_callback, pattern=f"^{MENU_SCHEDULE}$"))
    app.add_handler(CallbackQueryHandler(menu_due_callback, pattern=f"^{MENU_DUE}$"))
    app.add_handler(CallbackQueryHandler(menu_cancel_reviews_callback, pattern=f"^{MENU_CANCEL_REVIEWS}$"))
    app.add_handler(CallbackQueryHandler(menu_study_topics_callback, pattern=f"^{MENU_STUDY_TOPICS}$"))
    app.add_handler(CallbackQueryHandler(menu_topic_add_callback, pattern=f"^{MENU_TOPIC_ADD}$"))
    app.add_handler(CallbackQueryHandler(menu_topic_inbox_callback, pattern=f"^{MENU_TOPIC_INBOX}$"))
    app.add_handler(CallbackQueryHandler(menu_mistake_work_callback, pattern=f"^{MENU_MISTAKE_WORK}$"))
    app.add_handler(CallbackQueryHandler(menu_mistake_work_done_callback, pattern=f"^{MENU_MISTAKE_WORK_DONE}$"))
    app.add_handler(CallbackQueryHandler(menu_open_questions_callback, pattern=f"^{MENU_OPEN_QUESTIONS}$"))
    app.add_handler(
        CallbackQueryHandler(
            menu_open_questions_answered_callback,
            pattern=f"^{MENU_OPEN_QUESTIONS_ANSWERED}$",
        )
    )
    app.add_handler(CallbackQueryHandler(menu_explain_check_callback, pattern=f"^{MENU_EXPLAIN_CHECK}$"))
    app.add_handler(CallbackQueryHandler(menu_explain_check_list_callback, pattern=f"^{MENU_EXPLAIN_CHECK_LIST}$"))
    app.add_handler(CallbackQueryHandler(menu_explain_check_done_callback, pattern=f"^{MENU_EXPLAIN_CHECK_DONE}$"))
    app.add_handler(CallbackQueryHandler(menu_daily_settings_callback, pattern=f"^{MENU_DAILY_SETTINGS}$"))
    app.add_handler(
        CallbackQueryHandler(
            menu_coding_reps_settings_callback,
            pattern=f"^{MENU_CODING_REPS_SETTINGS}$",
        )
    )
    app.add_handler(CallbackQueryHandler(menu_llm_usage_callback, pattern=f"^{MENU_LLM_USAGE}$"))
    app.add_handler(CallbackQueryHandler(menu_changelog_callback, pattern=f"^{MENU_CHANGELOG}$"))
    app.add_handler(CallbackQueryHandler(daily_quiz_toggle_callback, pattern=f"^{DAILY_QUIZ_TOGGLE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(daily_quiz_start_callback, pattern=f"^{DAILY_QUIZ_START_PREFIX}"))
    app.add_handler(CallbackQueryHandler(daily_quiz_skip_callback, pattern=f"^{DAILY_QUIZ_SKIP_PREFIX}"))
    app.add_handler(CallbackQueryHandler(daily_quiz_postpone_callback, pattern=f"^{DAILY_QUIZ_POSTPONE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(daily_quiz_done_callback, pattern=f"^{DAILY_QUIZ_DONE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(daily_quiz_open_callback, pattern=f"^{DAILY_QUIZ_OPEN_PREFIX}"))
    app.add_handler(
        CallbackQueryHandler(
            menu_daily_quiz_outstanding_callback,
            pattern=f"^{MENU_DAILY_QUIZ_OUTSTANDING}$",
        )
    )
    app.add_handler(CallbackQueryHandler(coding_reps_toggle_callback, pattern=f"^{CODING_REPS_TOGGLE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(coding_reps_done_callback, pattern=f"^{CODING_REPS_DONE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(coding_reps_skip_callback, pattern=f"^{CODING_REPS_SKIP_PREFIX}"))
    app.add_handler(CallbackQueryHandler(instant_blocks_callback, pattern=f"^{INSTANT_BLOCKS}$"))
    app.add_handler(CallbackQueryHandler(instant_block_all_callback, pattern=f"^{INSTANT_BLOCK_ALL_PREFIX}"))
    app.add_handler(CallbackQueryHandler(instant_block_callback, pattern=f"^{INSTANT_BLOCK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(instant_topic_callback, pattern=f"^{INSTANT_TOPIC_PREFIX}"))
    app.add_handler(CallbackQueryHandler(abort_instant_quiz_callback, pattern=f"^{ABORT_INSTANT_QUIZ}$"))
    app.add_handler(CallbackQueryHandler(open_question_blocks_callback, pattern=f"^{OPEN_QUESTION_BLOCKS}$"))
    app.add_handler(CallbackQueryHandler(open_question_block_callback, pattern=f"^{OPEN_QUESTION_BLOCK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(open_question_topic_callback, pattern=f"^{OPEN_QUESTION_TOPIC_PREFIX}"))
    app.add_handler(CallbackQueryHandler(open_question_from_quiz_callback, pattern=f"^{OPEN_QUESTION_FROM_QUIZ_PREFIX}"))
    app.add_handler(CallbackQueryHandler(open_question_skip_callback, pattern=f"^{OPEN_QUESTION_SKIP_PREFIX}"))
    app.add_handler(CallbackQueryHandler(open_question_open_callback, pattern=f"^{OPEN_QUESTION_OPEN_PREFIX}"))
    app.add_handler(CallbackQueryHandler(open_question_delete_callback, pattern=f"^{OPEN_QUESTION_DELETE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(abort_open_question_callback, pattern=f"^{ABORT_OPEN_QUESTION}$"))
    app.add_handler(CallbackQueryHandler(quiz_size_callback, pattern=f"^{QUIZ_SIZE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(abort_quiz_size_callback, pattern=f"^{ABORT_QUIZ_SIZE}$"))
    app.add_handler(CallbackQueryHandler(start_review_callback, pattern=f"^{START_REVIEW_PREFIX}"))
    app.add_handler(CallbackQueryHandler(postpone_due_callback, pattern=f"^{POSTPONE_DUE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(explain_then_review_callback, pattern=f"^{EXPLAIN_THEN_REVIEW_PREFIX}"))
    app.add_handler(CallbackQueryHandler(skip_explain_review_callback, pattern=f"^{SKIP_EXPLAIN_REVIEW_PREFIX}"))
    app.add_handler(CallbackQueryHandler(quiz_answer_callback, pattern=f"^{QUIZ_ANSWER_PREFIX}"))
    app.add_handler(CallbackQueryHandler(mistake_review_callback, pattern=f"^{MISTAKE_REVIEW_PREFIX}"))
    app.add_handler(CallbackQueryHandler(save_mistake_report_callback, pattern=f"^{SAVE_MISTAKE_REPORT_PREFIX}"))
    app.add_handler(CallbackQueryHandler(cancel_review_callback, pattern=f"^{CANCEL_REVIEW_PREFIX}"))
    app.add_handler(
        CallbackQueryHandler(
            confirm_cancel_review_callback,
            pattern=f"^{CONFIRM_CANCEL_REVIEW_PREFIX}",
        )
    )
    app.add_handler(CallbackQueryHandler(abort_cancel_review_callback, pattern=f"^{ABORT_CANCEL_REVIEW}$"))
    app.add_handler(CallbackQueryHandler(topic_inbox_delete_callback, pattern=f"^{TOPIC_INBOX_DELETE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(mistake_work_open_callback, pattern=f"^{MISTAKE_WORK_OPEN_PREFIX}"))
    app.add_handler(CallbackQueryHandler(mistake_work_done_callback, pattern=f"^{MISTAKE_WORK_DONE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(mistake_work_delete_callback, pattern=f"^{MISTAKE_WORK_DELETE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(explain_check_open_callback, pattern=f"^{EXPLAIN_CHECK_OPEN_PREFIX}"))
    app.add_handler(CallbackQueryHandler(explain_check_done_callback, pattern=f"^{EXPLAIN_CHECK_DONE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(explain_check_delete_callback, pattern=f"^{EXPLAIN_CHECK_DELETE_PREFIX}"))
    app.add_handler(MessageHandler(filters.VOICE, menu_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_text))
    app.add_handler(MessageHandler(filters.ALL, fallback))
    app.add_error_handler(telegram_error_handler)

    if app.job_queue is None:
        log.warning(
            "JobQueue is unavailable. Install python-telegram-bot[job-queue] to enable due notifications."
        )
    else:
        app.job_queue.run_repeating(
            notify_due_reviews,
            interval=settings.review_tick_seconds,
            first=10,
            name="due-review-notifications",
        )
        app.job_queue.run_once(
            notify_version_update,
            when=5,
            name="version-update-notification",
        )
        app.job_queue.run_repeating(
            notify_llm_budget,
            interval=300,
            first=120,
            name="llm-budget-alert",
        )
        app.job_queue.run_daily(
            send_daily_quiz_offer,
            time=datetime_time(
                hour=settings.daily_quiz_hour,
                minute=settings.daily_quiz_minute,
                tzinfo=_daily_quiz_timezone(settings),
            ),
            name="daily-quiz-offer",
        )
        app.job_queue.run_daily(
            send_coding_rep_reminder,
            time=datetime_time(
                hour=settings.coding_reps_hour,
                minute=settings.coding_reps_minute,
                tzinfo=_daily_quiz_timezone(settings),
            ),
            name="coding-rep-reminder",
        )
    return app


def run_bot() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = load_settings()
    services = AppServices(settings)
    app = build_application(settings, services)

    log.info("Starting LearnKeeper polling.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


def main() -> None:
    run_bot()
