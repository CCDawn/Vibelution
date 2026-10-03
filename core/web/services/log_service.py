"""Log tree, preview, and guarded cleanup helpers."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import Any, Callable, NamedTuple

from core.web.services.log_diagnostics import analyze_log_content
from vibelution_storage import (
    resolve_project_logs_home,
    resolve_project_runtime_home,
    resolve_project_workspace_home,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAX_TREE_DEPTH = 6
MAX_TEXT_CHARS = 200_000
MAX_ROOT_SUMMARY_ITEMS = 20_000
ROOT_SUMMARY_CACHE_TTL_SECONDS = 30.0

# runtime_logs is the logs/ root itself, but the two dedicated sub-roots that
# live inside it (runtime_scenes, conversations) are summarized on their own
# and must not be double counted under runtime_logs.
RUNTIME_LOGS_EXCLUDED_TOP_DIRS = frozenset({"runtime_scenes", "conversations"})

# Module-level summary cache keyed by the tuple of resolved root paths, so a
# different PROJECT_ROOT (for example under pytest) never reuses another
# project's data. Concurrency: one lock, compute-then-swap. A cold compute
# holds the lock (single-flight: concurrent callers wait once and reuse the
# fresh result); the only worst case is serialized recomputes, never a stale
# read beyond the TTL.
_root_summary_cache_lock = threading.Lock()
_root_summary_cache: dict[tuple[str, ...], tuple[float, dict[str, dict]]] = {}

LOG_ROOTS = (
    {"id": "runtime_scenes", "path": "logs/runtime_scenes"},
    {"id": "launcher_runtime", "path": ".runtime/launcher"},
    {"id": "runtime_logs", "path": "logs"},
    {"id": "workspace_logs", "path": "workspace/logs"},
    {"id": "conversation_logs", "path": "logs/conversations"},
)

LANGUAGE_BY_SUFFIX = {
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".json": "json",
    ".jsonl": "json",
    ".log": "text",
    ".md": "markdown",
    ".ps1": "powershell",
    ".py": "python",
    ".text": "text",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
}

ROOT_GUIDES = {
    "runtime_scenes": {
        "userGuide": "优先按一次运行查看统一时间线，再打开关联原始日志。",
        "agentGuide": "先读 runtime scene timeline；需要上下文时再追 rawRefs 指向的原始日志。",
    },
    "launcher_runtime": {
        "userGuide": "Launcher 进程 stdout/stderr、启动控制与前端构建日志。",
        "agentGuide": "排查启动、关闭、端口和后台服务时，只打开 firstRead.evidencePaths 里点名的 backend.stdout.log / backend.stderr.log / launcher-control.log；带 warning 的文件不要整篇读。",
    },
    "runtime_logs": {
        "userGuide": "项目 logs/ 根下的普通运行日志（不含 runtime_scenes 包与 conversations）。",
        "agentGuide": "仅用于 logs/ 根目录的普通日志；Launcher 即时输出在 launcher_runtime，诊断现场在 runtime_scenes。",
    },
    "workspace_logs": {
        "userGuide": "适合回看工作区内生成的转录、轮次和辅助运行记录。",
        "agentGuide": "用于追踪工作流产物、转录和工具辅助脚本输出，通常作为 conversation log 的补充证据。",
    },
    "conversation_logs": {
        "userGuide": "适合回看 agent 会话、工具调用、子 agent 输出和轮次结论。",
        "agentGuide": "排查 agent 漂移、重复工具、停止/继续、委派和验证行为时优先读取 conversation_*.jsonl。",
    },
}


def list_log_roots() -> list[dict]:
    """List available log roots for the web workbench."""

    summaries = _get_log_root_summaries()
    roots: list[dict] = []
    for root in LOG_ROOTS:
        root_id = root["id"]
        root_path = _resolve_log_root(root_id)
        roots.append(
            {
                "id": root_id,
                "path": root["path"],
                "exists": root_path.exists() and root_path.is_dir(),
                "summary": summaries.get(root_id) or _summarize_log_root(root_id, root_path),
            }
        )
    return roots


def build_log_tree(root_id: str) -> dict:
    """Build a trimmed tree for a single log root."""

    root_meta = _root_meta(root_id)
    root_path = _resolve_log_root(root_id)
    if not root_path.exists() or not root_path.is_dir():
        return {
            "root": root_meta,
            "nodes": [],
        }

    nodes: list[dict] = []
    for child in sorted(root_path.iterdir(), key=_sort_key):
        if _should_skip_child(root_id, child, root_path):
            continue
        node = _build_node(child, root_path=root_path, depth=0)
        if node is not None:
            nodes.append(node)
    return {
        "root": root_meta,
        "nodes": nodes,
    }


def read_log_file(root_id: str, relative_path: str) -> dict:
    """Read a log file preview for the selected root."""

    root_meta = _root_meta(root_id)
    _assert_allowed_runtime_log_path(root_id, relative_path)
    file_path = _resolve_log_path(root_id, relative_path)
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
        "rootId": root_meta["id"],
        "rootPath": root_meta["path"],
        "relativePath": relative_path,
        "path": f"{root_meta['path']}/{relative_path}".replace("//", "/"),
        "language": LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text"),
        "content": content,
        "truncated": truncated,
        "diagnostics": _analyze_log_content(root_meta["id"], relative_path, content),
    }


def clear_log_file(root_id: str, relative_path: str) -> dict:
    """Empty one log file while keeping it in place."""

    _assert_allowed_runtime_log_path(root_id, relative_path)
    file_path = _resolve_log_path(root_id, relative_path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {relative_path}")
    file_path.write_bytes(b"")
    _invalidate_log_root_summary_cache()
    return read_log_file(root_id, relative_path)


def delete_log_files(root_id: str, relative_paths: list[str]) -> dict:
    """Delete a selected list of files from one allowed log root."""

    root_meta = _root_meta(root_id)
    normalized_paths = _normalize_relative_paths(relative_paths)
    if not normalized_paths:
        raise ValueError("Select at least one log file to delete")

    deleted_paths: list[str] = []
    missing_paths: list[str] = []
    for relative_path in normalized_paths:
        _assert_allowed_runtime_log_path(root_id, relative_path)
        file_path = _resolve_log_path(root_id, relative_path)
        if not file_path.exists():
            missing_paths.append(relative_path)
            continue
        if not file_path.is_file():
            raise ValueError("Only log files can be deleted")
        file_path.unlink()
        deleted_paths.append(relative_path)

    _invalidate_log_root_summary_cache()
    return {
        "rootId": root_meta["id"],
        "rootPath": root_meta["path"],
        "deletedPaths": deleted_paths,
        "missingPaths": missing_paths,
        "deletedCount": len(deleted_paths),
    }


def _build_node(path: Path, *, root_path: Path, depth: int) -> dict | None:
    relative_path = path.relative_to(root_path).as_posix()
    if path.is_dir():
        if depth >= MAX_TREE_DEPTH:
            return {
                "name": path.name,
                "path": relative_path,
                "type": "directory",
                "children": [],
            }
        children = []
        for child in sorted(path.iterdir(), key=_sort_key):
            node = _build_node(child, root_path=root_path, depth=depth + 1)
            if node is not None:
                children.append(node)
        return {
            "name": path.name,
            "path": relative_path,
            "type": "directory",
            "children": children,
        }

    return {
        "name": path.name,
        "path": relative_path,
        "type": "file",
    }


def _root_meta(root_id: str) -> dict:
    for root in LOG_ROOTS:
        if root["id"] == root_id:
            root_path = _resolve_log_root(root_id)
            return {
                "id": root["id"],
                "path": root["path"],
                "exists": root_path.exists() and root_path.is_dir(),
                "summary": _summarize_log_root(root_id, root_path),
            }
    raise ValueError(f"Unknown log root: {root_id}")


def _summarize_log_root(root_id: str, root_path: Path) -> dict:
    if not root_path.exists() or not root_path.is_dir():
        return _missing_log_root_summary(root_id)
    skip = _entry_is_excluded_from_runtime_logs if root_id == "runtime_logs" else None
    return _summary_from_entries(root_id, _walk_summary_entries(root_path, skip=skip))


def _analyze_log_content(root_id: str, relative_path: str, content: str) -> dict[str, Any]:
    return analyze_log_content(
        anchor=f"{root_id}/{relative_path}",
        content=content,
        normal_summary="未发现明显错误或警告，可先把它作为正常路径或补充证据。",
        empty_summary="当前日志为空，暂时不能作为诊断证据。",
        error_summary_prefix="发现 ",
        warning_summary_prefix="发现 ",
        error_next_step="打开错误筛选，围绕第 {line} 行向前找触发动作、向后找失败结果。",
        warning_next_step="打开警告筛选，确认第 {line} 行附近是否出现重试、超时或被阻断动作。",
        structured_next_step="按结构化事件类型查看会话阶段，再与相邻 debug/runtime 日志交叉验证。",
        fallback_next_step="如当前问题仍未解释，切到相邻日志分组查找同一时间段的运行现场或会话记录。",
    )


class _WalkEntry(NamedTuple):
    """One visited filesystem entry with its single cached stat result."""

    path: Path
    relative: str
    stat_result: os.stat_result | None
    is_dir: bool


def _entry_is_excluded_from_runtime_logs(relative: str) -> bool:
    return relative.split("/", 1)[0] in RUNTIME_LOGS_EXCLUDED_TOP_DIRS


def _describe_children(dir_path: Path, prefix: str) -> list[_WalkEntry]:
    """List one directory with exactly one stat per child.

    The cached stat later drives sorting, counting, and the recursion
    decision, replacing the historical pattern of stat() + is_dir() +
    is_file() + sort-time is_dir() (about five stat calls per entry on
    Windows, where stat is a slow syscall).
    """
    children: list[_WalkEntry] = []
    # On Windows scandir retains attributes from directory enumeration. Path.stat
    # discards them and opens every child again, dominating a cold summary read.
    with os.scandir(dir_path) as entries:
        for entry in entries:
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            try:
                stat_result = entry.stat()
                is_dir = S_ISDIR(stat_result.st_mode)
            except OSError:
                stat_result = None
                is_dir = False
            children.append(
                _WalkEntry(path=Path(entry.path), relative=relative, stat_result=stat_result, is_dir=is_dir)
            )
    return children


def _entry_sort_key(entry: _WalkEntry) -> tuple[int, str]:
    return (0 if entry.is_dir else 1, entry.path.name.lower())


def _walk_summary_entries(
    root_path: Path,
    skip: Callable[[str], bool] | None = None,
) -> list[_WalkEntry]:
    """Pre-order walk (dirs first, name-sorted per level) with one stat per entry.

    Mirrors the historical ``_iter_log_children`` traversal order, so summary
    numbers (including the item cap and latest-path tie-breaking) stay
    identical to the previous implementation.
    """
    entries: list[_WalkEntry] = []
    stack = sorted(_describe_children(root_path, ""), key=_entry_sort_key, reverse=True)
    while stack:
        entry = stack.pop()
        if skip is not None and skip(entry.relative):
            continue
        entries.append(entry)
        if entry.is_dir:
            try:
                stack.extend(
                    sorted(
                        _describe_children(entry.path, entry.relative),
                        key=_entry_sort_key,
                        reverse=True,
                    )
                )
            except OSError:
                continue
    return entries


def _missing_log_root_summary(root_id: str) -> dict:
    guide = ROOT_GUIDES.get(root_id, {})
    return {
        "health": "missing",
        "fileCount": 0,
        "directoryCount": 0,
        "sizeBytes": 0,
        "lastModifiedAt": "",
        "latestPath": "",
        "userGuide": guide.get("userGuide", ""),
        "agentGuide": guide.get("agentGuide", ""),
    }


def _summary_from_entries(root_id: str, entries: list[_WalkEntry]) -> dict:
    guide = ROOT_GUIDES.get(root_id, {})
    file_count = 0
    directory_count = 0
    size_bytes = 0
    latest_path = ""
    latest_mtime = 0.0
    scanned = 0
    for entry in entries:
        if scanned >= MAX_ROOT_SUMMARY_ITEMS:
            break
        scanned += 1
        stat_result = entry.stat_result
        if stat_result is None:
            continue
        if entry.is_dir:
            directory_count += 1
            continue
        if not S_ISREG(stat_result.st_mode):
            continue
        file_count += 1
        size_bytes += int(stat_result.st_size)
        if stat_result.st_mtime >= latest_mtime:
            latest_mtime = stat_result.st_mtime
            latest_path = entry.relative

    return {
        "health": "empty" if file_count == 0 and directory_count == 0 else "active",
        "fileCount": file_count,
        "directoryCount": directory_count,
        "sizeBytes": size_bytes,
        "lastModifiedAt": _format_mtime(latest_mtime),
        "latestPath": latest_path,
        "userGuide": guide.get("userGuide", ""),
        "agentGuide": guide.get("agentGuide", ""),
    }


def _collect_log_root_summaries() -> dict[str, dict]:
    """Summarize every log root, walking each filesystem tree at most once.

    runtime_scenes and conversation_logs are sub-trees of the logs root, and
    runtime_logs is the logs root minus those two sub-trees. One walk of the
    logs root is partitioned three ways instead of walking overlapping roots
    separately. A pre-order traversal restricted to a sub-tree equals a
    standalone pre-order walk of that sub-tree, so each partition keeps the
    exact order (and therefore the exact summary) of ``_summarize_log_root``.
    """
    summaries: dict[str, dict] = {}
    for root_id in ("launcher_runtime", "workspace_logs"):
        summaries[root_id] = _summarize_log_root(root_id, _resolve_log_root(root_id))

    logs_root = _resolve_log_root("runtime_logs")
    logs_entries: list[_WalkEntry] | None = None
    if logs_root.exists() and logs_root.is_dir():
        logs_entries = _walk_summary_entries(logs_root)

    sub_root_top_dirs = {"runtime_scenes": "runtime_scenes", "conversation_logs": "conversations"}
    for root_id in ("runtime_scenes", "runtime_logs", "conversation_logs"):
        root_path = _resolve_log_root(root_id)
        if logs_entries is None or not root_path.exists() or not root_path.is_dir():
            summaries[root_id] = _summarize_log_root(root_id, root_path)
            continue
        if root_id == "runtime_logs":
            entries = [
                entry
                for entry in logs_entries
                if not _entry_is_excluded_from_runtime_logs(entry.relative)
            ]
        else:
            prefix = f"{sub_root_top_dirs[root_id]}/"
            entries = [
                _WalkEntry(
                    path=entry.path,
                    relative=entry.relative[len(prefix):],
                    stat_result=entry.stat_result,
                    is_dir=entry.is_dir,
                )
                for entry in logs_entries
                if entry.relative.startswith(prefix)
            ]
        summaries[root_id] = _summary_from_entries(root_id, entries)
    return summaries


def _log_root_cache_key() -> tuple[str, ...]:
    return tuple(str(_resolve_log_root(root["id"])) for root in LOG_ROOTS)


def _get_log_root_summaries() -> dict[str, dict]:
    """Return cached log-root summaries, recomputing after the TTL expires."""
    cache_key = _log_root_cache_key()
    now = time.monotonic()
    with _root_summary_cache_lock:
        cached = _root_summary_cache.get(cache_key)
        if cached is not None and now < cached[0]:
            return cached[1]
        summaries = _collect_log_root_summaries()
        _root_summary_cache.clear()
        _root_summary_cache[cache_key] = (now + ROOT_SUMMARY_CACHE_TTL_SECONDS, summaries)
        return summaries


def _invalidate_log_root_summary_cache() -> None:
    with _root_summary_cache_lock:
        _root_summary_cache.clear()


def _format_mtime(value: float) -> str:
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_log_root(root_id: str) -> Path:
    logs_root = resolve_project_logs_home(PROJECT_ROOT).resolve()
    resolved_roots = {
        "runtime_scenes": logs_root / "runtime_scenes",
        "launcher_runtime": resolve_project_runtime_home(PROJECT_ROOT) / "launcher",
        "runtime_logs": logs_root,
        "workspace_logs": resolve_project_workspace_home(PROJECT_ROOT) / "logs",
        "conversation_logs": logs_root / "conversations",
    }
    if root_id in resolved_roots:
        return resolved_roots[root_id].resolve()
    raise ValueError(f"Unknown log root: {root_id}")


def _resolve_log_path(root_id: str, relative_path: str) -> Path:
    root_path = _resolve_log_root(root_id)
    candidate = (root_path / relative_path).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("Path must stay inside the selected log root") from exc
    return candidate


def _normalize_relative_paths(items: list[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    for raw in items:
        value = str(raw or "").strip().replace("\\", "/")
        if not value or value in normalized:
            continue
        normalized.append(value)
    return normalized


def _sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.is_dir() else 1, path.name.lower())


def _should_skip_child(root_id: str, child: Path, root_path: Path) -> bool:
    if root_id != "runtime_logs":
        return False
    try:
        relative = child.relative_to(root_path).as_posix()
    except ValueError:
        return False
    return _entry_is_excluded_from_runtime_logs(relative)


def _assert_allowed_runtime_log_path(root_id: str, relative_path: str) -> None:
    if root_id != "runtime_logs":
        return
    normalized = str(relative_path or "").strip().replace("\\", "/").lstrip("/")
    while normalized.startswith("./"):
        normalized = normalized[2:].lstrip("/")
    if normalized == "runtime_scenes" or normalized.startswith("runtime_scenes/"):
        raise ValueError("Runtime scene bundles must be managed from the runtime scenes surface")
    if normalized == "conversations" or normalized.startswith("conversations/"):
        raise ValueError("Conversation logs must be managed from the conversation logs surface")
