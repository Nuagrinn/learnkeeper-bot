from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Row
from typing import Any


@dataclass(frozen=True)
class MistakeWorkItem:
    id: str
    quiz_session_id: str
    topic_id: str
    topic_title: str
    session_type: str
    status: str
    priority: str
    title: str
    section: str
    summary: str
    diagnosis: str
    weak_concepts: list[str]
    questions: list[dict[str, Any]]
    suggestion: dict[str, Any]
    report: dict[str, Any]
    agent_provider: str
    agent_model: str
    prompt_version: str
    created_at: datetime
    updated_at: datetime
    done_at: datetime | None = None
    deleted_at: datetime | None = None


def mistake_work_item_from_row(row: Row) -> MistakeWorkItem:
    return MistakeWorkItem(
        id=row["id"],
        quiz_session_id=row["quiz_session_id"],
        topic_id=row["topic_id"],
        topic_title=row["topic_title"],
        session_type=row["session_type"],
        status=row["status"],
        priority=row["priority"],
        title=row["title"],
        section=row["section"],
        summary=row["summary"],
        diagnosis=row["diagnosis"],
        weak_concepts=_json_list(row["weak_concepts_json"]),
        questions=_json_list(row["questions_json"]),
        suggestion=_json_dict(row["suggestion_json"]),
        report=_json_dict(row["report_json"]),
        agent_provider=row["agent_provider"],
        agent_model=row["agent_model"],
        prompt_version=row["prompt_version"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        done_at=datetime.fromisoformat(row["done_at"]) if row["done_at"] else None,
        deleted_at=(
            datetime.fromisoformat(row["deleted_at"])
            if row["deleted_at"]
            else None
        ),
    )


def _json_list(value: str) -> list:
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
