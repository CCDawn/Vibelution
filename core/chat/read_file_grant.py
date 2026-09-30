"""Session-scoped full-read grant for existing-file writes.

A bound agent turn may overwrite, edit, or delete an existing file only after
this session recorded a full-file read whose mtime, size, and content hash
still match the bytes on disk. Partial reads do not count. Creating a missing
file does not need a prior read. Shell commands are not a grant source.

The record is append-only under the session file history. Loading it does not
stat the disk, so a later user save is not treated as an agent read. Outside a
bound turn the check is skipped, so direct callers keep their current behavior.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from core.chat import file_change_ledger as ledger

_GRANT_NAME = "read_grants.jsonl"
_SOURCES = {"read", "write"}

FULL_READ_REQUIRED = (
    "写入前需要这次会话里有一次从头到尾的完整读取"
    "（read_file，offset 为 0，max_lines 为 0）。"
    "当前没有匹配的完整读取记录，或文件的修改时间、大小或内容已经变了。"
    "请重新完整读取后再写。"
)


def _grant_store() -> Path | None:
    context = ledger._resolve_turn_context()
    if context is None:
        return None
    project_root, session_id, _turn_id = context
    return ledger.file_history_root(project_root, session_id) / _GRANT_NAME


def _fingerprint(path: Path) -> tuple[int, int, str] | None:
    try:
        if not path.is_file():
            return None
        stat = path.stat()
        data = path.read_bytes()
    except OSError:
        return None
    if int(stat.st_size) != len(data):
        return None
    revision = hashlib.sha256(data).hexdigest()
    return int(stat.st_mtime_ns), len(data), revision


def _latest(path: Path) -> dict[str, Any] | None:
    store = _grant_store()
    if store is None:
        return None
    normalized = ledger._normalize_stored_path(path)
    found: dict[str, Any] | None = None
    for entry in ledger._read_json_lines(store):
        if str(entry.get("path") or "") == normalized:
            found = entry
    return found


def _matches(stored: dict[str, Any], finger: tuple[int, int, str]) -> bool:
    mtime_ns, size, revision = finger
    if str(stored.get("source") or "") not in _SOURCES:
        return False
    try:
        stored_mtime = int(stored.get("mtimeNs"))
        stored_size = int(stored.get("size"))
    except (TypeError, ValueError):
        return False
    return (
        stored_mtime == mtime_ns
        and stored_size == size
        and str(stored.get("revision") or "") == revision
    )


def remember_current_file(path: Path | str, *, source: str) -> None:
    """Store the on-disk fingerprint. No-op outside a bound turn."""

    if source not in _SOURCES:
        return
    store = _grant_store()
    if store is None:
        return
    target = Path(path)
    finger = _fingerprint(target)
    if finger is None:
        return
    mtime_ns, size, revision = finger
    ledger._append_json_line(
        store,
        {
            "path": ledger._normalize_stored_path(target),
            "mtimeNs": mtime_ns,
            "size": size,
            "revision": revision,
            "source": source,
        },
    )


def existing_file_write_block(path: Path | str) -> str | None:
    """Return a reason when a bound turn must not mutate this existing file.

    ``None`` means allow: no bound turn, the path is not an existing file, or
    the stored fingerprint still matches the disk.
    """

    if ledger._resolve_turn_context() is None:
        return None
    target = Path(path)
    try:
        is_file = target.is_file()
    except OSError:
        return FULL_READ_REQUIRED
    if not is_file:
        return None
    stored = _latest(target)
    finger = _fingerprint(target)
    if stored is None or finger is None or not _matches(stored, finger):
        return FULL_READ_REQUIRED
    return None
