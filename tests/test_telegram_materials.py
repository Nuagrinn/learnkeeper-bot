from __future__ import annotations

import unittest

from app.adapters.telegram.bot import (
    UTF8_BOM,
    _read_material_input_file,
    _telegram_material_document_bytes,
)


class _FakeRepo:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read_material_bytes(self, source_path: str) -> bytes:
        return self.data


class _FakeServices:
    def __init__(self, data: bytes) -> None:
        self.repo = _FakeRepo(data)


class TelegramMaterialDocumentTests(unittest.TestCase):
    def test_markdown_upload_gets_utf8_bom(self) -> None:
        raw = "# Слайсы в Go\r\nТекст\r\n".encode("utf-8")

        result = _telegram_material_document_bytes("base-go/01-slices/review.md", raw)

        self.assertTrue(result.startswith(UTF8_BOM))
        self.assertEqual(raw, result[len(UTF8_BOM) :])

    def test_markdown_upload_does_not_duplicate_existing_bom(self) -> None:
        raw = UTF8_BOM + "# Слайсы в Go\n".encode("utf-8")

        result = _telegram_material_document_bytes("base-go/01-slices/review.md", raw)

        self.assertEqual(raw, result)

    def test_non_markdown_upload_is_untouched(self) -> None:
        raw = b"\x89PNG\r\n\x1a\n"

        result = _telegram_material_document_bytes("base-go/diagram.png", raw)

        self.assertEqual(raw, result)

    def test_invalid_utf8_markdown_upload_is_untouched(self) -> None:
        raw = b"# invalid utf8: \xff"

        result = _telegram_material_document_bytes("base-go/review.md", raw)

        self.assertEqual(raw, result)

    def test_read_material_input_file_marks_markdown_as_utf8(self) -> None:
        raw = "# Слайсы в Go\n".encode("utf-8")

        input_file = _read_material_input_file(
            _FakeServices(raw),
            "b01",
            "base-go/01-slices/review.md",
        )

        self.assertIsNotNone(input_file)
        assert input_file is not None
        self.assertEqual("b01-review.md", input_file.filename)
        self.assertEqual("text/markdown; charset=utf-8", input_file.mimetype)
        self.assertTrue(input_file.input_file_content.startswith(UTF8_BOM))


if __name__ == "__main__":
    unittest.main()
