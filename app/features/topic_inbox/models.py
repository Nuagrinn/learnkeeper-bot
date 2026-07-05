from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Row


@dataclass(frozen=True)
class TopicInboxItem:
    id: str
    raw_text: str
    title: str
    section: str
    source: str
    status: str
    agent_summary: str
    agent_provider: str
    agent_model: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


def topic_inbox_item_from_row(row: Row) -> TopicInboxItem:
    return TopicInboxItem(
        id=row["id"],
        raw_text=row["raw_text"],
        title=row["title"],
        section=row["section"],
        source=row["source"],
        status=row["status"],
        agent_summary=row["agent_summary"],
        agent_provider=row["agent_provider"],
        agent_model=row["agent_model"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        deleted_at=(
            datetime.fromisoformat(row["deleted_at"])
            if row["deleted_at"]
            else None
        ),
    )
