"""Hidden Child Sessions bound to one Challenge preformal candidate review.

Candidate selection normally happens before a formal research run exists, so a
preformal review room carries a ``PreformalCandidateReviewScopeV1`` instead of a
``WorkflowDiscussionScopeV1``.  Its speakers still must not share an Agent's
long-lived direct Session, because a group round writes its whole transcript
back into the bound Session and the next speaker turn loads that Session as
``chat_history``.  This module resolves exactly one hidden Child Session per
(room scope, Agent) and never falls back to ``directSessionId``.

Ordinary Session admission, journal, worker and SSE semantics are untouched:
the resolver only calls the existing create-session primitives and verifies the
canonical Child Session detail it got back.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.discussion_scope import (
    PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND,
    PreformalCandidateReviewScopeV1,
    session_scope_key,
)
from core.web.services.team_workflow import meeting_rounds

SCHEMA_VERSION = 1
REGISTRY_FILE_NAME = "preformal_review_roots.json"
SESSION_SOURCE = "challenge_preformal_review_session"
SPLIT_REASON = "preformal_candidate_review_scope_v1"
ROOT_TITLE_PREFIX = "挑战杯｜候选预评审"
_REGISTRY_LOCK = threading.RLock()


class PreformalReviewSessionError(RuntimeError):
    """Raised when a preformal review Child Session cannot be resolved safely."""


def resolve_preformal_review_session(
    team_id: str,
    *,
    discussion_scope: PreformalCandidateReviewScopeV1 | Mapping[str, Any],
    agent_id: str,
    role_key: str = "",
    role_label: str = "",
    created_from_task_id: str = "",
    bound_session_id: str = "",
) -> dict[str, Any]:
    """Return the one hidden Child Session bound to this room scope and Agent.

    ``bound_session_id`` is the participant Session the caller read from the
    room; it is reused only when it really is the hidden Child Session for this
    scope, so sibling discussion rounds of one meeting keep the same bounded
    context. Anything else creates a fresh Child Session under the Agent's
    preformal root, and a direct Session is never returned.
    """

    scope = _normalize_scope(discussion_scope)
    normalized_team_id = _text(team_id)
    normalized_agent_id = _text(agent_id)
    if not normalized_agent_id:
        raise PreformalReviewSessionError("preformal review session requires an agentId")
    if scope.teamId != normalized_team_id:
        raise PreformalReviewSessionError(
            "preformal review scope does not match the meeting team"
        )
    normalized_role_key = _text(role_key, limit=80)
    normalized_role_label = _text(role_label, limit=80)

    root_session_id = _resolve_root_session(
        normalized_team_id,
        normalized_agent_id,
        role_key=normalized_role_key,
        role_label=normalized_role_label,
    )
    session_scope = session_scope_key(scope, normalized_agent_id)
    existing_id = _text(bound_session_id)
    if existing_id:
        detail = _service().session_service.get_session_detail(existing_id)
        if _child_detail_matches_scope(
            detail,
            scope=scope,
            agent_id=normalized_agent_id,
            root_session_id=root_session_id,
        ):
            return _result_payload(
                scope=scope,
                session_id=existing_id,
                detail=detail,
                root_session_id=root_session_id,
                agent_id=normalized_agent_id,
                role_key=normalized_role_key,
                session_scope=session_scope,
                created=False,
            )

    title = _child_session_title(scope, normalized_role_label)
    created_at = _service().utc_now_iso()
    binding = {
        "teamId": normalized_team_id,
        "agentId": normalized_agent_id,
        "roleKey": normalized_role_key,
        "roleLabel": normalized_role_label,
        "attempt": 1,
        "retryOfSessionId": "",
        "createdFromTaskId": _text(created_from_task_id),
        "createdAt": created_at,
        "selectionId": scope.selectionId,
        "candidateId": scope.candidateId,
        "discussionScope": scope.to_dict(),
        "discussionScopeHash": scope.scope_hash,
    }
    s = _service()
    child_result = s.session_service.create_child_session(
        root_session_id,
        user_request=f"独立处理题目 {scope.questionId} 候选 {scope.candidateId} 的预评审讨论",
        task_title=title,
        split_reason=SPLIT_REASON,
        auto_start=False,
        switch_to_child=False,
        source=SESSION_SOURCE,
        experiment_binding=binding,
    )
    created_session_id = _text(child_result.get("childSessionId"))
    canonical_detail = (
        s.session_service.get_session_detail(created_session_id)
        if created_session_id
        else None
    )
    if not _child_detail_matches_scope(
        canonical_detail,
        scope=scope,
        agent_id=normalized_agent_id,
        root_session_id=root_session_id,
    ):
        raise PreformalReviewSessionError(
            "New preformal review Session is missing its canonical hidden scope."
        )
    return _result_payload(
        scope=scope,
        session_id=created_session_id,
        detail=canonical_detail,
        root_session_id=root_session_id,
        agent_id=normalized_agent_id,
        role_key=normalized_role_key,
        session_scope=session_scope,
        created=True,
    )


def _normalize_scope(
    value: PreformalCandidateReviewScopeV1 | Mapping[str, Any],
) -> PreformalCandidateReviewScopeV1:
    if isinstance(value, PreformalCandidateReviewScopeV1):
        return value
    if not isinstance(value, Mapping):
        raise PreformalReviewSessionError("preformal review requires a discussion scope")
    try:
        scope = PreformalCandidateReviewScopeV1.from_mapping(value)
    except ContractValidationError as exc:
        raise PreformalReviewSessionError(str(exc)) from exc
    if scope.kind != PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND:
        raise PreformalReviewSessionError(
            "preformal review session requires a preformal candidate review scope"
        )
    return scope


def _resolve_root_session(
    team_id: str,
    agent_id: str,
    *,
    role_key: str,
    role_label: str,
) -> str:
    """Return the Agent's hidden preformal root, creating it exactly once."""

    s = _service()
    with _REGISTRY_LOCK:
        registry = _read_registry(team_id)
        record = registry["agents"].get(agent_id)
        stored_id = _text(record.get("sessionId")) if isinstance(record, Mapping) else ""
        if stored_id:
            detail = s.session_service.get_session_detail(stored_id)
            if _root_detail_matches_agent(detail, agent_id=agent_id):
                return stored_id
            if isinstance(detail, Mapping):
                raise PreformalReviewSessionError(
                    "Preformal review root registry points to a non-canonical root Session."
                )
        created_at = s.utc_now_iso()
        title = _root_session_title(role_label or role_key or agent_id)
        session = s.session_service.create_chat_session(
            title=title,
            agent_id=agent_id,
            created_by=SESSION_SOURCE,
            conversation_index_kind=(
                s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN
            ),
            activate=False,
            experiment_binding={
                "teamId": team_id,
                "agentId": agent_id,
                "roleKey": role_key,
                "roleLabel": role_label,
                "attempt": 1,
                "createdAt": created_at,
            },
        )
        created_session_id = _text(session.get("id"))
        created_detail = s.session_service.get_session_detail(created_session_id)
        if not _root_detail_matches_agent(
            created_detail, agent_id=agent_id
        ) or not _root_is_hidden(created_detail):
            raise PreformalReviewSessionError(
                "New preformal review root Session is missing from the canonical session index."
            )
        registry["agents"][agent_id] = {
            "sessionId": created_session_id,
            "agentId": agent_id,
            "roleKey": role_key,
            "createdAt": created_at,
        }
        _write_registry(team_id, registry)
        return created_session_id


def _root_session_title(role_label: str) -> str:
    return f"{ROOT_TITLE_PREFIX}｜{role_label}"[:120]


def _child_session_title(
    scope: PreformalCandidateReviewScopeV1, role_label: str
) -> str:
    parts = [scope.questionId, "候选预评审", scope.candidateId]
    if role_label:
        parts.append(role_label)
    return "｜".join(parts)[:120]


def _root_detail_matches_agent(
    detail: Any,
    *,
    agent_id: str,
) -> bool:
    if not isinstance(detail, Mapping):
        return False
    session_kind = _text(
        detail.get("sessionKind") or detail.get("session_kind"), limit=40
    ).lower()
    if session_kind and session_kind != "main":
        return False
    if _text(detail.get("agentId")) != agent_id:
        return False
    if _text(detail.get("parentSessionId") or detail.get("parent_session_id")):
        return False
    root_session_id = _text(detail.get("rootSessionId") or detail.get("root_session_id"))
    session_id = _text(detail.get("id") or detail.get("sessionId"))
    return not root_session_id or (bool(session_id) and root_session_id == session_id)


def _root_is_hidden(detail: Any) -> bool:
    return isinstance(detail, Mapping) and detail.get("hiddenFromIndex") is True


def _child_detail_matches_scope(
    detail: Any,
    *,
    scope: PreformalCandidateReviewScopeV1,
    agent_id: str,
    root_session_id: str,
) -> bool:
    if not isinstance(detail, Mapping):
        return False
    return bool(
        _text(detail.get("agentId")) == agent_id
        and _text(detail.get("sessionKind"), limit=40).lower() == "child"
        and detail.get("hiddenFromIndex") is True
        and _text(detail.get("parentSessionId")) == root_session_id
        and _text(detail.get("rootSessionId")) == root_session_id
        and _detail_bound_to_scope(detail, scope)
    )


def _detail_bound_to_scope(
    detail: Mapping[str, Any],
    scope: PreformalCandidateReviewScopeV1,
) -> bool:
    binding = detail.get("experimentBinding")
    if not isinstance(binding, Mapping):
        binding = detail.get("experiment_binding")
    if not isinstance(binding, Mapping):
        return False
    raw_scope = binding.get("discussionScope")
    if not isinstance(raw_scope, Mapping):
        return False
    try:
        bound = PreformalCandidateReviewScopeV1.from_mapping(raw_scope)
    except ContractValidationError:
        return False
    return bool(
        bound.key == scope.key
        and _text(binding.get("discussionScopeHash"), limit=64) == scope.scope_hash
    )


def _result_payload(
    *,
    scope: PreformalCandidateReviewScopeV1,
    session_id: str,
    detail: Mapping[str, Any] | None,
    root_session_id: str,
    agent_id: str,
    role_key: str,
    session_scope: str,
    created: bool,
) -> dict[str, Any]:
    return {
        "sessionId": session_id,
        "sessionKind": "child",
        "sessionCreated": created,
        "title": _text(detail.get("title") if isinstance(detail, Mapping) else "", limit=120),
        "agentId": agent_id,
        "roleKey": role_key,
        "parentSessionId": root_session_id,
        "rootSessionId": root_session_id,
        "discussionScope": scope.to_dict(),
        "discussionScopeHash": scope.scope_hash,
        "discussionSessionScopeKey": session_scope,
    }


def _registry_path(team_id: str) -> Path:
    return (
        meeting_rounds._team_workspace_root(_text(team_id))
        / "research_workflow"
        / REGISTRY_FILE_NAME
    )


def _empty_registry(team_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": _text(team_id),
        "agents": {},
        "updatedAt": "",
    }


def _read_registry(team_id: str) -> dict[str, Any]:
    registry = _empty_registry(team_id)
    path = _registry_path(team_id)
    if not path.exists():
        return registry
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return registry
    if not isinstance(payload, dict):
        return registry
    agents = payload.get("agents") if isinstance(payload.get("agents"), dict) else {}
    registry["agents"] = {
        _text(agent_id): dict(record)
        for agent_id, record in agents.items()
        if _text(agent_id) and isinstance(record, Mapping)
    }
    registry["updatedAt"] = _text(payload.get("updatedAt"), limit=120)
    return registry


def _write_registry(team_id: str, registry: dict[str, Any]) -> None:
    s = _service()
    registry["schemaVersion"] = SCHEMA_VERSION
    registry["teamId"] = _text(team_id)
    registry["updatedAt"] = s.utc_now_iso()
    s._write_json(_registry_path(team_id), registry)


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _text(value: Any, *, limit: int = 160) -> str:
    return str(value or "").strip()[:limit]


__all__ = [
    "PreformalReviewSessionError",
    "REGISTRY_FILE_NAME",
    "SCHEMA_VERSION",
    "SESSION_SOURCE",
    "SPLIT_REASON",
    "resolve_preformal_review_session",
]
