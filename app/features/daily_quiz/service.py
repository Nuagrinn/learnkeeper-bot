from __future__ import annotations

import random
import uuid
from datetime import date, datetime

from app.core.db import Database
from app.core.repo import RepoService, RepoTopic
from app.features.daily_quiz.models import (
    OUTSTANDING_STATUSES,
    PENDING,
    DailyQuizOffer,
    daily_quiz_offer_from_row,
)


DAILY_QUIZ_ENABLED = "daily_quiz_enabled"
DAILY_QUIZ_LAST_SENT_DATE = "daily_quiz_last_sent_date"


class DailyQuizService:
    def __init__(self, db: Database, repo: RepoService):
        self.db = db
        self.repo = repo

    def is_enabled(self) -> bool:
        return _to_bool(self._get(DAILY_QUIZ_ENABLED, "false"))

    def set_enabled(self, enabled: bool) -> None:
        self._set(DAILY_QUIZ_ENABLED, "true" if enabled else "false")

    def last_sent_date(self) -> str:
        return self._get(DAILY_QUIZ_LAST_SENT_DATE, "")

    def should_send_today(self, today: date) -> bool:
        return self.is_enabled() and self.last_sent_date() != today.isoformat()

    def mark_sent(self, today: date) -> None:
        self._set(DAILY_QUIZ_LAST_SENT_DATE, today.isoformat())

    def ready_topics(self) -> list[RepoTopic]:
        topics = self.repo.list_trainable_topics()
        topics.sort(key=lambda item: (item.section, item.order_index or 10_000, item.title.lower()))
        return topics

    def random_ready_topic(self) -> RepoTopic | None:
        topics = self.ready_topics()
        if not topics:
            return None
        return random.choice(topics)

    def create_offer(
        self,
        topic: RepoTopic,
        today: date,
        *,
        now: datetime | None = None,
    ) -> DailyQuizOffer:
        created = (now or datetime.now()).replace(microsecond=0)
        offer_id = uuid.uuid4().hex[:12]
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO daily_quiz_offers
                    (id, offer_date, topic_id, topic_title, section, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    offer_id,
                    today.isoformat(),
                    topic.id,
                    topic.title,
                    topic.section,
                    PENDING,
                    created.isoformat(timespec="seconds"),
                    created.isoformat(timespec="seconds"),
                ),
            )
        offer = self.get_offer(offer_id)
        assert offer is not None
        return offer

    def get_offer(self, offer_id: str) -> DailyQuizOffer | None:
        clean_id = offer_id.strip()
        if not clean_id:
            return None
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT * FROM daily_quiz_offers WHERE id = ?",
                (clean_id,),
            ).fetchone()
        return daily_quiz_offer_from_row(row) if row else None

    def set_status(
        self,
        offer_id: str,
        status: str,
        *,
        now: datetime | None = None,
    ) -> DailyQuizOffer | None:
        updated = (now or datetime.now()).replace(microsecond=0)
        with self.db.session() as conn:
            conn.execute(
                "UPDATE daily_quiz_offers SET status = ?, updated_at = ? WHERE id = ?",
                (status, updated.isoformat(timespec="seconds"), offer_id),
            )
        return self.get_offer(offer_id)

    def list_outstanding(self, *, limit: int = 10) -> list[DailyQuizOffer]:
        placeholders = ",".join("?" for _ in OUTSTANDING_STATUSES)
        with self.db.session() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM daily_quiz_offers
                WHERE status IN ({placeholders})
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*OUTSTANDING_STATUSES, max(1, min(50, int(limit)))),
            ).fetchall()
        return [daily_quiz_offer_from_row(row) for row in rows]

    def _get(self, key: str, default: str) -> str:
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()
        return row["value"] if row else default

    def _set(self, key: str, value: str) -> None:
        now = datetime.now().replace(microsecond=0).isoformat(timespec="seconds")
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, now),
            )


def _to_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")
