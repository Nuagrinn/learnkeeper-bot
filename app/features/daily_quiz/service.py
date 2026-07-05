from __future__ import annotations

import random
from datetime import date, datetime

from app.core.db import Database
from app.core.repo import RepoService, RepoTopic


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
        topics: list[RepoTopic] = []
        for topic in self.repo.list_topics():
            if topic.status != "ready":
                continue
            if not self.repo.get_topic_materials(topic).files:
                continue
            topics.append(topic)
        topics.sort(key=lambda item: (item.section, item.order_index or 10_000, item.title.lower()))
        return topics

    def random_ready_topic(self) -> RepoTopic | None:
        topics = self.ready_topics()
        if not topics:
            return None
        return random.choice(topics)

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
