"""Pure projection for the current Challenge Cup discussion.

The workflow owns the active discussion identity.  This module deliberately
does not read a team, a chat store, or a ``linkedChatRoomId`` pointer.  It
accepts already-loaded workflow, meeting, and room projections and returns a
small, fail-closed navigation anchor.

There are two important properties here:

* a room is eligible only when its canonical discussion scope agrees with the
  workflow and the selected meeting; and
* a list is never made "current" merely because one element happened to be
  first.  An explicit workflow candidate/meeting wins, otherwise exactly one
  open scoped meeting is required.

The helpers are intentionally tolerant about envelope names because the
projection route and the append-only stores use different response wrappers.
They are not tolerant about identity: missing or malformed scope is degraded,
never repaired from a legacy team room.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlencode

from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.contracts.discussion_scope import (
    CANDIDATE_REVIEW_SCOPE_KIND,
    PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND,
    QUESTION_GENERATION_SCOPE_KIND,
    PreformalCandidateReviewScopeV1,
    WorkflowDiscussionScopeV1,
    parse_discussion_scope,
)

STATUS_READY = "ready"
STATUS_DEGRADED = "degraded"

NO_ACTIVE_DISCUSSION = "no_active_discussion_anchor"
WORKFLOW_SCOPE_MISSING = "workflow_scope_missing"
WORKFLOW_SCOPE_INVALID = "workflow_scope_invalid"
WORKFLOW_SCOPE_HASH_MISMATCH = "workflow_scope_hash_mismatch"
WORKFLOW_CANDIDATE_MISMATCH = "workflow_candidate_mismatch"
WORKFLOW_MEETING_MISMATCH = "workflow_meeting_mismatch"
AMBIGUOUS_ACTIVE_MEETING = "ambiguous_active_meeting"
AMBIGUOUS_ACTIVE_CANDIDATE = "ambiguous_active_candidate"
MEETING_MISSING = "meeting_missing"
MEETING_SCOPE_MISSING = "meeting_scope_missing"
MEETING_SCOPE_MISMATCH = "meeting_scope_mismatch"
MEETING_SCOPE_HASH_MISMATCH = "meeting_scope_hash_mismatch"
MEETING_ROOM_MISSING = "meeting_room_missing"
MEETING_CLOSED = "meeting_closed"
ROOM_MISSING = "room_missing"
ROOM_SCOPE_MISSING = "room_scope_missing"
ROOM_SCOPE_MISMATCH = "room_scope_mismatch"
ROOM_SCOPE_HASH_MISMATCH = "room_scope_hash_mismatch"
ROOM_CLOSED = "room_closed"
ROOM_UNREADABLE = "room_unreadable"
PREFORMAL_SCOPE_MISSING = "preformal_scope_missing"
PREFORMAL_SCOPE_INVALID = "preformal_scope_invalid"
PREFORMAL_SCOPE_HASH_MISMATCH = "preformal_scope_hash_mismatch"
PREFORMAL_BINDING_MISMATCH = "preformal_binding_mismatch"
PREFORMAL_MEETING_MISSING = "preformal_meeting_missing"
PREFORMAL_ROOM_MISSING = "preformal_room_missing"
PREFORMAL_ROOM_SCOPE_MISMATCH = "preformal_room_scope_mismatch"
PREFORMAL_MEETING_CLOSED = "preformal_meeting_closed"

_PREFORMAL_SCOPE_AUTHORITY = "preformal_candidate_review_scope.v1"
_PREFORMAL_SCOPE_SOURCE = "hypothesis_first_candidate_review.v1"

_OUTPUT_FIELDS = (
    "scope",
    "scopeHash",
    "roomId",
    "meetingRoundId",
    "questionId",
    "selectionId",
    "candidateId",
    "deepLink",
    "returnTo",
    "returnLabel",
    "status",
    "degradedReason",
)

_SCOPE_FIELDS = (
    "version",
    "kind",
    "teamId",
    "researchProjectId",
    "workflowRunId",
    "workflowNodeId",
    "questionId",
    "selectionId",
    "candidateId",
)
_SCOPE_ALIASES: dict[str, tuple[str, ...]] = {
    "version": ("version", "scopeVersion"),
    "kind": ("kind", "scopeKind"),
    "teamId": ("teamId", "team_id"),
    "researchProjectId": ("researchProjectId", "research_project_id", "projectId"),
    "workflowRunId": ("workflowRunId", "workflow_run_id", "runId"),
    "workflowNodeId": ("workflowNodeId", "workflow_node_id", "nodeId"),
    "questionId": ("questionId", "question_id"),
    "selectionId": ("selectionId", "selection_id"),
    "candidateId": ("candidateId", "candidate_id"),
}

_NESTED_SCOPE_KEYS = (
    "discussionScope",
    "activeDiscussionScope",
    "workflowScope",
    "scope",
)
_NESTED_PROJECTION_KEYS = (
    "activeDiscussionAnchor",
    "activeDiscussion",
    "activeTask",
    "currentTask",
    "currentDiscussion",
    "workflow",
    "projection",
    "state",
)
_ACTIVE_KEYS = (
    "activeDiscussionAnchor",
    "activeDiscussion",
    "activeTask",
    "currentTask",
    "currentDiscussion",
)

_OPEN_MEETING_STATUSES = {
    "open",
    "active",
    "running",
    "in_progress",
    "pending",
    "queued",
    "starting",
    "dispatching",
    "summarizing",
    "awaiting_approval",
}
_TERMINAL_STATUSES = {
    "closed",
    "archived",
    "deleted",
    "cancelled",
    "canceled",
    "failed",
    "stopped",
    "completed",
    "succeeded",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _text(value).lower()


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _records(value: Any, key: str) -> list[Mapping[str, Any]]:
    """Unwrap list responses without treating a mapping's insertion order as state."""

    if isinstance(value, Mapping):
        nested = value.get(key)
        if isinstance(nested, Iterable) and not isinstance(nested, (str, bytes, Mapping)):
            value = nested
        elif key == "rooms":
            # A test/adapter may expose ``{roomId: room}``; retain the key only
            # when the value itself has no roomId.  This is still a projection,
            # not a fallback to a team's linked room.
            rows: list[Mapping[str, Any]] = []
            for room_id, room in value.items():
                if isinstance(room, Mapping):
                    item = dict(room)
                    item.setdefault("roomId", room_id)
                    rows.append(item)
            return rows
        else:
            return []
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _first_text(payloads: Iterable[Mapping[str, Any]], keys: Iterable[str]) -> str:
    for payload in payloads:
        for key in keys:
            value = _text(payload.get(key))
            if value:
                return value
    return ""


def _first_nested_text(
    payloads: Iterable[Mapping[str, Any]],
    keys: Iterable[str],
) -> str:
    value = _first_text(payloads, keys)
    if value:
        return value
    for payload in payloads:
        for scope_key in _NESTED_SCOPE_KEYS:
            nested = payload.get(scope_key)
            if isinstance(nested, Mapping):
                value = _first_text((nested,), keys)
                if value:
                    return value
    return ""


def _scope_candidate(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Find the first explicitly named discussion-scope object."""

    for key in _NESTED_SCOPE_KEYS:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _scope_from_mapping(
    raw: Any,
    *,
    allow_selection_parent: bool = False,
) -> tuple[WorkflowDiscussionScopeV1 | None, str, str | None]:
    """Return ``(scope, supplied_hash, error)`` for a candidate mapping.

    ``scopeHash`` is metadata in the surrounding record, not part of the v1
    identity object.  It is therefore removed before parsing and checked by
    the caller.  Unknown business fields are ignored only when they sit beside
    a complete canonical scope; the canonical scope parser still rejects
    unknown identity fields.
    """

    if not isinstance(raw, Mapping):
        return None, "", "scope_not_object"
    nested = _scope_candidate(raw)
    source = nested if nested is not None else raw
    supplied_hash = _text(
        raw.get("scopeHash")
        or raw.get("discussionScopeHash")
        or (nested.get("scopeHash") if nested else "")
        or (nested.get("discussionScopeHash") if nested else "")
    )
    candidate: dict[str, Any] = {}
    for field in _SCOPE_FIELDS:
        for alias in _SCOPE_ALIASES[field]:
            if alias in source and source.get(alias) is not None:
                candidate[field] = source.get(alias)
                break
    # A surrounding record is allowed to carry the scope fields beside a
    # nested partial scope.  This is useful for compact room/meeting records,
    # while still requiring the complete canonical identity before success.
    for field in _SCOPE_FIELDS:
        if field in candidate:
            continue
        for alias in _SCOPE_ALIASES[field]:
            if alias in raw and raw.get(alias) is not None:
                candidate[field] = raw.get(alias)
                break
    if not candidate.get("kind"):
        candidate["kind"] = (
            CANDIDATE_REVIEW_SCOPE_KIND
            if _text(candidate.get("selectionId")) and _text(candidate.get("candidateId"))
            else QUESTION_GENERATION_SCOPE_KIND
        )
    if not candidate.get("version"):
        candidate["version"] = 1
    # A selection-level workflow projection can identify the parent scope while
    # the candidate is still being selected. It is not a room scope and is
    # normalized to the generation parent; the caller keeps selectionId as an
    # active reference separately. Meeting and room records never enable this.
    if (
        allow_selection_parent
        and candidate.get("kind") == QUESTION_GENERATION_SCOPE_KIND
        and _text(candidate.get("selectionId"))
        and not _text(candidate.get("candidateId"))
    ):
        candidate.pop("selectionId", None)
    if candidate.get("kind") == QUESTION_GENERATION_SCOPE_KIND:
        # ``from_mapping`` correctly rejects review-only keys even when they
        # are empty; omit them before parsing the generation identity.
        candidate.pop("selectionId", None)
        candidate.pop("candidateId", None)
    # An absent selection/candidate is meaningful for generation; the parser
    # enforces that review scopes have both values.
    try:
        return parse_discussion_scope(candidate), supplied_hash, None
    except (ContractValidationError, TypeError, ValueError) as exc:
        return None, supplied_hash, _text(exc) or "scope_invalid"


def _scope_from_payload(
    payload: Mapping[str, Any],
    *,
    allow_selection_parent: bool = False,
) -> tuple[WorkflowDiscussionScopeV1 | None, str, str | None]:
    candidate = _scope_candidate(payload)
    if candidate is not None:
        # Preserve hashes/direct fields beside a nested scope.
        merged = dict(candidate)
        for key in ("scopeHash", "discussionScopeHash"):
            if key in payload and key not in merged:
                merged[key] = payload.get(key)
        return _scope_from_mapping(merged, allow_selection_parent=allow_selection_parent)
    return _scope_from_mapping(payload, allow_selection_parent=allow_selection_parent)


_PREFORMAL_SCOPE_FIELDS = (
    "version",
    "kind",
    "teamId",
    "questionId",
    "selectionId",
    "candidateId",
    "meetingRoundId",
    "roomId",
)
_PREFORMAL_SCOPE_ALIASES: dict[str, tuple[str, ...]] = {
    "version": ("version", "scopeVersion"),
    "kind": ("kind", "scopeKind"),
    "teamId": ("teamId", "team_id"),
    "questionId": ("questionId", "question_id", "question"),
    "selectionId": ("selectionId", "selection_id"),
    "candidateId": ("candidateId", "candidate_id"),
    "meetingRoundId": ("meetingRoundId", "meeting_round_id"),
    "roomId": ("roomId", "room_id", "linkedChatRoomId", "discussionRoomId"),
}
_PREFORMAL_SCOPE_NESTED_KEYS = (
    "preformalDiscussionScope",
    "preformalScope",
    "preformalBinding",
)


def _preformal_scope_candidate(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for key in _PREFORMAL_SCOPE_NESTED_KEYS:
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            return nested
    nested = _scope_candidate(payload)
    if isinstance(nested, Mapping) and (
        _text(nested.get("kind")) == PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND
    ):
        return nested
    if (
        _text(payload.get("kind")) == PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND
        or _text(payload.get("scopeKind")) == PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND
        or _text(payload.get("scopeAuthority")) == _PREFORMAL_SCOPE_AUTHORITY
    ):
        return payload
    return None


def _preformal_scope_from_payload(
    payload: Mapping[str, Any],
    *,
    defaults: Mapping[str, Any] | None = None,
    allow_legacy: bool = False,
    include_legacy_scope_hash: bool = True,
) -> tuple[PreformalCandidateReviewScopeV1 | None, str, str | None]:
    """Parse a preformal binding, optionally projecting the six-field legacy record.

    ``allow_legacy`` is used only after the chain has supplied the exact
    selection/candidate/meeting/room references.  It is deliberately false
    for generic workflow projections so a question or team room can never
    become a current discussion by itself.
    """

    if not isinstance(payload, Mapping):
        return None, "", "scope_not_object"
    nested = _preformal_scope_candidate(payload)
    if nested is None and not allow_legacy:
        return None, "", "scope_missing"
    source = nested if nested is not None else payload
    supplied_hash = _text(
        payload.get("discussionScopeHash")
        or (source.get("discussionScopeHash") if isinstance(source, Mapping) else "")
        or payload.get("scopeHash")
        or (source.get("scopeHash") if isinstance(source, Mapping) else "")
    )
    if not include_legacy_scope_hash and nested is None:
        supplied_hash = _text(
            payload.get("discussionScopeHash")
            or (source.get("discussionScopeHash") if isinstance(source, Mapping) else "")
        )
    candidate: dict[str, Any] = {}
    for field in _PREFORMAL_SCOPE_FIELDS:
        for alias in _PREFORMAL_SCOPE_ALIASES[field]:
            if alias in source and source.get(alias) is not None:
                candidate[field] = source.get(alias)
                break
    if nested is None:
        # Legacy projection is allowed only after the owning chain supplied an
        # exact selection/candidate/meeting/room binding.  A persisted explicit
        # scope must stand on its own: never repair a damaged new envelope from
        # loose outer fields or defaults.
        for field, value in dict(defaults or {}).items():
            if field in _PREFORMAL_SCOPE_FIELDS and not _text(candidate.get(field)):
                candidate[field] = value
        candidate.setdefault("version", 1)
        candidate.setdefault("kind", PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND)
    try:
        return PreformalCandidateReviewScopeV1.from_mapping(candidate), supplied_hash, None
    except (ContractValidationError, TypeError, ValueError) as exc:
        return None, supplied_hash, _text(exc) or "scope_invalid"


def _scope_equal(left: WorkflowDiscussionScopeV1, right: WorkflowDiscussionScopeV1) -> bool:
    return left.to_dict() == right.to_dict()


def _scope_base_equal(left: WorkflowDiscussionScopeV1, right: WorkflowDiscussionScopeV1) -> bool:
    return all(
        getattr(left, field) == getattr(right, field)
        for field in (
            "teamId",
            "researchProjectId",
            "workflowRunId",
            "workflowNodeId",
            "questionId",
        )
    )


def _scope_hash_is_valid(scope: WorkflowDiscussionScopeV1, supplied_hash: str) -> bool:
    return not supplied_hash or supplied_hash.lower() == scope.scope_hash.lower()


def _nested_payloads(projection: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Order active projection nodes before generic state nodes."""

    payloads: list[Mapping[str, Any]] = [projection]
    for key in _ACTIVE_KEYS + ("workflow", "projection", "state"):
        nested = projection.get(key)
        if isinstance(nested, Mapping):
            payloads.insert(0, nested)
    # Keep the most specific active object first, then the root.  Duplicate
    # objects are harmless and make the precedence explicit without sorting.
    result: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    for item in payloads:
        if id(item) not in seen:
            seen.add(id(item))
            result.append(item)
    return result


def _find_active_scope(projection: Mapping[str, Any]) -> tuple[WorkflowDiscussionScopeV1 | None, str, str | None]:
    payloads = _nested_payloads(projection)
    for payload in payloads:
        scope, supplied_hash, error = _scope_from_payload(
            payload,
            allow_selection_parent=True,
        )
        if scope is not None:
            return scope, supplied_hash, error
    return None, "", "scope_missing"


def _find_preformal_scope(
    projection: Mapping[str, Any],
) -> tuple[PreformalCandidateReviewScopeV1 | None, str, str | None]:
    """Find an explicit chain binding for a review opened before a formal run."""

    for payload in _nested_payloads(projection):
        scope, supplied_hash, error = _preformal_scope_from_payload(payload)
        if scope is None:
            continue
        return scope, supplied_hash, error
    return None, "", "scope_missing"


def _explicit_refs(projection: Mapping[str, Any]) -> dict[str, str]:
    payloads = _nested_payloads(projection)
    return {
        "meetingRoundId": _first_text(
            payloads,
            ("activeMeetingRoundId", "currentMeetingRoundId", "meetingRoundId"),
        ),
        "roomId": _first_text(
            payloads,
            ("activeRoomId", "currentRoomId", "discussionRoomId", "roomId"),
        ),
        "selectionId": _first_text(
            payloads,
            ("activeSelectionId", "currentSelectionId", "selectionId"),
        ) or _first_nested_text(
            payloads,
            ("activeSelectionId", "currentSelectionId", "selectionId"),
        ),
        "candidateId": _first_text(
            payloads,
            ("activeCandidateId", "currentCandidateId", "candidateId"),
        ) or _first_nested_text(
            payloads,
            ("activeCandidateId", "currentCandidateId", "candidateId"),
        ),
    }


def _meeting_id(meeting: Mapping[str, Any]) -> str:
    return _first_text((meeting,), ("meetingRoundId", "meetingId", "id"))


def _meeting_room_id(meeting: Mapping[str, Any]) -> str:
    # ``linkedChatRoomId`` on a scoped meeting is a binding produced by the
    # meeting owner.  It is valid only after the meeting scope is validated;
    # this is not the forbidden team-level fallback.
    return _first_text(
        (meeting,),
        ("roomId", "discussionRoomId", "scopedRoomId", "linkedChatRoomId"),
    )


def _meeting_is_open(meeting: Mapping[str, Any]) -> bool:
    status = _lower(meeting.get("status"))
    return status in _OPEN_MEETING_STATUSES or not status


def _meeting_is_terminal(meeting: Mapping[str, Any]) -> bool:
    return _lower(meeting.get("status")) in _TERMINAL_STATUSES


def _room_is_readable(room: Mapping[str, Any]) -> tuple[bool, str]:
    for key in ("readable", "isReadable", "canRead"):
        if key in room:
            value = room.get(key)
            if isinstance(value, bool) and not value:
                return False, ROOM_UNREADABLE
            if _lower(value) in {"false", "0", "no", "denied", "unreadable"}:
                return False, ROOM_UNREADABLE
    if bool(room.get("deleted")) or bool(room.get("archived")):
        return False, ROOM_CLOSED
    if _lower(room.get("status")) in _TERMINAL_STATUSES:
        return False, ROOM_CLOSED
    return True, ""


def _room_id(room: Mapping[str, Any]) -> str:
    return _first_text((room,), ("roomId", "id"))


def _degraded(
    reason: str,
    *,
    scope: WorkflowDiscussionScopeV1 | None = None,
    room_id: str = "",
    meeting_round_id: str = "",
    question_id: str = "",
    selection_id: str = "",
    candidate_id: str = "",
) -> dict[str, Any]:
    if scope is not None:
        scope_payload: dict[str, Any] | None = scope.to_dict()
        scope_hash = scope.scope_hash
        question_id = scope.questionId
        selection_id = scope.selectionId
        candidate_id = scope.candidateId
    else:
        scope_payload = None
        scope_hash = ""
    return {
        "scope": scope_payload,
        "scopeHash": scope_hash,
        "roomId": room_id,
        "meetingRoundId": meeting_round_id,
        "questionId": question_id,
        "selectionId": selection_id,
        "candidateId": candidate_id,
        "deepLink": "",
        "returnTo": "",
        "returnLabel": "",
        "status": STATUS_DEGRADED,
        "degradedReason": reason,
    }


def _preformal_degraded(
    reason: str,
    *,
    scope: PreformalCandidateReviewScopeV1 | None = None,
    room_id: str = "",
    meeting_round_id: str = "",
    question_id: str = "",
    selection_id: str = "",
    candidate_id: str = "",
) -> dict[str, Any]:
    if scope is not None:
        scope_payload: dict[str, Any] | None = scope.to_dict()
        scope_hash = scope.scope_hash
        room_id = scope.roomId
        meeting_round_id = scope.meetingRoundId
        question_id = scope.questionId
        selection_id = scope.selectionId
        candidate_id = scope.candidateId
    else:
        scope_payload = None
        scope_hash = ""
    return {
        "scope": scope_payload,
        "scopeHash": scope_hash,
        "roomId": room_id,
        "meetingRoundId": meeting_round_id,
        "questionId": question_id,
        "selectionId": selection_id,
        "candidateId": candidate_id,
        "deepLink": "",
        "returnTo": "",
        "returnLabel": "",
        "status": STATUS_DEGRADED,
        "degradedReason": reason,
    }


def _preformal_ready(
    scope: PreformalCandidateReviewScopeV1,
) -> dict[str, Any]:
    # A preformal review has no honest workflow run/node.  Return to the
    # stable question review surface instead of manufacturing a formal run id.
    return_to = "/teams?" + urlencode(
        {
            "teamId": scope.teamId,
            "researchView": "workflow",
            "workflowId": "challenge-cup-research",
            "questionId": scope.questionId,
            "node": "hf_review",
            "panel": "node",
        }
    )
    deep_link = "/chat?" + urlencode(
        {
            "room": scope.roomId,
            "returnTo": return_to,
            "returnLabel": "返回科研流程",
        }
    )
    return {
        "scope": scope.to_dict(),
        "scopeHash": scope.scope_hash,
        "roomId": scope.roomId,
        "meetingRoundId": scope.meetingRoundId,
        "questionId": scope.questionId,
        "selectionId": scope.selectionId,
        "candidateId": scope.candidateId,
        "deepLink": deep_link,
        "returnTo": return_to,
        "returnLabel": "返回科研流程",
        "status": STATUS_READY,
        "degradedReason": "",
    }


def _preformal_ref_value(
    meeting: Mapping[str, Any],
    direct_keys: Iterable[str],
    ref_keys: Iterable[str],
) -> str:
    direct = _first_text((meeting,), direct_keys)
    if direct:
        return direct
    for ref_key in ref_keys:
        prefix = f"{ref_key}:"
        for list_key in ("inputArtifactRefs", "discussionItemRefs"):
            for raw in list(meeting.get(list_key) or []):
                value = _text(raw)
                if value.startswith(prefix):
                    return value.split(":", 1)[1].strip()
    return ""


def _preformal_meeting_binding(
    meeting: Mapping[str, Any],
    *,
    scope: PreformalCandidateReviewScopeV1,
) -> tuple[bool, str]:
    """Validate a meeting against an exact preformal chain binding."""

    if _meeting_id(meeting) != scope.meetingRoundId:
        return False, PREFORMAL_BINDING_MISMATCH
    meeting_question = _first_text((meeting,), ("questionId", "question"))
    if not meeting_question or meeting_question.upper() != scope.questionId.upper():
        return False, PREFORMAL_BINDING_MISMATCH
    meeting_team = _first_text((meeting,), ("teamId", "researchTeamId"))
    if meeting_team and meeting_team != scope.teamId:
        return False, PREFORMAL_BINDING_MISMATCH
    if _meeting_room_id(meeting) != scope.roomId:
        return False, PREFORMAL_BINDING_MISMATCH
    selection_id = _preformal_ref_value(
        meeting,
        ("selectionId", "selection_id"),
        ("hypothesis_selection",),
    )
    candidate_id = _preformal_ref_value(
        meeting,
        ("candidateId", "candidate_id"),
        ("hypothesis_candidate",),
    )
    if selection_id != scope.selectionId or candidate_id != scope.candidateId:
        return False, PREFORMAL_BINDING_MISMATCH

    explicit_scope = _preformal_scope_candidate(meeting)
    if explicit_scope is not None:
        stored_scope, supplied_hash, _error = _preformal_scope_from_payload(
            meeting,
            defaults=scope.to_dict(),
            allow_legacy=False,
            include_legacy_scope_hash=False,
        )
        if stored_scope is None:
            return False, PREFORMAL_SCOPE_INVALID
        if supplied_hash and not _scope_hash_is_valid(stored_scope, supplied_hash):
            return False, PREFORMAL_SCOPE_HASH_MISMATCH
        if stored_scope.to_dict() != scope.to_dict():
            return False, PREFORMAL_BINDING_MISMATCH
    return True, ""


def _preformal_room_binding(
    room: Mapping[str, Any],
    *,
    scope: PreformalCandidateReviewScopeV1,
) -> tuple[bool, str]:
    config = room.get("config") if isinstance(room.get("config"), Mapping) else room
    if not isinstance(config, Mapping):
        return False, PREFORMAL_ROOM_SCOPE_MISMATCH
    source = _text(config.get("source"))
    if source and source != _PREFORMAL_SCOPE_SOURCE:
        return False, PREFORMAL_ROOM_SCOPE_MISMATCH
    if not source:
        return False, PREFORMAL_ROOM_SCOPE_MISMATCH
    has_explicit_scope = _preformal_scope_candidate(config) is not None
    stored_scope, supplied_hash, _error = _preformal_scope_from_payload(
        config,
        defaults={"roomId": scope.roomId},
        allow_legacy=True,
        include_legacy_scope_hash=False,
    )
    if stored_scope is None:
        return False, PREFORMAL_ROOM_SCOPE_MISMATCH
    if supplied_hash and not _scope_hash_is_valid(stored_scope, supplied_hash):
        return False, PREFORMAL_SCOPE_HASH_MISMATCH
    hash_keys = (
        ("discussionScopeHash", "scopeHash")
        if has_explicit_scope
        else ("discussionScopeHash",)
    )
    for hash_key in hash_keys:
        stored_hash = _text(config.get(hash_key))
        if stored_hash and stored_hash.lower() != stored_scope.scope_hash.lower():
            return False, PREFORMAL_SCOPE_HASH_MISMATCH
    if stored_scope.to_dict() != scope.to_dict():
        return False, PREFORMAL_ROOM_SCOPE_MISMATCH
    return True, ""


def _project_preformal_discussion_anchor(
    scope: PreformalCandidateReviewScopeV1,
    meetings: Any,
    rooms: Any,
) -> dict[str, Any]:
    meeting_records = _records(meetings, "meetings")
    matching_meetings = [
        meeting
        for meeting in meeting_records
        if _meeting_id(meeting) == scope.meetingRoundId
    ]
    if len(matching_meetings) != 1:
        return _preformal_degraded(
            PREFORMAL_MEETING_MISSING,
            scope=scope,
        )
    meeting = matching_meetings[0]
    if _meeting_is_terminal(meeting):
        return _preformal_degraded(PREFORMAL_MEETING_CLOSED, scope=scope)
    valid, reason = _preformal_meeting_binding(meeting, scope=scope)
    if not valid:
        return _preformal_degraded(reason, scope=scope)

    room_records = _records(rooms, "rooms")
    room = next((item for item in room_records if _room_id(item) == scope.roomId), None)
    if room is None:
        return _preformal_degraded(PREFORMAL_ROOM_MISSING, scope=scope)
    valid, reason = _preformal_room_binding(room, scope=scope)
    if not valid:
        return _preformal_degraded(reason, scope=scope)
    readable, room_reason = _room_is_readable(room)
    if not readable:
        return _preformal_degraded(room_reason or ROOM_UNREADABLE, scope=scope)
    return _preformal_ready(scope)


def _ready(
    scope: WorkflowDiscussionScopeV1,
    room_id: str,
    meeting_round_id: str,
) -> dict[str, Any]:
    # Keep the return route aligned with the existing workflow chat anchors:
    # it is an internal path, and both layers use URLSearchParams/urlencode
    # semantics instead of hand-built query escaping.
    return_to = "/teams?" + urlencode(
        {
            "teamId": scope.teamId,
            "researchView": "workflow",
            "runId": scope.workflowRunId,
            "node": scope.workflowNodeId,
        }
    )
    deep_link = "/chat?" + urlencode(
        {
            "room": room_id,
            "returnTo": return_to,
            "returnLabel": "返回科研流程",
        }
    )
    return {
        "scope": scope.to_dict(),
        "scopeHash": scope.scope_hash,
        "roomId": room_id,
        "meetingRoundId": meeting_round_id,
        "questionId": scope.questionId,
        "selectionId": scope.selectionId,
        "candidateId": scope.candidateId,
        "deepLink": deep_link,
        "returnTo": return_to,
        "returnLabel": "返回科研流程",
        "status": STATUS_READY,
        "degradedReason": "",
    }


def project_active_discussion_anchor(
    workflow_projection: Mapping[str, Any] | None,
    meetings: Any = None,
    rooms: Any = None,
) -> dict[str, Any]:
    """Project one navigable anchor from already-loaded scoped records.

    No external store is touched.  ``workflow_projection`` must identify a
    canonical discussion scope.  A candidate-review scope resolves to its one
    candidate room; a generation scope resolves to its one generation room.
    If more than one open meeting remains and the workflow did not name one,
    the result is degraded instead of guessing from list order.
    """

    if not isinstance(workflow_projection, Mapping):
        return _degraded(NO_ACTIVE_DISCUSSION)

    scope, supplied_scope_hash, scope_error = _find_active_scope(workflow_projection)
    if scope is None:
        preformal_scope, preformal_hash, preformal_error = _find_preformal_scope(
            workflow_projection
        )
        if preformal_scope is not None:
            if preformal_hash and not _scope_hash_is_valid(
                preformal_scope, preformal_hash
            ):
                return _preformal_degraded(
                    PREFORMAL_SCOPE_HASH_MISMATCH,
                    scope=preformal_scope,
                )
            refs = _explicit_refs(workflow_projection)
            for field, expected in (
                ("meetingRoundId", preformal_scope.meetingRoundId),
                ("roomId", preformal_scope.roomId),
                ("selectionId", preformal_scope.selectionId),
                ("candidateId", preformal_scope.candidateId),
            ):
                if refs[field] and refs[field] != expected:
                    return _preformal_degraded(
                        PREFORMAL_BINDING_MISMATCH,
                        scope=preformal_scope,
                    )
            return _project_preformal_discussion_anchor(
                preformal_scope,
                meetings,
                rooms,
            )
        return _degraded(
            WORKFLOW_SCOPE_MISSING
            if scope_error == "scope_missing" and preformal_error == "scope_missing"
            else WORKFLOW_SCOPE_INVALID
        )
    if supplied_scope_hash and not _scope_hash_is_valid(scope, supplied_scope_hash):
        return _degraded(WORKFLOW_SCOPE_HASH_MISMATCH, scope=scope)

    refs = _explicit_refs(workflow_projection)
    # An explicit active candidate is an instruction, not a hint.  If the
    # projection carries a different candidate, fail closed before selecting a
    # meeting.  A generation scope may be promoted to a candidate-review scope
    # only when the workflow explicitly names selection+candidate together.
    if refs["candidateId"] and scope.is_candidate_review and refs["candidateId"] != scope.candidateId:
        return _degraded(WORKFLOW_CANDIDATE_MISMATCH, scope=scope)
    if refs["selectionId"] and scope.is_candidate_review and refs["selectionId"] != scope.selectionId:
        return _degraded(WORKFLOW_MEETING_MISMATCH, scope=scope)
    if not scope.is_candidate_review and refs["candidateId"]:
        if not refs["selectionId"]:
            return _degraded(WORKFLOW_CANDIDATE_MISMATCH, scope=scope)
        try:
            scope = WorkflowDiscussionScopeV1.review(
                teamId=scope.teamId,
                researchProjectId=scope.researchProjectId,
                workflowRunId=scope.workflowRunId,
                workflowNodeId=scope.workflowNodeId,
                questionId=scope.questionId,
                selectionId=refs["selectionId"],
                candidateId=refs["candidateId"],
            )
        except ContractValidationError:
            return _degraded(WORKFLOW_SCOPE_INVALID)

    meeting_records = _records(meetings, "meetings")
    room_records = _records(rooms, "rooms")
    if not meeting_records:
        return _degraded(MEETING_MISSING, scope=scope)

    explicit_meeting_id = refs["meetingRoundId"]
    candidate_meetings: list[tuple[Mapping[str, Any], WorkflowDiscussionScopeV1, str]] = []
    malformed_matching: list[Mapping[str, Any]] = []
    for meeting in meeting_records:
        meeting_id = _meeting_id(meeting)
        if explicit_meeting_id and meeting_id != explicit_meeting_id:
            continue
        meeting_scope, meeting_hash, _error = _scope_from_payload(meeting)
        if meeting_scope is None:
            # An explicitly named meeting with missing scope is a precise
            # mismatch; unrelated malformed history is ignored below.
            if explicit_meeting_id and meeting_id == explicit_meeting_id:
                malformed_matching.append(meeting)
            continue
        if meeting_hash and not _scope_hash_is_valid(meeting_scope, meeting_hash):
            if explicit_meeting_id and meeting_id == explicit_meeting_id:
                return _degraded(MEETING_SCOPE_HASH_MISMATCH, scope=scope, meeting_round_id=meeting_id)
            continue
        if scope.is_candidate_review:
            matches_scope = _scope_equal(meeting_scope, scope)
        elif refs["selectionId"]:
            # A selection-level workflow projection carries the common parent
            # identity. Review meetings add candidateId, so match the parent
            # and selection without inventing a candidate from list order.
            matches_scope = (
                meeting_scope.is_candidate_review
                and _scope_base_equal(meeting_scope, scope)
                and meeting_scope.selectionId == refs["selectionId"]
            ) or _scope_equal(meeting_scope, scope)
        else:
            matches_scope = _scope_equal(meeting_scope, scope)
        if not matches_scope:
            continue
        if refs["roomId"] and _meeting_room_id(meeting) and refs["roomId"] != _meeting_room_id(meeting):
            if explicit_meeting_id and meeting_id == explicit_meeting_id:
                return _degraded(WORKFLOW_MEETING_MISMATCH, scope=scope, meeting_round_id=meeting_id)
            continue
        candidate_meetings.append((meeting, meeting_scope, meeting_id))

    if malformed_matching:
        meeting_id = _meeting_id(malformed_matching[0])
        return _degraded(MEETING_SCOPE_MISSING, scope=scope, meeting_round_id=meeting_id)
    if not candidate_meetings:
        return _degraded(
            WORKFLOW_MEETING_MISMATCH if explicit_meeting_id else MEETING_MISSING,
            scope=scope,
            meeting_round_id=explicit_meeting_id,
        )

    if explicit_meeting_id:
        selected = candidate_meetings[0]
    else:
        open_meetings = [item for item in candidate_meetings if _meeting_is_open(item[0])]
        if len(open_meetings) > 1:
            reason = (
                AMBIGUOUS_ACTIVE_CANDIDATE
                if scope.is_candidate_review or any(item[1].is_candidate_review for item in open_meetings)
                else AMBIGUOUS_ACTIVE_MEETING
            )
            return _degraded(reason, scope=scope)
        if len(open_meetings) == 1:
            selected = open_meetings[0]
        elif len(candidate_meetings) == 1:
            selected = candidate_meetings[0]
        else:
            reason = (
                AMBIGUOUS_ACTIVE_CANDIDATE
                if any(item[1].is_candidate_review for item in candidate_meetings)
                else AMBIGUOUS_ACTIVE_MEETING
            )
            return _degraded(reason, scope=scope)

    meeting, meeting_scope, meeting_id = selected
    if not _scope_equal(meeting_scope, scope) and not (
        not scope.is_candidate_review
        and refs["selectionId"]
        and meeting_scope.is_candidate_review
        and _scope_base_equal(meeting_scope, scope)
        and meeting_scope.selectionId == refs["selectionId"]
    ):
        return _degraded(MEETING_SCOPE_MISMATCH, scope=scope, meeting_round_id=meeting_id)
    # Once a concrete candidate meeting has been selected, its full scope is
    # the anchor scope. This is the only point where a selection parent gains a
    # candidate, and it came from a unique/explicit meeting rather than order.
    if not scope.is_candidate_review and meeting_scope.is_candidate_review:
        scope = meeting_scope
    if _meeting_is_terminal(meeting):
        return _degraded(MEETING_CLOSED, scope=scope, meeting_round_id=meeting_id)

    room_id = _meeting_room_id(meeting)
    if refs["roomId"] and room_id and refs["roomId"] != room_id:
        return _degraded(WORKFLOW_MEETING_MISMATCH, scope=scope, meeting_round_id=meeting_id)
    if not room_id:
        return _degraded(MEETING_ROOM_MISSING, scope=scope, meeting_round_id=meeting_id)
    room = next((item for item in room_records if _room_id(item) == room_id), None)
    if room is None:
        return _degraded(ROOM_MISSING, scope=scope, meeting_round_id=meeting_id)
    room_scope, room_hash, _room_error = _scope_from_payload(room)
    if room_scope is None:
        # Some room stores place the scope under config, which is a legitimate
        # scoped room envelope and is handled by _scope_from_payload through
        # the nested key below.  Missing scope is otherwise fail-closed.
        config = room.get("config")
        if isinstance(config, Mapping):
            room_scope, room_hash, _room_error = _scope_from_payload(config)
    if room_scope is None:
        return _degraded(ROOM_SCOPE_MISSING, scope=scope, meeting_round_id=meeting_id)
    if room_hash and not _scope_hash_is_valid(room_scope, room_hash):
        return _degraded(ROOM_SCOPE_HASH_MISMATCH, scope=scope, meeting_round_id=meeting_id)
    if not _scope_equal(room_scope, meeting_scope) or not _scope_equal(room_scope, scope):
        return _degraded(ROOM_SCOPE_MISMATCH, scope=scope, meeting_round_id=meeting_id)
    readable, room_reason = _room_is_readable(room)
    if not readable:
        return _degraded(room_reason or ROOM_UNREADABLE, scope=scope, meeting_round_id=meeting_id)
    return _ready(scope, room_id, meeting_id)


# Friendly aliases for route adapters and tests.  All aliases intentionally
# point at the same pure function so there cannot be multiple anchor rules.
resolve_active_discussion_anchor = project_active_discussion_anchor
build_active_discussion_anchor = project_active_discussion_anchor
project_activeDiscussionAnchor = project_active_discussion_anchor


__all__ = [
    "AMBIGUOUS_ACTIVE_CANDIDATE",
    "AMBIGUOUS_ACTIVE_MEETING",
    "NO_ACTIVE_DISCUSSION",
    "STATUS_DEGRADED",
    "STATUS_READY",
    "build_active_discussion_anchor",
    "project_activeDiscussionAnchor",
    "project_active_discussion_anchor",
    "resolve_active_discussion_anchor",
]
