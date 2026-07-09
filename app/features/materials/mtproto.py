from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# TODO: Parked experiment, not wired into the bot (no import from bot.py or
# app/adapters). Investigated whether MTProto could force text/markdown MIME
# on uploaded documents where Bot API sendDocument could not (Telegram
# silently drops mime_type to None for Bot API uploads regardless of what is
# requested). Blocked on setting up a working TELEGRAM_API_ID/API_HASH app at
# my.telegram.org for this bot. The "read material" feature now sends GitHub
# links instead (see read_material_topic_callback in
# app/adapters/telegram/bot.py), which sidesteps the MIME problem entirely
# and made this probe unnecessary for now. Either finish wiring this in if a
# document-upload-based approach is needed again later, or delete
# app/features/materials/, tests/test_material_mtproto.py, the
# material-mtproto-probe CLI command, the telethon dependency, and the
# TELEGRAM_API_ID/API_HASH/MTPROTO_SESSION settings.
log = logging.getLogger(__name__)


class MaterialMtprotoError(RuntimeError):
    pass


@dataclass(frozen=True)
class SentMaterialDocument:
    message_id: int | None
    filename: str
    requested_mime_type: str
    stored_mime_type: str | None


class MaterialMtprotoSender:
    """Send material documents through MTProto instead of Bot API sendDocument.

    Telegram Bot API currently does not preserve text/markdown MIME metadata for
    uploaded .md files. MTProto lets us pass the document MIME explicitly, which
    is the bit Telegram iOS appears to need for its native markdown viewer.
    """

    def __init__(
        self,
        *,
        api_id: int | None,
        api_hash: str,
        bot_token: str,
        session_path: Path,
        recipient_id: int | None,
    ) -> None:
        self.api_id = api_id
        self.api_hash = api_hash.strip()
        self.bot_token = bot_token.strip()
        self.session_path = session_path
        self.recipient_id = recipient_id

    def validate(self) -> None:
        missing: list[str] = []
        if not self.api_id:
            missing.append("TELEGRAM_API_ID")
        if not self.api_hash:
            missing.append("TELEGRAM_API_HASH")
        if not self.bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.recipient_id:
            missing.append("TG_USER_ID")
        if missing:
            joined = ", ".join(missing)
            raise MaterialMtprotoError(f"Missing MTProto settings: {joined}")

    async def send_markdown_document(
        self,
        *,
        file_path: Path,
        filename: str,
        caption: str = "",
    ) -> SentMaterialDocument:
        self.validate()
        if not file_path.is_file():
            raise MaterialMtprotoError(f"Material file not found: {file_path}")

        try:
            from telethon import TelegramClient
            from telethon.tl import types
        except ImportError as exc:
            raise MaterialMtprotoError(
                "Telethon is not installed. Run: python -m pip install -r requirements.txt"
            ) from exc

        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        assert self.api_id is not None
        assert self.recipient_id is not None

        log.info(
            "MTProto material send started path=%s filename=%s recipient_id=%s",
            file_path,
            filename,
            self.recipient_id,
        )
        client = TelegramClient(str(self.session_path), self.api_id, self.api_hash)
        try:
            await client.start(bot_token=self.bot_token)
            message = await client.send_file(
                self.recipient_id,
                file=str(file_path),
                caption=caption,
                force_document=True,
                mime_type="text/markdown",
                attributes=[types.DocumentAttributeFilename(file_name=filename)],
            )
        finally:
            await client.disconnect()

        stored_mime_type = _message_document_mime_type(message)
        log.info(
            "MTProto material send finished message_id=%s stored_mime_type=%s",
            getattr(message, "id", None),
            stored_mime_type or "-",
        )
        return SentMaterialDocument(
            message_id=getattr(message, "id", None),
            filename=filename,
            requested_mime_type="text/markdown",
            stored_mime_type=stored_mime_type,
        )


def _message_document_mime_type(message: Any) -> str | None:
    media = getattr(message, "media", None)
    document = getattr(media, "document", None)
    mime_type = getattr(document, "mime_type", None)
    return str(mime_type) if mime_type else None
