"""D04 meeting closure, digest, decision and private-memory handoff tests."""

from __future__ import annotations

import pytest

from core.research.workflow.contracts import ContractValidationError
from core.web.services import team_service
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import personal_memory_candidates as memories


def _team(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memories, "PROJECT_ROOT", tmp_path)
    return team_service.create_team(name="meeting team")["teamId"]


def _scope(**overrides):
    payload = {
        "program": "XH-202619",
        "theme": "cc-gpu-operator-001",
        "campaign": "cc-campaign-gpu-operator-001",
        "question": "SCI-091",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-coordinator",
        "mode": "formal",
    }
    payload.update(overrides)
    return payload


def _meeting(**overrides):
    payload = {
        **_scope(),
        "meetingRoundId": "meeting-demo-1",
        "meetingType": "hypothesis_review",
        "participants": ["agent-alpha", "agent-beta"],
        "discussionItemRefs": ["hypothesis_round:hround-demo-1"],
    }
    payload.update(overrides)
    return payload


def _closure(**overrides):
    payload = {
        "summary": "Candidate A is selected for a bounded offline validation.",
        "discussionTopics": ["novelty", "feasibility", "falsifiability"],
        "decisions": [
            {
                "decision": "select_candidate",
                "rationale": "Candidate A has the strongest bounded evidence plan.",
                "decidedBy": "agent-coordinator",
                "candidateRefs": ["cand-a"],
                "evidenceRefs": ["evidence:review-matrix-1"],
                "status": "adopted",
            }
        ],
        "closedBy": "agent-coordinator",
        "memorySummaries": {
            "agent-alpha": "Prefer bounded ablations before a full operator run.",
            "agent-beta": "Track compilation and runtime evidence separately.",
        },
        "memoryClass": "lesson",
        "reusePolicy": "reusable_same_scope",
        "evidenceStatus": "reported",
    }
    payload.update(overrides)
    return payload


def test_close_meeting_emits_digest_decision_and_private_memory_refs(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    created = meetings.create_meeting_round(team_id, _meeting())
    closed = meetings.close_meeting_round(team_id, "meeting-demo-1", _closure())

    assert created["status"] == "created"
    assert closed["meetingRound"]["status"] == "closed"
    assert closed["digest"]["summary"].startswith("Candidate A")
    assert closed["decisions"][0]["decision"] == "select_candidate"
    assert "personalMemoryCandidates" not in closed
    assert {item["agentId"] for item in closed["personalMemoryCandidateRefs"]} == {
        "agent-alpha",
        "agent-beta",
    }

    alpha = memories.list_personal_memory_candidates(team_id, agent_id="agent-alpha")
    beta = memories.list_personal_memory_candidates(team_id, agent_id="agent-beta")
    assert alpha["candidateCount"] == 1
    assert beta["candidateCount"] == 1
    assert alpha["storagePath"] != beta["storagePath"]
    assert alpha["candidates"][0]["summary"].startswith("Prefer bounded")
    assert beta["candidates"][0]["summary"].startswith("Track compilation")


def test_close_meeting_is_idempotent_but_rejects_conflicting_reuse(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    meetings.create_meeting_round(team_id, _meeting())
    closure = _closure()
    first = meetings.close_meeting_round(team_id, "meeting-demo-1", closure)
    repeated = meetings.close_meeting_round(team_id, "meeting-demo-1", closure)

    assert first["status"] == "created"
    assert repeated["status"] == "reused"
    with pytest.raises(meetings.ResearchMeetingRoundError, match="different closure content"):
        meetings.close_meeting_round(
            team_id,
            "meeting-demo-1",
            _closure(summary="A different meeting summary."),
        )

    with pytest.raises(meetings.ResearchMeetingRoundError, match="different content"):
        meetings.create_meeting_round(
            team_id,
            _meeting(participants=["agent-alpha"]),
        )


def test_close_meeting_fails_closed_without_digest_or_decision(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    meetings.create_meeting_round(team_id, _meeting())
    with pytest.raises(ContractValidationError, match="summary"):
        meetings.close_meeting_round(
            team_id, "meeting-demo-1", _closure(summary="")
        )
    with pytest.raises(ContractValidationError, match="decision record"):
        meetings.close_meeting_round(
            team_id, "meeting-demo-1", _closure(decisions=[])
        )
