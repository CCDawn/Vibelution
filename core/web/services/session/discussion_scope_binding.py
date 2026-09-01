"""Private allowlist for Challenge Cup Discussion Scope session bindings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.discussion_scope import (
    PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND,
    PreformalCandidateReviewScopeV1,
    parse_discussion_scope,
)


class DiscussionScopeBindingError(ValueError):
    """Raised when a Session binding carries an incomplete or foreign scope."""


def normalize_discussion_scope_binding(
    raw_binding: Mapping[str, Any],
    *,
    team_id: str,
    research_project_id: str,
    workflow_run_id: str,
    workflow_node_id: str,
    selection_id: str = "",
    candidate_id: str = "",
) -> dict[str, Any]:
    """Return a strict, path-free discussion binding or an empty mapping."""

    raw_scope = raw_binding.get("discussionScope")
    raw_hash = str(raw_binding.get("discussionScopeHash") or "").strip().lower()
    if raw_scope is None and not raw_hash:
        return {}
    if not isinstance(raw_scope, Mapping) or not raw_hash:
        raise DiscussionScopeBindingError(
            "Discussion scope binding requires discussionScope and discussionScopeHash."
        )
    if str(raw_scope.get("kind") or "").strip() == PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND:
        return _normalize_preformal_binding(
            raw_scope,
            raw_hash,
            team_id=team_id,
            selection_id=selection_id,
            candidate_id=candidate_id,
            formal_identity={
                "researchProjectId": research_project_id,
                "workflowRunId": workflow_run_id,
                "workflowNodeId": workflow_node_id,
            },
        )
    try:
        scope = parse_discussion_scope(raw_scope)
    except ContractValidationError as exc:
        raise DiscussionScopeBindingError(str(exc)) from exc
    expected = {
        "teamId": str(team_id or "").strip(),
        "researchProjectId": str(research_project_id or "").strip(),
        "workflowRunId": str(workflow_run_id or "").strip(),
        "workflowNodeId": str(workflow_node_id or "").strip(),
        "selectionId": str(selection_id or "").strip(),
        "candidateId": str(candidate_id or "").strip(),
    }
    actual = {
        "teamId": scope.teamId,
        "researchProjectId": scope.researchProjectId,
        "workflowRunId": scope.workflowRunId,
        "workflowNodeId": scope.workflowNodeId,
        "selectionId": scope.selectionId,
        "candidateId": scope.candidateId,
    }
    if actual != expected:
        raise DiscussionScopeBindingError(
            "Discussion scope identity does not match the Session experiment binding."
        )
    if raw_hash != scope.scope_hash:
        raise DiscussionScopeBindingError(
            "Discussion scope hash does not match the Session experiment binding."
        )
    return {
        "discussionScope": scope.to_dict(),
        "discussionScopeHash": scope.scope_hash,
    }


def _normalize_preformal_binding(
    raw_scope: Mapping[str, Any],
    raw_hash: str,
    *,
    team_id: str,
    selection_id: str,
    candidate_id: str,
    formal_identity: Mapping[str, str],
) -> dict[str, Any]:
    """Bind a pre-formal candidate review without inventing run or project identity."""

    claimed = {
        key: str(value or "").strip()
        for key, value in formal_identity.items()
        if str(value or "").strip()
    }
    if claimed:
        raise DiscussionScopeBindingError(
            "Preformal discussion scope binding must not claim "
            + ", ".join(sorted(claimed))
        )
    try:
        scope = PreformalCandidateReviewScopeV1.from_mapping(raw_scope)
    except ContractValidationError as exc:
        raise DiscussionScopeBindingError(str(exc)) from exc
    expected = {
        "teamId": str(team_id or "").strip(),
        "selectionId": str(selection_id or "").strip(),
        "candidateId": str(candidate_id or "").strip(),
    }
    actual = {
        "teamId": scope.teamId,
        "selectionId": scope.selectionId,
        "candidateId": scope.candidateId,
    }
    if actual != expected:
        raise DiscussionScopeBindingError(
            "Preformal discussion scope identity does not match the Session experiment binding."
        )
    if raw_hash != scope.scope_hash:
        raise DiscussionScopeBindingError(
            "Discussion scope hash does not match the Session experiment binding."
        )
    return {
        "discussionScope": scope.to_dict(),
        "discussionScopeHash": scope.scope_hash,
    }


__all__ = [
    "DiscussionScopeBindingError",
    "normalize_discussion_scope_binding",
]
