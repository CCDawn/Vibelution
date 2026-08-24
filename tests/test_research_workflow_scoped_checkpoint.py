"""Narrow contract checks for challenge Discussion Scope checkpoints.

The runtime integration suite owns graph/room orchestration.  These tests keep
the checkpoint lane focused on metadata-only persistence and fail-closed
five-way scope comparison.
"""

from __future__ import annotations

from core.research.workflow.challenge_cup_runtime import (
    GraphDispatch,
    _validate_state_scope_binding,
)
from core.research.workflow.checkpoint_store import (
    ScopeBindingMismatch,
    assert_scope_bindings_match,
    build_checkpoint_binding_payload,
    canonical_discussion_scope,
    validate_scope_bindings,
)


def _scope() -> dict[str, str | int]:
    return {
        "version": 1,
        "kind": "candidate_review",
        "teamId": "research-team",
        "researchProjectId": "challenge-sci-096",
        "workflowRunId": "run-1",
        "workflowNodeId": "hypothesis_review",
        "questionId": "SCI-096",
        "selectionId": "selection-1",
        "candidateId": "H2",
    }


def test_checkpoint_binding_derives_hash_and_excludes_chat_body() -> None:
    binding = build_checkpoint_binding_payload(
        _scope(),
        room_ref={"roomId": "room-1", "messages": ["must not persist"]},
    )
    assert binding["scopeHash"] == binding["scope"]["scopeHash"]
    assert "messages" not in binding["roomRef"]
    assert "scopeHash" in canonical_discussion_scope(binding["scope"], require_hash=True)


def test_five_way_scope_binding_accepts_child_scope_without_agent_id() -> None:
    scope = canonical_discussion_scope(_scope())
    participant_scope = {**scope, "agentId": "agent-a"}
    result = assert_scope_bindings_match(
        workflow_checkpoint={"scope": scope},
        business_checkpoint={"scope": scope},
        meeting={"scope": scope},
        room={"config": {"scope": scope}},
        participant_sessions=[{"scope": participant_scope, "childSessionId": "child-a"}],
    )
    assert result["scopeHash"] == scope["scopeHash"]


def test_five_way_scope_binding_returns_blocked_code_for_mismatch() -> None:
    scope = canonical_discussion_scope(_scope())
    other = canonical_discussion_scope({**_scope(), "candidateId": "H3"})
    result = validate_scope_bindings(
        workflow_checkpoint={"scope": scope},
        business_checkpoint={"scope": scope},
        meeting={"scope": other},
        room={"config": {"scope": scope}},
        participant_sessions=[{"scope": {**scope, "agentId": "agent-a"}}],
    )
    assert result["ok"] is False
    assert result["code"] == "scope_binding_mismatch"


def test_graph_dispatch_round_trips_scoped_binding_metadata() -> None:
    dispatch = GraphDispatch(
        action_id="act-1",
        run_id="run-1",
        node_run_id="node-run-1",
        node_id="hypothesis_review",
        attempt=1,
        dispatch_kind="start",
        discussion_scope=_scope(),
        scope_binding_required=True,
    )
    restored = GraphDispatch.from_payload(dispatch.to_payload())
    assert restored.scope_binding_required is True
    assert restored.discussion_scope is not None
    assert restored.scope_hash


def test_direct_session_is_rejected_for_formal_participant_binding() -> None:
    scope = canonical_discussion_scope(_scope())
    try:
        assert_scope_bindings_match(
            workflow_checkpoint={"scope": scope},
            business_checkpoint={"scope": scope},
            meeting={"scope": scope},
            room={"config": {"scope": scope}},
            participant_sessions=[
                {
                    "scope": {**scope, "agentId": "agent-a"},
                    "directSessionId": "agent-a-direct",
                }
            ],
        )
    except ScopeBindingMismatch as exc:
        assert exc.code == "scope_binding_mismatch"
    else:  # pragma: no cover - protects the fail-closed contract
        raise AssertionError("direct Session binding must be rejected")


def test_formal_graph_checkpoint_requires_all_five_authorities() -> None:
    scope = canonical_discussion_scope(_scope())
    try:
        _validate_state_scope_binding(
            {
                "scope_binding_required": True,
                "discussion_scope": scope,
                "discussion_scope_hash": scope["scopeHash"],
            }
        )
    except ScopeBindingMismatch as exc:
        assert exc.code == "scope_binding_mismatch"
        assert exc.field == "businessCheckpoint.scope"
    else:  # pragma: no cover - formal graphs must never resume partially bound
        raise AssertionError("a formal checkpoint without five authorities must block")


def test_formal_graph_checkpoint_accepts_matching_five_authorities() -> None:
    scope = canonical_discussion_scope(_scope())
    authority = {"scope": scope}
    participant = {"scope": {**scope, "agentId": "agent-a"}}
    result = _validate_state_scope_binding(
        {
            "scope_binding_required": True,
            "discussion_scope": scope,
            "discussion_scope_hash": scope["scopeHash"],
            "business_checkpoint_ref": authority,
            "meeting_ref": authority,
            "room_ref": authority,
            "participant_binding_refs": [participant],
        }
    )
    assert result is not None
    assert result["scopeHash"] == scope["scopeHash"]
