from __future__ import annotations

import unittest
from datetime import datetime

from app.adapters.telegram.formatters import (
    format_cancel_review_confirm,
    format_cancel_review_done,
    format_cancel_review_list,
    format_due_notification,
    format_explain_check_list,
    format_explain_check_report,
    format_instant_quiz_report,
    format_llm_usage_report,
    format_mistake_review_preview,
    format_mistake_work_item,
    format_mistake_work_list,
    format_review_created,
    format_review_creation_started,
    format_topics,
    split_message,
)
from app.adapters.telegram.formatters import format_quiz_question, format_quiz_report
from app.core.repo import RepoTopic
from app.features.llm_usage.models import LlmFeatureUsage, LlmUsageStats
from app.features.explain_check.models import ExplanationCheck
from app.features.mistake_work.agent import MistakeReviewResult
from app.features.mistake_work.models import MistakeWorkItem
from app.features.quiz.models import QuizAnswer, QuizQuestion, QuizSession
from app.features.review_tasks.models import ReviewTask
from app.adapters.telegram.formatters import format_task, format_tasks


class TelegramFormattersTest(unittest.TestCase):
    def test_format_task(self) -> None:
        task = ReviewTask(
            id="abc123",
            topic_id="b01",
            topic_title="Слайсы",
            created_at=datetime(2026, 7, 3, 10, 0),
            due_at=datetime(2026, 7, 4, 10, 0),
            stage=1,
            status="active",
            interval_days=1,
        )

        text = format_task(task)

        self.assertIn("<b>Слайсы</b>", text)
        self.assertIn("Этап: 1/3", text)
        self.assertIn("<b>Дата:</b> <code>04-07-2026</code>", text)
        self.assertIn("Статус: 🟢 активна", text)
        self.assertIn("<code>abc123</code>", text)

    def test_format_topics(self) -> None:
        topic = RepoTopic(
            id="b01",
            title="Слайсы",
            status="ready",
            section="Базовый Go",
            source_paths=["base-go/slices.md"],
        )

        text = format_topics([topic])

        self.assertIn("<b>Темы</b>", text)
        self.assertIn("<b>Базовый Go</b>", text)
        self.assertIn("<code>b01</code> · ✅ Слайсы", text)
        self.assertNotIn("<code>base-go/slices.md</code>", text)

    def test_format_review_created_hides_materials(self) -> None:
        task = ReviewTask(
            id="abc123",
            topic_id="b01",
            topic_title="Слайсы",
            created_at=datetime(2026, 7, 3, 10, 0),
            due_at=datetime(2026, 7, 4, 9, 0),
            stage=1,
            status="active",
            interval_days=1,
        )

        text = format_review_created(
            task,
            created=False,
            source_paths=["base-go/slices.md"],
        )

        self.assertIn("Задача не создана", text)
        self.assertIn("такая активная задача уже есть", text)
        self.assertIn("<b>Слайсы</b>", text)
        self.assertNotIn("Материалы", text)
        self.assertNotIn("base-go/slices.md", text)

    def test_format_review_creation_started(self) -> None:
        text = format_review_creation_started("слайсы <go>")

        self.assertIn("Принял команду на создание задачи", text)
        self.assertIn("<code>слайсы &lt;go&gt;</code>", text)
        self.assertIn("это может занять немного времени", text)

    def test_format_tasks_empty(self) -> None:
        self.assertEqual("empty", format_tasks([], empty_text="empty"))

    def test_format_tasks(self) -> None:
        task = ReviewTask(
            id="abc123",
            topic_id="b01",
            topic_title="Слайсы",
            created_at=datetime(2026, 7, 3, 10, 0),
            due_at=datetime(2026, 7, 4, 10, 0),
            stage=1,
            status="active",
            interval_days=1,
        )

        text = format_tasks([task], empty_text="empty", title="Ближайшие повторы")

        self.assertIn("<b>Ближайшие повторы</b>", text)
        self.assertIn("Всего: 1", text)
        self.assertIn("<b>1.</b>", text)
        self.assertIn("<b>Слайсы</b>", text)
        self.assertIn("<b>Дата:</b> <code>04-07-2026</code>", text)
        self.assertNotIn("<code>abc123</code>", text)

    def test_format_cancel_review_list_empty(self) -> None:
        text = format_cancel_review_list([])

        self.assertIn("Удалить повтор", text)
        self.assertIn("Активных отложенных задач сейчас нет", text)

    def test_format_cancel_review_confirm(self) -> None:
        task = ReviewTask(
            id="abc123",
            topic_id="b01",
            topic_title="Слайсы",
            created_at=datetime(2026, 7, 3, 10, 0),
            due_at=datetime(2026, 7, 4, 9, 0),
            stage=1,
            status="active",
            interval_days=1,
        )

        text = format_cancel_review_confirm(task)

        self.assertIn("Отменить отложенный повтор", text)
        self.assertIn("<b>Слайсы</b>", text)
        self.assertIn("<code>04-07-2026</code>", text)
        self.assertIn("История не удалится", text)

    def test_format_cancel_review_done(self) -> None:
        task = ReviewTask(
            id="abc123",
            topic_id="b01",
            topic_title="Слайсы",
            created_at=datetime(2026, 7, 3, 10, 0),
            due_at=datetime(2026, 7, 4, 9, 0),
            stage=1,
            status="cancelled",
            interval_days=1,
        )

        text = format_cancel_review_done(task)

        self.assertIn("Повтор отменен", text)
        self.assertIn("<b>Слайсы</b>", text)
        self.assertIn("история сохранена", text)

    def test_split_message(self) -> None:
        text = "\n".join(f"line {i}" for i in range(20))
        chunks = split_message(text, limit=40)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 40 for chunk in chunks))

    def test_format_due_notification(self) -> None:
        task = ReviewTask(
            id="abc123",
            topic_id="b01",
            topic_title="Слайсы",
            created_at=datetime(2026, 7, 3, 10, 0),
            due_at=datetime(2026, 7, 4, 10, 0),
            stage=1,
            status="active",
            interval_days=1,
        )

        text = format_due_notification(task)

        self.assertIn("Пора повторить тему", text)
        self.assertIn("Слайсы", text)
        self.assertIn("Этап: 1", text)
        self.assertIn("<b>Плановая дата:</b> <code>04-07-2026</code>", text)

    def test_format_quiz_question(self) -> None:
        session = QuizSession(
            id="s1",
            task_id="t1",
            topic_id="b01",
            status="in_progress",
            question_count=2,
            current_question_no=1,
            started_at=datetime(2026, 7, 3, 10, 0),
            material_fingerprint="abc",
            material_snapshot={},
        )
        question = QuizQuestion(
            id="q1",
            session_id="s1",
            question_no=1,
            text="Что такое slice?",
            options=["A1", "B1", "C1", "D1"],
            correct_index=0,
            explanation="Пояснение",
            source_refs=["base-go/slices.md"],
        )

        text = format_quiz_question(session, question)

        self.assertIn("Вопрос 1/2", text)
        self.assertIn("<b>A.</b> A1", text)
        self.assertIn("<b>D.</b> D1", text)

    def test_format_quiz_question_renders_code_block_and_inline(self) -> None:
        session = QuizSession(
            id="s1",
            task_id="t1",
            topic_id="b01",
            status="in_progress",
            question_count=2,
            current_question_no=1,
            started_at=datetime(2026, 7, 3, 10, 0),
            material_fingerprint="abc",
            material_snapshot={},
        )
        question = QuizQuestion(
            id="q1",
            session_id="s1",
            question_no=2,
            text="Дан код:\n\n```go\nif a < b {\n  fmt.Println(a & b)\n}\n```\n\nЧто выведет `x`?",
            options=["1", "100", "3", "0"],
            correct_index=0,
            explanation="Пояснение",
            source_refs=["base-go/slices.md"],
        )

        text = format_quiz_question(session, question)

        self.assertIn('<pre><code class="language-go">', text)
        self.assertNotIn("```", text)
        self.assertIn("a &lt; b", text)
        self.assertIn("a &amp; b", text)
        self.assertIn("<code>x</code>", text)

    def test_format_mistake_review_preview(self) -> None:
        report = MistakeReviewResult(
            title="Разбор индексов PostgreSQL",
            section="Базы данных",
            priority="high",
            summary="Путается INCLUDE и ключ индекса.",
            diagnosis="Нужно доразобрать устройство B-tree.",
            weak_concepts=["INCLUDE", "index-only scan"],
            material_suggestion={
                "title": "Индексы PostgreSQL: INCLUDE",
                "target_section": "Базы данных",
                "details": "Добавить материал про leaf tuples.",
            },
            questions_to_revisit=[
                {
                    "question_no": 2,
                    "missed_point": "INCLUDE не часть ключа.",
                    "correct_idea": "INCLUDE хранится для покрытия запроса.",
                    "practice_prompt": "Объяснить index-only scan.",
                }
            ],
            provider="fake",
            model="fake",
        )

        text = format_mistake_review_preview(report)

        self.assertIn("Разбор ошибок готов", text)
        self.assertIn("🔴 высокая", text)
        self.assertIn("Что потом добавить в lk-prep", text)
        self.assertIn("Можно сохранить", text)

    def test_long_mistake_review_preview_splits_within_telegram_limit(self) -> None:
        report = MistakeReviewResult(
            title="Слайсы и массивы " * 40,
            section="Базовый Go",
            priority="high",
            summary="Развёрнутое описание проблемы. " * 60,
            diagnosis="Подробный диагноз с деталями. " * 300,
            weak_concepts=[f"слабый концепт номер {i} с пояснением" for i in range(8)],
            material_suggestion={
                "title": "Слайсы",
                "target_section": "Базовый Go",
                "details": "Что добавить в материалы. " * 300,
            },
            questions_to_revisit=[
                {
                    "question_no": i,
                    "missed_point": "что было упущено в этом вопросе " * 80,
                    "correct_idea": "верная идея с объяснением " * 80,
                    "practice_prompt": "практическое задание для отработки " * 80,
                }
                for i in range(1, 6)
            ],
            provider="fake",
            model="fake",
        )

        preview = format_mistake_review_preview(report)
        self.assertGreater(len(preview), 4096)

        chunks = split_message(preview)
        self.assertGreaterEqual(len(chunks), 2)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 4096)

    def test_format_mistake_work_list_and_item(self) -> None:
        item = MistakeWorkItem(
            id="mw1",
            quiz_session_id="s1",
            topic_id="db01",
            topic_title="Индексы PostgreSQL",
            session_type="instant",
            status="active",
            priority="normal",
            title="Разбор индексов",
            section="Базы данных",
            summary="Пробел в INCLUDE.",
            diagnosis="Нужно доразобрать устройство индекса.",
            weak_concepts=["INCLUDE"],
            questions=[{"question_no": 2}],
            suggestion={"details": "Добавить примеры."},
            report={
                "questions_to_revisit": [
                    {
                        "question_no": 2,
                        "missed_point": "INCLUDE не ключ.",
                        "correct_idea": "INCLUDE хранится отдельно.",
                        "practice_prompt": "Объяснить на примере.",
                    }
                ]
            },
            agent_provider="fake",
            agent_model="fake",
            prompt_version="fake",
            created_at=datetime(2026, 7, 5, 11, 0),
            updated_at=datetime(2026, 7, 5, 11, 0),
        )

        list_text = format_mistake_work_list([item])
        item_text = format_mistake_work_item(item)

        self.assertIn("Активные отчеты", list_text)
        self.assertIn("Индексы PostgreSQL", list_text)
        self.assertIn("Работа над ошибками", item_text)
        self.assertIn("Что добавить/усилить", item_text)

    def test_format_explain_check_list_and_report(self) -> None:
        item = ExplanationCheck(
            id="ec1",
            topic_id="b08",
            topic_title="Строки в Go",
            section="Базовый Go",
            source="voice",
            explanation_text="Строки в Go неизменяемы, потому что...",
            status="active",
            priority="high",
            layer_reached=2,
            summary="В целом верно, но путает len с количеством символов.",
            covered_concepts=["string immutable"],
            missing_concepts=["rune vs byte в range"],
            false_models=[
                {
                    "false_model": "len(string) считает символы",
                    "correct_model": "len(string) считает байты UTF-8",
                }
            ],
            follow_up_question="Что выведет len(\"привет\")?",
            material_fingerprint="fp1",
            agent_provider="claude_cli_explain_check",
            agent_model="claude-sonnet-5",
            prompt_version="learnkeeper-explain-check-v1",
            created_at=datetime(2026, 7, 8, 11, 0),
            updated_at=datetime(2026, 7, 8, 11, 0),
        )

        list_text = format_explain_check_list([item])
        report_text = format_explain_check_report(item)

        self.assertIn("Мои объяснения", list_text)
        self.assertIn("Строки в Go", list_text)
        self.assertIn("Проверка объяснения", report_text)
        self.assertIn("2/4 — воспроизведение", report_text)
        self.assertIn("🔴 высокая", report_text)
        self.assertIn("len(string) считает символы", report_text)
        self.assertIn("len(string) считает байты UTF-8", report_text)
        self.assertIn("Что выведет", report_text)

    def test_long_explain_check_report_stays_within_telegram_limit(self) -> None:
        item = ExplanationCheck(
            id="ec2",
            topic_id="db02",
            topic_title="PostgreSQL: MVCC" * 10,
            section="Базы данных",
            source="text",
            explanation_text="Развернутое объяснение своими словами. " * 200,
            status="active",
            priority="normal",
            layer_reached=3,
            summary="Развернутая выжимка. " * 60,
            covered_concepts=[f"концепт {i} с подробным пояснением" for i in range(8)],
            missing_concepts=[f"пробел {i} с подробным пояснением" for i in range(8)],
            false_models=[
                {
                    "false_model": "ложная модель номер " * 20,
                    "correct_model": "верная модель номер " * 20,
                }
                for _ in range(6)
            ],
            follow_up_question="Развернутый вопрос на подумать. " * 40,
            material_fingerprint="fp2",
            agent_provider="claude_cli_explain_check",
            agent_model="claude-sonnet-5",
            prompt_version="learnkeeper-explain-check-v1",
            created_at=datetime(2026, 7, 8, 11, 0),
            updated_at=datetime(2026, 7, 8, 11, 0),
        )

        report = format_explain_check_report(item)
        chunks = split_message(report)

        for chunk in chunks:
            self.assertLessEqual(len(chunk), 4096)

    def test_format_quiz_report_with_mistakes(self) -> None:
        session = QuizSession(
            id="s1",
            task_id="t1",
            topic_id="b01",
            status="finished",
            question_count=1,
            current_question_no=1,
            started_at=datetime(2026, 7, 3, 10, 0),
            finished_at=datetime(2026, 7, 3, 10, 5),
            material_fingerprint="abc",
            material_snapshot={},
            score_percent=0,
            correct_count=0,
            total_count=1,
        )
        question = QuizQuestion(
            id="q1",
            session_id="s1",
            question_no=1,
            text="Что такое slice?",
            options=["A1", "B1", "C1", "D1"],
            correct_index=2,
            explanation="Пояснение",
            source_refs=["base-go/slices.md"],
        )
        answer = QuizAnswer(
            id="a1",
            session_id="s1",
            question_id="q1",
            selected_index=0,
            is_correct=False,
            answered_at=datetime(2026, 7, 3, 10, 1),
        )
        task = ReviewTask(
            id="t1",
            topic_id="b01",
            topic_title="Слайсы",
            created_at=datetime(2026, 7, 3, 10, 0),
            due_at=datetime(2026, 7, 4, 10, 0),
            stage=1,
            status="active",
            interval_days=1,
        )

        text = format_quiz_report(session, [question], [answer], task)

        self.assertIn("Тест завершен", text)
        self.assertIn("Результат:</b> 0%", text)
        self.assertIn("завершен этап 1 из 3", text)
        self.assertIn("Правильно:</b> C", text)
        self.assertIn("Следующий повтор", text)
        self.assertIn("через 1 день", text)
        self.assertIn("Что разобрать", text)

    def test_format_quiz_report_success_with_next_stage_interval(self) -> None:
        session = QuizSession(
            id="s1",
            task_id="t1",
            topic_id="b01",
            status="finished",
            question_count=5,
            current_question_no=5,
            started_at=datetime(2026, 7, 3, 10, 0),
            finished_at=datetime(2026, 7, 3, 10, 5),
            material_fingerprint="abc",
            material_snapshot={},
            score_percent=100,
            correct_count=5,
            total_count=5,
        )
        question = QuizQuestion(
            id="q1",
            session_id="s1",
            question_no=1,
            text="Что такое slice?",
            options=["A1", "B1", "C1", "D1"],
            correct_index=0,
            explanation="Пояснение",
            source_refs=["base-go/slices.md"],
        )
        answer = QuizAnswer(
            id="a1",
            session_id="s1",
            question_id="q1",
            selected_index=0,
            is_correct=True,
            answered_at=datetime(2026, 7, 3, 10, 1),
        )
        task = ReviewTask(
            id="t1",
            topic_id="b01",
            topic_title="Слайсы",
            created_at=datetime(2026, 7, 3, 10, 0),
            due_at=datetime(2026, 7, 10, 10, 0),
            stage=2,
            status="active",
            interval_days=7,
        )

        text = format_quiz_report(session, [question], [answer], task)

        self.assertIn("<b>Тема:</b> Слайсы", text)
        self.assertIn("завершен этап 1 из 3", text)
        self.assertIn("Результат:</b> 100% (5/5)", text)
        self.assertIn("через 7 дней (1 неделя)", text)
        self.assertIn("<code>10-07-2026</code>", text)
        self.assertIn("Ошибок нет", text)

    def test_format_instant_quiz_report_has_no_next_review(self) -> None:
        session = QuizSession(
            id="s1",
            task_id=None,
            topic_id="b01",
            topic_title="Слайсы",
            session_type="instant",
            status="finished",
            question_count=1,
            current_question_no=1,
            started_at=datetime(2026, 7, 3, 10, 0),
            finished_at=datetime(2026, 7, 3, 10, 5),
            material_fingerprint="abc",
            material_snapshot={},
            score_percent=100,
            correct_count=1,
            total_count=1,
        )
        question = QuizQuestion(
            id="q1",
            session_id="s1",
            question_no=1,
            text="Что такое slice?",
            options=["A1", "B1", "C1", "D1"],
            correct_index=0,
            explanation="Пояснение",
            source_refs=["base-go/slices.md"],
        )
        answer = QuizAnswer(
            id="a1",
            session_id="s1",
            question_id="q1",
            selected_index=0,
            is_correct=True,
            answered_at=datetime(2026, 7, 3, 10, 1),
        )

        text = format_instant_quiz_report(session, [question], [answer])

        self.assertIn("Моментальный тест завершен", text)
        self.assertIn("<b>Тема:</b> Слайсы", text)
        self.assertIn("Расписание:</b> не изменялось", text)
        self.assertNotIn("Следующий повтор", text)

    def test_format_llm_usage_report(self) -> None:
        stats = [
            LlmUsageStats(
                label="Сегодня",
                since=datetime(2026, 7, 5, 0, 0),
                request_count=2,
                success_count=1,
                failure_count=1,
                input_tokens=1000,
                output_tokens=200,
                total_tokens=1200,
                estimated_usd=0,
                duration_ms=65000,
                budget_usd=10,
                budget_percent=12.34,
                budget_tokens=10000,
                token_budget_percent=12.0,
                features=[
                    LlmFeatureUsage(
                        feature="quiz_generation",
                        request_count=2,
                        input_tokens=1000,
                        output_tokens=200,
                        total_tokens=1200,
                        estimated_usd=0,
                    )
                ],
            )
        ]

        text = format_llm_usage_report(stats, prices_configured=False)

        self.assertIn("LLM usage", text)
        self.assertIn("Сегодня", text)
        self.assertIn("Запросы: <b>2</b>", text)
        self.assertIn("<code>1 200</code>", text)
        self.assertIn("генерация тестов", text)
        # token budget line: absolute / budget (percent)
        self.assertIn("12.0%", text)
        self.assertIn("<code>10 000</code>", text)
        # cost line: absolute / budget (percent)
        self.assertIn("12.3%", text)
        self.assertIn("$10.00", text)
        # per-feature share of period tokens
        self.assertIn("100%", text)


if __name__ == "__main__":
    unittest.main()
