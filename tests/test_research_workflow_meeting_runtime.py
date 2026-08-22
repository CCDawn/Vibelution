"""HF-2 hypothesis-first meeting runtime tests.

Covers the batch contract: fixture selection -> ``open_hypothesis_review_meeting``
-> a bound chat-room discussion round (two-way link between room ``roundId`` and
``meetingRoundId``); the four-state status machine rejecting illegal
transitions; closure producing the full artifact set (digest v2, decision
records, per-participant memory candidates) with message traceability;
idempotent re-closure; requirements §15.4 completion conditions enforced
fail-closed; the discussion driver termination trio (maxMessages, convergence
signal, per-round check); and the regression that non-hypothesis-first stage
coordination stays ``manual_only``.

All discussion content comes from fake runners (DEV fixtures); no real model
or network is involved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.research.competition.resources import load_science_question_catalog
from core.research.workflow.contracts import (
    ContractValidationError,
    MeetingDigest,
    MeetingRound,
    scope_hash_for,
)
from core.research.workflow.contracts.meeting_round import (
    ensure_meeting_status_transition,
)
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    session_service,
    team_service,
    team_workflow_orchestration_service,
)
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow import personal_memory_candidates as memories

from tests._support.team_workflow.helpers import (
    _use_fake_local_research_config,
    _use_tmp_project_root,
)

_TEAM_ROLES = (
    "challenge_cup_search",
    "challenge_cup_extractor",
    "challenge_cup_knowledge_manager",
    "challenge_cup_execution_steward",
    "challenge_cup_experiment_revision",
    "challenge_cup_evaluator",
)
_ROLES = (
    "challenge_cup_search",
    "challenge_cup_knowledge_manager",
    "challenge_cup_experiment_revision",
    "challenge_cup_evaluator",
)


def _team_with_room(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memories, "PROJECT_ROOT", tmp_path)
    agents: dict[str, str] = {}
    for role in _TEAM_ROLES:
        agent = agent_directory_service.create_agent_instance(display_name=f"HF2 {role}")
        session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title=f"HF2 {role}")
        agents[role] = agent["agentId"]
    team_id = team_service.create_team(
        name="HF-2 假说评审团队",
        members=[{"agentId": agents[role], "role": role} for role in _TEAM_ROLES],
    )["teamId"]
    return team_id, {role: agents[role] for role in _ROLES}


def _selection_payload(agent_ids, **overrides):
    payload = {
        "selectionId": "sel-hf2-1",
        "questionId": "SCI-096",
        "selectedCandidateIds": ["cand-a", "cand-b"],
        "decidedBy": agent_ids[0],
        "meetingRoundId": "meeting-hf2-1",
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


def _marker_runner(participant, prompt, context):
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


def _content_runner(participant, prompt, context):
    role = str(participant.get("teamRole") or "participant")
    return {
        "status": "completed",
        "raw_output": f"AGREE: {role} 每轮都补充一条新证据",
        "summary": "ok",
    }


def _failed_runner(participant, prompt, context):
    return {
        "status": "failed",
        "errorType": "protocol_error",
        "summary": "speaker failed before producing discussion evidence",
    }


def _open_meeting(tmp_path, monkeypatch, *, runner=None, background=False, **overrides):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    opened = meeting_runtime.open_hypothesis_review_meeting(
        team_id,
        _selection_payload(list(agents.values()), **overrides),
        agent_runner=runner or _marker_runner,
        background=background,
    )
    return team_id, agents, opened


def test_candidate_generation_prompt_includes_canonical_question_context(
    tmp_path, monkeypatch
):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    prompts: list[str] = []
    speaker_agent_ids: list[str] = []

    def capture_runner(participant, prompt, context):
        prompts.append(str(prompt))
        speaker_agent_ids.append(str(participant.get("agentId") or ""))
        return {
            "status": "completed",
            "raw_output": "CANDIDATE: cand-a | 可证伪机制 | 来自赛题正文",
            "summary": "ok",
        }

    catalog_question = next(
        item
        for item in load_science_question_catalog()["questions"]
        if item["id"] == "SCI-001"
    )
    agent_ids = list(agents.values())
    meeting_runtime.open_candidate_generation_meeting(
        team_id,
        {
            "questionId": "SCI-001",
            "meetingRoundId": "meeting-hf2-generation-context",
            "program": "XH-202619",
            "theme": "cc-catalog-001",
            "campaign": "cc-campaign-001",
            "question": "SCI-001",
            "branch": "main",
            "workflow": "hypothesis_first",
            "agentId": agent_ids[0],
            "mode": "dev",
            "participants": agent_ids,
        },
        agent_runner=capture_runner,
        background=False,
    )

    assert prompts
    assert all(str(catalog_question["question_en"]) in prompt for prompt in prompts)
    assert all(str(catalog_question["domain"]) in prompt for prompt in prompts)
    assert all("每位参与者必须直接提出至少一个可证伪候选" in prompt for prompt in prompts)
    assert all("不得等待其他角色代为提出" in prompt for prompt in prompts)
    assert speaker_agent_ids == list(agents.values())


def test_review_prompt_includes_selected_candidate_content(tmp_path, monkeypatch):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    prompts: list[str] = []

    def capture_runner(participant, prompt, context):
        prompts.append(str(prompt))
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}

    agent_ids = list(agents.values())
    meeting_runtime.open_hypothesis_review_meeting(
        team_id,
        _selection_payload(
            agent_ids,
            selectedCandidateIds=["cand-a"],
        ),
        agent_runner=capture_runner,
        background=False,
        candidate_contexts=[
            {
                "candidateId": "cand-a",
                "claim": "素数是整数乘法的原子单元",
                "rationale": "算术基本定理保证唯一分解",
            }
        ],
    )

    assert prompts
    assert all("cand-a" in prompt for prompt in prompts)
    assert all("素数是整数乘法的原子单元" in prompt for prompt in prompts)
    assert all("算术基本定理保证唯一分解" in prompt for prompt in prompts)


def test_review_prompt_teaches_evidence_request_marker(tmp_path, monkeypatch):
    """Reviews must know the EVIDENCE_REQUEST format: the closure digest only
    extracts requests from that marker, and an untaught format wedges the
    first source-collection round (no envelope -> collectionReady stays
    false forever)."""
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    prompts: list[str] = []

    def capture_runner(participant, prompt, context):
        prompts.append(str(prompt))
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}

    agent_ids = list(agents.values())
    meeting_runtime.open_hypothesis_review_meeting(
        team_id,
        _selection_payload(agent_ids),
        agent_runner=capture_runner,
        background=False,
    )

    assert prompts
    assert all("EVIDENCE_REQUEST" in prompt for prompt in prompts)
    assert all('"searchEnvelope"' in prompt for prompt in prompts)
    assert all("AGREE:" in prompt for prompt in prompts)
    assert all("DISAGREE:" in prompt for prompt in prompts)


def test_review_prompt_keeps_all_candidate_lines_beyond_generic_topic_cap(
    tmp_path, monkeypatch
):
    """The review topic embeds one line per candidate and must not hit the
    generic chat-room six-line topic cap (observed live: only 3 of 9
    selected candidates reached the agents)."""
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    prompts: list[str] = []

    def capture_runner(participant, prompt, context):
        prompts.append(str(prompt))
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}

    candidate_ids = [f"cand-{index}" for index in range(9)]
    candidate_contexts = [
        {
            "candidateId": candidate_id,
            "claim": f"{candidate_id} 的可证伪陈述",
            "rationale": f"{candidate_id} 的机制理由",
        }
        for candidate_id in candidate_ids
    ]
    agent_ids = list(agents.values())
    meeting_runtime.open_hypothesis_review_meeting(
        team_id,
        _selection_payload(agent_ids, selectedCandidateIds=candidate_ids),
        agent_runner=capture_runner,
        background=False,
        candidate_contexts=candidate_contexts,
    )

    assert prompts
    for candidate_id in candidate_ids:
        assert all(f"{candidate_id} 的可证伪陈述" in prompt for prompt in prompts), (
            f"{candidate_id} statement was truncated out of the meeting topic"
        )


def _closure_payload(agent_ids, **overrides):
    payload = {
        "decisions": [
            {
                "decision": "select_candidate",
                "rationale": "cand-a 证据最完整，进入有界验证。",
                "decidedBy": agent_ids[0],
                "candidateRefs": ["cand-a"],
                "evidenceRefs": ["evidence:review-matrix-1"],
                "status": "adopted",
            }
        ],
        "closedBy": agent_ids[0],
        "memorySummaries": {agent_id: f"{agent_id} 的评审记忆" for agent_id in agent_ids},
        "memoryClass": "lesson",
        "reusePolicy": "reusable_same_scope",
        "evidenceStatus": "reported",
    }
    payload.update(overrides)
    return payload


def _decision_without_evidence(agent_ids):
    return [
        {
            "decision": "select_candidate",
            "rationale": "仅凭直觉选择 cand-a。",
            "decidedBy": agent_ids[0],
            "candidateRefs": ["cand-a"],
            "evidenceRefs": [],
            "status": "adopted",
        }
    ]


def test_open_hypothesis_review_meeting_binds_room_round_both_ways(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)

    assert opened["status"] == "opened"
    meeting_round = opened["meetingRound"]
    assert meeting_round["meetingRoundId"] == "meeting-hf2-1"
    assert meeting_round["schemaVersion"] == meetings.SCHEMA_VERSION
    assert meeting_round["meetingType"] == "hypothesis_review"
    assert meeting_round["stage"] == "hypothesis"
    assert meeting_round["roundType"] == "decision_gate"
    assert meeting_round["rounds"] == 3
    assert meeting_round["status"] == "open"
    assert meeting_round["participants"] == list(agents.values())
    assert meeting_round["participantRoleIds"] == list(_ROLES)
    assert meeting_round["inputArtifactRefs"] == ["hypothesis_selection:sel-hf2-1"]
    assert meeting_round["discussionItemRefs"] == [
        "hypothesis_candidate:cand-a",
        "hypothesis_candidate:cand-b",
    ]
    assert meeting_round["agenda"] and meeting_round["agendaQuestions"] and meeting_round["agendaRules"]

    room_id = opened["roomId"]
    round_id = opened["roundId"]
    assert meeting_round["linkedChatRoomId"] == room_id
    assert meeting_round["chatRoomRoundIds"] == [round_id]

    room_detail = chat_room_service.get_chat_room_detail(room_id)
    bound_round = next(item for item in room_detail["rounds"] if item["roundId"] == round_id)
    assert bound_round["config"]["meetingRoundId"] == "meeting-hf2-1"
    assert bound_round["config"]["selectionId"] == "sel-hf2-1"
    assert bound_round["config"]["scopeHash"] == meeting_round["scopeHash"]
    assert bound_round["config"]["source"] == meeting_runtime.MEETING_SOURCE
    assert bound_round["config"]["discussionRoundIndex"] == 1
    assert bound_round["config"]["participantAgentIds"] == list(agents.values())
    assert bound_round["status"] == "completed"
    assert len(bound_round["messages"]) == len(_ROLES)

    reopened = meeting_runtime.open_hypothesis_review_meeting(
        team_id,
        _selection_payload(list(agents.values())),
        agent_runner=_marker_runner,
        background=False,
    )
    assert reopened["status"] == "reused"
    assert reopened["meetingRound"]["meetingRoundId"] == "meeting-hf2-1"
    assert reopened["roundId"] == round_id
    assert reopened["chatRoomRoundIds"] == [round_id]


def test_open_hypothesis_review_meeting_validates_selection_and_participants(tmp_path, monkeypatch):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    agent_ids = list(agents.values())

    with pytest.raises(ContractValidationError, match="selectionId"):
        meeting_runtime.open_hypothesis_review_meeting(
            team_id, _selection_payload(agent_ids, selectionId=""), background=False
        )
    with pytest.raises(ContractValidationError, match="selectedCandidateIds"):
        meeting_runtime.open_hypothesis_review_meeting(
            team_id, _selection_payload(agent_ids, selectedCandidateIds=[]), background=False
        )
    with pytest.raises(ContractValidationError, match="server-resolved participant roster"):
        meeting_runtime.open_hypothesis_review_meeting(
            team_id, _selection_payload(agent_ids, participants=[]), background=False
        )
    with pytest.raises(ContractValidationError, match="server-resolved participant roster"):
        meeting_runtime.open_hypothesis_review_meeting(
            team_id,
            _selection_payload(agent_ids, participants=[agent_ids[0], "agent-outsider"]),
            background=False,
        )
    room_agent_ids = [
        participant["agentId"]
        for participant in chat_room_service.get_chat_room_detail(
            team_service.get_team(team_id)["linkedChatRoomId"]
        )["participants"]
    ]
    assert len(room_agent_ids) == 6
    with pytest.raises(ContractValidationError, match="server-resolved participant roster"):
        meeting_runtime.open_hypothesis_review_meeting(
            team_id,
            _selection_payload(agent_ids, participants=room_agent_ids),
            background=False,
        )
    with pytest.raises(ContractValidationError, match="does not match the meeting scope"):
        meeting_runtime.open_hypothesis_review_meeting(
            team_id, _selection_payload(agent_ids, questionId="SCI-999"), background=False
        )


def test_direct_meeting_runtime_rejects_partial_or_forged_participant_contract(
    tmp_path, monkeypatch
):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    agent_ids = list(agents.values())

    with pytest.raises(ContractValidationError, match="complete participant contract"):
        meeting_runtime.open_hypothesis_review_meeting(
            team_id,
            _selection_payload(
                agent_ids,
                participantRoleIds=list(_ROLES),
            ),
            background=False,
        )

    resolved = meeting_runtime.resolve_hypothesis_meeting_participants(
        team_id,
        team_service.get_team(team_id)["linkedChatRoomId"],
        "hypothesis_review",
    )
    forged_contracts = {
        "participantRoleIds": {
            **resolved,
            "participantRoleIds": list(reversed(resolved["participantRoleIds"])),
        },
        "teamRoleContractVersion": {
            **resolved,
            "teamRoleContractVersion": resolved["teamRoleContractVersion"] + 1,
        },
        "participantPolicyVersion": {
            **resolved,
            "participantPolicyVersion": resolved["participantPolicyVersion"] + 1,
        },
        "roleContractFingerprint": {
            **resolved,
            "roleContractFingerprint": "e" * 64,
        },
        "participantRoleSnapshot": {
            **resolved,
            "participantRoleSnapshot": [
                *resolved["participantRoleSnapshot"][:-1],
                {
                    **resolved["participantRoleSnapshot"][-1],
                    "agentId": resolved["participants"][0],
                },
            ],
        },
        "resolutionHash": {**resolved, "resolutionHash": "f" * 64},
    }
    for field, forged in forged_contracts.items():
        with pytest.raises(ContractValidationError, match=field):
            meeting_runtime.open_hypothesis_review_meeting(
                team_id,
                _selection_payload(agent_ids, **forged),
                background=False,
            )


def test_four_state_machine_rejects_illegal_transitions(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    agent_ids = list(agents.values())

    with pytest.raises(ContractValidationError, match="not allowed"):
        meetings.submit_meeting_digest_draft(team_id, meeting_round_id, {"summary": "x"})
    with pytest.raises(ContractValidationError, match="not allowed"):
        meetings.approve_meeting_closure(team_id, meeting_round_id, _closure_payload(agent_ids))
    with pytest.raises(ContractValidationError, match="not allowed"):
        meetings.reject_meeting_digest_draft(team_id, meeting_round_id)

    begun = meetings.begin_meeting_summary(team_id, meeting_round_id, actor=agent_ids[0])
    assert begun["status"] == "summarizing"
    with pytest.raises(ContractValidationError, match="not allowed"):
        meetings.begin_meeting_summary(team_id, meeting_round_id)
    with pytest.raises(ContractValidationError, match="not allowed"):
        meetings.approve_meeting_closure(team_id, meeting_round_id, _closure_payload(agent_ids))
    with pytest.raises(ContractValidationError, match="missing required sections"):
        meetings.submit_meeting_digest_draft(team_id, meeting_round_id, {"summary": "x"})
    with pytest.raises(ContractValidationError, match="sourceMessageRefs"):
        meetings.submit_meeting_digest_draft(
            team_id,
            meeting_round_id,
            {
                "summary": "x",
                "agreements": [],
                "disagreements": [],
                "actionItems": [],
                "risks": [],
                "knowledgeCandidates": [],
                "sourceMessageRefs": [],
            },
        )

    drafted = meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)
    assert drafted["status"] == "awaiting_approval"
    with pytest.raises(ContractValidationError, match="not allowed"):
        meetings.begin_meeting_summary(team_id, meeting_round_id)

    rejected = meetings.reject_meeting_digest_draft(
        team_id, meeting_round_id, actor=agent_ids[0], reason="补充分歧细节"
    )
    assert rejected["status"] == "summarizing"
    assert "digestDraft" not in rejected["meetingRound"]

    meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)
    approved = meetings.approve_meeting_closure(team_id, meeting_round_id, _closure_payload(agent_ids))
    assert approved["meetingRound"]["status"] == "closed"
    with pytest.raises(ContractValidationError, match="not allowed"):
        meetings.begin_meeting_summary(team_id, meeting_round_id)
    with pytest.raises(ContractValidationError, match="not allowed"):
        meetings.reject_meeting_digest_draft(team_id, meeting_round_id)


def test_begin_summary_blocked_while_discussion_round_running(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch, background=True)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]

    # _use_tmp_project_root installs _NoopBackgroundExecutor: background rounds
    # are submitted but never executed, so this round stays running.
    with pytest.raises(meetings.ResearchMeetingRoundError, match="still running"):
        meetings.begin_meeting_summary(team_id, meeting_round_id)
    begun = meetings.begin_meeting_summary(team_id, meeting_round_id, human_triggered=True)
    assert begun["status"] == "summarizing"
    assert begun["meetingRound"]["summaryHumanTriggered"] is True


def test_close_flow_produces_full_artifacts_with_message_traceability(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    agent_ids = list(agents.values())

    # The legacy direct-close path refuses room-bound meetings.
    with pytest.raises(meetings.ResearchMeetingRoundError, match="room-bound"):
        meetings.close_meeting_round(team_id, meeting_round_id, _closure_payload(agent_ids))

    meetings.begin_meeting_summary(team_id, meeting_round_id, actor=agent_ids[0])
    drafted = meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)
    draft = drafted["digestDraft"]
    assert drafted["meetingRound"]["status"] == "awaiting_approval"
    assert draft["summary"]
    assert draft["agendaSummary"]
    assert any("cand-b" in item["issue"] for item in draft["disagreements"])
    assert any("数据集偏差" in risk for risk in draft["risks"])
    assert draft["actionItems"][0]["ownerRoleId"] == "researcher"
    assert "补充 cand-b 的消融实验证据" in draft["actionItems"][0]["action"]
    assert any("预测编码" in item for item in draft["knowledgeCandidates"])
    assert len(draft["sourceMessageRefs"]) == len(_ROLES)
    assert len(draft["contentHash"]) == 64

    approved = meetings.approve_meeting_closure(team_id, meeting_round_id, _closure_payload(agent_ids))
    assert approved["closed"] is True
    assert approved["status"] == "created"

    digest = approved["digest"]
    assert digest["schemaVersion"] == meetings.SCHEMA_VERSION
    assert digest["meetingRoundId"] == meeting_round_id
    assert len(digest["contentHash"]) == 64
    assert digest["decisionRefs"] == [item["decisionId"] for item in approved["decisions"]]
    assert any("cand-b" in item["issue"] for item in digest["disagreements"])
    assert any("数据集偏差" in risk for risk in digest["risks"])
    assert digest["participantAgentIds"] == agent_ids

    source_messages = meetings.meeting_source_messages(approved["meetingRound"])
    known_message_ids = {str(message["messageId"]) for message in source_messages}
    assert known_message_ids
    for ref in digest["sourceMessageRefs"]:
        room_id, round_id, message_id = ref.split("/")
        assert room_id == opened["roomId"]
        assert round_id == opened["roundId"]
        assert message_id in known_message_ids

    decision = approved["decisions"][0]
    assert decision["decision"] == "select_candidate"
    assert decision["evidenceRefs"] == ["evidence:review-matrix-1"]
    assert decision["meetingRoundId"] == meeting_round_id

    assert {item["agentId"] for item in approved["personalMemoryCandidateRefs"]} == set(agent_ids)
    for agent_id in agent_ids:
        listed = memories.list_personal_memory_candidates(team_id, agent_id=agent_id)
        assert listed["candidateCount"] == 1

    closed_round = approved["meetingRound"]
    assert closed_round["status"] == "closed"
    assert closed_round["closedBy"] == agent_ids[0]
    assert closed_round["digestId"] == digest["digestId"]
    assert closed_round["decisionRefs"] == digest["decisionRefs"]
    assert closed_round["closureHash"]


def test_approve_meeting_closure_is_idempotent_and_rejects_conflicts(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    agent_ids = list(agents.values())
    meetings.begin_meeting_summary(team_id, meeting_round_id)
    meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)

    payload = _closure_payload(agent_ids)
    first = meetings.approve_meeting_closure(team_id, meeting_round_id, payload)
    repeated = meetings.approve_meeting_closure(team_id, meeting_round_id, payload)

    assert first["status"] == "created"
    assert repeated["status"] == "reused"
    assert repeated["digest"]["digestId"] == first["digest"]["digestId"]
    assert [item["decisionId"] for item in repeated["decisions"]] == [
        item["decisionId"] for item in first["decisions"]
    ]

    decisions_path = Path(first["storagePath"]).parent / "decision_records.jsonl"
    decision_records = [
        json.loads(line)
        for line in decisions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(decision_records) == 1
    digests_path = Path(first["storagePath"]).parent / "meeting_digests.jsonl"
    digest_records = [
        json.loads(line)
        for line in digests_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(digest_records) == 1
    for agent_id in agent_ids:
        listed = memories.list_personal_memory_candidates(team_id, agent_id=agent_id)
        assert listed["candidateCount"] == 1

    with pytest.raises(meetings.ResearchMeetingRoundError, match="different closure content"):
        meetings.approve_meeting_closure(
            team_id,
            meeting_round_id,
            _closure_payload(agent_ids, closedBy=agent_ids[1]),
        )


def test_closure_gate_enforces_section_15_4_fail_closed(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    agent_ids = list(agents.values())
    meetings.begin_meeting_summary(team_id, meeting_round_id)
    meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)

    with pytest.raises(ContractValidationError, match="evidence ref"):
        meetings.approve_meeting_closure(
            team_id,
            meeting_round_id,
            _closure_payload(agent_ids, decisions=_decision_without_evidence(agent_ids)),
        )
    with pytest.raises(ContractValidationError, match="disagreement"):
        meetings.approve_meeting_closure(
            team_id,
            meeting_round_id,
            _closure_payload(agent_ids, disagreements=[]),
        )
    with pytest.raises(ContractValidationError, match="unresolved risk"):
        meetings.approve_meeting_closure(
            team_id,
            meeting_round_id,
            _closure_payload(agent_ids, risks=[]),
        )
    with pytest.raises(ContractValidationError, match="role owner"):
        meetings.approve_meeting_closure(
            team_id,
            meeting_round_id,
            _closure_payload(
                agent_ids,
                actionItems=[{"ownerRoleId": "", "action": "补充 cand-b 的消融实验证据"}],
            ),
        )
    with pytest.raises(ContractValidationError, match="existing room messages"):
        meetings.approve_meeting_closure(
            team_id,
            meeting_round_id,
            _closure_payload(agent_ids, sourceMessageRefs=["room-x/round-y/message-bogus"]),
        )
    with pytest.raises(ContractValidationError, match="pending"):
        meetings.approve_meeting_closure(
            team_id,
            meeting_round_id,
            _closure_payload(
                agent_ids,
                decisions=[
                    {
                        "decision": "select_candidate",
                        "rationale": "cand-a 进入有界验证，但需人类最终批准。",
                        "decidedBy": agent_ids[0],
                        "candidateRefs": ["cand-a"],
                        "evidenceRefs": ["evidence:review-matrix-1"],
                        "status": "adopted",
                        "requiresHumanApproval": True,
                    }
                ],
            ),
        )

    # Every failure left the meeting in awaiting_approval; a valid approval closes it.
    assert (
        meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"]["status"]
        == "awaiting_approval"
    )
    approved = meetings.approve_meeting_closure(team_id, meeting_round_id, _closure_payload(agent_ids))
    assert approved["closed"] is True


def test_discussion_driver_stops_on_convergence_signal(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]

    result = meeting_runtime.run_meeting_discussion(
        team_id, meeting_round_id, agent_runner=_marker_runner
    )

    assert result["stopReason"] == "converged"
    assert result["roundsRun"] == 2
    assert result["roundBudget"] == 3
    assert result["meetingRound"]["status"] == "awaiting_approval"
    assert len(result["chatRoomRoundIds"]) == 2
    room_detail = chat_room_service.get_chat_room_detail(result["roomId"])
    for round_id in result["chatRoomRoundIds"]:
        bound = next(item for item in room_detail["rounds"] if item["roundId"] == round_id)
        assert bound["config"]["meetingRoundId"] == meeting_round_id
        assert bound["config"]["participantAgentIds"] == list(agents.values())
        assert [message["agentId"] for message in bound["messages"]] == list(
            agents.values()
        )


def test_discussion_driver_stops_at_round_budget(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch, runner=_content_runner)

    result = meeting_runtime.run_meeting_discussion(
        team_id,
        opened["meetingRound"]["meetingRoundId"],
        agent_runner=_content_runner,
    )

    assert result["stopReason"] == "budget_exhausted"
    assert result["roundsRun"] == 3
    assert result["completedMessageCount"] >= 3


def test_discussion_driver_enforces_max_messages_cap(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch, runner=_content_runner)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]

    result = meeting_runtime.run_meeting_discussion(
        team_id,
        meeting_round_id,
        agent_runner=_content_runner,
        max_messages=2,
    )

    assert result["stopReason"] == "max_messages"
    assert result["roundsRun"] < 3
    assert result["completedMessageCount"] >= 2

    with pytest.raises(ContractValidationError, match="maxMessages"):
        meeting_runtime.run_meeting_discussion(
            team_id, meeting_round_id, agent_runner=_content_runner, max_messages=0
        )


def test_failed_discussion_does_not_advance_to_summary(tmp_path, monkeypatch):
    team_id, _agents, opened = _open_meeting(
        tmp_path,
        monkeypatch,
        runner=_failed_runner,
    )
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]

    result = meeting_runtime.run_meeting_discussion(
        team_id,
        meeting_round_id,
        agent_runner=_failed_runner,
    )

    assert result["completedMessageCount"] == 0
    assert result["stopReason"] == "no_progress"
    assert result["summaryDraft"]["status"] == "blocked"
    assert result["summaryDraft"]["blocker"]["code"] == "discussion_has_no_completed_messages"
    persisted = meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"]
    assert persisted["status"] == "open"
    assert "summaryDraftError" not in persisted


def test_run_meeting_discussion_requires_open_bound_meeting(tmp_path, monkeypatch):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    agent_ids = list(agents.values())
    created = meetings.create_meeting_round(
        team_id,
        {
            "meetingRoundId": "meeting-hf2-unbound",
            "program": "XH-202619",
            "theme": "cc-neuro-001",
            "campaign": "cc-campaign-neuro-001",
            "question": "SCI-096",
            "branch": "main",
            "workflow": "hypothesis_first",
            "agentId": agent_ids[0],
            "mode": "dev",
            "meetingType": "hypothesis_review",
            "participants": agent_ids,
            "discussionItemRefs": ["hypothesis_candidate:cand-a"],
        },
    )
    with pytest.raises(meeting_runtime.ResearchMeetingRuntimeError, match="no bound chat room"):
        meeting_runtime.run_meeting_discussion(
            team_id, created["meetingRound"]["meetingRoundId"], agent_runner=_marker_runner
        )

    opened = meeting_runtime.open_hypothesis_review_meeting(
        team_id,
        _selection_payload(agent_ids),
        agent_runner=_marker_runner,
        background=False,
    )
    bound_round_id = opened["meetingRound"]["meetingRoundId"]
    meetings.begin_meeting_summary(team_id, bound_round_id)
    with pytest.raises(
        meeting_runtime.ResearchMeetingRuntimeError, match="while the meeting round is open"
    ):
        meeting_runtime.run_meeting_discussion(team_id, bound_round_id, agent_runner=_marker_runner)


def test_legacy_meeting_without_participant_snapshot_cannot_continue_discussion(
    tmp_path, monkeypatch
):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    _team, room_id = meeting_runtime._ensure_linked_room(team_id)
    created = meetings.create_meeting_round(
        team_id,
        {
            "meetingRoundId": "meeting-hf2-legacy-bound",
            "program": "XH-202619",
            "theme": "cc-neuro-001",
            "campaign": "cc-campaign-neuro-001",
            "question": "SCI-096",
            "branch": "main",
            "workflow": "hypothesis_first",
            "agentId": next(iter(agents.values())),
            "mode": "dev",
            "meetingType": "hypothesis_review",
            "participants": list(agents.values()),
            "discussionItemRefs": ["hypothesis_candidate:cand-a"],
            "linkedChatRoomId": room_id,
        },
    )
    meetings.bind_meeting_chat_room_round(
        team_id,
        created["meetingRound"]["meetingRoundId"],
        room_id,
        "round-legacy-bound",
    )

    with pytest.raises(
        meeting_runtime.ResearchMeetingRuntimeError,
        match="no complete participant snapshot",
    ):
        meeting_runtime.run_meeting_discussion(
            team_id,
            created["meetingRound"]["meetingRoundId"],
            agent_runner=_marker_runner,
        )


def test_meeting_status_transition_contract_map():
    ensure_meeting_status_transition("open", "summarizing")
    ensure_meeting_status_transition("summarizing", "awaiting_approval")
    ensure_meeting_status_transition("awaiting_approval", "summarizing")
    ensure_meeting_status_transition("awaiting_approval", "closed")
    with pytest.raises(ContractValidationError, match="not allowed"):
        ensure_meeting_status_transition("open", "closed")
    with pytest.raises(ContractValidationError, match="not allowed"):
        ensure_meeting_status_transition("summarizing", "closed")
    with pytest.raises(ContractValidationError, match="not allowed"):
        ensure_meeting_status_transition("closed", "open")
    with pytest.raises(ContractValidationError, match="must be one of"):
        ensure_meeting_status_transition("open", "bogus")


def test_legacy_v1_records_stay_readable_with_defaults():
    scope = {
        "program": "XH-202619",
        "theme": "cc-neuro-001",
        "campaign": "cc-campaign-neuro-001",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "hypothesis_first",
    }
    scope_hash = scope_hash_for(**scope, agent_id="agent-legacy", mode="formal")
    legacy_round = {
        "schemaVersion": 1,
        "meetingRoundId": "meeting-legacy-1",
        **scope,
        "agentId": "agent-legacy",
        "mode": "formal",
        "scopeHash": scope_hash,
        "meetingType": "hypothesis_review",
        "participants": ["agent-legacy"],
        "discussionItemRefs": [],
        "status": "open",
        "startedAt": "2026-08-01T00:00:00Z",
        "closedAt": "",
        "closedBy": "",
    }
    parsed_round = MeetingRound.from_dict(legacy_round)
    assert parsed_round.rounds == 3
    assert parsed_round.stage == ""
    assert parsed_round.roundType == ""
    assert parsed_round.agenda == ()
    assert parsed_round.participantRoleIds == ()
    assert parsed_round.inputArtifactRefs == ()
    assert parsed_round.linkedChatRoomId == ""
    assert parsed_round.chatRoomRoundIds == ()

    legacy_digest = {
        "schemaVersion": 1,
        "digestId": "digest-legacy-1",
        "meetingRoundId": "meeting-legacy-1",
        "scopeHash": scope_hash,
        "summary": "legacy digest",
        "participantAgentIds": ["agent-legacy"],
        "discussionTopics": [],
        "decisionRefs": ["decision-legacy-1"],
        "closedBy": "agent-legacy",
        "createdAt": "2026-08-01T00:00:00Z",
    }
    parsed_digest = MeetingDigest.from_dict(legacy_digest)
    assert parsed_digest.agendaSummary == ""
    assert parsed_digest.agreements == ()
    assert parsed_digest.disagreements == ()
    assert parsed_digest.actionItems == ()
    assert parsed_digest.knowledgeCandidates == ()
    assert parsed_digest.sourceMessageRefs == ()
    assert parsed_digest.contentHash == ""


def test_non_hypothesis_stage_coordination_stays_manual_only(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="HF2 回归研究员")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="HF2 回归研究员")
    team_id = team_service.create_team(
        name="HF-2 回归团队",
        members=[{"agentId": agent["agentId"], "role": "researcher"}],
    )["teamId"]

    response = team_workflow_orchestration_service.start_research_stage_round(
        team_id,
        {"stageType": "experiment", "topic": "回归：实验规划阶段不自动开会"},
    )

    contract = response["stageRound"]["coordinationContract"]
    assert contract["autoStarted"] is False
    assert contract["startResult"]["started"] is False
    assert contract["startResult"]["skipped"] is True
    assert contract["startResult"]["skipReason"] == "manual_only"

    room_id = str(team_service.get_team(team_id).get("linkedChatRoomId") or "").strip()
    if room_id:
        room_detail = chat_room_service.get_chat_room_detail(room_id)
        assert room_detail["rounds"] == []
