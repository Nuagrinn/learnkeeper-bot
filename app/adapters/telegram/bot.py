from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import subprocess
from datetime import datetime, time as datetime_time
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
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
    format_mistake_review_preview,
    format_mistake_work_created,
    format_mistake_work_item,
    format_mistake_work_list,
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
from app.features.quiz.factory import build_quiz_generator
from app.features.quiz.generator import QuizGenerationError
from app.features.quiz.models import QuizQuestion, QuizSession
from app.features.quiz.service import QuestionClosedError, QuizService
from app.features.daily_quiz.service import DailyQuizService
from app.features.review_tasks.service import ReviewTaskService, TopicNotReadyError
from app.features.speech.factory import build_speech_to_text
from app.features.speech.service import SpeechToTextError
from app.features.topic_inbox.factory import build_topic_inbox_agent
from app.features.topic_inbox.service import TopicInboxService


log = logging.getLogger(__name__)
START_REVIEW_PREFIX = "start_review:"
QUIZ_ANSWER_PREFIX = "quiz_answer:"
INSTANT_BLOCKS = "instant_blocks"
INSTANT_BLOCK_PREFIX = "instant_block:"
INSTANT_BLOCK_ALL_PREFIX = "instant_block_all:"
INSTANT_TOPIC_PREFIX = "instant_topic:"
ABORT_INSTANT_QUIZ = "abort_instant_quiz"
DAILY_QUIZ_TOGGLE_PREFIX = "daily_quiz_toggle:"
DAILY_QUIZ_START_PREFIX = "daily_quiz_start:"
DAILY_QUIZ_SKIP_PREFIX = "daily_quiz_skip:"
MENU_REVIEW = "menu_review"
MENU_TESTS = "menu_tests"
MENU_PROCESSING = "menu_processing"
MENU_IDEAS = "menu_ideas"
MENU_SETTINGS = "menu_settings"
MENU_SCHEDULE = "menu_schedule"
MENU_DUE = "menu_due"
MENU_CANCEL_REVIEWS = "menu_cancel_reviews"
MENU_STUDY_TOPICS = "menu_study_topics"
MENU_TOPIC_ADD = "menu_topic_add"
MENU_TOPIC_INBOX = "menu_topic_inbox"
MENU_MISTAKE_WORK = "menu_mistake_work"
MENU_MISTAKE_WORK_DONE = "menu_mistake_work_done"
MENU_DAILY_SETTINGS = "menu_daily_settings"
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
GENERATION_FRAMES = ("⏳", "⌛")
BTN_TOPICS = "📚 Темы"
BTN_REVIEW_MENU = "🔁 Повторы"
BTN_TEST_MENU = "🧪 Тесты"
BTN_IDEAS_MENU = "🗂 Проработка"
BTN_SETTINGS_MENU = "⚙️ Настройки"
BTN_REVIEW_ADD = "➕ Добавить повтор"
BTN_INSTANT_QUIZ = "▶️ Пройти тест сейчас"
BTN_DAILY_QUIZ = "🌅 Ежедневные тесты"
BTN_LLM_USAGE = "📊 Токены LLM"
BTN_CHANGELOG = "📝 Changelog"
BTN_REVIEW_CANCEL = "🗑 Удалить повтор"
BTN_STUDY_TOPICS = "💡 Темы на изучение"
BTN_TOPIC_ADD = "➕ Добавить тему"
BTN_TOPIC_INBOX = "📥 Идеи тем"
BTN_MISTAKE_WORK = "🧩 Работа над ошибками"
BTN_MISTAKE_WORK_ACTIVE = "📋 Активные отчеты"
BTN_MISTAKE_WORK_DONE = "✅ Проработанные"
BTN_SCHEDULE = "🗓 Расписание"
BTN_DUE = "⏰ Пора повторять"
BTN_HELP = "❔ Помощь"
LEGACY_MENU_BUTTONS = {
    "Темы",
    "Добавить повтор",
    "Пройти тест сейчас",
    "Ежедневные тесты",
    "Токены LLM",
    "Changelog",
    "Удалить повтор",
    "Идеи",
    "Темы на изучение",
    "Добавить тему",
    "Идеи тем",
    "Работа над ошибками",
    "Активные отчеты",
    "Проработанные",
    "Расписание",
    "Пора повторять",
    "Помощь",
}
MENU_BUTTONS = {
    BTN_TOPICS,
    BTN_REVIEW_MENU,
    BTN_TEST_MENU,
    BTN_IDEAS_MENU,
    BTN_SETTINGS_MENU,
    BTN_REVIEW_ADD,
    BTN_INSTANT_QUIZ,
    BTN_DAILY_QUIZ,
    BTN_LLM_USAGE,
    BTN_CHANGELOG,
    BTN_REVIEW_CANCEL,
    BTN_STUDY_TOPICS,
    BTN_TOPIC_ADD,
    BTN_TOPIC_INBOX,
    BTN_MISTAKE_WORK,
    BTN_MISTAKE_WORK_ACTIVE,
    BTN_MISTAKE_WORK_DONE,
    BTN_SCHEDULE,
    BTN_DUE,
    BTN_HELP,
} | LEGACY_MENU_BUTTONS


LAST_NOTIFIED_VERSION_KEY = "app_version_last_notified"
CHANGELOG_LIMIT = 8


class AppServices:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.db_path)
        self.db.migrate()
        self.repo = RepoService(settings.interview_review_path)
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
            ),
        )
        self.review_tasks = ReviewTaskService(self.db, self.repo)
        self.daily_quiz = DailyQuizService(self.db, self.repo)
        self.topic_inbox = TopicInboxService(
            self.db,
            build_topic_inbox_agent(settings, usage_recorder=self.llm_usage),
        )
        self.mistake_work = MistakeWorkService(self.db)
        self.mistake_review_agent = build_mistake_review_agent(
            settings,
            usage_recorder=self.llm_usage,
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
            [BTN_TOPICS, BTN_REVIEW_MENU],
            [BTN_TEST_MENU, BTN_IDEAS_MENU],
            [BTN_SETTINGS_MENU, BTN_HELP],
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
        f"<b>{BTN_TOPICS}</b> - список тем из interview-review\n"
        f"<b>{BTN_REVIEW_MENU}</b> - добавить, посмотреть или отменить повторы\n"
        f"<b>{BTN_TEST_MENU}</b> - моментальные и ежедневные тесты\n"
        f"<b>{BTN_IDEAS_MENU}</b> - идеи тем и отчеты по ошибкам\n"
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
    services = _services(context)
    await _sync_materials_repo(context, "topics")
    items = (
        services.repo.search_topics(query, limit=20)
        if query
        else services.repo.list_topics()[:20]
    )
    await _answer_long(update, format_topics(items))


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
        "🧪 Тесты",
        "Быстрые тренировки без изменения расписания и ежедневный случайный тест.",
        _tests_menu_keyboard(),
    )


async def _show_ideas_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_section_menu(
        update,
        "🗂 Проработка",
        "Идеи новых тем и отдельная очередь отчетов после ошибок в тестах.",
        _ideas_menu_keyboard(),
    )


async def _show_study_topics_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_section_menu(
        update,
        "💡 Темы на изучение",
        "Голосовые и текстовые идеи, которые потом руками переносим в interview-review.",
        _study_topics_menu_keyboard(),
    )


async def _show_mistake_work_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_section_menu(
        update,
        "🧩 Работа над ошибками",
        "Отчеты, которые агент собрал после неправильных ответов в тестах.",
        _mistake_work_menu_keyboard(),
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
            [InlineKeyboardButton(BTN_DAILY_QUIZ, callback_data=MENU_DAILY_SETTINGS)],
        ]
    )


def _ideas_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_STUDY_TOPICS, callback_data=MENU_STUDY_TOPICS)],
            [InlineKeyboardButton(BTN_MISTAKE_WORK, callback_data=MENU_MISTAKE_WORK)],
        ]
    )


def _study_topics_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_TOPIC_ADD, callback_data=MENU_TOPIC_ADD)],
            [InlineKeyboardButton(BTN_TOPIC_INBOX, callback_data=MENU_TOPIC_INBOX)],
        ]
    )


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
        await _answer_long(update, "Не вижу тему. Попробуй написать или надиктовать еще раз.")
        return

    log.info(
        "Topic inbox creation started source=%s query_len=%s",
        source,
        len(clean_query),
    )
    wait_message = None
    if update.message:
        wait_message = await update.message.reply_text(
            "<b>Принял идею темы</b>\n\n"
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
        text = "Не смог сохранить идею темы.\n\nПроверь логи локального запуска."
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


def _quiz_report_keyboard(session_id: str, questions, answers) -> InlineKeyboardMarkup | None:
    if not _mistake_questions(questions, answers):
        return None
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Разобрать ошибки",
                    callback_data=f"{MISTAKE_REVIEW_PREFIX}{session_id}",
                )
            ]
        ]
    )


async def _show_review_blocks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _services(context)
    await _sync_materials_repo(context, "review-blocks")
    grouped = _ready_review_topics_by_section(services)
    if not grouped:
        await _answer_long(
            update,
            "<b>Добавить повтор</b>\n\n"
            "В interview-review пока нет ready-тем с читаемыми материалами.",
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
            "В interview-review пока нет ready-тем с читаемыми материалами.",
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
    for topic in services.repo.list_topics():
        if topic.status != "ready":
            continue
        if not services.repo.get_topic_materials(topic).files:
            continue
        section = topic.section or "Без блока"
        grouped.setdefault(section, []).append(topic)
    for topics in grouped.values():
        topics.sort(key=lambda item: (item.order_index or 10_000, item.title.lower()))
    return grouped


def _review_blocks_text(grouped: dict[str, list]) -> str:
    total = sum(len(topics) for topics in grouped.values())
    return (
        "<b>Добавить повтор</b>\n\n"
        f"Готовых тем: <b>{total}</b>\n"
        "Выбери блок."
    )


def _review_topics_text(section: str, topics: list) -> str:
    return (
        "<b>Добавить повтор</b>\n\n"
        f"<b>{html.escape(section, quote=False)}</b>\n"
        f"Тем: <b>{len(topics)}</b>\n\n"
        "Выбери тему."
    )


def _review_block_keyboard(grouped: dict[str, list]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, (section, topics) in enumerate(grouped.items()):
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(f"{section} ({len(topics)})"),
                    callback_data=f"{REVIEW_BLOCK_PREFIX}{index}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("Отмена", callback_data=ABORT_REVIEW_ADD)])
    return InlineKeyboardMarkup(rows)


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
            "В interview-review пока нет ready-тем с читаемыми материалами.",
        )
        return
    if not update.message:
        return
    await update.message.reply_text(
        _instant_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_instant_block_keyboard(grouped),
    )


async def _edit_instant_blocks(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _sync_materials_repo(context, "instant-blocks")
    grouped = _ready_review_topics_by_section(_services(context))
    if not grouped:
        await query.edit_message_text(
            "<b>Пройти тест сейчас</b>\n\n"
            "В interview-review пока нет ready-тем с читаемыми материалами.",
            parse_mode=ParseMode.HTML,
        )
        return
    await query.edit_message_text(
        _instant_blocks_text(grouped),
        parse_mode=ParseMode.HTML,
        reply_markup=_instant_block_keyboard(grouped),
    )


def _instant_blocks_text(grouped: dict[str, list]) -> str:
    total = sum(len(topics) for topics in grouped.values())
    return (
        "<b>Пройти тест сейчас</b>\n\n"
        f"Готовых тем: <b>{total}</b>\n"
        "Выбери блок."
    )


def _instant_topics_text(section: str, topics: list) -> str:
    return (
        "<b>Пройти тест сейчас</b>\n\n"
        f"<b>{html.escape(section, quote=False)}</b>\n"
        f"Тем: <b>{len(topics)}</b>\n\n"
        "Можно пройти тест по всему блоку или выбрать конкретную тему."
    )


def _instant_block_keyboard(grouped: dict[str, list]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, (section, topics) in enumerate(grouped.items()):
        rows.append(
            [
                InlineKeyboardButton(
                    _button_label(f"{section} ({len(topics)})"),
                    callback_data=f"{INSTANT_BLOCK_PREFIX}{index}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("Отмена", callback_data=ABORT_INSTANT_QUIZ)])
    return InlineKeyboardMarkup(rows)


def _instant_topic_keyboard(section_index: int, topics: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                "Весь блок",
                callback_data=f"{INSTANT_BLOCK_ALL_PREFIX}{section_index}",
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


async def _show_daily_quiz_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _services(context)
    if not update.message:
        return
    await update.message.reply_text(
        _daily_quiz_settings_text(services, context),
        parse_mode=ParseMode.HTML,
        reply_markup=_daily_quiz_settings_keyboard(services.daily_quiz.is_enabled()),
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
    last_sent = services.daily_quiz.last_sent_date() or "еще не отправлялся"
    return "\n".join(
        [
            "<b>Ежедневные тесты</b>",
            "",
            f"<b>Статус:</b> {html.escape(status, quote=False)}",
            f"<b>Время:</b> <code>{settings.daily_quiz_hour:02d}:{settings.daily_quiz_minute:02d}</code>",
            f"<b>Таймзона:</b> <code>{html.escape(settings.daily_quiz_timezone, quote=False)}</code>",
            f"<b>Готовых тем:</b> {ready_count}",
            f"<b>Последняя отправка:</b> <code>{html.escape(last_sent, quote=False)}</code>",
            "",
            "Если режим включен, утром бот пришлет случайную ready-тему с кнопками: пройти тест или пропустить.",
        ]
    )


def _daily_quiz_settings_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    next_value = "false" if enabled else "true"
    label = "Выключить" if enabled else "Включить"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"{DAILY_QUIZ_TOGGLE_PREFIX}{next_value}")]]
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
            "Можно пройти сейчас или пропустить сегодня.",
        ]
    )
    return "\n".join(lines)


def _daily_quiz_offer_keyboard(topic_id: str, today: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Пройти",
                    callback_data=f"{DAILY_QUIZ_START_PREFIX}{topic_id}",
                ),
                InlineKeyboardButton(
                    "Пропустить",
                    callback_data=f"{DAILY_QUIZ_SKIP_PREFIX}{today}",
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
    await _answer_long(
        update,
        format_tasks(
            tasks,
            empty_text="Сейчас нет задач, которые пора повторять.",
            title="Пора повторять",
        ),
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


def _material_context(services: AppServices, session: QuizSession) -> list[dict[str, str]]:
    repo_path = services.repo.repo_path
    raw_paths = session.material_snapshot.get("source_paths")
    if not repo_path or not isinstance(raw_paths, list):
        return []
    context: list[dict[str, str]] = []
    total_chars = 0
    for raw_path in raw_paths[:8]:
        rel = str(raw_path).strip()
        if not rel:
            continue
        path = repo_path / rel
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        excerpt = content[:5000]
        total_chars += len(excerpt)
        context.append({"source_path": rel, "excerpt": excerpt})
        if total_chars >= 25000:
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
    start_call,
) -> None:
    services = _services(context)
    log.info(
        "Starting instant quiz from Telegram topic_title=%s questions=%s",
        topic_title,
        services.quiz_question_count,
    )
    await query.edit_message_text(
        _generation_wait_text(
            topic_title=topic_title,
            question_count=services.quiz_question_count,
            frame=GENERATION_FRAMES[0],
        )
    )
    animation_task = asyncio.create_task(
        _animate_generation_message(
            query,
            topic_title=topic_title,
            question_count=services.quiz_question_count,
        )
    )
    try:
        result = await asyncio.to_thread(
            start_call,
            question_count=services.quiz_question_count,
        )
    except QuizGenerationError as exc:
        log.exception("Instant quiz generation failed topic_title=%s", topic_title)
        await query.edit_message_text(
            "Не удалось сгенерировать моментальный тест.\n\n"
            f"Причина: {exc}\n\n"
            "Попробуй позже или проверь генерацию через `quiz-preview`."
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
        "<b>💡 Темы на изучение</b>\n\n"
        "Сохраняй сюда голосовые и текстовые идеи для будущей ручной проработки.",
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
        reply_markup=_daily_quiz_settings_keyboard(services.daily_quiz.is_enabled()),
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
        reply_markup=_daily_quiz_settings_keyboard(enabled),
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
    topic_id = (query.data or "").removeprefix(DAILY_QUIZ_START_PREFIX).strip().lower()
    topic = services.repo.get_topic(topic_id)
    if not topic:
        await query.edit_message_text("Тема ежедневного теста уже не найдена. Завтра выберу новую.")
        return

    await _start_instant_quiz(
        query,
        context,
        topic_title=topic.title,
        start_call=lambda *, question_count: services.quiz.start_instant_topic_session(
            topic.id,
            question_count=question_count,
        ),
    )


async def daily_quiz_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    today = (query.data or "").removeprefix(DAILY_QUIZ_SKIP_PREFIX).strip()
    await query.answer("Пропущено")
    await query.edit_message_text(
        "<b>Ежедневный тест пропущен</b>\n\n"
        f"Дата: <code>{html.escape(today, quote=False)}</code>",
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
    raw_index = (query.data or "").removeprefix(INSTANT_BLOCK_PREFIX)
    try:
        index = int(raw_index)
    except ValueError:
        await query.edit_message_text("Не понял выбранный блок. Нажми «Пройти тест сейчас» еще раз.")
        return

    grouped = _ready_review_topics_by_section(_services(context))
    sections = list(grouped.items())
    if index < 0 or index >= len(sections):
        await query.edit_message_text("Список блоков устарел. Нажми «Пройти тест сейчас» еще раз.")
        return

    section, topics = sections[index]
    await query.edit_message_text(
        _instant_topics_text(section, topics),
        parse_mode=ParseMode.HTML,
        reply_markup=_instant_topic_keyboard(index, topics),
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

    await _start_instant_quiz(
        query,
        context,
        topic_title=topic.title,
        start_call=lambda *, question_count: services.quiz.start_instant_topic_session(
            topic.id,
            question_count=question_count,
        ),
    )


async def instant_block_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    owner_id = _owner_id(context)
    if not query.from_user or query.from_user.id != owner_id:
        await query.answer("Это личный бот LearnKeeper.", show_alert=True)
        return

    await query.answer()
    raw_index = (query.data or "").removeprefix(INSTANT_BLOCK_ALL_PREFIX)
    try:
        index = int(raw_index)
    except ValueError:
        await query.edit_message_text("Не понял выбранный блок. Нажми «Пройти тест сейчас» еще раз.")
        return

    services = _services(context)
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
        start_call=lambda *, question_count: services.quiz.start_instant_block_session(
            section,
            question_count=question_count,
        ),
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

    log.info("Starting quiz from Telegram callback task_id=%s topic_id=%s", task.id, task.topic_id)
    await query.edit_message_text(
        _generation_wait_text(
            topic_title=task.topic_title,
            question_count=services.quiz_question_count,
            frame=GENERATION_FRAMES[0],
        )
    )
    animation_task = asyncio.create_task(
        _animate_generation_message(
            query,
            topic_title=task.topic_title,
            question_count=services.quiz_question_count,
        )
    )
    try:
        result = await asyncio.to_thread(
            services.quiz.start_session,
            task_id,
            question_count=services.quiz_question_count,
        )
    except QuizGenerationError as exc:
        animation_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await animation_task
        log.exception("Quiz generation failed for task_id=%s", task_id)
        await query.edit_message_text(
            "Не удалось сгенерировать тест.\n\n"
            f"Причина: {exc}\n\n"
            "Попробуй позже или проверь генерацию через `quiz-preview`."
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
        await query.edit_message_text(
            text=format_instant_quiz_report(result.session, questions, answers),
            reply_markup=_quiz_report_keyboard(result.session.id, questions, answers),
            parse_mode=ParseMode.HTML,
        )
        return

    if not result.session.task_id:
        await query.edit_message_text("Тест завершен, но не удалось найти связанную задачу.")
        return

    task = result.finished_task or services.review_tasks.get_task(result.session.task_id)
    await query.edit_message_text(
        text=format_quiz_report(result.session, questions, answers, task),
        reply_markup=_quiz_report_keyboard(result.session.id, questions, answers),
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
        "<b>Разбираю ошибки</b>\n\n"
        "Отправил отчет агенту. Это может занять немного времени.",
        parse_mode=ParseMode.HTML,
    )
    request = _mistake_review_input(services, session, questions, answers)
    log.info(
        "Mistake review queued session_id=%s mistakes=%s topic_id=%s",
        session.id,
        len(request.mistakes),
        session.topic_id,
    )
    try:
        report = await asyncio.to_thread(services.mistake_review_agent.analyze, request)
    except MistakeReviewAgentError as exc:
        log.warning("Mistake review failed session_id=%s error=%s", session.id, exc)
        await _safe_query_edit(
            query,
            "<b>Не удалось разобрать ошибки</b>\n\n"
            f"Причина: {html.escape(str(exc), quote=False)}",
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as exc:
        log.exception("Mistake review failed unexpectedly session_id=%s", session.id)
        await _safe_query_edit(
            query,
            "<b>Не удалось разобрать ошибки</b>\n\n"
            f"Причина: {html.escape(str(exc), quote=False)}",
            parse_mode=ParseMode.HTML,
        )
        return

    pending = context.user_data.setdefault("pending_mistake_reports", {})
    pending[session.id] = {"report": report, "questions": request.mistakes}
    await _safe_query_edit(
        query,
        format_mistake_review_preview(report),
        parse_mode=ParseMode.HTML,
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
    raw_index = (query.data or "").removeprefix(REVIEW_BLOCK_PREFIX)
    try:
        index = int(raw_index)
    except ValueError:
        await query.edit_message_text("Не понял выбранный блок. Нажми «Добавить повтор» еще раз.")
        return

    grouped = _ready_review_topics_by_section(_services(context))
    sections = list(grouped.items())
    if index < 0 or index >= len(sections):
        await query.edit_message_text("Список блоков устарел. Нажми «Добавить повтор» еще раз.")
        return

    section, topics = sections[index]
    await query.edit_message_text(
        _review_topics_text(section, topics),
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
    if awaiting_review and not awaiting_study:
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
    if not awaiting_review and not awaiting_study:
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
            f"Голосом сейчас можно пользоваться после <b>{BTN_IDEAS_MENU}</b> → <b>{BTN_TOPIC_ADD}</b>.",
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

    context.user_data["awaiting_review_topic"] = False
    context.user_data["awaiting_study_topic"] = False
    await _edit_or_reply(
        update,
        wait_message,
        f"<b>Распознал:</b> {html.escape(query, quote=False)}\n\nОбрабатываю...",
        parse_mode=ParseMode.HTML,
    )
    if awaiting_study:
        await _create_topic_inbox_item(update, context, query, source="voice")
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

    context.user_data["awaiting_review_topic"] = False
    context.user_data["awaiting_study_topic"] = False
    if text in (BTN_TOPICS, "Темы"):
        await _show_topics(update, context)
        return
    if text == BTN_REVIEW_MENU:
        await _show_review_menu(update, context)
        return
    if text == BTN_TEST_MENU:
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
    if text in (BTN_DAILY_QUIZ, "Ежедневные тесты"):
        await _show_daily_quiz_settings(update, context)
        return
    if text in (BTN_LLM_USAGE, "Токены LLM"):
        await _show_llm_usage(update, context)
        return
    if text in (BTN_CHANGELOG, "Changelog"):
        await _show_changelog(update, context)
        return
    if text in (BTN_STUDY_TOPICS, "Темы на изучение"):
        await _show_study_topics_menu(update, context)
        return
    if text in (BTN_TOPIC_ADD, "Добавить тему"):
        context.user_data["awaiting_study_topic"] = True
        await _answer_long(update, format_study_topic_prompt())
        return
    if text in (BTN_TOPIC_INBOX, "Идеи тем"):
        await _show_topic_inbox(update, context)
        return
    if text in (BTN_MISTAKE_WORK, BTN_MISTAKE_WORK_ACTIVE, "Работа над ошибками", "Активные отчеты"):
        await _show_mistake_work_active(update, context)
        return
    if text in (BTN_MISTAKE_WORK_DONE, "Проработанные"):
        await _show_mistake_work_done(update, context)
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
        f"Новые темы лежат в разделе <b>{BTN_IDEAS_MENU}</b>.",
    )


async def notify_due_reviews(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = _services(context)
    owner_id = _owner_id(context)
    tasks = services.review_tasks.due_for_notification(now=datetime.now(), limit=10)
    if not tasks:
        return

    for task in tasks:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Начать тест", callback_data=f"{START_REVIEW_PREFIX}{task.id}")]]
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

    try:
        await context.bot.send_message(
            chat_id=owner_id,
            text=_daily_quiz_offer_text(topic),
            reply_markup=_daily_quiz_offer_keyboard(topic.id, today.isoformat()),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        log.exception("Failed to send daily quiz offer topic_id=%s", topic.id)
        return

    services.daily_quiz.mark_sent(today)
    log.info("Daily quiz offer sent topic_id=%s date=%s", topic.id, today.isoformat())


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
    app.add_handler(CallbackQueryHandler(review_add_blocks_callback, pattern=f"^{REVIEW_ADD_BLOCKS}$"))
    app.add_handler(CallbackQueryHandler(review_block_callback, pattern=f"^{REVIEW_BLOCK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(review_topic_callback, pattern=f"^{REVIEW_TOPIC_PREFIX}"))
    app.add_handler(CallbackQueryHandler(reset_review_callback, pattern=f"^{RESET_REVIEW_PREFIX}"))
    app.add_handler(CallbackQueryHandler(abort_review_add_callback, pattern=f"^{ABORT_REVIEW_ADD}$"))
    app.add_handler(CallbackQueryHandler(menu_schedule_callback, pattern=f"^{MENU_SCHEDULE}$"))
    app.add_handler(CallbackQueryHandler(menu_due_callback, pattern=f"^{MENU_DUE}$"))
    app.add_handler(CallbackQueryHandler(menu_cancel_reviews_callback, pattern=f"^{MENU_CANCEL_REVIEWS}$"))
    app.add_handler(CallbackQueryHandler(menu_study_topics_callback, pattern=f"^{MENU_STUDY_TOPICS}$"))
    app.add_handler(CallbackQueryHandler(menu_topic_add_callback, pattern=f"^{MENU_TOPIC_ADD}$"))
    app.add_handler(CallbackQueryHandler(menu_topic_inbox_callback, pattern=f"^{MENU_TOPIC_INBOX}$"))
    app.add_handler(CallbackQueryHandler(menu_mistake_work_callback, pattern=f"^{MENU_MISTAKE_WORK}$"))
    app.add_handler(CallbackQueryHandler(menu_mistake_work_done_callback, pattern=f"^{MENU_MISTAKE_WORK_DONE}$"))
    app.add_handler(CallbackQueryHandler(menu_daily_settings_callback, pattern=f"^{MENU_DAILY_SETTINGS}$"))
    app.add_handler(CallbackQueryHandler(menu_llm_usage_callback, pattern=f"^{MENU_LLM_USAGE}$"))
    app.add_handler(CallbackQueryHandler(menu_changelog_callback, pattern=f"^{MENU_CHANGELOG}$"))
    app.add_handler(CallbackQueryHandler(daily_quiz_toggle_callback, pattern=f"^{DAILY_QUIZ_TOGGLE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(daily_quiz_start_callback, pattern=f"^{DAILY_QUIZ_START_PREFIX}"))
    app.add_handler(CallbackQueryHandler(daily_quiz_skip_callback, pattern=f"^{DAILY_QUIZ_SKIP_PREFIX}"))
    app.add_handler(CallbackQueryHandler(instant_blocks_callback, pattern=f"^{INSTANT_BLOCKS}$"))
    app.add_handler(CallbackQueryHandler(instant_block_all_callback, pattern=f"^{INSTANT_BLOCK_ALL_PREFIX}"))
    app.add_handler(CallbackQueryHandler(instant_block_callback, pattern=f"^{INSTANT_BLOCK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(instant_topic_callback, pattern=f"^{INSTANT_TOPIC_PREFIX}"))
    app.add_handler(CallbackQueryHandler(abort_instant_quiz_callback, pattern=f"^{ABORT_INSTANT_QUIZ}$"))
    app.add_handler(CallbackQueryHandler(start_review_callback, pattern=f"^{START_REVIEW_PREFIX}"))
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
        app.job_queue.run_daily(
            send_daily_quiz_offer,
            time=datetime_time(
                hour=settings.daily_quiz_hour,
                minute=settings.daily_quiz_minute,
                tzinfo=_daily_quiz_timezone(settings),
            ),
            name="daily-quiz-offer",
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
