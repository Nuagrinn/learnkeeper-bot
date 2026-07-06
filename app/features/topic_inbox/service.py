from __future__ import annotations

import re
import uuid
from datetime import datetime

from app.core.db import Database
from app.features.topic_inbox.agent import TopicInboxAgent, TopicInboxAgentError
from app.features.topic_inbox.models import TopicInboxItem, topic_inbox_item_from_row


ACTIVE = "active"
DELETED = "deleted"


class TopicInboxService:
    def __init__(self, db: Database, agent: TopicInboxAgent):
        self.db = db
        self.agent = agent

    def create_item(self, raw_text: str, *, source: str) -> TopicInboxItem:
        clean_raw = _clean_inline(raw_text)
        if not clean_raw:
            raise ValueError("Topic request must not be empty")

        provider = getattr(self.agent, "provider", "")
        model = getattr(self.agent, "model", "")
        summary = ""
        title = clean_raw
        section = _explicit_section_name(clean_raw)

        try:
            result = self.agent.normalize(clean_raw)
        except TopicInboxAgentError as exc:
            summary = f"Agent failed, saved raw request: {exc}"
        except Exception as exc:
            summary = f"Agent failed unexpectedly, saved raw request: {exc}"
        else:
            title = _clean_inline(result.title) or clean_raw
            section = _sanitize_section(result.section) or section
            title = _strip_section_prefix(title, section)
            title = _strip_meta_title_prefix(title)
            summary = result.summary
            provider = result.provider
            model = result.model

        now = _now()
        item = TopicInboxItem(
            id=uuid.uuid4().hex[:12],
            raw_text=clean_raw,
            title=title,
            section=section,
            source=source,
            status=ACTIVE,
            agent_summary=summary,
            agent_provider=provider,
            agent_model=model,
            created_at=now,
            updated_at=now,
        )
        self._insert(item)
        return item

    def list_active(self, *, limit: int = 20) -> list[TopicInboxItem]:
        with self.db.session() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM study_topic_inbox
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (ACTIVE, limit),
            ).fetchall()
        return [topic_inbox_item_from_row(row) for row in rows]

    def get_item(self, item_id: str) -> TopicInboxItem | None:
        clean_id = item_id.strip()
        if not clean_id:
            return None
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT * FROM study_topic_inbox WHERE id = ?",
                (clean_id,),
            ).fetchone()
        return topic_inbox_item_from_row(row) if row else None

    def delete_item(self, item_id: str) -> TopicInboxItem:
        item = self.get_item(item_id)
        if not item:
            raise ValueError("Topic inbox item not found")
        now = _now()
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE study_topic_inbox
                SET status = ?, updated_at = ?, deleted_at = ?
                WHERE id = ?
                """,
                (DELETED, now.isoformat(), now.isoformat(), item.id),
            )
        updated = self.get_item(item.id)
        if not updated:
            raise ValueError("Topic inbox item not found after delete")
        return updated

    def _insert(self, item: TopicInboxItem) -> None:
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO study_topic_inbox (
                    id,
                    raw_text,
                    title,
                    section,
                    source,
                    status,
                    agent_summary,
                    agent_provider,
                    agent_model,
                    created_at,
                    updated_at,
                    deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.raw_text,
                    item.title,
                    item.section,
                    item.source,
                    item.status,
                    item.agent_summary,
                    item.agent_provider,
                    item.agent_model,
                    item.created_at.isoformat(),
                    item.updated_at.isoformat(),
                    item.deleted_at.isoformat() if item.deleted_at else None,
                ),
            )


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _clean_inline(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).strip(" .!?,:;\"'«»")


def _explicit_section_name(value: str) -> str:
    explicit = re.search(
        r"(?:^|\b)(?:(?:отдельный|новый)\s+)?(?:блок|раздел)\s+(.+?)(?:[:.;]|$)",
        value,
        flags=re.IGNORECASE,
    )
    if explicit:
        return _clean_inline(explicit.group(1))[:80]
    for separator in (".", ":", " - ", " — ", " / ", "/"):
        if separator not in value:
            continue
        candidate = _clean_inline(value.split(separator, 1)[0])
        if len(candidate) >= 3:
            return candidate[:80]
    return ""


def _strip_section_prefix(title: str, section: str) -> str:
    if not title or not section:
        return title
    pattern = rf"^{re.escape(section)}\s*[:\-—]\s*"
    stripped = re.sub(pattern, "", title, flags=re.IGNORECASE).strip()
    return stripped or title


def _sanitize_section(section: str) -> str:
    clean = _clean_inline(section)
    if clean.lower() in {"inbox", "topic", "theme", "тема", "идея", "темы", "идеи"}:
        return ""
    return clean[:80]


def _strip_meta_title_prefix(title: str) -> str:
    clean = _clean_inline(title)
    return re.sub(
        r"^(?:нормализац(?:ия|ию)\s+)?(?:темы|идеи|запроса)\s*[:\-—]\s*",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip() or clean
