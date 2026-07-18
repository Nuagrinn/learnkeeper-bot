from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.core.catalog import CatalogLoader, CatalogNode


log = logging.getLogger(__name__)

RunCommand = Callable[..., subprocess.CompletedProcess[str]]


QUERY_NOISE_WORDS = {
    "а",
    "давай",
    "давайте",
    "добавь",
    "добавить",
    "задачу",
    "запланируй",
    "запланировать",
    "закрепление",
    "мне",
    "на",
    "надо",
    "нужно",
    "поставить",
    "поставь",
    "по",
    "повтор",
    "повторение",
    "повторить",
    "повторять",
    "пожалуйста",
    "про",
    "создай",
    "создать",
    "тема",
    "тему",
    "хочу",
    "add",
    "create",
    "review",
    "task",
    "topic",
}


@dataclass(frozen=True)
class RepoTopic:
    id: str
    title: str
    status: str = "unknown"
    section: str = ""
    order_index: int | None = None
    material_fingerprint: str = ""
    tags: list[str] = field(default_factory=list)
    source_paths: list[str] = field(default_factory=list)
    kind: str = "topic"
    parent_id: str = ""
    parent_title: str = ""
    breadcrumb: list[str] = field(default_factory=list)
    catalog_path: str = ""
    trainable: bool = True
    score: int = 0


@dataclass(frozen=True)
class MaterialMetadata:
    source_role: str = ""
    source_refs: list[str] = field(default_factory=list)
    prompt_helper: str = ""
    challenge_helper: str = ""

    @property
    def has_guidance(self) -> bool:
        return bool(
            self.source_role
            or self.source_refs
            or self.prompt_helper
            or self.challenge_helper
        )


@dataclass(frozen=True)
class TopicMaterial:
    source_path: str
    content: str
    metadata: MaterialMetadata = field(default_factory=MaterialMetadata)


@dataclass(frozen=True)
class TopicMaterials:
    topic: RepoTopic
    files: list[TopicMaterial]
    fingerprint: str


@dataclass(frozen=True)
class RepoPullResult:
    """Outcome of a best-effort ``git pull`` on the materials repository.

    Pulling must never block quiz generation: any failure returns a result with
    ``status="failed"`` instead of raising, so the bot falls back to whatever is
    already on disk.
    """

    status: str  # "updated" | "up_to_date" | "skipped" | "failed"
    detail: str = ""

    @property
    def updated(self) -> bool:
        return self.status == "updated"

    @property
    def ok(self) -> bool:
        return self.status in ("updated", "up_to_date")


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^\w]+", "-", text, flags=re.UNICODE)
    text = text.strip("-")
    return text or "topic"


def _normalize(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _query_variants(query: str) -> list[str]:
    normalized = _normalize(query)
    if not normalized:
        return []

    variants = [normalized]
    terms = normalized.split()
    meaningful = " ".join(term for term in terms if term not in QUERY_NOISE_WORDS)
    if meaningful and meaningful not in variants:
        variants.append(meaningful)
    return variants


def _score_topic_query(*, query_norm: str, haystack: str, title_norm: str) -> int:
    query_terms = {term for term in query_norm.split() if term}
    score = 0
    if query_norm == title_norm:
        score += 100
    if query_norm and query_norm in haystack:
        score += 50
    score += sum(10 for term in query_terms if term in haystack)
    return score


def _first_heading(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[:80]:
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
    except OSError:
        return None
    return None


class RepoService:
    def __init__(self, repo_path: Path | None):
        self.repo_path = Path(repo_path) if repo_path else None

    def is_available(self) -> bool:
        return bool(self.repo_path and self.repo_path.exists() and self.repo_path.is_dir())

    def pull_latest(
        self,
        *,
        remote: str = "origin",
        branch: str = "",
        timeout_seconds: int = 120,
        run_command: RunCommand | None = None,
    ) -> RepoPullResult:
        """Fast-forward the local materials clone to the latest remote commit.

        Best-effort and non-fatal: on any problem (no repo, no git, no upstream,
        diverged history, timeout) it logs and returns a result so the caller can
        keep generating a quiz from the materials already on disk.
        """
        if not self.is_available() or self.repo_path is None:
            return RepoPullResult("skipped", "lk-prep repository is not available")
        if not (self.repo_path / ".git").exists():
            return RepoPullResult("skipped", "lk-prep is not a git repository")

        runner = run_command or subprocess.run
        args = ["git", "-C", str(self.repo_path), "pull", "--ff-only"]
        if remote and branch:
            args.extend([remote, branch])
        try:
            result = runner(
                args,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
        except FileNotFoundError:
            log.warning("git executable not found; skipping lk-prep pull")
            return RepoPullResult("failed", "git executable not found")
        except subprocess.TimeoutExpired:
            log.warning("lk-prep pull timed out after %s seconds", timeout_seconds)
            return RepoPullResult("failed", f"git pull timed out after {timeout_seconds}s")

        if result.returncode != 0:
            detail = ((result.stderr or "") + (result.stdout or "")).strip()[:300]
            log.warning(
                "lk-prep pull failed returncode=%s detail=%s",
                result.returncode,
                detail,
            )
            return RepoPullResult("failed", detail or f"git pull exited with {result.returncode}")

        output = (result.stdout or "").strip()
        if "up to date" in output.lower():
            log.info("lk-prep already up to date")
            return RepoPullResult("up_to_date", output)
        log.info(
            "lk-prep pull applied updates: %s",
            output.splitlines()[-1] if output else "(no output)",
        )
        return RepoPullResult("updated", output)

    def search_topics(self, query: str, limit: int = 10) -> list[RepoTopic]:
        if not self.is_available():
            return []

        topics = self.list_topics()
        query_variants = _query_variants(query)
        if not query_variants:
            return []

        scored: list[RepoTopic] = []
        for topic in topics:
            haystack = _normalize(
                " ".join(
                    [
                        topic.title,
                        topic.id,
                        topic.section,
                        topic.parent_title,
                        topic.catalog_path,
                        " ".join(topic.breadcrumb),
                        " ".join(topic.source_paths),
                    ]
                )
            )
            title_norm = _normalize(topic.title)
            score = max(
                _score_topic_query(
                    query_norm=query_norm,
                    haystack=haystack,
                    title_norm=title_norm,
                )
                for query_norm in query_variants
            )
            if score > 0:
                scored.append(replace(topic, score=score))
        scored.sort(key=lambda item: (-item.score, item.title.lower()))
        return scored[:limit]

    def resolve_topic(self, query: str) -> RepoTopic:
        matches = self.search_topics(query, limit=1)
        if matches:
            return matches[0]
        return RepoTopic(id=slugify(query), title=query.strip(), source_paths=[])

    def get_topic(self, topic_id: str) -> RepoTopic | None:
        clean_id = topic_id.strip().lower()
        if not clean_id or not self.is_available():
            return None
        for topic in self.list_topics():
            if topic.id.lower() == clean_id:
                return topic
        return None

    def get_topic_materials(self, topic: RepoTopic) -> TopicMaterials:
        files: list[TopicMaterial] = []
        if self.repo_path:
            for rel in topic.source_paths:
                material = self.read_material(rel)
                if material:
                    files.append(material)
        return TopicMaterials(
            topic=topic,
            files=files,
            fingerprint=self.material_fingerprint(topic.source_paths),
        )

    def read_material(self, source_path: str) -> TopicMaterial | None:
        if not self.repo_path:
            return None
        path = self.repo_path / source_path
        if not path.is_file():
            return None
        try:
            raw_content = path.read_text(encoding="utf-8")
        except OSError:
            return None
        content, metadata = _extract_material_metadata(raw_content)
        return TopicMaterial(source_path=source_path, content=content, metadata=metadata)

    def list_topics(self) -> list[RepoTopic]:
        if not self.is_available():
            return []

        topics: dict[str, RepoTopic] = {}
        for topic in self._load_catalog_topics():
            topics[topic.id] = topic

        # Markdown scan is a fallback: it adds files not already represented by
        # ROOT.md/topics.json, but does not override explicit catalog entries.
        known_paths = {
            path
            for topic in topics.values()
            for path in topic.source_paths
        }
        for topic in self._scan_markdown_topics():
            if topic.source_paths and topic.source_paths[0] in known_paths:
                continue
            topics.setdefault(topic.id, topic)

        return sorted(topics.values(), key=lambda item: item.id.lower())

    def list_trainable_topics(self) -> list[RepoTopic]:
        return [
            topic
            for topic in self.list_topics()
            if topic.trainable and topic.status == "ready" and self.get_topic_materials(topic).files
        ]

    def _load_catalog_topics(self) -> list[RepoTopic]:
        if not self.repo_path:
            return []
        snapshot = CatalogLoader(self.repo_path).load()
        return [_topic_from_catalog_node(node) for node in snapshot.nodes]

    def _load_json_topics(self) -> list[RepoTopic]:
        if not self.repo_path:
            return []
        manifest = self.repo_path / "topics.json"
        if not manifest.exists():
            return []
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        items = raw.get("topics", raw if isinstance(raw, list) else [])
        topics: list[RepoTopic] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            topic_id = str(item.get("id") or slugify(title))
            paths = [str(p) for p in item.get("paths", [])]
            tags = [str(t) for t in item.get("tags", [])]
            topics.append(
                RepoTopic(
                    id=topic_id,
                    title=title,
                    status=str(item.get("status", "unknown")),
                    section=str(item.get("section", "")),
                    order_index=_optional_int(item.get("order_index")),
                    material_fingerprint=self.material_fingerprint(paths),
                    tags=tags,
                    source_paths=paths,
                )
            )
        return topics

    def _load_root_topics(self) -> list[RepoTopic]:
        if not self.repo_path:
            return []
        root = self.repo_path / "ROOT.md"
        if not root.exists():
            return []
        try:
            lines = root.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

        topics: list[RepoTopic] = []
        current_section = ""
        section_order: dict[str, int] = {}
        for line in lines:
            heading = _section_heading(line)
            if heading:
                current_section = heading
                section_order.setdefault(current_section, 0)
                continue

            cells = _table_cells(line)
            if not cells:
                continue
            if cells[0] in ("#", "---") or set(cells[0]) <= {"-"}:
                continue
            if cells[0].lower() in ("#", "id", "раздел"):
                continue
            topic_id = cells[0].strip()
            if not re.match(r"^[A-Za-zА-Яа-я]{1,4}\d{1,3}$", topic_id):
                continue
            if len(cells) < 3:
                continue

            title = _strip_markdown(cells[1])
            status = _normalize_status(cells[-1])
            links: list[str] = []
            for cell in cells[2:-1]:
                links.extend(_extract_markdown_links(cell))
            section_order[current_section] = section_order.get(current_section, 0) + 1

            topics.append(
                RepoTopic(
                    id=topic_id.lower(),
                    title=title,
                    status=status,
                    section=current_section,
                    order_index=section_order[current_section],
                    material_fingerprint=self.material_fingerprint(links),
                    tags=[_topic_group(topic_id)],
                    source_paths=links,
                )
            )
        return topics

    def _scan_markdown_topics(self) -> list[RepoTopic]:
        if not self.repo_path:
            return []
        has_primary_catalog = (self.repo_path / "ROOT.md").exists()
        topics: list[RepoTopic] = []
        for path in self.repo_path.rglob("*.md"):
            if any(part in (".git", ".idea", ".gocache") for part in path.parts):
                continue
            rel = path.relative_to(self.repo_path).as_posix()
            if rel in ("ROOT.md", "AGENTS.md", "CLAUDE.md", "README.md"):
                continue
            title = _first_heading(path) or path.stem.replace("-", " ").replace("_", " ")
            topics.append(
                RepoTopic(
                    id=slugify(title),
                    title=title,
                    status="unknown" if has_primary_catalog else "ready",
                    section=_fallback_section(rel),
                    material_fingerprint=self.material_fingerprint([rel]),
                    source_paths=[rel],
                    kind="discovered",
                    catalog_path=_fallback_section(rel),
                    trainable=not has_primary_catalog,
                )
            )
        return topics

    def material_fingerprint(self, source_paths: list[str]) -> str:
        if not self.repo_path or not source_paths:
            return ""
        digest = hashlib.sha256()
        added = False
        for rel in sorted(source_paths):
            path = self.repo_path / rel
            if not path.is_file():
                continue
            try:
                content = path.read_bytes()
            except OSError:
                continue
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(content)
            digest.update(b"\0")
            added = True
        return digest.hexdigest() if added else ""


def _table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _topic_from_catalog_node(node: CatalogNode) -> RepoTopic:
    return RepoTopic(
        id=node.id,
        title=node.title,
        status=node.status,
        section=node.section,
        order_index=node.order_index,
        material_fingerprint=node.material_fingerprint,
        tags=list(node.tags),
        source_paths=list(node.source_paths),
        kind=node.kind,
        parent_id=node.parent_id,
        parent_title=node.parent_title,
        breadcrumb=list(node.breadcrumb),
        catalog_path=node.catalog_path,
        trainable=node.trainable,
    )


def _extract_markdown_links(value: str) -> list[str]:
    return [match.strip() for match in re.findall(r"\[[^\]]+\]\(([^)]+)\)", value)]


def _strip_markdown(value: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    return text.replace("`", "").strip()


def _normalize_status(value: str) -> str:
    text = _normalize(_strip_markdown(value))
    if text in ("готово", "done", "ready"):
        return "ready"
    if text in ("планируется", "planned", "todo"):
        return "planned"
    if text in ("в процессе", "learning", "in progress"):
        return "learning"
    return text or "unknown"


def _topic_group(topic_id: str) -> str:
    prefix = re.sub(r"\d+", "", topic_id).lower()
    return prefix or "topic"


def _section_heading(line: str) -> str:
    stripped = line.strip()
    if not stripped.startswith("## "):
        return ""
    heading = stripped.lstrip("#").strip()
    if heading.lower().startswith("быстрый"):
        return ""
    return heading


def _fallback_section(rel_path: str) -> str:
    if "/" not in rel_path:
        return ""
    first = rel_path.split("/", 1)[0]
    if first == "database":
        return "Базы данных"
    if first == "base-go":
        return "Базовый Go"
    if first.startswith(("01-", "02-", "03-", "05-", "06-", "07-")):
        return "Code Review Go"
    return first


def _optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_material_metadata(content: str) -> tuple[str, MaterialMetadata]:
    text = content.lstrip("\ufeff")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return content, MaterialMetadata()

    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return content, MaterialMetadata()

    frontmatter = "".join(lines[1:end_index])
    body = "".join(lines[end_index + 1 :])
    return body.lstrip("\r\n"), _parse_lk_frontmatter(frontmatter)


def _parse_lk_frontmatter(frontmatter: str) -> MaterialMetadata:
    lk_lines = _lk_frontmatter_lines(frontmatter)
    if not lk_lines:
        return MaterialMetadata()

    source_role = ""
    source_refs: list[str] = []
    prompt_helper_lines: list[str] = []
    challenge_helper_lines: list[str] = []
    mode = ""

    for raw_line in lk_lines:
        stripped = raw_line.strip()
        if mode in ("prompt_helper", "challenge_helper"):
            if _is_lk_key_line(raw_line):
                mode = ""
            else:
                if mode == "prompt_helper":
                    prompt_helper_lines.append(_strip_lk_indent(raw_line))
                else:
                    challenge_helper_lines.append(_strip_lk_indent(raw_line))
                continue

        if mode == "source_refs":
            if stripped.startswith("- "):
                source_refs.append(_clean_yaml_scalar(stripped[2:]))
                continue
            if _is_lk_key_line(raw_line):
                mode = ""

        if stripped.startswith("source_role:"):
            source_role = _clean_yaml_scalar(stripped.split(":", 1)[1])
            continue
        if stripped.startswith("source_refs:"):
            mode = "source_refs"
            inline = stripped.split(":", 1)[1].strip()
            if inline.startswith("[") and inline.endswith("]"):
                source_refs.extend(
                    _clean_yaml_scalar(item)
                    for item in inline.strip("[]").split(",")
                    if _clean_yaml_scalar(item)
                )
            continue
        if stripped.startswith("prompt_helper:"):
            value = stripped.split(":", 1)[1].strip()
            if value in ("|", ">"):
                mode = "prompt_helper"
                continue
            prompt_helper_lines.append(_clean_yaml_scalar(value))
            continue
        if stripped.startswith("challenge_helper:"):
            value = stripped.split(":", 1)[1].strip()
            if value in ("|", ">"):
                mode = "challenge_helper"
                continue
            challenge_helper_lines.append(_clean_yaml_scalar(value))

    prompt_helper = "\n".join(prompt_helper_lines).strip()
    challenge_helper = "\n".join(challenge_helper_lines).strip()
    return MaterialMetadata(
        source_role=source_role.strip(),
        source_refs=[ref for ref in source_refs if ref],
        prompt_helper=prompt_helper,
        challenge_helper=challenge_helper,
    )


def _lk_frontmatter_lines(frontmatter: str) -> list[str]:
    lines = frontmatter.splitlines()
    result: list[str] = []
    in_lk = False
    for line in lines:
        if not in_lk:
            if line.strip() == "lk:":
                in_lk = True
            continue
        if line.strip() and not line.startswith((" ", "\t")):
            break
        result.append(line)
    return result


def _is_lk_key_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("- "):
        return False
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*:", stripped))


def _strip_lk_indent(line: str) -> str:
    if line.startswith("    "):
        return line[4:]
    if line.startswith("  "):
        return line[2:]
    return line.strip()


def _clean_yaml_scalar(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1].strip()
    return text
