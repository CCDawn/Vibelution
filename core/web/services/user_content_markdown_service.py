from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from core.chatroom.store import utc_now_iso


SCHEMA_VERSION = 1
MAX_IMPORT_FILES = 5000
MAX_FILE_BYTES = 2 * 1024 * 1024
MARKDOWN_SUFFIXES = {".md", ".markdown"}
SKIPPED_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__"}
PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SAFE_ID_FRAGMENT = re.compile(r"[^a-zA-Z0-9._-]+")
_WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
_INLINE_TAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_-]+)")
_TASK_OPEN_RE = re.compile(r"^\s*[-*]\s+\[\s\]\s+", re.MULTILINE)
_TASK_DONE_RE = re.compile(r"^\s*[-*]\s+\[[xX]\]\s+", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)


class UserContentMarkdownError(ValueError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def preview_markdown_space_import(source_path: str, *, user_id: str = "default") -> dict[str, Any]:
    normalized_user_id = _safe_id(user_id or "default", default="default")
    resolved_source = _resolve_source_dir(source_path)
    scan = _scan_markdown_tree(resolved_source)
    return {
        "ok": True,
        "schemaVersion": SCHEMA_VERSION,
        "userId": normalized_user_id,
        "source": {
            "path": str(resolved_source),
            "managedRoot": str(_user_content_root(normalized_user_id)),
        },
        "summary": scan["summary"],
        "pages": scan["pages"],
        "ignoredFiles": scan["ignoredFiles"],
        "updatedAt": utc_now_iso(),
    }


def import_markdown_space(
    source_path: str,
    *,
    user_id: str = "default",
    space_name: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    normalized_user_id = _safe_id(user_id or "default", default="default")
    resolved_source = _resolve_source_dir(source_path)
    managed_workspace_root = _workspace_path().resolve()
    if _is_relative_to(resolved_source, managed_workspace_root):
        raise UserContentMarkdownError("source_inside_managed_root")
    scan = _scan_markdown_tree(resolved_source)
    chosen_space_name = str(space_name or "").strip() or resolved_source.name
    space_id = _safe_id(chosen_space_name, default=_safe_id(resolved_source.name, default="space"))
    space_root = _user_content_root(normalized_user_id) / space_id
    pages_root = space_root / "pages"
    index_root = space_root / "index"
    imports_root = space_root / "imports"

    if space_root.exists():
        if not overwrite:
            raise UserContentMarkdownError("space_exists")
        backup_root = space_root.with_name(f"{space_id}.backup.{_timestamp_token()}")
        if backup_root.exists():
            shutil.rmtree(backup_root)
        shutil.move(str(space_root), str(backup_root))

    pages_root.mkdir(parents=True, exist_ok=True)
    index_root.mkdir(parents=True, exist_ok=True)
    imports_root.mkdir(parents=True, exist_ok=True)

    indexed_at = utc_now_iso()
    pages = []
    links = []
    task_rows = []
    all_tags: set[str] = set()

    for row in scan["pageRows"]:
        relative_path = row["relativePath"]
        target_path = pages_root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(row["sourcePath"], target_path)

        page = _page_payload(relative_path, row, indexed_at=indexed_at)
        pages.append(page)
        all_tags.update(page["tags"])
        if page["taskCounts"]["total"] > 0:
            task_rows.append(
                {
                    "pageId": page["pageId"],
                    "title": page["title"],
                    "relativePath": page["relativePath"],
                    "taskCounts": page["taskCounts"],
                }
            )
        for wikilink in page["wikilinks"]:
            links.append(
                {
                    "sourcePageId": page["pageId"],
                    "sourceRelativePath": page["relativePath"],
                    "sourceTitle": page["title"],
                    "targetTitle": wikilink,
                }
            )

    pages.sort(key=lambda item: (item["relativePath"], item["pageId"]))
    links.sort(key=lambda item: (item["sourceRelativePath"], item["targetTitle"]))
    task_rows.sort(key=lambda item: item["relativePath"])

    source_hash = _sha256_for_directory(scan["pageRows"])
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "userId": normalized_user_id,
        "spaceId": space_id,
        "spaceName": chosen_space_name,
        "canonicalPagesRoot": str(pages_root),
        "indexRoot": str(index_root),
        "importsRoot": str(imports_root),
        "managedRoot": str(space_root),
        "pageCount": len(pages),
        "sourceRef": {
            "path": str(resolved_source),
            "sha256": source_hash,
        },
        "summary": scan["summary"],
        "updatedAt": indexed_at,
        "importedAt": indexed_at,
    }
    page_index = {
        "schemaVersion": SCHEMA_VERSION,
        "spaceId": space_id,
        "updatedAt": indexed_at,
        "pages": pages,
    }
    link_index = {
        "schemaVersion": SCHEMA_VERSION,
        "spaceId": space_id,
        "updatedAt": indexed_at,
        "linkCount": len(links),
        "links": links,
    }
    task_index = {
        "schemaVersion": SCHEMA_VERSION,
        "spaceId": space_id,
        "updatedAt": indexed_at,
        "taskPageCount": len(task_rows),
        "tasks": task_rows,
    }
    object_index = {
        "schemaVersion": SCHEMA_VERSION,
        "spaceId": space_id,
        "updatedAt": indexed_at,
        "objects": {
            "tags": sorted(all_tags),
            "pageIds": [page["pageId"] for page in pages],
            "wikilinkCount": len(links),
            "taskCount": sum(int(page["taskCounts"]["total"]) for page in pages),
        },
    }

    _write_json(space_root / "manifest.json", manifest)
    _write_json(index_root / "page_index.json", page_index)
    _write_json(index_root / "link_index.json", link_index)
    _write_json(index_root / "task_index.json", task_index)
    _write_json(index_root / "object_index.json", object_index)
    _append_jsonl(
        imports_root / "import_log.jsonl",
        {
            "schemaVersion": SCHEMA_VERSION,
            "importedAt": indexed_at,
            "userId": normalized_user_id,
            "spaceId": space_id,
            "spaceName": chosen_space_name,
            "sourcePath": str(resolved_source),
            "sourceSha256": source_hash,
            "pageCount": len(pages),
        },
    )

    return {
        "ok": True,
        "schemaVersion": SCHEMA_VERSION,
        "userId": normalized_user_id,
        "space": {
            "spaceId": space_id,
            "spaceName": chosen_space_name,
            "canonicalPagesRoot": str(pages_root),
            "indexRoot": str(index_root),
            "manifestPath": str(space_root / "manifest.json"),
        },
        "summary": {
            **scan["summary"],
            "importedPageCount": len(pages),
        },
        "updatedAt": indexed_at,
    }


def list_markdown_spaces(*, user_id: str = "default") -> dict[str, Any]:
    normalized_user_id = _safe_id(user_id or "default", default="default")
    spaces = []
    for manifest in _iter_active_space_manifests(normalized_user_id):
        spaces.append(_space_summary(manifest))
    return {
        "ok": True,
        "schemaVersion": SCHEMA_VERSION,
        "userId": normalized_user_id,
        "spaces": spaces,
        "summary": {"spaceCount": len(spaces)},
        "updatedAt": utc_now_iso(),
    }


def list_markdown_space_pages(space_id: str, *, user_id: str = "default", query: str = "", tag: str = "") -> dict[str, Any]:
    manifest, page_index = _load_space(normalized_user_id=_safe_id(user_id or "default", default="default"), space_id=space_id)
    normalized_query = str(query or "").strip().lower()
    normalized_tag = str(tag or "").strip().lower()
    pages = []
    for page in list(page_index.get("pages") or []):
        if normalized_tag and normalized_tag not in {str(item).lower() for item in list(page.get("tags") or [])}:
            continue
        search_basis = "\n".join([str(page.get("title") or ""), str(page.get("relativePath") or ""), " ".join(page.get("wikilinks") or [])]).lower()
        if normalized_query and normalized_query not in search_basis:
            continue
        pages.append(page)
    return {
        "ok": True,
        "schemaVersion": SCHEMA_VERSION,
        "space": _space_summary(manifest),
        "pages": pages,
        "summary": {"pageCount": len(pages)},
        "updatedAt": utc_now_iso(),
    }


def get_markdown_space_page(space_id: str, page_id: str, *, user_id: str = "default") -> dict[str, Any]:
    normalized_user_id = _safe_id(user_id or "default", default="default")
    manifest, page_index = _load_space(normalized_user_id=normalized_user_id, space_id=space_id)
    for page in list(page_index.get("pages") or []):
        if str(page.get("pageId") or "") != str(page_id or "").strip():
            continue
        page_path = Path(str(manifest.get("canonicalPagesRoot") or "")) / str(page.get("relativePath") or "")
        return {
            "ok": True,
            "schemaVersion": SCHEMA_VERSION,
            "space": _space_summary(manifest),
            "page": {
                **page,
                "content": _read_text(page_path),
            },
            "updatedAt": utc_now_iso(),
        }
    raise UserContentMarkdownError("page_not_found")


def search_user_markdown_spaces(
    *,
    user_id: str = "default",
    query: str = "",
    space_id: str = "",
    limit: int = 10,
    max_excerpt_chars: int = 900,
) -> dict[str, Any]:
    normalized_user_id = _safe_id(user_id or "default", default="default")
    bounded_limit = max(1, min(100, int(limit or 10)))
    bounded_excerpt = max(120, min(4000, int(max_excerpt_chars or 900)))
    normalized_query = str(query or "").strip()
    terms = [item for item in re.split(r"\s+", normalized_query.lower()) if item]
    results = []

    for manifest in _iter_active_space_manifests(normalized_user_id):
        current_space_id = str(manifest.get("spaceId") or "").strip()
        if space_id and current_space_id != str(space_id).strip():
            continue
        page_index = _read_json(Path(str(manifest.get("indexRoot") or "")) / "page_index.json")
        for page in list(page_index.get("pages") or []):
            page_id_value = str(page.get("pageId") or "").strip()
            page_path = Path(str(manifest.get("canonicalPagesRoot") or "")) / str(page.get("relativePath") or "")
            content = _read_text(page_path)
            haystack = "\n".join(
                [
                    str(page.get("title") or ""),
                    str(page.get("relativePath") or ""),
                    " ".join(str(item) for item in list(page.get("tags") or [])),
                    content,
                ]
            )
            score = _score_literal_match(haystack, terms)
            if terms and score <= 0:
                continue
            match_reason = "literal_query_match" if terms else "space_browse"
            excerpt = _excerpt_for_query(content or haystack, terms, max_chars=bounded_excerpt)
            results.append(
                (
                    score,
                    str(page.get("updatedAt") or ""),
                    {
                        "resultId": f"user-md-{current_space_id}-{page_id_value}",
                        "resultType": "user_markdown_page",
                        "sourceDomain": "user_content",
                        "title": page["title"],
                        "excerpt": excerpt,
                        "score": score,
                        "rank": 0,
                        "userId": normalized_user_id,
                        "spaceId": current_space_id,
                        "spaceName": str(manifest.get("spaceName") or "").strip(),
                        "pageId": page_id_value,
                        "pageRelativePath": page["relativePath"],
                        "searchBackend": "user_markdown_literal",
                        "matchReason": match_reason,
                        "metadata": {"tags": page["tags"], "taskCounts": page["taskCounts"], "updatedAt": page["updatedAt"]},
                        "citation": {"sourceDomain": "user_content", "spaceId": current_space_id, "pageId": page_id_value, "pageRelativePath": page["relativePath"]},
                    },
                )
            )

    results.sort(key=lambda item: (item[0], item[1], item[2]["title"]), reverse=True)
    selected = []
    for rank, (_, _, result) in enumerate(results[:bounded_limit], start=1):
        next_result = dict(result)
        next_result["rank"] = rank
        selected.append(next_result)

    return {
        "ok": True,
        "schemaVersion": SCHEMA_VERSION,
        "userId": normalized_user_id,
        "query": normalized_query,
        "results": selected,
        "summary": {"resultCount": len(selected)},
        "updatedAt": utc_now_iso(),
    }


def _user_content_root(user_id: str = "default") -> Path:
    normalized_user_id = _safe_id(user_id or "default", default="default")
    return _workspace_path("users", normalized_user_id, "markdown_spaces")


def _workspace_path(*parts: str) -> Path:
    try:
        from core.infrastructure import developer_sandbox

        return Path(developer_sandbox.route_workspace_path(PROJECT_ROOT, "user_content", *parts, intent="state", seed=True))
    except Exception:
        return Path(PROJECT_ROOT) / "workspace" / "user_content" / Path(*parts)


def _resolve_source_dir(source_path: str) -> Path:
    resolved = Path(source_path).expanduser().resolve()
    if not resolved.exists():
        raise UserContentMarkdownError("source_path_missing")
    if not resolved.is_dir():
        raise UserContentMarkdownError("source_not_directory")
    return resolved


def _scan_markdown_tree(source_root: Path) -> dict[str, Any]:
    page_rows = []
    ignored_files = []
    seen_count = 0

    for path in sorted(source_root.rglob("*")):
        if any(part in SKIPPED_DIRS for part in path.parts[len(source_root.parts) :]):
            continue
        if path.is_dir():
            continue
        relative_path = path.relative_to(source_root).as_posix()
        suffix = path.suffix.lower()
        if suffix not in MARKDOWN_SUFFIXES:
            ignored_files.append({"relativePath": relative_path, "reason": "non_markdown"})
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            ignored_files.append({"relativePath": relative_path, "reason": "file_too_large"})
            continue
        seen_count += 1
        if seen_count > MAX_IMPORT_FILES:
            raise UserContentMarkdownError("max_import_files_exceeded")
        content = _read_text(path)
        metadata = _parse_markdown_metadata(content)
        page_rows.append(
            {
                "sourcePath": path,
                "relativePath": relative_path,
                "title": metadata["title"] or path.stem,
                "tags": metadata["tags"],
                "wikilinks": metadata["wikilinks"],
                "openCount": metadata["openCount"],
                "doneCount": metadata["doneCount"],
                "content": content,
            }
        )

    summary = {
        "markdownFileCount": len(page_rows),
        "ignoredFileCount": len(ignored_files),
        "wikilinkCount": sum(len(row["wikilinks"]) for row in page_rows),
        "taskCount": sum(int(row["openCount"]) + int(row["doneCount"]) for row in page_rows),
        "tagCount": len({tag for row in page_rows for tag in row["tags"]}),
    }
    pages = [
        {
            "relativePath": row["relativePath"],
            "title": row["title"],
            "tags": row["tags"],
            "wikilinkCount": len(row["wikilinks"]),
            "taskCount": int(row["openCount"]) + int(row["doneCount"]),
        }
        for row in page_rows
    ]
    return {
        "summary": summary,
        "pageRows": page_rows,
        "pages": pages,
        "ignoredFiles": ignored_files,
    }


def _parse_markdown_metadata(content: str) -> dict[str, Any]:
    text = str(content or "")
    tags = set(_INLINE_TAG_RE.findall(text))
    frontmatter_match = _FRONTMATTER_RE.match(text)
    body = text
    if frontmatter_match:
        body = text[frontmatter_match.end() :]
        tags.update(_parse_frontmatter_tags(frontmatter_match.group(1)))
    title = ""
    for line in body.splitlines():
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title:
                break
    wikilinks = [item.strip() for item in _WIKILINK_RE.findall(body) if item.strip()]
    open_count = len(_TASK_OPEN_RE.findall(body))
    done_count = len(_TASK_DONE_RE.findall(body))
    return {
        "title": title,
        "tags": sorted(tags),
        "wikilinks": wikilinks,
        "openCount": open_count,
        "doneCount": done_count,
    }


def _parse_frontmatter_tags(frontmatter: str) -> list[str]:
    tags = []
    for raw_line in str(frontmatter or "").splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("tags:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value.startswith("[") and value.endswith("]"):
            tags.extend(item.strip().strip("'\"") for item in value[1:-1].split(","))
        elif value:
            tags.append(value.strip("'\""))
    return [item for item in tags if item]


def _page_payload(relative_path: str, row: dict[str, Any], *, indexed_at: str) -> dict[str, Any]:
    open_count = int(row["openCount"])
    done_count = int(row["doneCount"])
    total_count = open_count + done_count
    text = str(row["content"] or "")
    encoded = text.encode("utf-8")
    return {
        "pageId": _page_id_for_relative_path(relative_path),
        "relativePath": relative_path,
        "title": row["title"],
        "tags": row["tags"],
        "wikilinks": row["wikilinks"],
        "taskCounts": {"open": open_count, "done": done_count, "total": total_count},
        "contentHash": "sha256:" + hashlib.sha256(encoded).hexdigest(),
        "byteSize": len(encoded),
        "updatedAt": indexed_at,
    }


def _page_id_for_relative_path(relative_path: str) -> str:
    normalized_path = Path(relative_path).as_posix().strip("/")
    cleaned = _safe_id(Path(normalized_path).with_suffix("").as_posix().replace("/", "-"), default="page")
    path_hash = hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()[:12]
    return f"page-{cleaned}-{path_hash}"


def _safe_id(value: Any, *, default: str) -> str:
    text = str(value or "").strip()
    cleaned = _SAFE_ID_FRAGMENT.sub("-", text).strip(".-_").lower()
    return cleaned or default


def _timestamp_token() -> str:
    return utc_now_iso().replace(":", "").replace("-", "").replace(".", "").replace("Z", "Z")


def _sha256_for_directory(page_rows: list[dict[str, Any]]) -> str:
    payload = [
        {
            "relativePath": row["relativePath"],
            "contentHash": hashlib.sha256(str(row["content"] or "").encode("utf-8")).hexdigest(),
        }
        for row in page_rows
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _space_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "spaceId": str(manifest.get("spaceId") or "").strip(),
        "spaceName": str(manifest.get("spaceName") or "").strip(),
        "canonicalPagesRoot": str(manifest.get("canonicalPagesRoot") or "").strip(),
        "indexRoot": str(manifest.get("indexRoot") or "").strip(),
        "pageCount": int(manifest.get("pageCount") or 0),
        "updatedAt": str(manifest.get("updatedAt") or "").strip(),
    }


def _iter_active_space_manifests(normalized_user_id: str) -> list[dict[str, Any]]:
    manifests = []
    root = _user_content_root(normalized_user_id)
    if not root.exists():
        return manifests
    for space_root in sorted(path for path in root.iterdir() if path.is_dir()):
        manifest = _read_json(space_root / "manifest.json")
        if not manifest:
            continue
        manifest_space_id = str(manifest.get("spaceId") or "").strip()
        if not manifest_space_id or space_root.name != manifest_space_id:
            continue
        manifests.append(manifest)
    return manifests


def _load_space(*, normalized_user_id: str, space_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_space_id = _safe_id(space_id or "", default="")
    if not normalized_space_id:
        raise UserContentMarkdownError("space_not_found")
    space_root = _user_content_root(normalized_user_id) / normalized_space_id
    manifest = _read_json(space_root / "manifest.json")
    if not manifest:
        raise UserContentMarkdownError("space_not_found")
    page_index = _read_json(Path(str(manifest.get("indexRoot") or "")) / "page_index.json")
    return manifest, page_index


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def _score_literal_match(haystack: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    lowered = haystack.lower()
    score = 0.0
    for term in terms:
        count = lowered.count(term)
        if count <= 0:
            return 0.0
        score += float(count)
    return score


def _excerpt_for_query(text: str, terms: list[str], *, max_chars: int) -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""
    if not terms:
        return normalized[:max_chars]
    lowered = normalized.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    if not positions:
        return normalized[:max_chars]
    start = max(0, min(positions) - 40)
    excerpt = normalized[start : start + max_chars]
    return excerpt.strip()
