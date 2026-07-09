from __future__ import annotations

from pathlib import Path
import unittest

from app.features.materials.mtproto import MaterialMtprotoError, MaterialMtprotoSender


class MaterialMtprotoSenderTests(unittest.TestCase):
    def test_validate_reports_missing_settings(self) -> None:
        sender = MaterialMtprotoSender(
            api_id=None,
            api_hash="",
            bot_token="",
            session_path=Path("data/telegram-mtproto"),
            recipient_id=None,
        )

        with self.assertRaises(MaterialMtprotoError) as ctx:
            sender.validate()

        message = str(ctx.exception)
        self.assertIn("TELEGRAM_API_ID", message)
        self.assertIn("TELEGRAM_API_HASH", message)
        self.assertIn("TELEGRAM_BOT_TOKEN", message)
        self.assertIn("TG_USER_ID", message)

    def test_validate_accepts_complete_settings(self) -> None:
        sender = MaterialMtprotoSender(
            api_id=123,
            api_hash="hash",
            bot_token="token",
            session_path=Path("data/telegram-mtproto"),
            recipient_id=456,
        )

        sender.validate()


if __name__ == "__main__":
    unittest.main()
