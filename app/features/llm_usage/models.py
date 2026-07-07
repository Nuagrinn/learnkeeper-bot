from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from sqlite3 import Row
from typing import Any


@dataclass(frozen=True)
class LlmUsageEvent:
    id: str
    provider: str
    feature: str
    model: str
    prompt_version: str
    request_label: str
    usage_source: str
    input_chars: int
    output_chars: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_usd: float
    duration_ms: int
    success: bool
    error: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class LlmFeatureUsage:
    feature: str
    request_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_usd: float


@dataclass(frozen=True)
class LlmUsageStats:
    label: str
    since: datetime
    request_count: int
    success_count: int
    failure_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_usd: float
    duration_ms: int
    budget_usd: float = 0
    budget_percent: float = 0
    budget_tokens: int = 0
    token_budget_percent: float = 0
    features: list[LlmFeatureUsage] = field(default_factory=list)


def llm_usage_event_from_row(row: Row) -> LlmUsageEvent:
    metadata_raw = row["metadata_json"] or "{}"
    try:
        metadata = json.loads(metadata_raw)
    except json.JSONDecodeError:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return LlmUsageEvent(
        id=row["id"],
        provider=row["provider"],
        feature=row["feature"],
        model=row["model"],
        prompt_version=row["prompt_version"],
        request_label=row["request_label"],
        usage_source=row["usage_source"],
        input_chars=int(row["input_chars"]),
        output_chars=int(row["output_chars"]),
        input_tokens=int(row["input_tokens"]),
        output_tokens=int(row["output_tokens"]),
        total_tokens=int(row["total_tokens"]),
        estimated_usd=float(row["estimated_usd"]),
        duration_ms=int(row["duration_ms"]),
        success=bool(row["success"]),
        error=row["error"],
        metadata=metadata,
        created_at=datetime.fromisoformat(row["created_at"]),
    )
