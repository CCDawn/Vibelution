from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    project_agent_bus_service,
    session_service,
    team_service,
    team_workflow_orchestration_service,
)
from core.web.services.team_workflow import research_project_agent_tasks
from core.web.services.team_workflow.experiment_kernel import (
    _select_experiment_stage_round,
)
from core.web.services.team_workflow.research_project_agent_tasks import (
    SESSION_RECONCILE_MAX_UNREADABLE_FAILURES,
    ResearchProjectAgentTaskError,
    get_research_project_agent_task_context,
    get_research_project_agent_task_status,
    reconcile_research_project_agent_task_statuses,
    research_project_iteration_readiness,
    start_research_project_agent_task,
    update_research_project_agent_task_status,
)


def test_source_collection_task_receipt_context_uses_server_task_authority(
    monkeypatch,
) -> None:
    from core.web.services.session.worker import _model_invocation_receipt_context
    from core.web.services.team_workflow.source_collection import stage_session

    policy_sha256 = "a" * 64
    monkeypatch.setattr(
        stage_session,
        "_read_source_collection_stage_session_task_record",
        lambda team_id, task_id: {
            "teamId": team_id,
            "taskId": task_id,
            "sessionId": "session-source-1",
            "researchProjectId": "project-source-1",
            "turn": {"turnId": "turn-source-1"},
            "challengeTaskContract": {
                "questionId": "SCI-096",
                "workflowRunId": "run-source-formal-1",
                "workflowId": "challenge-cup-research",
                "workflowVersionId": "v2.1",
                "workflowNodeId": "source_finding",
                "nodeRunId": "node-run-source-1",
                "nodeAttempt": 1,
                "stageId": "generation",
                "modelPolicySha256": policy_sha256,
                "effectiveRoute": {
                    "modelRef": "openai/gpt-5.6",
                    "providerId": "openai",
                    "modelId": "gpt-5.6",
                },
            },
        },
    )

    context = _model_invocation_receipt_context(
        {
            "message_metadata": {
                "taskId": "source-task-1",
                "sourceCollectionStageTaskId": "source-task-1",
                "teamId": "team-source-1",
                "researchProjectId": "project-source-1",
            }
        },
        session_id="session-source-1",
        turn_id="turn-source-1",
    )

    assert context is not None
    assert context["receiptRunId"] == "run-source-formal-1"
    assert context["modelPolicySha256"] == policy_sha256
    assert context["outcomeKinds"] == ["source_evidence"]
    assert context["questionStageBinding"]["formalNodeId"] == "source_finding"


def _use_tmp_project_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    for service in (
        agent_directory_service,
        chat_room_service,
        project_agent_bus_service,
        session_service,
        team_service,
        team_workflow_orchestration_service,
    ):
        monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)


def _team_project_and_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    role_specs = (
        ("experiment_planner", "challenge_cup_experiment_planner", "实验规划"),
        ("experiment_ledger", "challenge_cup_experiment_ledger", "实验证据"),
        ("iteration_planner", "challenge_cup_iteration_planner", "迭代决策"),
        ("iteration_versioning", "challenge_cup_versioning", "版本治理"),
    )
    members = []
    agents = {}
    for team_role, role_key, label in role_specs:
        agent = agent_directory_service.create_agent_instance(
            display_name=label,
            role_key=role_key,
        )
        agents[team_role] = agent
        members.append(
            {
                "agentId": agent["agentId"],
                "agentName": label,
                "role": team_role,
            }
        )
    team = team_service.create_team(name="科研团队", members=members)
    project = team_workflow_orchestration_service.create_research_project(
        team["teamId"],
        {"name": "层级反馈实验"},
    )["project"]
    return team, project, agents


def _accepted_submitter(monkeypatch):
    calls: list[dict] = []

    def fake_submit(session_id: str, content: str, **kwargs):
        calls.append(
            {
                "sessionId": session_id,
                "content": content,
                "kwargs": kwargs,
            }
        )
        return {
            "accepted": True,
            "turnId": f"turn-{len(calls)}",
            "status": "running",
            "acceptedAt": "2026-07-28T00:00:00+00:00",
        }

    monkeypatch.setattr(session_service, "submit_session_message", fake_submit)
    return calls


def _allow_iteration_tasks(monkeypatch, project_id: str) -> None:
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_load_experiment_plan_store",
        lambda _team_id: {
            "plans": [
                {
                    "planId": "plan-iteration-ready",
                    "researchProjectId": project_id,
                    "contractValidation": {"valid": True},
                    "readiness": {"readyForPlanReview": True},
                    "designGate": {"status": "frozen"},
                    "activeSmokeResult": {
                        "smokeResultId": "smoke-iteration-ready",
                        "status": "needs_review",
                    },
                }
            ]
        },
    )


def _client() -> TestClient:
    return TestClient(
        create_app(),
        headers={CONTROL_TOKEN_HEADER: get_control_token()},
    )


def test_task_start_resolves_fixed_role_and_replays_idempotently(tmp_path, monkeypatch):
    team, project, agents = _team_project_and_agents(tmp_path, monkeypatch)
    calls = _accepted_submitter(monkeypatch)

    first = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "targetRef": "stage-round-1",
            "idempotencyKey": "design-stage-round-1",
            "returnTo": "/teams?team=research",
            "returnLabel": "返回科研工作台",
        },
    )
    replay = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "targetRef": "stage-round-1",
            "idempotencyKey": "design-stage-round-1",
        },
    )

    assert first["task"]["agentId"] == agents["experiment_planner"]["agentId"]
    assert first["task"]["roleKey"] == "challenge_cup_experiment_planner"
    assert first["task"]["roleLabel"] == "实验规划"
    assert first["task"]["status"] == "running"
    assert first["task"]["sessionTitle"] == "层级反馈实验｜实验规划"
    assert first["task"]["turn"]["turnId"] == "turn-1"
    assert first["chatRoute"] == first["task"]["chatRoute"]
    assert replay["idempotentReplay"] is True
    assert replay["task"]["taskId"] == first["task"]["taskId"]
    assert replay["task"]["sessionId"] == first["task"]["sessionId"]
    assert len(calls) == 1


def test_task_start_requires_explicit_agent_to_match_team_role_snapshot(
    tmp_path, monkeypatch
):
    team, project, agents = _team_project_and_agents(tmp_path, monkeypatch)
    calls = _accepted_submitter(monkeypatch)

    started = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "agentId": agents["experiment_planner"]["agentId"],
            "idempotencyKey": "exact-agent-design-1",
        },
    )
    assert started["task"]["agentId"] == agents["experiment_planner"]["agentId"]
    assert len(calls) == 1

    with pytest.raises(ResearchProjectAgentTaskError) as exc:
        start_research_project_agent_task(
            team["teamId"],
            project["projectId"],
            {
                "taskKind": "experiment_design",
                "agentId": agents["experiment_ledger"]["agentId"],
                "idempotencyKey": "wrong-agent-design-1",
            },
        )
    assert exc.value.code == "explicit_agent_mismatch"
    assert len(calls) == 1


def test_hypothesis_task_preserves_formal_workflow_scope(
    tmp_path,
    monkeypatch,
) -> None:
    team, project, agents = _team_project_and_agents(tmp_path, monkeypatch)
    calls = _accepted_submitter(monkeypatch)

    started = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "hypothesis_design",
            "agentId": agents["experiment_planner"]["agentId"],
            "targetRef": "node-run:nr-run-sci-096-hypothesis_design-a5",
            "workflowRunId": "run-sci-096",
            "workflowNodeId": "hypothesis_design",
            "sourceCollectionRunId": "dprun-sci-096",
            "idempotencyKey": "hypothesis-run-sci-096-a5",
        },
    )

    task = started["task"]
    assert task["taskKind"] == "hypothesis_design"
    assert task["workflowRunId"] == "run-sci-096"
    assert task["workflowNodeId"] == "hypothesis_design"
    assert task["sourceCollectionRunId"] == "dprun-sci-096"
    assert task["roleLabel"] == "假设设计"
    assert "record_hypothesis_set" in calls[0]["content"]
    assert "本节点到 hypothesis_set 写回即结束" in calls[0]["content"]


def test_candidate_hypothesis_tasks_run_in_parallel_hidden_child_sessions(
    tmp_path, monkeypatch
) -> None:
    team, project, agents = _team_project_and_agents(tmp_path, monkeypatch)
    calls = _accepted_submitter(monkeypatch)
    common = {
        "taskKind": "hypothesis_design",
        "agentId": agents["experiment_planner"]["agentId"],
        "workflowRunId": "run-sci-096",
        "workflowNodeId": "hypothesis_design",
        "nodeRunId": "node-run-hypothesis",
        "sourceCollectionRunId": "dprun-sci-096",
        "selectionId": "selection-1",
        "selectedCandidateIds": ["H1", "H2"],
    }
    h1 = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            **common,
            "candidateId": "H1",
            "subtaskId": "node-run-hypothesis:selection-1:H1",
            "targetRef": "hypothesis:selection-1:H1",
            "candidateContext": {"candidateId": "H1", "statement": "claim H1"},
            "idempotencyKey": "candidate-H1",
        },
    )
    h2 = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            **common,
            "candidateId": "H2",
            "subtaskId": "node-run-hypothesis:selection-1:H2",
            "targetRef": "hypothesis:selection-1:H2",
            "candidateContext": {"candidateId": "H2", "statement": "claim H2"},
            "idempotencyKey": "candidate-H2",
        },
    )

    assert h1["task"]["sessionId"] != h2["task"]["sessionId"]
    assert h1["task"]["candidateId"] == "H1"
    assert h2["task"]["candidateId"] == "H2"
    assert session_service.get_session_detail(h1["task"]["sessionId"])[
        "hiddenFromIndex"
    ] is True
    assert "record_hypothesis_fragment" in calls[0]["content"]
    assert '"candidateId":"H1"' in calls[0]["content"]
    assert len(calls) == 2


def test_candidate_task_persists_private_frozen_hypothesis_binding(
    tmp_path, monkeypatch
) -> None:
    team, project, agents = _team_project_and_agents(tmp_path, monkeypatch)
    calls = _accepted_submitter(monkeypatch)
    snapshot_hash = "d" * 64
    started = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "hypothesis_design",
            "agentId": agents["experiment_planner"]["agentId"],
            "workflowRunId": "run-sci-096",
            "workflowNodeId": "hypothesis_design",
            "nodeRunId": "node-run-hypothesis",
            "sourceCollectionRunId": "dprun-sci-096",
            "selectionId": "selection-1",
            "selectedCandidateIds": ["H1"],
            "candidateId": "H1",
            "candidateContext": {"candidateId": "H1", "statement": "claim H1"},
            "subtaskId": "node-run-hypothesis:selection-1:H1",
            "targetRef": "hypothesis:selection-1:H1",
            "idempotencyKey": "candidate-H1-frozen",
        },
        _hypothesis_input_binding={
            "status": "ready",
            "workflowRunId": "run-sci-096",
            "sourceCollectionRunId": "dprun-sci-096",
            "allowedEvidenceRefs": ["source:paper:1"],
            "knowledgeSnapshot": {
                "snapshotHash": snapshot_hash,
                "packageCount": 1,
                "packages": [],
                "knowledgeItemIds": ["ki-1"],
            },
        },
    )

    public_task = started["task"]
    assert public_task["consumedKnowledgeSnapshotHash"] == snapshot_hash
    assert "hypothesisInputBinding" not in public_task
    assert snapshot_hash in calls[0]["content"]
    context = get_research_project_agent_task_context(
        team["teamId"], project["projectId"], public_task["taskId"]
    )
    assert context["hypothesisInput"]["knowledgeSnapshot"]["snapshotHash"] == (
        snapshot_hash
    )
    assert context["hypothesisInput"]["candidateId"] == "H1"
    status = get_research_project_agent_task_status(
        team["teamId"], project["projectId"]
    )
    assert "hypothesisInputBinding" not in status["tasks"][0]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "statement",
            "s"
            * research_project_agent_tasks.CANDIDATE_CONTEXT_STATEMENT_MAX_CHARS
            + "overflow",
        ),
        (
            "mechanism",
            "m"
            * research_project_agent_tasks.CANDIDATE_CONTEXT_MECHANISM_MAX_CHARS
            + "overflow",
        ),
        (
            "predictions",
            ["prediction"]
            * (research_project_agent_tasks.CANDIDATE_CONTEXT_MAX_PREDICTIONS + 1),
        ),
        (
            "predictions",
            [
                "p"
                * research_project_agent_tasks.CANDIDATE_CONTEXT_PREDICTION_MAX_CHARS
                + "overflow"
            ],
        ),
    ],
)
def test_candidate_context_rejects_unbounded_prompt_fields(
    tmp_path,
    monkeypatch,
    field,
    value,
) -> None:
    team, project, agents = _team_project_and_agents(tmp_path, monkeypatch)
    calls = _accepted_submitter(monkeypatch)
    context = {"candidateId": "H1", "statement": "claim H1"}
    context[field] = value

    with pytest.raises(ResearchProjectAgentTaskError) as exc:
        start_research_project_agent_task(
            team["teamId"],
            project["projectId"],
            {
                "taskKind": "hypothesis_design",
                "agentId": agents["experiment_planner"]["agentId"],
                "workflowRunId": "run-sci-096",
                "workflowNodeId": "hypothesis_design",
                "nodeRunId": "node-run-hypothesis",
                "sourceCollectionRunId": "dprun-sci-096",
                "selectionId": "selection-1",
                "selectedCandidateIds": ["H1"],
                "candidateId": "H1",
                "subtaskId": "node-run-hypothesis:selection-1:H1",
                "candidateContext": context,
                "idempotencyKey": f"candidate-boundary-{field}",
            },
        )

    assert exc.value.code == "invalid_candidate_context"
    assert calls == []


def test_hypothesis_workflow_task_does_not_reuse_the_planners_flat_experiment_session(
    tmp_path,
    monkeypatch,
) -> None:
    team, project, agents = _team_project_and_agents(tmp_path, monkeypatch)
    calls = _accepted_submitter(monkeypatch)
    experiment = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "targetRef": "manual-plan",
            "idempotencyKey": "manual-plan-1",
        },
    )
    update_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
        experiment["task"]["taskId"],
        status="completed",
    )

    hypothesis = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "hypothesis_design",
            "agentId": agents["experiment_planner"]["agentId"],
            "targetRef": "node-run:nr-run-sci-096-hypothesis_design-a5",
            "workflowRunId": "run-sci-096",
            "workflowNodeId": "hypothesis_design",
            "sourceCollectionRunId": "dprun-sci-096",
            "idempotencyKey": "hypothesis-run-sci-096-a5",
        },
    )

    assert hypothesis["task"]["sessionId"] != experiment["task"]["sessionId"]
    assert hypothesis["task"]["sessionAttempt"] == 1
    assert hypothesis["task"]["sessionTitle"] == "层级反馈实验｜假设设计"
    assert calls[1]["sessionId"] == hypothesis["task"]["sessionId"]
    assert calls[1]["kwargs"]["message_metadata"]["workflowRunId"] == "run-sci-096"


def test_iteration_task_requires_frozen_design_and_registered_result(
    tmp_path, monkeypatch
):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    calls = _accepted_submitter(monkeypatch)
    plan = {
        "planId": "plan-iteration-gate",
        "researchProjectId": project["projectId"],
        "contractValidation": {"valid": True},
        "readiness": {"readyForPlanReview": True},
        "designGate": {"status": "frozen"},
    }
    plan_store = {"plans": []}
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_load_experiment_plan_store",
        lambda _team_id: plan_store,
    )

    missing_design = research_project_iteration_readiness(
        team["teamId"],
        project["projectId"],
    )
    assert missing_design["ready"] is False
    assert missing_design["code"] == "missing_frozen_experiment_design"
    with pytest.raises(
        ResearchProjectAgentTaskError,
        match="frozen executable experiment design",
    ):
        start_research_project_agent_task(
            team["teamId"],
            project["projectId"],
            {"taskKind": "iteration_decision"},
        )

    plan_store["plans"] = [plan]
    missing_result = research_project_iteration_readiness(
        team["teamId"],
        project["projectId"],
    )
    assert missing_result["ready"] is False
    assert missing_result["code"] == "missing_experiment_result"
    with pytest.raises(
        ResearchProjectAgentTaskError,
        match="registered smoke or full-run result",
    ):
        start_research_project_agent_task(
            team["teamId"],
            project["projectId"],
            {"taskKind": "iteration_decision"},
        )

    plan["activeSmokeRun"] = {
        "smokeRunId": "smoke-needs-review",
        "status": "needs_review",
        "adapter": "predictive_coding_reconstruction_proxy",
        "seed": 42,
        "decisionHint": "accept",
        "metrics": {
            "baselineMse": 0.025838,
            "variantMse": 0.007935,
            "improvement": 0.017903,
        },
        "artifactHash": "sha256:smoke-artifact",
        "proxyOnly": True,
        "boundaries": [
            "offline_numpy_proxy",
            "not_target_dataset_evaluation",
        ],
        "logs": ["must-not-enter-agent-context"],
    }
    ready = research_project_iteration_readiness(
        team["teamId"],
        project["projectId"],
    )
    assert ready["ready"] is True
    assert ready["resultId"] == "smoke-needs-review"
    assert ready["reasonZh"] == "已登记待复核 Smoke，可进入迭代决策进行复核与修订。"
    started = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {"taskKind": "iteration_decision"},
    )
    assert started["task"]["status"] == "running"
    assert len(calls) == 1
    assert calls[0]["kwargs"]["turn_mode"] == "task"
    assert (
        calls[0]["kwargs"]["message_metadata"]["researchProjectId"]
        == project["projectId"]
    )


def test_different_project_roles_use_distinct_flat_sessions(tmp_path, monkeypatch):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)

    planner = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "idempotencyKey": "planner-1",
        },
    )
    ledger = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_evidence_review",
            "targetRef": "plan-1",
            "idempotencyKey": "ledger-1",
        },
    )

    assert planner["task"]["sessionId"] != ledger["task"]["sessionId"]
    assert planner["task"]["sessionAttempt"] == 1
    assert ledger["task"]["sessionAttempt"] == 1
    assert ledger["task"]["sessionTitle"] == "层级反馈实验｜实验证据"


def test_active_task_blocks_formal_retry_then_terminal_retry_creates_attempt_two(
    tmp_path, monkeypatch
):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    _allow_iteration_tasks(monkeypatch, project["projectId"])
    first = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "iteration_decision",
            "targetRef": "loop-1",
            "idempotencyKey": "iteration-1",
        },
    )

    with pytest.raises(
        ResearchProjectAgentTaskError,
        match="still active",
    ):
        start_research_project_agent_task(
            team["teamId"],
            project["projectId"],
            {
                "taskKind": "iteration_decision",
                "targetRef": "loop-1",
                "formalRetry": True,
                "retryTaskId": first["task"]["taskId"],
                "idempotencyKey": "iteration-retry-active",
            },
        )

    update_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
        first["task"]["taskId"],
        status="failed",
        result_refs=["loop-1"],
    )
    retry = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "iteration_decision",
            "targetRef": "loop-1",
            "formalRetry": True,
            "retryTaskId": first["task"]["taskId"],
            "idempotencyKey": "iteration-retry-1",
        },
    )

    assert retry["task"]["sessionAttempt"] == 2
    assert retry["task"]["sessionId"] != first["task"]["sessionId"]
    assert retry["task"]["retryOfSessionId"] == first["task"]["sessionId"]
    assert retry["task"]["retrySourceTaskId"] == first["task"]["taskId"]
    assert retry["task"]["sessionTitle"] == "层级反馈实验｜迭代决策｜重试 2"


def test_public_task_status_is_project_scoped_and_path_prompt_secret_free(
    tmp_path, monkeypatch
):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "version_governance",
            "targetRef": "candidate-1",
            "idempotencyKey": "version-1",
        },
    )

    status = get_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
    )
    encoded = json.dumps(status, ensure_ascii=False).lower()

    assert status["researchProjectId"] == project["projectId"]
    assert status["tasks"][0]["roleKey"] == "challenge_cup_versioning"
    assert "storagepath" not in encoded
    assert "prompt" not in encoded
    assert "secret" not in encoded
    assert str(tmp_path).lower() not in encoded


def test_experiment_design_task_materializes_candidate_graph_hypotheses_once(
    tmp_path, monkeypatch
):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    candidate_store = team_workflow_orchestration_service._load_candidate_store(
        team["teamId"]
    )
    candidate_store["candidates"] = [
        {
            "candidateId": "candidate-graph-sleep",
            "candidateType": "candidate_graph",
            "teamId": team["teamId"],
            "title": "Sleep evidence graph",
            "sourceKind": "agent_writeback",
            "sourceRefs": [],
            "evidenceRefs": [],
            "metadata": {
                "agentWriteback": {
                    "result": {
                        "candidateGraph": {
                            "nodes": [
                                {
                                    "id": "source-retained-1",
                                    "title": "Retained source",
                                    "evidenceRef": "evidence-anchor-1",
                                },
                                {
                                    "id": "source-challenge-1",
                                    "title": "Challenging source",
                                    "evidenceRef": "evidence-anchor-2",
                                },
                            ],
                            "falsifiableHypotheses": [
                                {
                                    "id": "H1",
                                    "statement": "NREM downscaling preserves relative synaptic differences.",
                                    "boundary": "Requires stage-specific intervention.",
                                    "supportingCandidates": ["source-retained-1"],
                                    "challengingCandidates": ["source-challenge-1"],
                                },
                                {
                                    "id": "H2",
                                    "statement": "NREM replay and REM recalibration have separable effects.",
                                    "boundary": "Requires independent NREM and REM controls.",
                                    "supportingCandidates": ["source-retained-1"],
                                    "challengingCandidates": [],
                                },
                            ],
                        }
                    }
                }
            },
            "currentWorkflowNode": "candidate_graph",
            "currentState": "preview_ready",
            "qualityStatus": "needs_revision",
            "createdAt": "2026-07-29T00:00:00+00:00",
            "updatedAt": "2026-07-29T00:00:00+00:00",
        }
    ]
    project_root = (
        team_workflow_orchestration_service.resolve_research_project_workspace_root(
            team["teamId"],
            project["projectId"],
        )
    )
    candidate_store_path = project_root / "candidate_store" / "index.json"
    team_workflow_orchestration_service._write_json(
        candidate_store_path, candidate_store
    )

    first = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "idempotencyKey": "design-from-graph-1",
        },
    )
    replay = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "idempotencyKey": "design-from-graph-1",
        },
    )

    projected = [
        item
        for item in team_workflow_orchestration_service._read_json(
            candidate_store_path
        )["candidates"]
        if item.get("candidateType") == "algorithm_hypothesis"
    ]
    assert first["task"]["status"] == "running"
    assert replay["idempotentReplay"] is True
    assert len(projected) == 2
    assert {
        item["metadata"]["projection"]["graphHypothesisId"] for item in projected
    } == {
        "H1",
        "H2",
    }
    assert all(
        item["sourceKind"] == "candidate_graph_hypothesis_projection"
        for item in projected
    )
    assert all(item["qualityStatus"] == "needs_revision" for item in projected)
    assert all(
        item["metadata"]["output"]["requiresReview"] is True for item in projected
    )
    assert all(item["sourceRefs"] and item["evidenceRefs"] for item in projected)


def test_task_status_read_is_side_effect_free(tmp_path, monkeypatch):
    """GET 状态接口是纯读：session 已终态也不得借查询写回 store。"""
    team, project, agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "idempotencyKey": "design-readonly-1",
        },
    )
    root = team_workflow_orchestration_service.resolve_research_project_workspace_root(
        team["teamId"],
        project["projectId"],
    )
    store_path = root / "research_project_agent_tasks.json"
    before = store_path.read_bytes()
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda _session_id, **_kwargs: {
            "status": "ready",
            "currentPhase": "ready",
            "activeTask": None,
        },
    )

    status = get_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
    )

    assert status["tasks"][0]["status"] == "running"
    assert store_path.read_bytes() == before


def test_task_status_reconciles_ready_session_with_created_experiment_plan(
    tmp_path, monkeypatch
):
    team, project, agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    started = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "idempotencyKey": "design-reconcile-1",
        },
    )
    task_id = started["task"]["taskId"]
    root = team_workflow_orchestration_service.resolve_research_project_workspace_root(
        team["teamId"],
        project["projectId"],
    )
    team_workflow_orchestration_service._write_json(
        root / "experiment_plans" / "index.json",
        {
            "schemaVersion": 1,
            "storeKind": team_workflow_orchestration_service.EXPERIMENT_PLAN_STORE_KIND,
            "teamId": team["teamId"],
            "activePlanId": "plan-reconciled",
            "plans": [
                {
                    "planId": "plan-reconciled",
                    "researchProjectId": project["projectId"],
                    "createdByAgent": agents["experiment_planner"]["agentId"],
                    "createdFromTaskId": task_id,
                    "createdAt": "9999-07-29T00:01:00+00:00",
                    "updatedAt": "9999-07-29T00:01:00+00:00",
                    "status": "draft",
                }
            ],
        },
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda _session_id, **_kwargs: {
            "status": "ready",
            "currentPhase": "ready",
            "activeTask": None,
        },
    )

    assert get_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
    )["tasks"][0]["status"] == "running"

    summary = reconcile_research_project_agent_task_statuses(
        team["teamId"],
        project["projectId"],
    )

    assert summary["reconciled"] == 1
    status = get_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
    )
    assert status["activeTasks"] == []
    assert status["tasks"][0]["taskId"] == task_id
    assert status["tasks"][0]["status"] == "completed"
    assert status["tasks"][0]["resultRefs"] == ["plan-reconciled"]


def test_task_status_reconciles_needs_continue_session_as_stopped(
    tmp_path, monkeypatch
):
    """SCI-003 回归：needs_continue 是暂停态，不能让任务永远停留在 running。"""
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    started = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "idempotencyKey": "design-needs-continue-1",
        },
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda _session_id, **_kwargs: {
            "status": "needs_continue",
            "currentPhase": "needs_continue",
            "activeTask": None,
        },
    )

    reconcile_research_project_agent_task_statuses(
        team["teamId"],
        project["projectId"],
    )

    status = get_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
    )

    assert status["activeTasks"] == []
    assert status["tasks"][0]["taskId"] == started["task"]["taskId"]
    assert status["tasks"][0]["status"] == "stopped"
    assert status["tasks"][0]["failureCode"] == "session_needs_continue"


def test_reconcile_never_guesses_plan_ownership_without_task_link(
    tmp_path, monkeypatch
):
    """无 createdFromTaskId 的 plan 不能靠 actor/时间窗启发式归属成本任务证据。"""
    team, project, agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    started = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "idempotencyKey": "design-unlinked-plan-1",
        },
    )
    update_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
        started["task"]["taskId"],
        status="incomplete",
        failure_code="task_result_not_recorded",
    )
    root = team_workflow_orchestration_service.resolve_research_project_workspace_root(
        team["teamId"],
        project["projectId"],
    )
    planner = agents["experiment_planner"]
    team_workflow_orchestration_service._write_json(
        root / "experiment_plans" / "index.json",
        {
            "schemaVersion": 1,
            "storeKind": team_workflow_orchestration_service.EXPERIMENT_PLAN_STORE_KIND,
            "teamId": team["teamId"],
            "activePlanId": "plan-unlinked",
            "plans": [
                {
                    "planId": "plan-unlinked",
                    "researchProjectId": project["projectId"],
                    "createdByAgent": (
                        f"{planner['agentCode']} {planner['displayName']}"
                    ),
                    "createdAt": "9999-07-29T00:01:00+00:00",
                    "updatedAt": "9999-07-29T00:01:00+00:00",
                    "status": "draft",
                }
            ],
        },
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda _session_id, **_kwargs: {
            "status": "ready",
            "currentPhase": "ready",
            "activeTask": None,
        },
    )

    reconcile_research_project_agent_task_statuses(
        team["teamId"],
        project["projectId"],
    )

    status = get_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
    )

    assert status["tasks"][0]["status"] == "incomplete"
    assert status["tasks"][0]["failureCode"] == "plan_task_link_missing"
    assert status["tasks"][0]["resultRefs"] == []


def test_reconcile_fails_task_after_repeated_unreadable_sessions(
    tmp_path, monkeypatch
):
    """session 持续不可读时任务必须进入明确失败态，而不是被无限静默跳过。"""
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    started = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "idempotencyKey": "design-unreadable-1",
        },
    )
    task_id = started["task"]["taskId"]

    def _raise_unreadable(_session_id: str, **_kwargs):
        raise RuntimeError("session store unavailable")

    monkeypatch.setattr(session_service, "get_session_detail", _raise_unreadable)

    for expected_failures in range(1, SESSION_RECONCILE_MAX_UNREADABLE_FAILURES):
        reconcile_research_project_agent_task_statuses(
            team["teamId"],
            project["projectId"],
        )
        status = get_research_project_agent_task_status(
            team["teamId"],
            project["projectId"],
        )
        assert status["tasks"][0]["status"] == "running"
        assert status["tasks"][0]["sessionReconcileFailures"] == expected_failures

    summary = reconcile_research_project_agent_task_statuses(
        team["teamId"],
        project["projectId"],
    )

    assert summary["failedSessionUnreadable"] == [task_id]
    status = get_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
    )
    assert status["activeTasks"] == []
    assert status["tasks"][0]["status"] == "failed"
    assert status["tasks"][0]["failureCode"] == "session_unreadable"
    assert status["tasks"][0]["turn"]["status"] == "failed"


def test_completed_task_projects_and_persists_terminal_turn_status(
    tmp_path, monkeypatch
):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    started = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "idempotencyKey": "design-terminal-turn-status-1",
        },
    )

    completed = update_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
        started["task"]["taskId"],
        status="completed",
        result_refs=["plan-terminal-turn"],
    )

    assert completed["status"] == "completed"
    assert completed["turn"]["status"] == "completed"

    root = team_workflow_orchestration_service.resolve_research_project_workspace_root(
        team["teamId"],
        project["projectId"],
    )
    store_path = root / "research_project_agent_tasks.json"
    store = json.loads(store_path.read_text(encoding="utf-8"))
    store["tasks"][0]["turn"]["status"] = "running"
    store_path.write_text(
        json.dumps(store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    status = get_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
    )

    assert status["tasks"][0]["status"] == "completed"
    assert status["tasks"][0]["turn"]["status"] == "completed"


def test_task_start_rejects_missing_fixed_role_binding(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="无实验职责团队", members=[])
    project = team_workflow_orchestration_service.create_research_project(
        team["teamId"],
        {"name": "无绑定实验"},
    )["project"]

    with pytest.raises(
        ResearchProjectAgentTaskError,
        match="is not bound",
    ) as exc_info:
        start_research_project_agent_task(
            team["teamId"],
            project["projectId"],
            {
                "taskKind": "experiment_design",
                "idempotencyKey": "missing-role",
            },
        )

    assert exc_info.value.code == "agent_role_unbound"


def test_explicit_agent_resolution_accepts_canonical_product_role_member(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="挑战杯搜索",
        role_key="challenge_cup_search",
    )
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[
            {
                "agentId": agent["agentId"],
                "agentName": "挑战杯搜索",
                "role": "challenge_cup_search",
            }
        ],
    )

    member, resolved = research_project_agent_tasks._resolve_role_agent(
        team["teamId"],
        research_project_agent_tasks.TASK_KIND_CONTRACTS["problem_understanding"],
        requested_agent_id=agent["agentId"],
    )

    assert member["role"] == "challenge_cup_search"
    assert resolved["agentId"] == agent["agentId"]

    unrelated = agent_directory_service.create_agent_instance(
        display_name="无关角色",
        role_key="challenge_cup_evaluator",
    )
    with pytest.raises(ResearchProjectAgentTaskError) as exc_info:
        research_project_agent_tasks._resolve_role_agent(
            team["teamId"],
            research_project_agent_tasks.TASK_KIND_CONTRACTS[
                "problem_understanding"
            ],
            requested_agent_id=unrelated["agentId"],
        )
    assert exc_info.value.code == "explicit_agent_mismatch"


def test_agent_task_routes_expose_typed_start_and_status_payloads(
    tmp_path, monkeypatch
):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    client = _client()
    base = (
        f"/api/teams/{team['teamId']}/workflow-orchestration/"
        f"research-projects/{project['projectId']}/agent-tasks"
    )

    started = client.post(
        f"{base}/start",
        json={
            "taskKind": "experiment_design",
            "targetRef": "stage-round-1",
            "idempotencyKey": "route-design-1",
        },
    )
    status_response = client.get(f"{base}/status")

    assert started.status_code == 201
    assert started.json()["task"]["taskKind"] == "experiment_design"
    assert started.json()["task"]["turn"]["turnId"] == "turn-1"
    assert status_response.status_code == 200
    assert (
        status_response.json()["tasks"][0]["taskId"] == started.json()["task"]["taskId"]
    )


def test_agent_task_reconcile_route_repairs_stuck_running_task(
    tmp_path, monkeypatch
):
    """后端重启把任务留在 running、session 已 ready 的死锁由维护端点解开。"""
    team, project, agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    client = _client()
    base = (
        f"/api/teams/{team['teamId']}/workflow-orchestration/"
        f"research-projects/{project['projectId']}/agent-tasks"
    )
    started = client.post(
        f"{base}/start",
        json={
            "taskKind": "experiment_design",
            "targetRef": "stage-round-1",
            "idempotencyKey": "route-reconcile-1",
        },
    )
    assert started.status_code == 201
    task_id = started.json()["task"]["taskId"]
    root = team_workflow_orchestration_service.resolve_research_project_workspace_root(
        team["teamId"],
        project["projectId"],
    )
    team_workflow_orchestration_service._write_json(
        root / "experiment_plans" / "index.json",
        {
            "schemaVersion": 1,
            "storeKind": team_workflow_orchestration_service.EXPERIMENT_PLAN_STORE_KIND,
            "teamId": team["teamId"],
            "activePlanId": "plan-route-reconciled",
            "plans": [
                {
                    "planId": "plan-route-reconciled",
                    "researchProjectId": project["projectId"],
                    "createdByAgent": agents["experiment_planner"]["agentId"],
                    "createdFromTaskId": task_id,
                    "createdAt": "9999-07-29T00:01:00+00:00",
                    "updatedAt": "9999-07-29T00:01:00+00:00",
                    "status": "draft",
                }
            ],
        },
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda _session_id, **_kwargs: {
            "status": "ready",
            "currentPhase": "ready",
            "activeTask": None,
        },
    )

    repaired = client.post(f"{base}/reconcile")
    repeat = client.post(f"{base}/reconcile")

    assert repaired.status_code == 200
    body = repaired.json()
    assert body["teamId"] == team["teamId"]
    assert body["researchProjectId"] == project["projectId"]
    assert body["checked"] == 1
    assert body["reconciled"] == 1
    assert body["outcomes"] == [
        {
            "taskId": task_id,
            "action": "reconciled",
            "status": "completed",
            "failureCode": "",
        }
    ]
    status_response = client.get(f"{base}/status")
    assert status_response.json()["activeTasks"] == []
    assert status_response.json()["tasks"][0]["status"] == "completed"
    assert status_response.json()["tasks"][0]["resultRefs"] == [
        "plan-route-reconciled"
    ]
    # 幂等：任务已终态且结果已记录，再次 reconcile 是无写 no-op。
    assert repeat.status_code == 200
    assert repeat.json() == {
        "teamId": team["teamId"],
        "researchProjectId": project["projectId"],
        "checked": 0,
        "reconciled": 0,
        "failedSessionUnreadable": [],
        "outcomes": [],
    }


def test_agent_task_reconcile_route_returns_404_for_missing_project(
    tmp_path, monkeypatch
):
    _team_project_and_agents(tmp_path, monkeypatch)
    client = _client()

    response = client.post(
        f"/api/teams/team-route-404/workflow-orchestration/"
        f"research-projects/project-missing/agent-tasks/reconcile"
    )

    assert response.status_code == 404


def test_agent_task_reconcile_route_maps_agent_task_error_to_422(
    tmp_path, monkeypatch
):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    client = _client()

    def raise_task_error(team_id: str, project_id: str):
        raise ResearchProjectAgentTaskError(
            "Task store inconsistent.",
            code="task_store_inconsistent",
        )

    monkeypatch.setattr(
        "core.web.routes.team_workflows.research_projects"
        ".reconcile_research_project_agent_task_statuses",
        raise_task_error,
    )

    response = client.post(
        f"/api/teams/{team['teamId']}/workflow-orchestration/"
        f"research-projects/{project['projectId']}/agent-tasks/reconcile"
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "task_store_inconsistent"


def test_experiment_task_context_is_project_scoped_and_bounded(tmp_path, monkeypatch):
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    started = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "targetRef": "stage-round-project-a",
            "idempotencyKey": "design-context-project-a",
        },
    )
    other_project = team_workflow_orchestration_service.create_research_project(
        team["teamId"],
        {"name": "另一个项目"},
    )["project"]
    plan_store = {
        "plans": [
            {
                "planId": "plan-project-a",
                "researchProjectId": project["projectId"],
                "experimentName": project["name"],
                "title": "本项目计划",
                "status": "draft",
                "revision": 2,
                "stageRoundId": "stage-round-project-a",
                "experimentContract": {
                    "researchQuestion": "Does A improve?",
                    "dataset": "dataset-a",
                    "baseline": "baseline-a",
                    "metrics": ["metric-a"],
                },
                "readiness": {"readyForPlanReview": True},
                "activeFullRunResult": {
                    "fullRunResultId": "full-result-a",
                    "status": "passed",
                    "metricName": "accuracy",
                    "metricValue": "0.91",
                    "delta": "+0.02",
                    "resultPath": str(tmp_path / "must-not-leak.json"),
                    "logRef": str(tmp_path / "must-not-leak.log"),
                },
                "activeSmokeRunId": "smoke-run-a",
                "activeSmokeRun": {
                    "smokeRunId": "smoke-run-a",
                    "status": "needs_review",
                    "adapter": "predictive_coding_reconstruction_proxy",
                    "seed": 42,
                    "decisionHint": "accept",
                    "metrics": {
                        "decisionConfidence": 0.8,
                        "baseline": {
                            "reconstruction_mse": 0.025838,
                            "masked_region_mse": 0.114479,
                        },
                        "variant": {
                            "reconstruction_mse": 0.007935,
                            "masked_region_mse": 0.034923,
                        },
                        "delta": {
                            "mse_improvement": 0.017903,
                            "reconstruction_mse_delta": 0.017903,
                        },
                        "threshold": {"mse_improvement": 0.001},
                    },
                    "artifactHash": "sha256:smoke-artifact-a",
                    "proxyOnly": True,
                    "boundaries": [
                        "offline_numpy_proxy",
                        "not_target_dataset_evaluation",
                    ],
                    "logs": ["must-not-enter-agent-context"],
                    "resultPath": str(tmp_path / "must-not-leak-smoke.json"),
                },
                "updatedAt": "2026-07-28T01:00:00+00:00",
            },
            {
                "planId": "plan-project-b",
                "researchProjectId": other_project["projectId"],
                "experimentName": other_project["name"],
                "title": "其他项目计划",
                "status": "draft",
            },
        ]
    }
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_load_experiment_plan_store",
        lambda _team_id: plan_store,
    )

    context = get_research_project_agent_task_context(
        team["teamId"],
        project["projectId"],
        started["task"]["taskId"],
    )
    encoded = json.dumps(context, ensure_ascii=False).lower()

    assert context["task"]["taskKind"] == "experiment_design"
    assert context["experiment"]["planCount"] == 1
    assert context["experiment"]["plans"][0]["planId"] == "plan-project-a"
    assert context["experiment"]["plans"][0]["fullRunResult"] == {
        "resultId": "full-result-a",
        "status": "passed",
        "metricName": "accuracy",
        "metricValue": "0.91",
        "delta": "+0.02",
    }
    assert context["experiment"]["plans"][0]["smokeRun"] == {
        "resultId": "smoke-run-a",
        "status": "needs_review",
        "adapter": "predictive_coding_reconstruction_proxy",
        "seed": 42,
        "decisionHint": "accept",
        "metrics": {
            "decisionConfidence": 0.8,
            "baseline.reconstruction_mse": 0.025838,
            "baseline.masked_region_mse": 0.114479,
            "variant.reconstruction_mse": 0.007935,
            "variant.masked_region_mse": 0.034923,
            "delta.mse_improvement": 0.017903,
            "delta.reconstruction_mse_delta": 0.017903,
            "threshold.mse_improvement": 0.001,
        },
        "artifactHash": "sha256:smoke-artifact-a",
        "proxyOnly": True,
        "boundaries": [
            "offline_numpy_proxy",
            "not_target_dataset_evaluation",
        ],
        "recordedAt": "",
    }
    assert "must-not-enter-agent-context" not in encoded
    assert "plan-project-b" not in encoded
    assert "storagepath" not in encoded
    assert str(tmp_path).lower() not in encoded


def test_experiment_stage_round_selection_is_project_scoped():
    rounds = [
        {
            "stageRoundId": "round-project-a",
            "stageType": "experiment",
            "researchProjectId": "project-a",
            "status": "planning",
            "createdAt": "2026-07-28T01:00:00+00:00",
        },
        {
            "stageRoundId": "round-project-b",
            "stageType": "experiment",
            "researchProjectId": "project-b",
            "status": "planning",
            "createdAt": "2026-07-28T02:00:00+00:00",
        },
    ]

    selected = _select_experiment_stage_round(
        {"researchProjectId": "project-a"},
        rounds,
    )

    assert selected["stageRoundId"] == "round-project-a"


def _retry_lineage_fixture():
    from types import SimpleNamespace

    from core.research.workflow.contracts import PendingAction
    from core.research.workflow.models import ActorKind

    a1 = SimpleNamespace(
        run_id="run-1",
        node_id="hypothesis_design",
        node_run_id="nr-1",
        retry_of_node_run_id=None,
        attempt=1,
    )
    a2 = SimpleNamespace(
        run_id="run-1",
        node_id="hypothesis_design",
        node_run_id="nr-2",
        retry_of_node_run_id="nr-1",
        attempt=2,
    )
    attempts = {"nr-1": a1, "nr-2": a2}

    class _Repo:
        def get_attempt(self, node_run_id):
            return attempts.get(node_run_id)

    class _Store:
        def read(self, fn):
            return fn(_Repo())

    action = PendingAction(
        action_id="act-1",
        run_id="run-1",
        node_run_id="nr-2",
        node_id="hypothesis_design",
        attempt=2,
        actor_kind=ActorKind.SYSTEM,
        action_kind="agent_node",
        input_snapshot_hash="h",
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="h",
    )
    return action, _Store()


def test_formal_retry_lineage_without_tasks_falls_back_to_first_run(monkeypatch):
    """A node blocked before any agent dispatch (readiness gate) owns no
    project task in its whole retry lineage; the retry is the node's first
    real execution and must fall back to the plain start payload instead of
    failing on a missing source task (SCI-003 hypothesis_design incident)."""
    from core.web.services.team_workflow.research_runtime import real_domain_ports

    action, store = _retry_lineage_fixture()
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks."
        "get_research_project_agent_task_status",
        lambda team_id, project_id: {"tasks": []},
    )
    payload = real_domain_ports._formal_project_retry_payload(
        action,
        team_id="t",
        project_id="p",
        agent_id="agent-1",
        task_kind="hypothesis_design",
        store=store,
    )
    assert payload == {}


def test_formal_retry_lineage_with_matching_task_returns_retry_payload(monkeypatch):
    from core.web.services.team_workflow.research_runtime import real_domain_ports

    action, store = _retry_lineage_fixture()
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks."
        "get_research_project_agent_task_status",
        lambda team_id, project_id: {
            "tasks": [
                {
                    "taskId": "task-1",
                    "workflowRunId": "run-1",
                    "nodeRunId": "nr-1",
                    "agentId": "agent-1",
                    "taskKind": "hypothesis_design",
                }
            ]
        },
    )
    payload = real_domain_ports._formal_project_retry_payload(
        action,
        team_id="t",
        project_id="p",
        agent_id="agent-1",
        task_kind="hypothesis_design",
        store=store,
    )
    assert payload == {"formalRetry": True, "retryTaskId": "task-1"}


def test_formal_retry_lineage_with_ambiguous_tasks_still_fails_closed(monkeypatch):
    from core.web.services.team_workflow.research_runtime import real_domain_ports

    action, store = _retry_lineage_fixture()
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks."
        "get_research_project_agent_task_status",
        lambda team_id, project_id: {
            "tasks": [
                {
                    "taskId": "task-1",
                    "workflowRunId": "run-1",
                    "nodeRunId": "nr-1",
                    "agentId": "agent-1",
                    "taskKind": "hypothesis_design",
                },
                {
                    "taskId": "task-2",
                    "workflowRunId": "run-1",
                    "nodeRunId": "nr-1",
                    "agentId": "agent-1",
                    "taskKind": "hypothesis_design",
                },
            ]
        },
    )
    import pytest

    with pytest.raises(RuntimeError, match="missing or ambiguous"):
        real_domain_ports._formal_project_retry_payload(
            action,
            team_id="t",
            project_id="p",
            agent_id="agent-1",
            task_kind="hypothesis_design",
            store=store,
        )


def test_accepted_member_roles_expand_legacy_aliases_through_contract():
    """Task contracts name roles with legacy aliases while member tables carry
    the canonical product role id; the authoritative role contract must bridge
    them (SCI-003 hypothesis_design incident: 'experiment_planner' is a legacy
    alias of the canonical 'challenge_cup_experiment_revision')."""
    from core.web.services.team_workflow.research_project_agent_tasks import (
        _accepted_member_roles,
    )

    accepted = _accepted_member_roles(
        "experiment_planner", "challenge_cup_experiment_planner"
    )
    assert "challenge_cup_experiment_revision" in accepted
    assert "experiment_planner" in accepted
    assert "challenge_cup_experiment_planner" in accepted


def test_hypothesis_design_task_binds_canonical_role_member(tmp_path, monkeypatch):
    """A team whose member table carries the canonical product role id must
    satisfy a hypothesis_design task contract that names the legacy alias."""
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    fresh = team_service.get_team(team["teamId"])
    fresh["members"] = [
        {**member, "role": "challenge_cup_experiment_revision"}
        if member["role"] == "experiment_planner"
        else member
        for member in fresh["members"]
    ]
    team_service.update_team(team["teamId"], members=fresh["members"])
    started = start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "hypothesis_design",
            "idempotencyKey": "hyp-1",
            "workflowRunId": "run-hyp-1",
            "workflowNodeId": "hypothesis_design",
            "sourceCollectionRunId": "dprun-hyp-1",
        },
    )
    assert started["task"]["status"] == "running"


def _append_turn_journal(session_id: str, entries: list[dict]) -> None:
    """Write real turn-journal events for a task session under the tmp root."""

    from core.chat.turn_journal import append_turn_event

    for entry in entries:
        append_turn_event(
            session_service.PROJECT_ROOT,
            session_id,
            entry["turnId"],
            entry["eventType"],
            status=entry.get("status", ""),
            payload=entry.get("payload", {}),
            source=entry.get("source", "test_journal"),
        )


def _final_answer_item_entry(turn_id: str, text: str) -> dict:
    return {
        "turnId": turn_id,
        "eventType": "assistant_item_committed",
        "payload": {
            "kind": "assistant_message",
            "channel": "answer",
            "phase": "final_answer",
            "status": "completed",
            "terminal": True,
            "text": text,
        },
    }


def _turn_completed_entry(turn_id: str, summary: str = "") -> dict:
    return {
        "turnId": turn_id,
        "eventType": "turn_completed",
        "status": "completed",
        "payload": {"resultStatus": "completed", "summary": summary},
    }


def _ready_session_detail(_session_id: str, **_kwargs):
    return {
        "status": "ready",
        "currentPhase": "ready",
        "activeTask": None,
    }


def _start_design_task(team, project, key: str):
    return start_research_project_agent_task(
        team["teamId"],
        project["projectId"],
        {
            "taskKind": "experiment_design",
            "idempotencyKey": key,
        },
    )


def test_reconcile_completes_task_from_session_final_turn_when_refs_missing(
    tmp_path, monkeypatch
):
    """SCI-091 回归：围栏写回拒绝盖章但 turn 已完成且有最终正文时，
    任务按会话终 turn 证据判 completed，而不是永远 incomplete。"""
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    started = _start_design_task(team, project, "design-session-final-1")
    session_id = started["task"]["sessionId"]
    _append_turn_journal(
        session_id,
        [
            _final_answer_item_entry("turn-1", "假设集边界说明与最终结论正文。"),
            _turn_completed_entry("turn-1", "假设集边界说明与最终结论正文。"),
        ],
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        _ready_session_detail,
    )

    summary = reconcile_research_project_agent_task_statuses(
        team["teamId"],
        project["projectId"],
    )

    assert summary["reconciled"] == 1
    assert summary["outcomes"][0]["status"] == "completed"
    assert summary["outcomes"][0]["resultSource"] == "session_final_turn"
    status = get_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
    )
    assert status["activeTasks"] == []
    assert status["tasks"][0]["status"] == "completed"
    assert status["tasks"][0]["failureCode"] == ""
    assert status["tasks"][0]["resultRefs"] == [
        f"session-final-turn:{session_id}:turn-1"
    ]
    assert status["tasks"][0]["resultSource"] == "session_final_turn"
    # 已按会话终 turn 终结的任务不再反复进入 reconcile 目标集。
    repeat = reconcile_research_project_agent_task_statuses(
        team["teamId"],
        project["projectId"],
    )
    assert repeat["checked"] == 0


def test_reconcile_keeps_incomplete_when_final_turn_has_no_answer_text(
    tmp_path, monkeypatch
):
    """turn completed 但没有非空最终 assistant 正文时，防呆不放松。"""
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    started = _start_design_task(team, project, "design-session-empty-text-1")
    _append_turn_journal(
        started["task"]["sessionId"],
        [
            _final_answer_item_entry("turn-1", ""),
            _turn_completed_entry("turn-1", ""),
        ],
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        _ready_session_detail,
    )

    reconcile_research_project_agent_task_statuses(
        team["teamId"],
        project["projectId"],
    )

    status = get_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
    )
    assert status["tasks"][0]["status"] == "incomplete"
    assert status["tasks"][0]["failureCode"] == "task_result_not_recorded"
    assert status["tasks"][0]["resultRefs"] == []
    assert status["tasks"][0]["resultSource"] == ""


def test_reconcile_keeps_incomplete_when_latest_terminal_turn_failed(
    tmp_path, monkeypatch
):
    """最新终态 turn 是 failed 时，回退不得把失败会话洗成 completed。"""
    team, project, _agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    started = _start_design_task(team, project, "design-session-failed-turn-1")
    _append_turn_journal(
        started["task"]["sessionId"],
        [
            _final_answer_item_entry("turn-1", "中间轮有正文但不终态。"),
            _turn_completed_entry("turn-1", "中间轮有正文但不终态。"),
            {
                "turnId": "turn-2",
                "eventType": "turn_failed",
                "status": "failed_runtime",
                "payload": {"errorType": "runtime_error", "summary": ""},
            },
        ],
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        _ready_session_detail,
    )

    reconcile_research_project_agent_task_statuses(
        team["teamId"],
        project["projectId"],
    )

    status = get_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
    )
    assert status["tasks"][0]["status"] == "incomplete"
    assert status["tasks"][0]["failureCode"] == "task_result_not_recorded"
    assert status["tasks"][0]["resultRefs"] == []
    assert status["tasks"][0]["resultSource"] == ""


def test_reconcile_stamped_result_refs_take_precedence_over_session_final_turn(
    tmp_path, monkeypatch
):
    """writeback 盖章路径优先：refs 有值时保持原路径且不留回退审计位。"""
    team, project, agents = _team_project_and_agents(tmp_path, monkeypatch)
    _accepted_submitter(monkeypatch)
    started = _start_design_task(team, project, "design-stamped-refs-1")
    task_id = started["task"]["taskId"]
    _append_turn_journal(
        started["task"]["sessionId"],
        [
            _final_answer_item_entry("turn-1", "已写回计划后的最终正文。"),
            _turn_completed_entry("turn-1", "已写回计划后的最终正文。"),
        ],
    )
    root = team_workflow_orchestration_service.resolve_research_project_workspace_root(
        team["teamId"],
        project["projectId"],
    )
    team_workflow_orchestration_service._write_json(
        root / "experiment_plans" / "index.json",
        {
            "schemaVersion": 1,
            "storeKind": team_workflow_orchestration_service.EXPERIMENT_PLAN_STORE_KIND,
            "teamId": team["teamId"],
            "activePlanId": "plan-stamped",
            "plans": [
                {
                    "planId": "plan-stamped",
                    "researchProjectId": project["projectId"],
                    "createdByAgent": agents["experiment_planner"]["agentId"],
                    "createdFromTaskId": task_id,
                    "createdAt": "9999-07-29T00:01:00+00:00",
                    "updatedAt": "9999-07-29T00:01:00+00:00",
                    "status": "draft",
                }
            ],
        },
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        _ready_session_detail,
    )

    summary = reconcile_research_project_agent_task_statuses(
        team["teamId"],
        project["projectId"],
    )

    assert summary["reconciled"] == 1
    assert "resultSource" not in summary["outcomes"][0]
    status = get_research_project_agent_task_status(
        team["teamId"],
        project["projectId"],
    )
    assert status["tasks"][0]["status"] == "completed"
    assert status["tasks"][0]["resultRefs"] == ["plan-stamped"]
    assert status["tasks"][0]["resultSource"] == ""
