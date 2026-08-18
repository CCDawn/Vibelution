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


def _patch_approved_question(monkeypatch: pytest.MonkeyPatch) -> None:
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
            "hypotheses": [
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
    meetings.begin_meeting_summary(team_id, meeting_round_id, actor=actor)
    drafted = meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)
    assert drafted["status"] == "awaiting_approval"


def _candidate(candidate_id: str, reviewer: str) -> dict:
    return {
        "candidateId": candidate_id,
        "claim": f"{candidate_id} 声称脉冲序列通过层级预测编码携带信息",
        "rationale": "fixture rationale",
        "differenceFromAlternatives": f"{candidate_id} 与其他候选的编码层级假设不同",
        "lineageRefs": [],
        "scores": {
            "novelty": 0.6,
            "competitionFit": 0.7,
            "falsifiability": 0.8,
            "evidenceSupport": 0.7,
            "feasibility": 0.6,
            "replicability": 0.6,
            "scopeAlignment": 0.9,
        },
        "reviewedBy": reviewer,
        "status": "reviewed",
    }


def _close_hypothesis_round(
    team_id: str,
    agent_ids: list[str],
    meeting_round_id: str,
    closed_result: dict,
    *,
    accepted: bool,
) -> dict:
    digest_id = str(closed_result["digest"].get("digestId") or "")
    decision_ids = [str(item.get("decisionId") or "") for item in closed_result["decisions"]]
    created = hrounds.create_hypothesis_round(
        team_id,
        {
            **_scope_fields(agent_ids[0]),
            "candidates": [
                _candidate("hyp-a", agent_ids[1]),
                _candidate("hyp-b", agent_ids[1]),
            ],
        },
    )
    round_id = created["round"]["roundId"]
    closed = hrounds.close_hypothesis_round(
        team_id,
        round_id,
        {
            "pairwiseComparisons": [
                {
                    "comparisonId": "cmp-1",
                    "leftCandidateId": "hyp-a",
                    "rightCandidateId": "hyp-b",
                    "reviewerAgentId": agent_ids[1],
                    "outcome": "left_wins",
                    "justification": "hyp-a 的机制与泛化证据更完整",
                }
            ],
            "pareto": {
                "paretoFrontCandidateIds": ["hyp-a"],
                "dominatedCandidateIds": ["hyp-b"],
                "analystAgentId": agent_ids[1],
                "notes": "",
            },
            "metaReview": {
                "metaReviewId": "meta-hf4-1",
                "reviewerAgentId": agent_ids[0],
                "recommendationCandidateId": "hyp-a",
                "rationale": "证据收敛，可以进入实验设计",
                "riskNotes": "",
                "accepted": accepted,
            },
            "meetingRefs": [
                {"kind": "meeting_round", "id": meeting_round_id},
                {"kind": "meeting_digest", "id": digest_id},
                {"kind": "decision_record", "id": decision_ids[0]},
            ],
            "closedBy": agent_ids[0],
        },
    )
    return closed["round"]


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
            #    HF-3 executor fixture closes an accepted round; a frozen
            #    template baseline appears.
            _drive_to_awaiting_approval(team_id, second_meeting_id, agent_ids[0])
            closed_second = chain.close_review_meeting(
                team_id,
                second_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
            )
            assert closed_second["collection"]["requests"] == []
            assert len(collection_calls) == 1
            _close_hypothesis_round(
                team_id, agent_ids, second_meeting_id, closed_second, accepted=True
            )
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
            closed_second = chain.close_review_meeting(
                team_id,
                second_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
            )
            # HF-3 executor fixture: round closes but MetaReview is NOT accepted.
            _close_hypothesis_round(
                team_id, agent_ids, second_meeting_id, closed_second, accepted=False
            )
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

            # Re-closing with the identical payload replays the closure and
            # must not duplicate the collection request or the facade call.
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
    finally:
        runtime.close()
