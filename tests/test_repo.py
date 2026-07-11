from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from app.core.repo import RepoService


class RepoServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "lk-prep"
        self.repo.mkdir()
        (self.repo / "ROOT.md").write_text(
            """
# LK Prep

## Code Review Go

| # | Тема | Материал | Практика | Статус |
|---|---|---|---|---|
| CR01 | Data race в Go | [review.md](01-data-race/review.md) | [practice.go](01-data-race/practice.go) | Готово |
| CR02 | Backpressure | - | - | Планируется |
""".strip(),
            encoding="utf-8",
        )
        (self.repo / "AGENTS.md").write_text("# Agent Contract\n", encoding="utf-8")
        (self.repo / "CLAUDE.md").write_text("# Claude Instructions\n", encoding="utf-8")
        topic_dir = self.repo / "01-data-race"
        topic_dir.mkdir()
        (topic_dir / "review.md").write_text("# Data race в Go\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_root_md_topics_are_primary_catalog(self) -> None:
        topics = RepoService(self.repo).list_topics()

        cr01 = next(topic for topic in topics if topic.id == "cr01")
        self.assertEqual("Data race в Go", cr01.title)
        self.assertEqual("ready", cr01.status)
        self.assertEqual("Code Review Go", cr01.section)
        self.assertEqual(1, cr01.order_index)
        self.assertTrue(cr01.material_fingerprint)
        self.assertEqual(
            ["01-data-race/review.md", "01-data-race/practice.go"],
            cr01.source_paths,
        )

        cr02 = next(topic for topic in topics if topic.id == "cr02")
        self.assertEqual("planned", cr02.status)
        self.assertEqual("Code Review Go", cr02.section)
        self.assertEqual(2, cr02.order_index)
        self.assertEqual("", cr02.material_fingerprint)
        self.assertFalse(any(topic.id == "agent-contract" for topic in topics))
        self.assertFalse(any(topic.id == "claude-instructions" for topic in topics))

    def test_search_finds_root_topic_by_text(self) -> None:
        matches = RepoService(self.repo).search_topics("data race")

        self.assertEqual("cr01", matches[0].id)

    def test_search_ignores_case_and_punctuation(self) -> None:
        matches = RepoService(self.repo).search_topics("DATA RACE!")

        self.assertEqual("cr01", matches[0].id)
        self.assertGreaterEqual(matches[0].score, 50)

    def test_search_ignores_voice_command_words(self) -> None:
        matches = RepoService(self.repo).search_topics("давай data race на повторение")

        self.assertEqual("cr01", matches[0].id)
        self.assertGreaterEqual(matches[0].score, 50)

    def test_get_topic_materials_parses_lk_frontmatter(self) -> None:
        (self.repo / "01-data-race" / "review.md").write_text(
            """---
lk:
  source_role: primary_source_artifact
  source_refs:
    - "Go Memory Model"
  prompt_helper: |
    Проверяй не определение, а понимание happens-before и race detector.
---

# Data race в Go

Материал темы.
""",
            encoding="utf-8",
        )

        topic = RepoService(self.repo).get_topic("cr01")
        assert topic is not None
        materials = RepoService(self.repo).get_topic_materials(topic)

        material = materials.files[0]
        self.assertEqual("primary_source_artifact", material.metadata.source_role)
        self.assertEqual(["Go Memory Model"], material.metadata.source_refs)
        self.assertIn("happens-before", material.metadata.prompt_helper)
        self.assertTrue(material.content.startswith("# Data race"))
        self.assertNotIn("source_role", material.content)

    def test_pull_latest_skips_when_not_a_git_repo(self) -> None:
        result = RepoService(self.repo).pull_latest()

        self.assertEqual("skipped", result.status)
        self.assertFalse(result.ok)

    def test_pull_latest_skips_when_repo_missing(self) -> None:
        result = RepoService(None).pull_latest()

        self.assertEqual("skipped", result.status)

    def test_pull_latest_reports_up_to_date(self) -> None:
        (self.repo / ".git").mkdir()
        calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="Already up to date.\n", stderr="")

        result = RepoService(self.repo).pull_latest(run_command=fake_run)

        self.assertEqual("up_to_date", result.status)
        self.assertTrue(result.ok)
        self.assertIn("--ff-only", calls[0])

    def test_pull_latest_reports_updated(self) -> None:
        (self.repo / ".git").mkdir()

        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(
                command, 0, stdout="Updating a1b2c3d..e4f5g6h\nFast-forward\n", stderr=""
            )

        result = RepoService(self.repo).pull_latest(run_command=fake_run)

        self.assertEqual("updated", result.status)
        self.assertTrue(result.updated)

    def test_pull_latest_passes_remote_and_branch(self) -> None:
        (self.repo / ".git").mkdir()
        captured: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="Already up to date.\n", stderr="")

        RepoService(self.repo).pull_latest(remote="origin", branch="main", run_command=fake_run)

        self.assertEqual(captured[0][-3:], ["--ff-only", "origin", "main"])

    def test_pull_latest_failure_is_not_fatal(self) -> None:
        (self.repo / ".git").mkdir()

        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="fatal: no tracking branch")

        result = RepoService(self.repo).pull_latest(run_command=fake_run)

        self.assertEqual("failed", result.status)
        self.assertIn("tracking branch", result.detail)


if __name__ == "__main__":
    unittest.main()
