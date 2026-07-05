from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.core.db import Database
from app.features.llm_usage.service import (
    LlmUsageBudgetConfig,
    LlmUsagePriceConfig,
    LlmUsageService,
)


class LlmUsageServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.sqlite3")
        self.db.migrate()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_records_estimated_tokens_and_cost(self) -> None:
        service = LlmUsageService(
            self.db,
            price_config=LlmUsagePriceConfig(
                input_usd_per_1m_tokens=3,
                output_usd_per_1m_tokens=15,
            ),
        )

        event = service.record(
            provider="claude_cli",
            feature="quiz_generation",
            model="sonnet",
            input_chars=400,
            output_chars=80,
            duration_ms=1234,
            metadata={"topic_id": "b01"},
            created_at=datetime(2026, 7, 5, 10, 0),
        )

        self.assertEqual(100, event.input_tokens)
        self.assertEqual(20, event.output_tokens)
        self.assertEqual(120, event.total_tokens)
        self.assertGreater(event.estimated_usd, 0)
        self.assertEqual("estimated", event.usage_source)

        recent = service.recent_events()
        self.assertEqual(1, len(recent))
        self.assertEqual("b01", recent[0].metadata["topic_id"])

    def test_stats_for_periods_aggregates_failures_and_features(self) -> None:
        service = LlmUsageService(
            self.db,
            price_config=LlmUsagePriceConfig(
                input_usd_per_1m_tokens=3,
                output_usd_per_1m_tokens=15,
            ),
            budget_config=LlmUsageBudgetConfig(
                rolling_5h_usd=1,
                daily_usd=10,
                weekly_usd=20,
                monthly_usd=30,
            ),
        )
        now = datetime(2026, 7, 5, 12, 0)
        service.record(
            provider="claude_cli",
            feature="quiz_generation",
            input_chars=40,
            output_chars=20,
            success=True,
            created_at=now,
        )
        service.record(
            provider="claude_cli",
            feature="topic_inbox_normalize",
            input_chars=80,
            output_chars=0,
            success=False,
            error="boom",
            created_at=now - timedelta(days=2),
        )

        five_hours, today, week, month = service.stats_for_periods(now=now)

        self.assertEqual("5 часов", five_hours.label)
        self.assertEqual(1, five_hours.request_count)
        self.assertGreater(five_hours.budget_percent, 0)
        self.assertEqual(1, today.request_count)
        self.assertEqual(0, today.failure_count)
        self.assertEqual(2, week.request_count)
        self.assertEqual(1, week.failure_count)
        self.assertEqual(2, month.request_count)
        self.assertEqual("topic_inbox_normalize", week.features[0].feature)


if __name__ == "__main__":
    unittest.main()
