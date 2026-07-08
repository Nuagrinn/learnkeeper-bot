from __future__ import annotations

import random
import uuid
from datetime import date, datetime

from app.core.db import Database
from app.features.coding_reps.models import (
    CODING_REPS,
    CodingRep,
    CodingRepLogEntry,
    coding_rep_log_entry_from_row,
)


CODING_REPS_ENABLED = "coding_reps_enabled"
CODING_REPS_LAST_SENT_DATE = "coding_reps_last_sent_date"


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


class CodingRepsService:
    def __init__(self, db: Database):
        self.db = db

    def is_enabled(self) -> bool:
        return _to_bool(self._get(CODING_REPS_ENABLED, "false"))

    def set_enabled(self, enabled: bool) -> None:
        self._set(CODING_REPS_ENABLED, "true" if enabled else "false")

    def last_sent_date(self) -> str:
        return self._get(CODING_REPS_LAST_SENT_DATE, "")

    def should_send_today(self, today: date) -> bool:
        return self.is_enabled() and self.last_sent_date() != today.isoformat()

    def mark_sent(self, today: date) -> None:
        self._set(CODING_REPS_LAST_SENT_DATE, today.isoformat())

    def random_rep(self) -> CodingRep:
        """Pick a rep, avoiding an immediate repeat of the last one sent."""
        last_id = self._last_logged_rep_id()
        candidates = [rep for rep in CODING_REPS if rep.id != last_id]
        return random.choice(candidates or CODING_REPS)

    def log_sent(self, rep: CodingRep, *, now: datetime | None = None) -> str:
        now = (now or _now()).replace(microsecond=0)
        log_id = uuid.uuid4().hex[:12]
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO coding_rep_log (id, rep_id, rep_title, status, sent_at)
                VALUES (?, ?, ?, 'sent', ?)
                """,
                (log_id, rep.id, rep.title, now.isoformat(timespec="seconds")),
            )
        return log_id

    def mark_responded(
        self,
        log_id: str,
        status: str,
        *,
        now: datetime | None = None,
    ) -> None:
        now = (now or _now()).replace(microsecond=0)
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE coding_rep_log
                SET status = ?, responded_at = ?
                WHERE id = ?
                """,
                (status, now.isoformat(timespec="seconds"), log_id),
            )

    def recent_log(self, *, limit: int = 20) -> list[CodingRepLogEntry]:
        with self.db.session() as conn:
            rows = conn.execute(
                "SELECT * FROM coding_rep_log ORDER BY sent_at DESC LIMIT ?",
                (max(1, min(100, int(limit))),),
            ).fetchall()
        return [coding_rep_log_entry_from_row(row) for row in rows]

    def get_log_entry(self, log_id: str) -> CodingRepLogEntry | None:
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT * FROM coding_rep_log WHERE id = ?",
                (log_id,),
            ).fetchone()
        return coding_rep_log_entry_from_row(row) if row else None

    def _last_logged_rep_id(self) -> str | None:
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT rep_id FROM coding_rep_log ORDER BY sent_at DESC LIMIT 1"
            ).fetchone()
        return row["rep_id"] if row else None

    def _get(self, key: str, default: str) -> str:
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()
        return row["value"] if row else default

    def _set(self, key: str, value: str) -> None:
        now = _now().isoformat(timespec="seconds")
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
