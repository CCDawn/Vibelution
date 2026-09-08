from types import SimpleNamespace

import pytest


def test_run_without_drafts_cannot_consume_another_runs_r0(monkeypatch):
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain as chain
    monkeypatch.setattr(chain, "list_exploratory_drafts", lambda *_, **kw: {
        "drafts": [] if kw.get("workflow_run_id") else [
            {"draftId": "origin", "meetingRoundId": "origin-meeting"},
            {"draftId": "other-run", "meetingRoundId": "other-meeting"},
            {"draftId": "tagged-run", "meetingRoundId": "tagged-meeting"},
        ],
    })
    monkeypatch.setattr(chain, "_question_generation_meetings", lambda *_: [
        {"meetingRoundId": "origin-meeting"},
        {"meetingRoundId": "other-meeting", "modelInvocationReceiptAuthority": {"workflowRunId": "run-other"}},
        {"meetingRoundId": "tagged-meeting", "workflowRunId": "run-other"},
    ])
    assert chain._available_exploratory_drafts("team", "SCI-009", workflow_run_id="run-current") == [
        {"draftId": "origin", "meetingRoundId": "origin-meeting"},
    ]

from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow import research_project_hypothesis_context as context
from core.web.services.team_workflow.research_runtime import agent_task_artifact_builder
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import canonical_sha256


def _problem():
    return {
        "scope": "Engineered materials containing living cells; exclude cell-free TX-TL.",
        "subquestions": ["Can switching be reversed?"],
        "assumptions": ["Cells remain viable."],
        "known_unknowns": ["Switching duration."],
        "human_gate": {"required": True, "decision": "pending", "rationale": "Review required."},
    }


def test_grounded_scope_uses_latest_attempt_and_preserves_pending_gate(monkeypatch):
    attempts = [
        SimpleNamespace(node_id="problem_understanding", attempt=1, status="succeeded", node_run_id="old"),
        SimpleNamespace(node_id="problem_understanding", attempt=2, status="succeeded", node_run_id="current"),
        SimpleNamespace(node_id="hypothesis_design", attempt=3, status="running", node_run_id="other"),
    ]
    store = SimpleNamespace(read=lambda f: f(SimpleNamespace(list_attempts=lambda run: attempts)))
    observed = {}

    def readback(**kwargs):
        observed.update(kwargs)
        return _problem()

    monkeypatch.setattr(agent_task_artifact_builder, "load_canonical_problem_understanding_payload", readback)
    result = context._grounded_problem_context("research-team", "run-current", store=store)
    assert observed == {"record": {"teamId": "research-team", "runId": "run-current"}, "node_run": {"nodeRunId": "current"}}
    assert result == {"workflowRunId": "run-current", "nodeRunId": "current", "contentHash": canonical_sha256(_problem()), "payload": _problem()}
    assert result["payload"]["human_gate"]["decision"] == "pending"


@pytest.mark.parametrize("status", ["running", "failed"])
def test_grounded_scope_never_falls_back_to_old_success(status):
    attempts = [
        SimpleNamespace(node_id="problem_understanding", attempt=1, status="succeeded", node_run_id="old"),
        SimpleNamespace(node_id="problem_understanding", attempt=2, status=status, node_run_id="current"),
    ]
    store = SimpleNamespace(read=lambda f: f(SimpleNamespace(list_attempts=lambda run: attempts)))
    assert context._grounded_problem_context("research-team", "run-current", store=store) is None


def test_generation_discussion_receives_scope_identity_and_research_limits():
    topic = meeting_runtime._generation_opening_topic(
        "meeting-r1", "SCI-011", [], generation_context={
            "candidateAuthority": "formal_grounded_candidate",
            "problemUnderstandingContext": {"workflowRunId": "run-current", "nodeRunId": "scope-v2", "contentHash": "hash-v2", "payload": _problem()},
            "evidenceClaims": [{"sourceRef": "source:1", "claim": "Cells survive switching."}],
        },
    )
    for value in ["scope-v2", "hash-v2", _problem()["scope"], "Switching duration.", "pending", "source:1"]:
        assert value in topic
    assert "设计参数" in topic
    assert "替代解释" in topic
    assert "对照" in topic
    assert "资源" in topic


def test_formal_generation_passes_problem_context_to_meeting(tmp_path, monkeypatch):
    from tests.test_research_workflow_hypothesis_first_chain import (
        _hf_env, _QUESTION_ID, _ROLES, _candidate_generation_runner,
        _drive_to_awaiting_approval, _closure_payload, server_operator_scope,
    )
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain as chain

    team_id, agents = _hf_env(tmp_path, monkeypatch)
    problem_context = {"workflowRunId": "run-current", "nodeRunId": "scope-v2", "contentHash": "hash-v2", "payload": _problem()}

    class MeetingReached(Exception):
        pass

    def capture(_team, payload, **kwargs):
        assert payload["generationContext"]["problemUnderstandingContext"] == problem_context
        raise MeetingReached

    with server_operator_scope("u-1", roles=("operator",)):
        r0 = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner,
            _candidate_authority="exploratory_draft",
        )["meetingRound"]["meetingRoundId"]
        agent_ids = [agents[role] for role in _ROLES]
        _drive_to_awaiting_approval(team_id, r0, agent_ids[0])
        chain.close_review_meeting(team_id, r0, _closure_payload(agent_ids, []))
        monkeypatch.setattr(meeting_runtime, "open_candidate_generation_meeting", capture)
        with pytest.raises(MeetingReached):
            chain.open_candidate_generation_meeting(
                team_id, _QUESTION_ID, _candidate_authority="formal_grounded_candidate",
                _generation_context={
                    "status": "ready", "allowedEvidenceRefs": ["evidence:accepted-1"],
                    "problemUnderstandingContext": problem_context,
                },
            )
