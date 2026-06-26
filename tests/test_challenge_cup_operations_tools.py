import json

from core.web.services import research_loop_service, runtime_scene_service, team_workflow_orchestration_service
from tools.challenge_cup_operations_tools import (
    challenge_cup_experiment_context_tool,
    challenge_cup_experiment_writeback_tool,
    challenge_cup_iteration_context_tool,
    challenge_cup_iteration_writeback_tool,
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


def test_challenge_cup_iteration_tool_wraps_research_loop_decisions(monkeypatch):
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
        lambda team_id, payload: {"teamId": team_id, "loop": payload, "boundaries": {"autoExecution": False}},
    )
    monkeypatch.setattr(
        research_loop_service,
        "record_research_loop_decision",
        lambda team_id, loop_id, payload: {
            "teamId": team_id,
            "loopId": loop_id,
            "decision": payload,
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
