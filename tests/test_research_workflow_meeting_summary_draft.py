"""Meeting summary-draft / approve-digest state machine (hypothesis-first).

Covers the P0/P1 server contract: bound-round gate, open→summarizing→
awaiting_approval recovery, same source-hash reuse, draft-error retry,
stale digest hash, generation candidate registration, and review
evidenceRequests → one collection request.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from core.research.workflow.contracts import ContractValidationError
from core.web.services import chat_room_service
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import question_launch
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)
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


def _mixed_source_type_evidence_runner(participant, prompt, context):
    result = _evidence_runner(participant, prompt, context)
    raw_output = str(result.get("raw_output") or "")
    if "EVIDENCE_REQUEST:" in raw_output:
        result = {
            **result,
            "raw_output": raw_output.replace(
                '"sourceTypes": ["paper"]',
                '"sourceTypes": ["paper", "reference"]',
            ),
        }
    return result


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


def test_summary_draft_concurrent_requests_share_one_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(meeting_runtime, "maybe_auto_draft_meeting", lambda *a, **k: None)
    agent_ids = [agents[role] for role in _ROLES]
    original = meeting_runtime.build_meeting_digest_draft
    build_calls = {"count": 0}
    caller_count = {"count": 0}
    build_calls_lock = threading.Lock()
    caller_count_lock = threading.Lock()
    both_callers_started = threading.Event()
    first_builder_started = threading.Event()
    release_builder = threading.Event()

    def counting_builder(*args, **kwargs):
        with build_calls_lock:
            build_calls["count"] += 1
            call_number = build_calls["count"]
        if call_number == 1:
            first_builder_started.set()
            assert both_callers_started.wait(timeout=5)
            assert release_builder.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(meeting_runtime, "build_meeting_digest_draft", counting_builder)

    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
    meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]

    def request_summary_draft() -> dict:
        with caller_count_lock:
            caller_count["count"] += 1
            if caller_count["count"] == 2:
                both_callers_started.set()
        with server_operator_scope("u-1", roles=("operator",)):
            return meeting_runtime.prepare_meeting_summary_draft(
                team_id, meeting_id, actor=agent_ids[0], force=False
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(request_summary_draft) for _ in range(2)]
        assert both_callers_started.wait(timeout=5)
        assert first_builder_started.wait(timeout=5)
        release_builder.set()
        results = [future.result(timeout=5) for future in futures]

    assert [result["status"] for result in results] == [
        "awaiting_approval",
        "awaiting_approval",
    ]
    assert len({result["digestDraft"]["contentHash"] for result in results}) == 1
    assert build_calls["count"] == 1
    with meeting_runtime._SUMMARY_DRAFT_LOCKS_GUARD:
        assert (team_id, meeting_id) not in meeting_runtime._SUMMARY_DRAFT_LOCKS


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


def test_prepare_generation_repairs_stale_empty_candidate_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )
    agent_ids = [agents[role] for role in _ROLES]

    def stale_drafter(meeting_round, source_messages):
        draft = meeting_runtime.build_meeting_digest_draft(meeting_round, source_messages)
        draft["proposedCandidates"] = []
        return draft

    with server_operator_scope("u-1", roles=("operator",)):
        opened = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )
        meeting_id = opened["meetingRound"]["meetingRoundId"]
        stale = meeting_runtime.prepare_meeting_summary_draft(
            team_id,
            meeting_id,
            actor=agent_ids[0],
            force=False,
            drafter=stale_drafter,
        )
        assert stale["digestDraft"]["proposedCandidates"] == []

        repaired = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )

    assert repaired["status"] == "awaiting_approval"
    assert repaired["digestDraft"]["proposedCandidates"]
    assert repaired["digestDraft"]["contentHash"] != stale["digestDraft"]["contentHash"]


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
            agent_runner=_mixed_source_type_evidence_runner,
        )
        # The selection now fans out into one room per candidate. This fixture
        # asks for evidence about hyp-b, so approve hyp-b's own review rather
        # than the primary (hyp-a) room.
        review = next(
            item
            for item in recorded["reviewMeeting"]["reviewMeetings"]
            if "hypothesis_candidate:hyp-b"
            in list(item["meetingRound"].get("discussionItemRefs") or [])
        )
        meeting_id = review["meetingRound"]["meetingRoundId"]
        drafted = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert drafted["status"] == "awaiting_approval"
        assert drafted["digestDraft"]["evidenceRequests"]
        assert drafted["digestDraft"]["evidenceRequests"][0]["searchEnvelope"][
            "sourceTypes"
        ] == ["paper"]
        assert drafted["digestDraft"]["validationErrors"] == [
            {
                "code": "search_source_types_dropped",
                "message": "已忽略不支持的 sourceTypes：reference",
            }
        ]
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
        assert drafted["digestDraft"]["evidenceRequests"] == []
        approved = chain.approve_meeting_digest(
            team_id,
            meeting_id,
            closed_by=agent_ids[0],
            expected_digest_content_hash=drafted["digestDraft"]["contentHash"],
        )
        assert approved["closed"] is False
        assert approved["status"] == "awaiting_approval"
        assert approved["validationErrors"] == drafted["digestDraft"]["validationErrors"]
        assert len(
            {
                (str(item.get("code") or ""), str(item.get("message") or ""))
                for item in approved["validationErrors"]
            }
        ) == len(approved["validationErrors"])
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        assert meeting["status"] == "awaiting_approval"
        assert collection_calls == []


def test_mixed_source_types_keep_valid_values_and_report_dropped_tokens() -> None:
    normalized, warnings = meeting_runtime.validate_evidence_request_draft(
        {
            "rationale": "需要补充同行评审论文。",
            "candidateRefs": ["hyp-a"],
            "evidenceRefs": ["evidence:review-gap"],
            "searchEnvelope": {
                "keywords": ["neuronal spike coding"],
                "sourceTypes": ["paper", "reference"],
                "evidenceLevels": ["peer_reviewed"],
            },
            "requirements": {"minEvidenceLevel": "medium"},
            "writebackPolicy": {},
        },
        {
            "meetingType": "hypothesis_review",
            "selectedCandidateIds": ["hyp-a"],
            "discussionItemRefs": ["hypothesis_candidate:hyp-a"],
        },
    )

    assert normalized is not None
    assert normalized["searchEnvelope"]["sourceTypes"] == ["paper"]
    assert warnings == [
        {
            "code": "search_source_types_dropped",
            "message": "已忽略不支持的 sourceTypes：reference",
        }
    ]


def test_all_unsupported_source_types_keep_evidence_request_blocked() -> None:
    normalized, errors = meeting_runtime.validate_evidence_request_draft(
        {
            "rationale": "需要补充资料。",
            "candidateRefs": ["hyp-a"],
            "searchEnvelope": {
                "keywords": ["neuronal spike coding"],
                "sourceTypes": ["reference"],
            },
        },
        {
            "meetingType": "hypothesis_review",
            "selectedCandidateIds": ["hyp-a"],
        },
    )

    assert normalized is None
    assert errors == [
        {
            "code": "search_source_types_invalid",
            "message": "sourceTypes 未包含支持的来源类型：reference",
        }
    ]


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


def _r5_freeform_messages(count: int = 9) -> list[dict]:
    speeches = [
        "hyp-a 的预测编码解释和已有 EEG 证据更吻合，建议优先验证。",
        "hyp-b 的泛化路径还不清楚，现在下结论过早。",
        "机制上更支持分层预测误差，而不是单一增益控制。",
        "现有数据只能排除最粗糙的对照，还不能定论。",
        "如果 hyp-a 成立，睡眠剥夺后预测误差应系统性增大。",
        "我担心样本偏差会把 hyp-a 推得太高。",
        "可以把下一轮重点放在可证伪预测而不是再讲一遍机制。",
        "知识缺口主要在跨被试泛化，而不是概念本身。",
        "综合来看我仍倾向 hyp-a，但必须保留 hyp-b 作为对照。",
    ]
    return [
        {
            "status": "completed",
            "content": speeches[index % len(speeches)],
            "roomId": "room-r5",
            "roundId": "round-r5",
            "messageId": f"msg-{index + 1}",
            "speakerTitle": f"A{index + 1:03d}",
            "participantId": f"agent-{index + 1}",
        }
        for index in range(count)
    ]


def test_unstructured_fallback_from_r5_shaped_freeform_speeches() -> None:
    messages = _r5_freeform_messages()
    markers = meetings.extract_discussion_markers(messages)
    assert markers["agreements"] == []
    assert markers["disagreements"] == []
    draft = meeting_runtime.build_meeting_digest_draft(
        {
            "meetingRoundId": "mr-r5",
            "meetingType": "hypothesis_review",
            "agenda": ["评审入选候选"],
            "discussionItemRefs": ["hypothesis_candidate:hyp-a"],
            "participants": [f"agent-{index}" for index in range(1, 10)],
            "chatRoomRoundIds": ["round-r5"],
        },
        messages,
    )
    assert len(draft["agreements"]) == 9
    for item in draft["agreements"]:
        assert item["derivedFrom"] == "unstructured"
        assert item["sourceMessageRefs"]
        assert item["sourceMessageRefs"][0].startswith("room-r5/round-r5/")
        assert item["text"]
    assert "自由格式发言" in draft["summary"]


def test_unstructured_fallback_does_not_override_markers() -> None:
    messages = [
        {
            "status": "completed",
            "content": "AGREE: hyp-a 机制证据最完整\nDISAGREE: hyp-b 泛化不足",
            "roomId": "room-1",
            "roundId": "round-1",
            "messageId": "msg-1",
            "speakerTitle": "A001",
        }
    ]
    extracted = meetings.extract_discussion_markers(messages)
    fallback = meetings.apply_unstructured_digest_fallback(extracted, messages)
    assert fallback["agreements"] == ["hyp-a 机制证据最完整"]
    assert fallback["disagreements"][0]["issue"] == "hyp-b 泛化不足"


def test_candidate_markers_accept_common_markdown_emphasis() -> None:
    messages = [
        {
            "status": "completed",
            "content": (
                "**CANDIDATE: 2 | 极端嗜盐菌可能存在未鉴明的色素合成机制** "
                "| 宏基因组与基因敲除可证伪\n"
                "- **CANDIDATE: 3 | 热液嗜热菌可能产生新型热稳定色素 "
                "| LC-MS 与 P450 敲除可证伪**"
            ),
            "roomId": "room-markdown",
            "roundId": "round-markdown",
            "messageId": "msg-markdown",
            "speakerTitle": "A003",
        }
    ]

    extracted = meetings.extract_discussion_markers(messages)

    assert extracted["proposedCandidates"] == [
        {
            "candidateId": "2",
            "statement": "极端嗜盐菌可能存在未鉴明的色素合成机制",
            "rationale": "宏基因组与基因敲除可证伪",
            "proposedBy": "A003",
        },
        {
            "candidateId": "3",
            "statement": "热液嗜热菌可能产生新型热稳定色素",
            "rationale": "LC-MS 与 P450 敲除可证伪",
            "proposedBy": "A003",
        },
    ]


def test_candidate_generation_digest_reports_proposed_candidate_count() -> None:
    messages = [
        {
            "status": "completed",
            "content": (
                "CANDIDATE: 1 | 候选一 | 理由一\n"
                "CANDIDATE: 2 | 候选二 | 理由二"
            ),
            "roomId": "room-generation",
            "roundId": "round-generation",
            "messageId": "message-generation",
            "speakerTitle": "A001",
        }
    ]
    draft = meeting_runtime.build_meeting_digest_draft(
        {
            "meetingRoundId": "mr-generation",
            "meetingType": meeting_runtime.CANDIDATE_GENERATION_MEETING_TYPE,
            "agenda": ["提出候选"],
            "discussionItemRefs": [],
            "participants": ["a", "b", "c", "d"],
            "chatRoomRoundIds": ["round-generation"],
        },
        messages,
    )

    assert len(draft["proposedCandidates"]) == 2
    assert "候选生成会议 mr-generation" in draft["summary"]
    assert "围绕 2 个候选" in draft["summary"]
    assert "0 个入选候选" not in draft["summary"]


def test_empty_digest_with_completed_speech_is_blocked() -> None:
    meeting_round = {"meetingType": "hypothesis_review"}
    messages = [
        {
            "status": "completed",
            "content": "free form opinion",
            "roomId": "r",
            "roundId": "rd",
            "messageId": "m1",
        }
    ]
    empty_draft = {
        "summary": "x",
        "agreements": [],
        "disagreements": [],
        "actionItems": [],
        "knowledgeCandidates": [],
        "evidenceRequests": [],
        "sourceMessageRefs": ["r/rd/m1"],
    }
    with pytest.raises(ContractValidationError, match="纪要未捕获讨论内容"):
        meetings.assert_review_digest_captured_discussion(
            meeting_round, empty_draft, messages
        )


def test_empty_discussion_does_not_fabricate_unstructured_entries() -> None:
    messages = [
        {
            "status": "completed",
            "content": "pass",
            "roomId": "r",
            "roundId": "rd",
            "messageId": "m1",
        }
    ]
    fallback = meetings.apply_unstructured_digest_fallback(
        meetings.extract_discussion_markers(messages), messages
    )
    assert fallback["agreements"] == []
    meeting_round = {
        "meetingRoundId": "mr-empty",
        "meetingType": "hypothesis_review",
        "agenda": [],
        "discussionItemRefs": [],
        "participants": ["a"],
        "chatRoomRoundIds": ["rd"],
    }
    draft = meeting_runtime.build_meeting_digest_draft(meeting_round, messages)
    assert draft["agreements"] == []
    meetings.assert_review_digest_captured_discussion(meeting_round, draft, messages)


def test_prepare_summary_blocks_zero_completed_speeches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(meeting_runtime, "maybe_auto_draft_meeting", lambda *a, **k: None)
    from core.web.services.team_workflow import hypothesis_selection as selections

    def _pass_only(participant, prompt, context):
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}

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
            agent_runner=_pass_only,
        )
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
        result = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert result["status"] == "blocked"
        assert result["blocker"]["code"] == "discussion_has_no_completed_messages"


def test_prepare_summary_draft_persists_unstructured_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(meeting_runtime, "maybe_auto_draft_meeting", lambda *a, **k: None)
    from core.web.services.team_workflow import hypothesis_selection as selections

    def _freeform(participant, prompt, context):
        if "批评与修订" in str(prompt):
            return {"status": "completed", "raw_output": "pass", "summary": "pass"}
        return {
            "status": "completed",
            "raw_output": "我认为 hyp-a 更值得进入有界验证，现有对照还不能排除 hyp-b。",
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
            agent_runner=_freeform,
        )
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
        drafted = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        agreements = drafted["digestDraft"]["agreements"]
        assert agreements
        assert all(
            isinstance(item, dict) and item.get("derivedFrom") == "unstructured"
            for item in agreements
        )
        assert all(item.get("sourceMessageRefs") for item in agreements)


def test_approve_empty_digest_with_completed_speech_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(meeting_runtime, "maybe_auto_draft_meeting", lambda *a, **k: None)
    from core.web.services.team_workflow import hypothesis_selection as selections

    def _empty_drafter(meeting_round, source_messages):
        refs = [
            meetings.message_source_ref(message)
            for message in source_messages
            if str(message.get("status") or "").strip().lower() == "completed"
            and not meetings.is_pass_message(message)
        ]
        return {
            "summary": "empty capture",
            "agendaSummary": "x",
            "discussionTopics": [],
            "agreements": [],
            "disagreements": [],
            "actionItems": [],
            "risks": [],
            "blockers": [],
            "knowledgeCandidates": [],
            "proposedCandidates": [],
            "evidenceRequests": [],
            "validationErrors": [],
            "sourceMessageRefs": refs,
        }

    def _freeform(participant, prompt, context):
        if "批评与修订" in str(prompt):
            return {"status": "completed", "raw_output": "pass", "summary": "pass"}
        return {
            "status": "completed",
            "raw_output": "自由格式评审意见，没有使用标记。",
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
            agent_runner=_freeform,
        )
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
        drafted = meeting_runtime.prepare_meeting_summary_draft(
            team_id,
            meeting_id,
            actor=agent_ids[0],
            force=False,
            drafter=_empty_drafter,
        )
        assert drafted["digestDraft"]["agreements"] == []
        with pytest.raises(ContractValidationError, match="纪要未捕获讨论内容"):
            chain.approve_meeting_digest(
                team_id,
                meeting_id,
                closed_by=agent_ids[0],
                expected_digest_content_hash=drafted["digestDraft"]["contentHash"],
            )


# ---------------------------------------------------------------------------
# SCI-096: a hung review-profile LLM call must fail structured and bounded
# instead of pinning the meeting in summarizing while holding the summary
# lock; the retry path regenerates the digest from the bound source messages.
# ---------------------------------------------------------------------------


_FAKE_REVIEW_LLM = {
    "client": object(),
    "profileId": "primary",
    "modelId": "fake-review-model",
}


class _FakeLLMResponse:
    def __init__(self, content: str):
        self.content = content


def _digest_llm_payload() -> str:
    return json.dumps(
        {
            "summary": "评审完成，倾向候选 A。",
            "agendaSummary": "评审候选 A/B",
            "agreements": ["候选 A 更契合赛题"],
            "disagreements": [],
            "actionItems": [],
            "risks": [],
            "knowledgeCandidates": [],
            "proposedCandidates": [],
            "evidenceRequests": [],
        },
        ensure_ascii=False,
    )


def test_summary_draft_llm_hang_times_out_and_stays_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time as time_module

    from core.web.services.team_workflow import llm_review_runners

    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(meeting_runtime, "maybe_auto_draft_meeting", lambda *a, **k: None)
    agent_ids = [agents[role] for role in _ROLES]

    release = threading.Event()

    def hanging_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        # Wedged provider transport: blocks until the test releases it.
        release.wait(timeout=15)
        return _FakeLLMResponse("{}")

    monkeypatch.setattr(
        llm_review_runners, "resolve_review_llm", lambda: dict(_FAKE_REVIEW_LLM)
    )
    monkeypatch.setattr(llm_review_runners, "invoke_llm", hanging_invoke_llm)
    monkeypatch.setattr(
        llm_review_runners, "review_llm_call_timeout_seconds", lambda: 0.3
    )

    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]

        started = time_module.monotonic()
        failed = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        elapsed = time_module.monotonic() - started

        assert elapsed < 10, "a hung LLM call must not block the summary draft"
        assert failed["status"] == "summarizing"
        assert failed["summaryDraftError"]["code"] == "summary_draft_timeout"
        assert failed["summaryDraftError"]["remediationLabel"] == "重试生成纪要"
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        assert meeting["status"] == "summarizing"
        assert meeting["summaryDraftError"]["code"] == "summary_draft_timeout"
        # The per-meeting summary lock must not outlive the timed-out attempt.
        with meeting_runtime._SUMMARY_DRAFT_LOCKS_GUARD:
            assert (team_id, meeting_id) not in meeting_runtime._SUMMARY_DRAFT_LOCKS

        # Retry path regenerates the digest from the existing source messages
        # without reopening the discussion.
        release.set()

        def good_invoke_llm(client, messages, tools=None, context=None, **kwargs):
            return _FakeLLMResponse(_digest_llm_payload())

        monkeypatch.setattr(llm_review_runners, "invoke_llm", good_invoke_llm)
        retried = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert retried["status"] == "awaiting_approval"
        assert retried["digestDraft"]["summary"] == "评审完成，倾向候选 A。"
        assert not retried.get("summaryDraftError")
        meeting = meetings.get_meeting_round(team_id, meeting_id)["meetingRound"]
        assert meeting["status"] == "awaiting_approval"
        assert not meeting.get("summaryDraftError")
        # Recovery reused the bound discussion: no new chat room rounds.
        assert len(meeting.get("chatRoomRoundIds") or []) == len(
            recorded["reviewMeeting"]["meetingRound"].get("chatRoomRoundIds") or []
        )


def test_summary_draft_timeout_error_maps_through_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow import llm_review_runners

    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    monkeypatch.setattr(meeting_runtime, "maybe_auto_draft_meeting", lambda *a, **k: None)
    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]

        def timed_out_builder(*_args, **_kwargs):
            raise llm_review_runners.ReviewLLMTimeoutError(
                purpose="meeting_digest", timeout_seconds=180.0
            )

        monkeypatch.setattr(meeting_runtime, "build_meeting_digest_draft", timed_out_builder)
        failed = meeting_runtime.prepare_meeting_summary_draft(
            team_id, meeting_id, actor=agent_ids[0], force=False
        )
        assert failed["status"] == "summarizing"
        assert failed["summaryDraftError"]["code"] == "summary_draft_timeout"
        assert "180" in failed["summaryDraftError"]["message"]
        with meeting_runtime._SUMMARY_DRAFT_LOCKS_GUARD:
            assert (team_id, meeting_id) not in meeting_runtime._SUMMARY_DRAFT_LOCKS
