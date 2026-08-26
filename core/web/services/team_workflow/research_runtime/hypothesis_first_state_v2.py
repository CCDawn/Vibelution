"""Canonical read-only projection for hypothesis-first workflow state V2.

The projector consumes existing durable facts.  It never repairs or writes an
owning store, and it keeps command-CAS and wire-representation versions
separate so telemetry cannot stale an otherwise valid command.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from core.research.competition.resources import CATALOG_ID, CATALOG_SHA256
from core.research.competition.result_set import is_official_question_id

from . import hypothesis_first_chain

_QUESTION_ID_PATTERN = re.compile(r"^SCI-\d{3}$")
_CANDIDATE_KIND = "hypothesis_candidate"
_REVIEW_LINK_KIND = "review_round_link"
_REVIEW_DISPATCH_ATTEMPT_KIND = "review_dispatch_attempt"
_COLLECTION_REQUEST_KIND = "collection_request"
_HUMAN_ADJUDICATION_KIND = "human_adjudication"
_RESET_AUDIT_KIND = "question_reset_audit"
_GENERATION_MEETING_TYPE = "hypothesis_candidate_generation"
_REVIEW_MEETING_TYPE = "hypothesis_review"
_EPOCH = "1970-01-01T00:00:00Z"
_TIMESTAMP_KEYS = {
    "createdAt",
    "updatedAt",
    "queuedAt",
    "startedAt",
    "heartbeatAt",
    "finishedAt",
    "closedAt",
    "decidedAt",
    "resetAt",
}
_STATE_VERSION_IGNORED_KEYS = {
    "computedAt",
    "representationVersion",
    "sourceCursor",
    "updatedAt",
    "queuedAt",
    "startedAt",
    "heartbeatAt",
    "finishedAt",
    "detectedAt",
    "itemCount",
    "expectedStateVersion",
}
_QUESTION_SNAPSHOT_CACHE_LOCK = threading.RLock()
_QUESTION_SNAPSHOT_CACHE: dict[
    tuple[str, str],
    tuple[tuple[tuple[str, int, int], ...], dict[str, Any]],
] = {}
_CHAT_ROOM_ROUND_STOPPED_STATUSES = {
    "cancelled",
    "canceled",
    "idle",
    "stopped",
    "stopped_by_user",
    "superseded",
    "terminated",
}
_CHAT_ROOM_ROUND_FAILED_STATUSES = {
    "error",
    "failed",
    "failed_provider",
    "failed_runtime",
    "stop_failed",
}
_CHAT_ROOM_ROUND_STOPPED_RUNTIME_STATUSES = {
    "cancelled",
    "canceled",
    "force_stopped",
    "orphan_reconciled",
    "orphaned_room_reconciled",
    "stopped",
    "terminated",
}
_CHAT_ROOM_RUN_KIND = "chat_room_round"


class HypothesisFirstStateScopeError(ValueError):
    """A team/question cannot produce a normal canonical snapshot."""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class HypothesisFirstStateSourceError(RuntimeError):
    """A required durable authority could not produce a trustworthy read."""

    code = "state_source_unavailable"
    status_code = 503

    def __init__(self, message: str) -> None:
        super().__init__(message)


def _record_projection_scene_event(
    event_code: str,
    *,
    team_id: str,
    question_id: str,
    source_error_type: str = "",
) -> None:
    """Best-effort projection observability; never blocks the failing read."""
    from core.web.services.runtime_scene_service import (
        record_runtime_scene_event_quietly,
    )

    record_runtime_scene_event_quietly(
        "team_workflow_orchestration",
        "hypothesis_first_state",
        event_code,
        level="warning",
        outcome="failed",
        fields={
            "teamId": str(team_id or ""),
            "questionId": str(question_id or ""),
            "sourceErrorType": source_error_type,
        },
    )


def _source_file_cursor(path: Path) -> tuple[str, int, int]:
    """Return a cheap cross-process cursor for one append-only authority."""

    resolved = str(path.resolve())
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (resolved, -1, -1)
    return (resolved, int(stat.st_size), int(stat.st_mtime_ns))


def _question_snapshot_signature(team_id: str) -> tuple[tuple[str, int, int], ...]:
    """Stamp every JSONL source replayed by ``_question_reset_snapshot``."""

    from core.web.services.team_workflow import (
        hypothesis_rounds,
        hypothesis_selection,
        meeting_rounds,
    )

    return tuple(
        _source_file_cursor(path)
        for path in (
            hypothesis_first_chain._storage_path(team_id),
            hypothesis_selection._storage_path(team_id),
            meeting_rounds._rounds_path(team_id),
            meeting_rounds._digests_path(team_id),
            meeting_rounds._decisions_path(team_id),
            hypothesis_rounds._storage_path(team_id),
        )
    )


def clear_hypothesis_first_state_v2_cache() -> None:
    """Clear process-local projector replay cache (tests/maintenance only)."""

    with _QUESTION_SNAPSHOT_CACHE_LOCK:
        _QUESTION_SNAPSHOT_CACHE.clear()


def _compact_question_snapshot(
    snapshot: Mapping[str, Any],
    question_id: str,
) -> dict[str, Any]:
    """Discard unrelated team history before a snapshot enters the cache."""

    normalized = question_id.upper()
    meeting_ids = {
        str(item or "").strip()
        for item in snapshot.get("targetMeetingIds") or []
        if str(item or "").strip()
    }
    round_ids = {
        str(item or "").strip()
        for item in snapshot.get("targetRoundIds") or []
        if str(item or "").strip()
    }
    return {
        "questionId": normalized,
        "chainRecords": [
            dict(record)
            for record in snapshot.get("chainRecords") or []
            if isinstance(record, Mapping)
            and str(record.get("questionId") or "").strip().upper() == normalized
        ],
        "selectionRecords": [
            dict(record)
            for record in snapshot.get("selectionRecords") or []
            if isinstance(record, Mapping)
            and str(record.get("questionId") or "").strip().upper() == normalized
        ],
        "meetingRecords": [
            dict(record)
            for record in snapshot.get("meetingRecords") or []
            if isinstance(record, Mapping)
            and str(record.get("meetingRoundId") or "") in meeting_ids
        ],
        "digestRecords": [
            dict(record)
            for record in snapshot.get("digestRecords") or []
            if isinstance(record, Mapping)
            and str(record.get("meetingRoundId") or "") in meeting_ids
        ],
        "decisionRecords": [
            dict(record)
            for record in snapshot.get("decisionRecords") or []
            if isinstance(record, Mapping)
            and str(record.get("meetingRoundId") or "") in meeting_ids
        ],
        "hypothesisRoundRecords": [
            dict(record)
            for record in snapshot.get("hypothesisRoundRecords") or []
            if isinstance(record, Mapping)
            and str(record.get("roundId") or "") in round_ids
        ],
        "targetMeetingIds": meeting_ids,
        "targetRoundIds": round_ids,
    }


def _cached_question_reset_snapshot(team_id: str, question_id: str) -> dict[str, Any]:
    """Reuse scoped source replay only while every durable file cursor matches.

    File cursors make correctness independent from browser SSE and from
    process-local write notifications: another worker/process changing any
    source invalidates the next read before the cached snapshot is returned.
    """

    key = (team_id, question_id)
    before = _question_snapshot_signature(team_id)
    with _QUESTION_SNAPSHOT_CACHE_LOCK:
        cached = _QUESTION_SNAPSHOT_CACHE.get(key)
        if cached is not None and cached[0] == before:
            return deepcopy(cached[1])

    # Avoid caching a cross-file observation while an append/atomic rewrite is
    # in flight. One retry is sufficient; a continuously changing workload
    # still gets a fresh uncached snapshot rather than stale data.
    raw_snapshot = hypothesis_first_chain._question_reset_snapshot(team_id, question_id)
    after = _question_snapshot_signature(team_id)
    if before != after:
        before = after
        raw_snapshot = hypothesis_first_chain._question_reset_snapshot(team_id, question_id)
        after = _question_snapshot_signature(team_id)
    snapshot = _compact_question_snapshot(raw_snapshot, question_id)
    if before == after:
        with _QUESTION_SNAPSHOT_CACHE_LOCK:
            _QUESTION_SNAPSHOT_CACHE[key] = (after, deepcopy(snapshot))
    return snapshot


def _phase(
    lifecycle: str = "not_started",
    outcome: str = "none",
    actionability: str = "idle",
    *,
    updated_at: str | None = None,
    problems: Sequence[Mapping[str, Any]] = (),
    attempt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "lifecycle": lifecycle,
        "outcome": outcome,
        "actionability": actionability,
        "attempt": dict(attempt) if attempt is not None else None,
        "updatedAt": updated_at,
        "problems": [dict(item) for item in problems],
    }


def _problem(
    code: str,
    message: str,
    *,
    category: str = "integrity",
    severity: str = "error",
    recoverable: bool = True,
    source_kind: str,
    source_id: str | None = None,
    detected_at: str = _EPOCH,
) -> dict[str, Any]:
    return {
        "code": code,
        "category": category,
        "severity": severity,
        "message": message,
        "recoverable": recoverable,
        "sourceKind": source_kind,
        "sourceId": source_id,
        "detectedAt": detected_at,
    }


def _latest(records: Sequence[Mapping[str, Any]], identity: str) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for source in records:
        record = dict(source)
        record_id = str(record.get(identity) or "").strip()
        if record_id:
            by_id[record_id] = record
        else:
            anonymous.append(record)
    return anonymous + list(by_id.values())


def _timestamp(record: Mapping[str, Any]) -> str | None:
    for key in ("updatedAt", "finishedAt", "closedAt", "createdAt", "startedAt"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return None


def _latest_timestamp(*values: Any) -> str:
    found: list[str] = []

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                visit(child, str(child_key))
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for child in value:
                visit(child, key)
        elif key in _TIMESTAMP_KEYS:
            text = str(value or "").strip()
            if text:
                found.append(text)

    for value in values:
        visit(value)
    return max(found, default=_EPOCH)


def _canonical_hash(value: Any, *, length: int = 16) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


def _selection_version_for_link(
    link: Mapping[str, Any],
    *,
    selection_by_id: Mapping[str, Mapping[str, Any]],
    question_id: str,
    reset_id: str,
) -> str:
    """Resolve a review link's selection version, including legacy links."""

    explicit = str(link.get("selectionVersion") or "").strip()
    if explicit:
        return explicit
    selection_id = str(link.get("selectionId") or "").strip()
    selection = selection_by_id.get(selection_id)
    if not isinstance(selection, Mapping):
        return ""
    return hypothesis_first_chain.selection_version_for(
        question_id=question_id,
        selected_candidate_ids=selection.get("selectedCandidateIds"),
        previous_selection_id=str(selection.get("previousSelectionId") or ""),
        reset_id=reset_id,
        scope_hash=str(selection.get("scopeHash") or ""),
    )


def _ordered_link_candidate_ids(links: Sequence[Mapping[str, Any]]) -> list[str]:
    """Recover candidate order from durable review bindings only."""

    ordered = sorted(
        [item for item in links if isinstance(item, Mapping)],
        key=lambda item: (
            int(item.get("candidateOrder") or 0),
            str(item.get("createdAt") or ""),
            str(item.get("candidateId") or ""),
        ),
    )
    return list(
        dict.fromkeys(
            str(item.get("candidateId") or "").strip()
            for item in ordered
            if str(item.get("candidateId") or "").strip()
        )
    )


def _state_relevant(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _state_relevant(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            if str(key) not in _STATE_VERSION_IGNORED_KEYS
        }
    if isinstance(value, list):
        return [_state_relevant(item) for item in value]
    return value


def finalize_state_versions(
    snapshot: Mapping[str, Any],
    *,
    reset_id: str,
) -> dict[str, Any]:
    """Attach opaque CAS and representation tokens without circular hashes."""

    result = deepcopy(dict(snapshot))
    result.pop("representationVersion", None)
    result.pop("sourceCursor", None)
    result.pop("stateVersion", None)
    action_relevant = _state_relevant(result)
    state_version = f"hf2-action:{reset_id}:{_canonical_hash(action_relevant)}"
    result["stateVersion"] = state_version
    for action in result.get("allowedActions") or []:
        if isinstance(action, dict) and action.get("kind") == "command":
            action["expectedStateVersion"] = state_version
    representation_body = deepcopy(result)
    representation_body.pop("representationVersion", None)
    representation_version = (
        f"hf2-repr:{reset_id}:{_canonical_hash(representation_body)}"
    )
    result["representationVersion"] = representation_version
    if "sourceCursor" in snapshot:
        result["sourceCursor"] = deepcopy(snapshot["sourceCursor"])
    return result


def _command_action(
    command: str,
    *,
    label: str,
    target_phase: str,
    payload: Mapping[str, Any],
    action_id: str | None = None,
    target_node_id: str | None = None,
    input_schema_ref: str | None = None,
    requires_confirmation: bool = False,
    confirmation_text: str | None = None,
) -> dict[str, Any]:
    resolved_id = action_id or command.replace("_", "-")
    return {
        "kind": "command",
        "actionId": resolved_id,
        "label": label,
        "enabled": True,
        "disabledReason": None,
        "targetPhase": target_phase,
        "targetNodeId": target_node_id,
        "command": command,
        "payload": dict(payload),
        "inputSchemaRef": input_schema_ref,
        "idempotencyKey": f"hf2:{resolved_id}:{_canonical_hash(payload)}",
        "expectedStateVersion": "hf2-action:pending:pending",
        "requiresConfirmation": requires_confirmation,
        "confirmationText": confirmation_text,
    }


def _navigation_anchor(
    *,
    question_id: str,
    selection_id: str | None,
    candidate_id: str | None,
    meeting: Mapping[str, Any],
    return_to: str,
) -> dict[str, Any]:
    meeting_id = str(meeting.get("meetingRoundId") or "").strip() or None
    room_id = str(meeting.get("linkedChatRoomId") or "").strip() or None
    return_label = "返回挑战杯流程"
    if room_id:
        deep_link = "/chat?" + urlencode(
            {
                "room": room_id,
                "returnTo": return_to,
                "returnLabel": return_label,
            }
        )
        status = "ready"
        degraded_reason = None
    else:
        deep_link = None
        status = "degraded"
        degraded_reason = "讨论房间尚未就绪"
    return {
        "status": status,
        "degradedReason": degraded_reason,
        "roomId": room_id,
        "meetingRoundId": meeting_id,
        "questionId": question_id,
        "selectionId": selection_id,
        "candidateId": candidate_id,
        "deepLink": deep_link,
        "returnTo": return_to,
        "returnLabel": return_label,
    }


def _navigation_action(
    anchor: Mapping[str, Any],
    *,
    candidate_id: str | None = None,
    action_id: str | None = None,
    label: str = "进入候选评审室",
    target_phase: str = "review",
    target_node_id: str = "hf_review",
) -> dict[str, Any]:
    return {
        "kind": "navigation",
        "actionId": action_id or (
            f"open-review-room:{candidate_id}"
            if candidate_id
            else "open-discussion-room"
        ),
        "label": label,
        "enabled": bool(anchor.get("deepLink")),
        "disabledReason": None if anchor.get("deepLink") else str(
            anchor.get("degradedReason") or "讨论房间尚未就绪"
        ),
        "targetPhase": target_phase,
        "targetNodeId": target_node_id,
        "navigation": dict(anchor),
    }


def _linked_chat_room_round_problem(
    meeting: Mapping[str, Any],
    chat_room_round_snapshots: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any] | None:
    """Project a terminal linked room round as a meeting execution problem.

    Meeting records are append-only workflow facts, while the chat-room
    WorkRun is the authority for whether a bound discussion executor is still
    alive.  Only an explicitly persisted terminal snapshot is strong enough to
    override an ``open`` meeting; a missing snapshot deliberately preserves the
    legacy projection instead of guessing that the round stopped.
    """

    if not isinstance(chat_room_round_snapshots, Mapping):
        return None
    round_ids = [
        str(round_id or "").strip()
        for round_id in list(meeting.get("chatRoomRoundIds") or [])
        if str(round_id or "").strip()
    ]
    # ``chatRoomRoundIds`` is append-only: a retry appends a new room round
    # and the last bound id is the only current execution authority.  Older
    # terminal rounds remain useful history but must not block a newer round.
    round_id = round_ids[-1] if round_ids else ""
    if not round_id:
        return None
    snapshot = chat_room_round_snapshots.get(round_id)
    if not isinstance(snapshot, Mapping):
        return None
    snapshot_id = str(
        snapshot.get("runId") or snapshot.get("roundId") or ""
    ).strip()
    if snapshot_id and snapshot_id != round_id:
        return None
    status = str(
        snapshot.get("status")
        or snapshot.get("currentPhase")
        or snapshot.get("phase")
        or ""
    ).strip().lower()
    runtime_status = str(snapshot.get("runtimeStatus") or "").strip().lower()
    reconciliation_source = str(
        snapshot.get("reconciliationSource") or ""
    ).strip().lower()
    is_orphaned = (
        reconciliation_source == "missing_process_controller"
        or "orphan" in runtime_status
        or "orphan" in reconciliation_source
    )
    is_stopped = status in _CHAT_ROOM_ROUND_STOPPED_STATUSES or runtime_status in {
        *_CHAT_ROOM_ROUND_STOPPED_RUNTIME_STATUSES,
    }
    is_failed = status in _CHAT_ROOM_ROUND_FAILED_STATUSES or runtime_status in {
        "error",
        "failed",
        "failed_provider",
        "failed_runtime",
    }
    if not (is_orphaned or is_stopped or is_failed):
        return None
    if is_orphaned:
        code = "discussion_round_orphaned"
        fallback = "绑定的讨论轮次因执行器丢失已停止"
    elif is_failed:
        code = "discussion_round_failed"
        fallback = "绑定的讨论轮次执行失败"
    else:
        code = "discussion_round_stopped"
        fallback = "绑定的讨论轮次已停止"
    reason = ""
    for key in (
        "forceStopReason",
        "stopReason",
        "reason",
        "error",
        "summary",
        "runtimeStatus",
        "reconciliationSource",
    ):
        candidate = str(snapshot.get(key) or "").strip()
        if candidate:
            reason = candidate
            break
    message = f"{fallback}：{reason}" if reason else fallback
    return _problem(
        code,
        message,
        category="execution",
        source_kind="chat_room_round",
        source_id=round_id,
        detected_at=_timestamp(snapshot) or _timestamp(meeting) or _EPOCH,
    )


def _load_chat_room_round_snapshot(round_id: str) -> Mapping[str, Any] | None:
    """Read one chat-room WorkRun through the public runtime-store API.

    ``chat_room_service`` exposes only active/latest summaries; the projector
    needs an arbitrary bound round and must not call its reconciliation facade.
    ``WorkRunStore.load_snapshot`` is a read-only infrastructure accessor, so
    this keeps the projection independent of the service's private store
    factory and its side effects.
    """

    from core.runtime_manager import work_run_store

    return work_run_store.WorkRunStore(
        root=work_run_store.WORK_RUNS_DIR,
    ).load_snapshot(_CHAT_ROOM_RUN_KIND, round_id)


def _meeting_phase(
    meeting: Mapping[str, Any],
    *,
    chat_room_round_snapshots: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], str]:
    status = str(meeting.get("status") or "").strip().lower()
    updated_at = _timestamp(meeting)
    summary_error = meeting.get("summaryError") or meeting.get("summaryDraftError")
    if summary_error:
        if isinstance(summary_error, Mapping):
            summary_message = str(
                summary_error.get("message")
                or summary_error.get("code")
                or "会议纪要生成失败"
            )
            summary_code = str(summary_error.get("code") or "meeting_summary_failed")
        else:
            summary_message = str(summary_error)
            summary_code = "meeting_summary_failed"
        problem = _problem(
            summary_code,
            summary_message,
            category="execution",
            source_kind="meeting_round",
            source_id=str(meeting.get("meetingRoundId") or "") or None,
            detected_at=updated_at or _EPOCH,
        )
        return _phase(
            "failed",
            "none",
            "available",
            updated_at=updated_at,
            problems=[problem],
        ), status
    linked_round_problem = None
    if status in {"open", "summarizing"}:
        linked_round_problem = _linked_chat_room_round_problem(
            meeting,
            chat_room_round_snapshots,
        )
    if linked_round_problem is not None:
        return _phase(
            "failed",
            "none",
            "blocked",
            updated_at=updated_at
            or linked_round_problem.get("detectedAt")
            or _EPOCH,
            problems=[linked_round_problem],
        ), "linked_round_stopped"
    if status == "closed":
        return _phase("completed", "succeeded", "terminal", updated_at=updated_at), status
    if status == "awaiting_approval":
        return _phase("waiting_human", "none", "waiting_user", updated_at=updated_at), status
    if status in {"open", "summarizing"}:
        return _phase("running", "none", "executing", updated_at=updated_at), status
    if status in {"blocked", "stalled"}:
        problem = _problem(
            "discussion_stalled",
            str(
                meeting.get("stalledReason")
                or meeting.get("blocker", {}).get("message")
                if isinstance(meeting.get("blocker"), Mapping)
                else "讨论驱动器已停止推进"
            ),
            category="execution",
            source_kind="meeting_round",
            source_id=str(meeting.get("meetingRoundId") or "") or None,
            detected_at=updated_at or _EPOCH,
        )
        return _phase(
            "failed",
            "none",
            "available",
            updated_at=updated_at,
            problems=[problem],
        ), status
    problem = _problem(
        "meeting_status_unknown",
        "会议状态无法映射到规范状态",
        source_kind="meeting_round",
        source_id=str(meeting.get("meetingRoundId") or "") or None,
        detected_at=updated_at or _EPOCH,
    )
    return _phase("not_started", "none", "blocked", updated_at=updated_at, problems=[problem]), status


def _dispatch_attempt_view(attempt: Mapping[str, Any]) -> dict[str, Any] | None:
    """Shape one durable review-dispatch attempt as the wire ``WorkflowAttempt``."""
    if not str(attempt.get("attemptId") or "").strip():
        return None
    return {
        "attemptId": str(attempt.get("attemptId") or ""),
        "number": int(attempt.get("attemptNumber") or 1),
        "lifecycle": str(attempt.get("lifecycle") or "queued"),
        "queuedAt": str(attempt.get("createdAt") or "").strip() or None,
        "startedAt": None,
        "heartbeatAt": None,
        "finishedAt": str(attempt.get("updatedAt") or "").strip() or None,
        "supersedesAttemptId": None,
    }


def _review_candidate(
    *,
    question_id: str,
    selection_id: str,
    candidate_id: str,
    candidate_order: int,
    round_index: int,
    link: Mapping[str, Any] | None,
    meeting: Mapping[str, Any] | None,
    return_to: str,
    dispatch_attempt: Mapping[str, Any] | None = None,
    chat_room_round_snapshots: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if not link or not meeting:
        attempt_lifecycle = str((dispatch_attempt or {}).get("lifecycle") or "").strip()
        if attempt_lifecycle in {"queued", "running"}:
            # Dispatch intent is durable but the meeting side effect has not
            # landed yet (in flight, or interrupted mid-fan-out).
            in_flight = _phase(
                "queued",
                "none",
                "waiting_system",
                updated_at=_timestamp(dispatch_attempt or {}),
                attempt=_dispatch_attempt_view(dispatch_attempt or {}),
            )
            return {
                **in_flight,
                "candidateId": candidate_id,
                "candidateOrder": candidate_order,
                "selectionId": selection_id,
                "roundIndex": round_index,
                "meetingRoundId": None,
                "discussionAnchor": None,
                "discussion": in_flight,
                "summarization": _phase(),
                "approval": _phase(),
            }
        if attempt_lifecycle == "failed":
            error = str((dispatch_attempt or {}).get("error") or "").strip()
            problem = _problem(
                "review_dispatch_failed",
                error or "候选评审会议分发失败",
                category="execution",
                source_kind="review_dispatch_attempt",
                source_id=str((dispatch_attempt or {}).get("attemptId") or "") or None,
                detected_at=_timestamp(dispatch_attempt or {}) or _EPOCH,
            )
            failed = _phase(
                "failed",
                "none",
                "available",
                updated_at=_timestamp(dispatch_attempt or {}),
                problems=[problem],
                attempt=_dispatch_attempt_view(dispatch_attempt or {}),
            )
            return {
                **failed,
                "candidateId": candidate_id,
                "candidateOrder": candidate_order,
                "selectionId": selection_id,
                "roundIndex": round_index,
                "meetingRoundId": None,
                "discussionAnchor": None,
                "discussion": failed,
                "summarization": _phase(),
                "approval": _phase(),
            }
        if attempt_lifecycle == "completed":
            # The attempt claims success but its link/meeting is unreadable:
            # an integrity defect, never a fresh dispatch.
            problem = _problem(
                "review_dispatch_state_missing",
                "评审分发已记录完成，但会议关联缺失",
                source_kind="review_dispatch_attempt",
                source_id=str((dispatch_attempt or {}).get("attemptId") or "") or None,
                detected_at=_timestamp(dispatch_attempt or {}) or _EPOCH,
            )
            blocked = _phase(
                "not_started",
                "none",
                "blocked",
                updated_at=_timestamp(dispatch_attempt or {}),
                problems=[problem],
                attempt=_dispatch_attempt_view(dispatch_attempt or {}),
            )
            return {
                **blocked,
                "candidateId": candidate_id,
                "candidateOrder": candidate_order,
                "selectionId": selection_id,
                "roundIndex": round_index,
                "meetingRoundId": None,
                "discussionAnchor": None,
                "discussion": blocked,
                "summarization": _phase(),
                "approval": _phase(),
            }
        problem = _problem(
            "review_dispatch_missing",
            "已记录选择，但候选评审会议尚未建立",
            source_kind="review_dispatch",
            source_id=selection_id,
        )
        blocked = _phase("not_started", "none", "blocked", problems=[problem])
        return {
            **blocked,
            "candidateId": candidate_id,
            "candidateOrder": candidate_order,
            "selectionId": selection_id,
            "roundIndex": round_index,
            "meetingRoundId": None,
            "discussionAnchor": None,
            "discussion": blocked,
            "summarization": _phase(),
            "approval": _phase(),
        }

    candidate_phase, status = _meeting_phase(
        meeting,
        chat_room_round_snapshots=chat_room_round_snapshots,
    )
    if status == "closed":
        discussion = _phase("completed", "succeeded", "terminal", updated_at=_timestamp(meeting))
        summarization = deepcopy(discussion)
        approval = deepcopy(discussion)
    elif status == "awaiting_approval":
        discussion = _phase("completed", "succeeded", "terminal", updated_at=_timestamp(meeting))
        summarization = deepcopy(discussion)
        approval = _phase("waiting_human", "none", "waiting_user", updated_at=_timestamp(meeting))
    elif status == "summarizing":
        discussion = _phase("completed", "succeeded", "terminal", updated_at=_timestamp(meeting))
        summarization = _phase("running", "none", "waiting_system", updated_at=_timestamp(meeting))
        approval = _phase()
    else:
        discussion = deepcopy(candidate_phase)
        summarization = _phase()
        approval = _phase()
    anchor = _navigation_anchor(
        question_id=question_id,
        selection_id=selection_id,
        candidate_id=candidate_id,
        meeting=meeting,
        return_to=return_to,
    )
    return {
        **candidate_phase,
        "candidateId": candidate_id,
        "candidateOrder": candidate_order,
        "selectionId": selection_id,
        "roundIndex": round_index,
        "meetingRoundId": str(meeting.get("meetingRoundId") or "") or None,
        "discussionAnchor": anchor,
        "discussion": discussion,
        "summarization": summarization,
        "approval": approval,
    }


def _meeting_is_stalled(meeting: Mapping[str, Any]) -> bool:
    """Return whether an operator-visible discussion recovery is warranted.

    A room can remain ``open`` after its executor has died.  The meeting
    runtime records explicit blocker/driver markers for newer records, while
    older records only expose the terminal ``blocked``/``stalled`` status.
    Keep this predicate conservative: a normal open meeting still gets a
    navigation action, but does not receive destructive recovery commands.
    """

    status = str(meeting.get("status") or "").strip().lower()
    if status in {"blocked", "stalled"}:
        return True
    for key in (
        "stalledAt",
        "stalledReason",
        "discussionDriverError",
        "summaryDraftError",
        "summaryError",
    ):
        if meeting.get(key):
            return True
    driver = meeting.get("discussionDriver")
    return isinstance(driver, Mapping) and str(driver.get("status") or "").lower() in {
        "failed",
        "stalled",
    }


def _meeting_recovery_actions(
    *,
    question_id: str,
    meeting: Mapping[str, Any],
    target_phase: str,
    target_node_id: str,
    selection_id: str | None,
    candidate_id: str | None,
    return_to: str,
    label: str,
    chat_room_round_snapshots: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Project navigation and operator recovery commands for one meeting."""

    meeting_id = str(meeting.get("meetingRoundId") or "").strip()
    anchor = _navigation_anchor(
        question_id=question_id,
        selection_id=selection_id,
        candidate_id=candidate_id,
        meeting=meeting,
        return_to=return_to,
    )
    actions: list[dict[str, Any]] = [
        _navigation_action(
            anchor,
            candidate_id=candidate_id,
            action_id=(
                f"open-review-room:{candidate_id}"
                if candidate_id
                else f"open-generation-room:{meeting_id}"
            ),
            label=label,
            target_phase=target_phase,
            target_node_id=target_node_id,
        )
    ]
    status = str(meeting.get("status") or "").strip().lower()
    linked_round_problem = _linked_chat_room_round_problem(
        meeting,
        chat_room_round_snapshots,
    )
    if status in {"open", "summarizing"} and linked_round_problem:
        # The linked WorkRun is terminal, so there is no live executor to
        # resume or stop.  Review meetings can safely supersede a zero-speech
        # failed attempt and open the next budgeted round; the owning service
        # rechecks terminality and completed messages under its lock.
        if str(meeting.get("meetingType") or "").strip().lower() == "hypothesis_review":
            actions.append(
                _command_action(
                    "reopen_review",
                    action_id=f"reopen-review:{meeting_id}",
                    label="重新发起评审讨论",
                    target_phase=target_phase,
                    target_node_id=target_node_id,
                    payload={"meetingRoundId": meeting_id},
                )
            )
        return actions, anchor
    stalled = _meeting_is_stalled(meeting)
    if status == "awaiting_approval":
        actions.append(
            _command_action(
                "approve_summary",
                action_id=(
                    f"approve-summary:{candidate_id}"
                    if candidate_id
                    else f"approve-generation-summary:{meeting_id}"
                ),
                label="确认候选纪要" if candidate_id else "确认候选生成纪要",
                target_phase=target_phase,
                target_node_id=target_node_id,
                payload={"meetingRoundId": meeting_id},
                input_schema_ref="hypothesis-first/approve-summary/v1",
            )
        )
    if stalled:
        # ``resume_discussion`` is the non-destructive first recovery.  The
        # stop/retry choices are both precise to this meeting and are useful
        # when the executor has left an open round with no progress.
        actions.append(
            _command_action(
                "resume_discussion",
                action_id=f"resume-discussion:{meeting_id}",
                label="恢复讨论",
                target_phase=target_phase,
                target_node_id=target_node_id,
                payload={"meetingRoundId": meeting_id},
            )
        )
        actions.append(
            _command_action(
                "stop_discussion",
                action_id=f"stop-discussion:{meeting_id}",
                label="停止本次讨论",
                target_phase=target_phase,
                target_node_id=target_node_id,
                payload={"meetingRoundId": meeting_id},
                requires_confirmation=True,
                confirmation_text="停止后将保留失败尝试，并允许重新发起精确的讨论恢复。",
            )
        )
        actions.append(
            _command_action(
                "regenerate_summary",
                action_id=f"regenerate-summary:{meeting_id}",
                label="重试生成纪要",
                target_phase=target_phase,
                target_node_id=target_node_id,
                payload={"meetingRoundId": meeting_id},
            )
        )
    elif status == "summarizing" and meeting.get("summaryDraftError"):
        actions.append(
            _command_action(
                "regenerate_summary",
                action_id=f"regenerate-summary:{meeting_id}",
                label="重试生成纪要",
                target_phase=target_phase,
                target_node_id=target_node_id,
                payload={"meetingRoundId": meeting_id},
            )
        )
    return actions, anchor


def _aggregate(states: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    result = {"total": len(states), "completed": 0, "pending": 0, "failed": 0, "blocked": 0}
    for state in states:
        if state.get("actionability") == "blocked":
            result["blocked"] += 1
        elif state.get("lifecycle") == "failed":
            result["failed"] += 1
        elif state.get("lifecycle") == "completed":
            result["completed"] += 1
        else:
            result["pending"] += 1
    return result


def _collection_request_state(request: Mapping[str, Any]) -> dict[str, Any]:
    status = str(request.get("status") or "").strip().lower()
    run_status = str(request.get("collectionRunStatus") or "").strip().lower()
    request_id = str(request.get("requestId") or "").strip()
    run_id = str(request.get("collectionRunId") or "").strip() or None
    updated_at = _timestamp(request)
    if run_status in {"failed", "cancelled"}:
        child = _phase("failed", "none", "available", updated_at=updated_at)
    elif run_status in {"succeeded", "completed"}:
        child = _phase("completed", "succeeded", "terminal", updated_at=updated_at)
    elif run_id:
        child = _phase("running", "none", "waiting_system", updated_at=updated_at)
    else:
        child = _phase()
    child["runId"] = run_id
    handed_off = status == "handed_off"
    if handed_off:
        handoff = _phase("completed", "succeeded", "terminal", updated_at=updated_at)
        request_phase = _phase("completed", "succeeded", "terminal", updated_at=updated_at)
    elif child["lifecycle"] == "completed":
        handoff = _phase("waiting_human", "none", "waiting_user", updated_at=updated_at)
        request_phase = _phase("waiting_human", "none", "waiting_user", updated_at=updated_at)
    elif child["lifecycle"] == "failed":
        handoff = _phase()
        request_phase = _phase("failed", "none", "available", updated_at=updated_at)
    elif run_id:
        handoff = _phase()
        request_phase = _phase("running", "none", "waiting_system", updated_at=updated_at)
    else:
        missing = _problem(
            "collection_child_missing",
            "资料搜集请求尚未建立子运行",
            source_kind="collection_request",
            source_id=request_id or None,
            detected_at=updated_at or _EPOCH,
        )
        handoff = _phase()
        request_phase = _phase("completed", "partial", "blocked", updated_at=updated_at, problems=[missing])
    handoff.update(
        {
            "handoffId": str(request.get("handoffId") or request.get("handoffRef") or "") or None,
            "targetRoundIndex": request.get("targetRoundIndex"),
        }
    )
    return {
        **request_phase,
        "requestId": request_id,
        "queryCount": len(list((request.get("searchEnvelope") or {}).get("keywords") or []))
        if isinstance(request.get("searchEnvelope"), Mapping)
        else 0,
        "childRun": child,
        "sources": [],
        "handoff": handoff,
    }


def _project_program_output_record(
    *,
    question_id: str,
    record: Mapping[str, Any],
    run_id: str,
    artifact_ref: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], str]:
    required_gate_keys = (
        "H1_problem_understanding",
        "H2_hypothesis_selection",
        "H3_research_plan",
        "H4_external_output",
    )
    raw_gates = record.get("humanGates")
    raw_gates = raw_gates if isinstance(raw_gates, Mapping) else {}
    raw_decisions = raw_gates.get("decisions")
    raw_decisions = raw_decisions if isinstance(raw_decisions, Mapping) else {}
    allowed_decisions = {"pending", "approved", "revision_requested", "rejected"}
    problems: list[dict[str, Any]] = []
    decisions: dict[str, str] = {}
    for key in required_gate_keys:
        decision = str(raw_decisions.get(key) or "pending")
        if decision not in allowed_decisions:
            problems.append(
                _problem(
                    "program_human_gate_invalid",
                    "Challenge Program 人工审核状态无法映射",
                    source_kind="challenge_question_output",
                    source_id=str(record.get("recordId") or "") or None,
                    detected_at=_timestamp(record) or _EPOCH,
                )
            )
            decision = "pending"
        decisions[key] = decision
    approved_count = sum(value == "approved" for value in decisions.values())
    review = record.get("review")
    review = review if isinstance(review, Mapping) else {}
    actions: list[dict[str, Any]] = []
    validation = record.get("validation")
    validation = validation if isinstance(validation, Mapping) else {}
    validation_passed = (
        validation.get("schemaValidation") == "passed"
        and validation.get("citationValidation") == "passed"
        and validation.get("semanticValidation") == "passed"
        and validation.get("officialModelCall") is True
    )
    if not validation_passed:
        validation_problem = _problem(
            "program_candidate_validation_failed",
            "Challenge Program 候选输出尚未通过完整校验或缺少官方模型调用证据",
            source_kind="challenge_question_output",
            source_id=str(record.get("recordId") or "") or None,
            detected_at=_timestamp(record) or _EPOCH,
        )
        program_phase = _phase(
            "not_started",
            "none",
            "blocked",
            updated_at=_timestamp(record),
            problems=[*problems, validation_problem],
        )
        actions.append(
            _command_action(
                "archive_run",
                action_id=f"archive-formal-run:{run_id}",
                label="归档并重建正式运行",
                target_phase="program_delivery",
                target_node_id="formal_runtime",
                payload={"runId": run_id},
                requires_confirmation=True,
                confirmation_text="当前交付记录校验失败。归档正式运行后可重新创建并补齐上游证据。",
            )
        )
        return (
            {
                **program_phase,
                "deliveryStatus": "succeeded",
                "deliveryArtifactRef": artifact_ref,
                "handoffStatus": "registered",
                "outputRecordId": str(record.get("recordId") or "") or None,
                "outputRunId": run_id or None,
                "humanReviewStatus": "not_started",
                "humanGates": {
                    "decisions": decisions,
                    "reviewer": str(review.get("reviewer") or "") or None,
                    "rationale": str(review.get("rationale") or "") or None,
                    "decidedAt": str(review.get("decidedAt") or "") or None,
                },
                "approvedGateCount": approved_count,
                "requiredGateCount": 4,
            },
            [*problems, validation_problem],
            actions,
            "program_delivery",
        )
    if approved_count == 4:
        human_status = "approved"
        program_phase = _phase(
            "completed", "succeeded", "terminal", updated_at=_timestamp(record), problems=problems
        )
        phase = "completed"
    elif any(value == "revision_requested" for value in decisions.values()):
        human_status = "revision_requested"
        program_phase = _phase(
            "completed", "rejected", "available", updated_at=_timestamp(record), problems=problems
        )
        phase = "program_delivery"
        actions.append(
            _command_action(
                "create_formal_revision",
                label="创建正式研究修订",
                target_phase="program_delivery",
                target_node_id="formal_runtime",
                payload={
                    "runId": run_id,
                    "outputRecordId": str(record.get("recordId") or ""),
                },
            )
        )
    elif any(value == "rejected" for value in decisions.values()):
        human_status = "rejected"
        program_phase = _phase(
            "completed", "rejected", "terminal", updated_at=_timestamp(record), problems=problems
        )
        phase = "program_delivery"
    else:
        human_status = "waiting_human"
        program_phase = _phase(
            "waiting_human", "none", "waiting_user", updated_at=_timestamp(record), problems=problems
        )
        phase = "program_delivery"
        actions.append(
            _command_action(
                "record_program_review",
                label="审核 H1–H4",
                target_phase="program_delivery",
                target_node_id="program_delivery",
                payload={"questionId": question_id, "outputRunId": run_id},
                input_schema_ref="challenge-program/h1-h4-review/v1",
            )
        )
    return (
        {
            **program_phase,
            "deliveryStatus": "succeeded",
            "deliveryArtifactRef": artifact_ref,
            "handoffStatus": "registered",
            "outputRecordId": str(record.get("recordId") or "") or None,
            "outputRunId": run_id or None,
            "humanReviewStatus": human_status,
            "humanGates": {
                "decisions": decisions,
                "reviewer": str(review.get("reviewer") or "") or None,
                "rationale": str(review.get("rationale") or "") or None,
                "decidedAt": str(review.get("decidedAt") or "") or None,
            },
            "approvedGateCount": approved_count,
            "requiredGateCount": 4,
        },
        problems,
        actions,
        phase,
    )


def _project_formal_and_program(
    *,
    question_id: str,
    formal_runs: Sequence[Mapping[str, Any]],
    formal_snapshots: Mapping[str, Mapping[str, Any]],
    program_output: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], str | None]:
    runs = [
        dict(item)
        for item in formal_runs
        if str(item.get("questionId") or "").strip().upper() == question_id
        and str(item.get("status") or "").strip().lower() != "archived"
    ]
    empty_formal = {
        **_phase(),
        "runId": None,
        "runVersion": None,
        "runStatus": None,
        "completionKind": None,
        "lineageDisposition": None,
        "isCurrentRevision": False,
        "parentRunId": None,
        "childRunIds": [],
        "currentNodeIds": [],
    }
    empty_program = {
        **_phase(),
        "deliveryStatus": "not_started",
        "deliveryArtifactRef": None,
        "handoffStatus": "not_started",
        "outputRecordId": None,
        "outputRunId": None,
        "humanReviewStatus": "not_started",
        "humanGates": {
            "decisions": {
                "H1_problem_understanding": "pending",
                "H2_hypothesis_selection": "pending",
                "H3_research_plan": "pending",
                "H4_external_output": "pending",
            },
            "reviewer": None,
            "rationale": None,
            "decidedAt": None,
        },
        "approvedGateCount": 0,
        "requiredGateCount": 4,
    }
    record = (
        dict(program_output.get("record") or {})
        if isinstance(program_output, Mapping)
        and isinstance(program_output.get("record"), Mapping)
        else {}
    )
    if not runs:
        if not record:
            return empty_formal, empty_program, [], [], None
        package = record.get("resultPackage")
        package = package if isinstance(package, Mapping) else {}
        program, output_problems, output_actions, phase = _project_program_output_record(
            question_id=question_id,
            record=record,
            run_id=str(record.get("runId") or "").strip(),
            artifact_ref=str(package.get("locator") or "").strip() or None,
        )
        return empty_formal, program, output_problems, output_actions, phase

    by_id = {str(item.get("runId") or ""): item for item in runs}
    children_by_parent: dict[str, list[str]] = {}
    for item in runs:
        parent_id = str(item.get("parentRunId") or "").strip()
        run_id = str(item.get("runId") or "").strip()
        if parent_id and run_id:
            children_by_parent.setdefault(parent_id, []).append(run_id)
    for item in runs:
        run_id = str(item.get("runId") or "").strip()
        explicit = [
            str(child).strip()
            for child in list(item.get("childRunIds") or [])
            if str(child).strip()
        ]
        if explicit:
            children_by_parent[run_id] = list(
                dict.fromkeys(children_by_parent.get(run_id, []) + explicit)
            )
    leaves = [
        item
        for item in runs
        if not [child for child in children_by_parent.get(str(item.get("runId") or ""), []) if child in by_id]
    ]
    candidates = leaves or runs
    candidates.sort(
        key=lambda item: (
            str(item.get("updatedAt") or item.get("createdAt") or ""),
            str(item.get("runId") or ""),
        )
    )
    current = candidates[-1]
    current_id = str(current.get("runId") or "")
    current_children = children_by_parent.get(current_id, [])
    problems: list[dict[str, Any]] = []
    lineage_conflict = len(leaves) > 1
    if lineage_conflict:
        problems.append(
            _problem(
                "formal_run_lineage_conflict",
                "正式运行存在多个互斥的当前修订",
                source_kind="formal_run",
                source_id=current_id or None,
                detected_at=_timestamp(current) or _EPOCH,
            )
        )
    raw_status = str(current.get("status") or "").strip().lower()
    run_status = "queued" if raw_status == "created" else raw_status
    lifecycle = "running"
    outcome = "none"
    actionability = "executing"
    if run_status == "queued":
        lifecycle, actionability = "queued", "waiting_system"
    elif run_status == "waiting_human":
        lifecycle, actionability = "waiting_human", "waiting_user"
    elif run_status in {"blocked", "reconciliation_required"}:
        lifecycle, actionability = "running", "blocked"
    elif run_status == "succeeded":
        lifecycle, outcome, actionability = "completed", "succeeded", "terminal"
    elif run_status == "failed":
        lifecycle, actionability = "failed", "available"
    elif run_status == "cancelled":
        lifecycle, actionability = "cancelled", "available"
    elif run_status == "archived":
        lifecycle, outcome, actionability = "completed", "succeeded", "terminal"
    elif run_status != "running":
        actionability = "blocked"
        problems.append(
            _problem(
                "formal_run_status_unknown",
                "正式运行状态无法映射",
                source_kind="formal_run",
                source_id=current_id or None,
                detected_at=_timestamp(current) or _EPOCH,
            )
        )
    if lineage_conflict:
        actionability = "blocked"
    current_snapshot = dict(formal_snapshots.get(current_id) or {})
    active_nodes = list(
        current_snapshot.get("activeNodeIds")
        or current.get("runtimeCurrentNodeIds")
        or ([current.get("activeNodeId")] if current.get("activeNodeId") else [])
    )
    if current_children:
        disposition = "branched_parent"
        is_current = False
    elif lineage_conflict:
        disposition = "conflicted"
        is_current = False
    else:
        disposition = "current"
        is_current = True
    formal = {
        **_phase(
            lifecycle,
            outcome,
            actionability,
            updated_at=_timestamp(current),
            problems=problems,
        ),
        "runId": current_id or None,
        "runVersion": int(current.get("runVersion") or 0),
        "runStatus": run_status,
        "completionKind": str(current.get("completionKind") or "") or None,
        "lineageDisposition": disposition,
        "isCurrentRevision": is_current,
        "parentRunId": str(current.get("parentRunId") or "") or None,
        "childRunIds": current_children,
        "currentNodeIds": [str(item) for item in active_nodes if str(item)],
    }
    actions: list[dict[str, Any]] = []
    if lineage_conflict:
        for leaf in leaves:
            leaf_id = str(leaf.get("runId") or "").strip()
            if not leaf_id:
                continue
            actions.append(
                _command_action(
                    "archive_run",
                    action_id=f"archive-formal-run:{leaf_id}",
                    label=f"归档分支 {leaf_id}",
                    target_phase="formal_runtime",
                    target_node_id="formal_runtime",
                    payload={"runId": leaf_id},
                    requires_confirmation=True,
                    confirmation_text="归档不再保留为当前分支；请仅归档不应继续的正式运行。",
                )
            )
        return formal, empty_program, problems, actions, "formal_runtime"
    if run_status in {"failed", "cancelled"}:
        actions.append(
            _command_action(
                "archive_run",
                action_id=f"archive-formal-run:{current_id}",
                label="归档失败运行并重建",
                target_phase="formal_runtime",
                target_node_id="formal_runtime",
                payload={"runId": current_id},
                requires_confirmation=True,
                confirmation_text="归档当前终态运行后，可重新创建正式研究运行。",
            )
        )
        return formal, empty_program, problems, actions, "formal_runtime"
    if run_status in {"blocked", "reconciliation_required"}:
        actions.append(
            _command_action(
                "reconcile_formal_run",
                label="修复正式研究运行",
                target_phase="formal_runtime",
                target_node_id="formal_runtime",
                payload={"runId": current_id},
            )
        )
        return formal, empty_program, problems, actions, "formal_runtime"
    if run_status not in {"succeeded", "archived"}:
        return formal, empty_program, problems, actions, "formal_runtime"

    delivery_status = str(current_snapshot.get("deliveryStatus") or "").strip().lower()
    artifact_summary = current_snapshot.get("artifactSummary")
    artifact_summary = artifact_summary if isinstance(artifact_summary, Mapping) else {}
    artifact_ref = str(
        artifact_summary.get("finalArtifactLocator")
        or artifact_summary.get("finalArtifactId")
        or ""
    ).strip() or None
    if record and str(record.get("runId") or "").strip() == current_id:
        program, output_problems, output_actions, phase = _project_program_output_record(
            question_id=question_id,
            record=record,
            run_id=current_id,
            artifact_ref=artifact_ref,
        )
        problems.extend(output_problems)
        actions.extend(output_actions)
        return formal, program, problems, actions, phase

    if delivery_status in {"pending", "queued", "running"}:
        program = {
            **empty_program,
            **_phase("running", "none", "waiting_system", updated_at=_timestamp(current)),
            "deliveryStatus": "queued" if delivery_status == "pending" else delivery_status,
            "deliveryArtifactRef": artifact_ref,
        }
        return formal, program, problems, actions, "program_delivery"
    if delivery_status in {"blocked", "failed"}:
        handoff = current_snapshot.get("programCandidateHandoff")
        handoff = handoff if isinstance(handoff, Mapping) else {}
        needs_context = (
            str(handoff.get("status") or "").strip().upper() == "NEEDS_CONTEXT"
        )
        delivery_problem = _problem(
            (
                "program_candidate_handoff_needs_context"
                if needs_context
                else "program_delivery_failed"
            ),
            (
                "结果包已生成，但 Challenge Program 登记仍缺少上下文"
                if needs_context
                else "正式结果交付失败"
            ),
            category="execution",
            source_kind="formal_run",
            source_id=current_id,
            detected_at=_timestamp(current) or _EPOCH,
        )
        problems.append(delivery_problem)
        program = {
            **empty_program,
            **_phase(
                "not_started" if needs_context else "failed",
                "none",
                "blocked" if needs_context else "available",
                problems=[delivery_problem],
            ),
            "deliveryStatus": delivery_status,
            "deliveryArtifactRef": artifact_ref,
            "handoffStatus": "needs_context" if needs_context else "failed",
        }
        actions.append(
            _command_action(
                "retry_program_handoff",
                label="补齐交付上下文" if needs_context else "重试结果交付",
                target_phase="program_delivery",
                target_node_id="program_delivery",
                payload={"runId": current_id, "deliveryArtifactRef": artifact_ref},
            )
        )
        return formal, program, problems, actions, "program_delivery"
    missing_code = (
        "program_candidate_handoff_needs_context"
        if delivery_status == "succeeded"
        else "formal_result_package_missing"
    )
    missing_message = (
        "结果包已生成，但 Challenge Program 登记仍缺少上下文"
        if delivery_status == "succeeded"
        else "正式运行已成功，但结果包尚不可读"
    )
    missing_problem = _problem(
        missing_code,
        missing_message,
        source_kind="formal_run",
        source_id=current_id,
        detected_at=_timestamp(current) or _EPOCH,
    )
    problems.append(missing_problem)
    program = {
        **empty_program,
        **_phase("not_started", "none", "blocked", problems=[missing_problem]),
        "deliveryStatus": "succeeded" if delivery_status == "succeeded" else "not_started",
        "deliveryArtifactRef": artifact_ref,
        "handoffStatus": "needs_context" if delivery_status == "succeeded" else "not_started",
    }
    actions.append(
        _command_action(
            "retry_program_handoff",
            label="补齐交付上下文" if delivery_status == "succeeded" else "恢复结果交付",
            target_phase="program_delivery",
            target_node_id="program_delivery",
            payload={"runId": current_id, "deliveryArtifactRef": artifact_ref},
        )
    )
    return formal, program, problems, actions, "program_delivery"


def project_state_from_records(
    *,
    team_id: str,
    question_id: str,
    reset_boundary: Mapping[str, Any] | None,
    chain_records: Sequence[Mapping[str, Any]],
    selection_records: Sequence[Mapping[str, Any]],
    meeting_records: Sequence[Mapping[str, Any]],
    digest_records: Sequence[Mapping[str, Any]],
    decision_records: Sequence[Mapping[str, Any]],
    hypothesis_round_records: Sequence[Mapping[str, Any]],
    formal_runs: Sequence[Mapping[str, Any]] = (),
    formal_snapshots: Mapping[str, Mapping[str, Any]] | None = None,
    program_output: Mapping[str, Any] | None = None,
    chat_room_round_snapshots: Mapping[str, Mapping[str, Any]] | None = None,
    return_to: str = "",
    include_source_cursor: bool = False,
) -> dict[str, Any]:
    """Project one canonical snapshot from already scoped durable records."""

    normalized_question_id = str(question_id or "").strip().upper()
    return_to = return_to or "/teams?" + urlencode(
        {
            "teamId": team_id,
            "researchView": "workflow",
            "workflowId": "challenge-cup-research",
            "questionId": normalized_question_id,
            "panel": "node",
        }
    )
    # Reset audit records define the boundary but are not workflow progress.
    # Keeping them in the business-fact stream makes a freshly reset question
    # indistinguishable from a failed/empty generation attempt.
    chain = [
        dict(item)
        for item in chain_records
        if str(item.get("recordKind") or "") != _RESET_AUDIT_KIND
    ]
    selections = [dict(item) for item in selection_records]
    meetings = _latest(meeting_records, "meetingRoundId")
    rounds = _latest(hypothesis_round_records, "roundId")
    reset = dict(reset_boundary or {})
    reset_id = str(reset.get("resetId") or "origin")
    reset_at = str(reset.get("resetAt") or "").strip() or None
    room_round_snapshots = (
        dict(chat_room_round_snapshots)
        if isinstance(chat_room_round_snapshots, Mapping)
        else {}
    )
    computed_at = _latest_timestamp(
        chain,
        selections,
        meetings,
        digest_records,
        decision_records,
        rounds,
        reset,
        formal_runs,
        formal_snapshots or {},
        program_output or {},
        room_round_snapshots,
    )
    source_cursor = {
        "chain": _canonical_hash(chain, length=24),
        "selection": _canonical_hash(selections, length=24),
        "meeting": _canonical_hash(meetings, length=24),
        "digest": _canonical_hash(list(digest_records), length=24),
        "decision": _canonical_hash(list(decision_records), length=24),
        "hypothesisRound": _canonical_hash(rounds, length=24),
        "formalRun": _canonical_hash(list(formal_runs), length=24),
        "formalSnapshot": _canonical_hash(dict(formal_snapshots or {}), length=24),
        "programOutput": _canonical_hash(dict(program_output or {}), length=24),
        "chatRoomRound": _canonical_hash(room_round_snapshots, length=24),
    }

    candidates = sorted(
        (
            record
            for record in chain
            if str(record.get("recordKind") or "") == _CANDIDATE_KIND
        ),
        key=lambda item: (int(item.get("candidateOrder") or 0), str(item.get("createdAt") or "")),
    )
    candidate_ids = list(
        dict.fromkeys(
            str(item.get("candidateId") or "").strip()
            for item in candidates
            if str(item.get("candidateId") or "").strip()
        )
    )
    generation_attempts = sorted(
        _latest(
            [
                record
                for record in chain
                if str(record.get("recordKind") or "") == "generation_attempt"
            ],
            "attemptId",
        ),
        key=lambda item: (
            int(item.get("attemptNumber") or 0),
            str(item.get("updatedAt") or item.get("createdAt") or ""),
        ),
    )
    generation_attempt = generation_attempts[-1] if generation_attempts else None
    attempt_wire = None
    if generation_attempt:
        attempt_wire = {
            "attemptId": str(generation_attempt.get("attemptId") or ""),
            "number": int(generation_attempt.get("attemptNumber") or 1),
            "lifecycle": str(generation_attempt.get("lifecycle") or "not_started"),
            "queuedAt": str(generation_attempt.get("queuedAt") or "") or None,
            "startedAt": str(generation_attempt.get("startedAt") or "") or None,
            "heartbeatAt": str(generation_attempt.get("heartbeatAt") or "") or None,
            "finishedAt": str(generation_attempt.get("finishedAt") or "") or None,
            "supersedesAttemptId": str(
                generation_attempt.get("supersedesAttemptId") or ""
            )
            or None,
        }
    generation_meetings = sorted(
        (
            item
            for item in meetings
            if str(item.get("meetingType") or "") == _GENERATION_MEETING_TYPE
        ),
        key=lambda item: str(item.get("createdAt") or ""),
    )
    generation_meeting = generation_meetings[-1] if generation_meetings else None
    active_attempt_lifecycle = str(
        (generation_attempt or {}).get("lifecycle") or ""
    )
    active_attempt_outcome = str((generation_attempt or {}).get("outcome") or "none")
    generation_meeting_status = str(
        (generation_meeting or {}).get("status") or ""
    ).strip().lower()
    generation_phase = None
    generation_projection_status = ""
    if generation_meeting:
        generation_phase, generation_projection_status = _meeting_phase(
            generation_meeting,
            chat_room_round_snapshots=room_round_snapshots,
        )
    if generation_projection_status == "linked_round_stopped":
        generation = {
            **(generation_phase or _phase("failed", "none", "blocked")),
            "attempt": attempt_wire,
            "generationMeetingId": str(
                (generation_meeting or {}).get("meetingRoundId") or ""
            )
            or None,
            "candidateCount": len(candidate_ids),
            "candidateIds": candidate_ids,
        }
    elif generation_meeting_status == "awaiting_approval":
        generation = {
            **(generation_phase or _phase()),
            "attempt": attempt_wire,
            "generationMeetingId": str(
                (generation_meeting or {}).get("meetingRoundId") or ""
            )
            or None,
            "candidateCount": len(candidate_ids),
            "candidateIds": candidate_ids,
        }
    elif generation_attempt and active_attempt_lifecycle in {
        "queued",
        "running",
        "waiting_human",
        "failed",
        "cancelled",
        "superseded",
    }:
        actionability = {
            "queued": "waiting_system",
            "running": "executing",
            "waiting_human": "waiting_user",
            "failed": "available",
            "cancelled": "available",
            "superseded": "terminal",
        }[active_attempt_lifecycle]
        generation = {
            **_phase(
                active_attempt_lifecycle,
                "none",
                actionability,
                updated_at=_timestamp(generation_attempt),
                attempt=attempt_wire,
            ),
            "generationMeetingId": str(
                generation_attempt.get("meetingRoundId") or ""
            )
            or None,
            "candidateCount": len(candidate_ids),
            "candidateIds": candidate_ids,
        }
    elif generation_attempt and active_attempt_lifecycle == "completed":
        generation = {
            **_phase(
                "completed",
                active_attempt_outcome if active_attempt_outcome != "none" else (
                    "succeeded" if candidate_ids else "empty"
                ),
                "terminal" if candidate_ids else "available",
                updated_at=_timestamp(generation_attempt),
                attempt=attempt_wire,
            ),
            "generationMeetingId": str(
                generation_attempt.get("meetingRoundId") or ""
            )
            or None,
            "candidateCount": len(candidate_ids),
            "candidateIds": candidate_ids,
        }
    elif candidate_ids:
        generation = {
            **_phase("completed", "succeeded", "terminal", updated_at=_timestamp(generation_meeting or candidates[-1])),
            "generationMeetingId": str((generation_meeting or {}).get("meetingRoundId") or "") or None,
            "candidateCount": len(candidate_ids),
            "candidateIds": candidate_ids,
        }
    elif generation_meeting:
        generation_phase = generation_phase or _phase()
        generation_status = generation_projection_status or generation_meeting_status
        if generation_status == "closed":
            generation_phase = _phase("completed", "empty", "available", updated_at=_timestamp(generation_meeting))
        generation = {
            **generation_phase,
            "generationMeetingId": str(generation_meeting.get("meetingRoundId") or "") or None,
            "candidateCount": 0,
            "candidateIds": [],
        }
    else:
        generation = {
            **_phase("not_started", "none", "available"),
            "generationMeetingId": None,
            "candidateCount": 0,
            "candidateIds": [],
        }

    selection_records_latest = sorted(
        selections, key=lambda item: str(item.get("createdAt") or "")
    )
    selection_record_by_id = {
        str(item.get("selectionId") or "").strip(): item
        for item in selection_records_latest
        if str(item.get("selectionId") or "").strip()
    }
    selection_record = selection_records_latest[-1] if selection_records_latest else None
    selection_id = str((selection_record or {}).get("selectionId") or "").strip() or None
    reset_selection_id = reset_id
    review_link_records = [
        dict(item)
        for item in _latest(
            [record for record in chain if record.get("recordKind") == _REVIEW_LINK_KIND],
            "linkId",
        )
        if str(item.get("questionId") or "").strip().upper()
        == normalized_question_id
    ]
    meeting_by_id = {
        str(item.get("meetingRoundId") or ""): item for item in meetings
    }
    links_by_group: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for item in review_link_records:
        linked_selection_id = str(item.get("selectionId") or "").strip()
        version = _selection_version_for_link(
            item,
            selection_by_id=selection_record_by_id,
            question_id=normalized_question_id,
            reset_id=reset_selection_id,
        )
        if linked_selection_id:
            links_by_group.setdefault(
                (
                    linked_selection_id,
                    version or f"legacy:{linked_selection_id}",
                    int(item.get("roundIndex") or 1),
                ),
                [],
            ).append(item)

    active_binding_groups: list[dict[str, Any]] = []
    for (group_selection_id, group_version, group_round), group_links in links_by_group.items():
        group_meeting_ids = {
            str(item.get("meetingRoundId") or "").strip()
            for item in group_links
            if str(item.get("meetingRoundId") or "").strip()
        }
        if any(
            str(meeting_by_id.get(meeting_id, {}).get("status") or "").strip().lower()
            in {"open", "summarizing", "awaiting_approval"}
            for meeting_id in group_meeting_ids
        ):
            active_binding_groups.append(
                {
                    "selectionId": group_selection_id,
                    "selectionVersion": group_version,
                    "roundIndex": group_round,
                    "links": group_links,
                }
            )

    active_by_version: dict[str, list[dict[str, Any]]] = {}
    for group in active_binding_groups:
        active_by_version.setdefault(str(group["selectionVersion"]), []).append(group)
    selection_integrity_problems: list[dict[str, Any]] = []
    for version, groups in active_by_version.items():
        if version.startswith("legacy:"):
            selection_integrity_problems.append(
                _problem(
                    "review_binding_version_missing",
                    "活动评审缺少可验证的 selectionVersion，当前选择已锁定并停止新的提交",
                    category="integrity",
                    source_kind="review_binding",
                    source_id=version.removeprefix("legacy:") or None,
                    detected_at=computed_at,
                )
            )
        identities = {
            str(group.get("selectionId") or "")
            for group in groups
        }
        if len(identities) > 1:
            selection_integrity_problems.append(
                _problem(
                    "active_review_binding_conflict",
                    "同一选择版本存在多个活动评审绑定，当前选择已锁定并停止新的提交",
                    category="integrity",
                    source_kind="review_binding",
                    source_id=version or None,
                    detected_at=computed_at,
                )
            )

    # When selection-context is missing, a durable active review binding is
    # the remaining authority.  Prefer it over an unrelated latest selection
    # record so a stale/empty context can never reopen the selector.
    durable_binding = None
    if active_binding_groups:
        durable_binding = max(
            active_binding_groups,
            key=lambda item: (
                int(item.get("roundIndex") or 0),
                max(
                    str(link.get("createdAt") or "")
                    for link in list(item.get("links") or [])
                ),
            ),
        )
    if selection_record is None and durable_binding is not None:
        selection_id = str(durable_binding.get("selectionId") or "").strip() or None
    elif durable_binding is not None and selection_id:
        selection_version = _selection_version_for_link(
            dict(next(iter(durable_binding.get("links") or []))),
            selection_by_id=selection_record_by_id,
            question_id=normalized_question_id,
            reset_id=reset_selection_id,
        )
        record_version = hypothesis_first_chain.selection_version_for(
            question_id=normalized_question_id,
            selected_candidate_ids=(selection_record or {}).get("selectedCandidateIds"),
            previous_selection_id=str(
                (selection_record or {}).get("previousSelectionId") or ""
            ),
            reset_id=reset_selection_id,
            scope_hash=str((selection_record or {}).get("scopeHash") or ""),
        )
        if selection_version and selection_version == record_version and selection_id != str(
            durable_binding.get("selectionId") or ""
        ):
            # Two ids for one active version are themselves an integrity
            # conflict. Keep projecting the durable binding, which is the
            # only identity that can safely navigate back to the review.
            selection_id = str(durable_binding.get("selectionId") or "").strip() or selection_id

    selected_candidate_ids = [
        str(item).strip()
        for item in list((selection_record or {}).get("selectedCandidateIds") or [])
        if str(item).strip()
    ]
    if durable_binding is not None and (
        selection_record is None
        or selection_id == str(durable_binding.get("selectionId") or "").strip()
        and not selected_candidate_ids
        or selection_integrity_problems
    ):
        durable_selection_id = str(durable_binding.get("selectionId") or "").strip()
        durable_candidate_ids = _ordered_link_candidate_ids(
            [
                item
                for item in review_link_records
                if str(item.get("selectionId") or "").strip()
                == durable_selection_id
            ]
        )
        if durable_candidate_ids:
            selected_candidate_ids = durable_candidate_ids
    if selection_id:
        selection = {
            **_phase(
                "completed",
                "succeeded",
                "terminal",
                updated_at=_timestamp(selection_record or {}),
                problems=selection_integrity_problems,
            ),
            "selectionId": selection_id,
            "selectedCandidateIds": selected_candidate_ids,
        }
    elif candidate_ids:
        selection = {
            **_phase("waiting_human", "none", "waiting_user", updated_at=_timestamp(candidates[-1])),
            "selectionId": None,
            "selectedCandidateIds": [],
        }
    else:
        selection = {**_phase(), "selectionId": None, "selectedCandidateIds": []}

    links = [
        item
        for item in review_link_records
        if not selection_id or str(item.get("selectionId") or "") == selection_id
    ]
    active_round = max((int(item.get("roundIndex") or 0) for item in links), default=0)
    if selection_id and not active_round:
        active_round = 1
    active_links = [item for item in links if int(item.get("roundIndex") or 0) == active_round]
    link_by_candidate = {
        str(item.get("candidateId") or ""): item for item in active_links
    }
    # Newest durable dispatch attempt per candidate of the active round; the
    # projector only reads these facts, it never back-fills them.
    dispatch_attempt_by_candidate: dict[str, dict[str, Any]] = {}
    if selection_id:
        for record in _latest(
            [
                item
                for item in chain
                if str(item.get("recordKind") or "") == _REVIEW_DISPATCH_ATTEMPT_KIND
            ],
            "attemptId",
        ):
            if str(record.get("selectionId") or "") != selection_id:
                continue
            if int(record.get("roundIndex") or 0) != active_round:
                continue
            candidate = str(record.get("candidateId") or "").strip()
            if not candidate:
                continue
            existing = dispatch_attempt_by_candidate.get(candidate)
            if existing is None or (
                int(record.get("attemptNumber") or 0),
                str(record.get("updatedAt") or ""),
            ) >= (
                int(existing.get("attemptNumber") or 0),
                str(existing.get("updatedAt") or ""),
            ):
                dispatch_attempt_by_candidate[candidate] = record
    review_candidates = []
    for order, candidate_id in enumerate(selected_candidate_ids):
        link = link_by_candidate.get(candidate_id)
        meeting = meeting_by_id.get(str((link or {}).get("meetingRoundId") or ""))
        review_candidates.append(
            _review_candidate(
                question_id=normalized_question_id,
                selection_id=selection_id or "",
                candidate_id=candidate_id,
                candidate_order=int((link or {}).get("candidateOrder") or order),
                round_index=active_round,
                link=link,
                meeting=meeting,
                return_to=return_to,
                dispatch_attempt=dispatch_attempt_by_candidate.get(candidate_id),
                chat_room_round_snapshots=room_round_snapshots,
            )
        )
    review_aggregate = _aggregate(review_candidates)
    if selection_integrity_problems:
        review_phase = _phase(
            # Integrity conflicts keep the review locked, but they are not a
            # terminal execution failure.  Keep the pre-existing lifecycle so
            # this stopped-round fix does not alter an unrelated selection
            # recovery contract.
            "running",
            "none",
            "blocked",
            updated_at=computed_at,
            problems=[
                *selection_integrity_problems,
                *[
                    problem
                    for item in review_candidates
                    for problem in list(item.get("problems") or [])
                ],
            ],
        )
    elif not review_candidates:
        review_phase = _phase()
    elif review_aggregate["blocked"]:
        problems = [
            problem
            for item in review_candidates
            for problem in list(item.get("problems") or [])
        ]
        review_phase = _phase(
            "failed",
            "none",
            "blocked",
            updated_at=computed_at,
            problems=problems,
        )
    elif review_aggregate["failed"]:
        review_phase = _phase(
            "failed",
            "none",
            "available",
            problems=[
                problem
                for item in review_candidates
                for problem in list(item.get("problems") or [])
            ],
        )
    elif review_aggregate["completed"] == review_aggregate["total"]:
        review_phase = _phase("completed", "succeeded", "terminal", updated_at=computed_at)
    elif any(item.get("lifecycle") == "waiting_human" for item in review_candidates):
        review_phase = _phase("waiting_human", "none", "waiting_user", updated_at=computed_at)
    else:
        review_phase = _phase("running", "none", "waiting_system", updated_at=computed_at)
    review = {
        **review_phase,
        "activeRoundIndex": active_round or None,
        "aggregate": review_aggregate,
        "candidates": review_candidates,
    }

    request_records = _latest(
        [record for record in chain if record.get("recordKind") == _COLLECTION_REQUEST_KIND],
        "requestId",
    )
    collection_requests = [_collection_request_state(item) for item in request_records]
    collection_aggregate = _aggregate(collection_requests)
    if not collection_requests:
        collection_phase = _phase()
    elif collection_aggregate["blocked"]:
        collection_phase = _phase("running", "none", "blocked", updated_at=computed_at)
    elif collection_aggregate["failed"]:
        collection_phase = _phase("failed", "none", "available", updated_at=computed_at)
    elif collection_aggregate["completed"] == collection_aggregate["total"]:
        collection_phase = _phase("completed", "succeeded", "terminal", updated_at=computed_at)
    elif any(item.get("lifecycle") == "waiting_human" for item in collection_requests):
        collection_phase = _phase("waiting_human", "none", "waiting_user", updated_at=computed_at)
    else:
        collection_phase = _phase("running", "none", "waiting_system", updated_at=computed_at)
    collection = {
        **collection_phase,
        "aggregate": collection_aggregate,
        "requests": collection_requests,
    }

    latest_round = (
        max(rounds, key=lambda item: str(item.get("createdAt") or ""))
        if rounds
        else None
    )
    latest_adjudication = next(
        (
            item
            for item in reversed(chain)
            if item.get("recordKind") == _HUMAN_ADJUDICATION_KIND
            and str(item.get("hypothesisRoundId") or "")
            == str((latest_round or {}).get("roundId") or "")
        ),
        None,
    )
    meta_review = (latest_round or {}).get("metaReview")
    accepted = (
        bool(meta_review.get("accepted"))
        if isinstance(meta_review, Mapping)
        else False
    ) or str((latest_adjudication or {}).get("decision") or "").lower() == "accepted"
    adjudication_rejected = (
        str((latest_adjudication or {}).get("decision") or "").lower() == "rejected"
    )
    pending_collection = any(item.get("lifecycle") != "completed" for item in collection_requests)
    converged = bool(latest_round and latest_round.get("status") == "closed" and accepted and not pending_collection)
    round_index = int((latest_round or {}).get("roundIndex") or active_round or 0)
    round_budget = max(
        [int(item.get("roundBudget") or 0) for item in links] + [3]
    )
    if adjudication_rejected:
        convergence_phase = _phase(
            "completed",
            "rejected",
            "terminal",
            updated_at=_timestamp(latest_adjudication or latest_round or {}),
        )
    elif converged:
        convergence_phase = _phase(
            "completed",
            "succeeded",
            "terminal",
            updated_at=_timestamp(latest_adjudication or latest_round or {}),
        )
    elif (
        latest_round
        and str(latest_round.get("status") or "").lower() == "closed"
        and round_index >= round_budget
    ):
        convergence_phase = _phase(
            "completed",
            "exhausted",
            "waiting_user",
            updated_at=_timestamp(latest_adjudication or latest_round),
        )
    elif latest_round:
        convergence_phase = _phase("waiting_human", "none", "waiting_user", updated_at=_timestamp(latest_round))
    else:
        convergence_phase = _phase()
    convergence = {
        **convergence_phase,
        "latestHypothesisRoundId": str((latest_round or {}).get("roundId") or "") or None,
        "accepted": converged,
        "roundIndex": round_index,
        "roundBudget": round_budget,
    }

    (
        formal_runtime,
        program_delivery,
        _formal_problems,
        formal_actions,
        formal_phase,
    ) = _project_formal_and_program(
        question_id=normalized_question_id,
        formal_runs=formal_runs,
        formal_snapshots=formal_snapshots or {},
        program_output=program_output,
    )

    allowed_actions: list[dict[str, Any]] = []
    if generation["lifecycle"] == "not_started":
        allowed_actions.append(
            _command_action(
                "open_generation",
                label="开始生成候选",
                target_phase="generation",
                target_node_id="hf_generation",
                payload={"questionId": normalized_question_id},
            )
        )
    elif (
        generation["outcome"] == "empty" or generation["lifecycle"] == "failed"
    ) and not any(
        problem.get("code") in {
            "discussion_round_orphaned",
            "discussion_round_stopped",
        }
        for problem in list(generation.get("problems") or [])
    ):
        allowed_actions.append(
            _command_action(
                "retry_generation",
                label="重新生成候选",
                target_phase="generation",
                target_node_id="hf_generation",
                payload={
                    "questionId": normalized_question_id,
                    "previousAttemptId": str(
                        ((generation.get("attempt") or {}).get("attemptId"))
                        or generation["generationMeetingId"]
                        or "legacy-generation"
                    ),
                },
            )
        )
    if generation_meeting:
        generation_meeting_actions, _generation_anchor = _meeting_recovery_actions(
            question_id=normalized_question_id,
            meeting=generation_meeting,
            target_phase="generation",
            target_node_id="hf_generation",
            selection_id=None,
            candidate_id=None,
            return_to=return_to,
            label="进入候选生成讨论室",
            chat_room_round_snapshots=room_round_snapshots,
        )
        # A closed generation room is historical and has no actionable
        # navigation; awaiting approval and stalled/open recovery remain
        # visible.  The anchor is still retained in the generation phase for
        # diagnostics through the meeting id.
        if str(generation_meeting.get("status") or "").lower() != "closed":
            allowed_actions.extend(generation_meeting_actions)
    if selection["lifecycle"] == "waiting_human":
        allowed_actions.append(
            _command_action(
                "record_selection",
                label="选择候选假说",
                target_phase="selection",
                target_node_id="hf_selection",
                payload={
                    "questionId": normalized_question_id,
                    "generationAttemptId": generation["generationMeetingId"] or f"legacy:{_canonical_hash(candidate_ids)}",
                },
                input_schema_ref="hypothesis-first/record-selection/v1",
            )
        )
    if review_candidates:
        if (
            (review_aggregate["blocked"] or review_aggregate["failed"])
            and selection_id
            and not selection_integrity_problems
            and not any(
                problem.get("code")
                in {
                    "discussion_round_orphaned",
                    "discussion_round_stopped",
                }
                for candidate in review_candidates
                for problem in list(candidate.get("problems") or [])
            )
        ):
            failed_candidate_ids = [
                str(item.get("candidateId") or "")
                for item in review_candidates
                if item.get("actionability") == "blocked"
                or item.get("lifecycle") == "failed"
            ]
            allowed_actions.append(
                _command_action(
                    "retry_review_dispatch",
                    label="重试候选评审分发",
                    target_phase="review",
                    target_node_id="hf_review",
                    payload={
                        "selectionId": selection_id,
                        "candidateIds": failed_candidate_ids or selected_candidate_ids,
                    },
                )
            )
        for candidate in review_candidates:
            candidate_meeting = meeting_by_id.get(
                str(candidate.get("meetingRoundId") or "")
            )
            if candidate_meeting:
                candidate_actions, _candidate_anchor = _meeting_recovery_actions(
                    question_id=normalized_question_id,
                    meeting=candidate_meeting,
                    target_phase="review",
                    target_node_id="hf_review",
                    selection_id=selection_id,
                    candidate_id=str(candidate["candidateId"]),
                    return_to=return_to,
                    label="进入候选评审室",
                    chat_room_round_snapshots=room_round_snapshots,
                )
                if str(candidate_meeting.get("status") or "").lower() != "closed":
                    allowed_actions.extend(candidate_actions)
            elif isinstance(candidate.get("discussionAnchor"), Mapping):
                allowed_actions.append(
                    _navigation_action(
                        candidate["discussionAnchor"],
                        candidate_id=str(candidate["candidateId"]),
                    )
                )
            if candidate.get("approval", {}).get("lifecycle") == "waiting_human" and not any(
                item.get("kind") == "command"
                and item.get("actionId") == f"approve-summary:{candidate['candidateId']}"
                for item in allowed_actions
            ):
                # Legacy meeting projections may not have a full meeting
                # record; retain the approval command in that case.
                allowed_actions.append(
                    _command_action(
                        "approve_summary",
                        action_id=f"approve-summary:{candidate['candidateId']}",
                        label="确认候选纪要",
                        target_phase="review",
                        target_node_id="hf_review",
                        payload={"meetingRoundId": candidate["meetingRoundId"]},
                        input_schema_ref="hypothesis-first/approve-summary/v1",
                    )
                )
    for request_state in collection_requests:
        request_id = str(request_state.get("requestId") or "")
        if not request_id:
            continue
        child = request_state.get("childRun")
        child_run_id = (
            str(child.get("runId") or "").strip()
            if isinstance(child, Mapping)
            else ""
        ) or None
        request_lifecycle = str(request_state.get("lifecycle") or "").lower()
        child_lifecycle = (
            str(child.get("lifecycle") or "").lower()
            if isinstance(child, Mapping)
            else ""
        )
        handoff_lifecycle = str(
            (request_state.get("handoff") or {}).get("lifecycle") or ""
        ).lower()
        if child_lifecycle == "failed" or request_lifecycle == "failed":
            allowed_actions.append(
                _command_action(
                    "retry_collection",
                    action_id=f"retry-collection:{request_id}",
                    label="重试资料搜集",
                    target_phase="collection",
                    target_node_id="hf_collection",
                    payload={"requestId": request_id, "childRunId": child_run_id},
                )
            )
        elif child_run_id and request_lifecycle == "running":
            allowed_actions.append(
                _command_action(
                    "stop_collection",
                    action_id=f"stop-collection:{request_id}",
                    label="停止资料搜集",
                    target_phase="collection",
                    target_node_id="hf_collection",
                    payload={"requestId": request_id, "childRunId": child_run_id},
                    requires_confirmation=True,
                    confirmation_text="这会停止当前资料搜集；停止后可重试或重置本题。",
                )
            )
        elif not child_run_id:
            allowed_actions.append(
                _command_action(
                    "retry_collection",
                    action_id=f"retry-collection:{request_id}",
                    label="重新建立资料搜集",
                    target_phase="collection",
                    target_node_id="hf_collection",
                    payload={"requestId": request_id, "childRunId": None},
                )
            )
        elif request_lifecycle == "blocked":
            allowed_actions.append(
                _command_action(
                    "continue_collection",
                    action_id=f"continue-collection:{request_id}",
                    label="继续资料搜集",
                    target_phase="collection",
                    target_node_id="hf_collection",
                    payload={
                        "requestId": request_id,
                        "childRunId": child_run_id,
                    },
                )
            )
        elif (
            child_lifecycle == "completed"
            and handoff_lifecycle == "waiting_human"
        ):
            allowed_actions.append(
                _command_action(
                    "handoff_collection",
                    action_id=f"handoff-collection:{request_id}",
                    label="确认资料交接",
                    target_phase="collection",
                    target_node_id="hf_collection",
                    payload={"requestId": request_id, "childRunId": child_run_id},
                )
            )
        elif child_run_id and str(request_state.get("handoffStatus") or "").lower() in {
            "failed",
            "pending",
            "needs_context",
        }:
            allowed_actions.append(
                _command_action(
                    "handoff_collection",
                    action_id=f"handoff-collection:{request_id}",
                    label="重试资料交接",
                    target_phase="collection",
                    target_node_id="hf_collection",
                    payload={"requestId": request_id, "childRunId": child_run_id},
                )
            )
    if (
        latest_round
        and not converged
        and not adjudication_rejected
        and str(latest_round.get("status") or "").lower() == "closed"
    ):
        round_id = str(latest_round.get("roundId") or "")
        previous_meeting_round_id = next(
            (
                str(item.get("meetingRoundId") or "")
                for item in sorted(
                    active_links,
                    key=lambda item: (
                        int(item.get("candidateOrder") or 0),
                        str(item.get("candidateId") or ""),
                    ),
                )
                if str(item.get("meetingRoundId") or "")
            ),
            "",
        )
        if round_index < round_budget and previous_meeting_round_id:
            allowed_actions.append(
                _command_action(
                    "open_next_review",
                    action_id=f"open-next-review:{round_id}",
                    label="发起下一轮候选评审",
                    target_phase="convergence",
                    target_node_id="hf_convergence",
                    payload={
                        "previousMeetingRoundId": previous_meeting_round_id,
                        "roundBudget": round_budget,
                    },
                )
            )
        elif round_id:
            allowed_actions.append(
                _command_action(
                    "human_adjudication",
                    action_id=f"human-adjudication:{round_id}",
                    label="人工裁决收敛结果",
                    target_phase="convergence",
                    target_node_id="hf_convergence",
                    payload={"hypothesisRoundId": round_id},
                    input_schema_ref="hypothesis-first/human-adjudication/v1",
                )
            )
    # ``create_formal_run`` is only a transition out of a converged chain.  A
    # formal run (including a succeeded run waiting for delivery) or an
    # imported Challenge Program output already owns the next phase; emitting
    # the creation command there would let a first-enabled-command consumer
    # fork duplicate formal runs.
    if converged and formal_phase is None:
        allowed_actions.append(
            _command_action(
                "create_formal_run",
                label="创建正式研究运行",
                target_phase="formal_runtime",
                target_node_id="formal_runtime",
                payload={
                    "questionId": normalized_question_id,
                    "hypothesisRoundId": convergence["latestHypothesisRoundId"],
                },
            )
        )
    allowed_actions.extend(formal_actions)

    any_facts = bool(
        chain
        or selections
        or meetings
        or digest_records
        or decision_records
        or rounds
        or formal_runs
        or program_output
    )
    # A formal run only becomes phase-authoritative after hypothesis
    # convergence.  Older clients could create the run as a container before
    # generation; letting that legacy fact win here hides the generation and
    # review actions required to ever reach convergence.
    if formal_phase is not None and (
        converged
        or formal_phase in {"program_delivery", "completed"}
        or formal_runtime.get("lineageDisposition") == "conflicted"
    ):
        current_phase = formal_phase
    elif converged:
        current_phase = "formal_runtime"
    elif collection_requests and collection["lifecycle"] != "completed":
        current_phase = "collection"
    elif review_candidates and review["lifecycle"] != "completed":
        current_phase = "review"
    elif latest_round:
        current_phase = "convergence"
    elif selection_id:
        current_phase = "review"
    elif candidate_ids:
        current_phase = "selection"
    else:
        current_phase = "generation"
    phase_lookup = {
        "generation": generation,
        "selection": selection,
        "review": review,
        "collection": collection,
        "convergence": convergence,
        "formal_runtime": formal_runtime,
        "program_delivery": program_delivery,
        "completed": program_delivery,
    }
    current_state = phase_lookup[current_phase]
    # Capabilities belong to the authoritative current phase.  Without this
    # fence, a succeeded formal run whose delivery is blocked can still expose
    # an upstream generation action and send first-action clients backwards.
    allowed_actions = [
        action
        for action in allowed_actions
        if str(action.get("targetPhase") or "") == current_phase
    ]
    overall = _phase(
        current_state["lifecycle"],
        current_state["outcome"],
        current_state["actionability"],
        updated_at=current_state.get("updatedAt"),
        problems=current_state.get("problems") or [],
    )
    all_problems = [
        problem
        for phase in phase_lookup.values()
        for problem in list(phase.get("problems") or [])
    ]
    awaiting_human_count = (
        int(generation.get("lifecycle") == "waiting_human")
        + int(selection.get("lifecycle") == "waiting_human")
        + sum(
            1
            for candidate in review_candidates
            if candidate.get("approval", {}).get("lifecycle") == "waiting_human"
        )
        + sum(
            1
            for request in collection_requests
            if request.get("lifecycle") == "waiting_human"
            or request.get("handoff", {}).get("lifecycle") == "waiting_human"
        )
        + int(convergence.get("lifecycle") == "waiting_human")
        + int(program_delivery.get("humanReviewStatus") == "waiting_human")
    )
    raw: dict[str, Any] = {
        "schemaVersion": 2,
        "contract": "hypothesis-first-state/v2",
        "teamId": team_id,
        "questionId": normalized_question_id,
        "computedAt": computed_at,
        "scope": {
            "questionInOfficialCatalog": True,
            "catalogId": CATALOG_ID,
            "catalogSha256": CATALOG_SHA256,
        },
        "resetBoundary": {
            "resetId": reset_id,
            "resetAt": reset_at,
            "source": "question_reset_audit" if reset_boundary else "origin",
        },
        "isInitial": not any_facts,
        "awaitingHumanCount": awaiting_human_count,
        "currentPhase": current_phase,
        "overall": overall,
        "generation": generation,
        "selection": selection,
        "review": review,
        "collection": collection,
        "convergence": convergence,
        "formalRuntime": formal_runtime,
        "programDelivery": program_delivery,
        "allowedActions": allowed_actions,
        "problems": all_problems,
    }
    if include_source_cursor:
        raw["sourceCursor"] = source_cursor
    return finalize_state_versions(raw, reset_id=reset_id)


def _scope_records(team_id: str, question_id: str) -> dict[str, Any]:
    snapshot = _cached_question_reset_snapshot(team_id, question_id)
    meeting_ids = set(snapshot["targetMeetingIds"])
    round_ids = set(snapshot["targetRoundIds"])
    normalized = question_id.upper()
    chain_records = [
        record
        for record in snapshot["chainRecords"]
        if str(record.get("questionId") or "").strip().upper() == normalized
    ]
    reset_records = [
        record
        for record in snapshot["chainRecords"]
        if record.get("recordKind") == _RESET_AUDIT_KIND
        and str(record.get("questionId") or "").strip().upper() == normalized
    ]
    reset_boundary = reset_records[-1] if reset_records else None
    meeting_records = [
        record
        for record in snapshot["meetingRecords"]
        if str(record.get("meetingRoundId") or "") in meeting_ids
    ]
    chat_room_round_snapshots: dict[str, dict[str, Any]] = {}
    try:
        # WorkRun snapshots are the read-only runtime authority.  Do not call
        # chat-room detail here: that facade reconciles/repairs room state as a
        # side effect, which is not appropriate for a canonical projection.
        bound_round_ids: set[str] = set()
        for meeting in meeting_records:
            meeting_round_ids = [
                str(round_id or "").strip()
                for round_id in list(meeting.get("chatRoomRoundIds") or [])
                if str(round_id or "").strip()
            ]
            if meeting_round_ids:
                # The append-only list's final id is the current retry.  Do
                # not spend a read on historical rounds that cannot affect
                # the canonical projection.
                bound_round_ids.add(meeting_round_ids[-1])
        for round_id in bound_round_ids:
            work_run = _load_chat_room_round_snapshot(round_id)
            if not isinstance(work_run, Mapping):
                continue
            snapshot_id = str(
                work_run.get("runId") or work_run.get("roundId") or ""
            ).strip()
            if snapshot_id and snapshot_id != round_id:
                continue
            chat_room_round_snapshots[round_id] = dict(work_run)
    except (OSError, TypeError, ValueError) as exc:
        # Missing/unreadable runtime snapshots must not make the durable
        # research ledger unavailable; the projector will retain the meeting's
        # own status and avoid inferring a stop without strong evidence.
        _record_projection_scene_event(
            "chat_room_round_snapshot.unavailable",
            team_id=team_id,
            question_id=normalized,
            source_error_type=type(exc).__name__,
        )
    try:
        from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
        from core.web.services.team_workflow import challenge_question_runs

        from .formal_read_runtime import get_query_service

        query_service = get_query_service()
        run_payload = query_service.list_runs(
            team_id=team_id,
            workflow_id=CHALLENGE_CUP_WORKFLOW_ID,
        )
        formal_runs = [
            dict(record)
            for record in list(run_payload.get("runs") or [])
            if isinstance(record, Mapping)
            and str(record.get("questionId") or "").strip().upper() == normalized
        ]
        formal_snapshots: dict[str, dict[str, Any]] = {}
        for run in formal_runs:
            run_id = str(run.get("runId") or "").strip()
            if not run_id:
                continue
            projected = query_service.get_snapshot(team_id=team_id, run_id=run_id)
            if hasattr(projected, "to_dict"):
                projected = projected.to_dict()
            if not isinstance(projected, Mapping):
                raise TypeError("formal workflow snapshot is not a mapping")
            formal_snapshots[run_id] = dict(projected)
        try:
            program_output = challenge_question_runs.get_challenge_question_run_detail(
                team_id,
                normalized,
            )
        except ValueError as exc:
            if "challenge_question_run_not_found" not in str(exc):
                raise
            program_output = None
    except Exception as exc:
        _record_projection_scene_event(
            "state_projection.failed",
            team_id=team_id,
            question_id=normalized,
            source_error_type=type(exc).__name__,
        )
        raise HypothesisFirstStateSourceError(
            f"无法读取挑战杯流程权威状态：{type(exc).__name__}"
        ) from exc

    return {
        "reset_boundary": reset_boundary,
        "chain_records": chain_records,
        "selection_records": [
            record
            for record in snapshot["selectionRecords"]
            if str(record.get("questionId") or "").strip().upper() == normalized
        ],
        "meeting_records": [
            dict(record) for record in meeting_records
        ],
        "digest_records": [
            record
            for record in snapshot["digestRecords"]
            if str(record.get("meetingRoundId") or "") in meeting_ids
        ],
        "decision_records": [
            record
            for record in snapshot["decisionRecords"]
            if str(record.get("meetingRoundId") or "") in meeting_ids
        ],
        "hypothesis_round_records": [
            record
            for record in snapshot["hypothesisRoundRecords"]
            if str(record.get("roundId") or "") in round_ids
        ],
        "formal_runs": formal_runs,
        "formal_snapshots": formal_snapshots,
        "program_output": program_output,
        "chat_room_round_snapshots": chat_room_round_snapshots,
    }


def project_hypothesis_first_state_v2(
    team_id: str,
    question_id: str,
    *,
    return_to: str = "",
    include_source_cursor: bool = False,
) -> dict[str, Any]:
    """Read and project the canonical V2 state for one official question."""

    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    if not _QUESTION_ID_PATTERN.fullmatch(normalized_question_id):
        raise HypothesisFirstStateScopeError(
            "question_id_invalid",
            "questionId 必须使用 SCI-001 形式",
            status_code=422,
        )
    if not is_official_question_id(normalized_question_id):
        raise HypothesisFirstStateScopeError(
            "catalog_question_unknown",
            "题号不在官方挑战杯目录中",
            status_code=404,
        )
    sources = _scope_records(normalized_team_id, normalized_question_id)
    return project_state_from_records(
        team_id=normalized_team_id,
        question_id=normalized_question_id,
        return_to=return_to,
        include_source_cursor=include_source_cursor,
        **sources,
    )
