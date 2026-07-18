from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogNode:
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
    source: str = ""


@dataclass(frozen=True)
class CatalogSnapshot:
    nodes: list[CatalogNode]

    def trainable_nodes(self) -> list[CatalogNode]:
        return [node for node in self.nodes if node.trainable]


class CatalogSource(Protocol):
    def load(self) -> list[CatalogNode]:
        ...


class CatalogLoader:
    """Loads lk-prep as a catalog graph, not just a flat ROOT.md table."""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    def load(self) -> CatalogSnapshot:
        nodes: list[CatalogNode] = []
        nodes.extend(JsonCatalogSource(self.repo_path).load())

        root_nodes = RootMarkdownCatalogSource(self.repo_path).load()
        nodes.extend(root_nodes)
        nodes.extend(NestedIndexCatalogSource(self.repo_path, root_nodes).load())

        return CatalogSnapshot(_dedupe_nodes(nodes))


class JsonCatalogSource:
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    def load(self) -> list[CatalogNode]:
        manifest = self.repo_path / "topics.json"
        if not manifest.exists():
            return []
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("Could not parse topics.json in lk-prep", exc_info=True)
            return []

        items = raw.get("topics", raw if isinstance(raw, list) else [])
        nodes: list[CatalogNode] = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            node_id = str(item.get("id") or _slugify(title)).lower()
            paths = [_normalize_repo_relpath(str(path)) for path in item.get("paths", [])]
            tags = [str(tag) for tag in item.get("tags", [])]
            section = str(item.get("section", "")).strip()
            kind = str(item.get("kind") or "topic").strip() or "topic"
            breadcrumb = _breadcrumb(section, title)
            nodes.append(
                CatalogNode(
                    id=node_id,
                    title=title,
                    status=str(item.get("status", "unknown")).strip() or "unknown",
                    section=section,
                    order_index=_optional_int(item.get("order_index")) or index,
                    material_fingerprint=_material_fingerprint(self.repo_path, paths),
                    tags=tags,
                    source_paths=[path for path in paths if path],
                    kind=kind,
                    parent_id=str(item.get("parent_id") or "").lower(),
                    parent_title=str(item.get("parent_title") or ""),
                    breadcrumb=breadcrumb,
                    catalog_path=_catalog_path(breadcrumb),
                    trainable=_as_bool(item.get("trainable"), default=bool(paths)),
                    source="json",
                )
            )
        return nodes


class RootMarkdownCatalogSource:
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    def load(self) -> list[CatalogNode]:
        root = self.repo_path / "ROOT.md"
        if not root.exists():
            return []
        try:
            lines = root.read_text(encoding="utf-8").splitlines()
        except OSError:
            log.warning("Could not read ROOT.md in lk-prep", exc_info=True)
            return []

        nodes: list[CatalogNode] = []
        current_section = ""
        section_order: dict[str, int] = {}
        for line in lines:
            heading = _section_heading(line)
            if heading:
                current_section = heading
                section_order.setdefault(current_section, 0)
                continue

            cells = _table_cells(line)
            if not _is_topic_row(cells):
                continue

            node_id = cells[0].strip()
            title = _strip_markdown(cells[1])
            status = _normalize_status(cells[-1])
            links = _links_from_material_cells(cells[2:-1])
            kind = _root_node_kind(current_section, links)
            section_order[current_section] = section_order.get(current_section, 0) + 1
            breadcrumb = _breadcrumb(current_section, title)
            normalized_links = [_normalize_repo_relpath(link) for link in links]
            nodes.append(
                CatalogNode(
                    id=node_id.lower(),
                    title=title,
                    status=status,
                    section=current_section,
                    order_index=section_order[current_section],
                    material_fingerprint=_material_fingerprint(self.repo_path, normalized_links),
                    tags=[_topic_group(node_id)],
                    source_paths=[path for path in normalized_links if path],
                    kind=kind,
                    breadcrumb=breadcrumb,
                    catalog_path=_catalog_path(breadcrumb),
                    trainable=_is_trainable(kind=kind, source_paths=normalized_links),
                    source="root",
                )
            )
        return nodes


class NestedIndexCatalogSource:
    """Expands catalog index files linked from ROOT.md into child nodes.

    The first supported shape is the book chapter table used by lk-prep:

    | Topic id | Глава | Разбор | Материал | Статус |
    """

    def __init__(self, repo_path: Path, parents: list[CatalogNode]):
        self.repo_path = repo_path
        self.parents = parents

    def load(self) -> list[CatalogNode]:
        nodes: list[CatalogNode] = []
        for parent in self.parents:
            for index_path in _index_paths(parent.source_paths):
                nodes.extend(self._load_index(parent, index_path))
        return nodes

    def _load_index(self, parent: CatalogNode, index_path: str) -> list[CatalogNode]:
        path = self.repo_path / index_path
        if not path.is_file():
            log.warning(
                "Catalog index linked from ROOT.md is missing parent_id=%s path=%s",
                parent.id,
                index_path,
            )
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            log.warning("Could not read catalog index path=%s", index_path, exc_info=True)
            return []

        index_title = _first_heading(lines) or parent.title
        child_section = _child_section(parent, index_path, index_title)
        rows = _parse_index_rows(lines)
        nodes: list[CatalogNode] = []
        for row_index, row in enumerate(rows, start=1):
            node = self._node_from_row(
                parent=parent,
                index_path=index_path,
                child_section=child_section,
                row=row,
                row_index=row_index,
            )
            if node:
                nodes.append(node)
        return nodes

    def _node_from_row(
        self,
        *,
        parent: CatalogNode,
        index_path: str,
        child_section: str,
        row: dict[str, str],
        row_index: int,
    ) -> CatalogNode | None:
        raw_id = _first_present(row, "topic id", "#", "id", "тема id")
        if not raw_id:
            return None
        node_id = raw_id.strip()
        if not _TOPIC_ID_RE.match(node_id):
            return None

        title = (
            _strip_markdown(_first_present(row, "разбор", "тема", "title"))
            or _strip_markdown(_first_present(row, "глава", "chapter"))
            or node_id
        )
        status = _normalize_status(_first_present(row, "статус", "status"))
        material_cells = [
            value
            for key, value in row.items()
            if key not in ("topic id", "#", "id", "тема id", "глава", "chapter", "разбор", "тема", "title", "статус", "status")
        ]
        links = [
            _resolve_index_link(index_path, link)
            for cell in material_cells
            for link in _extract_markdown_links(cell)
        ]
        links = [link for link in links if link]
        breadcrumb = [*parent.breadcrumb, title] if parent.breadcrumb else _breadcrumb(parent.title, title)
        return CatalogNode(
            id=node_id.lower(),
            title=title,
            status=status,
            section=child_section,
            order_index=row_index,
            material_fingerprint=_material_fingerprint(self.repo_path, links),
            tags=[_topic_group(node_id), parent.id, parent.kind],
            source_paths=links,
            kind=_child_kind(parent),
            parent_id=parent.id,
            parent_title=parent.title,
            breadcrumb=breadcrumb,
            catalog_path=_catalog_path(breadcrumb),
            trainable=_is_trainable(kind=_child_kind(parent), source_paths=links),
            source="nested",
        )


_TOPIC_ID_RE = re.compile(r"^[A-Za-zА-Яа-я]{1,4}\d{1,3}$")
_INDEX_FILENAMES = {"index.md", "toc.md", "contents.md"}


def _dedupe_nodes(nodes: list[CatalogNode]) -> list[CatalogNode]:
    by_id: dict[str, CatalogNode] = {}
    order: list[str] = []
    for node in nodes:
        key = node.id.lower()
        if key not in by_id:
            order.append(key)
            by_id[key] = node
            continue
        previous = by_id[key]
        by_id[key] = _prefer_node(previous, node)
    return [by_id[key] for key in order]


def _prefer_node(left: CatalogNode, right: CatalogNode) -> CatalogNode:
    if left.kind in ("book", "index") and right.trainable:
        return right
    if not left.trainable and right.trainable:
        return right
    if _source_priority(right.source) > _source_priority(left.source):
        return right
    return left


def _source_priority(source: str) -> int:
    return {
        "json": 1,
        "nested": 2,
        "root": 3,
    }.get(source, 0)


def _table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _is_topic_row(cells: list[str]) -> bool:
    if len(cells) < 3:
        return False
    first = cells[0].strip()
    if not first or first in ("#", "---") or set(first) <= {"-"}:
        return False
    if first.lower() in ("#", "id", "раздел", "topic id"):
        return False
    return bool(_TOPIC_ID_RE.match(first))


def _parse_index_rows(lines: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    headers: list[str] = []
    for line in lines:
        cells = _table_cells(line)
        if not cells:
            headers = []
            continue
        if set(cells[0]) <= {"-"}:
            continue
        normalized_first = _normalize_header(cells[0])
        if normalized_first in ("topic id", "#", "id"):
            headers = [_normalize_header(cell) for cell in cells]
            continue
        if not headers or len(cells) != len(headers):
            continue
        row = dict(zip(headers, cells, strict=True))
        if _is_topic_row(cells):
            rows.append(row)
    return rows


def _section_heading(line: str) -> str:
    stripped = line.strip()
    if not stripped.startswith("## "):
        return ""
    heading = stripped.lstrip("#").strip()
    if heading.lower().startswith("быстрый"):
        return ""
    return heading


def _first_heading(lines: list[str]) -> str:
    for line in lines[:80]:
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _extract_markdown_links(value: str) -> list[str]:
    return [match.strip() for match in re.findall(r"\[[^\]]+\]\(([^)]+)\)", value)]


def _links_from_material_cells(cells: list[str]) -> list[str]:
    links: list[str] = []
    for cell in cells:
        links.extend(_extract_markdown_links(cell))
    return links


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


def _normalize(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_header(value: str) -> str:
    return _normalize(_strip_markdown(value))


def _first_present(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value:
            return value
    return ""


def _root_node_kind(section: str, links: list[str]) -> str:
    if section.strip().lower() == "книги" and any(_is_index_path(path) for path in links):
        return "book"
    if any(_is_index_path(path) for path in links):
        return "index"
    return "topic"


def _child_kind(parent: CatalogNode) -> str:
    if parent.kind == "book" or parent.section.strip().lower() == "книги":
        return "chapter"
    return "topic"


def _is_trainable(*, kind: str, source_paths: list[str]) -> bool:
    if kind in ("book", "index", "reference"):
        return False
    return any(not _is_index_path(path) for path in source_paths)


def _index_paths(paths: list[str]) -> list[str]:
    return [path for path in paths if _is_index_path(path)]


def _is_index_path(path: str) -> bool:
    return PurePosixPath(path.replace("\\", "/")).name.lower() in _INDEX_FILENAMES


def _child_section(parent: CatalogNode, index_path: str, index_title: str) -> str:
    label = _index_label(index_path, index_title, parent.title)
    return f"{parent.section} / {label}" if parent.section else label


def _index_label(index_path: str, index_title: str, parent_title: str) -> str:
    parts = PurePosixPath(index_path).parts
    if len(parts) >= 2:
        slug = parts[-2].strip()
        if slug:
            return slug.upper() if len(slug) <= 6 else slug.replace("-", " ").title()
    return index_title or parent_title


def _breadcrumb(*parts: str) -> list[str]:
    return [part for part in (part.strip() for part in parts) if part]


def _catalog_path(parts: list[str]) -> str:
    return " > ".join(parts)


def _resolve_index_link(index_path: str, link: str) -> str:
    clean_link = link.strip().replace("\\", "/")
    if not clean_link or re.match(r"^[a-z]+://", clean_link, flags=re.IGNORECASE):
        return ""
    if clean_link.startswith(("/", "#")):
        return ""
    clean_link = clean_link.split("#", 1)[0].strip()
    if not clean_link:
        return ""
    base_dir = PurePosixPath(index_path).parent
    parts: list[str] = []
    for part in PurePosixPath(base_dir, clean_link).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return ""
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _normalize_repo_relpath(path: str) -> str:
    clean = path.strip().replace("\\", "/")
    if not clean or re.match(r"^[a-z]+://", clean, flags=re.IGNORECASE):
        return ""
    if clean.startswith(("/", "#")):
        return ""
    clean = clean.split("#", 1)[0].strip()
    return clean


def _material_fingerprint(repo_path: Path, source_paths: list[str]) -> str:
    if not source_paths:
        return ""
    digest = hashlib.sha256()
    added = False
    for rel in sorted(source_paths):
        path = repo_path / rel
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


def _topic_group(topic_id: str) -> str:
    prefix = re.sub(r"\d+", "", topic_id).lower()
    return prefix or "topic"


def _slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^\w]+", "-", text, flags=re.UNICODE)
    text = text.strip("-")
    return text or "topic"


def _optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")
