"""T7: preformal candidate reviews speak through hidden Child Sessions.

A preformal review room has no formal workflow run yet, so its scope is a
``PreformalCandidateReviewScopeV1``. These tests pin the Session isolation
contract for that room: every participant resolves to exactly one hidden Child
Session bound to the room scope, the Agent's long-lived direct Session is never
used or written, and a mismatched scope fails closed instead of falling back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.research.workflow.contracts.discussion_scope import (
    PreformalCandidateReviewScopeV1,
    session_scope_key,
)
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    session_service,
    team_service,
)
from core.web.services.session.discussion_scope_binding import (
    DiscussionScopeBindingError,
    normalize_discussion_scope_binding,
)
from core.web.services.session.projection import _public_experiment_binding
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import preformal_review_sessions as sessions

from tests._support.team_workflow.helpers import (
    _use_fake_local_research_config,
    _use_tmp_project_root,
)

_TEAM_ROLES = ("coordinator", "researcher")


def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, dict[str, str]]:
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    agents: dict[str, str] = {}
    for role in _TEAM_ROLES:
        agent = agent_directory_service.create_agent_instance(
            display_name=f"T7 {role}",
            role_key=role,
            created_by="t7-test",
        )
        session_service.ensure_agent_direct_session(
            agent_id=agent["agentId"], title=f"T7 {role}"
        )
        agents[role] = agent["agentId"]
    team_id = team_service.create_team(
        name="T7 预评审隔离团队",
        purpose="challenge-preformal-review-session",
        members=[{"agentId": agents[role], "role": role} for role in _TEAM_ROLES],
    )["teamId"]
    return team_id, agents


def _scope(team_id: str, *, candidate_id: str = "hyp-a") -> PreformalCandidateReviewScopeV1:
    return PreformalCandidateReviewScopeV1.review(
        teamId=team_id,
        questionId="SCI-096",
        selectionId="hsel-t7-1",
        candidateId=candidate_id,
        meetingRoundId=f"meeting-t7-{candidate_id}",
        roomId=f"room-t7-{candidate_id}",
    )


def test_preformal_review_session_binds_hidden_child_not_direct_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _env(tmp_path, monkeypatch)
    agent_id = agents["coordinator"]
    direct_session_id = str(
        (
            session_service.ensure_agent_direct_session(agent_id=agent_id) or {}
        ).get("id")
        or ""
    )
    scope = _scope(team_id)

    resolved = sessions.resolve_preformal_review_session(
        team_id,
        discussion_scope=scope,
        agent_id=agent_id,
        role_key="coordinator",
        role_label="协调员",
        created_from_task_id="meeting-t7-hyp-a",
    )

    assert resolved["sessionCreated"] is True
    assert resolved["sessionKind"] == "child"
    child_session_id = resolved["sessionId"]
    assert child_session_id
    assert child_session_id != direct_session_id
    assert resolved["discussionScopeHash"] == scope.scope_hash
    assert resolved["discussionSessionScopeKey"] == session_scope_key(scope, agent_id)

    detail = session_service.get_session_detail(child_session_id)
    assert detail is not None
    assert detail["sessionKind"] == "child"
    assert detail["hiddenFromIndex"] is True
    assert detail["parentSessionId"] == resolved["rootSessionId"]
    assert detail["rootSessionId"] == resolved["rootSessionId"]
    binding = detail["experimentBinding"]
    assert binding["discussionScope"] == scope.to_dict()
    assert binding["discussionScopeHash"] == scope.scope_hash
    assert binding["selectionId"] == "hsel-t7-1"
    assert binding["candidateId"] == "hyp-a"

    root_detail = session_service.get_session_detail(resolved["rootSessionId"])
    assert root_detail is not None
    assert root_detail["sessionKind"] == "main"
    assert root_detail["hiddenFromIndex"] is True

    direct_detail = session_service.get_session_detail(direct_session_id)
    assert direct_detail is not None
    assert direct_detail["agentId"] == agent_id
    assert not direct_detail.get("childSessionIds")


def test_preformal_review_session_is_idempotent_per_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _env(tmp_path, monkeypatch)
    agent_id = agents["coordinator"]
    scope = _scope(team_id)

    first = sessions.resolve_preformal_review_session(
        team_id,
        discussion_scope=scope,
        agent_id=agent_id,
        role_key="coordinator",
        role_label="协调员",
    )
    second = sessions.resolve_preformal_review_session(
        team_id,
        discussion_scope=scope,
        agent_id=agent_id,
        role_key="coordinator",
        role_label="协调员",
        bound_session_id=first["sessionId"],
    )
    other_candidate = sessions.resolve_preformal_review_session(
        team_id,
        discussion_scope=_scope(team_id, candidate_id="hyp-b"),
        agent_id=agent_id,
        role_key="coordinator",
        role_label="协调员",
    )

    assert second["sessionId"] == first["sessionId"]
    assert second["sessionCreated"] is False
    assert other_candidate["sessionId"] != first["sessionId"]
    assert other_candidate["rootSessionId"] == first["rootSessionId"]

    registry = json.loads(
        Path(sessions._registry_path(team_id)).read_text(encoding="utf-8")
    )
    assert list(registry["agents"]) == [agent_id]


def test_preformal_review_session_rejects_foreign_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _env(tmp_path, monkeypatch)
    agent_id = agents["coordinator"]
    scope = _scope(team_id)
    resolved = sessions.resolve_preformal_review_session(
        team_id,
        discussion_scope=scope,
        agent_id=agent_id,
        role_key="coordinator",
    )

    with pytest.raises(sessions.PreformalReviewSessionError):
        sessions.resolve_preformal_review_session(
            "other-team",
            discussion_scope=scope,
            agent_id=agent_id,
            bound_session_id=resolved["sessionId"],
        )

    sibling = agents["researcher"]
    mismatched = sessions.resolve_preformal_review_session(
        team_id,
        discussion_scope=scope,
        agent_id=sibling,
        role_key="researcher",
        bound_session_id=resolved["sessionId"],
    )
    assert mismatched["sessionId"] != resolved["sessionId"]
    assert mismatched["agentId"] == sibling


def _preformal_binding_kwargs(scope: PreformalCandidateReviewScopeV1, **overrides) -> dict:
    kwargs = {
        "team_id": scope.teamId,
        "research_project_id": "",
        "workflow_run_id": "",
        "workflow_node_id": "",
        "selection_id": scope.selectionId,
        "candidate_id": scope.candidateId,
    }
    kwargs.update(overrides)
    return kwargs


def test_discussion_scope_binding_accepts_preformal_identity() -> None:
    scope = _scope("t7")

    normalized = normalize_discussion_scope_binding(
        {"discussionScope": scope.to_dict(), "discussionScopeHash": scope.scope_hash},
        **_preformal_binding_kwargs(scope),
    )

    assert normalized == {
        "discussionScope": scope.to_dict(),
        "discussionScopeHash": scope.scope_hash,
    }


@pytest.mark.parametrize(
    "claimed",
    [
        {"research_project_id": "project-1"},
        {"workflow_run_id": "run-1", "workflow_node_id": "node-1"},
    ],
)
def test_preformal_binding_refuses_claimed_formal_identity(claimed: dict) -> None:
    scope = _scope("t7")

    with pytest.raises(DiscussionScopeBindingError, match="must not claim"):
        normalize_discussion_scope_binding(
            {"discussionScope": scope.to_dict(), "discussionScopeHash": scope.scope_hash},
            **_preformal_binding_kwargs(scope, **claimed),
        )


def test_preformal_binding_rejects_foreign_identity_and_hash() -> None:
    scope = _scope("t7")
    payload = {
        "discussionScope": scope.to_dict(),
        "discussionScopeHash": scope.scope_hash,
    }

    with pytest.raises(DiscussionScopeBindingError, match="does not match"):
        normalize_discussion_scope_binding(
            payload, **_preformal_binding_kwargs(scope, candidate_id="hyp-other")
        )
    with pytest.raises(DiscussionScopeBindingError, match="does not match"):
        normalize_discussion_scope_binding(
            {**payload, "discussionScopeHash": "0" * 64},
            **_preformal_binding_kwargs(scope),
        )
    with pytest.raises(DiscussionScopeBindingError, match="does not match"):
        normalize_discussion_scope_binding(
            payload, **_preformal_binding_kwargs(scope, team_id="t8")
        )


def test_public_experiment_binding_projects_preformal_child() -> None:
    scope = _scope("t7")
    projected = _public_experiment_binding(
        {
            "teamId": "t7",
            "agentId": "agent-t7",
            "roleKey": "coordinator",
            "attempt": 1,
            "selectionId": scope.selectionId,
            "candidateId": scope.candidateId,
            "discussionScope": scope.to_dict(),
            "discussionScopeHash": scope.scope_hash,
        }
    )

    assert projected is not None
    assert projected["selectionId"] == scope.selectionId
    assert projected["candidateId"] == scope.candidateId
    assert projected["researchProjectId"] == ""
    assert projected["discussionScope"] == scope.to_dict()
    assert projected["discussionScopeHash"] == scope.scope_hash

    assert (
        _public_experiment_binding(
            {
                "teamId": "t7",
                "agentId": "agent-t7",
                "attempt": 1,
                "selectionId": scope.selectionId,
                "candidateId": scope.candidateId,
                "discussionScope": scope.to_dict(),
                "discussionScopeHash": scope.scope_hash,
                "workflowRunId": "run-1",
                "workflowNodeId": "node-1",
            }
        )
        is None
    )
    assert (
        _public_experiment_binding(
            {
                "teamId": "t7",
                "agentId": "agent-t7",
                "attempt": 1,
                "selectionId": scope.selectionId,
                "candidateId": scope.candidateId,
            }
        )
        is None
    )


def test_session_scope_key_serializes_preformal_envelope_once() -> None:
    scope = _scope("t7")

    assert session_scope_key(scope.to_dict(), "agent-t7") == session_scope_key(
        scope, "agent-t7"
    )
    assert session_scope_key(scope, "agent-t7").startswith(
        "v3|session|agent-t7|v1|preformal_candidate_review|t7|SCI-096|hsel-t7-1|hyp-a|"
    )


def test_preformal_review_sessions_stay_out_of_the_ordinary_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ordinary Session listings must not gain the hidden review lineage."""

    team_id, agents = _env(tmp_path, monkeypatch)
    agent_id = agents["coordinator"]
    direct_session_id = str(
        (session_service.ensure_agent_direct_session(agent_id=agent_id) or {}).get("id")
        or ""
    )
    visible_before = {
        item["id"] for item in session_service.list_sessions(include_hidden_internal=True)
    }

    resolved = sessions.resolve_preformal_review_session(
        team_id,
        discussion_scope=_scope(team_id),
        agent_id=agent_id,
        role_key="coordinator",
    )

    ordinary = {item["id"] for item in session_service.list_sessions()}
    assert resolved["sessionId"] not in ordinary
    assert resolved["rootSessionId"] not in ordinary
    assert direct_session_id in ordinary
    hidden = {
        item["id"] for item in session_service.list_sessions(include_hidden_internal=True)
    } - visible_before
    assert {resolved["sessionId"], resolved["rootSessionId"]} <= hidden


def test_ordinary_room_participants_still_resolve_to_direct_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, agents = _env(tmp_path, monkeypatch)
    agent_ids = [agents["coordinator"], agents["researcher"]]
    direct_ids = {
        agent_id: str(
            (session_service.ensure_agent_direct_session(agent_id=agent_id) or {}).get("id")
            or ""
        )
        for agent_id in agent_ids
    }

    room = chat_room_service.create_chat_room(
        title="T7 普通房间",
        participant_agent_ids=agent_ids,
        mode="round_robin",
    )

    bound = {
        str(participant["agentId"]): str(participant.get("sessionId") or "")
        for participant in room["participants"]
    }
    assert bound == direct_ids
