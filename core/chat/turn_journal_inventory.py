"""Bounded existing-only metadata observation of native Session Journals.

Body bytes are parsed only inside this owner and immediately discarded. The
original latest_open_turn_id/fold_active_events remain the branch authority.
An open Journal is not evidence of a running worker or permission to stop it.
"""
from __future__ import annotations

import re
import stat
from pathlib import Path
from typing import Any, Callable

from core.assistant_runtime.migration_io import check_path, path_identity, read_stable_file, strict_json
from core.infrastructure import developer_sandbox

from . import turn_journal

MAX_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_LINE_BYTES = 256 * 1024
MAX_LINES = 100000
MAX_DIRECTORIES = 10000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,511}\Z")


def _authority_snapshot(project_root: Path) -> tuple[Path, Callable[[], None]]:
    """Pin existing routing inputs; never call a config/sandbox initializer."""
    from config.public_config import read_existing_config_snapshot

    config = check_path(Path(developer_sandbox.CONFIG_PATH))
    before = path_identity(config)
    routing = developer_sandbox.workspace_routing_fingerprint(project_root)
    active = developer_sandbox._active_state_path(project_root)
    active_identity = path_identity(check_path(active)) if active.exists() else None
    public = read_existing_config_snapshot(config)
    workspace = check_path(developer_sandbox.existing_sandboxed_workspace_path(project_root, public_config=public))
    root = check_path(workspace / "sessions")

    def verify() -> None:
        if (path_identity(check_path(config)) != before
                or developer_sandbox.workspace_routing_fingerprint(project_root) != routing
                or (path_identity(check_path(active)) if active.exists() else None) != active_identity
                or developer_sandbox.existing_sandboxed_workspace_path(project_root, public_config=public) != workspace):
            raise ValueError("source_changed")
        check_path(root)

    verify()
    return root, verify


def _token(value: Any, pattern=_ID, *, empty: bool = False) -> bool:
    return isinstance(value, str) and (empty and value == "" or pattern.fullmatch(value) is not None)


def _metadata_event(raw: bytes) -> turn_journal.TurnJournalEvent:
    row = strict_json(raw)
    if not isinstance(row, dict):
        raise ValueError("invalid_metadata")
    sid = row.get("sessionId", row.get("session_id"))
    tid = row.get("turnId", row.get("turn_id", ""))
    eid = row.get("eventId", row.get("event_id"))
    kind = row.get("eventType", row.get("event_type"))
    parent = row.get("parentEventId", row.get("parent_event_id", ""))
    sequence = row.get("sequence")
    schema = row.get("schemaVersion", row.get("schema_version", turn_journal.SCHEMA_VERSION))
    if (not _token(sid) or not _token(tid, empty=True) or not _token(eid, _EVENT_ID)
            or not _token(kind, _EVENT_ID) or not _token(parent, _EVENT_ID, empty=True)
            or type(sequence) is not int or not 1 <= sequence <= 2**63 - 1
            or type(schema) is not int or not 1 <= schema <= turn_journal.SCHEMA_VERSION
            or kind == turn_journal.EVENT_TURN_STARTED and not tid):
        raise ValueError("invalid_metadata")
    payload = {}
    if kind == turn_journal.EVENT_BRANCH_REBASE:
        branch = row.get("payload")
        if not isinstance(branch, dict) or branch.get("operation") not in {"edit", "regenerate", "head_select"}:
            raise ValueError("invalid_metadata")
        target, branch_id = branch.get("fromEventId", ""), branch.get("branchId", "")
        if not _token(target, _EVENT_ID, empty=True) or not _token(branch_id, _EVENT_ID, empty=True):
            raise ValueError("invalid_metadata")
        payload = {"operation": branch["operation"], "fromEventId": target, "branchId": branch_id}
    return turn_journal.TurnJournalEvent(
        schema_version=turn_journal.SCHEMA_VERSION, event_id=eid, session_id=sid, turn_id=tid,
        sequence=sequence, event_type=kind, status="", timestamp="", source="",
        payload=payload, parent_event_id=parent,
    )


def _open_turn(raw: bytes, path: Path, root: Path, remaining_lines: int, line_limit: int):
    # A trailing partial record may be a terminal marker. Never infer an open
    # Turn from a prefix whose unseen tail could have settled or selected it.
    if raw and not raw.endswith(b"\n"):
        raise ValueError("invalid_metadata")
    lines = raw.split(b"\n")[:-1] if raw else []
    if len(lines) > remaining_lines or any(len(line) > line_limit for line in lines):
        raise OverflowError("budget_exceeded")
    events, ids, sequences = [], set(), set()
    sid = ""
    for line in lines:
        if not line.strip():
            continue
        event = _metadata_event(line)
        if event.event_id in ids or event.sequence in sequences or sid and sid != event.session_id:
            raise ValueError("invalid_metadata")
        ids.add(event.event_id)
        sequences.add(event.sequence)
        sid = event.session_id
        events.append(event)
    if sid and turn_journal.turn_journal_path(root, sid, journal_workspace_root=root) != path:
        raise ValueError("invalid_metadata")
    # Native load_turn_events sorts by sequence; uniqueness makes its timestamp
    # and event-id tie breakers irrelevant without retaining those strings.
    events.sort(key=lambda event: event.sequence)
    turn_id = turn_journal.latest_open_turn_id(events)
    fact = ({"sessionId": sid, "turnId": turn_id, "agentId": "", "status": "unknown",
             "stopRequested": False, "releasedToUser": False, "liveControl": False,
             "sources": ["journal"]} if turn_id else None)
    return fact, len(lines)


def read_turn_journal_inventory(project_root: Path, *, max_directories: int = MAX_DIRECTORIES,
                                max_bytes: int = MAX_BYTES, max_lines: int = MAX_LINES,
                                max_line_bytes: int = MAX_LINE_BYTES) -> dict[str, Any]:
    """Observe each Session's native latest open Turn, including Journal-only ones.

    Every explicit Journal read, including the final verification read, is
    charged to max_bytes. Directory entries and JSONL lines are separately
    bounded. Failure discards that Journal's facts, never repairs a source.
    Routing inputs have the existing owner's separate bounded read contract.
    """
    for value, ceiling in ((max_directories, MAX_DIRECTORIES), (max_bytes, MAX_BYTES),
                           (max_lines, MAX_LINES), (max_line_bytes, MAX_LINE_BYTES)):
        if type(value) is not int or not 1 <= value <= ceiling:
            raise ValueError("Invalid journal inventory limit")
    result = {"turns": [], "complete": False, "unavailable": False, "truncated": False,
              "invalidCount": 0, "reason": "none"}
    try:
        root, verify_authority = _authority_snapshot(Path(project_root))
        root = check_path(root)
        if not stat.S_ISDIR(root.stat().st_mode):
            raise ValueError("read_failed")
        directories = [(root, path_identity(root))]
    except (OSError, ValueError):
        return {**result, "unavailable": True, "reason": "read_failed"}
    observations, charged, lines, visited = [], 0, 0, 0
    try:
        for folder in root.iterdir():
            visited += 1
            if visited > max_directories or charged >= max_bytes:
                result["truncated"] = True
                break
            try:
                folder = check_path(folder)
                if not stat.S_ISDIR(folder.stat().st_mode):
                    continue
                directories.append((folder, path_identity(folder)))
                path = folder / "turn_journal.jsonl"
                try:
                    path.lstat()
                except FileNotFoundError:
                    continue
                path = check_path(path)
                initial_identity = path_identity(path)
                size = initial_identity[2]
                if size > MAX_FILE_BYTES:
                    result["truncated"] = True
                    continue
                if size * 2 > max_bytes - charged:
                    # No more namespace I/O after the total source budget is
                    # exhausted. Accepted Journals still get their reserved
                    # verification read and the scan remains explicitly partial.
                    result["truncated"] = True
                    break
                # Reserve both reads even if parsing rejects this file, so a
                # corrupt namespace cannot bypass the total source budget.
                charged += size * 2
                snapshot = read_stable_file(path, size, expected=initial_identity)
                consumed = snapshot.raw.count(b"\n") + int(bool(snapshot.raw) and not snapshot.raw.endswith(b"\n"))
                remaining_lines = max_lines - lines
                lines += consumed
                fact, _ = _open_turn(snapshot.raw, path, root, remaining_lines, max_line_bytes)
                observations.append((path, snapshot.identity, snapshot.sha256, size, fact))
                del snapshot
            except OverflowError:
                result["truncated"] = True
            except (OSError, ValueError, TypeError, RecursionError) as error:
                result["invalidCount"] += 1
                if str(error) in {"source_changed", "source_unavailable_or_changed"}:
                    result["reason"] = "source_changed"
        for path, identity, digest, size, fact in observations:
            try:
                after = read_stable_file(path, size, expected=identity)
                if after.sha256 != digest:
                    raise ValueError("source_changed")
                del after
                if fact is not None:
                    result["turns"].append(fact)
            except (OSError, ValueError):
                result["invalidCount"] += 1
                result["reason"] = "source_changed"
        if any(path_identity(check_path(path)) != identity for path, identity in directories):
            raise ValueError("source_changed")
        verify_authority()
    except (OSError, ValueError):
        return {**result, "turns": [], "reason": "source_changed", "invalidCount": result["invalidCount"] + 1}
    result["complete"] = not (result["invalidCount"] or result["truncated"])
    if result["reason"] == "none":
        result["reason"] = "invalid_metadata" if result["invalidCount"] else "budget_exceeded" if result["truncated"] else "none"
    result["turns"].sort(key=lambda item: (item["sessionId"], item["turnId"]))
    return result
