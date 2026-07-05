from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Row

from app.features.review_tasks.models import ReviewTask


@dataclass(frozen=True)
class GeneratedQuestion:
    text: str
    options: list[str]
    correct_index: int
    explanation: str
    source_refs: list[str]


@dataclass(frozen=True)
class QuizSession:
    id: str
    task_id: str | None
    topic_id: str
    status: str
    question_count: int
    current_question_no: int
    started_at: datetime
    material_fingerprint: str
    material_snapshot: dict[str, object]
    topic_title: str = ""
    session_type: str = "review"
    generator_provider: str = ""
    generator_model: str = ""
    prompt_version: str = ""
    generated_at: datetime | None = None
    finished_at: datetime | None = None
    score_percent: float | None = None
    correct_count: int | None = None
    total_count: int | None = None


@dataclass(frozen=True)
class QuizQuestion:
    id: str
    session_id: str
    question_no: int
    text: str
    options: list[str]
    correct_index: int
    explanation: str
    source_refs: list[str]


@dataclass(frozen=True)
class QuizAnswer:
    id: str
    session_id: str
    question_id: str
    selected_index: int
    is_correct: bool
    answered_at: datetime


@dataclass(frozen=True)
class StartQuizResult:
    session: QuizSession
    question: QuizQuestion
    created: bool


@dataclass(frozen=True)
class AnswerQuizResult:
    session: QuizSession
    question: QuizQuestion
    answer: QuizAnswer
    next_question: QuizQuestion | None
    finished_task: ReviewTask | None


def quiz_session_from_row(row: Row) -> QuizSession:
    finished = row["finished_at"]
    generated = row["generated_at"]
    return QuizSession(
        id=row["id"],
        task_id=row["task_id"],
        topic_id=row["topic_id"],
        topic_title=row["topic_title"] if "topic_title" in row.keys() else "",
        session_type=row["session_type"] if "session_type" in row.keys() else "review",
        status=row["status"],
        question_count=int(row["question_count"]),
        current_question_no=int(row["current_question_no"]),
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=datetime.fromisoformat(finished) if finished else None,
        material_fingerprint=row["material_fingerprint"],
        material_snapshot=json.loads(row["material_snapshot_json"] or "{}"),
        generator_provider=row["generator_provider"],
        generator_model=row["generator_model"],
        prompt_version=row["prompt_version"],
        generated_at=datetime.fromisoformat(generated) if generated else None,
        score_percent=row["score_percent"],
        correct_count=row["correct_count"],
        total_count=row["total_count"],
    )


def quiz_question_from_row(row: Row) -> QuizQuestion:
    return QuizQuestion(
        id=row["id"],
        session_id=row["session_id"],
        question_no=int(row["question_no"]),
        text=row["text"],
        options=json.loads(row["options_json"] or "[]"),
        correct_index=int(row["correct_index"]),
        explanation=row["explanation"],
        source_refs=json.loads(row["source_refs_json"] or "[]"),
    )


def quiz_answer_from_row(row: Row) -> QuizAnswer:
    return QuizAnswer(
        id=row["id"],
        session_id=row["session_id"],
        question_id=row["question_id"],
        selected_index=int(row["selected_index"]),
        is_correct=bool(row["is_correct"]),
        answered_at=datetime.fromisoformat(row["answered_at"]),
    )
