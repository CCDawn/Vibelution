"""Personal-assistant dispatch tracking over native agent inbox storage.

Read-only aggregation: dispatches are the PA-sent rows (``sourceAgentId`` ==
assistant) living in each target agent's ``agent_inbox_messages.jsonl``;
receipts are the rows other agents sent back into the assistant's own inbox.
No second transcript is built here — rows are projected straight from the
authoritative inbox JSONL the kernel already writes.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
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
_FOLLOWUP_KIND = "pa_followup"


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
    strict: bool = False,
) -> list[dict[str, Any]]:
    """Bounded matching scan; strict uniqueness reads need no ordering.

    A global top-``cap`` result can take at most ``cap`` rows from any single
    file, and if it takes k rows from a file they are that file's newest k
    matches — so per-file early stop is lossless for the merged window.
    """

    from core.web.services import agent_directory_service as directory

    matches: list[dict[str, Any]] = []
    if not path.exists():
        return matches
    try:
        # The shared reverse iterator tolerates I/O failures. A uniqueness
        # proof must instead reach EOF or a second distinct candidate.
        with (path.open("r", encoding="utf-8") if strict else nullcontext(directory._iter_text_lines_reverse(path))) as lines:
            for line in lines:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    if strict:
                        raise
                    continue
                if strict and not isinstance(payload, dict):
                    raise ValueError("Inbox record is not an object")
                if not isinstance(payload, dict) or not predicate(payload):
                    continue
                matches.append(payload)
                if len(matches) >= cap:
                    break
    except OSError as exc:
        if strict:
            raise
        _debug_logger.warning(
            f"Failed to scan agent inbox for dispatches. path={path} error={type(exc).__name__}"
        )
    return matches  # newest-first order from the reverse iterator


def _text(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip()


def _status(row: dict[str, Any]) -> str:
    return _text(row, "status").lower() or "pending"


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("metadata") if isinstance(row.get("metadata"), dict) else {}


def _is_followup(row: dict[str, Any]) -> bool:
    return _text(row, "kind") == _FOLLOWUP_KIND or bool(
        _text(_metadata(row), "paFollowupOfMessageId")
    )


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
            and not _is_followup(payload)
        )

    agent_rows = _agent_rows()
    agent_rows_by_id = {_text(row, "agentId"): row for row in agent_rows}
    dispatch_rows: list[dict[str, Any]] = []
    dispatch_inbox_agent_by_row_id: dict[int, str] = {}
    for agent_row in agent_rows:
        if _text(agent_row, "agentId") == assistant_agent_id:
            # The assistant's own inbox holds inbound rows only for receipts.
            continue

        try:
            inbox_agent_id = _text(agent_row, "agentId")
            inbox_dispatches = _scan_inbox_reverse(
                _inbox_path(agent_row), predicate=_is_dispatch, cap=window
            )
            dispatch_rows.extend(inbox_dispatches)
            dispatch_inbox_agent_by_row_id.update(
                {id(row): inbox_agent_id for row in inbox_dispatches}
            )
        except Exception as exc:
            _debug_logger.warning(
                f"Dispatch inbox scan failed. agentId={_text(agent_row, 'agentId')} error={type(exc).__name__}"
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

    thread_match_cache: dict[tuple[str, str], str | None] = {}
    followup_match_cache: dict[tuple[str, str], str | None] = {}

    def _followup_origin_id(message_id: str, target_agent_id: str) -> str | None:
        """Resolve an explicit reply to a chase in its authoritative target inbox."""
        key = (message_id, target_agent_id)
        if key in followup_match_cache:
            return followup_match_cache[key]
        target = agent_rows_by_id.get(target_agent_id)
        if target is None or target_agent_id == assistant_agent_id:
            return None
        try:
            candidates = _scan_inbox_reverse(
                _inbox_path(target),
                predicate=lambda payload: (
                    (_text(payload, "messageId") or _text(payload, "eventId")) == message_id
                    and _text(payload, "sourceAgentId") == assistant_agent_id
                    and _text(payload, "targetAgentId") == target_agent_id
                    and _is_followup(payload)
                ),
                cap=2, strict=True,
            )
        except Exception as exc:
            _debug_logger.warning(
                f"Follow-up receipt scan failed. agentId={target_agent_id} error={type(exc).__name__}"
            )
            candidates = []
        origin_id = None
        if len(candidates) == 1:
            followup = candidates[0]
            parent_id = _text(_metadata(followup), "paFollowupOfMessageId")
            parents = [
                row for row in dispatch_rows
                if (_text(row, "messageId") or _text(row, "eventId")) == parent_id
                and _text(row, "targetAgentId") == target_agent_id
                and _text(row, "threadId") == _text(followup, "threadId")
                and dispatch_inbox_agent_by_row_id.get(id(row)) == target_agent_id
            ]
            if len(parents) == 1:
                origin_id = parent_id
        followup_match_cache[key] = origin_id
        return origin_id

    def _unique_thread_dispatch_id(thread_id: str, target_agent_id: str) -> str | None:
        cache_key = (thread_id, target_agent_id)
        if cache_key in thread_match_cache:
            return thread_match_cache[cache_key]

        target_agent_row = agent_rows_by_id.get(target_agent_id)
        if target_agent_row is None or target_agent_id == assistant_agent_id:
            thread_match_cache[cache_key] = None
            return None

        seen_message_ids: set[str] = set()

        def _is_thread_dispatch(payload: dict[str, Any]) -> bool:
            if (
                not _is_dispatch(payload)
                or _text(payload, "targetAgentId") != target_agent_id
                or _text(payload, "threadId") != thread_id
            ):
                return False
            message_id = _text(payload, "messageId") or _text(payload, "eventId")
            if not message_id or message_id in seen_message_ids:
                return False
            seen_message_ids.add(message_id)
            return True

        try:
            candidates = _scan_inbox_reverse(
                _inbox_path(target_agent_row), predicate=_is_thread_dispatch, cap=2, strict=True
            )
        except Exception as exc:
            _debug_logger.warning(
                f"Thread dispatch matching scan failed. agentId={target_agent_id} error={type(exc).__name__}"
            )
            candidates = []

        candidate_ids = {
            _text(candidate, "messageId") or _text(candidate, "eventId")
            for candidate in candidates
        }
        unique_id = next(iter(candidate_ids)) if len(candidate_ids) == 1 else None
        thread_match_cache[cache_key] = unique_id
        return unique_id

    dispatches: list[dict[str, Any]] = []
    unmatched_receipts: list[dict[str, Any]] = []
    receipts_by_message_id: dict[str, list[dict[str, Any]]] = {}
    for row in receipt_rows:
        receipt = _receipt_row(row)
        source_agent_id = _text(row, "sourceAgentId")
        reply_to = _text(_metadata(row), "replyToMessageId")
        thread_id = _text(row, "threadId")
        target_dispatch = None
        if reply_to:
            explicit_rows = [
                dispatch_row
                for dispatch_row in dispatch_rows
                if reply_to == (_text(dispatch_row, "messageId") or _text(dispatch_row, "eventId"))
            ]
            if not explicit_rows and source_agent_id:
                parent_id = _followup_origin_id(reply_to, source_agent_id)
                explicit_rows = [
                    dispatch_row for dispatch_row in dispatch_rows
                    if parent_id and parent_id == (
                        _text(dispatch_row, "messageId") or _text(dispatch_row, "eventId")
                    )
                ]
            if (
                len(explicit_rows) == 1
                and source_agent_id
                and source_agent_id == _text(explicit_rows[0], "targetAgentId")
            ):
                target_dispatch = explicit_rows[0]
        elif thread_id and source_agent_id:
            unique_dispatch_id = _unique_thread_dispatch_id(thread_id, source_agent_id)
            visible_rows = [
                dispatch_row
                for dispatch_row in dispatch_rows
                if unique_dispatch_id
                and unique_dispatch_id
                == (_text(dispatch_row, "messageId") or _text(dispatch_row, "eventId"))
            ]
            if (
                len(visible_rows) == 1
                and thread_id == _text(visible_rows[0], "threadId")
                and source_agent_id == _text(visible_rows[0], "targetAgentId")
                and dispatch_inbox_agent_by_row_id.get(id(visible_rows[0])) == source_agent_id
            ):
                target_dispatch = visible_rows[0]
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
