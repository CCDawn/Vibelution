# -*- coding: utf-8 -*-
"""Turn-scoped file change ledger (pre-image checkpoint) for agent write tools.

Every agent file-write tool (create_file / edit_file / apply_diff_edit /
apply_patch_edit) captures a *pre-image* (the file bytes before the first
modification inside the current turn, or an explicit "did not exist"
sentinel) and an *after-image* (the bytes the turn left behind).  The ledger
is the checkpoint authority for two projections:

- turn-level ``changedFiles`` summaries surfaced on session-detail messages;
- whole-turn rewind (preview classification + strict idempotent apply).

Storage layout (all paths relative to the session workspace, mirroring the
turn journal's ``workspace/sessions/<token>/`` convention)::

    workspace/sessions/<session-token>/file_history/<turn-token>/
        pre.jsonl     # append-only; at most one entry per path (first wins)
        after.jsonl   # append-only; one entry per completed write (last wins)
        audit.jsonl   # rewind apply audit + idempotency marker
        images/<sha256>.bin   # content-addressed image payloads

Crash safety follows the turn journal's append discipline: byte-range sidecar
lock per file, single ``ab`` append with fsync, and partial-line-tolerant
reads (a torn trailing line is skipped, not fatal).

Every capture is fail-open: a ledger failure must never fail the user-visible
tool call; it is downgraded to a warning log and the file simply has no
checkpoint for that turn.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from core.infrastructure.file_lock import locked_sidecar
from core.chat.turn_journal import _safe_event_token, _safe_session_workspace_token

LEDGER_SCHEMA_VERSION = 1

_PRE_FILE = "pre.jsonl"
_AFTER_FILE = "after.jsonl"
_AUDIT_FILE = "audit.jsonl"
_IMAGES_DIR = "images"

_STATE_CREATED = "created"
_STATE_MODIFIED = "modified"
_STATE_DELETED = "deleted"

_CLASSIFICATION_SAFE = "safe"
_CLASSIFICATION_CHECKPOINT_MISSING = "checkpoint_missing"
_CLASSIFICATION_EXTERNAL_MODIFIED = "external_modified"
_CLASSIFICATION_NOT_IN_CHECKPOINT = "not_in_checkpoint"
_CLASSIFICATION_IGNORED = "ignored"

_ACTION_RESTORE = "restore"
_ACTION_DELETE = "delete"
_ACTION_NONE = "none"

_UNSAFE_CLASSIFICATIONS = frozenset(
    {
        _CLASSIFICATION_CHECKPOINT_MISSING,
        _CLASSIFICATION_EXTERNAL_MODIFIED,
        _CLASSIFICATION_NOT_IN_CHECKPOINT,
        _CLASSIFICATION_IGNORED,
    }
)

_LOCK_TIMEOUT_SECONDS = 10.0

# Per-directory thread lock: the journal's read-modify-write discipline needs
# both an in-process lock (readers included) and the OS byte-range sidecar.
_DIR_THREAD_LOCKS: dict[str, threading.RLock] = {}
_DIR_THREAD_LOCKS_GUARD = threading.Lock()

# Explicit turn-scope override. Production hooks resolve the turn identity
# from the agent runtime context (propagated into tool threads via
# copy_context); tests and non-runtime callers bind it explicitly instead of
# faking an agent runtime.
_SCOPE_PROJECT_ROOT: ContextVar[Path | None] = ContextVar(
    "vibelution_file_ledger_scoped_project_root", default=None
)
_SCOPE_SESSION_ID: ContextVar[str] = ContextVar(
    "vibelution_file_ledger_scoped_session_id", default=""
)
_SCOPE_TURN_ID: ContextVar[str] = ContextVar(
    "vibelution_file_ledger_scoped_turn_id", default=""
)


class FileChangeRewindConflictError(RuntimeError):
    """Strict rewind rejected because at least one file is unsafe."""

    def __init__(self, message: str, unsafe_files: list[dict[str, Any]]):
        super().__init__(message)
        self.unsafe_files = unsafe_files


def _debug():
    from core.logging import debug as debug_logger

    return debug_logger


def _warn(message: str) -> None:
    try:
        _debug().warning(f"[file_change_ledger] {message}")
    except Exception:
        pass


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@contextmanager
def bind_turn_scope(
    session_id: str,
    turn_id: str,
    *,
    project_root: Path | str | None = None,
) -> Iterator[None]:
    """Bind an explicit (project_root, session_id, turn_id) ledger scope.

    Precedence over the agent runtime context is intentional: this scope is
    the deterministic injection point for tests and internal callers that run
    outside a live agent turn.
    """

    root_token = _SCOPE_PROJECT_ROOT.set(Path(project_root) if project_root else None)
    session_token = _SCOPE_SESSION_ID.set(str(session_id or "").strip())
    turn_token = _SCOPE_TURN_ID.set(str(turn_id or "").strip())
    try:
        yield
    finally:
        _SCOPE_PROJECT_ROOT.reset(root_token)
        _SCOPE_SESSION_ID.reset(session_token)
        _SCOPE_TURN_ID.reset(turn_token)


def file_history_root(project_root: Path | str, session_id: str) -> Path:
    """Session-scoped ledger root (workspace/sessions/<token>/file_history)."""

    token = _safe_session_workspace_token(str(session_id or "").strip())
    return Path(project_root) / "workspace" / "sessions" / token / "file_history"


def turn_history_dir(project_root: Path | str, session_id: str, turn_id: str) -> Path:
    """Turn-scoped ledger directory holding pre/after/audit streams."""

    turn_token = _safe_event_token(str(turn_id or "").strip())
    return file_history_root(project_root, session_id) / turn_token


def _dir_thread_lock(path: Path) -> threading.RLock:
    key = str(path)
    with _DIR_THREAD_LOCKS_GUARD:
        lock = _DIR_THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _DIR_THREAD_LOCKS[key] = lock
        return lock


def _resolve_turn_context() -> tuple[Path, str, str] | None:
    """Resolve (project_root, session_id, turn_id), or None outside a turn."""

    session_id = _SCOPE_SESSION_ID.get()
    turn_id = _SCOPE_TURN_ID.get()
    project_root = _SCOPE_PROJECT_ROOT.get()
    if not session_id or not turn_id:
        try:
            from core.web.services.agent_directory_service import current_agent_runtime

            runtime = current_agent_runtime() or {}
        except Exception:
            runtime = {}
        session_id = session_id or str(runtime.get("sessionId") or "").strip()
        turn_id = turn_id or str(runtime.get("turnId") or "").strip()
    if not session_id or not turn_id:
        return None
    if project_root is None:
        try:
            from core.web.services.agent_directory_service import PROJECT_ROOT

            project_root = PROJECT_ROOT
        except Exception:
            return None
    return Path(project_root), session_id, turn_id


def _normalize_stored_path(path: Path) -> str:
    # resolve() (not absolute()) is the identity anchor: tools pass a mix of
    # as-given, Path.resolve()-ed and cwd-joined spellings of the same file;
    # without canonicalization the same file can split into two ledger rows.
    return Path(path).resolve().as_posix()


def display_path(path: str, project_root: Path | str) -> str:
    """Project-relative posix path when under the root, absolute otherwise."""

    try:
        # Both sides resolved: the stored path is canonical, but the root can
        # arrive in short-path (8.3) or differently-cased spellings.
        normalized = Path(path).resolve()
        relative = normalized.relative_to(Path(project_root).resolve())
        return relative.as_posix()
    except Exception:
        return Path(path).as_posix()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _store_image(images_dir: Path, data: bytes) -> str:
    """Content-addressed image write; returns the relative stored ref."""

    digest = _sha256_bytes(data)
    relative = f"{_IMAGES_DIR}/{digest}.bin"
    target = images_dir / f"{digest}.bin"
    if not target.exists():
        images_dir.mkdir(parents=True, exist_ok=True)
        tmp_target = target.with_suffix(f".tmp-{os.getpid()}-{threading.get_ident()}")
        tmp_target.write_bytes(data)
        os.replace(tmp_target, target)
    return relative


def _read_image(images_dir: Path, ref: str) -> bytes | None:
    if not ref:
        return None
    # Refs are generated locally as "images/<sha256>.bin"; reject anything else
    # so a corrupted entry can never escape the images directory.
    expected_prefix = f"{_IMAGES_DIR}/"
    if not ref.startswith(expected_prefix):
        return None
    name = ref[len(expected_prefix):]
    if "/" in name or "\\" in name or ".." in name:
        return None
    try:
        return (images_dir / name).read_bytes()
    except OSError:
        return None


def _append_json_line(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    with _dir_thread_lock(path.parent):
        with locked_sidecar(path, timeout=_LOCK_TIMEOUT_SECONDS):
            with path.open("ab") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    """Partial-line-tolerant JSONL read (a torn trailing line is skipped)."""

    try:
        raw = path.read_bytes()
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for line in raw.splitlines():
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries


def _read_bytes_or_none(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _count_lines(data: bytes | None) -> int:
    if not data:
        return 0
    text = data.decode("utf-8", errors="replace")
    if not text:
        return 0
    lines = text.count("\n")
    if not text.endswith("\n"):
        lines += 1
    return lines


def _pre_entry_for(entries: list[dict[str, Any]], stored_path: str) -> dict[str, Any] | None:
    for entry in entries:
        if str(entry.get("path") or "") == stored_path and entry.get("kind") == "pre":
            return entry
    return None


def _latest_after_entry_for(
    entries: list[dict[str, Any]], stored_path: str
) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for entry in entries:
        if str(entry.get("path") or "") == stored_path and entry.get("kind") == "after":
            latest = entry
    return latest


def capture_pre_write(abs_path: Path | str) -> None:
    """Record the pre-image of ``abs_path`` for the current turn (fail-open).

    Only the first capture per (turn, path) is kept: later writes inside the
    same turn must rewind to the state *before the turn*, not before their
    own call.
    """

    try:
        context = _resolve_turn_context()
        if context is None:
            return
        project_root, session_id, turn_id = context
        path = Path(abs_path)
        stored_path = _normalize_stored_path(path)
        turn_dir = turn_history_dir(project_root, session_id, turn_id)
        pre_path = turn_dir / _PRE_FILE
        with _dir_thread_lock(turn_dir):
            existing = _read_json_lines(pre_path)
            if _pre_entry_for(existing, stored_path) is not None:
                return
            data = _read_bytes_or_none(path)
            entry: dict[str, Any] = {
                "v": LEDGER_SCHEMA_VERSION,
                "kind": "pre",
                "path": stored_path,
                "existed": data is not None,
                "recordedAt": _now_timestamp(),
            }
            if data is not None:
                entry["image"] = _store_image(turn_dir / _IMAGES_DIR, data)
                entry["sha256"] = _sha256_bytes(data)
                entry["size"] = len(data)
            _append_json_line(pre_path, entry)
    except Exception as exc:  # fail-open: ledger must not break write tools
        _warn(f"pre-image capture failed for {abs_path}: {type(exc).__name__}: {exc}")


def capture_post_write(abs_path: Path | str) -> None:
    """Record the after-image and line-diff stats for ``abs_path`` (fail-open).

    Appended after every completed write so the latest entry always reflects
    what the turn left on disk (later writes supersede earlier ones).
    """

    try:
        context = _resolve_turn_context()
        if context is None:
            return
        project_root, session_id, turn_id = context
        path = Path(abs_path)
        stored_path = _normalize_stored_path(path)
        turn_dir = turn_history_dir(project_root, session_id, turn_id)
        data = _read_bytes_or_none(path)
        pre_entries = _read_json_lines(turn_dir / _PRE_FILE)
        pre_entry = _pre_entry_for(pre_entries, stored_path)
        pre_lines = 0
        if pre_entry is not None and pre_entry.get("existed"):
            pre_image = _read_image(turn_dir / _IMAGES_DIR, str(pre_entry.get("image") or ""))
            pre_lines = _count_lines(pre_image)
        after_lines = _count_lines(data)
        entry: dict[str, Any] = {
            "v": LEDGER_SCHEMA_VERSION,
            "kind": "after",
            "path": stored_path,
            "existed": data is not None,
            "recordedAt": _now_timestamp(),
            "additions": max(0, after_lines - pre_lines),
            "deletions": max(0, pre_lines - after_lines),
        }
        if data is not None:
            entry["image"] = _store_image(turn_dir / _IMAGES_DIR, data)
            entry["sha256"] = _sha256_bytes(data)
            entry["size"] = len(data)
        _append_json_line(turn_dir / _AFTER_FILE, entry)
    except Exception as exc:  # fail-open
        _warn(f"after-image capture failed for {abs_path}: {type(exc).__name__}: {exc}")


def _turn_entries(
    project_root: Path | str, session_id: str, turn_id: str
) -> tuple[Path, list[dict[str, Any]], list[dict[str, Any]]] | None:
    turn_dir = turn_history_dir(project_root, session_id, turn_id)
    pre_file = turn_dir / _PRE_FILE
    after_file = turn_dir / _AFTER_FILE
    if not pre_file.exists() and not after_file.exists():
        return None
    pre_entries = [
        entry
        for entry in _read_json_lines(pre_file)
        if entry.get("kind") == "pre" and str(entry.get("path") or "").strip()
    ]
    after_entries = [
        entry
        for entry in _read_json_lines(after_file)
        if entry.get("kind") == "after" and str(entry.get("path") or "").strip()
    ]
    return turn_dir, pre_entries, after_entries


def _file_change_state(
    pre_entry: dict[str, Any] | None, after_entry: dict[str, Any] | None
) -> str:
    existed_before = bool(pre_entry and pre_entry.get("existed"))
    exists_after = bool(after_entry and after_entry.get("existed"))
    if not existed_before and exists_after:
        return _STATE_CREATED
    if existed_before and not exists_after:
        return _STATE_DELETED
    if not existed_before and not exists_after:
        # Created and deleted inside the same turn: no net change to rewind.
        return "unchanged"
    return _STATE_MODIFIED


def turn_file_changes(
    project_root: Path | str, session_id: str, turn_id: str
) -> list[dict[str, Any]]:
    """Projected turn summary: [{path, additions, deletions, state}].

    Read-only. ``path`` is project-relative when under the project root.
    Unchanged files (content identical to the pre-image) are omitted.
    """

    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_turn_id:
        return []
    loaded = _turn_entries(project_root, session_id, normalized_turn_id)
    if loaded is None:
        return []
    turn_dir, pre_entries, after_entries = loaded
    images_dir = turn_dir / _IMAGES_DIR
    changes: list[dict[str, Any]] = []
    for pre_entry in pre_entries:
        stored_path = str(pre_entry.get("path") or "")
        after_entry = _latest_after_entry_for(after_entries, stored_path)
        if after_entry is None:
            # The write never completed (or crashed mid-way): no after-image,
            # so there is nothing to present as a turn change.
            continue
        state = _file_change_state(pre_entry, after_entry)
        if state == "unchanged":
            continue
        if pre_entry.get("existed") and after_entry.get("existed"):
            pre_digest = str(pre_entry.get("sha256") or "")
            after_digest = str(after_entry.get("sha256") or "")
            if pre_digest and pre_digest == after_digest:
                continue  # unchanged content: not a visible change
        changes.append(
            {
                "path": display_path(stored_path, project_root),
                "additions": int(after_entry.get("additions") or 0),
                "deletions": int(after_entry.get("deletions") or 0),
                "state": state,
            }
        )
    changes.sort(key=lambda item: item["path"])
    return changes


def _classify_file(
    turn_dir: Path,
    project_root: Path,
    pre_entry: dict[str, Any],
    after_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    """Classify one ledger file for rewind (safe / unsafe + action)."""

    stored_path = str(pre_entry.get("path") or "")
    existed_before = bool(pre_entry.get("existed"))
    current = _read_bytes_or_none(Path(stored_path))
    current_digest = _sha256_bytes(current) if current is not None else ""
    item: dict[str, Any] = {
        "path": display_path(stored_path, project_root),
        "currentExists": current is not None,
        "currentSize": len(current) if current is not None else 0,
    }

    if after_entry is None:
        # No after-image: the write completed without a post snapshot (or the
        # ledger was disabled mid-turn), so safety cannot be verified.
        item.update(
            {
                "action": _ACTION_NONE,
                "classification": _CLASSIFICATION_IGNORED,
                "state": _STATE_MODIFIED if existed_before else _STATE_CREATED,
            }
        )
        return item

    state = _file_change_state(pre_entry, after_entry)
    item["state"] = state
    after_digest = str(after_entry.get("sha256") or "")
    pre_digest = str(pre_entry.get("sha256") or "")
    pre_image = (
        _read_image(turn_dir / _IMAGES_DIR, str(pre_entry.get("image") or ""))
        if existed_before
        else None
    )

    if state == _STATE_CREATED:
        if not current:
            item.update({"action": _ACTION_NONE, "classification": _CLASSIFICATION_SAFE})
        elif after_digest and current_digest == after_digest:
            item.update({"action": _ACTION_DELETE, "classification": _CLASSIFICATION_SAFE})
        else:
            item.update(
                {
                    "action": _ACTION_NONE,
                    "classification": _CLASSIFICATION_EXTERNAL_MODIFIED,
                }
            )
        return item

    if state == _STATE_DELETED:
        if not existed_before:
            # Created inside the turn, deleted inside the turn: the pre-image
            # is "absent" and there is nothing to restore.
            item.update({"action": _ACTION_NONE, "classification": _CLASSIFICATION_SAFE})
        elif not current:
            item.update({"action": _ACTION_RESTORE, "classification": _CLASSIFICATION_SAFE})
        else:
            item.update(
                {
                    "action": _ACTION_NONE,
                    "classification": _CLASSIFICATION_EXTERNAL_MODIFIED,
                }
            )
        return item

    # modified / unchanged
    if state == "unchanged":
        # Net effect nil (e.g. overwritten back to the original bytes in-turn):
        # nothing to restore, and the pre-image legitimately has no payload.
        item.update({"action": _ACTION_NONE, "classification": _CLASSIFICATION_SAFE})
        return item
    if pre_image is None:
        item.update(
            {
                "action": _ACTION_NONE,
                "classification": _CLASSIFICATION_CHECKPOINT_MISSING,
            }
        )
        return item
    if current is not None and pre_digest and current_digest == pre_digest:
        item.update({"action": _ACTION_NONE, "classification": _CLASSIFICATION_SAFE})
        return item
    if after_digest and current_digest == after_digest:
        item.update({"action": _ACTION_RESTORE, "classification": _CLASSIFICATION_SAFE})
        return item
    item.update(
        {
            "action": _ACTION_NONE,
            "classification": _CLASSIFICATION_EXTERNAL_MODIFIED,
        }
    )
    return item


def preview_turn_rewind(
    project_root: Path | str, session_id: str, turn_id: str
) -> dict[str, Any] | None:
    """Whole-turn rewind preview.

    Returns ``None`` when the turn has no checkpoint at all; otherwise a
    payload of per-file {path, action, classification, state, currentExists,
    currentSize} items plus a ``canApply`` flag and a capability note.
    """

    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_turn_id:
        return None
    loaded = _turn_entries(project_root, session_id, normalized_turn_id)
    if loaded is None:
        return None
    turn_dir, pre_entries, after_entries = loaded
    files: list[dict[str, Any]] = []
    for pre_entry in pre_entries:
        after_entry = _latest_after_entry_for(after_entries, str(pre_entry.get("path") or ""))
        files.append(_classify_file(turn_dir, Path(project_root), pre_entry, after_entry))
    files.sort(key=lambda item: item["path"])
    ignored_count = sum(1 for item in files if item["classification"] == _CLASSIFICATION_IGNORED)
    external_count = sum(
        1 for item in files if item["classification"] == _CLASSIFICATION_EXTERNAL_MODIFIED
    )
    can_apply = all(item["classification"] == _CLASSIFICATION_SAFE for item in files)
    note = ""
    if ignored_count:
        note = (
            f"{ignored_count} 个文件缺少写入后快照（非受管写入路径），"
            "不在本次回退范围内。"
        )
    elif external_count:
        note = f"{external_count} 个文件在本轮写入后被再次修改，默认拒绝整批回退。"
    return {
        "sessionId": str(session_id or "").strip(),
        "turnId": normalized_turn_id,
        "files": files,
        "canApply": can_apply,
        "capabilityNote": note,
    }


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_target = target.with_name(
        f"{target.name}.rewind-tmp-{os.getpid()}-{threading.get_ident()}"
    )
    tmp_target.write_bytes(data)
    os.replace(tmp_target, target)


def _audit_records(turn_dir: Path) -> list[dict[str, Any]]:
    return _read_json_lines(turn_dir / _AUDIT_FILE)


def _applied_audit_record(turn_dir: Path, idempotency_key: str) -> dict[str, Any] | None:
    for record in _audit_records(turn_dir):
        if (
            str(record.get("idempotencyKey") or "") == idempotency_key
            and str(record.get("status") or "") == "applied"
        ):
            return record
    return None


def apply_turn_rewind(
    project_root: Path | str,
    session_id: str,
    turn_id: str,
    *,
    force: bool = False,
    requested_by: str = "",
) -> dict[str, Any]:
    """Restore every checkpointed file of one turn to its pre-image.

    Strict by default: any file classified unsafe rejects the whole batch
    without touching disk (raise :class:`FileChangeRewindConflictError`).
    ``force=True`` downgrades to per-file application: safe files are
    restored, unsafe files are skipped and reported.

    Idempotent: a successfully applied rewind records an audit entry keyed
    ``session-rewind:<session>:<turn>``; a repeated call replays that stored
    result instead of touching files again.
    """

    normalized_turn_id = str(turn_id or "").strip()
    loaded = _turn_entries(project_root, session_id, normalized_turn_id)
    if loaded is None:
        return {
            "sessionId": str(session_id or "").strip(),
            "turnId": normalized_turn_id,
            "status": "empty",
            "alreadyApplied": False,
            "applied": [],
            "skipped": [],
        }
    turn_dir, pre_entries, after_entries = loaded
    idempotency_key = f"session-rewind:{session_id}:{normalized_turn_id}"

    with _dir_thread_lock(turn_dir):
        applied_record = _applied_audit_record(turn_dir, idempotency_key)
        if applied_record is not None:
            return {
                "sessionId": str(session_id or "").strip(),
                "turnId": normalized_turn_id,
                "status": "applied",
                "alreadyApplied": True,
                "applied": list(applied_record.get("applied") or []),
                "skipped": list(applied_record.get("skipped") or []),
            }

        paired: list[tuple[dict[str, Any], dict[str, Any]]] = [
            (
                pre_entry,
                _classify_file(
                    turn_dir,
                    Path(project_root),
                    pre_entry,
                    _latest_after_entry_for(after_entries, str(pre_entry.get("path") or "")),
                ),
            )
            for pre_entry in pre_entries
        ]

        unsafe = [item for _pre, item in paired if item["classification"] in _UNSAFE_CLASSIFICATIONS]
        actionable = [
            (pre_entry, item)
            for pre_entry, item in paired
            if item["classification"] == _CLASSIFICATION_SAFE and item["action"] != _ACTION_NONE
        ]
        if unsafe and not force:
            raise FileChangeRewindConflictError(
                "存在非安全文件（写入后被再次修改或缺少检查点），已拒绝整批回退；"
                "确认后可用 force 仅恢复安全文件。",
                unsafe_files=unsafe,
            )

        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = [
            {"path": item["path"], "classification": item["classification"]}
            for item in unsafe
        ]
        for pre_entry, item in actionable:
            stored_path = str(pre_entry.get("path") or "")
            try:
                if item["action"] == _ACTION_DELETE:
                    target = Path(stored_path)
                    if target.exists():
                        target.unlink()
                else:
                    image = _read_image(turn_dir / _IMAGES_DIR, str(pre_entry.get("image") or ""))
                    if image is None:
                        skipped.append(
                            {"path": item["path"], "classification": _CLASSIFICATION_CHECKPOINT_MISSING}
                        )
                        continue
                    _atomic_write_bytes(Path(stored_path), image)
                applied.append({"path": item["path"], "action": item["action"]})
            except Exception as exc:
                skipped.append(
                    {"path": item["path"], "classification": f"apply_failed:{type(exc).__name__}"}
                )
                _warn(f"rewind apply failed for {item['path']}: {exc}")

        status = "applied" if applied or not paired else "empty"
        result = {
            "sessionId": str(session_id or "").strip(),
            "turnId": normalized_turn_id,
            "status": status,
            "alreadyApplied": False,
            "applied": applied,
            "skipped": skipped,
        }
        try:
            _append_json_line(
                turn_dir / _AUDIT_FILE,
                {
                    "v": LEDGER_SCHEMA_VERSION,
                    "idempotencyKey": idempotency_key,
                    "status": "applied" if status == "applied" else "empty",
                    "requestedBy": str(requested_by or "").strip(),
                    "mode": "force" if force else "strict",
                    "recordedAt": _now_timestamp(),
                    "applied": applied,
                    "skipped": skipped,
                },
            )
        except Exception as exc:
            _warn(f"rewind audit append failed: {exc}")
        return result


__all__ = [
    "FileChangeRewindConflictError",
    "apply_turn_rewind",
    "bind_turn_scope",
    "capture_post_write",
    "capture_pre_write",
    "display_path",
    "file_history_root",
    "preview_turn_rewind",
    "turn_file_changes",
    "turn_history_dir",
]
