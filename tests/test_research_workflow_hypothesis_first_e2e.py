"""HF-7 端到端开发态验收测试：假说先行科研流程。

设计文档 §8 验收逐条映射
（2026-08-18-hypothesis-first-research-flow-overall-design.md）：

- §8.1 fixture 全链路：选题批准 → 假说选择（多选）→ 首轮讨论自动开启（房间
  互引）→ 讨论关门（Digest/Decision/HypothesisRound 全量 artifact +
  sourceMessageRefs 回链）→ 自动搜集子运行（facade ensure 证据 + scopeHash
  幂等）→ knowledge_handoff 交接 → 父运行恢复 → 自动新一轮讨论 → 收敛
  （MetaReview.accepted 且无新缺口）→ hypothesis_design 放行 → 模板冻结门槛
  => test_end_to_end_fixture_chain_with_ledger_audit
- §8.2 未关门 / 缺 artifact 的轮次不得进入 readiness
  => test_unclosed_or_artifactless_round_never_feeds_readiness
- §8.3 重选链（previousSelectionId）与轮次 lineage 可追溯
  => test_reselection_chain_and_round_lineage_walk
- §8.4 关门幂等：重复关门不产生重复 Digest/Decision/记忆候选/HypothesisRound
  => test_closure_replay_produces_no_duplicate_artifacts
- §8.5 讨论参与角色工具快照不含搜集能力；搜集仅经单一 facade
  => test_participant_role_tool_snapshot_and_single_collection_facade
- §8.6 中断恢复：链路各点位重放不丢轮次、无重复副作用（含全新 runtime 重读）
  => test_interruption_replay_across_chain_points

任务 #4（platform readiness 门）：platform readiness 汇总实现
（core/research/competition/platform_flow_ready.py）不在本批次允许路径内，
按任务 fallback 在 §8.1 测试中以证据形式断言链路各门
（source_finding / hypothesis_design / command gate）的状态迁移。

全部为开发态 fixture：fake runner、fake 搜集运行、tmp_path 存储；
不调真实模型、不联网、不触发真实科研活动。
"""

from __future__ import annotations

import json
from concurrent.futures import Future
from pathlib import Path

import pytest

from core.research.workflow.contracts import (
    CURRENT_RESEARCH_TEAM_ROLE_CONTRACT,
    ActorRef,
    CommandRequest,
    WorkflowCommandKind,
    scope_hash_for,
)
from core.web.services import (
    agent_directory_service,
    agent_role_tool_profile_service,
    chat_room_service,
    data_processing_service,
    session_service,
    team_service,
)
from core.web.services.team_workflow import hypothesis_rounds as hrounds
from core.web.services.team_workflow import hypothesis_selection as selections
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow import personal_memory_candidates as memories
from core.web.services.team_workflow import research_templates as templates
from core.web.services.team_workflow.hypothesis_rounds import (
    ResearchHypothesisRoundError,
)
from core.web.services.team_workflow.hypothesis_selection import (
    ResearchHypothesisSelectionError,
)
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
from core.web.services.team_workflow.source_collection import facade
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

_ROLES = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.participant_policy(
    chain.HYPOTHESIS_REVIEW_MEETING_TYPE
).required_product_role_ids
_TEAM_ROLES = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.product_role_ids
_QUESTION_ID = "SCI-096"
_CANDIDATE_IDS = ("hyp-a", "hyp-b", "hyp-c")
_RUN_ID = "run-hf7-e2e"
_FIXED_NOW_MS = 1_750_000_000_000
_FACADE_TOOL = "research_knowledge_collection_tool"


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
    for role in (*_TEAM_ROLES, "experiment_planner"):
        agent = agent_directory_service.create_agent_instance(
            display_name=f"HF7 {role}",
            role_key=role,
            created_by="hf7-test",
        )
        session_service.ensure_agent_direct_session(
            agent_id=agent["agentId"], title=f"HF7 {role}"
        )
        agents[role] = agent["agentId"]
    team_id = team_service.create_team(
        name="HF-7 假说先行验收团队",
        purpose="challenge-workflow-hf7-e2e",
        members=[{"agentId": agents[role], "role": role} for role in _TEAM_ROLES],
    )["teamId"]
    return team_id, agents


def _patch_approved_question(monkeypatch: pytest.MonkeyPatch) -> None:
    detail = {
        "teamId": "hf7",
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
    if role == "challenge_cup_search":
        content = "AGREE: hyp-a 的机制证据最完整，进入有界验证"
    else:
        content = (
            "DISAGREE: hyp-b 的泛化证据不足\n"
            "RISK: 数据集偏差尚未评估\n"
            "ACTION: challenge_cup_experiment_revision | 补充 hyp-b 的消融实验证据\n"
            "KNOWLEDGE: 预测编码层级最新综述"
        )
    return {"status": "completed", "raw_output": content, "summary": "ok"}


def _stateful_collection_fakes(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict], list[dict]]:
    """Fake run creation behind the real facade; the run list reflects creations.

    Unlike a flat start-fake, this keeps state so the real facade
    ``_find_existing_run`` scope-hash idempotency path is exercised end to end.
    Returns ``(created_runs, facade_calls)``: run-creation payloads plus one
    entry per facade invocation (kwargs + result) as call evidence.
    """
    created: list[dict] = []
    facade_calls: list[dict] = []

    def fake_start(team_id, payload=None):
        index = len(created) + 1
        created.append(
            {
                "teamId": team_id,
                "payload": dict(payload or {}),
                "runId": f"dprun-hf7-{index}",
                "createdAt": f"2026-08-18T00:00:{index:02d}Z",
                "updatedAt": f"2026-08-18T00:00:{index:02d}Z",
            }
        )
        return {"runId": f"dprun-hf7-{index}", "status": "accepted"}

    def fake_list_runs(*, limit=200, metadata_filters=None, scope_filters=None, **_):
        scope_hash = str((scope_filters or {}).get("researchScopeHash") or "")
        runs = [
            {
                "runId": item["runId"],
                "createdAt": item["createdAt"],
                "updatedAt": item["updatedAt"],
            }
            for item in created
            if not scope_hash
            or str(item["payload"].get("scope", {}).get("researchScopeHash") or "")
            == scope_hash
        ]
        return {"runs": runs}

    def fake_summary(team_id, run_id=""):
        return {
            "status": "accepted",
            "runId": run_id,
            "run": {"runId": run_id, "status": "accepted"},
            "runStatus": {"status": "accepted", "currentPhase": "queued"},
            "summary": {"recordCount": 0, "sourceCandidateCount": 0},
            "stageCards": [],
        }

    def fake_background_start(team_id, run_id, payload=None):
        return {
            "teamId": team_id,
            "runId": run_id,
            "status": "running",
            "payload": dict(payload or {}),
        }

    real_facade = facade.research_knowledge_collection_facade

    def recording_facade(**kwargs):
        result = real_facade(**kwargs)
        facade_calls.append({"kwargs": dict(kwargs), "result": result})
        return result

    monkeypatch.setattr(collection_runs, "start_source_collection_run", fake_start)
    monkeypatch.setattr(
        collection_runs, "start_source_collection_search_background", fake_background_start
    )
    monkeypatch.setattr(collection_runs, "get_source_collection_summary", fake_summary)
    monkeypatch.setattr(data_processing_service, "list_processing_runs", fake_list_runs)
    monkeypatch.setattr(
        facade, "research_knowledge_collection_facade", recording_facade
    )
    return created, facade_calls


def _build_runtime(tmp_path: Path):
    return build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "checkpoints.sqlite",
        domain_overrides={
            "knowledge_package": lambda team_id, run_id: {
                "teamId": team_id,
                "sourceCollectionRunId": "dprun-hf7-1",
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
                "snapshotId": "snap:hf7:source_finding",
                "nodeId": "source_finding",
                "agentId": planner_agent_id,
                "roleKey": "source_finder",
            },
            {
                "snapshotId": "snap:hf7:hypothesis_design",
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
                event_id="evt-created-hf7",
            )
        )
        # The parent's own knowledge gate already completed upstream: a
        # succeeded knowledge_handoff attempt plus an accepted handoff into
        # hypothesis_design exist in the ledger.
        uow.repository.insert_command(
            build_command_record(
                "cmd-hf7-knowledge",
                run_id=_RUN_ID,
                team_id=team_id,
                node_id="knowledge_handoff",
                command_kind="resolve_human_task",
                idempotency_key="hf7:seed-knowledge",
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                "nr-hf7-knowledge_handoff-a1",
                run_id=_RUN_ID,
                node_id="knowledge_handoff",
                actor_kind="human",
                status="succeeded",
                command_id="cmd-hf7-knowledge",
            )
        )
        uow.repository.insert_handoff(
            handoff_id="ho-hf7-knowledge",
            run_id=_RUN_ID,
            edge_id="knowledge_handoff->hypothesis_design",
            from_node_run_id="nr-hf7-knowledge_handoff-a1",
            to_node_id="hypothesis_design",
            to_node_run_id=None,
            gate_kind="knowledge_package",
            input_snapshot_hash="c" * 64,
            offered_at_ms=_FIXED_NOW_MS,
        )
        uow.repository.update_handoff_status(
            "ho-hf7-knowledge", "waiting_human", _FIXED_NOW_MS + 1
        )
        uow.repository.update_handoff_status(
            "ho-hf7-knowledge", "accepted", _FIXED_NOW_MS + 2
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
            "approvalRef": "approval:hf7-template-1",
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


def _digest_records(team_id: str) -> list[dict]:
    return meetings._read_jsonl(meetings._digests_path(team_id))


def _decision_records(team_id: str) -> list[dict]:
    return meetings._read_jsonl(meetings._decisions_path(team_id))


def _memory_candidate_count(team_id: str, agent_ids: list[str]) -> int:
    total = 0
    for agent_id in agent_ids:
        total += int(
            memories.list_personal_memory_candidates(team_id, agent_id=agent_id)[
                "candidateCount"
            ]
        )
    return total


def _walk_round_lineage(team_id: str, round_id: str) -> list[str]:
    """DFS over HypothesisRound lineage round-refs; fails on cycles or open rounds."""
    visited: list[str] = []
    seen: set[str] = set()
    stack = [round_id]
    while stack:
        current = stack.pop()
        assert current not in seen, "hypothesis round lineage must be acyclic"
        seen.add(current)
        round_record = hrounds.get_hypothesis_round(team_id, current)["round"]
        assert round_record["status"] == "closed"
        visited.append(current)
        for ref in round_record.get("lineage") or []:
            if str(ref.get("kind") or "") == "round":
                stack.append(str(ref["id"]))
    return visited


# ---------------------------------------------------------------------------
# §8.1 fixture 全链路 + Ledger 审计链（任务 #1/#2/#4）
# ---------------------------------------------------------------------------


def test_end_to_end_fixture_chain_with_ledger_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    created_runs, facade_calls = _stateful_collection_fakes(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            # 0. 门证据（选择前）：source_finding 与 hypothesis_design 均阻断。
            finding = _evaluate(runtime, team_id, "source_finding")
            assert not finding.ready
            assert "hypothesis_first_meeting_open" in _blocker_codes(finding)
            meeting_blocker = next(
                blocker
                for blocker in finding.blockers
                if blocker.code == "hypothesis_first_meeting_open"
            )
            assert meeting_blocker.remediation is not None
            assert "开启首轮假说评审" in meeting_blocker.remediation.label
            assert "尚未开启" in meeting_blocker.title or "未闭环" in meeting_blocker.title
            design = _evaluate(runtime, team_id, "hypothesis_design")
            design_codes = _blocker_codes(design)
            assert "hypothesis_round_unconverged" in design_codes
            assert "template_baseline_missing" in design_codes

            # 1. 假说选择（多选 hyp-a/hyp-b）→ 首轮讨论自动开启，房间双向互引。
            recorded = _open_first_meeting(team_id, agent_ids)
            selection = recorded["selection"]
            review = recorded["reviewMeeting"]
            meeting = review["meetingRound"]
            first_meeting_id = meeting["meetingRoundId"]
            assert review["discussion"]["background"] is True
            assert meeting["meetingType"] == "hypothesis_review"
            assert meeting["linkedChatRoomId"] == review["roomId"]
            assert meeting["chatRoomRoundIds"] == [review["roundId"]]
            room_detail = chat_room_service.get_chat_room_detail(review["roomId"])
            bound_round = next(
                item
                for item in room_detail["rounds"]
                if item["roundId"] == review["roundId"]
            )
            assert bound_round["config"]["meetingRoundId"] == first_meeting_id
            assert bound_round["status"] == "completed"

            # 1b. 讨论运行时驱动第二轮批评轮并以收敛信号终止（多轮讨论证据）。
            discussion = meeting_runtime.run_meeting_discussion(
                team_id, first_meeting_id, agent_runner=_marker_runner
            )
            assert discussion["stopReason"] == "converged"
            assert discussion["roundsRun"] == 2

            # 2. 讨论关门：Digest v2 全量 artifact + sourceMessageRefs 回链、
            #    Decision 持久化、记忆候选、HypothesisRound 自动生成。
            closed = _close_first_meeting_with_envelope(
                team_id, agent_ids, first_meeting_id, runtime
            )
            assert closed["meetingRound"]["status"] == "closed"
            closed_meeting = closed["meetingRound"]
            digest_id = str(closed_meeting.get("digestId") or "")
            decision_ids = list(closed_meeting.get("decisionRefs") or [])
            assert digest_id and decision_ids

            digest = meetings._latest_by_id(
                _digest_records(team_id), "digestId", digest_id
            )
            assert digest is not None
            assert digest["meetingRoundId"] == first_meeting_id
            for key in (
                "agreements",
                "disagreements",
                "actionItems",
                "risks",
                "knowledgeCandidates",
            ):
                assert isinstance(digest.get(key), list), key
            assert digest["agreements"], "marker fixture must yield agreements"
            source_refs = list(digest.get("sourceMessageRefs") or [])
            assert source_refs
            known_refs = {
                meetings.message_source_ref(message)
                for message in meetings.meeting_source_messages(closed_meeting)
            }
            assert set(source_refs) <= known_refs
            for ref in source_refs:
                room_id, round_id, message_id = ref.split("/")
                assert room_id == review["roomId"]
                assert round_id in discussion["chatRoomRoundIds"]
                assert message_id

            persisted_decisions = [
                meetings._latest_by_id(_decision_records(team_id), "decisionId", item)
                for item in decision_ids
            ]
            assert all(item is not None for item in persisted_decisions)
            assert {
                str(item.get("decision") or "") for item in persisted_decisions
            } == {"request_new_evidence"}

            memory = closed["memorySummary"]
            assert memory["createdCount"] == len(agent_ids)
            assert _memory_candidate_count(team_id, agent_ids) == len(agent_ids)

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

            # 3. 自动搜集子运行：facade ensure 恰好一次，request 稳定互引。
            requests = closed["collection"]["requests"]
            assert len(requests) == 1
            request = requests[0]
            assert request["status"] == "pending"
            assert request["collectionRunId"] == "dprun-hf7-1"
            assert request["meetingRoundId"] == first_meeting_id
            assert request["decisionId"] in decision_ids
            assert len(created_runs) == 1
            assert len(facade_calls) == 1
            ensure_scope = created_runs[0]["payload"]["scope"]
            assert ensure_scope["researchScopeHash"] == meeting["scopeHash"]
            assert ensure_scope["searchEnvelope"]["keywords"] == [
                "predictive coding",
                "spike train coding",
            ]

            # 3b. facade scopeHash 幂等：同 scope 再次 ensure 复用现有运行，
            #     不产生第二次 run 创建。
            first_kwargs = facade_calls[0]["kwargs"]
            replay = facade.research_knowledge_collection_facade(
                team_id=team_id,
                action="ensure",
                scope=first_kwargs["scope"],
                searchEnvelope=first_kwargs["searchEnvelope"],
                requirements=first_kwargs["requirements"],
                writebackPolicy=first_kwargs["writebackPolicy"],
            )
            assert replay["idempotent"] is True
            assert replay["created"] is False
            assert replay["locator"]["runId"] == "dprun-hf7-1"
            assert replay["locator"]["scopeHash"] == meeting["scopeHash"]
            assert len(created_runs) == 1

            # 4. 门证据（关门后）：source_finding 放行；hypothesis_design 仍被
            #    知识缺口 + 未收敛阻断；command gate 同样拒绝（不只是探针）。
            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" not in _blocker_codes(finding)
            design = _evaluate(runtime, team_id, "hypothesis_design")
            design_codes = _blocker_codes(design)
            assert "knowledge_gap_pending" in design_codes
            assert "hypothesis_round_unconverged" in design_codes
            with pytest.raises(NodeNotReadyError):
                runtime.command_service.submit(
                    CommandRequest(
                        command_id="cmd-hf7-early-design",
                        run_id=_RUN_ID,
                        team_id=team_id,
                        command=WorkflowCommandKind.START_NODE,
                        node_id="hypothesis_design",
                        expected_run_version=1,
                        idempotency_key="hf7:test-early-design",
                        payload={},
                        requested_by=ActorRef("user", "u-1"),
                        requested_at_ms=_FIXED_NOW_MS,
                    )
                )

            # 5. 子运行 knowledge_handoff 交接：缺口清除、父运行重检（writer
            #    事务外，仍未收敛）、新一轮讨论自动开启并接上 lineage。
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
            resume = handoff["resume"]
            assert resume["runs"][0]["runId"] == _RUN_ID
            assert resume["runs"][0]["action"] == "not_ready"
            assert "hypothesis_round_unconverged" in resume["runs"][0]["blockers"]
            assert runtime.store.latest_attempt(_RUN_ID, "hypothesis_design") is None

            links = chain.list_review_round_links(team_id, question_id=_QUESTION_ID)[
                "links"
            ]
            assert [link["roundIndex"] for link in links] == [1, 2]
            assert links[0]["meetingRoundId"] == first_meeting_id
            assert links[1]["previousMeetingRoundId"] == first_meeting_id
            assert links[1]["collectionRequestId"] == request["requestId"]

            # 6. 第二轮关门（select_candidate，无新缺口）→ 第二个
            #    HypothesisRound lineage 回链第一轮；随后冻结模板基线。
            _drive_to_awaiting_approval(team_id, second_meeting_id, agent_ids[0])
            closed_second = chain.close_review_meeting(
                team_id,
                second_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
            )
            assert closed_second["collection"]["requests"] == []
            assert len(created_runs) == 1
            second_round = closed_second["hypothesisRound"]["round"]
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

            # 7. 收敛（MetaReview.accepted 且无新缺口）+ 模板冻结 →
            #    hypothesis_design 放行，父运行恢复并派发。
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

            # 8. Ledger 审计链：run_created → command_accepted → node_starting
            #    全部在 Workflow Ledger 事件流中可追溯，事件 sequence 唯一，
            #    命令带确定性幂等键，attempt 回链 command。
            events = runtime.store.list_events(_RUN_ID)
            event_types = [event.event_type for event in events]
            assert "run_created" in event_types
            assert "command_accepted" in event_types
            assert "node_starting" in event_types
            sequences = [event.sequence for event in events]
            assert len(set(sequences)) == len(sequences)
            command = runtime.store.get_command_by_idempotency(
                _RUN_ID,
                f"hf-chain:{_RUN_ID}:hypothesis_design:test:converged",
            )
            assert command is not None
            assert attempt.command_id == command.command_id

            # 9. 跨存储稳定 ID 互引总走查：选择 → 会议 → Digest/Decision →
            #    搜集 request → 轮次链接 → HypothesisRound，全部可解析。
            stored_selection = selections.get_hypothesis_selection(
                team_id, selection["selectionId"]
            )["selection"]
            assert stored_selection["questionId"] == _QUESTION_ID
            all_requests = chain.list_collection_requests(
                team_id, question_id=_QUESTION_ID
            )["requests"]
            assert [item["requestId"] for item in all_requests] == [
                request["requestId"]
            ]
            walked = _walk_round_lineage(team_id, second_round["roundId"])
            assert walked == [second_round["roundId"], first_round["roundId"]]
            state = chain.chain_state(team_id, _QUESTION_ID)
            assert state["selectionId"] == selection["selectionId"]
            assert state["firstMeetingClosed"] is True
            assert state["collectionReady"] is True
            assert state["meetingCount"] == 2
            assert state["hypothesisRoundCount"] == 2
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# §8.2 未关门 / 缺 artifact 的轮次不得进入 readiness
# ---------------------------------------------------------------------------


def test_unclosed_or_artifactless_round_never_feeds_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _stateful_collection_fakes(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            first_meeting_id = recorded["reviewMeeting"]["meetingRound"][
                "meetingRoundId"
            ]

            # open 状态：两个门都阻断。
            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" in _blocker_codes(finding)
            design = _evaluate(runtime, team_id, "hypothesis_design")
            assert "hypothesis_round_unconverged" in _blocker_codes(design)

            # 缺 artifact 的轮次无法生成 HypothesisRound（fail-closed）：
            # 未关门直接拒绝。
            with pytest.raises(ResearchHypothesisRoundError):
                hrounds.generate_hypothesis_round_from_meeting(
                    team_id, first_meeting_id
                )

            # summarizing / awaiting_approval 状态：仍未关门，门保持阻断。
            meetings.begin_meeting_summary(
                team_id, first_meeting_id, actor=agent_ids[0]
            )
            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" in _blocker_codes(finding)

            drafted = meeting_runtime.draft_meeting_digest(team_id, first_meeting_id)
            assert drafted["status"] == "awaiting_approval"
            finding = _evaluate(runtime, team_id, "source_finding")
            assert "hypothesis_first_meeting_open" in _blocker_codes(finding)
            design = _evaluate(runtime, team_id, "hypothesis_design")
            assert "hypothesis_round_unconverged" in _blocker_codes(design)
            with pytest.raises(ResearchHypothesisRoundError):
                hrounds.generate_hypothesis_round_from_meeting(
                    team_id, first_meeting_id
                )

            # 没有任何 HypothesisRound 落盘；readiness 完全不受影响。
            assert hrounds.list_hypothesis_rounds(team_id)["roundCount"] == 0
            state = chain.chain_state(team_id, _QUESTION_ID)
            assert state["firstMeetingClosed"] is False
            assert state["hypothesisRoundCount"] == 0
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# §8.3 重选链与轮次 lineage 追溯
# ---------------------------------------------------------------------------


def test_reselection_chain_and_round_lineage_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    _stateful_collection_fakes(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            # A. 两轮评审建立 round lineage：round2 → round1 → candidates。
            recorded = _open_first_meeting(team_id, agent_ids)
            first_selection_id = recorded["selection"]["selectionId"]
            first_meeting_id = recorded["reviewMeeting"]["meetingRound"][
                "meetingRoundId"
            ]
            closed = _close_first_meeting_with_envelope(
                team_id, agent_ids, first_meeting_id, runtime
            )
            first_round = closed["hypothesisRound"]["round"]
            request = closed["collection"]["requests"][0]
            handoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            second_meeting_id = handoff["nextMeeting"]["meetingRound"][
                "meetingRoundId"
            ]
            _drive_to_awaiting_approval(team_id, second_meeting_id, agent_ids[0])
            closed_second = chain.close_review_meeting(
                team_id,
                second_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
            )
            second_round = closed_second["hypothesisRound"]["round"]

            # 从最新轮次沿 lineage 走查：无环、途经轮次全部 closed、
            # 终止于选题 artifact 的候选集合。
            walked = _walk_round_lineage(team_id, second_round["roundId"])
            assert walked == [second_round["roundId"], first_round["roundId"]]
            terminal = hrounds.get_hypothesis_round(team_id, walked[-1])["round"]
            terminal_candidates = {
                item["id"] for item in terminal["lineage"] if item["kind"] == "candidate"
            }
            assert terminal_candidates == {"hyp-a", "hyp-b"}
            assert terminal_candidates <= set(_CANDIDATE_IDS)

            # B. 重选链：缺少 / 错误的 previousSelectionId 均被拒绝。
            with pytest.raises(ResearchHypothesisSelectionError):
                selections.record_hypothesis_selection(
                    team_id,
                    _selection_payload(agent_ids[0], selectedCandidateIds=["hyp-c", "hyp-b"]),
                    agent_runner=_marker_runner,
                )
            with pytest.raises(ResearchHypothesisSelectionError):
                selections.record_hypothesis_selection(
                    team_id,
                    _selection_payload(
                        agent_ids[0],
                        selectedCandidateIds=["hyp-c", "hyp-b"],
                        previousSelectionId="hfsel-does-not-exist",
                    ),
                    agent_runner=_marker_runner,
                )

            reselected = selections.record_hypothesis_selection(
                team_id,
                _selection_payload(
                    agent_ids[0],
                    selectedCandidateIds=["hyp-a", "hyp-c"],
                    previousSelectionId=first_selection_id,
                ),
                agent_runner=_marker_runner,
            )
            assert reselected["status"] == "created"
            re_selection = reselected["selection"]
            assert re_selection["previousSelectionId"] == first_selection_id
            assert re_selection["selectionId"] != first_selection_id

            # 重选自动开启属于自己的首轮会议（新 meetingRoundId，绑定新选择）。
            re_review = reselected["reviewMeeting"]
            assert re_review["status"] == "opened"
            re_meeting = re_review["meetingRound"]
            assert re_meeting["meetingRoundId"] != first_meeting_id
            assert (
                f"hypothesis_selection:{re_selection['selectionId']}"
                in list(re_meeting.get("inputArtifactRefs") or [])
            )

            # 选择账本可追溯：latest 指向重选，旧记录仍可解析，链可步行。
            listed = selections.list_hypothesis_selections(
                team_id, question_id=_QUESTION_ID
            )["selections"]
            assert [item["selectionId"] for item in listed] == [
                first_selection_id,
                re_selection["selectionId"],
            ]
            latest_scope = _scope_fields(agent_ids[0])
            latest_scope["scopeHash"] = scope_hash_for(
                **{
                    field: latest_scope[field]
                    for field in ("program", "theme", "campaign", "question", "branch", "workflow")
                },
                agent_id=latest_scope["agentId"],
                mode=latest_scope["mode"],
            )
            latest = selections.get_latest_hypothesis_selection(
                team_id,
                _QUESTION_ID,
                scope=latest_scope,
            )[
                "selection"
            ]
            assert latest["selectionId"] == re_selection["selectionId"]
            original = selections.get_hypothesis_selection(team_id, first_selection_id)[
                "selection"
            ]
            assert original["selectedCandidateIds"] == ["hyp-a", "hyp-b"]
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# §8.4 关门幂等：重复关门不产生重复 artifact
# ---------------------------------------------------------------------------


def test_closure_replay_produces_no_duplicate_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    created_runs, _facade_calls = _stateful_collection_fakes(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            first_meeting_id = recorded["reviewMeeting"]["meetingRound"][
                "meetingRoundId"
            ]
            payload = _closure_payload(agent_ids, [_envelope_decision(agent_ids[0])])
            closed = _close_first_meeting_with_envelope(
                team_id, agent_ids, first_meeting_id, runtime
            )
            request = closed["collection"]["requests"][0]
            first_round_id = closed["hypothesisRound"]["round"]["roundId"]

            snapshot = {
                "digests": len(_digest_records(team_id)),
                "decisions": len(_decision_records(team_id)),
                "memories": _memory_candidate_count(team_id, agent_ids),
                "rounds": hrounds.list_hypothesis_rounds(team_id)["roundCount"],
                "requests": chain.list_collection_requests(
                    team_id, question_id=_QUESTION_ID
                )["requestCount"],
                "facadeRuns": len(created_runs),
            }
            assert snapshot == {
                "digests": 1,
                "decisions": 1,
                "memories": len(agent_ids),
                "rounds": 1,
                "requests": 1,
                "facadeRuns": 1,
            }

            # 相同 payload 重复关门：全部 artifact 复用，零新增（reused 路径
            # 不再重写任何存储，记忆候选数保持不变即为不重复证据）。
            reclosed = chain.close_review_meeting(
                team_id, first_meeting_id, payload, runtime=runtime
            )
            assert reclosed["status"] == "reused"
            assert reclosed["collection"]["requests"][0]["requestId"] == request[
                "requestId"
            ]
            assert reclosed["hypothesisRound"]["status"] == "reused"
            assert reclosed["hypothesisRound"]["round"]["roundId"] == first_round_id
            assert reclosed["personalMemoryCandidateRefs"]
            assert {
                "digests": len(_digest_records(team_id)),
                "decisions": len(_decision_records(team_id)),
                "memories": _memory_candidate_count(team_id, agent_ids),
                "rounds": hrounds.list_hypothesis_rounds(team_id)["roundCount"],
                "requests": chain.list_collection_requests(
                    team_id, question_id=_QUESTION_ID
                )["requestCount"],
                "facadeRuns": len(created_runs),
            } == snapshot

            # 已关门会议拒绝以不同内容复用（closureHash 保护，fail-closed）。
            with pytest.raises(
                meetings.ResearchMeetingRoundError, match="different closure content"
            ):
                chain.close_review_meeting(
                    team_id,
                    first_meeting_id,
                    _closure_payload(
                        agent_ids,
                        [_envelope_decision(agent_ids[0])],
                        memoryClass="other_class",
                    ),
                    runtime=runtime,
                )

            # 会议轮次记录本身也不产生重复（append-only 去重）。
            meeting_list = meetings.list_meeting_rounds(team_id)["meetings"]
            assert [item["meetingRoundId"] for item in meeting_list] == [
                first_meeting_id
            ]
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# §8.5 参与角色工具快照 + 单一搜集 facade
# ---------------------------------------------------------------------------


def test_participant_role_tool_snapshot_and_single_collection_facade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    created_runs, facade_calls = _stateful_collection_fakes(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            recorded = _open_first_meeting(team_id, agent_ids)
            meeting = recorded["reviewMeeting"]["meetingRound"]
            first_meeting_id = meeting["meetingRoundId"]
            closed = _close_first_meeting_with_envelope(
                team_id, agent_ids, first_meeting_id, runtime
            )
            assert len(closed["collection"]["requests"]) == 1

            # 讨论参与角色的工具快照：可解析且
            # 不包含 stage-1 搜集 facade 工具——讨论角色无搜集能力。
            participant_roles = list(meeting.get("participantRoleIds") or [])
            assert set(participant_roles) == set(_ROLES)
            for role in participant_roles:
                profile = agent_role_tool_profile_service.role_tool_profile_for_role(
                    role, primary_mode="research"
                )
                assert profile is not None, role
                assert _FACADE_TOOL not in list(profile.get("allowedTools") or [])

            # 唯一的搜集角色：只允许 facade 工具（single visible interface）。
            collector = agent_role_tool_profile_service.role_tool_profile_for_role(
                "research_knowledge_collector", primary_mode="research"
            )
            assert collector is not None
            assert list(collector["allowedTools"]) == [_FACADE_TOOL]

            # 链路证据：搜集只经 facade ensure 发生，载荷固定为
            # scopeHash + searchEnvelope + source_finder 角色 + web_search 模式
            # + 全 False 写回策略。
            assert len(created_runs) == 1
            payload = created_runs[0]["payload"]
            assert payload["agentRoles"] == ["source_finder"]
            scope = payload["scope"]
            assert scope["researchScopeHash"] == meeting["scopeHash"]
            assert scope["collectionMode"] == "web_search"
            assert scope["searchEnvelope"]["keywords"]
            writeback = scope["writebackPolicy"]
            writeback_flags = {
                key: value for key, value in writeback.items() if key != "schemaVersion"
            }
            assert writeback_flags and not any(
                bool(value) for value in writeback_flags.values()
            )
            assert len(facade_calls) == 1
            call_result = facade_calls[0]["result"]
            assert call_result["action"] == "ensure"
            assert call_result["boundaries"]["singleVisibleInterface"] is True
            assert call_result["boundaries"]["networkExecution"] is False
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# §8.6 中断恢复：链路各点位重放不丢轮次、无重复副作用
# ---------------------------------------------------------------------------


def test_interruption_replay_across_chain_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team_id, agents = _hf_env(tmp_path, monkeypatch)
    _patch_approved_question(monkeypatch)
    created_runs, _facade_calls = _stateful_collection_fakes(monkeypatch)
    runtime = _build_runtime(tmp_path)
    try:
        _seed_parent_run(runtime, team_id, agents["experiment_planner"])
        agent_ids = [agents[role] for role in _ROLES]

        with server_operator_scope("u-1", roles=("operator",)):
            # 点位 A：选择已落盘、会议已开后崩溃 → 重放选择复用一切。
            recorded = _open_first_meeting(team_id, agent_ids)
            selection_id = recorded["selection"]["selectionId"]
            first_meeting_id = recorded["reviewMeeting"]["meetingRound"][
                "meetingRoundId"
            ]
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

            # 点位 B：关门后崩溃 → 重放关门不重复 request / facade / round。
            closed = _close_first_meeting_with_envelope(
                team_id, agent_ids, first_meeting_id, runtime
            )
            request = closed["collection"]["requests"][0]
            reclosed = chain.close_review_meeting(
                team_id,
                first_meeting_id,
                _closure_payload(agent_ids, [_envelope_decision(agent_ids[0])]),
                runtime=runtime,
            )
            assert reclosed["status"] == "reused"
            assert len(created_runs) == 1
            assert hrounds.list_hypothesis_rounds(team_id)["roundCount"] == 1

            # 点位 C：交接后崩溃 → 重放交接不开新会议、不新增链接。
            handoff = chain.record_collection_handoff(
                team_id,
                request["requestId"],
                handoff_ref="knowledge_package:pkg-1",
                runtime=runtime,
                agent_runner=_marker_runner,
            )
            second_meeting_id = handoff["nextMeeting"]["meetingRound"][
                "meetingRoundId"
            ]
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
            assert (
                chain.list_review_round_links(team_id, question_id=_QUESTION_ID)[
                    "linkCount"
                ]
                == 2
            )

        # 点位 D：进程重启（全新 runtime 读同一 ledger）→ 状态完整重放，
        # readiness 与 chain_state 与崩溃前一致，恢复重检不产生副作用。
        runtime.close()
        runtime = _build_runtime(tmp_path)
        with server_operator_scope("u-1", roles=("operator",)):
            state = chain.chain_state(team_id, _QUESTION_ID)
            assert state["selectionId"] == selection_id
            assert state["firstMeetingId"] == first_meeting_id
            assert state["firstMeetingClosed"] is True
            assert state["collectionRequestCount"] == 1
            assert state["pendingCollectionCount"] == 0
            assert state["collectionReady"] is True
            assert state["meetingCount"] == 2
            assert state["hypothesisRoundCount"] == 1

            design = _evaluate(runtime, team_id, "hypothesis_design")
            assert "hypothesis_round_unconverged" in _blocker_codes(design)
            resumed = chain.resume_parent_runs(
                team_id,
                question_id=_QUESTION_ID,
                runtime=runtime,
                trigger="test:after-restart",
            )
            assert resumed["runs"][0]["action"] == "not_ready"
            assert runtime.store.latest_attempt(_RUN_ID, "hypothesis_design") is None

            # 重启后继续推进链路：第二轮关门 → 冻结 → 恢复派发；
            # 同 trigger 重放复用命令，ledger 中只有一个 hypothesis_design attempt。
            _drive_to_awaiting_approval(team_id, second_meeting_id, agent_ids[0])
            closed_second = chain.close_review_meeting(
                team_id,
                second_meeting_id,
                _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                runtime=runtime,
            )
            assert closed_second["hypothesisRound"]["status"] == "created"
            _freeze_template_baseline(team_id, agent_ids[0])
            resumed = chain.resume_parent_runs(
                team_id,
                question_id=_QUESTION_ID,
                runtime=runtime,
                trigger="test:converged",
            )
            assert resumed["runs"][0]["action"] == "started"
            attempt = runtime.store.latest_attempt(_RUN_ID, "hypothesis_design")
            assert attempt is not None
            replayed_resume = chain.resume_parent_runs(
                team_id,
                question_id=_QUESTION_ID,
                runtime=runtime,
                trigger="test:converged",
            )
            assert replayed_resume["runs"][0]["action"] == "replayed"
            attempts = [
                item
                for item in runtime.store.list_attempts(_RUN_ID)
                if item.node_id == "hypothesis_design"
            ]
            assert len(attempts) == 1
            assert attempts[0].node_run_id == attempt.node_run_id
    finally:
        runtime.close()
