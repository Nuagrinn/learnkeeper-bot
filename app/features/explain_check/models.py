from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Row
from typing import Any


@dataclass(frozen=True)
class ExplanationCheck:
    id: str
    topic_id: str
    topic_title: str
    section: str
    source: str
    explanation_text: str
    status: str
    priority: str
    layer_reached: int
    summary: str
    covered_concepts: list[str]
    missing_concepts: list[str]
    false_models: list[dict[str, str]]
    follow_up_question: str
    material_fingerprint: str
    agent_provider: str
    agent_model: str
    prompt_version: str
    created_at: datetime
    updated_at: datetime
    done_at: datetime | None = None
    deleted_at: datetime | None = None
    linked_review_task_id: str = ""


def explanation_check_from_row(row: Row) -> ExplanationCheck:
    return ExplanationCheck(
        id=row["id"],
        topic_id=row["topic_id"],
        topic_title=row["topic_title"],
        section=row["section"],
        source=row["source"],
        explanation_text=row["explanation_text"],
        status=row["status"],
        priority=row["priority"],
        layer_reached=int(row["layer_reached"]),
        summary=row["summary"],
        covered_concepts=_json_list(row["covered_concepts_json"]),
        missing_concepts=_json_list(row["missing_concepts_json"]),
        false_models=_json_list(row["false_models_json"]),
        follow_up_question=row["follow_up_question"],
        material_fingerprint=row["material_fingerprint"],
        agent_provider=row["agent_provider"],
        agent_model=row["agent_model"],
        prompt_version=row["prompt_version"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        done_at=datetime.fromisoformat(row["done_at"]) if row["done_at"] else None,
        deleted_at=(
            datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None
        ),
        linked_review_task_id=row["linked_review_task_id"],
    )


def _json_list(value: str) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
