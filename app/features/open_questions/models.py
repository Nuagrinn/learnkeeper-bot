from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Row
from typing import Any


@dataclass(frozen=True)
class OpenQuestion:
    id: str
    topic_id: str
    topic_title: str
    section: str
    quiz_session_id: str
    origin: str
    status: str
    question_kind: str
    question_text: str
    answer_format_hint: str
    expected_points: list[str]
    rubric: list[dict[str, Any]]
    source_refs: list[str]
    material_fingerprint: str
    material_snapshot: dict[str, Any]
    generator_provider: str
    generator_model: str
    generate_prompt_version: str
    created_at: datetime
    updated_at: datetime
    answered_at: datetime | None = None
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class OpenQuestionAttempt:
    id: str
    open_question_id: str
    answer_text: str
    answer_source: str
    score_percent: float
    layer_reached: int
    summary: str
    strong_points: list[str]
    missing_points: list[str]
    false_models: list[dict[str, str]]
    better_answer: str
    next_drill: str
    should_create_mistake_work: bool
    checker_provider: str
    checker_model: str
    check_prompt_version: str
    raw_report: dict[str, Any]
    created_at: datetime


def open_question_from_row(row: Row) -> OpenQuestion:
    return OpenQuestion(
        id=row["id"],
        topic_id=row["topic_id"],
        topic_title=row["topic_title"],
        section=row["section"],
        quiz_session_id=row["quiz_session_id"],
        origin=row["origin"],
        status=row["status"],
        question_kind=row["question_kind"],
        question_text=row["question_text"],
        answer_format_hint=row["answer_format_hint"],
        expected_points=_json_list(row["expected_points_json"]),
        rubric=_json_list(row["rubric_json"]),
        source_refs=_json_list(row["source_refs_json"]),
        material_fingerprint=row["material_fingerprint"],
        material_snapshot=_json_dict(row["material_snapshot_json"]),
        generator_provider=row["generator_provider"],
        generator_model=row["generator_model"],
        generate_prompt_version=row["generate_prompt_version"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        answered_at=datetime.fromisoformat(row["answered_at"]) if row["answered_at"] else None,
        deleted_at=datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None,
    )


def open_question_attempt_from_row(row: Row) -> OpenQuestionAttempt:
    return OpenQuestionAttempt(
        id=row["id"],
        open_question_id=row["open_question_id"],
        answer_text=row["answer_text"],
        answer_source=row["answer_source"],
        score_percent=float(row["score_percent"]),
        layer_reached=int(row["layer_reached"]),
        summary=row["summary"],
        strong_points=_json_list(row["strong_points_json"]),
        missing_points=_json_list(row["missing_points_json"]),
        false_models=_json_list(row["false_models_json"]),
        better_answer=row["better_answer"],
        next_drill=row["next_drill"],
        should_create_mistake_work=bool(row["should_create_mistake_work"]),
        checker_provider=row["checker_provider"],
        checker_model=row["checker_model"],
        check_prompt_version=row["check_prompt_version"],
        raw_report=_json_dict(row["raw_report_json"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _json_list(value: str) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
