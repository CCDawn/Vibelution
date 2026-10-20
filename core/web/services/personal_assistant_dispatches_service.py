"""Personal-assistant dispatch tracking over native agent inbox storage.

Read-only aggregation: dispatches are the PA-sent rows (``sourceAgentId`` ==
assistant) living in each target agent's ``agent_inbox_messages.jsonl``;
receipts are the rows other agents sent back into the assistant's own inbox.
No second transcript is built here — rows are projected straight from the
authoritative inbox JSONL the kernel already writes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logging import debug as _debug_logger

INBOX_FILENAME = "agent_inbox_messages.jsonl"
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
# Receipt matching scans a newest-first window of the assistant inbox; twice
# the dispatch window (floor 100) keeps receipts findable when unrelated
# inbox traffic interleaves, without loading the whole file.
_RECEIPT_WINDOW_FLOOR = 100
_RECEIPT_WINDOW_MULTIPLIER = 2
# Auto-acknowledgements the assistant itself sent back (kind
# ``agent_inbox_reply``) are responses, not PA-initiated dispatches.
_REPLY_KIND = "agent_inbox_reply"


class PersonalAssistantDispatchesError(Exception):
    """Base error for the dispatch tracking read model."""


class PersonalAssistantMissingError(PersonalAssistantDispatchesError):
    """The personal assistant identity is absent and dispatches cannot exist."""


def _agent_rows() -> list[dict[str, Any]]:
    from core.web.services import agent_directory_service as directory

    rows: list[dict[str, Any]] = []
    for row in directory.load_state().get("agents") or []:
        if isinstance(row, dict) and str(row.get("agentId") or "").strip():
            rows.append(dict(row))
    return rows


def _inbox_path(agent_row: dict[str, Any]) -> Path:
    from core.web.services import agent_directory_service as directory

    agent = dict(agent_row)
    if not str(agent.get("workspacePath") or "").strip():
        agent["workspacePath"] = directory._agent_workspace_relative_path(
            str(agent.get("agentId") or "").strip()
        )
    return directory._agent_workspace_event_path(agent, INBOX_FILENAME)


def _scan_inbox_reverse(
    path: Path,
    *,
    predicate: Any,
    cap: int,
) -> list[dict[str, Any]]:
    """Newest-first inbox scan that stops once ``cap`` rows match.

    A global top-``cap`` result can take at most ``cap`` rows from any single
    file, and if it takes k rows from a file they are that file's newest k
    matches — so per-file early stop is lossless for the merged window.
    """

    from core.web.services import agent_directory_service as directory

    matches: list[dict[str, Any]] = []
    if not path.exists():
        return matches
    try:
        for line in directory._iter_text_lines_reverse(path):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or not predicate(payload):
                continue
            matches.append(payload)
            if len(matches) >= cap:
                break
    except OSError as exc:
        _debug_logger.warning(
            "Failed to scan agent inbox for dispatches. path=%s error=%s", path, exc
        )
    return matches  # newest-first order from the reverse iterator


def _text(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip()


def _status(row: dict[str, Any]) -> str:
    return _text(row, "status").lower() or "pending"


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("metadata") if isinstance(row.get("metadata"), dict) else {}


def _receipt_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "messageId": _text(row, "messageId") or _text(row, "eventId"),
        "sourceAgentId": _text(row, "sourceAgentId"),
        "sourceAgentName": _text(row, "sourceAgentName"),
        "summary": _text(row, "summary"),
        "status": _status(row),
        "receivedAt": _text(row, "createdAt"),
    }


def list_personal_assistant_dispatches(*, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Aggregate PA dispatches and receipts; pure read, no side effects."""

    from core.web.services import personal_assistant_service

    window = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    agent = personal_assistant_service.profile_agent()
    if agent is None or str(agent.get("status") or "active").strip() != "active":
        raise PersonalAssistantMissingError(
            "The personal assistant has not been created. Dispatches are unavailable."
        )
    assistant_agent_id = _text(agent, "agentId")

    # Dispatches: PA-sent rows across every agent inbox (active and archived
    # targets alike — archived agents keep their workspace and history).
    def _is_dispatch(payload: dict[str, Any]) -> bool:
        return (
            _text(payload, "sourceAgentId") == assistant_agent_id
            and _text(payload, "kind") != _REPLY_KIND
        )

    dispatch_rows: list[dict[str, Any]] = []
    for agent_row in _agent_rows():
        if _text(agent_row, "agentId") == assistant_agent_id:
            # The assistant's own inbox holds inbound rows only for receipts.
            continue

        try:
            dispatch_rows.extend(_scan_inbox_reverse(_inbox_path(agent_row), predicate=_is_dispatch, cap=window))
        except Exception as exc:
            _debug_logger.warning(
                "Dispatch inbox scan failed. agentId=%s error=%s",
                _text(agent_row, "agentId"),
                exc,
            )
    dispatch_rows.sort(
        key=lambda row: (_text(row, "createdAt"), _text(row, "messageId") or _text(row, "eventId"))
    )
    dispatch_rows = dispatch_rows[-window:]

    # Receipts: rows in the assistant's own inbox, matched back to dispatches
    # by explicit replyToMessageId or by same-thread same-source.
    receipt_window = max(window * _RECEIPT_WINDOW_MULTIPLIER, _RECEIPT_WINDOW_FLOOR)
    receipt_rows = _scan_inbox_reverse(
        _inbox_path(agent), predicate=lambda _payload: True, cap=receipt_window
    )

    dispatches: list[dict[str, Any]] = []
    unmatched_receipts: list[dict[str, Any]] = []
    receipts_by_message_id: dict[str, list[dict[str, Any]]] = {}
    for row in receipt_rows:
        receipt = _receipt_row(row)
        source_agent_id = _text(row, "sourceAgentId")
        reply_to = _text(_metadata(row), "replyToMessageId")
        thread_id = _text(row, "threadId")
        target_dispatch = None
        for dispatch_row in dispatch_rows:
            if reply_to and reply_to == (_text(dispatch_row, "messageId") or _text(dispatch_row, "eventId")):
                target_dispatch = dispatch_row
                break
            if (
                thread_id
                and thread_id == _text(dispatch_row, "threadId")
                and source_agent_id
                and source_agent_id == _text(dispatch_row, "targetAgentId")
            ):
                target_dispatch = dispatch_row
                break
        if target_dispatch is not None:
            receipts_by_message_id.setdefault(
                _text(target_dispatch, "messageId") or _text(target_dispatch, "eventId"), []
            ).append(receipt)
        else:
            unmatched_receipts.append(receipt)

    for dispatch_row in dispatch_rows:
        message_id = _text(dispatch_row, "messageId") or _text(dispatch_row, "eventId")
        matched = receipts_by_message_id.get(message_id) or []
        matched.sort(key=lambda item: (item["receivedAt"], item["messageId"]))
        dispatches.append(
            {
                "messageId": message_id,
                "threadId": _text(dispatch_row, "threadId") or None,
                "targetAgentId": _text(dispatch_row, "targetAgentId"),
                "targetAgentName": _text(dispatch_row, "targetAgentName"),
                "targetSessionId": _text(dispatch_row, "targetSessionId"),
                "summary": _text(dispatch_row, "summary"),
                "deliveryStatus": _status(dispatch_row),
                "sentAt": _text(dispatch_row, "createdAt"),
                "receipts": matched,
            }
        )
    dispatches.sort(key=lambda item: (item["sentAt"], item["messageId"]), reverse=True)
    unmatched_receipts.sort(key=lambda item: (item["receivedAt"], item["messageId"]), reverse=True)

    return {
        "assistantAgentId": assistant_agent_id,
        "dispatches": dispatches,
        "unmatchedReceipts": unmatched_receipts,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
