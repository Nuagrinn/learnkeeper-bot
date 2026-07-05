from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Protocol

from app.core.db import Database
from app.features.llm_usage.models import (
    LlmFeatureUsage,
    LlmUsageEvent,
    LlmUsageStats,
    llm_usage_event_from_row,
)


log = logging.getLogger(__name__)
TOKEN_CHARS_ESTIMATE = 4


class LlmUsageRecorder(Protocol):
    def record(
        self,
        *,
        provider: str,
        feature: str,
        model: str = "",
        prompt_version: str = "",
        request_label: str = "",
        input_chars: int = 0,
        output_chars: int = 0,
        duration_ms: int = 0,
        success: bool = True,
        error: str = "",
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> LlmUsageEvent | None:
        ...


class NoopLlmUsageRecorder:
    def record(
        self,
        *,
        provider: str,
        feature: str,
        model: str = "",
        prompt_version: str = "",
        request_label: str = "",
        input_chars: int = 0,
        output_chars: int = 0,
        duration_ms: int = 0,
        success: bool = True,
        error: str = "",
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        return None


@dataclass(frozen=True)
class LlmUsagePriceConfig:
    input_usd_per_1m_tokens: float = 0
    output_usd_per_1m_tokens: float = 0

    @property
    def configured(self) -> bool:
        return self.input_usd_per_1m_tokens > 0 or self.output_usd_per_1m_tokens > 0


@dataclass(frozen=True)
class LlmUsageBudgetConfig:
    rolling_5h_usd: float = 0
    daily_usd: float = 0
    weekly_usd: float = 0
    monthly_usd: float = 0

    @property
    def configured(self) -> bool:
        return any(
            value > 0
            for value in (
                self.rolling_5h_usd,
                self.daily_usd,
                self.weekly_usd,
                self.monthly_usd,
            )
        )


class LlmUsageService:
    def __init__(
        self,
        db: Database,
        *,
        price_config: LlmUsagePriceConfig | None = None,
        budget_config: LlmUsageBudgetConfig | None = None,
    ):
        self.db = db
        self.price_config = price_config or LlmUsagePriceConfig()
        self.budget_config = budget_config or LlmUsageBudgetConfig()

    @property
    def prices_configured(self) -> bool:
        return self.price_config.configured

    @property
    def budgets_configured(self) -> bool:
        return self.budget_config.configured

    def record(
        self,
        *,
        provider: str,
        feature: str,
        model: str = "",
        prompt_version: str = "",
        request_label: str = "",
        input_chars: int = 0,
        output_chars: int = 0,
        duration_ms: int = 0,
        success: bool = True,
        error: str = "",
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> LlmUsageEvent:
        created = (created_at or datetime.now()).replace(microsecond=0)
        input_tokens = _estimate_tokens(input_chars)
        output_tokens = _estimate_tokens(output_chars)
        total_tokens = input_tokens + output_tokens
        estimated_usd = _estimate_usd(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            price_config=self.price_config,
        )
        event = LlmUsageEvent(
            id=uuid.uuid4().hex[:12],
            provider=provider.strip() or "unknown",
            feature=feature.strip() or "unknown",
            model=model.strip(),
            prompt_version=prompt_version.strip(),
            request_label=request_label.strip()[:240],
            usage_source="estimated",
            input_chars=max(0, int(input_chars)),
            output_chars=max(0, int(output_chars)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_usd=estimated_usd,
            duration_ms=max(0, int(duration_ms)),
            success=bool(success),
            error=error.strip()[:1000],
            metadata=_safe_metadata(metadata or {}),
            created_at=created,
        )
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO llm_usage_events (
                    id, provider, feature, model, prompt_version, request_label,
                    usage_source, input_chars, output_chars, input_tokens,
                    output_tokens, total_tokens, estimated_usd, duration_ms,
                    success, error, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.provider,
                    event.feature,
                    event.model,
                    event.prompt_version,
                    event.request_label,
                    event.usage_source,
                    event.input_chars,
                    event.output_chars,
                    event.input_tokens,
                    event.output_tokens,
                    event.total_tokens,
                    event.estimated_usd,
                    event.duration_ms,
                    1 if event.success else 0,
                    event.error,
                    json.dumps(event.metadata, ensure_ascii=False),
                    event.created_at.isoformat(timespec="seconds"),
                ),
            )
        log.info(
            "LLM usage recorded provider=%s feature=%s success=%s input_tokens=%s output_tokens=%s estimated_usd=%.6f duration_ms=%s source=%s",
            event.provider,
            event.feature,
            event.success,
            event.input_tokens,
            event.output_tokens,
            event.estimated_usd,
            event.duration_ms,
            event.usage_source,
        )
        return event

    def recent_events(self, *, limit: int = 20) -> list[LlmUsageEvent]:
        with self.db.session() as conn:
            rows = conn.execute(
                """
                SELECT * FROM llm_usage_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(100, int(limit))),),
            ).fetchall()
        return [llm_usage_event_from_row(row) for row in rows]

    def stats_for_periods(self, *, now: datetime | None = None) -> list[LlmUsageStats]:
        current = (now or datetime.now()).replace(microsecond=0)
        today = datetime.combine(current.date(), time.min)
        return [
            self.stats_since(
                "5 часов",
                current - timedelta(hours=5),
                budget_usd=self.budget_config.rolling_5h_usd,
            ),
            self.stats_since("Сегодня", today, budget_usd=self.budget_config.daily_usd),
            self.stats_since(
                "7 дней",
                current - timedelta(days=7),
                budget_usd=self.budget_config.weekly_usd,
            ),
            self.stats_since(
                "30 дней",
                current - timedelta(days=30),
                budget_usd=self.budget_config.monthly_usd,
            ),
        ]

    def stats_since(
        self,
        label: str,
        since: datetime,
        *,
        budget_usd: float = 0,
    ) -> LlmUsageStats:
        since = since.replace(microsecond=0)
        since_text = since.isoformat(timespec="seconds")
        with self.db.session() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS request_count,
                    COALESCE(SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), 0) AS success_count,
                    COALESCE(SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), 0) AS failure_count,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(estimated_usd), 0) AS estimated_usd,
                    COALESCE(SUM(duration_ms), 0) AS duration_ms
                FROM llm_usage_events
                WHERE created_at >= ?
                """,
                (since_text,),
            ).fetchone()
            feature_rows = conn.execute(
                """
                SELECT
                    feature,
                    COUNT(*) AS request_count,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(estimated_usd), 0) AS estimated_usd
                FROM llm_usage_events
                WHERE created_at >= ?
                GROUP BY feature
                ORDER BY total_tokens DESC, request_count DESC, feature ASC
                LIMIT 5
                """,
                (since_text,),
            ).fetchall()
        estimated_usd = float(totals["estimated_usd"] or 0)
        safe_budget = max(0, float(budget_usd))
        return LlmUsageStats(
            label=label,
            since=since,
            request_count=int(totals["request_count"] or 0),
            success_count=int(totals["success_count"] or 0),
            failure_count=int(totals["failure_count"] or 0),
            input_tokens=int(totals["input_tokens"] or 0),
            output_tokens=int(totals["output_tokens"] or 0),
            total_tokens=int(totals["total_tokens"] or 0),
            estimated_usd=estimated_usd,
            duration_ms=int(totals["duration_ms"] or 0),
            budget_usd=safe_budget,
            budget_percent=_budget_percent(estimated_usd, safe_budget),
            features=[
                LlmFeatureUsage(
                    feature=row["feature"],
                    request_count=int(row["request_count"] or 0),
                    input_tokens=int(row["input_tokens"] or 0),
                    output_tokens=int(row["output_tokens"] or 0),
                    total_tokens=int(row["total_tokens"] or 0),
                    estimated_usd=float(row["estimated_usd"] or 0),
                )
                for row in feature_rows
            ],
        )


def _estimate_tokens(chars: int) -> int:
    safe_chars = max(0, int(chars))
    if safe_chars == 0:
        return 0
    return max(1, math.ceil(safe_chars / TOKEN_CHARS_ESTIMATE))


def _estimate_usd(
    *,
    input_tokens: int,
    output_tokens: int,
    price_config: LlmUsagePriceConfig,
) -> float:
    return round(
        (input_tokens / 1_000_000) * price_config.input_usd_per_1m_tokens
        + (output_tokens / 1_000_000) * price_config.output_usd_per_1m_tokens,
        6,
    )


def _budget_percent(value_usd: float, budget_usd: float) -> float:
    if budget_usd <= 0:
        return 0
    return round((max(0, value_usd) / budget_usd) * 100, 2)


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        clean_key = str(key)[:80]
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[clean_key] = value
        elif isinstance(value, list):
            safe[clean_key] = [
                item if isinstance(item, (str, int, float, bool)) or item is None else str(item)
                for item in value[:20]
            ]
        else:
            safe[clean_key] = str(value)
    return safe
