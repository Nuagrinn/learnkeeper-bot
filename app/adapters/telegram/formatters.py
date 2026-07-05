from __future__ import annotations

import html
from datetime import datetime

from app.core.repo import RepoTopic
from app.features.llm_usage.models import LlmUsageStats
from app.features.mistake_work.agent import MistakeReviewResult
from app.features.mistake_work.models import MistakeWorkItem
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
            "<b>Какую тему сохранить в inbox?</b>",
            "",
            "Напиши название следующим сообщением, либо отправь голосовое.",
            "Например: <code>System Design: Transactional Outbox</code>.",
            "",
            "Я сформулирую ее через агента и сохраню в SQLite. "
            "interview-review менять не буду.",
        ]
    )


def format_topic_inbox_created(item: TopicInboxItem) -> str:
    lines = [
        "<b>Идея темы сохранена</b>",
        "",
        f"<b>Тема:</b> {_h(item.title)}",
    ]
    if item.section:
        lines.append(f"<b>Блок:</b> {_h(item.section)}")
    lines.extend(
        [
            f"<b>ID:</b> <code>{_h(item.id)}</code>",
            "",
            "Позже можешь открыть список через кнопку <b>Идеи тем</b> и перенести это в interview-review руками.",
        ]
    )
    return "\n".join(lines)


def format_topic_inbox_list(items: list[TopicInboxItem]) -> str:
    if not items:
        return "<b>Идеи тем</b>\n\nСписок пуст."
    lines = [
        "<b>Идеи тем</b>",
        f"Всего: <b>{len(items)}</b>",
        "",
    ]
    for index, item in enumerate(items, start=1):
        lines.append(f"<b>{index}.</b> {_h(item.title)}")
        if item.section:
            lines.append(f"<b>Блок:</b> {_h(item.section)}")
        lines.append(f"ID: <code>{_h(item.id)}</code>")
        lines.append("")
    lines.append("Кнопками ниже можно удалить уже перенесенные или лишние идеи.")
    return "\n".join(lines).strip()


def format_mistake_review_preview(report: MistakeReviewResult) -> str:
    lines = [
        "<b>Разбор ошибок готов</b>",
        "",
        f"<b>{_h(report.title)}</b>",
        f"<b>Приоритет:</b> {_h(_priority_label(report.priority))}",
    ]
    if report.section:
        lines.append(f"<b>Блок:</b> {_h(report.section)}")
    lines.extend(["", f"<b>Коротко:</b> {_h(report.summary)}"])
    if report.diagnosis:
        lines.extend(["", "<b>Диагноз</b>", _h(_clip(report.diagnosis, 1200))])
    if report.weak_concepts:
        lines.extend(["", "<b>Что подтянуть</b>"])
        lines.extend(f"- {_h(item)}" for item in report.weak_concepts[:8])
    suggestion = report.interview_review_suggestion
    details = str(suggestion.get("details") or "").strip()
    if details:
        lines.extend(["", "<b>Что потом добавить в interview-review</b>", _h(_clip(details, 700))])
    if report.questions_to_revisit:
        lines.extend(["", "<b>Вопросы для повторной проверки</b>"])
        for item in report.questions_to_revisit[:5]:
            number = item.get("question_no") or "-"
            missed = str(item.get("missed_point") or "").strip()
            correct = str(item.get("correct_idea") or "").strip()
            practice = str(item.get("practice_prompt") or "").strip()
            lines.append(f"<b>{_h(number)}.</b> {_h(missed)}")
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
        lines.extend(["", "<b>Что добавить/усилить в interview-review</b>", _h(_clip(details, 700))])
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
            lines.append(f"<b>{_h(number)}.</b> {_h(missed)}")
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


def format_llm_usage_report(
    stats: list[LlmUsageStats],
    *,
    prices_configured: bool,
) -> str:
    budgets_configured = any(item.budget_usd > 0 for item in stats)
    lines = [
        "<b>LLM usage</b>",
        "",
        "Локальный учет запросов к Claude/агентам.",
        "Токены сейчас считаются оценочно по размеру входа и выхода.",
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
                (
                    "Токены: "
                    f"<code>{_format_int(item.total_tokens)}</code> "
                    f"(in <code>{_format_int(item.input_tokens)}</code> / "
                    f"out <code>{_format_int(item.output_tokens)}</code>)"
                ),
                f"Время ожидания: <code>{_format_duration_ms(item.duration_ms)}</code>",
            ]
        )
        if prices_configured:
            lines.append(
                f"API-equivalent: <code>${_format_usd(item.estimated_usd)}</code>"
            )
        if item.budget_usd > 0:
            lines.append(
                f"Ориентир: {_budget_status(item.budget_percent)} "
                f"<code>{item.budget_percent:.2f}%</code> "
                f"от <code>${_format_usd(item.budget_usd)}</code>"
            )
        if item.features:
            lines.append("<b>Топ фич</b>")
            for feature in item.features[:3]:
                lines.append(
                    f"- {_h(_feature_label(feature.feature))}: "
                    f"<code>{_format_int(feature.total_tokens)}</code> токенов "
                    f"({feature.request_count} req)"
                )
    return "\n".join(lines)


def format_quiz_question(session: QuizSession, question: QuizQuestion) -> str:
    lines = [
        f"<b>Вопрос {question.question_no}/{session.question_count}</b>",
        "",
        _h(question.text),
        "",
    ]
    lines.extend(
        f"<b>{ANSWER_LABELS[index]}.</b> {_h(option)}"
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
                    _h(question.text),
                    f"<b>Твой ответ:</b> {selected}. {_h(selected_text)}",
                    f"<b>Правильно:</b> {correct_label}. {_h(correct_text)}",
                    f"<i>{_h(question.explanation)}</i>",
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
                    _h(question.text),
                    f"<b>Твой ответ:</b> {selected}. {_h(selected_text)}",
                    f"<b>Правильно:</b> {correct_label}. {_h(correct_text)}",
                    f"<i>{_h(question.explanation)}</i>",
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


def _clip(value: str, limit: int) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n..."


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

