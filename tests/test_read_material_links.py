from __future__ import annotations

import unittest

from app.adapters.telegram.bot import _material_github_url, _read_material_links_text


class ReadMaterialLinksTest(unittest.TestCase):
    def test_material_github_url_joins_base_and_path(self) -> None:
        url = _material_github_url(
            "https://github.com/Nuagrinn/interview-review/blob/main",
            "base-go/01-slices/review.md",
        )

        self.assertEqual(
            "https://github.com/Nuagrinn/interview-review/blob/main/base-go/01-slices/review.md",
            url,
        )

    def test_material_github_url_strips_leading_slash_on_source_path(self) -> None:
        url = _material_github_url(
            "https://github.com/Nuagrinn/interview-review/blob/main",
            "/base-go/01-slices/review.md",
        )

        self.assertEqual(
            "https://github.com/Nuagrinn/interview-review/blob/main/base-go/01-slices/review.md",
            url,
        )

    def test_links_text_escapes_title_and_lists_each_link(self) -> None:
        text = _read_material_links_text(
            "Строки <и> байты",
            [
                ("internals.md", "https://example.com/internals.md?x=1&y=2"),
                ("review.md", "https://example.com/review.md"),
            ],
        )

        self.assertIn("Строки &lt;и&gt; байты", text)
        self.assertIn('<a href="https://example.com/internals.md?x=1&amp;y=2">internals.md</a>', text)
        self.assertIn('<a href="https://example.com/review.md">review.md</a>', text)


if __name__ == "__main__":
    unittest.main()
