from __future__ import annotations

import html
import re
from datetime import datetime

from app.core.repo import RepoTopic
from app.features.explain_check.models import ExplanationCheck
from app.features.llm_usage.models import LlmUsageStats
from app.features.mistake_work.agent import MistakeReviewResult
from app.features.mistake_work.models import MistakeWorkItem
from app.features.open_questions.models import OpenQuestion, OpenQuestionAttempt
from app.features.quiz.models import QuizAnswer, QuizQuestion, QuizSession
from app.features.review_tasks.models import ReviewTask
from app.features.review_tasks.service import TopicNotReadyError
from app.features.topic_inbox.models import TopicInboxItem


MAX_MESSAGE_LEN = 3900
ANSWER_LABELS = ["A", "B", "C", "D"]


def format_topic(topic: RepoTopic) -> str:
    lines = [
        f"<b>{_h(topic.id)}</b> · <b>{_h(topic.title)}</b>",
        f"Статус: {_h(_status_label(topic.status))}",
    ]
    if topic.section:
        lines.append(f"Блок: {_h(topic.section)}")
    return "\n".join(lines)


def format_topics(topics: list[RepoTopic]) -> str:
    if not topics:
        return "Темы не найдены."
    header = "\n".join([f"<b>Темы</b>", f"Найдено: {len(topics)}"])
    groups: dict[str, list[RepoTopic]] = {}
    for topic in topics:
        section = topic.section or "Без блока"
        groups.setdefault(section, []).append(topic)

    sections: list[str] = []
    for section, items in groups.items():
        lines = [f"<b>{_h(section)}</b>"]
        lines.extend(_format_topic_row(topic) for topic in items)
        sections.append("\n".join(lines))
    body = "\n\n".join(sections)
    return f"{header}\n\n{body}"


def _format_topic_row(topic: RepoTopic) -> str:
    return (
        f"<code>{_h(topic.id)}</code> · "
        f"{_h(_status_icon(topic.status))} "
        f"{_h(topic.title)}"
    )


def format_task(task: ReviewTask, *, include_id: bool = True) -> str:
    lines = [
        f"<b>{_h(task.topic_title)}</b>",
        f"<b>Дата:</b> <code>{_date_label(task.due_at)}</code>",
        f"Этап: {task.stage}/3 · Статус: {_h(_status_label(task.status))}",
    ]
    if include_id:
        lines.append(f"ID: <code>{_h(task.id)}</code>")
    return "\n".join(lines)


def format_tasks(
    tasks: list[ReviewTask],
    *,
    empty_text: str,
    title: str = "Задачи на повторение",
) -> str:
    if not tasks:
        return empty_text
    lines = [f"<b>{_h(title)}</b>", f"Всего: {len(tasks)}", ""]
    for index, task in enumerate(tasks, start=1):
        lines.append(f"<b>{index}.</b> {format_task(task, include_id=False)}")
        lines.append("")
    return "\n".join(lines).strip()


def format_review_created(task: ReviewTask, *, created: bool, source_paths: list[str]) -> str:
    action = (
        "Задача успешно создана"
        if created
        else "Задача не создана: такая активная задача уже есть"
    )
    return "\n".join([f"<b>{_h(action)}</b>", "", format_task(task)])


def format_review_creation_started(query: str) -> str:
    return "\n".join(
        [
            "<b>Принял команду на создание задачи</b>",
            "",
            f"<b>Тема:</b> <code>{_h(query)}</code>",
            "Добавляю задачу, это может занять немного времени.",
        ]
    )


def format_topic_not_ready(error: TopicNotReadyError) -> str:
    lines = [
        "<b>Не могу поставить повторение</b>",
        "",
        _h(error.reason),
    ]
    if error.suggestions:
        lines.extend(["", "<b>Темы с готовыми материалами</b>"])
        lines.extend(f"- {_h(item)}" for item in error.suggestions)
    lines.extend(
        [
            "",
            "Попробуй указать точнее название или id темы.",
            "Например: <code>/review_add cr01</code>.",
        ]
    )
    return "\n".join(lines)


def format_due_notification(task: ReviewTask) -> str:
    return (
        "<b>Пора повторить тему</b>\n\n"
        f"<b>{_h(task.topic_title)}</b>\n"
        f"Этап: {task.stage}/3\n"
        f"<b>Плановая дата:</b> <code>{_date_label(task.due_at)}</code>"
    )


def format_cancel_review_list(tasks: list[ReviewTask]) -> str:
    if not tasks:
        return (
            "<b>Удалить повтор</b>\n\n"
            "Активных отложенных задач сейчас нет."
        )
    return "\n".join(
        [
            "<b>Удалить повтор</b>",
            "",
            "Выбери задачу, которую нужно отменить.",
            "История прохождений и статистика останутся на месте.",
        ]
    )


def format_cancel_review_confirm(task: ReviewTask) -> str:
    return "\n".join(
        [
            "<b>Отменить отложенный повтор?</b>",
            "",
            f"<b>{_h(task.topic_title)}</b>",
            f"<b>Дата:</b> <code>{_date_label(task.due_at)}</code>",
            f"Этап: {task.stage}/3",
            "",
            "Задача будет помечена как отмененная. История не удалится.",
        ]
    )


def format_cancel_review_done(task: ReviewTask) -> str:
    return "\n".join(
        [
            "<b>Повтор отменен</b>",
            "",
            f"<b>{_h(task.topic_title)}</b>",
            f"<b>Дата была:</b> <code>{_date_label(task.due_at)}</code>",
            "",
            "Задача помечена как отмененная, история сохранена.",
        ]
    )


def format_study_topic_prompt() -> str:
    return "\n".join(
        [
            "<b>Какую идею сохранить в inbox?</b>",
            "",
            "Напиши мысль следующим сообщением, либо отправь голосовое.",
            "Например: <code>изучить rate limiter как паттерн отказоустойчивости</code>.",
            "",
            "Это может быть тема для изучения, книга, фича, заметка или задача. "
            "Я аккуратно сформулирую ее через агента и сохраню в SQLite.",
        ]
    )


def format_topic_inbox_created(item: TopicInboxItem) -> str:
    lines = [
        "<b>Идея сохранена</b>",
        "",
        f"<b>Идея:</b> {_h(item.title)}",
    ]
    if item.section:
        lines.append(f"<b>Категория:</b> {_h(item.section)}")
    lines.extend(
        [
            f"<b>ID:</b> <code>{_h(item.id)}</code>",
            "",
            "Позже можешь открыть список через кнопку <b>Список идей</b> и вручную решить, что с этим сделать.",
        ]
    )
    return "\n".join(lines)


def format_topic_inbox_list(items: list[TopicInboxItem]) -> str:
    if not items:
        return "<b>Список идей</b>\n\nСписок пуст."
    lines = [
        "<b>Список идей</b>",
        f"Всего: <b>{len(items)}</b>",
        "",
    ]
    for index, item in enumerate(items, start=1):
        lines.append(f"<b>{index}.</b> {_h(item.title)}")
        if item.section:
            lines.append(f"<b>Категория:</b> {_h(item.section)}")
        lines.append(f"ID: <code>{_h(item.id)}</code>")
        lines.append("")
    lines.append("Кнопками ниже можно удалить уже перенесенные или лишние идеи.")
    return "\n".join(lines).strip()


def format_mistake_review_preview(report: MistakeReviewResult) -> str:
    lines = [
        "<b>Разбор ошибок готов</b>",
        "",
        f"<b>{_h(_clip_inline(report.title, 300))}</b>",
        f"<b>Приоритет:</b> {_h(_priority_label(report.priority))}",
    ]
    if report.section:
        lines.append(f"<b>Блок:</b> {_h(report.section)}")
    lines.extend(["", f"<b>Коротко:</b> {_h(_clip_inline(report.summary, 700))}"])
    if report.diagnosis:
        lines.extend(["", "<b>Диагноз</b>", _h(_clip(report.diagnosis, 1200))])
    if report.weak_concepts:
        lines.extend(["", "<b>Что подтянуть</b>"])
        lines.extend(f"- {_h(item)}" for item in report.weak_concepts[:8])
    suggestion = report.material_suggestion
    details = str(suggestion.get("details") or "").strip()
    if details:
        lines.extend(["", "<b>Что потом добавить в lk-prep</b>", _h(_clip(details, 700))])
    if report.questions_to_revisit:
        lines.extend(["", "<b>Вопросы для повторной проверки</b>"])
        for item in report.questions_to_revisit[:5]:
            number = item.get("question_no") or "-"
            missed = str(item.get("missed_point") or "").strip()
            correct = str(item.get("correct_idea") or "").strip()
            practice = str(item.get("practice_prompt") or "").strip()
            lines.append(f"<b>{_h(number)}.</b> {_h(_clip_inline(missed, 400))}")
            if correct:
                lines.append(f"Верная идея: {_h(_clip(correct, 350))}")
            if practice:
                lines.append(f"Практика: <i>{_h(_clip(practice, 250))}</i>")
    lines.extend(
        [
            "",
            "Можно сохранить этот отчет в <b>Работа над ошибками</b>, чтобы потом разобрать его руками.",
        ]
    )
    return "\n".join(lines)


def format_mistake_work_created(item: MistakeWorkItem) -> str:
    return "\n".join(
        [
            "<b>Отчет сохранен</b>",
            "",
            f"<b>{_h(item.title)}</b>",
            f"<b>Тема:</b> {_h(item.topic_title)}",
            f"<b>Приоритет:</b> {_h(_priority_label(item.priority))}",
            f"<b>ID:</b> <code>{_h(item.id)}</code>",
            "",
            "Он лежит в разделе <b>Проработка</b> → <b>Работа над ошибками</b>.",
        ]
    )


def format_mistake_work_list(
    items: list[MistakeWorkItem],
    *,
    status_title: str = "Активные отчеты",
) -> str:
    if not items:
        return f"<b>{_h(status_title)}</b>\n\nСписок пуст."
    lines = [
        f"<b>{_h(status_title)}</b>",
        f"Всего: <b>{len(items)}</b>",
        "",
    ]
    for index, item in enumerate(items, start=1):
        lines.append(f"<b>{index}.</b> {_h(_priority_icon(item.priority))} {_h(item.title)}")
        lines.append(f"<b>Тема:</b> {_h(item.topic_title)}")
        lines.append(f"<b>Создан:</b> <code>{item.created_at:%d-%m-%Y}</code>")
        lines.append(f"ID: <code>{_h(item.id)}</code>")
        lines.append("")
    lines.append("Открой отчет кнопкой ниже, чтобы прочитать, отметить готовым или удалить.")
    return "\n".join(lines).strip()


def format_mistake_work_item(item: MistakeWorkItem) -> str:
    lines = [
        "<b>Работа над ошибками</b>",
        "",
        f"<b>{_h(item.title)}</b>",
        f"<b>Тема:</b> {_h(item.topic_title)}",
        f"<b>Статус:</b> {_h(_mistake_status_label(item.status))}",
        f"<b>Приоритет:</b> {_h(_priority_label(item.priority))}",
    ]
    if item.section:
        lines.append(f"<b>Блок:</b> {_h(item.section)}")
    lines.extend(
        [
            f"<b>Дата:</b> <code>{item.created_at:%d-%m-%Y}</code>",
            f"<b>ID:</b> <code>{_h(item.id)}</code>",
            "",
            f"<b>Коротко:</b> {_h(item.summary)}",
        ]
    )
    if item.diagnosis:
        lines.extend(["", "<b>Диагноз</b>", _h(_clip(item.diagnosis, 1200))])
    if item.weak_concepts:
        lines.extend(["", "<b>Что подтянуть</b>"])
        lines.extend(f"- {_h(concept)}" for concept in item.weak_concepts[:12])
    details = str(item.suggestion.get("details") or "").strip()
    if details:
        lines.extend(["", "<b>Что добавить/усилить в lk-prep</b>", _h(_clip(details, 700))])
    revisit = item.report.get("questions_to_revisit")
    if isinstance(revisit, list) and revisit:
        lines.extend(["", "<b>Вопросы для повторной проверки</b>"])
        for raw in revisit[:8]:
            if not isinstance(raw, dict):
                continue
            number = raw.get("question_no") or "-"
            missed = str(raw.get("missed_point") or "").strip()
            correct = str(raw.get("correct_idea") or "").strip()
            practice = str(raw.get("practice_prompt") or "").strip()
            lines.append(f"<b>{_h(number)}.</b> {_h(_clip_inline(missed, 400))}")
            if correct:
                lines.append(f"Верная идея: {_h(_clip(correct, 350))}")
            if practice:
                lines.append(f"Практика: <i>{_h(_clip(practice, 250))}</i>")
    if item.agent_provider:
        provider = item.agent_provider
        if item.agent_model:
            provider = f"{provider} {item.agent_model}"
        lines.extend(["", f"<b>Agent:</b> <code>{_h(provider)}</code>"])
    return "\n".join(lines)


_LAYER_LABELS = {
    1: "1/4 — узнавание",
    2: "2/4 — воспроизведение",
    3: "3/4 — применение",
    4: "4/4 — перенос",
}


def _layer_label(layer: int) -> str:
    return _LAYER_LABELS.get(layer, f"{layer}/4")


def _explain_check_status_label(status: str) -> str:
    labels = {
        "active": "активно",
        "done": "разобрано",
        "deleted": "удалено",
    }
    return labels.get(status, status)


def _open_question_status_label(status: str) -> str:
    labels = {
        "active": "ждет ответа",
        "answered": "проверен",
        "deleted": "удален",
    }
    return labels.get(status, status)


def _question_kind_label(kind: str) -> str:
    labels = {
        "mini_case": "мини-кейс",
        "code_review": "code review",
        "design_tradeoff": "design trade-off",
        "debugging": "debugging",
        "oral_interview": "устный вопрос",
    }
    return labels.get(kind, kind or "открытый вопрос")


def format_explain_check_created(item: ExplanationCheck) -> str:
    return "\n".join(
        [
            "<b>Объяснение проверено и сохранено</b>",
            "",
            f"<b>Тема:</b> {_h(item.topic_title)}",
            f"<b>Слой:</b> {_h(_layer_label(item.layer_reached))}",
            f"<b>Приоритет:</b> {_h(_priority_label(item.priority))}",
            f"<b>ID:</b> <code>{_h(item.id)}</code>",
            "",
            "Он лежит в разделе <b>Проработка</b> → <b>Объяснить тему</b> → <b>Мои объяснения</b>.",
        ]
    )


def format_explain_check_list(
    items: list[ExplanationCheck],
    *,
    status_title: str = "Мои объяснения",
) -> str:
    if not items:
        return f"<b>{_h(status_title)}</b>\n\nСписок пуст."
    lines = [
        f"<b>{_h(status_title)}</b>",
        f"Всего: <b>{len(items)}</b>",
        "",
    ]
    for index, item in enumerate(items, start=1):
        lines.append(f"<b>{index}.</b> {_h(_priority_icon(item.priority))} {_h(item.topic_title)}")
        lines.append(f"<b>Блок:</b> {_h(item.section) or '-'} · <b>Слой:</b> {_h(_layer_label(item.layer_reached))}")
        lines.append(f"<b>Создано:</b> <code>{item.created_at:%d-%m-%Y}</code>")
        lines.append(f"ID: <code>{_h(item.id)}</code>")
        lines.append("")
    lines.append("Открой запись кнопкой ниже, чтобы прочитать разбор, отметить разобранной или удалить.")
    return "\n".join(lines).strip()


def format_explain_check_report(item: ExplanationCheck) -> str:
    lines = [
        "<b>Проверка объяснения</b>",
        "",
        f"<b>Тема:</b> {_h(item.topic_title)}",
        f"<b>Статус:</b> {_h(_explain_check_status_label(item.status))}",
        f"<b>Слой понимания:</b> {_h(_layer_label(item.layer_reached))}",
        f"<b>Приоритет:</b> {_h(_priority_label(item.priority))}",
    ]
    if item.section:
        lines.append(f"<b>Блок:</b> {_h(item.section)}")
    if item.linked_review_task_id:
        lines.append("<b>Контекст:</b> перед плановым повтором")
    lines.extend(
        [
            f"<b>Дата:</b> <code>{item.created_at:%d-%m-%Y}</code>",
            f"<b>ID:</b> <code>{_h(item.id)}</code>",
            "",
            f"<b>Коротко:</b> {_h(_clip_inline(item.summary, 400))}",
        ]
    )
    if item.covered_concepts:
        lines.extend(["", "<b>Что точно объяснил</b>"])
        lines.extend(f"- {_h(concept)}" for concept in item.covered_concepts[:8])
    if item.missing_concepts:
        lines.extend(["", "<b>Что упустил</b>"])
        lines.extend(f"- {_h(concept)}" for concept in item.missing_concepts[:8])
    if item.false_models:
        lines.extend(["", "<b>Ложные модели → верные модели</b>"])
        for pair in item.false_models[:6]:
            false_model = str(pair.get("false_model") or "").strip()
            correct_model = str(pair.get("correct_model") or "").strip()
            if not false_model:
                continue
            lines.append(f"- ❌ {_h(_clip_inline(false_model, 200))}")
            if correct_model:
                lines.append(f"  ✅ {_h(_clip_inline(correct_model, 200))}")
    if item.follow_up_question:
        lines.extend(["", "<b>Вопрос на подумать</b>", _h(_clip_inline(item.follow_up_question, 300))])
    lines.extend(["", "<b>Твое объяснение</b>", _h(_clip(item.explanation_text, 1200))])
    if item.agent_provider:
        provider = item.agent_provider
        if item.agent_model:
            provider = f"{provider} {item.agent_model}"
        lines.extend(["", f"<b>Agent:</b> <code>{_h(provider)}</code>"])
    return "\n".join(lines)


def format_open_question_prompt(item: OpenQuestion) -> str:
    lines = [
        "<b>Открытый вопрос</b>",
        "",
        f"<b>Тема:</b> {_h(item.topic_title)}",
    ]
    if item.section:
        lines.append(f"<b>Блок:</b> {_h(item.section)}")
    lines.extend(
        [
            f"<b>Формат:</b> {_h(_question_kind_label(item.question_kind))}",
            "",
            _h(_clip(item.question_text, 1800)),
        ]
    )
    if item.answer_format_hint:
        lines.extend(["", f"<i>{_h(_clip_inline(item.answer_format_hint, 400))}</i>"])
    lines.extend(
        [
            "",
            "Ответь следующим сообщением текстом или голосом. Я проверю по рубрике.",
        ]
    )
    return "\n".join(lines)


def format_open_question_check_report(
    question: OpenQuestion,
    attempt: OpenQuestionAttempt,
) -> str:
    lines = [
        "<b>Открытый вопрос проверен</b>",
        "",
        f"<b>Тема:</b> {_h(question.topic_title)}",
        f"<b>Оценка:</b> <code>{attempt.score_percent:.0f}%</code>",
        f"<b>Слой:</b> {_h(_layer_label(attempt.layer_reached))}",
        f"<b>Коротко:</b> {_h(_clip_inline(attempt.summary, 500))}",
    ]
    if attempt.strong_points:
        lines.extend(["", "<b>Что получилось</b>"])
        lines.extend(f"- {_h(item)}" for item in attempt.strong_points[:8])
    if attempt.missing_points:
        lines.extend(["", "<b>Что упущено</b>"])
        lines.extend(f"- {_h(item)}" for item in attempt.missing_points[:8])
    if attempt.false_models:
        lines.extend(["", "<b>Ложные модели → верные модели</b>"])
        for pair in attempt.false_models[:6]:
            false_model = str(pair.get("false_model") or "").strip()
            correct_model = str(pair.get("correct_model") or "").strip()
            if not false_model:
                continue
            lines.append(f"- ❌ {_h(_clip_inline(false_model, 220))}")
            if correct_model:
                lines.append(f"  ✅ {_h(_clip_inline(correct_model, 220))}")
    if attempt.better_answer:
        lines.extend(["", "<b>Как мог бы звучать сильный ответ</b>", _h(_clip(attempt.better_answer, 1400))])
    if attempt.next_drill:
        lines.extend(["", "<b>Следующая мини-тренировка</b>", _h(_clip_inline(attempt.next_drill, 500))])
    lines.extend(["", "<b>Твой ответ</b>", _h(_clip(attempt.answer_text, 1000))])
    if attempt.checker_provider:
        provider = attempt.checker_provider
        if attempt.checker_model:
            provider = f"{provider} {attempt.checker_model}"
        lines.extend(["", f"<b>Agent:</b> <code>{_h(provider)}</code>"])
    return "\n".join(lines)


def format_open_question_list(
    items: list[OpenQuestion],
    *,
    status_title: str = "Открытые вопросы",
) -> str:
    if not items:
        return f"<b>{_h(status_title)}</b>\n\nСписок пуст."
    lines = [
        f"<b>{_h(status_title)}</b>",
        f"Всего: <b>{len(items)}</b>",
        "",
    ]
    for index, item in enumerate(items, start=1):
        lines.append(f"<b>{index}.</b> {_h(item.topic_title)}")
        lines.append(f"<b>Формат:</b> {_h(_question_kind_label(item.question_kind))}")
        lines.append(f"<b>Статус:</b> {_h(_open_question_status_label(item.status))}")
        lines.append(f"<b>Создан:</b> <code>{item.created_at:%d-%m-%Y}</code>")
        lines.append(f"ID: <code>{_h(item.id)}</code>")
        lines.append("")
    lines.append("Открой вопрос кнопкой ниже, чтобы ответить, прочитать проверку или удалить.")
    return "\n".join(lines).strip()


def format_open_question_item(
    item: OpenQuestion,
    attempt: OpenQuestionAttempt | None = None,
) -> str:
    if attempt:
        return format_open_question_check_report(item, attempt)
    lines = [
        "<b>Открытый вопрос</b>",
        "",
        f"<b>Тема:</b> {_h(item.topic_title)}",
        f"<b>Статус:</b> {_h(_open_question_status_label(item.status))}",
        f"<b>Формат:</b> {_h(_question_kind_label(item.question_kind))}",
    ]
    if item.section:
        lines.append(f"<b>Блок:</b> {_h(item.section)}")
    lines.extend(
        [
            f"<b>Дата:</b> <code>{item.created_at:%d-%m-%Y}</code>",
            f"<b>ID:</b> <code>{_h(item.id)}</code>",
            "",
            _h(_clip(item.question_text, 1800)),
        ]
    )
    if item.answer_format_hint:
        lines.extend(["", f"<i>{_h(_clip_inline(item.answer_format_hint, 400))}</i>"])
    return "\n".join(lines)


def format_llm_usage_report(
    stats: list[LlmUsageStats],
    *,
    prices_configured: bool,
) -> str:
    budgets_configured = any(item.budget_usd > 0 for item in stats)
    lines = [
        "<b>LLM usage</b>",
        "",
        "Локальный учёт запросов к Claude. Значения бюджета ниже — <b>локальные ориентиры</b>, "
        "а не реальные лимиты подписки Anthropic.",
        "<i>Токены включают дешёвые cache-read (~10% цены), поэтому число немного завышает реальный расход.</i>",
    ]
    if not prices_configured:
        lines.extend(
            [
                "",
                "<i>Стоимость не настроена: задай цены в .env, если нужен API-equivalent.</i>",
            ]
        )
    if prices_configured and not budgets_configured:
        lines.extend(
            [
                "",
                "<i>Бюджетные проценты не настроены: задай LLM_USAGE_BUDGET_* в .env.</i>",
            ]
        )

    if not stats or all(item.request_count == 0 for item in stats):
        lines.extend(["", "Запросов к LLM пока не записано."])
        return "\n".join(lines)

    for item in stats:
        lines.extend(
            [
                "",
                f"<b>{_h(item.label)}</b>",
                f"Запросы: <b>{item.request_count}</b> · ошибок: <b>{item.failure_count}</b>",
            ]
        )
        if item.budget_tokens > 0:
            lines.append(
                f"Токены: <code>{_format_int(item.total_tokens)}</code> / "
                f"<code>{_format_int(item.budget_tokens)}</code> "
                f"(<b>{item.token_budget_percent:.1f}%</b>) {_budget_status(item.token_budget_percent)}"
            )
            lines.append(
                f"<i>вход {_format_int(item.input_tokens)} · выход {_format_int(item.output_tokens)}</i>"
            )
        else:
            lines.append(
                "Токены: "
                f"<code>{_format_int(item.total_tokens)}</code> "
                f"(вход <code>{_format_int(item.input_tokens)}</code> / "
                f"выход <code>{_format_int(item.output_tokens)}</code>)"
            )
        if item.budget_usd > 0:
            lines.append(
                f"Стоимость: <code>${_format_usd(item.estimated_usd)}</code> / "
                f"<code>${_format_usd(item.budget_usd)}</code> "
                f"(<b>{item.budget_percent:.1f}%</b>) {_budget_status(item.budget_percent)}"
            )
        elif prices_configured or item.estimated_usd > 0:
            lines.append(
                f"Стоимость: <code>${_format_usd(item.estimated_usd)}</code> (API-эквивалент)"
            )
        lines.append(f"Время: <code>{_format_duration_ms(item.duration_ms)}</code>")
        if item.features and item.total_tokens > 0:
            lines.append("<b>Топ фич</b> (доля токенов периода)")
            for feature in item.features[:3]:
                share = feature.total_tokens / item.total_tokens * 100
                lines.append(
                    f"- {_h(_feature_label(feature.feature))}: "
                    f"<code>{_format_int(feature.total_tokens)}</code> "
                    f"(<b>{share:.0f}%</b>, {feature.request_count} req)"
                )
    return "\n".join(lines)


# NOTE: kept next to format_llm_usage_report so both share the token/usd helpers.
def format_llm_budget_alert(item: LlmUsageStats, level: int) -> str:
    head = (
        "🔴 Локальный ориентир 5ч исчерпан"
        if level >= 100
        else "🟡 Локальный ориентир 5ч почти исчерпан"
    )
    lines = [f"<b>{head}</b>", ""]
    if item.budget_tokens > 0:
        lines.append(
            f"Токены за 5ч: <code>{_format_int(item.total_tokens)}</code> / "
            f"<code>{_format_int(item.budget_tokens)}</code> "
            f"(<b>{item.token_budget_percent:.0f}%</b>)"
        )
    if item.budget_usd > 0:
        lines.append(
            f"Стоимость (API-экв.): <code>${_format_usd(item.estimated_usd)}</code> / "
            f"<code>${_format_usd(item.budget_usd)}</code> "
            f"(<b>{item.budget_percent:.0f}%</b>)"
        )
    lines.extend(
        [
            "",
            "<i>Это локальный ориентир бота, а не реальный лимит Anthropic. "
            "Если тестов много подряд — возможно, стоит сделать паузу.</i>",
        ]
    )
    return "\n".join(lines)


def format_quiz_question(session: QuizSession, question: QuizQuestion) -> str:
    lines = [
        f"<b>Вопрос {question.question_no}/{session.question_count}</b>",
        "",
        _rich(question.text),
        "",
    ]
    lines.extend(
        f"<b>{ANSWER_LABELS[index]}.</b> {_rich(option)}"
        for index, option in enumerate(question.options)
    )
    return "\n".join(lines)


def format_quiz_report(
    session: QuizSession,
    questions: list[QuizQuestion],
    answers: list[QuizAnswer],
    task: ReviewTask,
) -> str:
    answer_by_question = {answer.question_id: answer for answer in answers}
    score = session.score_percent if session.score_percent is not None else 0
    correct = session.correct_count if session.correct_count is not None else 0
    total = session.total_count if session.total_count is not None else len(questions)
    completed_stage = _completed_stage(task, score)
    lines = [
        "<b>Тест завершен</b>",
        "",
        f"<b>Тема:</b> {_h(task.topic_title)}",
        f"<b>Этап:</b> завершен этап {completed_stage} из 3",
        f"<b>Результат:</b> {score:.0f}% ({correct}/{total})",
        "",
        _format_next_review(task, score),
    ]

    mistakes = [
        question
        for question in questions
        if not answer_by_question.get(question.id)
        or not answer_by_question[question.id].is_correct
    ]
    if mistakes:
        lines.extend(["", "<b>Что разобрать</b>"])
        for question in mistakes[:10]:
            answer = answer_by_question.get(question.id)
            selected = (
                ANSWER_LABELS[answer.selected_index]
                if answer and 0 <= answer.selected_index < len(ANSWER_LABELS)
                else "-"
            )
            selected_text = (
                question.options[answer.selected_index]
                if answer and 0 <= answer.selected_index < len(question.options)
                else "нет ответа"
            )
            correct_label = ANSWER_LABELS[question.correct_index]
            correct_text = question.options[question.correct_index]
            lines.extend(
                [
                    "",
                    f"<b>Вопрос {question.question_no}</b>",
                    _rich(question.text),
                    f"<b>Твой ответ:</b> {selected}. {_rich(selected_text)}",
                    f"<b>Правильно:</b> {correct_label}. {_rich(correct_text)}",
                    f"<i>{_rich_inline(question.explanation)}</i>",
                ]
            )
            if question.source_refs:
                refs = ", ".join(_h(ref) for ref in question.source_refs)
                lines.append(f"<b>Материалы:</b> {refs}")
    else:
        lines.extend(["", "<b>Ошибок нет.</b>", "Отличный проход, двигаемся дальше."])

    return "\n".join(lines)


def format_instant_quiz_report(
    session: QuizSession,
    questions: list[QuizQuestion],
    answers: list[QuizAnswer],
) -> str:
    answer_by_question = {answer.question_id: answer for answer in answers}
    score = session.score_percent if session.score_percent is not None else 0
    correct = session.correct_count if session.correct_count is not None else 0
    total = session.total_count if session.total_count is not None else len(questions)
    title = session.topic_title or str(session.material_snapshot.get("topic_title") or session.topic_id)
    lines = [
        "<b>Моментальный тест завершен</b>",
        "",
        f"<b>Тема:</b> {_h(title)}",
        f"<b>Результат:</b> {score:.0f}% ({correct}/{total})",
        "",
        "<b>Расписание:</b> не изменялось. Это была тренировка вне цепочки повторений.",
    ]

    mistakes = [
        question
        for question in questions
        if not answer_by_question.get(question.id)
        or not answer_by_question[question.id].is_correct
    ]
    if mistakes:
        lines.extend(["", "<b>Что разобрать</b>"])
        for question in mistakes[:10]:
            answer = answer_by_question.get(question.id)
            selected = (
                ANSWER_LABELS[answer.selected_index]
                if answer and 0 <= answer.selected_index < len(ANSWER_LABELS)
                else "-"
            )
            selected_text = (
                question.options[answer.selected_index]
                if answer and 0 <= answer.selected_index < len(question.options)
                else "нет ответа"
            )
            correct_label = ANSWER_LABELS[question.correct_index]
            correct_text = question.options[question.correct_index]
            lines.extend(
                [
                    "",
                    f"<b>Вопрос {question.question_no}</b>",
                    _rich(question.text),
                    f"<b>Твой ответ:</b> {selected}. {_rich(selected_text)}",
                    f"<b>Правильно:</b> {correct_label}. {_rich(correct_text)}",
                    f"<i>{_rich_inline(question.explanation)}</i>",
                ]
            )
            if question.source_refs:
                refs = ", ".join(_h(ref) for ref in question.source_refs)
                lines.append(f"<b>Материалы:</b> {refs}")
    else:
        lines.extend(["", "<b>Ошибок нет.</b>", "Хорошая тренировка, можно двигаться дальше."])

    return "\n".join(lines)


def _format_next_review(task: ReviewTask, score: float) -> str:
    if task.status == "completed":
        return "<b>Следующий шаг:</b> цепочка повторения по этой задаче завершена."

    if score >= 80:
        reason = "Этап засчитан, переходим к следующему интервалу."
    elif score >= 60:
        reason = "Этап оставлен на закрепление: повторим его через короткий интервал."
    else:
        reason = "Этап нужно повторить: вернемся к нему быстрее."

    return "\n".join(
        [
            f"<b>Следующий повтор:</b> через {_format_interval(task.interval_days)}, "
            f"<code>{_date_label(task.due_at)}</code>.",
            reason,
        ]
    )


def _completed_stage(task: ReviewTask, score: float) -> int:
    if score >= 80 and task.status != "completed" and task.stage > 1:
        return task.stage - 1
    return task.stage


def _format_interval(days: int) -> str:
    if days <= 0:
        return "сейчас"
    if days % 30 == 0:
        months = days // 30
        return f"{days} {_plural_ru(days, 'день', 'дня', 'дней')} ({months} {_plural_ru(months, 'месяц', 'месяца', 'месяцев')})"
    if days % 7 == 0:
        weeks = days // 7
        return f"{days} {_plural_ru(days, 'день', 'дня', 'дней')} ({weeks} {_plural_ru(weeks, 'неделя', 'недели', 'недель')})"
    return f"{days} {_plural_ru(days, 'день', 'дня', 'дней')}"


def _plural_ru(value: int, one: str, few: str, many: str) -> str:
    abs_value = abs(value)
    if 11 <= abs_value % 100 <= 14:
        return many
    last = abs_value % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def _date_label(value: datetime) -> str:
    return value.strftime("%d-%m-%Y")


def _priority_label(priority: str) -> str:
    labels = {
        "high": "🔴 высокая",
        "normal": "🟡 обычная",
        "low": "🟢 низкая",
    }
    return labels.get(priority, "🟡 обычная")


def _priority_icon(priority: str) -> str:
    icons = {
        "high": "🔴",
        "normal": "🟡",
        "low": "🟢",
    }
    return icons.get(priority, "🟡")


def _mistake_status_label(status: str) -> str:
    labels = {
        "active": "активен",
        "done": "проработан",
        "deleted": "удален",
    }
    return labels.get(status, status)


def _h(value: object) -> str:
    return html.escape(str(value), quote=False)


_CODE_FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+#.-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


def _rich(value: object) -> str:
    """Render LLM text with Markdown code into Telegram HTML.

    Messages are sent with parse_mode=HTML, so backticks are not special: without
    this a model-written ```go ... ``` fence shows up verbatim. Fenced blocks
    become <pre>, inline `code` becomes <code>, everything else is HTML-escaped.
    """
    text = str(value)
    if not text:
        return ""
    parts: list[str] = []
    idx = 0
    for match in _CODE_FENCE_RE.finditer(text):
        parts.append(_rich_inline(text[idx:match.start()]))
        lang = match.group(1).strip().lower()
        code = _h(match.group(2).rstrip("\n"))
        if lang:
            parts.append(f'<pre><code class="language-{_h(lang)}">{code}</code></pre>')
        else:
            parts.append(f"<pre>{code}</pre>")
        idx = match.end()
    parts.append(_rich_inline(text[idx:]))
    return "".join(parts)


def _rich_inline(segment: str) -> str:
    """Escape text and turn inline `code` spans into <code> (no block tags).

    Safe to nest inside other inline tags like <i>, unlike the block <pre> that
    full _rich() can emit.
    """
    parts: list[str] = []
    idx = 0
    for match in _INLINE_CODE_RE.finditer(segment):
        parts.append(_h(segment[idx:match.start()]))
        parts.append(f"<code>{_h(match.group(1))}</code>")
        idx = match.end()
    parts.append(_h(segment[idx:]))
    return "".join(parts)


def _clip(value: str, limit: int) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n..."


def _clip_inline(value: str, limit: int) -> str:
    """Like _clip but keeps the result on one line (no injected newline)."""
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _status_label(status: str) -> str:
    labels = {
        "ready": "✅ готово",
        "planned": "🕓 в плане",
        "learning": "📖 изучается",
        "active": "🟢 активна",
        "completed": "✅ завершена",
        "cancelled": "⚪ отменена",
        "unknown": "❔ неизвестно",
    }
    return labels.get(status, status or "неизвестно")


def _status_icon(status: str) -> str:
    icons = {
        "ready": "✅",
        "planned": "🕓",
        "learning": "📖",
        "active": "🟢",
        "completed": "✅",
        "cancelled": "⚪",
        "unknown": "❔",
    }
    return icons.get(status, "❔")


def _feature_label(value: str) -> str:
    labels = {
        "quiz_generation": "генерация тестов",
        "topic_inbox_normalize": "идеи тем",
        "mistake_review_analysis": "разбор ошибок",
        "explain_check_analysis": "проверка объяснений",
    }
    return labels.get(value, value or "unknown")


def _format_int(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def _format_usd(value: float) -> str:
    if value < 0.01:
        return f"{value:.6f}"
    return f"{value:.2f}"


def _format_duration_ms(value: int) -> str:
    seconds = max(0, int(round(value / 1000)))
    if seconds < 60:
        return f"{seconds} с"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} мин {rest} с"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} ч {minutes} мин"


def _budget_status(percent: float) -> str:
    if percent >= 100:
        return "🔴"
    if percent >= 80:
        return "🟠"
    if percent >= 50:
        return "🟡"
    return "🟢"


def split_message(text: str, *, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        projected = current_len + len(line) + 1
        if current and projected > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line) + 1
        else:
            current.append(line)
            current_len = projected
    if current:
        chunks.append("\n".join(current))
    return chunks


def now_label(now: datetime | None = None) -> str:
    value = now or datetime.now()
    return value.strftime("%Y-%m-%d %H:%M")
