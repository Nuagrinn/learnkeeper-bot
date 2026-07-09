from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Row


PENDING = "pending"
STARTED = "started"
POSTPONED = "postponed"
SKIPPED = "skipped"
DONE = "done"

# Still worth revisiting later: never explicitly closed out.
OUTSTANDING_STATUSES = (PENDING, STARTED, POSTPONED)


@dataclass(frozen=True)
class DailyQuizOffer:
    id: str
    offer_date: str
    topic_id: str
    topic_title: str
    section: str
    status: str
    created_at: datetime
    updated_at: datetime


def daily_quiz_offer_from_row(row: Row) -> DailyQuizOffer:
    return DailyQuizOffer(
        id=row["id"],
        offer_date=row["offer_date"],
        topic_id=row["topic_id"],
        topic_title=row["topic_title"],
        section=row["section"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
