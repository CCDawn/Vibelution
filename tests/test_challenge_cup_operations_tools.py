import json

from core.web.services import research_loop_service, runtime_scene_service, team_workflow_orchestration_service
from tools.challenge_cup_operations_tools import (
    challenge_cup_experiment_context_tool,
    challenge_cup_experiment_writeback_tool,
    challenge_cup_iteration_context_tool,
    challenge_cup_iteration_writeback_tool,
    challenge_cup_versioning_context_tool,
    challenge_cup_versioning_writeback_tool,
)


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


def test_experiment_tool_binds_project_task_and_completes_writeback(
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
    assert updates == [
        (
            "research-team",
            "project-1",
            "task-design-1",
            {"status": "completed", "result_refs": ["plan-project-1"]},
        )
    ]
    assert result["task"]["status"] == "completed"


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
