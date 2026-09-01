"""D04 meeting closure, digest, decision and private-memory handoff tests."""

from __future__ import annotations

import pytest

from core.research.workflow.contracts import ContractValidationError, MeetingRound
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


def test_grounded_candidate_protocol_preserves_refs_check_and_authority(
    tmp_path, monkeypatch
):
    team_id = _team(tmp_path, monkeypatch)
    created = meetings.create_meeting_round(
        team_id,
        _meeting(
            meetingType="hypothesis_candidate_generation",
            candidateAuthority="formal_grounded_candidate",
            allowedEvidenceRefs=["evidence:accepted-1", "evidence:boundary-1"],
            exploratoryDraftRefs=["exploratory_draft:r0-a"],
            knowledgePackageRefs=["knowledge_package:pkg-1"],
            revisionOrdinal=1,
        ),
    )["meetingRound"]

    markers = meetings.extract_discussion_markers(
        [
            {
                "status": "completed",
                "speakerTitle": "研究员",
                "content": (
                    "CANDIDATE: r0-a | 腺苷积累损害记忆巩固 | 受体机制明确 "
                    "| REFS: evidence:accepted-1; evidence:boundary-1 "
                    "| CHECK: 阻断 A1 受体应恢复记忆表现"
                ),
            }
        ]
    )

    assert created["candidateAuthority"] == "formal_grounded_candidate"
    assert created["allowedEvidenceRefs"] == [
        "evidence:accepted-1",
        "evidence:boundary-1",
    ]
    assert created["revisionOrdinal"] == 1
    assert markers["proposedCandidates"] == [
        {
            "candidateId": "r0-a",
            "statement": "腺苷积累损害记忆巩固",
            "rationale": "受体机制明确",
            "proposedBy": "研究员",
            "lineageRefs": ["evidence:accepted-1", "evidence:boundary-1"],
            "testablePrediction": "阻断 A1 受体应恢复记忆表现",
        }
    ]
def test_meeting_round_persists_participant_contract_snapshot(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    snapshot = [
        {
            "roleId": "challenge_cup_search",
            "agentId": "agent-search",
            "observedRole": "source_finder",
        },
        {
            "roleId": "challenge_cup_knowledge_manager",
            "agentId": "agent-knowledge",
            "observedRole": "source_relation_mapper",
        },
        {
            "roleId": "challenge_cup_experiment_revision",
            "agentId": "agent-revision",
            "observedRole": "experiment_planner",
        },
        {
            "roleId": "challenge_cup_evaluator",
            "agentId": "agent-evaluator",
            "observedRole": "experiment_ledger",
        },
    ]
    created = meetings.create_meeting_round(
        team_id,
        _meeting(
            participants=[item["agentId"] for item in snapshot],
            participantRoleIds=[item["roleId"] for item in snapshot],
            teamRoleContractVersion=2,
            participantPolicyVersion=2,
            roleContractFingerprint="a" * 64,
            participantRoleSnapshot=snapshot,
            resolutionHash="b" * 64,
        ),
    )

    meeting_round = created["meetingRound"]
    parsed = MeetingRound.from_dict(meeting_round)
    assert meeting_round["teamRoleContractVersion"] == 2
    assert meeting_round["participantPolicyVersion"] == 2
    assert meeting_round["roleContractFingerprint"] == "a" * 64
    assert meeting_round["resolutionHash"] == "b" * 64
    assert parsed.participantRoleIds == tuple(item["roleId"] for item in snapshot)
    assert parsed.participantRoleSnapshot == tuple(snapshot)


def test_plan_review_accepts_legacy_participant_role_ids_without_challenge_contract(
    tmp_path, monkeypatch
):
    team_id = _team(tmp_path, monkeypatch)

    created = meetings.create_meeting_round(
        team_id,
        _meeting(
            meetingType="plan_review",
            participantRoleIds=["plan_author", "plan_reviewer"],
        ),
    )

    meeting_round = created["meetingRound"]
    assert meeting_round["participantRoleIds"] == ["plan_author", "plan_reviewer"]
    assert meeting_round["participantRoleSnapshot"] == []
    assert meeting_round["teamRoleContractVersion"] == 0


@pytest.mark.parametrize(
    "meeting_type",
    ["hypothesis_review", "hypothesis_candidate_generation"],
)
def test_meeting_round_rejects_participant_role_ids_without_complete_snapshot(
    tmp_path, monkeypatch, meeting_type
):
    team_id = _team(tmp_path, monkeypatch)

    with pytest.raises(ContractValidationError, match="teamRoleContractVersion"):
        meetings.create_meeting_round(
            team_id,
            _meeting(
                meetingType=meeting_type,
                participantRoleIds=["challenge_cup_search", "challenge_cup_evaluator"],
            ),
        )
    with pytest.raises(ContractValidationError, match="participantRoleIds"):
        meetings.create_meeting_round(
            team_id,
            _meeting(
                participants=["agent-search"],
                teamRoleContractVersion=2,
                participantPolicyVersion=2,
                roleContractFingerprint="a" * 64,
                participantRoleSnapshot=[
                    {"roleId": "challenge_cup_search", "agentId": "agent-search"}
                ],
                resolutionHash="b" * 64,
            ),
        )


def test_meeting_round_idempotency_seed_includes_participant_resolution_hash(
    tmp_path, monkeypatch
):
    team_id = _team(tmp_path, monkeypatch)
    snapshot = [
        {"roleId": "challenge_cup_search", "agentId": "agent-search"},
    ]
    common = _meeting(
        meetingRoundId="",
        startedAt="2026-08-23T00:00:00Z",
        participants=["agent-search"],
        participantRoleIds=["challenge_cup_search"],
        teamRoleContractVersion=2,
        participantPolicyVersion=2,
        roleContractFingerprint="a" * 64,
        participantRoleSnapshot=snapshot,
        resolutionHash="b" * 64,
    )
    first = meetings.create_meeting_round(team_id, common)
    second = meetings.create_meeting_round(
        team_id, {**common, "resolutionHash": "c" * 64}
    )

    assert first["meetingRound"]["meetingRoundId"] != second["meetingRound"]["meetingRoundId"]


def test_v2_digest_keeps_proposed_candidates():
    proposals = [
        {
            "candidateId": "cand-a",
            "statement": "候选假说 A",
            "rationale": "机制理由 A",
            "proposedBy": "agent-alpha",
        }
    ]
    digest = meetings._build_digest_v2(
        {
            "meetingRoundId": "meeting-generation-1",
            "scopeHash": "scope-generation-1",
            "participants": ["agent-alpha"],
        },
        {"summary": "候选生成完成", "proposedCandidates": proposals},
        {"closedBy": "agent-alpha"},
        "2026-08-21T00:00:00+00:00",
    )

    assert digest["proposedCandidates"] == proposals


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


# ---------------------------------------------------------------------------
# V2 operator stop: a stalled discussion with completed messages must have a
# real terminal path (stopped execution, transcript preserved); an empty
# attempt keeps the superseded-attempt recovery semantics.
# ---------------------------------------------------------------------------


def _room_detail(round_id: str, messages: list[dict]) -> dict:
    return {
        "roomId": "room-stop-1",
        "rounds": [
            {
                "roundId": round_id,
                "status": "completed",
                "messages": messages,
            }
        ],
    }


def _bind_stop_room(monkeypatch, round_id: str, messages: list[dict]) -> None:
    from core.web.services import chat_room_service

    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_detail",
        lambda room_id: _room_detail(round_id, messages)
        if room_id == "room-stop-1"
        else None,
    )


def test_stop_discussion_meeting_stops_attempt_and_keeps_completed_messages(
    tmp_path, monkeypatch
):
    team_id = _team(tmp_path, monkeypatch)
    meetings.create_meeting_round(team_id, _meeting(meetingRoundId="meeting-stop-msg"))
    meetings.bind_meeting_chat_room_round(
        team_id, "meeting-stop-msg", "room-stop-1", "round-stop-1"
    )
    _bind_stop_room(
        monkeypatch,
        "round-stop-1",
        [
            {
                "status": "completed",
                "speakerTitle": "研究员",
                "content": "DISAGREE: hyp-b 的泛化证据不足",
            }
        ],
    )

    stopped = meetings.stop_discussion_meeting(
        team_id, "meeting-stop-msg", actor="operator:v2-stop-discussion"
    )

    assert stopped["status"] == "stopped"
    record = stopped["meetingRound"]
    assert record["status"] == "closed"
    assert record["executionStatus"] == "stopped"
    assert record["recoveryReason"] == "operator_stop_discussion"
    assert record["summaryDraftError"]["code"] == "operator_stop_discussion"
    assert record["summaryDraftError"]["remediationLabel"] == "重新发起讨论"
    assert record["closedBy"] == "operator:v2-stop-discussion"
    # The transcript stays citable: no digest or decision was promoted, but
    # the completed messages survive the stop.
    assert not record.get("digestId")
    assert len(meetings.completed_meeting_source_messages(record)) == 1

    reused = meetings.stop_discussion_meeting(team_id, "meeting-stop-msg")
    assert reused["status"] == "reused"
    assert reused["meetingRound"]["executionStatus"] == "stopped"


def test_stop_discussion_meeting_supersedes_empty_attempt_with_existing_semantics(
    tmp_path, monkeypatch
):
    team_id = _team(tmp_path, monkeypatch)
    meetings.create_meeting_round(team_id, _meeting(meetingRoundId="meeting-stop-empty"))
    meetings.bind_meeting_chat_room_round(
        team_id, "meeting-stop-empty", "room-stop-1", "round-stop-empty"
    )
    _bind_stop_room(monkeypatch, "round-stop-empty", [])

    stopped = meetings.stop_discussion_meeting(team_id, "meeting-stop-empty")
    assert stopped["status"] == "superseded"
    record = stopped["meetingRound"]
    assert record["status"] == "closed"
    assert record["recoveryReason"] == "discussion_has_no_completed_messages"
    assert (
        record["summaryDraftError"]["code"] == "discussion_has_no_completed_messages"
    )
    assert record["summaryDraftError"]["remediationLabel"] == "重新发起讨论"
    assert record["closedBy"] == "operator:v2-stop-discussion"

    reused = meetings.stop_discussion_meeting(team_id, "meeting-stop-empty")
    assert reused["status"] == "reused"


def test_stop_discussion_meeting_refuses_still_running_rounds(tmp_path, monkeypatch):
    team_id = _team(tmp_path, monkeypatch)
    meetings.create_meeting_round(team_id, _meeting(meetingRoundId="meeting-stop-live"))
    monkeypatch.setattr(
        meetings, "running_bound_round_ids", lambda _meeting: ["round-live"]
    )

    with pytest.raises(
        meetings.ResearchMeetingRoundError, match="still running and cannot be stopped"
    ):
        meetings.stop_discussion_meeting(team_id, "meeting-stop-live")
    live = meetings.get_meeting_round(team_id, "meeting-stop-live")["meetingRound"]
    assert live["status"] == "open"
