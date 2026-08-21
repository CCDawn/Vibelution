"""HF-4 hypothesis-first orchestration chain integration tests.

End-to-end DEV fixture chain: hypothesis selection -> first review meeting
auto-opens (background wiring, room round <-> meetingRoundId two-way binding)
-> closure carrying a ``request_new_evidence`` decision with a searchEnvelope
-> stage-1 collection ``ensure`` through the existing facade (call evidence)
-> child collection handoff -> parent run ``hypothesis_design`` readiness
re-check and resume -> next review meeting auto-opens with continuous lineage.

Also covers: missing searchEnvelope never triggers collection and keeps
``source_finding`` blocked; an unconverged latest round blocks
``hypothesis_design``; the round budget forces a manual decision; interruption
recovery keeps rounds and stays idempotent.

All discussion content comes from fake runners and the collection run creation
is faked at ``source_collection.runs.start_source_collection_run``; no real
model, network, or research activity is involved.
"""

from __future__ import annotations

import json

from core.infrastructure import developer_sandbox
from concurrent.futures import Future
from pathlib import Path

import pytest

from core.research.workflow.contracts import (
    ActorRef,
    CommandRequest,
    WorkflowCommandKind,
)
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    session_service,
    team_service,
)
from core.web.services.team_workflow import hypothesis_rounds as hrounds
from core.web.services.team_workflow import hypothesis_selection as selections
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow import personal_memory_candidates as memories
from core.web.services.team_workflow import research_templates as templates
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import question_launch
from core.web.services.team_workflow.research_runtime.command_service import (
    NodeNotReadyError,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)
from core.web.services.team_workflow.research_runtime.runtime_factory import (
    build_workflow_runtime,
)
from core.web.services.team_workflow.source_collection import (
    runs as collection_runs,
)

from tests._support.team_workflow.helpers import (
    _use_fake_local_research_config,
    _use_tmp_project_root,
)
from tests._support.workflow_ledger_helpers import (
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_run_record,
)

_ROLES = ("coordinator", "researcher")
_QUESTION_ID = "SCI-096"
_CANDIDATE_IDS = ("hyp-a", "hyp-b", "hyp-c")
_RUN_ID = "run-hf4-parent"
_FIXED_NOW_MS = 1_750_000_000_000


class _InlineExecutor:
    """Run submitted chat-room rounds synchronously (DEV tests only)."""

    def __init__(self) -> None:
        self.submitted: list[dict] = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append({"fn": fn, "args": args, "kwargs": kwargs})
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - surfaced via future
            future.set_exception(exc)
        return future


def _hf_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memories, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(selections, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(hrounds, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(templates, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", _InlineExecutor())
    agents: dict[str, str] = {}
    for role in (*_ROLES, "experiment_planner"):
        agent = agent_directory_service.create_agent_instance(
            display_name=f"HF4 {role}",
            role_key=role,
            created_by="hf4-test",
        )
        session_service.ensure_agent_direct_session(
            agent_id=agent["agentId"], title=f"HF4 {role}"
        )
        agents[role] = agent["agentId"]
    team_id = team_service.create_team(
        name="HF-4 假说先行团队",
        purpose="challenge-workflow-hf4",
        members=[{"agentId": agents[role], "role": role} for role in _ROLES],
    )["teamId"]
    return team_id, agents


def _patch_approved_question(
    monkeypatch: pytest.MonkeyPatch, *, hypotheses: list[dict] | None = None
) -> None:
    detail = {
        "teamId": "hf4",
        "questionId": _QUESTION_ID,
        "selectedRunId": "stage1-sci-096-v1",
        "record": {
            "questionId": _QUESTION_ID,
            "runId": "stage1-sci-096-v1",
            "schemaVersion": 2,
            "submissionEligible": True,
            "status": "approved",
            "humanGates": {
                "allApproved": True,
                "decisions": {
                    "H1_problem_understanding": "approved",
                    "H2_hypothesis_selection": "approved",
                    "H3_research_plan": "approved",
                    "H4_external_output": "approved",
                },
            },
            "validation": {
                "schemaValidation": "passed",
                "citationValidation": "passed",
                "officialModelCall": True,
            },
        },
        "output": {
            "schema_version": 2,
            "identity": {
                "catalog_id": "science-125-questions-2021",
                "question_id": _QUESTION_ID,
                "question_en": "Fixture question",
            },
            "hypotheses": hypotheses
            if hypotheses is not None
            else [
                {"hypothesis_id": candidate_id, "statement": f"candidate {candidate_id}"}
                for candidate_id in _CANDIDATE_IDS
            ],
            "selection": {"selected_hypothesis_id": _CANDIDATE_IDS[0]},
            "review": {"human_review_status": "passed"},
            "submission": {"eligible": True},
        },
        "artifact": {"sha256": "b" * 64, "immutable": True},
    }
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {
            "completedQuestionIds": [_QUESTION_ID],
            "completedQuestionResults": [dict(detail["record"])],
        },
    )
    monkeypatch.setattr(
        question_launch,
        "get_challenge_question_run_detail",
        lambda _team_id, requested, *, run_id="": detail,
    )


def _scope_fields(agent_id: str) -> dict[str, str]:
    return {
        "program": "XH-202619",
        "theme": "cc-neuro-001",
        "campaign": "cc-campaign-neuro-001",
        "question": _QUESTION_ID,
        "branch": "main",
        "workflow": "hypothesis_first",
        "agentId": agent_id,
        "mode": "dev",
    }


def _selection_payload(agent_id: str, **overrides):
    payload = {
        **_scope_fields(agent_id),
        "questionId": _QUESTION_ID,
        "selectedCandidateIds": ["hyp-a", "hyp-b"],
        "decidedBy": agent_id,
    }
    payload.update(overrides)
    return payload


def _marker_runner(participant, prompt, context):
    """Round 1 carries the DEV fixture markers; follow-up critique rounds pass."""
    if "批评与修订" in str(prompt):
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}
    role = str(participant.get("teamRole") or "participant")
    if role == "coordinator":
        content = "AGREE: hyp-a 的机制证据最完整，进入有界验证"
    else:
        content = (
            "DISAGREE: hyp-b 的泛化证据不足\n"
            "RISK: 数据集偏差尚未评估\n"
            "ACTION: researcher | 补充 hyp-b 的消融实验证据\n"
            "KNOWLEDGE: 预测编码层级最新综述"
        )
    return {"status": "completed", "raw_output": content, "summary": "ok"}


def _fake_collection_runs(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake_start(team_id, payload=None):
        calls.append({"teamId": team_id, "payload": dict(payload or {})})
        return {"runId": f"dprun-hf4-{len(calls)}", "status": "accepted"}

    monkeypatch.setattr(collection_runs, "start_source_collection_run", fake_start)
    return calls


def _seed_question_reset_artifacts(team_id: str, question_id: str) -> dict[str, str]:
    """Seed only the durable hypothesis-first artifacts owned by one question."""
    suffix = question_id.lower()
    meeting_id = f"meeting-{suffix}"
    selection_id = f"selection-{suffix}"
    candidate_id = f"candidate-{suffix}"
    round_id = f"round-{suffix}"
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.CANDIDATE_KIND,
            "candidateId": candidate_id,
            "questionId": question_id,
            "statement": f"{question_id} candidate",
            "meetingRoundId": meeting_id,
        },
    )
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.COLLECTION_REQUEST_KIND,
            "requestId": f"request-{suffix}",
            "questionId": question_id,
            "meetingRoundId": meeting_id,
            "status": "completed",
        },
    )
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.REVIEW_ROUND_LINK_KIND,
            "linkId": f"link-{suffix}",
            "questionId": question_id,
            "meetingRoundId": meeting_id,
            "selectionId": selection_id,
            "roundIndex": 1,
        },
    )
    selections._append_jsonl(
        selections._storage_path(team_id),
        {"schemaVersion": 1, "selectionId": selection_id, "questionId": question_id},
    )
    meetings._append_jsonl(
        meetings._rounds_path(team_id),
        {
            "schemaVersion": 2,
            "meetingRoundId": meeting_id,
            "question": question_id,
            "meetingType": "hypothesis_review",
            "status": "closed",
        },
    )
    meetings._append_jsonl(
        meetings._digests_path(team_id),
        {"schemaVersion": 2, "digestId": f"digest-{suffix}", "meetingRoundId": meeting_id},
    )
    meetings._append_jsonl(
        meetings._decisions_path(team_id),
        {"schemaVersion": 2, "decisionId": f"decision-{suffix}", "meetingRoundId": meeting_id},
    )
    hrounds._append_jsonl(
        hrounds._storage_path(team_id),
        {
            "schemaVersion": 1,
            "roundId": round_id,
            "status": "closed",
            "meetingRefs": [{"kind": "meeting_round", "id": meeting_id}],
        },
    )
    return {
        "candidateId": candidate_id,
        "meetingId": meeting_id,
        "roundId": round_id,
        "selectionId": selection_id,
    }


def test_question_reset_clears_only_the_target_questions_closed_hypothesis_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    target = _seed_question_reset_artifacts(team_id, _QUESTION_ID)
    other = _seed_question_reset_artifacts(team_id, "SCI-097")

    preview = chain.preview_question_reset(team_id, _QUESTION_ID)

    assert preview["canReset"] is True
    assert preview["impact"] == {
        "candidateCount": 1,
        "selectionCount": 1,
        "meetingCount": 1,
        "hypothesisRoundCount": 1,
        "collectionRequestCount": 1,
        "collectionRunCount": 0,
    }

    result = chain.reset_question_chain(
        team_id,
        _QUESTION_ID,
        confirmation_question_id=_QUESTION_ID,
    )

    assert result["removed"] == preview["impact"]
    assert result["nextAction"] == {
        "targetNodeId": "hf_generation",
        "label": "生成候选假说",
    }
    assert chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)["candidates"] == []
    assert selections.list_hypothesis_selections(team_id, question_id=_QUESTION_ID)["selections"] == []
    assert chain.list_collection_requests(team_id, question_id=_QUESTION_ID)["requests"] == []
    assert [item["meetingRoundId"] for item in meetings.list_meeting_rounds(team_id)["meetings"]] == [other["meetingId"]]
    assert [item["roundId"] for item in hrounds.list_hypothesis_rounds(team_id)["rounds"]] == [other["roundId"]]

    assert chain.list_hypothesis_candidates(team_id, question_id="SCI-097")["candidates"][0]["candidateId"] == other["candidateId"]
    assert selections.list_hypothesis_selections(team_id, question_id="SCI-097")["selections"][0]["selectionId"] == other["selectionId"]
    assert target["meetingId"] != other["meetingId"]
    assert target["roundId"] != other["roundId"]


def test_question_reset_refuses_active_discussion_and_mismatched_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    target = _seed_question_reset_artifacts(team_id, _QUESTION_ID)
    meetings._append_jsonl(
        meetings._rounds_path(team_id),
        {
            "schemaVersion": 2,
            "meetingRoundId": target["meetingId"],
            "question": _QUESTION_ID,
            "meetingType": "hypothesis_review",
            "status": "open",
        },
    )

    preview = chain.preview_question_reset(team_id, _QUESTION_ID)

    assert preview["canReset"] is False
    assert "进行中的讨论" in preview["blockingReason"]
    with pytest.raises(chain.HypothesisFirstChainError, match="进行中的讨论"):
        chain.reset_question_chain(
            team_id,
            _QUESTION_ID,
            confirmation_question_id=_QUESTION_ID,
        )
    with pytest.raises(chain.HypothesisFirstChainError, match="输入当前题号"):
        chain.reset_question_chain(
            team_id,
            _QUESTION_ID,
            confirmation_question_id="SCI-097",
        )
    assert chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)["candidates"]


def test_question_reset_keeps_source_collection_untouched_if_ledger_rewrite_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    _seed_question_reset_artifacts(team_id, _QUESTION_ID)
    source_cleanup_calls: list[set[str]] = []

    def should_not_run_source_cleanup(_team_id: str, run_ids: set[str]) -> dict[str, object]:
        source_cleanup_calls.append(set(run_ids))
        return {}

    monkeypatch.setattr(
        collection_runs,
        "reset_source_collection_runs_for_question",
        should_not_run_source_cleanup,
    )
    monkeypatch.setattr(
        chain,
        "_rewrite_jsonl",
        lambda _path, _records: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(chain.HypothesisFirstChainError, match="原数据已尝试恢复"):
        chain.reset_question_chain(
            team_id,
            _QUESTION_ID,
            confirmation_question_id=_QUESTION_ID,
        )

    assert source_cleanup_calls == []
    assert chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)["candidates"]


def test_question_reset_restores_hypothesis_records_if_source_cleanup_late_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    _seed_question_reset_artifacts(team_id, _QUESTION_ID)

    def late_source_blocker(_team_id: str, _run_ids: set[str]) -> dict[str, object]:
        raise ValueError("资料运行状态已变化")

    monkeypatch.setattr(
        collection_runs,
        "reset_source_collection_runs_for_question",
        late_source_blocker,
    )

    with pytest.raises(ValueError, match="资料运行状态已变化"):
        chain.reset_question_chain(
            team_id,
            _QUESTION_ID,
            confirmation_question_id=_QUESTION_ID,
        )

    assert chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)["candidates"]


def _build_runtime(tmp_path: Path):
    return build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "checkpoints.sqlite",
        domain_overrides={
            "knowledge_package": lambda team_id, run_id: {
                "teamId": team_id,
                "sourceCollectionRunId": "dprun-hf4-1",
                "accepted": True,
                "knowledgeItems": [{"knowledgeItemId": "ki-1", "contentHash": "b" * 64}],
            },
        },
    )


def _seed_parent_run(runtime, team_id: str, planner_agent_id: str) -> None:
    input_snapshot = {
        "teamId": team_id,
        "projectId": "challenge-sci-096",
        "questionId": _QUESTION_ID,
        "workflowVersionId": "challenge-cup-research-v2.1.0",
        "researchBriefHash": "b" * 64,
        "datasetRefs": [],
        "metricContract": {},
        "constraintSnapshot": {},
        "competitionRuleRef": "rule",
        "competitionRuleVersion": "1",
        "trackAndRubricSnapshot": {},
        "researchObjectiveContract": {
            "question": "How do spike trains encode information?",
            "hypothesisFirst": True,
        },
        "sourcePolicy": {},
        "budgetPolicy": {
            "stageBudgets": {
                "knowledge_collection": {"tokens": 250000, "toolCalls": 300},
                "experiment_design": {"tokens": 250000, "toolCalls": 300},
            }
        },
        "stopPolicy": {},
        "environmentSnapshotRef": "env-1",
        "modelRoutingPolicy": {},
        "evaluationContract": {},
        "agentBindingSnapshot": [
            {
                "snapshotId": "snap:hf4:source_finding",
                "nodeId": "source_finding",
                "agentId": planner_agent_id,
                "roleKey": "source_finder",
            },
            {
                "snapshotId": "snap:hf4:hypothesis_design",
                "nodeId": "hypothesis_design",
                "agentId": planner_agent_id,
                "roleKey": "experiment_planner",
            },
        ],
        "createdBy": "u-1",
        "createdAt": "2026-08-18T00:00:00Z",
        "snapshotHash": "c" * 64,
    }
    record = build_run_record(
        run_id=_RUN_ID,
        team_id=team_id,
        last_event_sequence=1,
        input_snapshot_hash="c" * 64,
        thread_id=_RUN_ID,
    )
    record = record.__class__(
        **{
            **record.__dict__,
            "project_id": "challenge-sci-096",
            "question_id": _QUESTION_ID,
            "input_snapshot_json": json.dumps(input_snapshot, ensure_ascii=False),
        }
    )

    def mutate(uow):
        uow.repository.insert_run(record)
        uow.repository.insert_event(
            build_event_record(
                sequence=1,
                run_id=_RUN_ID,
                event_type="run_created",
                event_id="evt-created-hf4",
            )
        )
        # The parent's own knowledge gate already completed upstream: a
        # succeeded knowledge_handoff attempt plus an accepted handoff into
        # hypothesis_design exist in the ledger.
        uow.repository.insert_command(
            build_command_record(
                "cmd-hf4-knowledge",
                run_id=_RUN_ID,
                team_id=team_id,
                node_id="knowledge_handoff",
                command_kind="resolve_human_task",
                idempotency_key="hf4:seed-knowledge",
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                "nr-hf4-knowledge_handoff-a1",
                run_id=_RUN_ID,
                node_id="knowledge_handoff",
                actor_kind="human",
                status="succeeded",
                command_id="cmd-hf4-knowledge",
            )
        )
        uow.repository.insert_handoff(
            handoff_id="ho-hf4-knowledge",
            run_id=_RUN_ID,
            edge_id="knowledge_handoff->hypothesis_design",
            from_node_run_id="nr-hf4-knowledge_handoff-a1",
            to_node_id="hypothesis_design",
            to_node_run_id=None,
            gate_kind="knowledge_package",
            input_snapshot_hash="c" * 64,
            offered_at_ms=_FIXED_NOW_MS,
        )
        uow.repository.update_handoff_status(
            "ho-hf4-knowledge", "waiting_human", _FIXED_NOW_MS + 1
        )
        uow.repository.update_handoff_status(
            "ho-hf4-knowledge", "accepted", _FIXED_NOW_MS + 2
        )

    runtime.store.submit(mutate, force_flush=True).result(timeout=10)


def _evaluate(runtime, team_id: str, node_id: str):
    return runtime.readiness.evaluate(
        team_id=team_id,
        run_id=_RUN_ID,
        node_id=node_id,
        context=runtime.readiness_context,
        use_cache=False,
    )


def _blocker_codes(readiness) -> set[str]:
    return {blocker.code for blocker in readiness.blockers}


def _envelope_decision(agent_id: str, **overrides) -> dict:
    decision = {
        "decision": "request_new_evidence",
        "rationale": "hyp-b 的泛化证据不足，需要按信封补充搜集。",
        "decidedBy": agent_id,
        "candidateRefs": ["hyp-b"],
        "evidenceRefs": ["evidence:review-matrix-1"],
        "status": "adopted",
        "searchEnvelope": {
            "keywords": ["predictive coding", "spike train coding"],
            "sourceTypes": ["paper"],
            "evidenceLevels": ["peer_reviewed"],
        },
        "requirements": {"minEvidenceLevel": "medium", "completeness": "stage-one"},
        "writebackPolicy": {},
    }
    decision.update(overrides)
    return decision


def _select_decision(agent_id: str, **overrides) -> dict:
    decision = {
        "decision": "select_candidate",
        "rationale": "hyp-a 证据最完整，收敛进入实验设计。",
        "decidedBy": agent_id,
        "candidateRefs": ["hyp-a"],
        "evidenceRefs": ["evidence:review-matrix-2"],
        "status": "adopted",
    }
    decision.update(overrides)
    return decision


def _closure_payload(agent_ids: list[str], decisions: list[dict], **overrides) -> dict:
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


def _drive_to_awaiting_approval(team_id: str, meeting_round_id: str, actor: str) -> None:
    drafted = meeting_runtime.prepare_meeting_summary_draft(
        team_id, meeting_round_id, actor=actor, force=False
    )
    assert drafted["status"] == "awaiting_approval"


def _freeze_template_baseline(team_id: str, agent_id: str) -> dict:
    created = templates.create_template_baseline(
        team_id,
        {
            **_scope_fields(agent_id),
            "templateId": "hypothesis-design-template",
            "approvedBy": agent_id,
            "approvalRef": "approval:hf4-template-1",
            "content": {"sections": ["claim", "variables", "falsification"]},
        },
    )
    assert created["baseline"]["status"] == "frozen"
    return created["baseline"]


def _open_first_meeting(team_id: str, agent_ids: list[str]) -> dict:
    recorded = selections.record_hypothesis_selection(
        team_id,
        _selection_payload(agent_ids[0]),
        agent_runner=_marker_runner,
    )
    assert recorded["status"] == "created"
    review = recorded["reviewMeeting"]
    assert review["status"] == "opened"
    return recorded


def test_selection_review_prompt_hydrates_canonical_candidate_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(
        monkeypatch,
        hypotheses=[
            {
                "hypothesis_id": "hyp-a",
                "statement": "canonical statement a",
                "mechanism": "canonical mechanism a",
            },
            {
                "hypothesis_id": "hyp-b",
                "statement": "canonical statement b",
                "mechanism": "canonical mechanism b",
            },
        ],
    )
    prompts: list[str] = []

    def capture_runner(participant, prompt, context):
        prompts.append(str(prompt))
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}

    recorded = selections.record_hypothesis_selection(
        team_id,
        _selection_payload(agents["coordinator"]),
        agent_runner=capture_runner,
    )

    assert recorded["reviewMeeting"]["status"] == "opened"
    assert prompts
    assert all("canonical statement a" in prompt for prompt in prompts)
    assert all("canonical mechanism a" in prompt for prompt in prompts)
    assert all("canonical statement b" in prompt for prompt in prompts)
    assert all("canonical mechanism b" in prompt for prompt in prompts)


def _close_first_meeting_with_envelope(
    team_id: str, agent_ids: list[str], meeting_round_id: str, runtime
) -> dict:
    _drive_to_awaiting_approval(team_id, meeting_round_id, agent_ids[0])
    return chain.close_review_meeting(
        team_id,
        meeting_round_id,
        _closure_payload(agent_ids, [_envelope_decision(agent_ids[0])]),
        runtime=runtime,
    )


def test_hypothesis_first_chain_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    collection_calls = _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            # 0. Before any selection: both chain gates block.
            finding = _evaluate(runtime, team_id, "source_finding")
            assert not finding.ready
            assert "hypothesis_first_meeting_open" in _blocker_codes(finding)
            design = _evaluate(runtime, team_id, "hypothesis_design")
            design_codes = _blocker_codes(design)
            assert "hypothesis_round_unconverged" in design_codes
            assert "template_baseline_missing" in design_codes

            # 1. Selection persists -> first review meeting auto-opens in
            #    background mode with the room round <-> meetingRoundId binding.
            recorded = _open_first_meeting(team_id, agent_ids)
            review = recorded["reviewMeeting"]
            assert review["discussion"]["background"] is True
            meeting = review["meetingRound"]
            first_meeting_id = meeting["meetingRoundId"]
            assert meeting["meetingType"] == "hypothesis_review"
            assert meeting["linkedChatRoomId"] == review["roomId"]
            assert meeting["chatRoomRoundIds"] == [review["roundId"]]
            room_detail = chat_room_service.get_chat_room_detail(review["roomId"])
            bound_round = next(
                item for item in room_detail["rounds"] if item["roundId"] == review["roundId"]
            )
            assert bound_round["config"]["meetingRoundId"] == first_meeting_id
            assert bound_round["status"] == "completed"

            # 2. The open first discussion still blocks source_finding.
            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" in _blocker_codes(finding)

            # 3. Closing with a searchEnvelope decision triggers stage-1
            #    collection through the facade exactly once.
            closed = _close_first_meeting_with_envelope(
                team_id, agent_ids, first_meeting_id, runtime
            )
            assert closed["meetingRound"]["status"] == "closed"
            requests = closed["collection"]["requests"]
            assert len(requests) == 1
            request = requests[0]
            assert request["status"] == "pending"
            assert request["collectionRunId"] == "dprun-hf4-1"
            assert request["meetingRoundId"] == first_meeting_id
            assert len(collection_calls) == 1
            ensure_scope = collection_calls[0]["payload"]["scope"]
            assert ensure_scope["researchScopeHash"] == meeting["scopeHash"]
            assert ensure_scope["searchEnvelope"]["keywords"] == [
                "predictive coding",
                "spike train coding",
            ]

            # 3b. The closure auto-generates a closed HypothesisRound through
            #     the HF-3 executor: meetingRefs point back to this meeting and
            #     the first round's lineage terminates at the question candidates.
            generated = closed["hypothesisRound"]
            assert generated["status"] == "created"
            first_round = generated["round"]
            assert first_round["status"] == "closed"
            assert first_round["metaReview"]["accepted"] is True
            assert {
                item["id"]
                for item in first_round["meetingRefs"]
                if item["kind"] == "meeting_round"
            } == {first_meeting_id}
            assert {
                item["id"] for item in first_round["lineage"] if item["kind"] == "candidate"
            } == {"hyp-a", "hyp-b"}
            assert not [
                item for item in first_round["lineage"] if item["kind"] == "round"
            ]

            # 4. The collection decision unblocks source_finding; the pending
            #    collection request blocks hypothesis_design as a knowledge gap.
            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" not in _blocker_codes(finding)
            design = _evaluate(runtime, team_id, "hypothesis_design")
            design_codes = _blocker_codes(design)
            assert "knowledge_gap_pending" in design_codes
            assert "hypothesis_round_unconverged" in design_codes

            # The command gate enforces the same blockers (not just the probe).
            with pytest.raises(NodeNotReadyError):
                runtime.command_service.submit(
                    CommandRequest(
                        command_id="cmd-hf4-early-design",
                        run_id=_RUN_ID,
                        team_id=team_id,
                        command=WorkflowCommandKind.START_NODE,
                        node_id="hypothesis_design",
                        expected_run_version=1,
                        idempotency_key="hf4:test-early-design",
                        payload={},
                        requested_by=ActorRef("user", "u-1"),
                        requested_at_ms=_FIXED_NOW_MS,
                    )
                )

            # 5. Child collection handoff: gap clears, the parent re-checks
            #    (still unconverged) and the next review meeting auto-opens.
            handoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                handoff_ref="knowledge_package:pkg-1",
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            assert handoff["request"]["status"] == "handed_off"
            assert handoff["request"]["handoffRef"] == "knowledge_package:pkg-1"
            next_meeting = handoff["nextMeeting"]
            assert next_meeting["status"] == "opened"
            second_meeting_id = next_meeting["meetingRound"]["meetingRoundId"]
            assert second_meeting_id != first_meeting_id
            assert next_meeting["roundIndex"] == 2

            links = chain.list_review_round_links(team_id, question_id=_QUESTION_ID)["links"]
            assert [link["roundIndex"] for link in links] == [1, 2]
            assert links[0]["meetingRoundId"] == first_meeting_id
            assert links[1]["previousMeetingRoundId"] == first_meeting_id
            assert links[1]["collectionRequestId"] == request["requestId"]

            design = _evaluate(runtime, team_id, "hypothesis_design")
            design_codes = _blocker_codes(design)
            assert "knowledge_gap_pending" not in design_codes
            assert "hypothesis_round_unconverged" in design_codes
            resume = handoff["resume"]
            assert resume["runs"][0]["runId"] == _RUN_ID
            assert resume["runs"][0]["action"] == "not_ready"
            assert "hypothesis_round_unconverged" in resume["runs"][0]["blockers"]
            assert runtime.store.latest_attempt(_RUN_ID, "hypothesis_design") is None

            # 6. Second discussion closes without new evidence requests; the
            #    closure auto-generates the next HypothesisRound whose lineage
            #    links back to the first round; a frozen baseline appears.
            _drive_to_awaiting_approval(team_id, second_meeting_id, agent_ids[0])
            closed_second = chain.close_review_meeting(
                team_id,
                second_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
            )
            assert closed_second["collection"]["requests"] == []
            assert len(collection_calls) == 1
            generated_second = closed_second["hypothesisRound"]
            assert generated_second["status"] == "created"
            second_round = generated_second["round"]
            assert second_round["status"] == "closed"
            assert second_round["metaReview"]["accepted"] is True
            assert {
                item["id"]
                for item in second_round["meetingRefs"]
                if item["kind"] == "meeting_round"
            } == {second_meeting_id}
            assert [
                item["id"] for item in second_round["lineage"] if item["kind"] == "round"
            ] == [first_round["roundId"]]
            _freeze_template_baseline(team_id, agent_ids[0])

            # 7. Converged: the readiness re-check passes and the parent run
            #    dispatches hypothesis_design (writer-transaction-external).
            design = _evaluate(runtime, team_id, "hypothesis_design")
            assert design.ready, [b.code for b in design.blockers]
            resumed = chain.resume_parent_runs(
                team_id,
                question_id=_QUESTION_ID,
                runtime=runtime,
                trigger="test:converged",
            )
            assert resumed["runs"][0]["action"] == "started"
            attempt = runtime.store.latest_attempt(_RUN_ID, "hypothesis_design")
            assert attempt is not None
            assert attempt.status in {"starting", "dispatching", "running"}

            # Idempotent replay: the same trigger replays the command instead
            # of creating a second attempt.
            replayed = chain.resume_parent_runs(
                team_id,
                question_id=_QUESTION_ID,
                runtime=runtime,
                trigger="test:converged",
            )
            assert replayed["runs"][0]["action"] == "replayed"
            assert (
                runtime.store.latest_attempt(_RUN_ID, "hypothesis_design").node_run_id
                == attempt.node_run_id
            )
    finally:
        runtime.close()


def test_missing_search_envelope_never_triggers_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    collection_calls = _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            first_meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
            _drive_to_awaiting_approval(team_id, first_meeting_id, agent_ids[0])
            closed = chain.close_review_meeting(
                team_id,
                first_meeting_id,
                _closure_payload(
                    agent_ids,
                    [
                        _envelope_decision(
                            agent_ids[0], searchEnvelope={"sourceTypes": ["paper"]}
                        )
                    ],
                ),
                runtime=runtime,
            )
            assert closed["meetingRound"]["status"] == "closed"
            assert closed["collection"]["requests"] == []
            skipped = closed["collection"]["skipped"]
            assert len(skipped) == 1
            assert skipped[0]["reason"] == "search_envelope_missing"
            assert collection_calls == []

            # source_finding stays blocked: the first collection scope must
            # come from a discussion decision carrying a valid envelope.
            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" in _blocker_codes(finding)
    finally:
        runtime.close()


def test_unconverged_round_blocks_hypothesis_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            first_meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
            closed = _close_first_meeting_with_envelope(
                team_id, agent_ids, first_meeting_id, runtime
            )
            request = closed["collection"]["requests"][0]
            handoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            second_meeting_id = handoff["nextMeeting"]["meetingRound"]["meetingRoundId"]
            _drive_to_awaiting_approval(team_id, second_meeting_id, agent_ids[0])
            # MetaReview does NOT accept: the auto-generated round stays
            # unconverged and hypothesis_design remains blocked.
            rejected_metareview = lambda context, candidates, pairwise, pareto: {
                "recommendationCandidateId": "hyp-a",
                "rationale": "证据仍不充分，暂不收敛",
                "riskNotes": "hyp-b 泛化证据待补",
                "accepted": False,
            }
            closed_second = chain.close_review_meeting(
                team_id,
                second_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
                metareview_runner=rejected_metareview,
            )
            generated_second = closed_second["hypothesisRound"]
            assert generated_second["status"] == "created"
            assert generated_second["round"]["status"] == "closed"
            assert generated_second["round"]["metaReview"]["accepted"] is False
            _freeze_template_baseline(team_id, agent_ids[0])

            design = _evaluate(runtime, team_id, "hypothesis_design")
            design_codes = _blocker_codes(design)
            assert not design.ready
            assert "hypothesis_round_unconverged" in design_codes
            assert "knowledge_gap_pending" not in design_codes
            assert "template_baseline_missing" not in design_codes

            resumed = chain.resume_parent_runs(
                team_id,
                question_id=_QUESTION_ID,
                runtime=runtime,
                trigger="test:unconverged",
            )
            assert resumed["runs"][0]["action"] == "not_ready"
            assert runtime.store.latest_attempt(_RUN_ID, "hypothesis_design") is None
    finally:
        runtime.close()


def test_chain_state_budget_tracks_current_selection_not_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Budget exhaustion must follow the current selection's rounds; earlier
    selections and superseded rounds must not fake budget_exhausted."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _fake_collection_runs(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    recorded = _open_first_meeting(team_id, agent_ids)
    previous_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
    for _ in range(2):
        opened = chain.open_next_review_meeting(
            team_id,
            previous_meeting_round_id=previous_id,
            agent_runner=_marker_runner,
        )
        assert opened["status"] == "opened"
        previous_id = opened["meetingRound"]["meetingRoundId"]

    exhausted_state = chain.chain_state(team_id, _QUESTION_ID)
    assert exhausted_state["budgetExhausted"] is True
    assert exhausted_state["roundBudget"] == 3

    # Re-selecting candidates starts a fresh selection: its rounds restart at 1
    # and budget exhaustion must clear even though the question keeps all old
    # review meetings.
    reselected = selections.record_hypothesis_selection(
        team_id,
        _selection_payload(agent_ids[1]),
        agent_runner=_marker_runner,
    )
    assert reselected["status"] == "created"
    refreshed_state = chain.chain_state(team_id, _QUESTION_ID)
    assert refreshed_state["budgetExhausted"] is False
    assert refreshed_state["roundBudget"] == 3


def test_round_budget_exhaustion_requires_manual_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _fake_collection_runs(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    recorded = _open_first_meeting(team_id, agent_ids)
    first_meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]

    # Budget of 1: the follow-up round would be round 2 and must not open.
    exhausted = chain.open_next_review_meeting(
        team_id,
        previous_meeting_round_id=first_meeting_id,
        budget=1,
        agent_runner=_marker_runner,
    )
    assert exhausted["status"] == "budget_exhausted"
    assert exhausted["roundIndex"] == 2
    assert exhausted["budget"] == 1

    # A manually raised budget (capped at 5) opens the next round.
    opened = chain.open_next_review_meeting(
        team_id,
        previous_meeting_round_id=first_meeting_id,
        budget=5,
        agent_runner=_marker_runner,
    )
    assert opened["status"] == "opened"
    assert opened["roundIndex"] == 2

    with pytest.raises(ValueError, match="budget"):
        chain.open_next_review_meeting(
            team_id,
            previous_meeting_round_id=first_meeting_id,
            budget=6,
            agent_runner=_marker_runner,
        )


def test_interruption_recovery_preserves_rounds_and_idempotency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    collection_calls = _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            selection_id = recorded["selection"]["selectionId"]
            first_meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]

            # Re-recording the same selection reuses everything (recovery from
            # a crash between selection persistence and meeting opening).
            replayed = selections.record_hypothesis_selection(
                team_id,
                _selection_payload(agent_ids[0]),
                agent_runner=_marker_runner,
            )
            assert replayed["status"] == "reused"
            assert replayed["reviewMeeting"]["status"] == "reused"
            assert (
                replayed["reviewMeeting"]["meetingRound"]["meetingRoundId"]
                == first_meeting_id
            )

            closed = _close_first_meeting_with_envelope(
                team_id, agent_ids, first_meeting_id, runtime
            )
            request = closed["collection"]["requests"][0]
            first_round_id = closed["hypothesisRound"]["round"]["roundId"]
            assert closed["hypothesisRound"]["status"] == "created"

            # Re-closing with the identical payload replays the closure and
            # must not duplicate the collection request, the facade call, or
            # the generated HypothesisRound.
            reclosed = chain.close_review_meeting(
                team_id,
                first_meeting_id,
                _closure_payload(agent_ids, [_envelope_decision(agent_ids[0])]),
                runtime=runtime,
            )
            assert reclosed["status"] == "reused"
            assert len(reclosed["collection"]["requests"]) == 1
            assert reclosed["collection"]["requests"][0]["requestId"] == request["requestId"]
            assert len(collection_calls) == 1
            assert reclosed["hypothesisRound"]["status"] == "reused"
            assert reclosed["hypothesisRound"]["round"]["roundId"] == first_round_id
            assert (
                hrounds.list_hypothesis_rounds(team_id)["roundCount"] == 1
            )

            handoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                handoff_ref="knowledge_package:pkg-1",
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            second_meeting_id = handoff["nextMeeting"]["meetingRound"]["meetingRoundId"]

            # Repeating the handoff is a no-op: no new meeting, no new link.
            rehandoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                handoff_ref="knowledge_package:pkg-1",
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            assert rehandoff["status"] == "reused"
            assert (
                rehandoff["nextMeeting"]["meetingRound"]["meetingRoundId"]
                == second_meeting_id
            )
            links = chain.list_review_round_links(team_id, question_id=_QUESTION_ID)["links"]
            assert len(links) == 2

            # Chain state survives a fresh read (no in-memory state).
            state = chain.chain_state(team_id, _QUESTION_ID)
            assert state["selectionId"] == selection_id
            assert state["firstMeetingId"] == first_meeting_id
            assert state["firstMeetingClosed"] is True
            assert state["collectionRequestCount"] == 1
            assert state["pendingCollectionCount"] == 0
            assert state["collectionReady"] is True
            assert state["meetingCount"] == 2
            assert state["hypothesisRoundCount"] == 1
    finally:
        runtime.close()


def test_close_reports_failed_hypothesis_round_without_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate without a claim fails round generation, not the closure."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(
        monkeypatch,
        hypotheses=[
            {"hypothesis_id": "hyp-a", "statement": "hyp-a 的机制陈述"},
            {"hypothesis_id": "hyp-b", "statement": ""},
            {"hypothesis_id": "hyp-c", "statement": "hyp-c 的机制陈述"},
        ],
    )
    collection_calls = _fake_collection_runs(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            first_meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]
            _drive_to_awaiting_approval(team_id, first_meeting_id, agent_ids[0])
            closed = chain.close_review_meeting(
                team_id,
                first_meeting_id,
                _closure_payload(agent_ids, [_envelope_decision(agent_ids[0])]),
                runtime=runtime,
            )

            # The closure and the collection trigger stand; only the round
            # generation reports a structured failure (fail-closed via the
            # readiness layer, never a rollback of the closed fact).
            assert closed["meetingRound"]["status"] == "closed"
            assert len(closed["collection"]["requests"]) == 1
            assert len(collection_calls) == 1
            hypothesis_round = closed["hypothesisRound"]
            assert hypothesis_round["status"] == "failed"
            assert "hyp-b" in hypothesis_round["error"]
            assert hrounds.list_hypothesis_rounds(team_id)["roundCount"] == 0

            # hypothesis_design stays blocked on the unconverged round gate.
            design = _evaluate(runtime, team_id, "hypothesis_design")
            assert "hypothesis_round_unconverged" in _blocker_codes(design)
    finally:
        runtime.close()


def _candidate_generation_runner(participant, prompt, context):
    """Round-0 discussion fixture: the coordinator proposes CANDIDATE markers."""
    role = str(participant.get("teamRole") or "participant")
    if role == "coordinator":
        content = (
            "CANDIDATE: cand-a | 睡眠剥夺通过腺苷积累损害记忆巩固 | 腺苷受体机制明确\n"
            "CANDIDATE: cand-b | 睡眠剥夺通过突触稳态失衡损害记忆巩固 | 突触稳态假说"
        )
    else:
        content = "AGREE: cand-a 的检验路径更直接"
    return {"status": "completed", "raw_output": content, "summary": "ok"}


def test_candidate_generation_cold_start_registers_ledger_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catalog cold start: round-0 generation discussion -> ledger candidates.

    No approved v2 artifact exists, so the selection candidate source is the
    generation meeting's digest proposals recorded in the chain ledger.
    """
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )

    assert chain.needs_candidate_generation(team_id, _QUESTION_ID) is True

    with server_operator_scope("u-1", roles=("operator",)):
        opened = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )
        assert opened["status"] == "opened"
        meeting = opened["meetingRound"]
        assert meeting["meetingType"] == "hypothesis_candidate_generation"
        meeting_round_id = meeting["meetingRoundId"]

        # Reopening while open reuses the same discussion (deterministic id).
        reused = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )
        assert reused["meetingRound"]["meetingRoundId"] == meeting_round_id

        agent_ids = [agents[role] for role in _ROLES]
        _drive_to_awaiting_approval(team_id, meeting_round_id, agent_ids[0])
        closed = chain.close_review_meeting(
            team_id,
            meeting_round_id,
            _closure_payload(agent_ids, []),
        )
        assert closed["meetingRound"]["status"] == "closed"
        assert closed["candidateCount"] == 2
        statements = {item["statement"] for item in closed["candidates"]}
        assert "睡眠剥夺通过腺苷积累损害记忆巩固" in statements
        assert "睡眠剥夺通过突触稳态失衡损害记忆巩固" in statements

        candidates = chain.list_hypothesis_candidates(team_id, question_id=_QUESTION_ID)[
            "candidates"
        ]
        assert len(candidates) == 2
        assert chain.needs_candidate_generation(team_id, _QUESTION_ID) is False

        # A closed generation meeting is never reopened; replays reuse it.
        replayed = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )
        assert replayed["status"] == "reused"
        assert replayed["meetingRound"]["meetingRoundId"] == meeting_round_id

        state = chain.chain_state(team_id, _QUESTION_ID)
        assert state["candidateCount"] == 2
        assert state["generationMeetingId"] == meeting_round_id
        assert state["generationMeetingStatus"] == "closed"
        # The generation round is not a review round: it does not count into
        # the discussion-round budget.
        assert state["meetingCount"] == 0


def _empty_generation_runner(participant, prompt, context):
    """Discussion happens but nobody proposes a CANDIDATE marker."""
    return {
        "status": "completed",
        "raw_output": "AGREE: 现有证据不足以提出可证伪候选",
        "summary": "ok",
    }


def _failed_generation_runner(participant, prompt, context):
    return {
        "status": "failed",
        "errorType": "protocol_error",
        "summary": "speaker failed before producing discussion evidence",
    }


def test_failed_generation_attempt_can_be_superseded_and_restarted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )

    with server_operator_scope("u-1", roles=("operator",)):
        failed = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_failed_generation_runner
        )
        first_id = failed["meetingRound"]["meetingRoundId"]

        restarted = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )

    second_id = restarted["meetingRound"]["meetingRoundId"]
    assert second_id != first_id
    assert second_id.endswith("-a2")
    first = meetings.get_meeting_round(team_id, first_id)["meetingRound"]
    assert first["status"] == "closed"
    assert first["recoveryReason"] == "discussion_has_no_completed_messages"
    assert first["summaryDraftError"]["code"] == "discussion_has_no_completed_messages"
    assert restarted["status"] == "opened"


def test_closed_generation_without_candidates_allows_a_fresh_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closed generation attempt with zero proposals must not deadlock the
    cold start: the next open rolls to a new per-attempt meeting id."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )

    with server_operator_scope("u-1", roles=("operator",)):
        opened = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_empty_generation_runner
        )
        first_id = opened["meetingRound"]["meetingRoundId"]
        agent_ids = [agents[role] for role in _ROLES]
        # The discussion yields no CANDIDATE markers; closing it records the
        # empty outcome as a fact (the digest carries zero proposals).
        _drive_to_awaiting_approval(team_id, first_id, agent_ids[0])
        closed = chain.close_review_meeting(
            team_id,
            first_id,
            _closure_payload(agent_ids, []),
        )
        assert closed["meetingRound"]["status"] == "closed"
        assert closed["candidateCount"] == 0
        assert chain.needs_candidate_generation(team_id, _QUESTION_ID) is False

        regenerated = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_candidate_generation_runner
        )
        assert regenerated["status"] == "opened"
        second_id = regenerated["meetingRound"]["meetingRoundId"]
        assert second_id != first_id

        _drive_to_awaiting_approval(team_id, second_id, agent_ids[0])
        closed_second = chain.close_review_meeting(
            team_id,
            second_id,
            _closure_payload(agent_ids, []),
        )
        assert closed_second["candidateCount"] == 2
        assert chain.needs_candidate_generation(team_id, _QUESTION_ID) is False


def test_failed_review_round_can_be_reopened_with_next_budgeted_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A review round whose every speaker failed restarts as the next round.

    The blocked summarize path surfaces ``重新发起讨论`` for review rounds;
    ``reopen_failed_review_meeting`` supersedes the failed attempt
    (append-only, no digest) and opens round 2 with the same selection
    lineage and the fixed candidate context in its topic."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    with server_operator_scope("u-1", roles=("operator",)):
        failed = selections.record_hypothesis_selection(
            team_id,
            _selection_payload(agent_ids[0]),
            agent_runner=_failed_generation_runner,
        )
        assert failed["reviewMeeting"]["status"] == "opened"
        first_id = failed["reviewMeeting"]["meetingRound"]["meetingRoundId"]

        reopened = chain.reopen_failed_review_meeting(
            team_id,
            first_id,
            agent_runner=_marker_runner,
        )

    assert reopened["status"] == "reopened"
    superseded = reopened["supersededMeetingRound"]
    assert superseded["status"] == "closed"
    assert superseded["recoveryReason"] == "discussion_has_no_completed_messages"
    second = reopened["meetingRound"]
    assert second["meetingRoundId"] != first_id
    assert second["meetingRoundId"].endswith("-r2")
    assert second["status"] in {"open", "summarizing"}
    assert reopened["roundIndex"] == 2

    first = meetings.get_meeting_round(team_id, first_id)["meetingRound"]
    assert first["status"] == "closed"


def test_reopen_refuses_review_round_with_successful_speech(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rounds with citable completed messages must close through the
    four-state gate, not the failed-discussion recovery."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    with server_operator_scope("u-1", roles=("operator",)):
        recorded = _open_first_meeting(team_id, agent_ids)
        meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]

        with pytest.raises(meetings.ResearchMeetingRoundError):
            chain.reopen_failed_review_meeting(team_id, meeting_id)


def test_converged_chain_without_evidence_requests_is_collection_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A review chain that legitimately concluded "no additional collection"
    (converged, all rounds closed, zero evidence requests) must not wedge the
    first source-collection round: the closure decision itself is the scope."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            first_meeting_id = recorded["reviewMeeting"]["meetingRound"]["meetingRoundId"]

            _drive_to_awaiting_approval(team_id, first_meeting_id, agent_ids[0])
            closed = chain.close_review_meeting(
                team_id,
                first_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
            )
            assert closed["meetingRound"]["status"] == "closed"

            state = chain.chain_state(team_id, _QUESTION_ID)
            assert state["hypothesisConverged"] is True
            assert state["openMeetingIds"] == []
            assert state["collectionRequestCount"] == 0
            assert state["collectionReady"] is True

            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" not in _blocker_codes(finding)
    finally:
        runtime.close()


def test_evidence_request_probe_is_scoped_per_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One question's evidence request must not block another question's
    collection-ready waiver (team-wide scans are fatal for the 125-question
    batch)."""
    team_id, _agents = _hf_env(tmp_path, monkeypatch)
    root = (
        developer_sandbox.seeded_sandbox_workspace_path(
            chain._project_root(), "teams", chain._safe_team_id(team_id)
        )
        / "research_workflow"
    )
    root.mkdir(parents=True, exist_ok=True)
    scope = _scope_fields("agent-1")
    meetings_path = root / "meeting_rounds.jsonl"
    with meetings_path.open("w", encoding="utf-8") as fh:
        for round_id, question in (
            ("mtg-sci001", "SCI-001"),
            ("mtg-sci002", "SCI-002"),
        ):
            fh.write(
                json.dumps(
                    {
                        **scope,
                        "schemaVersion": 1,
                        "meetingRoundId": round_id,
                        "meetingType": "hypothesis_review",
                        "question": question,
                        "status": "closed",
                        "participants": ["agent-1"],
                        "startedAt": "2026-08-20T01:00:00Z",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    decisions_path = root / "decision_records.jsonl"
    with decisions_path.open("w", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "decisionId": "dec-x",
                    "decision": "request_new_evidence",
                    "rationale": "SCI-002 需要补充证据",
                    "decidedBy": "agent-1",
                    "candidateRefs": [],
                    "evidenceRefs": [],
                    "status": "adopted",
                    "meetingRoundId": "mtg-sci002",
                    "scopeHash": scope["scopeHash"] if "scopeHash" in scope else "sh",
                    "createdAt": "2026-08-20T02:00:00Z",
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    assert chain._question_requested_evidence(team_id, "SCI-001") is False
    assert chain._question_requested_evidence(team_id, "SCI-002") is True
    assert chain._question_requested_evidence(team_id, "") is False


def test_candidate_evidence_trail_cites_discussion_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The trail maps each ledger candidate to the speeches that cite it."""
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    with server_operator_scope("u-1", roles=("operator",)):
        _open_first_meeting(team_id, agent_ids)
        storage = chain._storage_path(team_id)
        with storage.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "schemaVersion": chain.SCHEMA_VERSION,
                        "recordKind": chain.CANDIDATE_KIND,
                        "candidateId": "hyp-a",
                        "questionId": _QUESTION_ID,
                        "statement": "hyp-a 陈述",
                        "rationale": "机制",
                        "proposedBy": "agent",
                        "meetingRoundId": "",
                        "createdAt": "2026-08-20T00:00:00Z",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

        result = chain.candidate_evidence_trail(team_id, _QUESTION_ID)

    by_id = {
        trail["candidateId"]: trail["entries"] for trail in result["trails"]
    }
    assert "hyp-a" in by_id
    entries = by_id["hyp-a"]
    assert entries, "review speeches citing cand-a must appear in the trail"
    assert all("hyp-a" in entry["excerpt"] for entry in entries)
    assert all(entry["meetingLabel"].startswith("评审") for entry in entries)
    assert all(entry["messageId"] for entry in entries)

    empty = chain.candidate_evidence_trail(team_id, "SCI-999")
    assert empty["trails"] == []
