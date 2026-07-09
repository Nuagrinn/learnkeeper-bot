from __future__ import annotations

import argparse
import asyncio
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from time import perf_counter

from app.config import load_settings
from app.core.db import Database
from app.core.repo import RepoService
from app.features.llm_usage.service import (
    LlmUsageBudgetConfig,
    LlmUsagePriceConfig,
    LlmUsageService,
)
from app.features.materials.mtproto import MaterialMtprotoError, MaterialMtprotoSender
from app.features.quiz.factory import build_quiz_generator
from app.features.quiz.generator import QuizGenerationError
from app.features.review_tasks.service import ReviewTaskService, TopicNotReadyError
from app.features.speech.factory import build_speech_to_text
from app.features.speech.service import SpeechToTextError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="learnkeeper-bot")
    parser.add_argument("--db", help="Path to SQLite database")
    parser.add_argument("--repo", help="Path to local interview-review repository")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create/update local SQLite schema")
    sub.add_parser("migrate", help="Apply pending SQLite migrations")
    sub.add_parser("db-status", help="Show SQLite database and applied migrations")
    sub.add_parser("repo-status", help="Show configured interview-review repository")
    sub.add_parser("llm-usage", help="Show local LLM usage statistics")

    material_mtproto = sub.add_parser(
        "material-mtproto-probe",
        help="Send one markdown material through MTProto with text/markdown MIME",
    )
    material_mtproto.add_argument("topic", help="Topic id/title/search query")
    material_mtproto.add_argument(
        "--source",
        default="",
        help="Optional material path from interview-review. Defaults to first .md source.",
    )
    material_mtproto.add_argument(
        "--pull",
        action="store_true",
        help="Run the configured interview-review git pull before sending the probe.",
    )

    add = sub.add_parser("review-add", help="Create a review task for a topic")
    add.add_argument("topic", help="Topic title or search query")
    add.add_argument("--due-days", type=int, default=1, help="Initial due offset")

    schedule = sub.add_parser("schedule", help="Show upcoming active review tasks")
    schedule.add_argument("--limit", type=int, default=20)

    due = sub.add_parser("due", help="Show review tasks due now")
    due.add_argument("--limit", type=int, default=20)

    complete = sub.add_parser("complete", help="Complete a task with a quiz score")
    complete.add_argument("task_id")
    complete.add_argument("score", type=float, help="Score percent, e.g. 85")

    cancel = sub.add_parser("cancel", help="Cancel an active review task")
    cancel.add_argument("task_id")

    topics = sub.add_parser("topics", help="Search topics in interview-review")
    topics.add_argument("query", nargs="?", default="")
    topics.add_argument("--limit", type=int, default=20)

    quiz_preview = sub.add_parser(
        "quiz-preview",
        help="Generate quiz questions for a topic without saving a session",
    )
    quiz_preview.add_argument("topic", help="Topic title or search query")
    quiz_preview.add_argument("--questions", type=int, default=None)

    sub.add_parser("stt-status", help="Show local speech-to-text configuration")

    stt_preview = sub.add_parser(
        "stt-preview",
        help="Transcribe an audio file through the configured local STT provider",
    )
    stt_preview.add_argument("audio", help="Path to .oga/.mp3/.wav audio file")
    stt_preview.add_argument(
        "--provider",
        choices=["disabled", "whisper_cpp", "whisper_cli", "openai"],
        default=None,
        help="Override STT_PROVIDER for this run",
    )

    return parser


def _service(args: argparse.Namespace) -> tuple[ReviewTaskService, RepoService]:
    settings = load_settings(db_path=args.db, repo_path=args.repo)
    db = Database(settings.db_path)
    db.initialize()
    repo = RepoService(settings.interview_review_path)
    return ReviewTaskService(db, repo), repo


def _print_task(row) -> None:
    print(
        f"{row.id} | {row.topic_title} | stage={row.stage} | "
        f"due={row.due_at:%d-%m-%Y} | status={row.status}"
    )


def _tool_exists(command: str) -> bool:
    path = Path(command)
    if path.is_absolute() or path.parent != Path("."):
        return path.exists()
    return shutil.which(command) is not None


def _select_material_source(topic, requested_source: str = "") -> str:
    requested = requested_source.strip().replace("\\", "/")
    if requested:
        return requested
    for source_path in topic.source_paths:
        if Path(source_path).suffix.lower() in (".md", ".markdown"):
            return source_path
    return topic.source_paths[0] if topic.source_paths else ""


def _material_probe_filename(topic_id: str, source_path: str) -> str:
    source = Path(source_path.replace("\\", "/"))
    stem = source.stem or "material"
    suffix = source.suffix or ".md"
    return f"{topic_id.lower()}-{stem}{suffix}"


async def _send_material_mtproto_probe(args: argparse.Namespace) -> None:
    settings = load_settings(db_path=args.db, repo_path=args.repo)
    repo = RepoService(settings.interview_review_path)
    if not repo.is_available() or repo.repo_path is None:
        print("interview-review repository is not configured or not available.")
        return

    if args.pull and settings.repo_pull_before_read:
        pull = repo.pull_latest(
            remote=settings.repo_git_remote,
            branch=settings.repo_git_branch,
            timeout_seconds=settings.repo_pull_timeout_seconds,
        )
        print(f"Repo pull: {pull.status}")
        if pull.detail:
            print(pull.detail)

    topic = repo.resolve_topic(args.topic)
    source_path = _select_material_source(topic, args.source)
    if not source_path:
        print(f"No material source found for topic: {topic.id} | {topic.title}")
        return

    file_path = repo.repo_path / source_path
    filename = _material_probe_filename(topic.id, source_path)
    sender = MaterialMtprotoSender(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        bot_token=settings.telegram_bot_token,
        session_path=settings.telegram_mtproto_session,
        recipient_id=settings.tg_user_id,
    )
    caption = f"MTProto markdown probe\n{topic.id} | {topic.title}\n{source_path}"
    try:
        result = await sender.send_markdown_document(
            file_path=file_path,
            filename=filename,
            caption=caption,
        )
    except MaterialMtprotoError as exc:
        print(f"MTProto material probe failed: {exc}")
        print()
        print("Required settings:")
        print("- TELEGRAM_API_ID")
        print("- TELEGRAM_API_HASH")
        print("- TELEGRAM_BOT_TOKEN")
        print("- TG_USER_ID")
        return

    print("MTProto material probe sent.")
    print(f"Message ID: {result.message_id}")
    print(f"Filename: {result.filename}")
    print(f"Requested MIME: {result.requested_mime_type}")
    print(f"Stored MIME: {result.stored_mime_type or '(none)'}")


def _print_stt_status(settings) -> None:
    print(f"STT provider: {settings.stt_provider}")
    print(f"Voice dir: {settings.voice_dir}")
    print(f"Language: {settings.stt_language}")
    print(f"Timeout: {settings.stt_timeout_seconds}s")
    print()
    print("Local tools:")
    print(f"- ffmpeg: {'OK' if _tool_exists(settings.ffmpeg_bin) else 'not found'} ({settings.ffmpeg_bin})")
    print(
        "- whisper.cpp bin: "
        f"{'OK' if _tool_exists(settings.stt_whisper_cpp_bin) else 'not found'} "
        f"({settings.stt_whisper_cpp_bin})"
    )
    print(
        "- whisper.cpp model: "
        f"{'OK' if settings.stt_whisper_cpp_model.exists() else 'not found'} "
        f"({settings.stt_whisper_cpp_model})"
    )
    print(
        "- whisper CLI: "
        f"{'OK' if _tool_exists(settings.stt_whisper_bin) else 'not found'} "
        f"({settings.stt_whisper_bin})"
    )
    print()
    print("Recommended no-credit setup:")
    print("STT_PROVIDER=whisper_cpp")
    print(f"STT_WHISPER_CPP_BIN={settings.stt_whisper_cpp_bin}")
    print(f"STT_WHISPER_CPP_MODEL={settings.stt_whisper_cpp_model}")


def _build_llm_usage_service(settings) -> LlmUsageService:
    db = Database(settings.db_path)
    db.migrate()
    return LlmUsageService(
        db,
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


def _print_llm_usage(service: LlmUsageService) -> None:
    print("LLM usage")
    print("Token counts are currently estimated from input/output text size.")
    if not service.prices_configured:
        print(
            "Cost estimate: disabled "
            "(set LLM_INPUT_USD_PER_1M_TOKENS and LLM_OUTPUT_USD_PER_1M_TOKENS)."
        )
    if not service.budgets_configured:
        print(
            "Budget percentages: disabled "
            "(set LLM_USAGE_BUDGET_5H_USD / DAILY / WEEKLY / MONTHLY)."
        )
    for stats in service.stats_for_periods():
        print()
        print(stats.label)
        print(f"- requests: {stats.request_count} (errors: {stats.failure_count})")
        print(
            f"- tokens: {stats.total_tokens} "
            f"(input={stats.input_tokens}, output={stats.output_tokens})"
        )
        print(f"- wait: {round(stats.duration_ms / 1000)}s")
        if service.prices_configured:
            print(f"- API-equivalent: ${stats.estimated_usd:.6f}")
        if stats.budget_usd > 0:
            print(
                f"- budget: {stats.budget_percent:.2f}% "
                f"of ${stats.budget_usd:.2f}"
            )
        if stats.features:
            print("- features:")
            for feature in stats.features[:5]:
                print(
                    f"  {feature.feature}: {feature.total_tokens} tokens, "
                    f"{feature.request_count} requests"
                )


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "init-db":
        settings = load_settings(db_path=args.db, repo_path=args.repo)
        result = Database(settings.db_path).migrate()
        print(f"DB ready: {settings.db_path}")
        if result.applied:
            print("Applied migrations:")
            for version in result.applied:
                print(f"- {version}")
        return

    if args.command == "migrate":
        settings = load_settings(db_path=args.db, repo_path=args.repo)
        result = Database(settings.db_path).migrate()
        print(f"DB ready: {settings.db_path}")
        if result.applied:
            print("Applied migrations:")
            for version in result.applied:
                print(f"- {version}")
        else:
            print("No pending migrations.")
        return

    if args.command == "db-status":
        settings = load_settings(db_path=args.db, repo_path=args.repo)
        db = Database(settings.db_path)
        migrations = db.applied_migrations()
        print(f"DB path: {settings.db_path}")
        print(f"Exists: {settings.db_path.exists()}")
        print("Applied migrations:")
        if migrations:
            for version in migrations:
                print(f"- {version}")
        else:
            print("- none")
        return

    if args.command == "repo-status":
        settings = load_settings(db_path=args.db, repo_path=args.repo)
        repo = RepoService(settings.interview_review_path)
        print(f"Repo path: {settings.interview_review_path or '(not configured)'}")
        print(f"Available: {repo.is_available()}")
        topics_count = len(repo.list_topics()) if repo.is_available() else 0
        print(f"Indexed topics: {topics_count}")
        return

    if args.command == "llm-usage":
        settings = load_settings(db_path=args.db, repo_path=args.repo)
        _print_llm_usage(_build_llm_usage_service(settings))
        return

    if args.command == "material-mtproto-probe":
        asyncio.run(_send_material_mtproto_probe(args))
        return

    if args.command == "stt-status":
        settings = load_settings(db_path=args.db, repo_path=args.repo)
        _print_stt_status(settings)
        return

    if args.command == "stt-preview":
        settings = load_settings(db_path=args.db, repo_path=args.repo)
        if args.provider:
            settings = replace(settings, stt_provider=args.provider)
        audio_path = Path(args.audio)
        if not audio_path.is_absolute():
            audio_path = Path.cwd() / audio_path
        if not audio_path.exists():
            print(f"Audio file not found: {audio_path}")
            return
        transcriber = build_speech_to_text(settings)
        print(f"Provider: {transcriber.provider}")
        print(f"Model: {transcriber.model}")
        print(f"Audio: {audio_path}")
        started_at = perf_counter()
        try:
            text = transcriber.transcribe(audio_path)
        except SpeechToTextError as exc:
            print(f"STT failed: {exc}")
            return
        elapsed = perf_counter() - started_at
        print(f"Elapsed: {elapsed:.2f}s")
        print()
        print(text)
        return

    service, repo = _service(args)

    if args.command == "review-add":
        try:
            result = service.create_review_task(
                args.topic,
                initial_due_days=args.due_days,
                replace_existing=True,
            )
        except TopicNotReadyError as exc:
            print(f"Cannot create review task: {exc.reason}")
            if exc.suggestions:
                print("Ready topics:")
                for item in exc.suggestions:
                    print(f"- {item}")
            return
        action = "created" if result.created else "already exists"
        print(f"Review task {action}:")
        _print_task(result.task)
        if result.topic.source_paths:
            print("Sources:")
            for path in result.topic.source_paths:
                print(f"- {path}")
        return

    if args.command == "schedule":
        tasks = service.upcoming(limit=args.limit)
        if not tasks:
            print("No active review tasks.")
            return
        for task in tasks:
            _print_task(task)
        return

    if args.command == "due":
        tasks = service.due_tasks(now=datetime.now(), limit=args.limit)
        if not tasks:
            print("No due review tasks.")
            return
        for task in tasks:
            _print_task(task)
        return

    if args.command == "complete":
        task = service.complete_task(args.task_id, args.score)
        print("Task updated:")
        _print_task(task)
        return

    if args.command == "cancel":
        task = service.cancel_task(args.task_id)
        print("Task cancelled:")
        _print_task(task)
        return

    if args.command == "topics":
        matches = (
            repo.search_topics(args.query, limit=args.limit)
            if args.query
            else repo.list_topics()[: args.limit]
        )
        if not matches:
            print("No matching topics found.")
            return
        for topic in matches:
            paths = ", ".join(topic.source_paths) or "-"
            section = f" | {topic.section}" if topic.section else ""
            print(f"{topic.id} | {topic.title} | {topic.status}{section} | {paths}")
        return

    if args.command == "quiz-preview":
        settings = load_settings(db_path=args.db, repo_path=args.repo)
        repo = RepoService(settings.interview_review_path)
        topic = repo.resolve_topic(args.topic)
        materials = repo.get_topic_materials(topic)
        llm_usage = _build_llm_usage_service(settings)
        generator = build_quiz_generator(settings, usage_recorder=llm_usage)
        count = args.questions or settings.quiz_question_count
        try:
            questions = generator.generate(
                topic=topic,
                materials=materials,
                question_count=count,
            )
        except QuizGenerationError as exc:
            print(f"Quiz generation failed: {exc}")
            return

        print(
            f"Generator: {getattr(generator, 'provider', 'unknown')} "
            f"{getattr(generator, 'model', '')}".strip()
        )
        print(f"Topic: {topic.id} | {topic.title}")
        print(f"Sources: {', '.join(path for path in topic.source_paths) or '-'}")
        print()
        labels = ["A", "B", "C", "D"]
        for no, question in enumerate(questions, start=1):
            print(f"{no}. {question.text}")
            for index, option in enumerate(question.options):
                print(f"   {labels[index]}. {option}")
            print(f"   Correct: {labels[question.correct_index]}")
            print(f"   Explanation: {question.explanation}")
            print(f"   Sources: {', '.join(question.source_refs)}")
            print()
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
