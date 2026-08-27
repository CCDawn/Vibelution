import json

from core.web.services import (
    agent_directory_service,
    research_loop_service,
    runtime_scene_service,
    session_service,
    team_workflow_orchestration_service,
)
from tools.challenge_cup_operations_tools import (
    challenge_cup_experiment_context_tool,
    challenge_cup_experiment_writeback_tool,
    challenge_cup_iteration_context_tool,
    challenge_cup_iteration_writeback_tool,
    challenge_cup_versioning_context_tool,
    challenge_cup_versioning_writeback_tool,
    research_knowledge_collection_tool,
)


def _canonical_agent_runtime(role_key: str) -> dict:
    agent_id = f"agent-{role_key}"
    return {
        "agentId": agent_id,
        "sessionId": f"session-{role_key}",
        "turnId": "turn-1",
        "agent": {
            "agentId": agent_id,
            "roleKey": role_key,
            "metadata": {
                "challengeCupTeamId": "research-team",
                "challengeCupTeamManagedVersion": 2,
                "challengeCupTeamRole": role_key,
                "challengeCupTeamRoleKey": role_key,
            },
        },
    }


def _canonical_agent_record(role_key: str) -> dict:
    return _canonical_agent_runtime(role_key)["agent"]


def test_canonical_managed_agents_fail_closed_without_formal_task_binding(
    monkeypatch,
):
    runtime = {"value": _canonical_agent_runtime("challenge_cup_search")}
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: runtime["value"],
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda *_args, **_kwargs: {},
    )

    def unexpected_write(*_args, **_kwargs):
        raise AssertionError("canonical direct sessions must not reach ledger writes")

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "create_experiment_plan",
        unexpected_write,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "register_experiment_smoke_result",
        unexpected_write,
    )
    monkeypatch.setattr(
        research_loop_service,
        "record_research_loop_evidence",
        unexpected_write,
    )

    cases = (
        ("challenge_cup_search", "experiment", "create_plan"),
        ("challenge_cup_extractor", "experiment", "create_plan"),
        ("challenge_cup_knowledge_manager", "experiment", "create_plan"),
        (
            "challenge_cup_execution_steward",
            "experiment",
            "register_smoke_result",
        ),
        ("challenge_cup_experiment_revision", "experiment", "create_plan"),
        ("challenge_cup_evaluator", "iteration", "record_evidence"),
    )
    for role_key, surface, operation in cases:
        runtime["value"] = _canonical_agent_runtime(role_key)
        if surface == "experiment":
            raw = challenge_cup_experiment_writeback_tool(
                team_id="research-team",
                operation=operation,
                plan_id="plan-1",
                payload_json='{"status":"passed"}',
            )
        else:
            raw = challenge_cup_iteration_writeback_tool(
                team_id="research-team",
                operation=operation,
                loop_id="loop-1",
                payload_json='{"evidenceType":"review","summary":"bounded"}',
            )
        result = json.loads(raw)
        assert result["status"] == "error", role_key
        assert result["errorType"] in {
            "formal_task_binding_required",
            "role_operation_denied",
        }, role_key


def test_canonical_bound_experiment_writeback_enforces_role_operation_matrix(
    monkeypatch,
):
    runtime = {
        "value": _canonical_agent_runtime("challenge_cup_experiment_revision")
    }
    writes: list[tuple[str, str]] = []
    task_kinds = {
        "task-revision": "experiment_design",
        "task-evaluator": "experiment_evidence_review",
        "task-execution": "experiment_evidence_review",
    }
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: runtime["value"],
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "require_research_project_agent_task",
        lambda _team_id, project_id, task_id, **_kwargs: {
            "taskId": task_id,
            "taskKind": task_kinds[task_id],
            "agentId": runtime["value"]["agentId"],
            "roleKey": runtime["value"]["agent"]["roleKey"],
            "researchProjectId": project_id,
        },
        raising=False,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "require_research_project_experiment_plan",
        lambda *_args, **_kwargs: {},
        raising=False,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "create_experiment_plan",
        lambda _team_id, payload: writes.append(("create_plan", payload["createdByAgent"]))
        or {
            "plan": {
                "planId": "plan-1",
                "researchProjectId": payload["researchProjectId"],
            }
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "register_experiment_full_run_result",
        lambda _team_id, _plan_id, payload: writes.append(
            ("register_full_run_result", payload["recordedByAgent"])
        )
        or {"fullRunResult": {"fullRunResultId": "full-1"}},
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "update_research_project_agent_task_status",
        lambda _team_id, _project_id, task_id, **kwargs: {
            "taskId": task_id,
            "status": kwargs["status"],
        },
    )

    def call(role_key: str, task_id: str, operation: str) -> dict:
        runtime["value"] = _canonical_agent_runtime(role_key)
        return json.loads(
            challenge_cup_experiment_writeback_tool(
                team_id="research-team",
                research_project_id="project-1",
                task_id=task_id,
                operation=operation,
                plan_id="plan-1",
                payload_json='{"status":"passed"}',
                recorded_by_agent=runtime["value"]["agentId"],
            )
        )

    assert call(
        "challenge_cup_experiment_revision",
        "task-revision",
        "create_plan",
    )["status"] == "ok"
    assert call(
        "challenge_cup_experiment_revision",
        "task-revision",
        "register_full_run_result",
    )["errorType"] == "role_operation_denied"
    assert call(
        "challenge_cup_evaluator",
        "task-evaluator",
        "create_plan",
    )["errorType"] == "role_operation_denied"
    assert call(
        "challenge_cup_evaluator",
        "task-evaluator",
        "register_full_run_result",
    )["status"] == "ok"
    assert call(
        "challenge_cup_execution_steward",
        "task-execution",
        "register_full_run_result",
    )["status"] == "ok"
    assert call(
        "challenge_cup_execution_steward",
        "task-execution",
        "create_plan",
    )["errorType"] == "role_operation_denied"
    assert [item[0] for item in writes] == [
        "create_plan",
        "register_full_run_result",
        "register_full_run_result",
    ]


def test_canonical_runtime_ignores_untrusted_actor_label(monkeypatch):
    from core.web.services.team_workflow.research_runtime import (
        challenge_cup_maintenance_fence,
        problem_understanding_artifact_writer,
    )

    runtime = _canonical_agent_runtime("challenge_cup_search")
    task = {
        "taskId": "task-1",
        "taskKind": "problem_understanding",
        "agentId": runtime["agentId"],
        "roleKey": runtime["agent"]["roleKey"],
        "researchProjectId": "project-1",
        "sessionId": runtime["sessionId"],
        "turn": {"turnId": runtime["turnId"]},
    }
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **_kwargs: (
            runtime["agent"] if agent_id == runtime["agentId"] else None
        ),
    )
    monkeypatch.setattr(
        challenge_cup_maintenance_fence,
        "assert_writes_allowed",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event",
        lambda *_args, **_kwargs: {"accepted": True},
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_context",
        lambda *_args, **_kwargs: {
            "task": task,
            "researchProjectId": task["researchProjectId"],
        },
    )
    monkeypatch.setattr(
        problem_understanding_artifact_writer,
        "write_problem_understanding_artifact",
        lambda **_kwargs: {
            "contentHash": "artifact-hash",
            "artifact": {"recordId": "problem-understanding-1"},
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "update_research_project_agent_task_status",
        lambda _team_id, _project_id, task_id, **kwargs: {
            "taskId": task_id,
            "status": kwargs["status"],
            "resultRefs": kwargs["result_refs"],
        },
    )

    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-1",
            operation="record_problem_understanding",
            payload_json="{}",
            recorded_by_agent=(
                f"A015 搜索 Agent ({runtime['agentId']})"
            ),
        )
    )

    assert result["status"] == "ok", result
    assert result["task"]["resultRefs"] == ["artifact-hash"]
    assert result["task"]["status"] == "running"


def test_canonical_bound_iteration_writeback_enforces_role_operation_matrix(
    monkeypatch,
):
    runtime = {
        "value": _canonical_agent_runtime("challenge_cup_experiment_revision")
    }
    writes: list[tuple[str, str]] = []
    task_kinds = {
        "task-revision": "iteration_decision",
        "task-evaluator": "experiment_evidence_review",
    }
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: runtime["value"],
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "require_research_project_agent_task",
        lambda _team_id, project_id, task_id, **_kwargs: {
            "taskId": task_id,
            "taskKind": task_kinds[task_id],
            "agentId": runtime["value"]["agentId"],
            "roleKey": runtime["value"]["agent"]["roleKey"],
            "researchProjectId": project_id,
        },
        raising=False,
    )
    monkeypatch.setattr(
        research_loop_service,
        "require_research_loop",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        research_loop_service,
        "record_research_loop_evidence",
        lambda _team_id, _loop_id, payload: writes.append(
            ("record_evidence", payload["recordedByAgent"])
        )
        or {"evidence": {"evidenceId": "evidence-1"}},
    )
    monkeypatch.setattr(
        research_loop_service,
        "record_research_loop_decision",
        lambda _team_id, _loop_id, payload: writes.append(
            ("record_decision", payload["decidedByAgent"])
        )
        or {"decision": {"decisionId": "decision-1"}},
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "update_research_project_agent_task_status",
        lambda _team_id, _project_id, task_id, **kwargs: {
            "taskId": task_id,
            "status": kwargs["status"],
        },
    )

    def call(role_key: str, task_id: str, operation: str) -> dict:
        runtime["value"] = _canonical_agent_runtime(role_key)
        payload = (
            '{"decision":"repair_and_repeat","rationale":"bounded"}'
            if operation == "record_decision"
            else '{"evidenceType":"review","summary":"bounded"}'
        )
        return json.loads(
            challenge_cup_iteration_writeback_tool(
                team_id="research-team",
                research_project_id="project-1",
                task_id=task_id,
                loop_id="loop-1",
                operation=operation,
                payload_json=payload,
                recorded_by_agent=runtime["value"]["agentId"],
            )
        )

    assert call(
        "challenge_cup_experiment_revision",
        "task-revision",
        "record_decision",
    )["status"] == "ok"
    assert call(
        "challenge_cup_evaluator",
        "task-evaluator",
        "record_evidence",
    )["status"] == "ok"
    assert call(
        "challenge_cup_evaluator",
        "task-evaluator",
        "record_decision",
    )["errorType"] == "role_operation_denied"
    assert call(
        "challenge_cup_execution_steward",
        "task-evaluator",
        "record_evidence",
    )["errorType"] == "role_operation_denied"
    assert [item[0] for item in writes] == ["record_decision", "record_evidence"]


def test_directory_only_canonical_actor_still_requires_formal_binding(monkeypatch):
    agent = _canonical_agent_record("challenge_cup_experiment_revision")
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {})
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **_kwargs: agent if agent_id == agent["agentId"] else None,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "create_experiment_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("directory-only canonical actor must not reach writes")
        ),
    )

    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            operation="create_plan",
            recorded_by_agent=agent["agentId"],
        )
    )

    assert result["status"] == "error"
    assert result["errorType"] == "formal_task_binding_required"


def test_directory_only_canonical_actor_rejects_explicit_formal_task(monkeypatch):
    agent = _canonical_agent_record("challenge_cup_experiment_revision")
    writes = []
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {})
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **_kwargs: agent if agent_id == agent["agentId"] else None,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "require_research_project_agent_task",
        lambda _team_id, project_id, task_id, **_kwargs: {
            "taskId": task_id,
            "taskKind": "experiment_design",
            "agentId": agent["agentId"],
            "roleKey": agent["roleKey"],
            "researchProjectId": project_id,
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "create_experiment_plan",
        lambda _team_id, payload: writes.append(dict(payload))
        or {
            "plan": {
                "planId": "plan-1",
                "researchProjectId": payload["researchProjectId"],
            }
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "update_research_project_agent_task_status",
        lambda _team_id, _project_id, task_id, **kwargs: {
            "taskId": task_id,
            "status": kwargs["status"],
        },
    )

    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-1",
            operation="create_plan",
            recorded_by_agent=agent["agentId"],
        )
    )

    assert result["status"] == "error"
    assert result["errorType"] == "formal_task_binding_required"
    assert writes == []


def test_directory_canonical_actor_cannot_hide_behind_legacy_runtime(monkeypatch):
    agent = _canonical_agent_record("challenge_cup_experiment_revision")
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "agent-legacy-runtime",
            "agent": {
                "agentId": "agent-legacy-runtime",
                "roleKey": "legacy_experiment_writer",
            },
        },
    )
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **_kwargs: agent if agent_id == agent["agentId"] else None,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "create_experiment_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("managed actor identity conflict must not reach writes")
        ),
    )

    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-1",
            operation="create_plan",
            recorded_by_agent=agent["agentId"],
        )
    )

    assert result["status"] == "error"
    assert result["errorType"] == "role_operation_denied"


def test_managed_runtime_rejects_incomplete_unknown_and_conflicting_roles(
    monkeypatch,
):
    runtime = {
        "value": _canonical_agent_runtime("challenge_cup_experiment_revision")
    }
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: runtime["value"],
    )

    cases = []
    missing_team = _canonical_agent_runtime("challenge_cup_experiment_revision")
    missing_team["agent"]["metadata"].pop("challengeCupTeamId")
    cases.append(missing_team)
    unknown_role = _canonical_agent_runtime("challenge_cup_experiment_revision")
    unknown_role["agent"]["metadata"]["challengeCupTeamRoleKey"] = "mystery_role"
    cases.append(unknown_role)
    conflicting_role = _canonical_agent_runtime("challenge_cup_experiment_revision")
    conflicting_role["agent"]["metadata"]["challengeCupTeamRole"] = (
        "challenge_cup_evaluator"
    )
    cases.append(conflicting_role)
    conflicting_legacy_role = _canonical_agent_runtime(
        "challenge_cup_experiment_revision"
    )
    conflicting_legacy_role["agent"]["metadata"]["teamRoleKey"] = (
        "challenge_cup_evaluator"
    )
    cases.append(conflicting_legacy_role)
    conflicting_team = _canonical_agent_runtime("challenge_cup_experiment_revision")
    conflicting_team["agent"]["metadata"]["teamId"] = "another-team"
    cases.append(conflicting_team)
    stale_version = _canonical_agent_runtime("challenge_cup_experiment_revision")
    stale_version["agent"]["metadata"]["challengeCupTeamManagedVersion"] = 1
    cases.append(stale_version)
    conflicting_agent = _canonical_agent_runtime("challenge_cup_experiment_revision")
    conflicting_agent["agent"]["agentId"] = "agent-other"
    cases.append(conflicting_agent)

    for candidate in cases:
        runtime["value"] = candidate
        result = json.loads(
            challenge_cup_experiment_writeback_tool(
                team_id="research-team",
                operation="create_plan",
            )
        )
        assert result["status"] == "error"
        assert result["errorType"] == "role_operation_denied"


def test_canonical_runtime_does_not_reuse_old_turn_session_task(monkeypatch):
    runtime = _canonical_agent_runtime("challenge_cup_experiment_revision")
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda *_args, **_kwargs: {
            "experimentBinding": {
                "teamId": "research-team",
                "researchProjectId": "project-1",
                "agentId": runtime["agentId"],
            }
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_status",
        lambda *_args, **_kwargs: {
            "tasks": [
                {
                    "taskId": "task-old-turn",
                    "taskKind": "experiment_design",
                    "agentId": runtime["agentId"],
                    "roleKey": "challenge_cup_experiment_revision",
                    "researchProjectId": "project-1",
                    "sessionId": runtime["sessionId"],
                    "turn": {"turnId": "turn-old"},
                    "status": "incomplete",
                    "failureCode": "task_result_not_recorded",
                    "resultRefs": [],
                }
            ]
        },
    )

    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            operation="create_plan",
        )
    )

    assert result["status"] == "error"
    assert result["errorType"] == "formal_task_binding_required"


def test_canonical_task_role_owner_must_match_runtime_role(monkeypatch):
    runtime = _canonical_agent_runtime("challenge_cup_experiment_revision")
    task_role = {"value": ""}
    writes = []
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "require_research_project_agent_task",
        lambda _team_id, project_id, task_id, **_kwargs: {
            "taskId": task_id,
            "taskKind": "experiment_design",
            "agentId": runtime["agentId"],
            "roleKey": task_role["value"],
            "researchProjectId": project_id,
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "create_experiment_plan",
        lambda _team_id, payload: writes.append(payload["createdByAgent"])
        or {"plan": {"planId": "plan-1", "researchProjectId": "project-1"}},
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "update_research_project_agent_task_status",
        lambda _team_id, _project_id, task_id, **kwargs: {
            "taskId": task_id,
            "status": kwargs["status"],
        },
    )

    missing = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-1",
            operation="create_plan",
        )
    )
    task_role["value"] = "challenge_cup_evaluator"
    mismatched = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-1",
            operation="create_plan",
        )
    )
    task_role["value"] = "experiment_planner"
    allowed = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-1",
            operation="create_plan",
        )
    )

    assert missing["errorType"] == "role_operation_denied"
    assert mismatched["errorType"] == "role_operation_denied"
    assert allowed["status"] == "ok"
    assert writes == [runtime["agentId"]]


def test_challenge_cup_experiment_tool_wraps_ledger_without_execution(monkeypatch):
    scene_events = []
    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: scene_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_experiment_planning_status",
        lambda team_id: {
            "teamId": team_id,
            "status": "ready_to_plan",
            "boundaries": {"autoExecution": False, "requiresUserDecision": True},
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "create_experiment_plan",
        lambda team_id, payload: {"teamId": team_id, "plan": payload, "boundaries": {"autoExecution": False}},
    )

    context = json.loads(challenge_cup_experiment_context_tool(team_id="research-team"))
    assert context["status"] == "ok"
    assert context["experimentPlanningStatus"]["status"] == "ready_to_plan"
    assert context["boundaries"]["autoExecution"] is False

    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            operation="create_plan",
            payload_json='{"title":"Plan A"}',
            recorded_by_agent="challenge_cup_experiment_planner",
        )
    )
    assert result["status"] == "ok"
    assert result["response"]["plan"]["title"] == "Plan A"
    assert result["response"]["plan"]["createdByAgent"] == "challenge_cup_experiment_planner"

    blocked = json.loads(challenge_cup_experiment_writeback_tool(team_id="research-team", operation="run_smoke"))
    assert blocked["status"] == "error"
    assert blocked["errorType"] == "unsupported_operation"
    assert blocked["boundaries"]["autoExecution"] is False
    blocked_events = [kwargs for args, kwargs in scene_events if len(args) >= 3 and args[2] == "tool.challenge_cup_operation.unsupported_blocked"]
    assert blocked_events
    assert blocked_events[-1]["fields"]["operation"] == "run_smoke"
    assert blocked_events[-1]["fields"]["boundary"] == "experiment_planning_ledger_only_not_training_execution"
    assert blocked_events[-1]["level"] == "warning"


def test_experiment_tool_binds_project_task_without_finishing_active_turn(
    monkeypatch,
):
    updates = []
    created_payloads = []
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_context",
        lambda team_id, project_id, task_id: {
            "teamId": team_id,
            "researchProjectId": project_id,
            "task": {
                "taskId": task_id,
                "taskKind": "experiment_design",
                "agentId": "agent-planner",
            },
            "experiment": {"plans": [], "planCount": 0},
        },
        raising=False,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "require_research_project_agent_task",
        lambda team_id, project_id, task_id, **_kwargs: {
            "taskId": task_id,
            "taskKind": "experiment_design",
            "agentId": "agent-planner",
            "researchProjectId": project_id,
        },
        raising=False,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "create_experiment_plan",
        lambda team_id, payload: created_payloads.append(dict(payload))
        or {
            "teamId": team_id,
            "plan": {
                "planId": "plan-project-1",
                "researchProjectId": payload["researchProjectId"],
            },
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "update_research_project_agent_task_status",
        lambda team_id, project_id, task_id, **kwargs: updates.append(
            (team_id, project_id, task_id, kwargs)
        )
        or {"taskId": task_id, "status": kwargs["status"]},
    )

    context = json.loads(
        challenge_cup_experiment_context_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-design-1",
        )
    )
    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-design-1",
            operation="create_plan",
            payload_json='{"title":"Project plan"}',
            recorded_by_agent="agent-planner",
        )
    )

    assert context["taskContext"]["researchProjectId"] == "project-1"
    assert result["status"] == "ok"
    assert created_payloads[0]["researchProjectId"] == "project-1"
    assert created_payloads[0]["createdByAgent"] == "agent-planner"
    assert created_payloads[0]["createdFromTaskId"] == "task-design-1"
    assert updates == [
        (
            "research-team",
            "project-1",
            "task-design-1",
            {"status": "running", "result_refs": ["plan-project-1"]},
        )
    ]
    assert result["task"]["status"] == "running"


def test_experiment_tool_allows_corrective_writeback_in_same_active_turn(
    monkeypatch,
):
    state = {"status": "running"}
    updates = []
    created_payloads = []

    def require_task(_team_id, project_id, task_id, **_kwargs):
        if state["status"] != "running":
            raise RuntimeError("Research project Agent task is no longer active.")
        return {
            "taskId": task_id,
            "taskKind": "experiment_design",
            "agentId": "agent-planner",
            "researchProjectId": project_id,
            "sessionId": "session-project-1",
            "status": state["status"],
            "turn": {"turnId": "turn-design-1"},
        }

    def update_task(_team_id, _project_id, task_id, **kwargs):
        state["status"] = kwargs["status"]
        updates.append(dict(kwargs))
        return {
            "taskId": task_id,
            "status": state["status"],
            "resultRefs": list(kwargs.get("result_refs") or []),
        }

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "require_research_project_agent_task",
        require_task,
        raising=False,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "create_experiment_plan",
        lambda team_id, payload: created_payloads.append(dict(payload))
        or {
            "teamId": team_id,
            "plan": {
                "planId": "plan-project-1",
                "researchProjectId": payload["researchProjectId"],
            },
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "update_research_project_agent_task_status",
        update_task,
    )

    first = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-design-1",
            operation="create_plan",
            payload_json='{"title":"Initial plan"}',
            recorded_by_agent="agent-planner",
        )
    )
    second = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-design-1",
            operation="create_plan",
            payload_json='{"title":"Corrected plan"}',
            recorded_by_agent="agent-planner",
        )
    )

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert [item["title"] for item in created_payloads] == [
        "Initial plan",
        "Corrected plan",
    ]
    assert updates == [
        {"status": "running", "result_refs": ["plan-project-1"]},
        {"status": "running", "result_refs": ["plan-project-1"]},
    ]
    assert state["status"] == "running"


def test_experiment_tool_infers_project_task_from_current_runtime(
    monkeypatch,
):
    updates = []
    created_payloads = []
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "agent-planner",
            "sessionId": "session-project-1",
            "turnId": "turn-design-1",
        },
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda _session_id, **_kwargs: {
            "experimentBinding": {
                "teamId": "research-team",
                "researchProjectId": "project-1",
                "agentId": "agent-planner",
            },
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_status",
        lambda _team_id, _project_id: {
            "tasks": [
                {
                    "taskId": "task-design-1",
                    "taskKind": "experiment_design",
                    "agentId": "agent-planner",
                    "researchProjectId": "project-1",
                    "sessionId": "session-project-1",
                    "status": "running",
                    "turn": {"turnId": "turn-design-1"},
                }
            ]
        },
        raising=False,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "require_research_project_agent_task",
        lambda _team_id, project_id, task_id, **_kwargs: {
            "taskId": task_id,
            "taskKind": "experiment_design",
            "agentId": "agent-planner",
            "researchProjectId": project_id,
            "sessionId": "session-project-1",
            "turn": {"turnId": "turn-design-1"},
        },
        raising=False,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_context",
        lambda team_id, project_id, task_id: {
            "teamId": team_id,
            "researchProjectId": project_id,
            "task": {
                "taskId": task_id,
                "taskKind": "experiment_design",
                "agentId": "agent-planner",
                "researchProjectId": project_id,
            },
            "experiment": {"plans": [], "planCount": 0},
        },
        raising=False,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "create_experiment_plan",
        lambda team_id, payload: created_payloads.append(dict(payload))
        or {
            "teamId": team_id,
            "plan": {
                "planId": "plan-runtime-bound",
                "researchProjectId": payload["researchProjectId"],
            },
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "update_research_project_agent_task_status",
        lambda team_id, project_id, task_id, **kwargs: updates.append(
            (team_id, project_id, task_id, kwargs)
        )
        or {"taskId": task_id, "status": kwargs["status"]},
    )

    context = json.loads(
        challenge_cup_experiment_context_tool(
            team_id="research-team",
            include_research_loop=True,
        )
    )
    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            operation="create_plan",
            payload_json='{"title":"Runtime-bound plan"}',
            recorded_by_agent="A019 实验规划",
        )
    )

    assert context["status"] == "ok"
    assert context["researchProjectId"] == "project-1"
    assert (
        context["researchLoopStatus"]["status"]
        == "project_scoped_unavailable"
    )
    assert result["status"] == "ok"
    assert created_payloads == [
        {
            "title": "Runtime-bound plan",
            "createdByAgent": "agent-planner",
            "registeredByAgent": "agent-planner",
            "recordedByAgent": "agent-planner",
            "requestedByAgent": "agent-planner",
            "researchProjectId": "project-1",
            "createdFromTaskId": "task-design-1",
            "createdFromSessionId": "session-project-1",
            "createdFromTurnId": "turn-design-1",
        }
    ]
    assert updates == [
        (
            "research-team",
            "project-1",
            "task-design-1",
            {"status": "running", "result_refs": ["plan-runtime-bound"]},
        )
    ]


def test_experiment_tool_fails_closed_when_bound_runtime_task_is_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "agent-planner",
            "sessionId": "session-project-1",
            "turnId": "turn-missing",
        },
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda _session_id, **_kwargs: {
            "experimentBinding": {
                "teamId": "research-team",
                "researchProjectId": "project-1",
                "agentId": "agent-planner",
            },
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_status",
        lambda _team_id, _project_id: {"tasks": []},
        raising=False,
    )

    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            operation="create_plan",
            payload_json='{"title":"Must not be written"}',
        )
    )

    assert result["status"] == "error"
    assert "exactly one compatible" in result["message"]


def test_iteration_tools_reuse_unique_bound_task_for_flat_session_follow_up(
    monkeypatch,
):
    created_payloads = []
    context_require_active = []
    write_require_active = []
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "agent-iteration",
            "sessionId": "session-project-1",
            "turnId": "turn-follow-up",
        },
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda _session_id, **_kwargs: {
            "experimentBinding": {
                "teamId": "research-team",
                "researchProjectId": "project-1",
                "agentId": "agent-iteration",
            },
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_status",
        lambda _team_id, _project_id: {
            "tasks": [
                {
                    "taskId": "task-iteration-1",
                    "taskKind": "iteration_decision",
                    "agentId": "agent-iteration",
                    "researchProjectId": "project-1",
                    "sessionId": "session-project-1",
                    "status": "incomplete",
                    "failureCode": "task_result_not_recorded",
                    "resultRefs": [],
                    "turn": {"turnId": "turn-initial"},
                }
            ]
        },
        raising=False,
    )

    def get_task_context(
        team_id,
        project_id,
        task_id,
        *,
        require_active=True,
    ):
        context_require_active.append(require_active)
        return {
            "teamId": team_id,
            "researchProjectId": project_id,
            "task": {
                "taskId": task_id,
                "taskKind": "iteration_decision",
                "agentId": "agent-iteration",
                "researchProjectId": project_id,
            },
            "experiment": {"plans": [], "planCount": 0},
        }

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_context",
        get_task_context,
        raising=False,
    )

    def require_task(_team_id, project_id, task_id, **kwargs):
        write_require_active.append(kwargs.get("require_active", True))
        return {
            "taskId": task_id,
            "taskKind": "iteration_decision",
            "agentId": "agent-iteration",
            "researchProjectId": project_id,
            "sessionId": "session-project-1",
            "turn": {"turnId": "turn-initial"},
        }

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "require_research_project_agent_task",
        require_task,
        raising=False,
    )
    monkeypatch.setattr(
        research_loop_service,
        "list_research_loop_templates",
        lambda: {"templates": []},
    )
    monkeypatch.setattr(
        research_loop_service,
        "get_research_loop_status",
        lambda team_id, research_project_id="": {
            "teamId": team_id,
            "researchProjectId": research_project_id,
            "activeLoopId": "",
        },
    )
    monkeypatch.setattr(
        research_loop_service,
        "create_research_loop",
        lambda team_id, payload: created_payloads.append(dict(payload))
        or {
            "teamId": team_id,
            "loop": {
                "loopId": "loop-follow-up",
                "researchProjectId": payload["researchProjectId"],
            },
        },
    )

    context = json.loads(
        challenge_cup_iteration_context_tool(team_id="research-team")
    )
    created = json.loads(
        challenge_cup_iteration_writeback_tool(
            team_id="research-team",
            operation="create_loop",
            payload_json='{"title":"Continue the bound iteration"}',
        )
    )

    assert context["status"] == "ok"
    assert context["researchProjectId"] == "project-1"
    assert context["taskContext"]["task"]["taskId"] == "task-iteration-1"
    assert created["status"] == "ok"
    assert created["task"]["taskId"] == "task-iteration-1"
    assert context_require_active == [False]
    assert write_require_active == [False]
    assert created_payloads == [
        {
            "title": "Continue the bound iteration",
            "createdByAgent": "agent-iteration",
            "recordedByAgent": "agent-iteration",
            "decidedByAgent": "agent-iteration",
            "researchProjectId": "project-1",
        }
    ]


def test_iteration_tool_rejects_ambiguous_flat_session_follow_up(monkeypatch):
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "agent-iteration",
            "sessionId": "session-project-1",
            "turnId": "turn-follow-up",
        },
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda _session_id, **_kwargs: {
            "experimentBinding": {
                "teamId": "research-team",
                "researchProjectId": "project-1",
                "agentId": "agent-iteration",
            },
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_status",
        lambda _team_id, _project_id: {
            "tasks": [
                {
                    "taskId": task_id,
                    "taskKind": "iteration_decision",
                    "agentId": "agent-iteration",
                    "sessionId": "session-project-1",
                    "turn": {"turnId": turn_id},
                }
                for task_id, turn_id in (
                    ("task-iteration-1", "turn-initial"),
                    ("task-iteration-2", "turn-later"),
                )
            ]
        },
        raising=False,
    )

    result = json.loads(
        challenge_cup_iteration_context_tool(team_id="research-team")
    )

    assert result["status"] == "error"
    assert "exactly one compatible" in result["message"]


def test_experiment_evidence_writeback_requires_plan_in_same_project(
    monkeypatch,
):
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "require_research_project_agent_task",
        lambda _team_id, project_id, task_id, **_kwargs: {
            "taskId": task_id,
            "taskKind": "experiment_evidence_review",
            "agentId": "agent-ledger",
            "researchProjectId": project_id,
        },
        raising=False,
    )

    def reject_cross_project_plan(*_args, **_kwargs):
        raise ValueError("Experiment plan does not belong to this research project.")

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "require_research_project_experiment_plan",
        reject_cross_project_plan,
        raising=False,
    )

    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-ledger-1",
            operation="register_full_run_result",
            plan_id="plan-other-project",
            payload_json='{"status":"passed"}',
            recorded_by_agent="agent-ledger",
        )
    )

    assert result["status"] == "error"
    assert "does not belong" in result["message"]


def test_challenge_cup_iteration_tool_wraps_research_loop_decisions(monkeypatch):
    scene_events = []
    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: scene_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        research_loop_service,
        "list_research_loop_templates",
        lambda: {"templates": [{"templateId": "algorithm_model_experiment"}], "boundaries": {"autoExecution": False}},
    )
    monkeypatch.setattr(
        research_loop_service,
        "get_research_loop_status",
        lambda team_id: {"teamId": team_id, "activeLoopId": "", "boundaries": {"autoExecution": False}},
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_experiment_planning_status",
        lambda team_id: {"teamId": team_id, "status": "planned", "boundaries": {"autoExecution": False}},
    )
    monkeypatch.setattr(
        research_loop_service,
        "create_research_loop",
        lambda team_id, payload: {
            "teamId": team_id,
            "loop": {"loopId": "loop-created-1", "templateId": "algorithm_model_experiment", **payload},
            "boundaries": {"autoExecution": False},
        },
    )
    monkeypatch.setattr(
        research_loop_service,
        "record_research_loop_decision",
        lambda team_id, loop_id, payload: {
            "teamId": team_id,
            "loopId": loop_id,
            "decision": {"decisionId": "decision-1", "statusAfterDecision": "iteration_planned", **payload},
            "iterationProposal": {"proposalId": "proposal-1"},
            "loop": {"loopId": loop_id, "templateId": "algorithm_model_experiment", "readiness": {"readyForDecision": True}},
            "boundaries": {"autoExecution": False},
        },
    )

    context = json.loads(challenge_cup_iteration_context_tool(team_id="research-team"))
    assert context["status"] == "ok"
    assert context["templates"]["templates"][0]["templateId"] == "algorithm_model_experiment"
    assert context["experimentPlanningStatus"]["status"] == "planned"
    assert context["boundaries"]["autoExecution"] is False
    assert context["writebackContract"]["record_evidence"] == {
        "requiredFields": ["evidenceType"],
        "oneOfEvidenceFields": [
            "summary",
            "metricName",
            "metricValue",
            "baselineMetricValue",
            "delta",
            "metrics",
            "artifact",
            "commandPreview",
            "source",
            "artifactRefs",
            "sourceRefs",
            "datasetRefs",
            "environmentRefs",
            "logRefs",
        ],
        "statusValues": [
            "passed",
            "failed",
            "needs_review",
            "not_applicable",
        ],
        "example": {
            "evidenceType": "metric_report",
            "status": "passed",
            "summary": "reconstruction_mse improved from 0.025838 to 0.007935",
            "metrics": {
                "baseline": 0.025838,
                "variant": 0.007935,
                "improvement": 0.017903,
            },
        },
    }
    assert context["writebackContract"]["record_decision"]["requiredFields"] == [
        "decision",
        "rationale",
    ]

    created = json.loads(
        challenge_cup_iteration_writeback_tool(
            team_id="research-team",
            operation="create_loop",
            payload_json='{"researchQuestion":"Does the metric improve?"}',
            recorded_by_agent="challenge_cup_iteration_planner",
        )
    )
    assert created["status"] == "ok"
    assert created["response"]["loop"]["researchQuestion"] == "Does the metric improve?"
    assert created["response"]["loop"]["createdByAgent"] == "challenge_cup_iteration_planner"

    decision = json.loads(
        challenge_cup_iteration_writeback_tool(
            team_id="research-team",
            loop_id="loop-1",
            operation="record_decision",
            payload_json='{"decision":"repair_and_repeat","rationale":"needs another metric check"}',
            recorded_by_agent="challenge_cup_iteration_planner",
        )
    )
    assert decision["status"] == "ok"
    assert decision["response"]["decision"]["decidedByAgent"] == "challenge_cup_iteration_planner"

    writeback_events = [kwargs for args, kwargs in scene_events if len(args) >= 3 and args[2] == "tool.challenge_cup_iteration_writeback.completed"]
    assert writeback_events
    child_payload = writeback_events[-1]["child_log_payload"]
    assert child_payload["kind"] == "challenge_cup_iteration_writeback"
    assert child_payload["operation"] == "record_decision"
    assert child_payload["loopId"] == "loop-1"
    assert child_payload["decisionId"] == "decision-1"
    assert child_payload["iterationProposalId"] == "proposal-1"
    assert child_payload["readyForDecision"] is True


def test_iteration_and_versioning_tools_bind_project_tasks_and_complete(
    monkeypatch,
):
    updates = []
    loop_payloads = []
    version_payloads = []
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_context",
        lambda team_id, project_id, task_id: {
            "teamId": team_id,
            "researchProjectId": project_id,
            "task": {
                "taskId": task_id,
                "taskKind": (
                    "iteration_decision"
                    if task_id == "task-iteration"
                    else "version_governance"
                ),
                "agentId": (
                    "agent-iteration"
                    if task_id == "task-iteration"
                    else "agent-versioning"
                ),
            },
            "experiment": {"plans": [], "planCount": 0},
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "require_research_project_agent_task",
        lambda _team_id, project_id, task_id, **_kwargs: {
            "taskId": task_id,
            "taskKind": (
                "iteration_decision"
                if task_id == "task-iteration"
                else "version_governance"
            ),
            "agentId": (
                "agent-iteration"
                if task_id == "task-iteration"
                else "agent-versioning"
            ),
            "researchProjectId": project_id,
        },
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "update_research_project_agent_task_status",
        lambda team_id, project_id, task_id, **kwargs: updates.append(
            (team_id, project_id, task_id, kwargs)
        )
        or {"taskId": task_id, "status": kwargs["status"]},
    )
    monkeypatch.setattr(
        research_loop_service,
        "get_research_loop_status",
        lambda team_id, research_project_id="": {
            "teamId": team_id,
            "researchProjectId": research_project_id,
            "loops": [{"loopId": "loop-project-1"}],
            "storagePath": "must/not/leak.json",
        },
    )
    monkeypatch.setattr(
        research_loop_service,
        "require_research_loop",
        lambda _team_id, loop_id, **_kwargs: {"loopId": loop_id},
        raising=False,
    )
    monkeypatch.setattr(
        research_loop_service,
        "record_research_loop_decision",
        lambda team_id, loop_id, payload: loop_payloads.append(dict(payload))
        or {
            "teamId": team_id,
            "loopId": loop_id,
            "decision": {"decisionId": "decision-project-1"},
            "loop": {"loopId": loop_id},
        },
    )

    from core.web.services import challenge_cup_versioning_service

    monkeypatch.setattr(
        challenge_cup_versioning_service,
        "get_candidate_versioning_status",
        lambda team_id, research_project_id="": {
            "teamId": team_id,
            "researchProjectId": research_project_id,
            "versionHistory": [],
            "storagePath": "must/not/leak.json",
        },
    )
    monkeypatch.setattr(
        challenge_cup_versioning_service,
        "record_candidate_version_event",
        lambda team_id, payload: version_payloads.append(dict(payload))
        or {
            "event": {
                "versionId": "version-project-1",
                "candidateId": payload["candidateId"],
                "researchProjectId": payload["researchProjectId"],
            },
            "relation": None,
            "rejection": None,
        },
    )

    iteration_context = json.loads(
        challenge_cup_iteration_context_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-iteration",
        )
    )
    iteration_result = json.loads(
        challenge_cup_iteration_writeback_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-iteration",
            loop_id="loop-project-1",
            operation="record_decision",
            payload_json='{"decision":"repair_and_repeat","rationale":"retry"}',
            recorded_by_agent="agent-iteration",
        )
    )
    version_context = json.loads(
        challenge_cup_versioning_context_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-versioning",
        )
    )
    version_result = json.loads(
        challenge_cup_versioning_writeback_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-versioning",
            operation="record_version",
            candidate_id="candidate-project-1",
            recorded_by_agent="agent-versioning",
        )
    )

    assert iteration_context["researchLoopStatus"]["researchProjectId"] == "project-1"
    assert "storagePath" not in json.dumps(iteration_context)
    assert iteration_result["task"]["status"] == "completed"
    assert loop_payloads[0]["researchProjectId"] == "project-1"
    assert version_context["versioningStatus"]["researchProjectId"] == "project-1"
    assert "storagePath" not in json.dumps(version_context)
    assert version_result["task"]["status"] == "completed"
    assert version_payloads[0]["researchProjectId"] == "project-1"
    assert [item[2] for item in updates] == [
        "task-iteration",
        "task-versioning",
    ]


def test_challenge_cup_versioning_tool_logs_writeback_child_payload(monkeypatch):
    scene_events = []
    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: scene_events.append((args, kwargs)) or {"accepted": True},
    )

    def fake_record_candidate_version_event(team_id, payload):
        return {
            "event": {
                "versionId": "version-1",
                "candidateId": payload["candidateId"],
                "operation": payload["operation"],
                "evidenceRefs": payload["evidenceRefs"],
                "changeSet": payload["changeSet"],
            },
            "relation": {"relationId": "relation-1"},
            "rejection": None,
            "status": {"summary": {"versionCount": 1, "relationCount": 1, "rejectionCount": 0}},
            "boundaries": {"autoApply": False},
        }

    from core.web.services import challenge_cup_versioning_service

    monkeypatch.setattr(
        challenge_cup_versioning_service,
        "record_candidate_version_event",
        fake_record_candidate_version_event,
    )

    result = json.loads(
        challenge_cup_versioning_writeback_tool(
            team_id="research-team",
            operation="derive",
            candidate_id="candidate-a",
            version_label="v2",
            derived_from_version_id="version-0",
            evidence_refs_json='[{"kind":"loop","id":"loop-evidence-1"}]',
            change_set_json='[{"field":"metric","change":"tightened"}]',
            recorded_by_agent="challenge_cup_versioning",
        )
    )

    assert result["status"] == "ok"
    writeback_events = [kwargs for args, kwargs in scene_events if len(args) >= 3 and args[2] == "tool.challenge_cup_versioning_writeback.completed"]
    assert writeback_events
    child_payload = writeback_events[-1]["child_log_payload"]
    assert child_payload["kind"] == "challenge_cup_versioning_writeback"
    assert child_payload["operation"] == "derive"
    assert child_payload["candidateId"] == "candidate-a"
    assert child_payload["versionId"] == "version-1"
    assert child_payload["relationId"] == "relation-1"
    assert child_payload["evidenceRefCount"] == 1
    assert child_payload["changeSetCount"] == 1


def _valid_scope_json() -> str:
    scope_hash = "a" * 64
    return json.dumps(
        {
            "program": "XH-202619",
            "theme": "cc-gpu-operator-001",
            "campaign": "cc-campaign-gpu-operator-001",
            "question": "SCI-091",
            "branch": "main",
            "workflow": "hypothesis_and_plan",
            "agentId": "agent-alpha",
            "mode": "formal",
            "scopeHash": scope_hash,
            "artifactLocator": f"research-artifact://x/{scope_hash}",
            "ledgerRoot": f"research-ledger://x/{scope_hash}",
            "cacheKey": f"scope:{scope_hash}:main:agent-alpha",
        }
    )


def test_research_knowledge_collection_tool_wraps_single_facade(monkeypatch):
    scene_events = []
    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: scene_events.append((args, kwargs)) or {"accepted": True},
    )
    from core.web.services.team_workflow.source_collection import facade as facade_module

    calls = []

    def fake_facade(**kwargs):
        calls.append(dict(kwargs))
        return {
            "schemaVersion": 1,
            "action": kwargs.get("action"),
            "status": "ok",
            "created": kwargs.get("action") == "ensure",
            "found": True,
            "locator": {"runId": "dprun-tool", "scopeHash": "s" * 64},
            "summary": {"status": "collecting", "available": True, "counts": {"recordCount": 4}},
            "scope": {"scopeHash": "s" * 64},
            "searchEnvelope": {"keywords": ["predictive coding"]},
            "requirements": {},
            "writebackPolicy": {},
            "boundaries": {"singleVisibleInterface": True},
        }

    monkeypatch.setattr(facade_module, "research_knowledge_collection_facade", fake_facade)

    result = json.loads(
        research_knowledge_collection_tool(
            action="inspect",
            scope=_valid_scope_json(),
            searchEnvelope='{"keywords":["predictive coding"],"sourceTypes":["paper"]}',
            requirements='{"minEvidenceLevel":"primary"}',
            writebackPolicy='{"providerWriteback":true}',
        )
    )

    assert result["status"] == "ok"
    assert result["locator"]["runId"] == "dprun-tool"
    assert calls[0]["action"] == "inspect"
    assert calls[0]["scope"]["scopeHash"] == "a" * 64
    assert calls[0]["searchEnvelope"]["keywords"] == ["predictive coding"]
    assert calls[0]["requirements"] == {"minEvidenceLevel": "primary"}
    assert calls[0]["writebackPolicy"] == {"providerWriteback": True}

    completed_events = [
        kwargs
        for args, kwargs in scene_events
        if len(args) >= 3 and args[2] == "tool.research_knowledge_collection.completed"
    ]
    assert completed_events
    assert completed_events[-1]["fields"]["action"] == "inspect"
    assert completed_events[-1]["fields"]["runId"] == "dprun-tool"


def test_research_knowledge_collection_tool_returns_error_payload(monkeypatch):
    scene_events = []
    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: scene_events.append((args, kwargs)) or {"accepted": True},
    )
    from core.web.services.team_workflow.source_collection import facade as facade_module

    def raise_error(**kwargs):
        raise facade_module.ResearchKnowledgeCollectionError(
            "bad scope", code="scope_invalid"
        )

    monkeypatch.setattr(facade_module, "research_knowledge_collection_facade", raise_error)

    result = json.loads(
        research_knowledge_collection_tool(
            action="ensure",
            scope=_valid_scope_json(),
            searchEnvelope="{}",
        )
    )

    assert result["status"] == "error"
    assert result["errorType"] == "ResearchKnowledgeCollectionError"
    assert "bad scope" in result["message"]
    assert result["boundaries"]["singleVisibleInterface"] is True
    assert result["boundaries"]["autoExecution"] is False

    failed_events = [
        kwargs
        for args, kwargs in scene_events
        if len(args) >= 3 and args[2] == "tool.research_knowledge_collection.failed"
    ]
    assert failed_events
    assert failed_events[-1]["level"] == "warning"
    assert failed_events[-1]["fields"]["outcome"] == "failed"
