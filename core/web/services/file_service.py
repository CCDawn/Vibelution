"""Workspace file tree and preview helpers."""

from __future__ import annotations

import time
from pathlib import Path, PurePosixPath, PureWindowsPath
from threading import Lock
from typing import Any

from core.web.services.runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXCLUDED_DIR_NAMES = {
    ".claude",
    ".codex",
    ".codex-logs",
    ".codex-temp",
    ".git",
    ".pytest_cache",
    ".runtime",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "workspace",
    "log_info",
    "logs",
    "backups",
}
MAX_TREE_DEPTH = 4
MAX_TREE_NODES = 1_500
MAX_TEXT_CHARS = 200_000
TREE_CACHE_TTL_SECONDS = 8.0
TREE_SLOW_THRESHOLD_MS = 250.0

_TREE_CACHE_LOCK = Lock()
_TREE_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "nodes": None,
    "stats": None,
}

LANGUAGE_BY_SUFFIX = {
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".mjs": "javascript",
    ".py": "python",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".yml": "yaml",
    ".yaml": "yaml",
}


def build_file_tree() -> list[dict]:
    """Build a trimmed project tree for the right-hand files panel."""

    now = time.monotonic()
    with _TREE_CACHE_LOCK:
        cached_nodes = _TREE_CACHE.get("nodes")
        if cached_nodes is not None and now < float(_TREE_CACHE.get("expires_at") or 0.0):
            return cached_nodes

    started = time.perf_counter()
    stats: dict[str, Any] = {
        "nodeCount": 0,
        "directoryCount": 0,
        "fileCount": 0,
        "skippedDirectoryCount": 0,
        "truncated": False,
        "cacheHit": False,
    }
    nodes: list[dict] = []
    for child in sorted(PROJECT_ROOT.iterdir(), key=_sort_key):
        if _node_budget_exhausted(stats):
            stats["truncated"] = True
            break
        node = _build_node(child, depth=0, stats=stats)
        if node is not None:
            nodes.append(node)
    elapsed_ms = (time.perf_counter() - started) * 1000
    with _TREE_CACHE_LOCK:
        _TREE_CACHE["nodes"] = nodes
        _TREE_CACHE["stats"] = dict(stats)
        _TREE_CACHE["expires_at"] = time.monotonic() + TREE_CACHE_TTL_SECONDS
    _record_file_tree_event("file.tree.loaded", stats, elapsed_ms=elapsed_ms)
    return nodes


def read_text_file(relative_path: str) -> dict:
    """Read a project file for the preview surface."""

    file_path = _resolve_project_path(relative_path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {relative_path}")
    raw = file_path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("Binary files are not supported in the preview yet")
    content = raw.decode("utf-8", errors="replace")
    truncated = len(content) > MAX_TEXT_CHARS
    if truncated:
        content = content[:MAX_TEXT_CHARS] + "\n\n... preview truncated ..."
    return {
        "path": relative_path,
        "language": LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text"),
        "content": content,
        "truncated": truncated,
    }


def _build_node(path: Path, depth: int, *, stats: dict[str, Any]) -> dict | None:
    if _is_excluded_dir(path):
        if path.is_dir():
            stats["skippedDirectoryCount"] += 1
        return None

    if _node_budget_exhausted(stats):
        stats["truncated"] = True
        return None

    relative_path = path.relative_to(PROJECT_ROOT).as_posix()
    stats["nodeCount"] += 1
    if path.is_dir():
        stats["directoryCount"] += 1
        if depth >= MAX_TREE_DEPTH:
            return {
                "name": path.name,
                "path": relative_path,
                "type": "directory",
                "children": [],
            }
        children = []
        try:
            child_paths = sorted(path.iterdir(), key=_sort_key)
        except OSError:
            stats["skippedDirectoryCount"] += 1
            child_paths = []
        for child in child_paths:
            if _node_budget_exhausted(stats):
                stats["truncated"] = True
                break
            node = _build_node(child, depth + 1, stats=stats)
            if node is not None:
                children.append(node)
        return {
            "name": path.name,
            "path": relative_path,
            "type": "directory",
            "children": children,
        }

    stats["fileCount"] += 1
    return {
        "name": path.name,
        "path": relative_path,
        "type": "file",
    }


def _resolve_project_path(relative_path: str) -> Path:
    raw_path = str(relative_path or "").strip()
    windows_path = PureWindowsPath(raw_path)
    posix_path = PurePosixPath(raw_path.replace("\\", "/"))
    if (
        not raw_path
        or windows_path.drive
        or windows_path.root
        or posix_path.is_absolute()
        or any(part == ".." for part in posix_path.parts)
    ):
        raise ValueError("Path must stay inside the project root")
    candidate = (PROJECT_ROOT / relative_path).resolve()
    project_root = PROJECT_ROOT.resolve()
    try:
        candidate.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("Path must stay inside the project root") from exc
    return candidate


def _is_excluded_dir(path: Path) -> bool:
    return path.name in EXCLUDED_DIR_NAMES or path.name.startswith(".pytest-run-")


def _sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.is_dir() else 1, path.name.lower())


def _node_budget_exhausted(stats: dict[str, Any]) -> bool:
    return int(stats.get("nodeCount") or 0) >= MAX_TREE_NODES


def _record_file_tree_event(event_code: str, stats: dict[str, Any], *, elapsed_ms: float) -> None:
    should_record = bool(stats.get("truncated")) or elapsed_ms >= TREE_SLOW_THRESHOLD_MS
    if event_code == "file.tree.cache_hit" and not should_record:
        return
    try:
        record_runtime_scene_event(
            "file_service",
            "files",
            event_code,
            message="Project file tree loaded.",
            level="warning" if elapsed_ms >= TREE_SLOW_THRESHOLD_MS or stats.get("truncated") else "info",
            outcome="truncated" if stats.get("truncated") else "loaded",
            fields={
                "elapsedMs": round(elapsed_ms, 2),
                "nodeCount": int(stats.get("nodeCount") or 0),
                "directoryCount": int(stats.get("directoryCount") or 0),
                "fileCount": int(stats.get("fileCount") or 0),
                "skippedDirectoryCount": int(stats.get("skippedDirectoryCount") or 0),
                "truncated": bool(stats.get("truncated")),
                "cacheHit": bool(stats.get("cacheHit")),
                "maxTreeDepth": MAX_TREE_DEPTH,
                "maxTreeNodes": MAX_TREE_NODES,
            },
        )
    except Exception:
        return
