from __future__ import annotations

import pytest

from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import register_or_resolve
from core.web.services.team_workflow import research_project_agent_tasks
from core.web.services.team_workflow.research_runtime import (
    agent_node_execution,
    agent_task_artifact_builder,
    external_agent_task_reconciliation,
    hypothesis_scoped_execution,
    workflow_artifact_store,
)
from core.web.services.team_workflow.research_runtime.agent_node_execution import (
    start_agent_node_execution,
)
from core.web.services.team_workflow.research_runtime.hypothesis_scoped_execution import (
    record_candidate_fragment_and_maybe_aggregate,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def _registered_workflow_version_id() -> str:
    """Pin fixture runs like production run creation does (fail-closed registry)."""

    return register_or_resolve(build_challenge_cup_workflow_definition()).workflowVersionId


def _task(candidate_id: str) -> dict:
    return {
        "task": {
            "taskId": f"task-{candidate_id}",
            "taskKind": "hypothesis_design",
            "teamId": "team-1",
            "researchProjectId": "project-1",
            "workflowRunId": "run-1",
            "workflowNodeId": "hypothesis_design",
            "nodeRunId": "node-run-1",
            "sourceCollectionRunId": "source-1",
            "selectionId": "selection-1",
            "candidateId": candidate_id,
            "subtaskId": f"node-run-1:selection-1:{candidate_id}",
            "sessionId": f"child-{candidate_id}",
            "sessionAttempt": 1,
        },
        "hypothesisInput": {
            "status": "ready",
            "allowedEvidenceRefs": ["counter-1"],
        },
    }


def _fragment(candidate_id: str) -> dict:
    return {
        "statement": f"statement {candidate_id}",
        "mechanism": f"mechanism {candidate_id}",
        "novelty_basis": f"novelty basis {candidate_id}",
        "predictions": [f"prediction {candidate_id}"],
        "boundary_conditions": [f"boundary {candidate_id}"],
        "falsificationCriteria": [f"falsify {candidate_id}"],
        "evidenceRefs": ["counter-1"],
        "counterEvidenceRefs": ["counter-1"],
        "scores": {
            "novelty": 0.8,
            "competitionFit": 0.7,
            "falsifiability": 0.9,
            "evidenceSupport": 0.6,
            "feasibility": 0.75,
        },
    }


def test_load_fan_out_reads_selection_and_candidates_from_current_run(
    monkeypatch,
) -> None:
    observed: dict[str, str] = {}

    def chain_state(_team_id, _question_id, **kwargs):
        observed["chain_run_id"] = str(kwargs.get("workflow_run_id") or "")
        return {"selectionId": "selection-1"}

    def get_selection(_team_id, _selection_id):
        return {
            "selection": {
                "selectionId": "selection-1",
                "questionId": "SCI-096",
                "workflowRunId": "run-1",
                "selectedCandidateIds": ["H1"],
            }
        }

    def list_candidates(_team_id, *, question_id, workflow_run_id):
        observed["candidate_run_id"] = workflow_run_id
        assert question_id == "SCI-096"
        return {
            "candidates": [
                {
                    "candidateId": "H1",
                    "workflowRunId": workflow_run_id,
                    "statement": "statement H1",
                }
            ]
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.hypothesis_first_chain.chain_state",
        chain_state,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.hypothesis_selection.get_hypothesis_selection",
        get_selection,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.hypothesis_first_chain.list_hypothesis_candidates",
        list_candidates,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.challenge_question_runs.get_challenge_question_run_detail",
        lambda *_args, **_kwargs: {"output": {}},
    )

    result = hypothesis_scoped_execution.load_hypothesis_fan_out_input(
        {
            "teamId": "team-1",
            "runId": "run-1",
            "inputSnapshot": {"questionId": "SCI-096"},
        }
    )

    assert result["selectedCandidateIds"] == ["H1"]
    assert observed == {"chain_run_id": "run-1", "candidate_run_id": "run-1"}


def test_agent_and_reconciliation_chain_reads_stay_on_current_run(monkeypatch) -> None:
    observed: list[tuple[str, str, str]] = []

    def chain_state(team_id, question_id, **kwargs):
        workflow_run_id = str(kwargs.get("workflow_run_id") or "")
        observed.append((team_id, question_id, workflow_run_id))
        return {"selectionId": workflow_run_id}

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.hypothesis_first_chain.chain_state",
        chain_state,
    )
    record = {
        "runId": "run-current",
        "workflowRunId": "run-stale",
        "teamId": "team-1",
        "inputSnapshot": {
            "questionId": "SCI-096",
            "workflowRunId": "run-stale",
        },
        "taskBundles": [],
    }
    assert agent_node_execution._hypothesis_chain_state(record) == {
        "selectionId": "run-current"
    }

    monkeypatch.setattr(
        external_agent_task_reconciliation,
        "resolve_hypothesis_scope_activation",
        lambda _record, *, chain_state: {
            "fanOutEnabled": bool(chain_state.get("selectionId")),
            "selectionRequired": False,
        },
    )
    assert external_agent_task_reconciliation._candidate_scope_applies(record)
    assert observed == [
        ("team-1", "SCI-096", "run-current"),
        ("team-1", "SCI-096", "run-current"),
    ]


def test_hypothesis_chain_read_fails_closed_without_run_id(monkeypatch) -> None:
    def unexpected_question_wide_read(*_args, **_kwargs):
        raise AssertionError("run-scoped execution must not read question-wide state")

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.hypothesis_first_chain.chain_state",
        unexpected_question_wide_read,
    )
    assert agent_node_execution._hypothesis_chain_state(
        {
            "teamId": "team-1",
            "inputSnapshot": {"questionId": "SCI-096"},
        }
    ) == {}


def test_fragments_close_independent_subtasks_and_last_one_fans_in(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        hypothesis_scoped_execution,
        "_current_selection",
        lambda *_args: {
            "selectionId": "selection-1",
            "selectedCandidateIds": ["H1", "H2"],
        },
    )
    updates: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        research_project_agent_tasks,
        "update_research_project_agent_task_status",
        lambda _team, _project, task_id, *, status, result_refs: updates.append(
            (task_id, list(result_refs))
        )
        or {"taskId": task_id, "status": status},
    )
    store = WorkflowRunStore(tmp_path / "runs")
    store.create_run(
        {
            "runId": "run-1",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": _registered_workflow_version_id(),
            "teamId": "team-1",
            "projectId": "project-1",
            "inputSnapshot": {"questionId": "SCI-096"},
            "taskBundles": [
                {
                    "bundleId": "bundle-1",
                    "parentNodeRunId": "node-run-1",
                    "status": "running",
                    "subtasks": [
                        {
                            "subtaskId": "node-run-1:selection-1:H1",
                            "scope": {
                                "selectionId": "selection-1",
                                "candidateId": "H1",
                            },
                            "attempt": 1,
                            "status": "running",
                            "taskId": "task-H1",
                            "sessionId": "child-H1",
                            "outputArtifactRefs": [],
                        },
                        {
                            "subtaskId": "node-run-1:selection-1:H2",
                            "scope": {
                                "selectionId": "selection-1",
                                "candidateId": "H2",
                            },
                            "attempt": 1,
                            "status": "running",
                            "taskId": "task-H2",
                            "sessionId": "child-H2",
                            "outputArtifactRefs": [],
                        },
                    ],
                }
            ],
        }
    )

    first = record_candidate_fragment_and_maybe_aggregate(
        team_id="team-1",
        task_context=_task("H1"),
        payload=_fragment("H1"),
        store=store,
    )
    assert external_agent_task_reconciliation._candidate_fan_out_ready(
        store.get_run("run-1"),
        {"nodeId": "hypothesis_design", "nodeRunId": "node-run-1"},
    ) is False
    second = record_candidate_fragment_and_maybe_aggregate(
        team_id="team-1",
        task_context=_task("H2"),
        payload=_fragment("H2"),
        store=store,
    )

    assert first["status"] == "fragment_recorded"
    assert first["taskBundle"]["subtasks"][0]["status"] == "succeeded"
    assert first["taskBundle"]["subtasks"][1]["status"] == "running"
    assert second["status"] == "aggregated"
    assert second["hypothesisSetRef"]
    assert second["taskBundle"]["aggregationArtifactRefs"] == [
        second["hypothesisSetRef"]
    ]
    assert external_agent_task_reconciliation._candidate_fan_out_ready(
        store.get_run("run-1"),
        {"nodeId": "hypothesis_design", "nodeRunId": "node-run-1"},
    ) is True
    assert [
        item["candidateId"]
        for item in agent_task_artifact_builder._hypothesis_set_payload(
            store.get_run("run-1"),
            {"nodeRunId": "node-run-1"},
        )["candidates"]
    ] == ["H1", "H2"]
    assert [
        item["candidateId"]
        for item in workflow_artifact_store.list_workflow_artifacts(
            "team-1", kind="hypothesis_set", workflow_run_id="run-1"
        )[0]["payload"]["candidates"]
    ] == ["H1", "H2"]
    assert {task_id for task_id, _refs in updates} == {"task-H1", "task-H2"}


def test_agent_node_execution_fans_selection_into_ordered_child_tasks(
    tmp_path, monkeypatch
) -> None:
    store = WorkflowRunStore(tmp_path / "runs")
    record = store.create_run(
        {
            "runId": "run-1",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": _registered_workflow_version_id(),
            "teamId": "team-1",
            "projectId": "project-1",
            "threadId": "thread-1",
            "inputSnapshot": {
                "questionId": "SCI-096",
                "researchObjectiveContract": {
                    "question": "question",
                    "hypothesisFirst": True,
                },
                "budgetPolicy": {"maxParallelTasks": 3},
                "workflowSessionScopeV3": {"hypothesis_design": "on"},
            },
            "bindingSnapshots": [
                {
                    "nodeId": "hypothesis_design",
                    "agentId": "agent-1",
                    "roleKey": "experiment_planner",
                }
            ],
            "nodeRuns": [
                {
                    "nodeRunId": "node-run-1",
                    "nodeId": "hypothesis_design",
                    "agentId": "agent-1",
                    "attempt": 1,
                    "status": "ready",
                    "inputSnapshotHash": "a" * 64,
                    "artifactRefs": [],
                    "checkpointId": "checkpoint-1",
                }
            ],
            "taskBundles": [],
            "modelRoutingDecisions": [],
            "budgetReservations": [],
            "events": [],
            "status": "running",
        }
    )
    monkeypatch.setattr(
        agent_node_execution,
        "load_hypothesis_fan_out_input",
        lambda *_args, **_kwargs: {
            "selection": {
                "selectionId": "selection-1",
                "selectedCandidateIds": ["H1", "H2"],
            },
            "selectionId": "selection-1",
            "selectedCandidateIds": ["H1", "H2"],
            "candidateSnapshots": [
                {"candidateId": "H1", "statement": "claim H1"},
                {"candidateId": "H2", "statement": "claim H2"},
            ],
        },
    )
    monkeypatch.setattr(
        agent_node_execution,
        "select_model_route",
        lambda *_args, **_kwargs: {
            "decisionId": "route-1",
            "nodeRunId": "node-run-1",
            "modelRef": "model-1",
            "purpose": "hypothesis",
            "estimatedCost": 1.0,
            "escalationReason": "",
        },
    )
    monkeypatch.setattr(
        agent_node_execution,
        "reserve_node_budget",
        lambda *_args, **_kwargs: {"reservationId": "budget-1"},
    )
    starts: list[dict] = []

    def fake_start(_store, current, **kwargs):
        candidate_id = kwargs["payload"]["candidateId"]
        started = {
            "agentId": "agent-1",
            "taskId": f"task-{candidate_id}",
            "sessionId": f"child-{candidate_id}",
            "sessionAttempt": 1,
            "turn": {"turnId": f"turn-{candidate_id}"},
            "chatRoute": f"/chat?session=child-{candidate_id}",
        }
        starts.append(started)
        return current, started

    monkeypatch.setattr(agent_node_execution, "_start_external_task", fake_start)
    monkeypatch.setattr(
        agent_node_execution, "_require_canonical_task_session", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        agent_node_execution, "start_node_execution", lambda *_args, **_kwargs: {}
    )

    with pytest.raises(
        agent_node_execution.AgentNodeExecutionError,
        match="maxConcurrency must be a positive integer",
    ):
        start_agent_node_execution(
            store,
            record=record,
            node_id="hypothesis_design",
            payload={"idempotencyKey": "dispatch-invalid", "maxConcurrency": "2"},
        )

    result = start_agent_node_execution(
        store,
        record=record,
        node_id="hypothesis_design",
        payload={"idempotencyKey": "dispatch-1", "maxConcurrency": 2},
    )

    assert result["taskIds"] == ["task-H1", "task-H2"]
    assert [
        item["scope"]["candidateId"] for item in result["taskBundle"]["subtasks"]
    ] == ["H1", "H2"]
    assert result["taskBundle"]["maxConcurrency"] == 2
    assert [item["sessionId"] for item in result["scopedSessions"]] == [
        "child-H1",
        "child-H2",
    ]
    assert len(starts) == 2


@pytest.mark.parametrize("scope_mode", ["on", "shadow"])
def test_agent_node_execution_uses_bounded_legacy_fallback_without_selection(
    tmp_path, monkeypatch, scope_mode
) -> None:
    store = WorkflowRunStore(tmp_path / "runs")
    record = store.create_run(
        {
            "runId": "run-legacy-1",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": _registered_workflow_version_id(),
            "teamId": "team-1",
            "projectId": "project-1",
            "threadId": "thread-legacy-1",
            "inputSnapshot": {
                "teamId": "team-1",
                "projectId": "project-1",
                "questionId": "SCI-LEGACY-1",
                "researchObjectiveContract": {"question": "legacy question"},
                "budgetPolicy": {"maxParallelTasks": 3},
                "workflowSessionScopeV3": {"hypothesis_design": scope_mode},
            },
            "bindingSnapshots": [
                {
                    "nodeId": "hypothesis_design",
                    "agentId": "agent-1",
                    "roleKey": "experiment_planner",
                }
            ],
            "nodeRuns": [
                {
                    "nodeRunId": "node-run-legacy-1",
                    "nodeId": "hypothesis_design",
                    "agentId": "agent-1",
                    "attempt": 1,
                    "status": "ready",
                    "inputSnapshotHash": "a" * 64,
                    "artifactRefs": [],
                    "checkpointId": "checkpoint-legacy-1",
                }
            ],
            "taskBundles": [],
            "modelRoutingDecisions": [],
            "budgetReservations": [],
            "events": [],
            "status": "running",
        }
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.hypothesis_first_chain.chain_state",
        lambda *_args, **_kwargs: {},
    )

    def unexpected_fan_out(_record):
        raise AssertionError("legacy compatibility must not load candidate fan-out")

    monkeypatch.setattr(
        agent_node_execution,
        "load_hypothesis_fan_out_input",
        unexpected_fan_out,
    )
    monkeypatch.setattr(
        agent_node_execution,
        "select_model_route",
        lambda *_args, **_kwargs: {
            "decisionId": "route-legacy-1",
            "nodeRunId": "node-run-legacy-1",
            "modelRef": "model-1",
            "purpose": "hypothesis",
            "estimatedCost": 1.0,
            "escalationReason": "",
        },
    )
    monkeypatch.setattr(
        agent_node_execution,
        "reserve_node_budget",
        lambda *_args, **_kwargs: {"reservationId": "budget-legacy-1"},
    )
    monkeypatch.setattr(
        agent_node_execution,
        "_start_external_task",
        lambda _store, current, **_kwargs: (
            current,
            {
                "agentId": "agent-1",
                "taskId": "task-legacy-1",
                "sessionId": "session-legacy-1",
                "sessionAttempt": 1,
                "turn": {"turnId": "turn-legacy-1"},
                "chatRoute": "/chat?session=session-legacy-1",
            },
        ),
    )
    monkeypatch.setattr(
        agent_node_execution,
        "_require_canonical_task_session",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        agent_node_execution,
        "start_node_execution",
        lambda *_args, **_kwargs: {},
    )

    result = start_agent_node_execution(
        store,
        record=record,
        node_id="hypothesis_design",
        payload={"idempotencyKey": "legacy-dispatch-1"},
    )

    assert result["taskId"] == "task-legacy-1"
    assert result["sessionScopeFallback"] == {
        "status": "compatibility",
        "reason": "legacy_non_hypothesis_first_without_authoritative_selection",
        "mode": scope_mode,
    }
    assert len(result["taskBundle"]["subtasks"]) == 1
    assert result["taskBundle"]["subtasks"][0]["scope"] == {
        "kind": "workflow_node_root",
        "nodeRunId": "node-run-legacy-1",
    }
    assert external_agent_task_reconciliation._candidate_fan_out_ready(
        store.get_run("run-legacy-1"),
        {"nodeId": "hypothesis_design", "nodeRunId": "node-run-legacy-1"},
    ) is True

    hypothesis_first_record = {
        **record,
        "runId": "run-hypothesis-1",
        "threadId": "thread-hypothesis-1",
        "inputSnapshot": {
            **record["inputSnapshot"],
            "researchObjectiveContract": {
                "question": "hypothesis-first question",
                "hypothesisFirst": True,
            },
        },
        "nodeRuns": [
            {
                **record["nodeRuns"][0],
                "nodeRunId": "node-run-hypothesis-1",
            }
        ],
        "taskBundles": [],
    }
    store.create_run(hypothesis_first_record)
    monkeypatch.setattr(
        agent_node_execution,
        "load_hypothesis_fan_out_input",
        lambda _record: (_ for _ in ()).throw(
            ValueError("hypothesis_design requires a current hypothesis selection")
        ),
    )
    with pytest.raises(
        agent_node_execution.AgentNodeExecutionError,
        match="requires a current hypothesis selection",
    ) as exc_info:
        start_agent_node_execution(
            store,
            record=store.get_run("run-hypothesis-1"),
            node_id="hypothesis_design",
            payload={"idempotencyKey": "hypothesis-dispatch-1"},
        )
    assert exc_info.value.code == "hypothesis_selection_invalid"
