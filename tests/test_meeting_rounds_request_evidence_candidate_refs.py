"""Closure-persistence gate for ``request_new_evidence`` candidateRefs.

Defect-8 decision-side closing piece: ``candidateRefs`` on a
``request_new_evidence`` decision name the hypothesis candidates the
collection serves — the claim belief gate's aggregation dimension. A decision
without them can only fail that gate closed at convergence, so the §15.4
closure gate must reject the closure before any digest/decision artifact is
persisted (fail-closed, recoverable: correct the payload and re-approve).
Companion to the chain's consumer-side structural rejection; this file owns
the persistence-side contract only and keeps legacy decision kinds unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.research.workflow.contracts import ContractValidationError
from core.web.services import (
    agent_directory_service,
    session_service,
    team_service,
)
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import personal_memory_candidates as memories
from tests._support.team_workflow.helpers import _use_tmp_project_root

_CREFS_TEAM_ROLES = (
    "challenge_cup_search",
    "challenge_cup_extractor",
    "challenge_cup_knowledge_manager",
    "challenge_cup_execution_steward",
    "challenge_cup_experiment_revision",
    "challenge_cup_evaluator",
)
_CREFS_PARTICIPANT_ROLES = (
    "challenge_cup_search",
    "challenge_cup_knowledge_manager",
    "challenge_cup_experiment_revision",
    "challenge_cup_evaluator",
)


def _crefs_team_with_room(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memories, "PROJECT_ROOT", tmp_path)
    agents: dict[str, str] = {}
    for role in _CREFS_TEAM_ROLES:
        agent = agent_directory_service.create_agent_instance(display_name=f"CREFS {role}")
        session_service.ensure_agent_direct_session(
            agent_id=agent["agentId"], title=f"CREFS {role}"
        )
        agents[role] = agent["agentId"]
    team_id = team_service.create_team(
        name="CREFS 决策落盘校验团队",
        members=[
            {"agentId": agents[role], "role": role} for role in _CREFS_TEAM_ROLES
        ],
    )["teamId"]
    return team_id, {role: agents[role] for role in _CREFS_PARTICIPANT_ROLES}


def _crefs_marker_runner(participant, prompt, context):
    """Round 1 carries the DEV fixture markers; follow-up critique rounds pass."""
    if "批评与修订" in str(prompt):
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}
    role = str(participant.get("teamRole") or "participant")
    if role == "challenge_cup_search":
        content = "AGREE: cand-a 的机制证据最完整，进入有界验证"
    else:
        content = (
            "DISAGREE: cand-b 的泛化证据不足\n"
            "RISK: 数据集偏差尚未评估\n"
            "ACTION: researcher | 补充 cand-b 的消融实验证据\n"
            "KNOWLEDGE: 预测编码层级最新综述"
        )
    return {"status": "completed", "raw_output": content, "summary": "ok"}


def _crefs_selection_payload(agent_ids, **overrides):
    payload = {
        "selectionId": "sel-crefs-1",
        "questionId": "SCI-096",
        "selectedCandidateIds": ["cand-a", "cand-b"],
        "decidedBy": agent_ids[0],
        "meetingRoundId": "meeting-crefs-1",
        "program": "XH-202619",
        "theme": "cc-neuro-001",
        "campaign": "cc-campaign-neuro-001",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "hypothesis_first",
        "agentId": agent_ids[0],
        "mode": "dev",
        "participants": list(agent_ids),
    }
    payload.update(overrides)
    return payload


def _crefs_open_awaiting_approval_meeting(tmp_path, monkeypatch):
    team_id, agents = _crefs_team_with_room(tmp_path, monkeypatch)
    agent_ids = list(agents.values())
    opened = meeting_runtime.open_hypothesis_review_meeting(
        team_id,
        _crefs_selection_payload(agent_ids),
        agent_runner=_crefs_marker_runner,
        background=False,
    )
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    meetings.begin_meeting_summary(team_id, meeting_round_id, actor=agent_ids[0])
    meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)
    return team_id, agents, meeting_round_id


def _crefs_request_evidence_decision(agent_ids, *, candidate_refs):
    return {
        "decision": "request_new_evidence",
        "rationale": "cand-b 的泛化证据不足，需要补充消融实验资料。",
        "decidedBy": agent_ids[0],
        "candidateRefs": list(candidate_refs),
        "evidenceRefs": ["evidence:review-matrix-1"],
        "searchEnvelope": {"keywords": ["predictive coding", "ablation"]},
        "status": "adopted",
    }


def _crefs_closure_payload(agent_ids, decisions, **overrides):
    payload = {
        "decisions": decisions,
        "closedBy": agent_ids[0],
        "memorySummaries": {agent_id: f"{agent_id} 的评审记忆" for agent_id in agent_ids},
        "memoryClass": "lesson",
        "reusePolicy": "reusable_same_scope",
        "evidenceStatus": "reported",
    }
    payload.update(overrides)
    return payload


def test_request_new_evidence_without_candidate_refs_rejected_before_persistence(
    tmp_path, monkeypatch
):
    team_id, agents, meeting_round_id = _crefs_open_awaiting_approval_meeting(
        tmp_path, monkeypatch
    )
    agent_ids = list(agents.values())

    with pytest.raises(ContractValidationError, match="candidateRef"):
        meetings.approve_meeting_closure(
            team_id,
            meeting_round_id,
            _crefs_closure_payload(
                agent_ids,
                [_crefs_request_evidence_decision(agent_ids, candidate_refs=[])],
            ),
        )

    # Fail-closed persistence: the rejected closure left no digest, no
    # decision record, and the round still waits for a corrected approval.
    assert meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"][
        "status"
    ] == "awaiting_approval"
    storage_dir = Path(meetings._rounds_path(team_id)).parent
    for store in ("decision_records.jsonl", "meeting_digests.jsonl"):
        path = storage_dir / store
        assert not path.exists() or not path.read_text(encoding="utf-8").strip(), store

    # Recovery stays on the existing idempotent closure flow: the corrected
    # payload (decision names the served candidates) closes normally and is
    # the first — and only — persisted artifact set.
    approved = meetings.approve_meeting_closure(
        team_id,
        meeting_round_id,
        _crefs_closure_payload(
            agent_ids,
            [
                _crefs_request_evidence_decision(
                    agent_ids, candidate_refs=["cand-b"]
                )
            ],
        ),
    )
    assert approved["status"] == "created"
    assert approved["decisions"][0]["candidateRefs"] == ["cand-b"]
    decision_records = [
        json.loads(line)
        for line in (storage_dir / "decision_records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(decision_records) == 1


def test_other_decision_kinds_still_close_without_candidate_refs(
    tmp_path, monkeypatch
):
    """The new check is scoped to ``request_new_evidence`` and must not move
    the legacy contract for other decision kinds."""
    team_id, agents, meeting_round_id = _crefs_open_awaiting_approval_meeting(
        tmp_path, monkeypatch
    )
    agent_ids = list(agents.values())

    approved = meetings.approve_meeting_closure(
        team_id,
        meeting_round_id,
        _crefs_closure_payload(
            agent_ids,
            [
                {
                    "decision": "select_candidate",
                    "rationale": "cand-a 证据最完整，进入有界验证。",
                    "decidedBy": agent_ids[0],
                    "candidateRefs": [],
                    "evidenceRefs": ["evidence:review-matrix-1"],
                    "status": "adopted",
                }
            ],
        ),
    )

    assert approved["status"] == "created"
    assert approved["decisions"][0]["decision"] == "select_candidate"
    assert approved["decisions"][0]["candidateRefs"] == []
