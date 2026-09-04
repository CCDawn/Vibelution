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
from core.web.services.team_workflow.research_runtime import meeting_receipt_authority

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


def test_meeting_discussion_executor_default_and_env_override(monkeypatch) -> None:
    """The driver pool defaults to 12; the env overrides it with a floor of 1.

    One executor thread drives one active meeting round end-to-end, so a
    four-thread pool queued later rounds for ~10 minutes under campaign
    concurrency before their first LLM call.  The module-level executor is
    built from the same helper the env override feeds.
    """

    monkeypatch.delenv("VIBELUTION_MEETING_DISCUSSION_MAX_WORKERS", raising=False)
    assert meeting_runtime._MEETING_DISCUSSION_MAX_WORKERS_DEFAULT == 24
    assert (
        meeting_runtime._meeting_discussion_max_workers()
        == meeting_runtime._MEETING_DISCUSSION_MAX_WORKERS_DEFAULT
    )
    assert meeting_runtime._MEETING_DISCUSSION_EXECUTOR._max_workers == (
        meeting_runtime._meeting_discussion_max_workers()
    )

    monkeypatch.setenv("VIBELUTION_MEETING_DISCUSSION_MAX_WORKERS", "16")
    assert meeting_runtime._meeting_discussion_max_workers() == 16
    monkeypatch.setenv("VIBELUTION_MEETING_DISCUSSION_MAX_WORKERS", "2")
    assert meeting_runtime._meeting_discussion_max_workers() == 2
    monkeypatch.setenv("VIBELUTION_MEETING_DISCUSSION_MAX_WORKERS", "0")
    assert meeting_runtime._meeting_discussion_max_workers() == 1
    monkeypatch.setenv("VIBELUTION_MEETING_DISCUSSION_MAX_WORKERS", "-5")
    assert meeting_runtime._meeting_discussion_max_workers() == 1
    monkeypatch.setenv("VIBELUTION_MEETING_DISCUSSION_MAX_WORKERS", "not-a-number")
    assert (
        meeting_runtime._meeting_discussion_max_workers()
        == meeting_runtime._MEETING_DISCUSSION_MAX_WORKERS_DEFAULT
    )


def _capture_discussion_events(monkeypatch) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []

    def capture(team_id, meeting_round_id, event_code, **details):
        events.append(
            {
                "teamId": team_id,
                "meetingRoundId": meeting_round_id,
                "eventCode": event_code,
                **details,
            }
        )

    monkeypatch.setattr(
        meeting_runtime,
        "_record_meeting_discussion_driver_event",
        capture,
    )
    return events


def test_meeting_discussion_event_is_bounded_and_best_effort(monkeypatch):
    from core.web.services import runtime_scene_service

    captured: dict[str, object] = {}

    def capture(*args, **kwargs):
        captured.update({"args": args, **kwargs})

    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event_quietly",
        capture,
    )
    meeting_runtime._record_meeting_discussion_driver_event(
        "team-observed",
        "meeting-observed",
        "meeting_discussion.round.completed",
        outcome="failed",
        fields={"roomId": "room-observed", "roundId": "round-observed"},
        error=RuntimeError("SECRET transcript and prompt"),
        error_category="round_execution",
    )

    assert captured["fields"] == {
        "teamId": "team-observed",
        "meetingRoundId": "meeting-observed",
        "roomId": "room-observed",
        "roundId": "round-observed",
        "errorCategory": "round_execution",
        "errorType": "RuntimeError",
    }
    assert "SECRET" not in json.dumps(captured, ensure_ascii=False, default=str)

    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event_quietly",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("scene down")),
    )
    meeting_runtime._record_meeting_discussion_driver_event(
        "team-observed",
        "meeting-observed",
        "meeting_discussion.run.started",
        outcome="started",
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


def _receipt_authority(team_id: str, *, run_id: str = "run-formal") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": team_id,
        "questionId": "SCI-096",
        "workflowRunId": run_id,
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "wv-formal",
        "modelPolicySha256": "a" * 64,
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


def test_candidate_generation_persists_server_receipt_authority_and_refuses_rebind(
    tmp_path, monkeypatch
):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    monkeypatch.setattr(
        meeting_receipt_authority,
        "workflow_run_stop_reason",
        lambda _authority: "",
    )
    contexts: list[dict[str, object]] = []

    def capture_runner(participant, prompt, context):
        contexts.append(dict(context))
        return {
            "status": "completed",
            "raw_output": "CANDIDATE: cand-a | 可证伪机制 | 正式运行",
            "summary": "ok",
        }

    payload = _selection_payload(list(agents.values()), meetingRoundId="meeting-cand-auth")
    opened = meeting_runtime.open_candidate_generation_meeting(
        team_id,
        payload,
        agent_runner=capture_runner,
        background=False,
        _model_invocation_receipt_authority=_receipt_authority(team_id),
    )

    assert opened["meetingRound"]["modelInvocationReceiptAuthority"]["workflowRunId"] == "run-formal"
    assert contexts
    assert contexts[0]["_modelInvocationReceiptAuthority"]["workflowRunId"] == "run-formal"
    with pytest.raises(meetings.ResearchMeetingRoundError, match="different content"):
        meeting_runtime.open_candidate_generation_meeting(
            team_id,
            payload,
            agent_runner=capture_runner,
            background=False,
            _model_invocation_receipt_authority=_receipt_authority(
                team_id,
                run_id="run-other",
            ),
        )


def test_reused_formal_meeting_without_receipt_authority_fails_closed(monkeypatch):
    scope = meeting_runtime.WorkflowDiscussionScopeV1.generation(
        teamId="team-1",
        researchProjectId="project-1",
        workflowRunId="run-1",
        workflowNodeId="hypothesis_design",
        questionId="SCI-096",
    )
    monkeypatch.setattr(meeting_runtime, "assert_writes_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        meeting_runtime,
        "_ensure_linked_room",
        lambda _team_id: ({"teamId": "team-1"}, "room-1"),
    )
    monkeypatch.setattr(
        meeting_runtime,
        "_validated_participant_resolution",
        lambda *_args, **_kwargs: {"participants": ["agent-1"]},
    )
    monkeypatch.setattr(
        meeting_runtime,
        "_discussion_scope_for_request",
        lambda *_args, **_kwargs: scope,
    )
    monkeypatch.setattr(
        meeting_runtime,
        "_resolve_scoped_meeting_room",
        lambda *_args, **_kwargs: ("room-1", scope),
    )
    monkeypatch.setattr(
        meetings,
        "create_meeting_round",
        lambda *_args, **_kwargs: {
            "status": "reused",
            "meetingRound": {"meetingRoundId": "meeting-existing"},
            "storagePath": "meeting-rounds.jsonl",
        },
    )

    with pytest.raises(
        meeting_runtime.ResearchMeetingRuntimeError,
        match="no verifiable receipt authority",
    ):
        meeting_runtime.open_candidate_generation_meeting(
            "team-1",
            {
                "questionId": "SCI-096",
                "meetingRoundId": "meeting-existing",
                "workflowRunId": "run-1",
                "workflowNodeId": "hypothesis_design",
                "researchProjectId": "project-1",
            },
            background=False,
        )


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
    opened = meeting_runtime.open_hypothesis_review_meeting(
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
    meeting = opened["meetingRound"]
    assert meeting["scopeAuthority"] == "preformal_candidate_review_scope.v1"
    assert meeting["deadlinePolicyVersion"] == "challenge_meeting_deadline.v1"
    assert meeting["challengeDeadlineAtMs"] == (
        meeting["serverCreatedAtMs"] + meeting["meetingBudgetMs"]
    )


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
    assert all("sourceTypes 只允许" in prompt for prompt in prompts)
    assert all(
        all(
            value in prompt
            for value in (
                "paper",
                "dataset",
                "url",
                "file",
                "note",
                "api",
                "news",
                "code",
                "repo",
                "report",
                "manual",
                "unknown",
            )
        )
        for prompt in prompts
    )
    assert all("evidenceLevels 只允许" in prompt for prompt in prompts)
    assert all(
        all(
            value in prompt
            for value in (
                "primary",
                "secondary",
                "tertiary",
                "high",
                "medium",
                "low",
                "peer_reviewed",
                "preprint",
            )
        )
        for prompt in prompts
    )
    assert all(
        '预印本使用 sourceTypes=["paper"]、evidenceLevels=["preprint"]' in prompt
        for prompt in prompts
    )
    assert all('代码仓库使用 sourceTypes=["repo"]' in prompt for prompt in prompts)
    assert all(
        "candidateRefs 只能填写本会议已绑定的候选 ID" in prompt
        for prompt in prompts
    )
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
    assert meeting_round["rounds"] == 2
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


def _direct_session_id(agent_id: str) -> str:
    return str(
        (session_service.ensure_agent_direct_session(agent_id=agent_id) or {}).get("id")
        or ""
    )


def _session_transcript(session_id: str) -> str:
    detail = session_service.get_session_detail(session_id) or {}
    return json.dumps(detail.get("messages") or [], ensure_ascii=False)


_PREFORMAL_FIXTURE_LINE = "cand-a 的机制证据最完整"


def test_preformal_review_room_binds_participants_to_hidden_child_sessions(
    tmp_path, monkeypatch
):
    """A preformal review speaks through Child Sessions, never direct Sessions."""

    team_id, agents, opened = _open_meeting(
        tmp_path,
        monkeypatch,
        meetingRoundId="meeting-t7-bound",
        selectedCandidateIds=["cand-a"],
    )
    room_id = opened["roomId"]
    room = chat_room_service.get_chat_room_detail(room_id)
    assert room["config"]["scopeAuthority"] == "preformal_candidate_review_scope.v1"

    direct_ids = {agent_id: _direct_session_id(agent_id) for agent_id in agents.values()}
    bound = {
        str(participant["agentId"]): str(participant.get("sessionId") or "")
        for participant in room["participants"]
    }
    assert set(bound) == set(direct_ids)
    for agent_id, session_id in bound.items():
        assert session_id
        assert session_id != direct_ids[agent_id]
        detail = session_service.get_session_detail(session_id)
        assert detail["sessionKind"] == "child"
        assert detail["hiddenFromIndex"] is True
        assert detail["parentSessionId"] == detail["rootSessionId"]
        assert detail["parentSessionId"] != direct_ids[agent_id]
        assert (
            detail["experimentBinding"]["discussionScope"]
            == room["config"]["discussionScope"]
        )
        assert (
            detail["experimentBinding"]["discussionScopeHash"]
            == room["config"]["scopeHash"]
        )
        direct_detail = session_service.get_session_detail(direct_ids[agent_id])
        assert not direct_detail["childSessionIds"]

    assert any(
        _PREFORMAL_FIXTURE_LINE in _session_transcript(session_id)
        for session_id in bound.values()
    )
    for agent_id in direct_ids:
        assert _PREFORMAL_FIXTURE_LINE not in _session_transcript(direct_ids[agent_id])

    reread = chat_room_service.get_chat_room_detail(room_id)
    assert {
        str(participant["agentId"]): str(participant.get("sessionId") or "")
        for participant in reread["participants"]
    } == bound


def test_preformal_review_room_reuses_the_same_child_sessions_on_reopen(
    tmp_path, monkeypatch
):
    team_id, agents, opened = _open_meeting(
        tmp_path,
        monkeypatch,
        meetingRoundId="meeting-t7-reopen",
        selectedCandidateIds=["cand-a"],
    )
    room_id = opened["roomId"]
    first = chat_room_service.get_chat_room_detail(room_id)
    bound = {
        str(participant["agentId"]): str(participant.get("sessionId") or "")
        for participant in first["participants"]
    }

    payload = _selection_payload(
        list(agents.values()),
        meetingRoundId="meeting-t7-reopen",
        selectedCandidateIds=["cand-a"],
    )
    reopened = meeting_runtime.open_hypothesis_review_meeting(
        team_id, payload, agent_runner=_marker_runner, background=False
    )
    second = chat_room_service.get_chat_room_detail(room_id)

    assert reopened["status"] == "reused"
    assert {
        str(participant["agentId"]): str(participant.get("sessionId") or "")
        for participant in second["participants"]
    } == bound
    for agent_id, session_id in bound.items():
        root = session_service.get_session_detail(session_id)["rootSessionId"]
        assert session_service.get_session_detail(root)["childSessionIds"] == [session_id]


def test_legacy_preformal_review_room_rebinds_off_direct_sessions(
    tmp_path, monkeypatch
):
    """A room created before Session isolation self-heals without touching history."""

    team_id, agents, opened = _open_meeting(
        tmp_path,
        monkeypatch,
        meetingRoundId="meeting-t7-legacy",
        selectedCandidateIds=["cand-a"],
    )
    room_id = opened["roomId"]
    room = chat_room_service.get_chat_room_detail(room_id)
    expected_scope_hash = room["config"]["scopeHash"]
    direct_ids = {
        str(participant["agentId"]): _direct_session_id(str(participant["agentId"]))
        for participant in room["participants"]
    }
    legacy_room = chat_room_service.update_chat_room(
        room_id,
        participant_session_ids=list(direct_ids.values()),
        config=dict(room["config"]),
    )
    assert {
        str(participant["agentId"]): str(participant.get("sessionId") or "")
        for participant in legacy_room["participants"]
    } == direct_ids

    reopened = meeting_runtime.open_hypothesis_review_meeting(
        team_id,
        _selection_payload(
            list(agents.values()),
            meetingRoundId="meeting-t7-legacy",
            selectedCandidateIds=["cand-a"],
        ),
        agent_runner=_marker_runner,
        background=False,
    )
    rebound = chat_room_service.get_chat_room_detail(room_id)

    assert reopened["status"] == "reused"
    assert rebound["config"]["scopeHash"] == expected_scope_hash
    for participant in rebound["participants"]:
        session_id = str(participant.get("sessionId") or "")
        agent_id = str(participant["agentId"])
        assert session_id
        assert session_id != direct_ids[agent_id]
        detail = session_service.get_session_detail(session_id)
        assert detail["sessionKind"] == "child"
        assert detail["hiddenFromIndex"] is True
        assert detail["experimentBinding"]["discussionScopeHash"] == expected_scope_hash


def test_preformal_review_room_refuses_a_mismatched_participant_roster(
    tmp_path, monkeypatch
):
    team_id, agents, opened = _open_meeting(
        tmp_path,
        monkeypatch,
        meetingRoundId="meeting-t7-roster",
        selectedCandidateIds=["cand-a"],
    )
    room_id = opened["roomId"]
    room = chat_room_service.get_chat_room_detail(room_id)
    kept = room["participants"][0]
    chat_room_service.update_chat_room(
        room_id,
        participant_session_ids=[str(kept["sessionId"])],
        config=dict(room["config"]),
    )

    with pytest.raises(
        meeting_runtime.ResearchMeetingRuntimeError,
        match="roster does not match the resolved participants",
    ):
        meeting_runtime.open_hypothesis_review_meeting(
            team_id,
            _selection_payload(
                list(agents.values()),
                meetingRoundId="meeting-t7-roster",
                selectedCandidateIds=["cand-a"],
            ),
            agent_runner=_marker_runner,
            background=False,
        )


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
    events = _capture_discussion_events(monkeypatch)
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]

    result = meeting_runtime.run_meeting_discussion(
        team_id, meeting_round_id, agent_runner=_marker_runner
    )

    assert result["stopReason"] == "converged"
    assert result["roundsRun"] == 2
    assert result["roundBudget"] == 2
    assert result["meetingRound"]["status"] == "awaiting_approval"
    assert len(result["chatRoomRoundIds"]) == 2
    assert [event["eventCode"] for event in events] == [
        "meeting_discussion.run.started",
        "meeting_discussion.round.started",
        "meeting_discussion.round.completed",
        "meeting_discussion.stop.decided",
        "meeting_discussion.summary.triggered",
    ]
    round_completed = events[2]
    assert round_completed["fields"]["roundId"] == result["chatRoomRoundIds"][-1]
    assert round_completed["fields"]["boundRoundCount"] == 2
    stop_decided = events[3]
    assert stop_decided["fields"]["stopReason"] == "converged"
    assert stop_decided["fields"]["passMessageCount"] == len(agents)
    assert events[4]["outcome"] == "succeeded"
    assert events[4]["fields"]["summaryStatus"] == "awaiting_approval"
    room_detail = chat_room_service.get_chat_room_detail(result["roomId"])
    for round_id in result["chatRoomRoundIds"]:
        bound = next(item for item in room_detail["rounds"] if item["roundId"] == round_id)
        assert bound["config"]["meetingRoundId"] == meeting_round_id
        assert bound["config"]["participantAgentIds"] == list(agents.values())
        assert [message["agentId"] for message in bound["messages"]] == list(
            agents.values()
        )


def test_round_close_schedules_one_cache_keepalive_per_round(tmp_path, monkeypatch):
    """Every round the discussion driver closes schedules exactly one cache
    keepalive probe, keyed by the persisted round id; scheduling failures
    never break the driver.  The opening round closes before the driver
    starts and is immediately followed by the driver's own round, so it is
    the driver-loop rounds that carry the keepalive."""

    from core.web.services.team_workflow import review_cache_keepalive

    scheduled: list[dict[str, str]] = []

    def capture_schedule(team_id, meeting_round_id, *, dedupe_key=""):
        scheduled.append(
            {
                "teamId": team_id,
                "meetingRoundId": meeting_round_id,
                "dedupeKey": dedupe_key,
            }
        )
        return {"status": "scheduled"}

    monkeypatch.setattr(
        review_cache_keepalive,
        "schedule_meeting_cache_keepalive",
        capture_schedule,
    )
    events = _capture_discussion_events(monkeypatch)
    team_id, _agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]

    result = meeting_runtime.run_meeting_discussion(
        team_id, meeting_round_id, agent_runner=_marker_runner
    )

    assert result["stopReason"] == "converged"
    assert result["roundsRun"] == 2
    assert [event["eventCode"] for event in events].count(
        "meeting_discussion.round.completed"
    ) == 1
    assert scheduled == [
        {
            "teamId": team_id,
            "meetingRoundId": meeting_round_id,
            "dedupeKey": result["chatRoomRoundIds"][-1],
        }
    ]


def test_round_close_keepalive_failure_never_breaks_the_driver(
    tmp_path, monkeypatch
):
    from core.web.services.team_workflow import review_cache_keepalive

    def broken_schedule(*_args, **_kwargs):
        raise RuntimeError("keepalive registry exploded")

    monkeypatch.setattr(
        review_cache_keepalive,
        "schedule_meeting_cache_keepalive",
        broken_schedule,
    )
    team_id, _agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]

    result = meeting_runtime.run_meeting_discussion(
        team_id, meeting_round_id, agent_runner=_marker_runner
    )

    assert result["status"] == "completed"
    assert result["stopReason"] == "converged"
    assert result["meetingRound"]["status"] == "awaiting_approval"


def test_formal_discussion_driver_reuses_bound_deadline_and_starts_no_late_round(monkeypatch):
    events = _capture_discussion_events(monkeypatch)
    meeting = {
        "meetingRoundId": "meeting-deadline",
        "status": "open",
        "linkedChatRoomId": "room-deadline",
        "chatRoomRoundIds": ["round-opening"],
        "rounds": 3,
        "question": "SCI-096",
        "meetingType": "hypothesis_candidate_generation",
        "modelInvocationReceiptAuthority": {
            "schemaVersion": 1,
            "authorityKind": "workflow_run",
            "teamId": "team-deadline",
            "questionId": "SCI-096",
            "workflowRunId": "run-deadline",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "wv-deadline",
            "modelPolicySha256": "a" * 64,
        },
    }
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda *_args: {"meetingRound": dict(meeting)},
    )
    monkeypatch.setattr(meeting_runtime, "_frozen_participant_agent_ids", lambda *_args: ["agent-1"])
    monkeypatch.setattr(meeting_runtime, "_selection_from_meeting", lambda *_args: {})
    monkeypatch.setattr(
        meeting_runtime,
        "_bound_room_challenge_deadline_at_ms",
        lambda *_args: 1_000_000,
    )
    monkeypatch.setattr(meeting_runtime.time, "time", lambda: 1000.001)
    monkeypatch.setattr(meeting_runtime, "workflow_run_stop_reason", lambda _authority: "")
    monkeypatch.setattr(meetings, "meeting_source_messages", lambda *_args: [{"status": "completed"}])
    monkeypatch.setattr(
        meeting_runtime,
        "prepare_meeting_summary_draft",
        lambda *_args, **_kwargs: {"meetingRound": dict(meeting)},
    )
    monkeypatch.setattr(
        meetings,
        "terminate_meeting_execution",
        lambda *_args, reason, **_kwargs: {
            "meetingRound": {**meeting, "status": "closed", "terminalReason": reason}
        },
    )
    monkeypatch.setattr(
        chat_room_service,
        "start_chat_room_round",
        lambda *_args, **_kwargs: pytest.fail("expired formal meeting must not start another room round"),
    )

    result = meeting_runtime._run_meeting_discussion_impl(
        "team-deadline",
        "meeting-deadline",
    )

    assert result["stopReason"] == "challenge_deadline"
    assert result["roundsRun"] == 1
    assert result["completedMessageCount"] == 1
    stop_decided = next(
        event
        for event in events
        if event["eventCode"] == "meeting_discussion.stop.decided"
    )
    assert stop_decided["fields"]["stopReason"] == "challenge_deadline"
    assert stop_decided["fields"]["deadlinePresent"] is True
    assert not any(
        event["eventCode"] == "meeting_discussion.summary.triggered"
        for event in events
    )
    assert meeting_runtime._round_config(
        {**meeting, "challengeDeadlineAtMs": 1_000_000},
        {},
        discussion_round_index=2,
        team_id="team-deadline",
    )["challengeDeadlineAtMs"] == 1_000_000


def test_old_workflow_run_can_open_new_review_meeting_with_fresh_server_deadline(
    tmp_path, monkeypatch
):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    before_ms = int(meeting_runtime.time.time() * 1000)
    selection = _selection_payload(
        list(agents.values()),
        meetingRoundId="meeting-review-after-old-run",
        startedAt="2025-01-01T00:00:00Z",
    )
    created = meetings.create_meeting_round(
        team_id,
        {
            **selection,
            "meetingType": "plan_review",
            "stage": "protocol",
            "roundType": "decision_gate",
            "modelInvocationReceiptAuthority": _receipt_authority(
                team_id,
                run_id="run-created-long-before-review",
            ),
        },
    )

    meeting_round = created["meetingRound"]
    deadline_at_ms = meeting_round["challengeDeadlineAtMs"]
    assert meeting_round["deadlinePolicyVersion"] == "challenge_meeting_deadline.v1"
    assert meeting_round["meetingBudgetMs"] == (
        meeting_round["perCallBudgetMs"]
        * meeting_round["plannedSerialCallCount"]
    )
    assert before_ms + meeting_round["meetingBudgetMs"] - 1_000 <= deadline_at_ms
    assert deadline_at_ms > before_ms + 300_000
    assert meeting_round["startedAt"] == "2025-01-01T00:00:00Z"
    assert meetings.get_meeting_round(
        team_id,
        meeting_round["meetingRoundId"],
    )["meetingRound"]["challengeDeadlineAtMs"] == deadline_at_ms


def test_review_meeting_round_config_carries_derived_per_call_budget(
    tmp_path, monkeypatch
):
    """The persisted meeting policy budget — not the 450s default — must reach
    the review meeting room round config (SCI production fence regression)."""

    from core.web.services.team_workflow import challenge_deadline_policy

    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    monkeypatch.setattr(
        challenge_deadline_policy,
        "derive_per_call_budget",
        lambda *_args, **_kwargs: {
            "perCallBudgetMs": 563_500,
            "latencyP95Ms": 450_800,
            "sampleCount": 40,
            "sampleSource": "provider_model_purpose_p95",
            "overrideEnv": "",
        },
    )
    # Keep the meeting open past the opening round; this test inspects the
    # round config, not the digest lifecycle.
    monkeypatch.setattr(
        meeting_runtime, "maybe_auto_draft_meeting", lambda *_args, **_kwargs: {}
    )
    monkeypatch.setattr(
        meeting_receipt_authority, "workflow_run_stop_reason", lambda _authority: ""
    )
    opened = meeting_runtime.open_hypothesis_review_meeting(
        team_id,
        _selection_payload(
            list(agents.values()),
            meetingRoundId="meeting-review-derived-budget",
        ),
        agent_runner=_marker_runner,
        background=False,
        _model_invocation_receipt_authority=_receipt_authority(
            team_id, run_id="run-derived-budget"
        ),
    )

    meeting_round = opened["meetingRound"]
    assert meeting_round["perCallBudgetMs"] == 563_500
    assert meeting_round["deadlinePolicyVersion"] == (
        challenge_deadline_policy.DEADLINE_POLICY_VERSION
    )
    round_config = chat_room_service.get_chat_room_detail(opened["roomId"])[
        "rounds"
    ][-1]["config"]
    assert round_config["perCallBudgetMs"] == 563_500
    assert round_config["perCallBudgetMs"] != (
        challenge_deadline_policy.DEFAULT_PER_CALL_BUDGET_MS
    )
    assert round_config["challengeDeadlineAtMs"] == meeting_round["challengeDeadlineAtMs"]
    assert round_config["meetingDeadlineAtMs"] == meeting_round["meetingDeadlineAtMs"]


def test_legacy_meeting_recovers_persisted_per_call_policy_from_bound_round(monkeypatch):
    """A legacy meeting without its own policy fields recovers them from the
    bound room round config so follow-up rounds keep the per-call fence."""

    meeting = {
        "meetingRoundId": "meeting-legacy-percall",
        "status": "open",
        "linkedChatRoomId": "room-legacy-percall",
        "chatRoomRoundIds": ["round-opening"],
        "rounds": 3,
        "question": "SCI-096",
        "meetingType": "hypothesis_review",
        "modelInvocationReceiptAuthority": {
            "schemaVersion": 1,
            "authorityKind": "workflow_run",
            "teamId": "team-legacy",
            "questionId": "SCI-096",
            "workflowRunId": "run-legacy",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "wv-legacy",
            "modelPolicySha256": "a" * 64,
        },
    }
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        meetings, "get_meeting_round", lambda *_args: {"meetingRound": dict(meeting)}
    )
    monkeypatch.setattr(meeting_runtime, "_frozen_participant_agent_ids", lambda *_args: ["agent-1"])
    monkeypatch.setattr(meeting_runtime, "_selection_from_meeting", lambda *_args: {})
    monkeypatch.setattr(
        meeting_runtime,
        "_bound_room_challenge_deadline_at_ms",
        lambda *_args: 5_000_000,
    )
    monkeypatch.setattr(
        meeting_runtime,
        "_bound_room_deadline_policy_field",
        lambda _room_id, _round_ids, field: {
            "perCallBudgetMs": 563_500,
            "meetingDeadlineAtMs": 5_000_000,
        }.get(field),
    )
    monkeypatch.setattr(meeting_runtime.time, "time", lambda: 1000.0)
    stop_reasons = [""]
    monkeypatch.setattr(
        meeting_runtime,
        "workflow_run_stop_reason",
        lambda _authority: stop_reasons.pop(0)
        if stop_reasons
        else "challenge_workflow_run_cancelled",
    )
    monkeypatch.setattr(
        meetings,
        "meeting_source_messages",
        lambda *_args: [{"status": "completed", "content": "DISAGREE: 证据不足"}],
    )
    monkeypatch.setattr(
        meeting_runtime,
        "_latest_bound_round_messages",
        lambda *_args: [{"status": "completed", "content": "DISAGREE: 证据不足"}],
    )
    monkeypatch.setattr(meetings, "is_pass_message", lambda _message: False)
    captured: dict[str, object] = {}

    def fake_start(_room_id, _topic, **kwargs):
        captured["config"] = dict(kwargs.get("config") or {})
        callback = kwargs.get("_on_round_persisted")
        if callback is not None:
            callback({"roomId": _room_id}, {"roundId": "round-followup"})
        return {"roundId": "round-followup", "status": "completed"}

    monkeypatch.setattr(chat_room_service, "start_chat_room_round", fake_start)
    monkeypatch.setattr(
        meetings,
        "bind_meeting_chat_room_round",
        lambda *_args, **_kwargs: {
            "meetingRound": {**meeting, "chatRoomRoundIds": ["round-opening", "round-followup"]}
        },
    )
    monkeypatch.setattr(
        meetings,
        "terminate_meeting_execution",
        lambda *_args, **_kwargs: {"meetingRound": dict(meeting)},
    )

    result = meeting_runtime._run_meeting_discussion_impl("team-legacy", "meeting-legacy-percall")

    assert result["stopReason"] == "challenge_workflow_run_cancelled"
    round_config = captured["config"]
    assert round_config["challengeDeadlineAtMs"] == 5_000_000
    assert round_config["perCallBudgetMs"] == 563_500
    assert round_config["meetingDeadlineAtMs"] == 5_000_000


@pytest.mark.parametrize(
    "stop_reason",
    ["challenge_workflow_run_cancelled", "challenge_workflow_run_blocked"],
)
def test_formal_discussion_starts_no_new_round_after_parent_run_inactive(
    monkeypatch,
    stop_reason,
):
    events = _capture_discussion_events(monkeypatch)
    meeting = {
        "meetingRoundId": "meeting-parent-cancelled",
        "status": "open",
        "linkedChatRoomId": "room-parent-cancelled",
        "chatRoomRoundIds": ["round-opening"],
        "rounds": 3,
        "question": "SCI-096",
        "meetingType": "hypothesis_candidate_generation",
        "modelInvocationReceiptAuthority": {
            "schemaVersion": 1,
            "authorityKind": "workflow_run",
            "teamId": "team-deadline",
            "questionId": "SCI-096",
            "workflowRunId": "run-cancelled",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "wv-deadline",
            "modelPolicySha256": "a" * 64,
        },
    }
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(meetings, "get_meeting_round", lambda *_args: {"meetingRound": dict(meeting)})
    monkeypatch.setattr(meeting_runtime, "_frozen_participant_agent_ids", lambda *_args: ["agent-1"])
    monkeypatch.setattr(meeting_runtime, "_selection_from_meeting", lambda *_args: {})
    monkeypatch.setattr(meeting_runtime, "_bound_room_challenge_deadline_at_ms", lambda *_args: None)
    monkeypatch.setattr(meetings, "meeting_source_messages", lambda *_args: [{"status": "completed"}])
    monkeypatch.setattr(
        meeting_runtime,
        "workflow_run_stop_reason",
        lambda _authority: stop_reason,
    )
    monkeypatch.setattr(
        chat_room_service,
        "start_chat_room_round",
        lambda *_args, **_kwargs: pytest.fail("cancelled parent must not start another room round"),
    )
    monkeypatch.setattr(
        meetings,
        "terminate_meeting_execution",
        lambda *_args, reason, **_kwargs: {
            "meetingRound": {**meeting, "status": "closed", "terminalReason": reason}
        },
    )

    result = meeting_runtime._run_meeting_discussion_impl(
        "team-deadline",
        "meeting-parent-cancelled",
    )

    assert result["status"] == "stopped"
    assert result["stopReason"] == stop_reason
    assert result["roundsRun"] == 1
    assert next(
        event["fields"]["stopReason"]
        for event in events
        if event["eventCode"] == "meeting_discussion.stop.decided"
    ) == stop_reason


def test_fenced_meeting_persists_closed_terminal_and_cannot_reschedule(tmp_path, monkeypatch):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    created = meetings.create_meeting_round(
        team_id,
        {
            **_selection_payload(
                list(agents.values()),
                meetingRoundId="meeting-fenced-terminal",
            ),
            "meetingType": "plan_review",
            "stage": "protocol",
            "roundType": "decision_gate",
            "modelInvocationReceiptAuthority": _receipt_authority(team_id),
        },
    )["meetingRound"]

    terminal = meetings.terminate_meeting_execution(
        team_id,
        created["meetingRoundId"],
        reason="challenge_workflow_run_cancelled",
    )["meetingRound"]

    assert terminal["status"] == "closed"
    assert terminal["executionStatus"] == "stopped"
    assert terminal["terminalReason"] == "challenge_workflow_run_cancelled"
    assert meeting_runtime.schedule_meeting_discussion(
        team_id,
        created["meetingRoundId"],
    )["status"] == "not_open"


def test_stopped_candidate_room_closes_meeting_and_generation_attempt(monkeypatch):
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

    meeting = {
        "meetingRoundId": "meeting-terminal-bridge",
        "meetingType": "hypothesis_candidate_generation",
        "status": "closed",
        "terminalReason": "challenge_workflow_run_blocked",
    }
    closed = []
    attempts = []
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda *_args: {"meetingRound": {**meeting, "status": "open"}},
    )
    monkeypatch.setattr(
        meetings,
        "terminate_meeting_execution",
        lambda team_id, meeting_id, *, reason: (
            closed.append((team_id, meeting_id, reason))
            or {"status": "stopped", "meetingRound": dict(meeting)}
        ),
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "fail_generation_attempt_for_meeting",
        lambda team_id, meeting_id, *, reason: attempts.append(
            (team_id, meeting_id, reason)
        ),
    )

    result = meeting_runtime.finalize_stopped_meeting_after_chat_round(
        {"roomId": "room-terminal-bridge"},
        {
            "roundId": "round-terminal-bridge",
            "terminalReason": "challenge_workflow_run_blocked",
            "config": {
                "teamId": "team-terminal-bridge",
                "meetingRoundId": "meeting-terminal-bridge",
                "meetingType": "hypothesis_candidate_generation",
            },
        },
    )

    assert result == {"status": "stopped", "meetingRound": meeting}
    assert closed == [
        (
            "team-terminal-bridge",
            "meeting-terminal-bridge",
            "challenge_workflow_run_blocked",
        )
    ]
    assert attempts == closed


def test_workflow_run_stop_reason_rechecks_blocked_then_allows_resumed_run(monkeypatch):
    statuses = iter(["blocked", "running"])

    class FakeStore:
        def get_run(self, _run_id):
            return type("Run", (), {"status": next(statuses)})()

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_write_runtime.get_write_store",
        lambda: FakeStore(),
    )
    authority = {"workflowRunId": "run-resumable"}

    assert meeting_receipt_authority.workflow_run_stop_reason(authority) == (
        "challenge_workflow_run_blocked"
    )
    assert meeting_receipt_authority.workflow_run_stop_reason(authority) == ""


def test_workflow_run_stop_reason_allows_only_chain_resolvable_readiness_blocks(
    monkeypatch,
):
    problem_jsons = iter(
        [
            json.dumps(
                {
                    "code": "auto_advance_not_ready",
                    "detail": "hypothesis_first_meeting_open",
                    "title": "评审尚未闭环",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "code": "auto_advance_not_ready",
                    "detail": "hypothesis_round_unconverged",
                }
            ),
            json.dumps(
                {
                    "code": "auto_advance_not_ready",
                    "detail": "source_candidates_missing",
                }
            ),
            json.dumps(
                {
                    "code": "auto_advance_not_ready",
                    "detail": "template_baseline_missing",
                }
            ),
            json.dumps(
                {
                    "code": "knowledge_gap_pending",
                    "detail": "hypothesis_round_unconverged",
                }
            ),
            json.dumps(
                {
                    "code": "auto_advance_not_ready",
                    "detail": ["hypothesis_first_meeting_open", "other"],
                }
            ),
            '{"code":"auto_advance_not_ready","detail":"other","detail":"hypothesis_first_meeting_open"}',
            "not-json",
            json.dumps({"code": "auto_advance_not_ready"}),
        ]
    )

    class FakeStore:
        def get_run(self, _run_id):
            return type(
                "Run",
                (),
                {
                    "status": "blocked",
                    "blocked_problem_json": next(problem_jsons),
                },
            )()

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_write_runtime.get_write_store",
        lambda: FakeStore(),
    )
    authority = {"workflowRunId": "run-blocked-human-gate"}

    # Chain-resolvable readiness gates: the chain's own meetings resolve them.
    assert meeting_receipt_authority.workflow_run_stop_reason(authority) == ""
    assert meeting_receipt_authority.workflow_run_stop_reason(authority) == ""
    # Every other blocked shape stays fail-closed.
    for _ in range(7):
        assert (
            meeting_receipt_authority.workflow_run_stop_reason(authority)
            == "challenge_workflow_run_blocked"
        )


def test_workflow_run_stop_reason_allows_mixed_chain_resolvable_details(monkeypatch):
    problem_jsons = iter(
        [
            json.dumps(
                {
                    "code": "auto_advance_not_ready",
                    "detail": "hypothesis_round_unconverged; template_baseline_missing",
                }
            ),
            json.dumps(
                {
                    "code": "auto_advance_not_ready",
                    "detail": "template_baseline_missing; hypothesis_round_unconverged",
                }
            ),
            json.dumps(
                {
                    "code": "auto_advance_not_ready",
                    "detail": "template_baseline_missing",
                }
            ),
            json.dumps(
                {
                    "code": "auto_advance_not_ready",
                    "detail": "source_candidates_missing; template_baseline_missing",
                }
            ),
            json.dumps(
                {
                    "code": "auto_advance_not_ready",
                    "detail": "hypothesis_round_unconverged ; hypothesis_first_meeting_open",
                }
            ),
        ]
    )

    class FakeStore:
        def get_run(self, _run_id):
            return type(
                "Run",
                (),
                {
                    "status": "blocked",
                    "blocked_problem_json": next(problem_jsons),
                },
            )()

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_write_runtime.get_write_store",
        lambda: FakeStore(),
    )
    authority = {"workflowRunId": "run-mixed-readiness-block"}

    # A joined readiness verdict stays meeting-permissive while any of its
    # causes is one the chain's own meetings resolve; the stale joined string
    # is not re-landed until the node re-dispatches, so exact matching here
    # deadlocked generation on runs blocked by several gates at once.
    assert meeting_receipt_authority.workflow_run_stop_reason(authority) == ""
    assert meeting_receipt_authority.workflow_run_stop_reason(authority) == ""
    # Details with no chain-resolvable cause stay fail-closed.
    assert (
        meeting_receipt_authority.workflow_run_stop_reason(authority)
        == "challenge_workflow_run_blocked"
    )
    assert (
        meeting_receipt_authority.workflow_run_stop_reason(authority)
        == "challenge_workflow_run_blocked"
    )
    assert meeting_receipt_authority.workflow_run_stop_reason(authority) == ""


def test_workflow_run_stop_reason_keeps_terminal_statuses_fail_closed(monkeypatch):
    statuses = iter(["cancelled", "failed"])

    class FakeStore:
        def get_run(self, _run_id):
            return type("Run", (), {"status": next(statuses)})()

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_write_runtime.get_write_store",
        lambda: FakeStore(),
    )
    authority = {"workflowRunId": "run-terminal"}

    assert meeting_receipt_authority.workflow_run_stop_reason(authority) == (
        "challenge_workflow_run_cancelled"
    )
    assert meeting_receipt_authority.workflow_run_stop_reason(authority) == (
        "challenge_workflow_run_failed"
    )


def test_formal_candidate_generation_runs_all_speakers_for_human_meeting_gate(
    tmp_path, monkeypatch
):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)

    class FakeStore:
        def get_run(self, _run_id):
            return type(
                "Run",
                (),
                {
                    "status": "blocked",
                    "blocked_problem_json": json.dumps(
                        {
                            "code": "auto_advance_not_ready",
                            "detail": "hypothesis_first_meeting_open",
                        }
                    ),
                },
            )()

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_write_runtime.get_write_store",
        lambda: FakeStore(),
    )
    agent_ids = list(agents.values())
    opened = meeting_runtime.open_candidate_generation_meeting(
        team_id,
        _selection_payload(
            agent_ids,
            meetingRoundId="meeting-human-gate-open",
        ),
        agent_runner=_marker_runner,
        background=False,
        _model_invocation_receipt_authority=_receipt_authority(
            team_id,
            run_id="run-blocked-human-gate",
        ),
    )

    room = chat_room_service.get_chat_room_detail(opened["roomId"])
    bound_round = next(
        item
        for item in room["rounds"]
        if item["roundId"] == opened["roundId"]
    )
    completed_messages = [
        message
        for message in bound_round["messages"]
        if message.get("status") == "completed"
    ]
    assert bound_round["status"] == "completed"
    assert len(completed_messages) == len(agent_ids)


def test_background_discussion_scheduler_deduplicates_one_ready_meeting(
    tmp_path, monkeypatch
):
    class DeferredExecutor:
        def __init__(self):
            self.submissions: list[tuple[object, tuple[object, ...]]] = []

        def submit(self, callback, *args):
            self.submissions.append((callback, args))
            return object()

    # The scheduler now persists a durable intent next to meeting_rounds.jsonl;
    # keep that write hermetic like the other meeting fixtures.
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    team_id = "team-scheduled-discussion"
    meeting_id = "meeting-scheduled-discussion"
    executor = DeferredExecutor()
    meeting = {
        "meetingRoundId": meeting_id,
        "status": "open",
        "chatRoomRoundIds": ["room-round-1"],
    }
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        meetings,
        "get_meeting_round",
        lambda *_args: {"meetingRound": dict(meeting)},
    )
    monkeypatch.setattr(meetings, "running_bound_round_ids", lambda *_args: [])
    monkeypatch.setattr(
        meeting_runtime,
        "_latest_bound_round_messages",
        lambda *_args: [{"status": "completed"}],
    )
    monkeypatch.setattr(meeting_runtime, "_MEETING_DISCUSSION_EXECUTOR", executor)
    monkeypatch.setattr(
        meeting_runtime,
        "run_meeting_discussion",
        lambda *_args, **_kwargs: {"stopReason": "converged"},
    )
    monkeypatch.setattr(
        meeting_runtime,
        "_record_meeting_discussion_driver_event",
        lambda *_args, **_kwargs: None,
    )
    key = (team_id, meeting_id)
    with meeting_runtime._MEETING_DISCUSSION_JOBS_LOCK:
        meeting_runtime._MEETING_DISCUSSION_JOBS.pop(key, None)
    try:
        first = meeting_runtime.schedule_meeting_discussion(team_id, meeting_id)
        duplicate = meeting_runtime.schedule_meeting_discussion(team_id, meeting_id)

        assert first["status"] == "scheduled"
        assert duplicate["status"] == "already_scheduled"
        assert len(executor.submissions) == 1

        callback, args = executor.submissions[0]
        callback(*args)
        with meeting_runtime._MEETING_DISCUSSION_JOBS_LOCK:
            assert key not in meeting_runtime._MEETING_DISCUSSION_JOBS
    finally:
        with meeting_runtime._MEETING_DISCUSSION_JOBS_LOCK:
            meeting_runtime._MEETING_DISCUSSION_JOBS.pop(key, None)


def test_auto_drive_hook_queues_discussion_instead_of_drafting(monkeypatch):
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        meeting_runtime,
        "schedule_meeting_discussion",
        lambda team_id, meeting_id: captured.update(
            {"teamId": team_id, "meetingRoundId": meeting_id}
        )
        or {"status": "scheduled", "meetingRoundId": meeting_id},
    )
    monkeypatch.setattr(
        meeting_runtime,
        "maybe_auto_draft_meeting",
        lambda *_args, **_kwargs: pytest.fail("auto-drive must not draft after round one"),
    )

    result = meeting_runtime.maybe_auto_draft_after_chat_round(
        {"roomId": "room-auto-drive", "config": {"teamId": "team-auto-drive"}},
        {
            "roundId": "round-auto-drive",
            "config": {
                "teamId": "team-auto-drive",
                "meetingRoundId": "meeting-auto-drive",
                "autoDriveDiscussion": True,
            },
        },
    )

    assert result == {"status": "scheduled", "meetingRoundId": "meeting-auto-drive"}
    assert captured == {
        "teamId": "team-auto-drive",
        "meetingRoundId": "meeting-auto-drive",
    }


def test_discussion_driver_stops_at_round_budget(tmp_path, monkeypatch):
    events = _capture_discussion_events(monkeypatch)
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch, runner=_content_runner)

    result = meeting_runtime.run_meeting_discussion(
        team_id,
        opened["meetingRound"]["meetingRoundId"],
        agent_runner=_content_runner,
    )

    assert result["stopReason"] == "budget_exhausted"
    assert result["roundsRun"] == 2
    assert result["completedMessageCount"] >= 3
    assert next(
        event["fields"]["stopReason"]
        for event in events
        if event["eventCode"] == "meeting_discussion.stop.decided"
    ) == "budget_exhausted"


def test_discussion_driver_enforces_max_messages_cap(tmp_path, monkeypatch):
    events = _capture_discussion_events(monkeypatch)
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
    assert next(
        event["fields"]["stopReason"]
        for event in events
        if event["eventCode"] == "meeting_discussion.stop.decided"
    ) == "max_messages"

    with pytest.raises(ContractValidationError, match="maxMessages"):
        meeting_runtime.run_meeting_discussion(
            team_id, meeting_round_id, agent_runner=_content_runner, max_messages=0
        )


def test_failed_discussion_does_not_advance_to_summary(tmp_path, monkeypatch):
    events = _capture_discussion_events(monkeypatch)
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
    assert next(
        event["fields"]["stopReason"]
        for event in events
        if event["eventCode"] == "meeting_discussion.stop.decided"
    ) == "no_progress"
    summary_triggered = next(
        event
        for event in events
        if event["eventCode"] == "meeting_discussion.summary.triggered"
    )
    assert summary_triggered["outcome"] == "blocked"
    assert summary_triggered["fields"]["summaryStatus"] == "blocked"
    persisted = meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"]
    assert persisted["status"] == "open"
    assert "summaryDraftError" not in persisted


def test_schedule_discussion_waits_on_terminal_silent_latest_round(tmp_path, monkeypatch):
    """Resume pins the documented contract for the restart-orphan shape.

    An open meeting whose latest bound round terminally died with zero
    completed speech answers ``waiting_for_completed_speech`` — the resume
    scheduler only continues meetings whose latest round spoke.  That orphan
    must redrive through the reopen/retry recovery paths, which judge the
    same last-bound-round view (SCI-007).
    """
    # Model the backend restart: no automatic summary drafting ever lands
    # (the process died before the post-round hook and the driver's graceful
    # stop), so the meeting record stays ``open`` across both rounds.
    monkeypatch.setattr(
        meeting_runtime,
        "maybe_auto_draft_meeting",
        lambda *_args, **_kwargs: None,
    )
    team_id, _agents, opened = _open_meeting(
        tmp_path, monkeypatch, runner=_content_runner
    )
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]

    monkeypatch.setattr(
        meeting_runtime,
        "prepare_meeting_summary_draft",
        lambda *_args, **_kwargs: {
            "status": "open",
            "meetingRound": meetings.get_meeting_round(
                team_id, meeting_round_id
            )["meetingRound"],
        },
    )

    # Round 2 dies before its first completed message: terminal, silent.
    driven = meeting_runtime.run_meeting_discussion(
        team_id, meeting_round_id, agent_runner=_failed_runner
    )
    # The planned-round budget ends the driver either way; what matters is
    # that round 2 ran and produced zero completed speech.
    assert driven["roundsRun"] == 2
    assert driven["stopReason"] in {"no_progress", "budget_exhausted"}
    orphan = meetings.get_meeting_round(team_id, meeting_round_id)["meetingRound"]
    assert orphan["status"] == "open"
    assert len(orphan["chatRoomRoundIds"]) == 2
    assert meetings.completed_meeting_source_messages(orphan)
    assert not meetings.completed_latest_bound_round_source_messages(orphan)

    scheduled = meeting_runtime.schedule_meeting_discussion(
        team_id, meeting_round_id
    )

    assert scheduled["status"] == "waiting_for_completed_speech"


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
    assert parsed_round.rounds == 2
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
    assert parsed_digest.documentMarkdown == ""
    assert parsed_digest.documentTemplateId == ""
    assert parsed_digest.factLedger == {}
    assert parsed_digest.contentHash == ""


def test_meeting_digest_contract_round_trips_document_and_fact_ledger():
    scope_hash = "d" * 64
    payload = {
        "schemaVersion": 2,
        "digestId": "digest-document-1",
        "meetingRoundId": "meeting-document-1",
        "scopeHash": scope_hash,
        "summary": "评审完成，倾向候选 A。",
        "participantAgentIds": ["agent-a"],
        "discussionTopics": ["评审候选 A/B"],
        "decisionRefs": ["decision-a"],
        "closedBy": "reviewer",
        "createdAt": "2026-09-01T00:00:00Z",
        "sourceMessageRefs": ["room-a/round-a/message-a"],
        "documentMarkdown": "# 评审纪要\n\n## 会议结论\n\n评审完成，倾向候选 A。",
        "documentTemplateId": "open_sections_v1",
        "factLedger": {
            "schemaVersion": 1,
            "source": "completed_meeting_messages",
            "agreements": ["候选 A 更契合赛题"],
            "sourceMessageRefs": ["room-a/round-a/message-a"],
        },
    }

    parsed = MeetingDigest.from_dict(payload)

    assert parsed.documentMarkdown.startswith("# 评审纪要")
    assert parsed.documentTemplateId == "open_sections_v1"
    assert parsed.factLedger["source"] == "completed_meeting_messages"
    assert parsed.to_dict()["factLedger"] == payload["factLedger"]


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


# ---------------------------------------------------------------------------
# Protocol fact ledger projection after LLM digest drafting.
#
# The LLM owns an open Markdown document. Explicit source-message protocol
# markers are independently captured in ``factLedger`` and projected into the
# legacy digest buckets while downstream consumers migrate.
# ---------------------------------------------------------------------------


def _lossy_llm_drafter(meeting_round, source_messages):
    """Mimic the production failure: rewrite every marker, drop evidence requests."""

    refs = [
        meetings.message_source_ref(message)
        for message in source_messages
        if str(message.get("status") or "").strip().lower() == "completed"
        and not meetings.is_pass_message(message)
    ]
    return {
        "summary": "LLM 叙事：评审整体顺利，倾向 cand-a。",
        "agendaSummary": "LLM 议程复述",
        "discussionTopics": ["LLM 话题一"],
        "documentMarkdown": "# 评审纪要\n\n## 会议结论\n\nLLM 叙事：评审整体顺利，倾向 cand-a。",
        "documentTemplateId": "open_sections_v1",
        "agreements": ["LLM 改写的共识"],
        "disagreements": [{"issue": "LLM 改写的分歧", "positions": [], "unresolvedReason": ""}],
        "actionItems": [{"ownerRoleId": "llm", "action": "LLM 改写的行动项", "dueGate": ""}],
        "risks": ["LLM 改写的风险"],
        "blockers": [],
        "knowledgeCandidates": ["LLM 改写的知识条目"],
        "proposedCandidates": [],
        "evidenceRequests": [],
        "sourceMessageRefs": refs,
    }


def _draft_with_lossy_llm(tmp_path, monkeypatch, *, runner=None):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch, runner=runner)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    agent_ids = list(agents.values())
    meetings.begin_meeting_summary(team_id, meeting_round_id, actor=agent_ids[0])
    drafted = meeting_runtime.draft_meeting_digest(
        team_id, meeting_round_id, drafter=_lossy_llm_drafter
    )
    assert drafted["status"] == "awaiting_approval"
    return team_id, agents, opened, drafted


def test_llm_digest_protocol_facts_live_in_separate_ledger(tmp_path, monkeypatch):
    team_id, agents, opened, drafted = _draft_with_lossy_llm(tmp_path, monkeypatch)
    draft = drafted["digestDraft"]
    meeting_round = drafted["meetingRound"]

    expected = meetings.extract_discussion_markers(
        meetings.completed_meeting_source_messages(meeting_round)
    )
    ledger = draft["factLedger"]
    assert ledger["schemaVersion"] == 1
    assert ledger["source"] == "completed_meeting_messages"
    # The lossy LLM rewrite never becomes authoritative. Every protocol-fact
    # bucket comes from the source ledger, and legacy fields are projections.
    assert ledger["agreements"] == expected["agreements"]
    assert ledger["disagreements"] == expected["disagreements"]
    assert ledger["risks"] == expected["risks"]
    assert ledger["actionItems"] == expected["actionItems"]
    assert ledger["knowledgeCandidates"] == expected["knowledgeCandidates"]
    assert ledger["proposedCandidates"] == expected["proposedCandidates"]
    assert draft["agreements"] == expected["agreements"]
    assert draft["disagreements"] == expected["disagreements"]
    assert draft["risks"] == expected["risks"]
    assert draft["actionItems"] == expected["actionItems"]
    assert draft["knowledgeCandidates"] == expected["knowledgeCandidates"]
    assert draft["proposedCandidates"] == expected["proposedCandidates"]
    assert expected["disagreements"], "fixture must carry disagreements to protect"
    assert all(
        item["issue"] == "cand-b 的泛化证据不足" for item in draft["disagreements"]
    )
    assert "数据集偏差尚未评估" in draft["risks"]
    assert all(
        item["action"] == "补充 cand-b 的消融实验证据" for item in draft["actionItems"]
    )

    # Narrative fields stay LLM-owned and must not be cleared by the merge.
    assert draft["summary"] == "LLM 叙事：评审整体顺利，倾向 cand-a。"
    assert draft["agendaSummary"] == "LLM 议程复述"
    assert draft["discussionTopics"] == ["LLM 话题一"]
    assert draft["documentMarkdown"].startswith("# 评审纪要")
    assert draft["sourceMessageRefs"]


def test_llm_digest_merge_passes_close_marker_gate(tmp_path, monkeypatch):
    team_id, agents, opened, drafted = _draft_with_lossy_llm(tmp_path, monkeypatch)
    draft = drafted["digestDraft"]
    markers = meetings.extract_discussion_markers(
        meetings.completed_meeting_source_messages(drafted["meetingRound"])
    )

    # The close gate passes on the merged draft directly...
    meetings._assert_markers_preserved(draft, markers)
    # ...and through the full closure flow that re-runs extraction fail-closed.
    agent_ids = list(agents.values())
    approved = meetings.approve_meeting_closure(
        team_id, drafted["meetingRound"]["meetingRoundId"], _closure_payload(agent_ids)
    )
    assert approved["meetingRound"]["status"] == "closed"
    assert any(
        item["issue"] == "cand-b 的泛化证据不足"
        for item in approved["digest"]["disagreements"]
    )
    assert approved["digest"]["documentMarkdown"].startswith("# 评审纪要")
    assert approved["digest"]["factLedger"]["disagreements"]


def _evidence_marker_runner(participant, prompt, context):
    """Round 1 carries markers plus one EVIDENCE_REQUEST; critique rounds pass."""
    if "批评与修订" in str(prompt):
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}
    role = str(participant.get("teamRole") or "participant")
    if role == "challenge_cup_search":
        return {
            "status": "completed",
            "raw_output": "AGREE: cand-a 的机制证据最完整，进入有界验证",
            "summary": "ok",
        }
    envelope = json.dumps(
        {
            "rationale": "cand-b 的泛化证据不足，需要按信封补充搜集。",
            "candidateRefs": ["cand-b"],
            "evidenceRefs": ["evidence:review-matrix-1"],
            "searchEnvelope": {
                "keywords": ["predictive coding", "spike train coding"],
                "sourceTypes": ["paper"],
                "evidenceLevels": ["peer_reviewed"],
            },
            "requirements": {"minEvidenceLevel": "medium", "completeness": "stage-one"},
            "writebackPolicy": {},
        },
        ensure_ascii=False,
    )
    return {
        "status": "completed",
        "raw_output": (
            "DISAGREE: cand-b 的泛化证据不足\n"
            "RISK: 数据集偏差尚未评估\n"
            "ACTION: researcher | 补充 cand-b 的消融实验证据\n"
            f"EVIDENCE_REQUEST: {envelope}"
        ),
        "summary": "ok",
    }


def test_llm_digest_evidence_requests_keep_extraction_verbatim(tmp_path, monkeypatch):
    team_id, agents, opened, drafted = _draft_with_lossy_llm(
        tmp_path, monkeypatch, runner=_evidence_marker_runner
    )
    draft = drafted["digestDraft"]

    # The lossy drafter dropped evidenceRequests entirely; the merge restores
    # them from the source-message markers with keywords untouched.
    requests = draft["evidenceRequests"]
    assert len(requests) >= 1
    assert requests[0]["searchEnvelope"]["keywords"] == [
        "predictive coding",
        "spike train coding",
    ]
    assert requests[0]["rationale"] == "cand-b 的泛化证据不足，需要按信封补充搜集。"
    assert requests[0]["candidateRefs"] == ["cand-b"]
    assert requests[0]["requirements"] == {
        "minEvidenceLevel": "medium",
        "completeness": "stage-one",
        "notes": "",
    }
    assert draft["validationErrors"] == []


def test_system_auto_draft_path_also_merges_deterministic_markers(tmp_path, monkeypatch):
    team_id, agents, opened = _open_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]

    drafted = meeting_runtime.prepare_meeting_summary_draft(
        team_id,
        meeting_round_id,
        actor="system",
        force=False,
        drafter=_lossy_llm_drafter,
    )
    assert drafted["status"] == "awaiting_approval"
    draft = drafted["digestDraft"]
    expected = meetings.extract_discussion_markers(
        meetings.completed_meeting_source_messages(drafted["meetingRound"])
    )
    assert draft["disagreements"] == expected["disagreements"]
    assert draft["risks"] == expected["risks"]
    assert draft["actionItems"] == expected["actionItems"]
    assert draft["summary"] == "LLM 叙事：评审整体顺利，倾向 cand-a。"


def test_llm_digest_with_empty_protocol_buckets_submits_legal_empty_buckets(
    tmp_path, monkeypatch
):
    def _freeform_runner(participant, prompt, context):
        if "批评与修订" in str(prompt):
            return {"status": "completed", "raw_output": "pass", "summary": "pass"}
        return {
            "status": "completed",
            "raw_output": "自由格式评审意见，没有使用任何协议标记。",
            "summary": "ok",
        }

    team_id, agents, opened, drafted = _draft_with_lossy_llm(
        tmp_path, monkeypatch, runner=_freeform_runner
    )
    draft = drafted["digestDraft"]
    # Extraction is empty, so the hallucinated LLM markers are stripped and the
    # submitted draft carries legal empty buckets instead.
    assert draft["agreements"] == []
    assert draft["disagreements"] == []
    assert draft["risks"] == []
    assert draft["actionItems"] == []
    assert draft["knowledgeCandidates"] == []
    assert draft["summary"] == "LLM 叙事：评审整体顺利，倾向 cand-a。"
    assert draft["sourceMessageRefs"]
