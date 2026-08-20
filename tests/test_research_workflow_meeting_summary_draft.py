"""Meeting summary-draft / approve-digest state machine (hypothesis-first).

Covers the P0/P1 server contract: bound-round gate, open→summarizing→
awaiting_approval recovery, same source-hash reuse, draft-error retry,
stale digest hash, generation candidate registration, and review
evidenceRequests → one collection request.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services import chat_room_service
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import question_launch

from tests.test_research_workflow_hypothesis_first_chain import (
    _QUESTION_ID,
    _ROLES,
    _build_runtime,
    _candidate_generation_runner,
    _fake_collection_runs,
    _hf_env,
    _open_first_meeting,
    _patch_approved_question,
    _seed_parent_run,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)


def _evidence_request_payload(**overrides) -> dict:
    payload = {
        "rationale": "hyp-b 的泛化证据不足，需要按信封补充搜集。",
        "candidateRefs": ["hyp-b"],
        "evidenceRefs": ["evidence:review-matrix-1"],
        "searchEnvelope": {
            "keywords": ["predictive coding", "spike train coding"],
            "sourceTypes": ["paper"],
            "evidenceLevels": ["peer_reviewed"],
        },
        "requirements": {"minEvidenceLevel": "medium", "completeness": "stage-one"},
        "writebackPolicy": {},
    }
    payload.update(overrides)
    return payload


def _evidence_runner(participant, prompt, context):
    if "批评与修订" in str(prompt):
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}
    role = str(participant.get("teamRole") or "participant")
    if role == "coordinator":
        return {
            "status": "completed",
            "raw_output": "AGREE: hyp-a 的机制证据最完整，进入有界验证",
            "summary": "ok",
        }
    envelope = json.dumps(_evidence_request_payload(), ensure_ascii=False)
    return {
        "status": "completed",
        "raw_output": (
            "DISAGREE: hyp-b 的泛化证据不足\n"
            "RISK: 数据集偏差尚未评估\n"
            "ACTION: researcher | 补充 hyp-b 的消融实验证据\n"
            "KNOWLEDGE: 预测编码层级最新综述\n"
            f"EVIDENCE_REQUEST: {envelope}"
        ),
        "summary": "ok",
    }


def _invalid_evidence_runner(participant, prompt, context):
    if "批评与修订" in str(prompt):
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}
    role = str(participant.get("teamRole") or "participant")
    if role == "coordinator":
        return {
            "status": "completed",
            "raw_output": "AGREE: 先确认本轮结论",
            "summary": "ok",
        }
    envelope = json.dumps(
        _evidence_request_payload(
            searchEnvelope={"keywords": [], "sourceTypes": ["paper"]}
        ),
        ensure_ascii=False,
    )
    return {
        "status": "completed",
        "raw_output": (
            "DISAGREE: hyp-b 的泛化证据不足\n"
            "RISK: 数据集偏差尚未评估\n"
            "ACTION: researcher | 补充 hyp-b 的消融实验证据\n"
            "KNOWLEDGE: 预测编码层级最新综述\n"
            f"EVIDENCE_REQUEST: {envelope}"
        ),
        "summary": "ok",
    }


def test_summary_draft_blocks_running_bound_rounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(meeting_runtime, "maybe_auto_draft_meeting", lambda *a, **k: None)
    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
        monkeypatch.setattr(
            chat_room_service,
            "RUNNING_ROUND_STATUSES",
            {"queued", "running", "stopping", "completed"},
        )
        result = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert result["status"] == "blocked"
        assert result["blocker"]["code"] == "discussion_round_running"
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        assert meeting["status"] == "open"


def test_summary_draft_open_to_awaiting_approval_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(meeting_runtime, "maybe_auto_draft_meeting", lambda *a, **k: None)
    agent_ids = [agents[role] for role in _ROLES]
    build_calls = {"count": 0}
    original = meeting_runtime.build_meeting_digest_draft

    def counting_builder(*args, **kwargs):
        build_calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(meeting_runtime, "build_meeting_digest_draft", counting_builder)
    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
        first = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert first["status"] == "awaiting_approval"
        assert first["digestDraft"]["sourceMessageContentHash"]
        second = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert second["status"] == "awaiting_approval"
        assert (
            second["digestDraft"]["contentHash"] == first["digestDraft"]["contentHash"]
        )
        assert (
            second["digestDraft"]["sourceMessageContentHash"]
            == first["digestDraft"]["sourceMessageContentHash"]
        )
        assert build_calls["count"] == 1


def test_summary_draft_retries_from_summarizing_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(meeting_runtime, "maybe_auto_draft_meeting", lambda *a, **k: None)
    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]

        original_builder = meeting_runtime.build_meeting_digest_draft

        def boom(*_args, **_kwargs):
            raise RuntimeError("coordinator draft exploded")

        monkeypatch.setattr(meeting_runtime, "build_meeting_digest_draft", boom)
        failed = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert failed["status"] == "summarizing"
        assert failed["summaryDraftError"]["code"]
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        assert meeting["status"] == "summarizing"
        assert meeting["summaryDraftError"]["code"]

        monkeypatch.setattr(meeting_runtime, "build_meeting_digest_draft", original_builder)
        retried = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert retried["status"] == "awaiting_approval"
        assert retried.get("summaryDraftError") in (None, {})


def test_approve_digest_rejects_stale_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
        drafted = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert drafted["status"] == "awaiting_approval"
        with pytest.raises(chain.StaleDigestError) as exc:
            chain.approve_meeting_digest(
                team_id,
                meeting_id,
                closed_by=agent_ids[0],
                expected_digest_content_hash="not-the-current-hash",
            )
        assert exc.value.code == "stale_digest"
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        assert meeting["status"] == "awaiting_approval"


def test_approve_generation_registers_ledger_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )
    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        opened = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )
        meeting_id = opened["meetingRound"]["meetingRoundId"]
        drafted = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert drafted["digestDraft"]["proposedCandidates"]
        approved = chain.approve_meeting_digest(
            team_id,
            meeting_id,
            closed_by=agent_ids[0],
            expected_digest_content_hash=drafted["digestDraft"]["contentHash"],
        )
        assert approved["meetingRound"]["status"] == "closed"
        assert approved["candidateCount"] >= 1
        listed = chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)
        assert listed["candidateCount"] >= 1


def test_approve_review_digest_starts_one_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    collection_calls = _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    from core.web.services.team_workflow import hypothesis_selection as selections

    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        recorded = selections.record_hypothesis_selection(
            team_id,
            {
                "program": "XH-202619",
                "theme": "cc-neuro-001",
                "campaign": "cc-campaign-neuro-001",
                "question": _QUESTION_ID,
                "branch": "main",
                "workflow": "hypothesis_first",
                "agentId": agent_ids[0],
                "mode": "dev",
                "questionId": _QUESTION_ID,
                "selectedCandidateIds": ["hyp-a", "hyp-b"],
                "decidedBy": agent_ids[0],
            },
            agent_runner=_evidence_runner,
        )
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
        drafted = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert drafted["status"] == "awaiting_approval"
        assert drafted["digestDraft"]["evidenceRequests"]
        approved = chain.approve_meeting_digest(
            team_id,
            meeting_id,
            closed_by=agent_ids[0],
            expected_digest_content_hash=drafted["digestDraft"]["contentHash"],
            runtime=runtime,
        )
        assert approved["meetingRound"]["status"] == "closed"
        assert len(approved["collection"]["requests"]) == 1
        assert len(collection_calls) == 1


def test_approve_review_digest_without_keywords_stays_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    collection_calls = _fake_collection_runs(monkeypatch)
    from core.web.services.team_workflow import hypothesis_selection as selections

    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        recorded = selections.record_hypothesis_selection(
            team_id,
            {
                "program": "XH-202619",
                "theme": "cc-neuro-001",
                "campaign": "cc-campaign-neuro-001",
                "question": _QUESTION_ID,
                "branch": "main",
                "workflow": "hypothesis_first",
                "agentId": agent_ids[0],
                "mode": "dev",
                "questionId": _QUESTION_ID,
                "selectedCandidateIds": ["hyp-a", "hyp-b"],
                "decidedBy": agent_ids[0],
            },
            agent_runner=_invalid_evidence_runner,
        )
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
        drafted = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert drafted["digestDraft"]["validationErrors"]
        approved = chain.approve_meeting_digest(
            team_id,
            meeting_id,
            closed_by=agent_ids[0],
            expected_digest_content_hash=drafted["digestDraft"]["contentHash"],
        )
        assert approved["closed"] is False
        assert approved["status"] == "awaiting_approval"
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        assert meeting["status"] == "awaiting_approval"
        assert collection_calls == []


def test_build_round_candidates_falls_back_to_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(question_launch, "_approved_details", lambda _team_id: {})
    with server_operator_scope("u-1", roles=("operator",)):
        fake_meeting = {"meetingRoundId": "mr-gen-ledger", "question": _QUESTION_ID}
        appended = chain._append_generation_candidates(
            team_id,
            fake_meeting,
            [
                {
                    "statement": "睡眠剥夺通过腺苷积累损害记忆巩固",
                    "rationale": "腺苷机制",
                    "proposedBy": "operator",
                }
            ],
        )
        candidate_id = appended[0]["candidateId"]
        review_meeting = {
            "question": _QUESTION_ID,
            "discussionItemRefs": [f"hypothesis_candidate:{candidate_id}"],
        }
        built = chain._build_round_candidates(team_id, review_meeting)
        assert built[0]["claim"] == "睡眠剥夺通过腺苷积累损害记忆巩固"
        assert built[0]["rationale"] == "腺苷机制"


def test_build_round_candidates_fail_closed_without_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(question_launch, "_approved_details", lambda _team_id: {})
    with server_operator_scope("u-1", roles=("operator",)):
        chain._append_jsonl(
            chain._storage_path(team_id),
            {
                "schemaVersion": 1,
                "recordKind": "hypothesis_candidate",
                "candidateId": "hyp-empty",
                "questionId": _QUESTION_ID,
                "statement": "",
                "rationale": "missing claim",
                "proposedBy": "operator",
                "meetingRoundId": "mr-x",
                "createdAt": "2026-08-19T00:00:00Z",
            },
        )
        review_meeting = {
            "question": _QUESTION_ID,
            "discussionItemRefs": ["hypothesis_candidate:hyp-empty"],
        }
        built = chain._build_round_candidates(team_id, review_meeting)
        assert built[0]["claim"] == ""
        generated = chain._generate_hypothesis_round(team_id, review_meeting)
        assert generated["status"] == "failed"


def test_auto_draft_runs_only_after_all_bound_rounds_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        # Inline executor finishes the chat before bind, so the completion
        # hook must not draft an unbound meeting.
        assert meeting["status"] == "open"
        room = chat_room_service.get_chat_room_detail(meeting["linkedChatRoomId"])
        assert room is not None
        bound_round_id = meeting["chatRoomRoundIds"][0]
        room_round = next(
            item
            for item in list(room.get("rounds") or [])
            if str(item.get("roundId") or "") == bound_round_id
        )
        drafted = meeting_runtime.maybe_auto_draft_after_chat_round(room, room_round)
        assert drafted is not None
        assert drafted["status"] == "awaiting_approval"
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        assert meeting["status"] == "awaiting_approval"
        assert meeting["digestDraft"]["contentHash"]


def test_approve_review_digest_without_evidence_requests_closes_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty digest (no evidence requests) must close through a legal
    decision. The UI's 确认并结束本轮 hit an invalid vocabulary word here and
    always failed while the round sat in awaiting_approval."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    from core.web.services.team_workflow import hypothesis_selection as selections

    def _plain_runner(participant, prompt, context):
        if "批评与修订" in str(prompt):
            return {"status": "completed", "raw_output": "pass", "summary": "pass"}
        role = str(participant.get("teamRole") or "participant")
        if role == "coordinator":
            return {
                "status": "completed",
                "raw_output": "AGREE: 本轮确认现有结论",
                "summary": "ok",
            }
        return {
            "status": "completed",
            "raw_output": "AGREE: hyp-a 的机制证据最完整",
            "summary": "ok",
        }

    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        recorded = selections.record_hypothesis_selection(
            team_id,
            {
                "program": "XH-202619",
                "theme": "cc-neuro-001",
                "campaign": "cc-campaign-neuro-001",
                "question": _QUESTION_ID,
                "branch": "main",
                "workflow": "hypothesis_first",
                "agentId": agent_ids[0],
                "mode": "dev",
                "questionId": _QUESTION_ID,
                "selectedCandidateIds": ["hyp-a", "hyp-b"],
                "decidedBy": agent_ids[0],
            },
            agent_runner=_plain_runner,
        )
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
        drafted = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert drafted["status"] == "awaiting_approval"
        assert not drafted["digestDraft"].get("evidenceRequests")

        approved = chain.approve_meeting_digest(
            team_id,
            meeting_id,
            closed_by=agent_ids[0],
            expected_digest_content_hash=drafted["digestDraft"]["contentHash"],
        )
        assert approved["meetingRound"]["status"] == "closed"
        decisions = approved.get("decisions") or []
        assert decisions, "closure must record the confirm decision"
        assert decisions[0]["decision"] == "close_round"
