"""Prune chat-state rows that no longer back any session.

``session_runtime_state`` has no foreign key onto the ``sessions`` projection,
so a session retired without its chat-state row leaves a ghost behind. Every
``save_chat_state`` read-modify-write then carries that ghost forward, and the
startup recovery sweep walks it on every boot (643 scanned sessions against a
438-row directory in the incident that prompted this module).

The repair is deliberately narrow: a row is dropped only when the directory no
longer knows the session, its workspace directory holds no files, and its
payload carries no message body. Anything less is kept, because a chat-state
row can legitimately exist before its directory row does.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

_logger = logging.getLogger(__name__)


def _payload_message_count(payload: Mapping[str, Any]) -> int:
    """How many messages a chat-state payload carries, defensively."""

    messages = payload.get("messages")
    if isinstance(messages, (list, tuple)):
        return len(messages)
    return 1 if messages else 0


# Session-runtime bookkeeping that lives at the workspace root. A ghost keeps
# one of these after its last admission, and it must not read as content, or
# the prune can never retire a session that only ever admitted a turn.
_RUNTIME_WORKSPACE_ROOT_FILES = frozenset({"session_admission.lock"})


def _is_runtime_workspace_file(path: Path, workspace_dir: Path) -> bool:
    """Whether a file is session-runtime bookkeeping rather than content."""

    if path.name in _RUNTIME_WORKSPACE_ROOT_FILES:
        return True
    # Locks and temp markers directly under the workspace root are re-created
    # on demand. A lock the user (or a tool) dropped deeper in the tree is not
    # ours to judge, so it still counts as content.
    return path.suffix == ".lock" and path.parent == workspace_dir


def _workspace_has_files(workspace_dir: Path | None) -> bool:
    """Whether a session workspace carries any file worth keeping.

    Every session materializes the same empty skeleton (``artifacts``, ``logs``,
    ``memory``, ``mental_model``, ``notes``, ``tmp``), so counting directory
    entries answers yes for every ghost and the prune would never fire. Only
    a real file inside the tree counts as content, and the session's own
    runtime bookkeeping at the workspace root does not.
    """

    if workspace_dir is None:
        return False
    try:
        for path in workspace_dir.rglob("*"):
            if not path.is_file():
                continue
            if _is_runtime_workspace_file(path, workspace_dir):
                continue
            return True
    except OSError:
        # An unreadable directory is not proof of emptiness; keep the row.
        return True
    return False


def prune_orphan_chat_state_sessions(project_root: Path) -> dict[str, Any]:
    """Drop chat-state rows that are provably empty and directory-less.

    Never raises: a failed sweep only restores the pre-sweep status quo.
    """

    from core.ui import chat_state

    from . import conversation_index

    summary: dict[str, Any] = {
        "orphanCandidateCount": 0,
        "keptWithContentCount": 0,
        "prunedCount": 0,
    }
    try:
        rows = chat_state.list_orphan_session_runtime_rows(project_root)
    except Exception as exc:  # noqa: BLE001 - a failed sweep never blocks startup
        _logger.warning("Orphan chat-state scan failed: %s", type(exc).__name__)
        return summary

    summary["orphanCandidateCount"] = len(rows)
    targets: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        session_id = str(row.get("sessionId") or "").strip()
        if not session_id:
            continue
        payload = row.get("payload")
        if not isinstance(payload, Mapping) or _payload_message_count(payload):
            summary["keptWithContentCount"] += 1
            continue
        workspace_dir = conversation_index._session_workspace_dir_if_present(
            session_id
        )
        if _workspace_has_files(workspace_dir):
            summary["keptWithContentCount"] += 1
            continue
        targets.append(session_id)

    if not targets:
        return summary
    try:
        summary["prunedCount"] = chat_state.delete_session_runtime_rows(
            project_root, targets
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning("Orphan chat-state prune failed: %s", type(exc).__name__)
    return summary
