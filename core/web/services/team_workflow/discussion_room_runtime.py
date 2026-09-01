"""Idempotent Challenge Cup chat rooms bound to one discussion scope.

This module owns the room-level binding only.  It deliberately receives
already-resolved participant Child Sessions and never falls back to a team's
public room or an Agent's direct session.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from core.research.workflow.contracts.discussion_scope import (
    DiscussionScopeEnvelope,
    WorkflowDiscussionScopeV1,
    parse_discussion_scope,
    parse_discussion_scope_envelope,
    session_scope_key,
)


ROOM_SCOPE_SOURCE = "challenge_workflow"
ROOM_SCOPE_AUTHORITY = "workflow_discussion_scope.v1"


class DiscussionRoomBindingError(RuntimeError):
    """Raised when a formal room cannot be bound without crossing scopes."""


class _ChatRoomPort(Protocol):
    def list_chat_rooms(self) -> list[dict[str, Any]]: ...

    def get_chat_room_detail(self, room_id: str) -> dict[str, Any] | None: ...

    def create_chat_room(self, **payload: Any) -> dict[str, Any]: ...


def _chat_room_port() -> _ChatRoomPort:
    from core.web.services import chat_room_service

    return chat_room_service


def _text(value: Any, *, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def validate_scoped_child_session_bindings(
    scope: DiscussionScopeEnvelope | Mapping[str, Any],
    bindings: Sequence[Mapping[str, Any]],
) -> tuple[list[str], dict[str, str]]:
    """Check the Child Sessions one scoped room owns and return their order."""

    return _participant_bindings(parse_discussion_scope_envelope(scope), bindings)


def _participant_bindings(
    scope: DiscussionScopeEnvelope,
    bindings: Sequence[Mapping[str, Any]],
) -> tuple[list[str], dict[str, str]]:
    session_ids: list[str] = []
    by_agent_id: dict[str, str] = {}
    seen_session_ids: set[str] = set()
    for index, raw in enumerate(bindings):
        if not isinstance(raw, Mapping):
            raise DiscussionRoomBindingError(
                f"participant binding {index} must be an object"
            )
        agent_id = _text(raw.get("agentId"))
        session_id = _text(raw.get("sessionId"))
        if not agent_id or not session_id:
            raise DiscussionRoomBindingError(
                "scoped discussion participants require agentId and scoped sessionId"
            )
        if agent_id in by_agent_id or session_id in seen_session_ids:
            raise DiscussionRoomBindingError(
                "scoped discussion participant Agent and session bindings must be unique"
            )
        raw_scope = raw.get("discussionScope")
        if not isinstance(raw_scope, Mapping):
            raise DiscussionRoomBindingError(
                f"participant {agent_id} is missing discussionScope"
            )
        try:
            participant_scope = parse_discussion_scope_envelope(raw_scope)
        except Exception as exc:
            raise DiscussionRoomBindingError(
                f"participant {agent_id} has an invalid discussionScope"
            ) from exc
        supplied_hash = _text(raw.get("discussionScopeHash"), limit=64).lower()
        if participant_scope.key != scope.key or supplied_hash != scope.scope_hash:
            raise DiscussionRoomBindingError(
                f"participant {agent_id} is bound to a different discussion scope"
            )
        supplied_session_key = _text(raw.get("discussionSessionScopeKey"), limit=700)
        expected_session_key = session_scope_key(scope, agent_id)
        if supplied_session_key and supplied_session_key != expected_session_key:
            raise DiscussionRoomBindingError(
                f"participant {agent_id} has a mismatched discussion session scope key"
            )
        by_agent_id[agent_id] = session_id
        seen_session_ids.add(session_id)
        session_ids.append(session_id)
    if not session_ids:
        raise DiscussionRoomBindingError(
            "scoped discussion room requires participant Child Sessions"
        )
    return session_ids, by_agent_id


def _room_config(scope: WorkflowDiscussionScopeV1) -> dict[str, Any]:
    return {
        "source": ROOM_SCOPE_SOURCE,
        "scopeAuthority": ROOM_SCOPE_AUTHORITY,
        "teamId": scope.teamId,
        "researchProjectId": scope.researchProjectId,
        "workflowRunId": scope.workflowRunId,
        "workflowNodeId": scope.workflowNodeId,
        "questionId": scope.questionId,
        "discussionScope": scope.to_dict(),
        "scopeHash": scope.scope_hash,
        **(
            {
                "selectionId": scope.selectionId,
                "candidateId": scope.candidateId,
            }
            if scope.is_candidate_review
            else {}
        ),
    }


def _room_binding(
    room: Mapping[str, Any] | None,
    *,
    scope: WorkflowDiscussionScopeV1,
    expected_by_agent_id: Mapping[str, str],
) -> dict[str, Any]:
    if not isinstance(room, Mapping):
        raise DiscussionRoomBindingError("scoped discussion room is missing")
    room_id = _text(room.get("roomId"))
    config = room.get("config")
    if not room_id or not isinstance(config, Mapping):
        raise DiscussionRoomBindingError("scoped discussion room has no canonical config")
    if _text(config.get("source")) != ROOM_SCOPE_SOURCE:
        raise DiscussionRoomBindingError("formal discussion room has a non-workflow source")
    raw_scope = config.get("discussionScope")
    if not isinstance(raw_scope, Mapping):
        raise DiscussionRoomBindingError("formal discussion room is missing discussionScope")
    try:
        stored_scope = parse_discussion_scope(raw_scope)
    except Exception as exc:
        raise DiscussionRoomBindingError(
            "formal discussion room has an invalid discussionScope"
        ) from exc
    if (
        stored_scope.key != scope.key
        or _text(config.get("scopeHash"), limit=64).lower() != scope.scope_hash
    ):
        raise DiscussionRoomBindingError(
            "formal discussion room config is bound to a different scope"
        )

    actual_by_agent_id: dict[str, str] = {}
    for participant in list(room.get("participants") or []):
        if not isinstance(participant, Mapping):
            continue
        agent_id = _text(participant.get("agentId"))
        session_id = _text(participant.get("sessionId"))
        if not agent_id or not session_id or agent_id in actual_by_agent_id:
            raise DiscussionRoomBindingError(
                "formal discussion room has an invalid participant binding"
            )
        actual_by_agent_id[agent_id] = session_id
    if actual_by_agent_id != dict(expected_by_agent_id):
        raise DiscussionRoomBindingError(
            "formal discussion room participant Child Sessions do not match the scope"
        )
    return dict(room)


def resolve_scoped_discussion_room(
    scope: WorkflowDiscussionScopeV1 | Mapping[str, Any],
    participant_bindings: Sequence[Mapping[str, Any]],
    *,
    title: str = "",
    participant_contexts_by_agent_id: Mapping[str, Mapping[str, Any]] | None = None,
    port: _ChatRoomPort | None = None,
) -> dict[str, Any]:
    """Resolve or create exactly one room for a canonical discussion scope.

    The deterministic room id makes retries idempotent.  Any pre-existing room
    with mismatched scope or participant Child Sessions fails closed instead
    of falling back to ``linkedChatRoomId``/``directSessionId``.
    """

    normalized_scope = parse_discussion_scope(scope)
    session_ids, expected_by_agent_id = _participant_bindings(
        normalized_scope, participant_bindings
    )
    chat_rooms = port or _chat_room_port()
    room_id = f"room-challenge-{normalized_scope.scope_hash[:24]}"

    existing = chat_rooms.get_chat_room_detail(room_id)
    if isinstance(existing, Mapping):
        return {
            "status": "reused",
            "roomId": room_id,
            "scope": normalized_scope.to_dict(),
            "scopeHash": normalized_scope.scope_hash,
            "room": _room_binding(
                existing,
                scope=normalized_scope,
                expected_by_agent_id=expected_by_agent_id,
            ),
        }

    created = chat_rooms.create_chat_room(
        room_id=room_id,
        title=_text(title, limit=120)
        or f"{normalized_scope.questionId} | {normalized_scope.kind}",
        participant_session_ids=session_ids,
        participant_contexts_by_agent_id=(
            {
                agent_id: dict(context)
                for agent_id, context in dict(participant_contexts_by_agent_id).items()
            }
            if isinstance(participant_contexts_by_agent_id, Mapping)
            else None
        ),
        mode="round_robin",
        purpose="meeting",
        config=_room_config(normalized_scope),
    )
    bound = _room_binding(
        created,
        scope=normalized_scope,
        expected_by_agent_id=expected_by_agent_id,
    )
    return {
        "status": "created",
        "roomId": room_id,
        "scope": normalized_scope.to_dict(),
        "scopeHash": normalized_scope.scope_hash,
        "room": bound,
    }


__all__ = [
    "DiscussionRoomBindingError",
    "ROOM_SCOPE_AUTHORITY",
    "ROOM_SCOPE_SOURCE",
    "resolve_scoped_discussion_room",
    "validate_scoped_child_session_bindings",
]
