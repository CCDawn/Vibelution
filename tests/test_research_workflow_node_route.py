"""Node route mode: designed next station, or the finishing agent chooses."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.research.workflow.definition import (
    build_challenge_cup_workflow_definition,
    definition_structure_hash,
)
from core.research.workflow.definition_registry import (
    parse_snapshot_payload,
    register_definition,
)
from core.research.workflow.models import (
    ActorKind,
    GateKind,
    NodeRouteMode,
    WorkflowDefinition,
    WorkflowEdgeSpec,
    WorkflowNodeSpec,
    WorkflowStageId,
    WorkflowStageSpec,
)
from core.research.workflow.node_route import (
    NodeRouteError,
    decision_from_attempts,
    extract_next_node_id,
    resolve_agent_route,
    route_choice_instruction,
    successors_for_decision,
    validate_definition_routes,
)

_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "core"
    / "research"
    / "workflow"
    / "definitions"
    / "challenge-cup-research@3.0.0.json"
)


def _node(
    node_id: str,
    *,
    actor: ActorKind = ActorKind.AGENT,
    mode: NodeRouteMode = NodeRouteMode.SPECIFIED,
) -> WorkflowNodeSpec:
    return WorkflowNodeSpec(
        nodeId=node_id,
        stageId=WorkflowStageId.EXPERIMENT_DESIGN,
        label=node_id,
        actorKind=actor,
        primaryRoleKey="experiment_planner",
        routeMode=mode,
    )


def _definition(
    *nodes: WorkflowNodeSpec,
    edges: tuple[WorkflowEdgeSpec, ...],
) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflowId="route-test",
        schemaVersion="0",
        label="route test",
        stages=(
            WorkflowStageSpec(
                stageId=WorkflowStageId.EXPERIMENT_DESIGN,
                index=1,
                label="实验设计",
                nodeIds=tuple(node.nodeId for node in nodes),
            ),
        ),
        nodes=nodes,
        edges=edges,
    )


def _edge(source: str, target: str) -> WorkflowEdgeSpec:
    return WorkflowEdgeSpec(
        edgeId=f"{source}-{target}",
        fromNodeId=source,
        toNodeId=target,
        label=target,
        gateKind=GateKind.AUTO,
    )


def _attempt(
    node_id: str,
    *,
    status: str = "succeeded",
    code: str = "",
    node_run_id: str = "",
) -> SimpleNamespace:
    problem = json.dumps({"code": code}) if code else ""
    return SimpleNamespace(
        node_id=node_id,
        node_run_id=node_run_id or f"nr-{node_id}-{status}",
        status=status,
        problem_json=problem,
    )


def test_challenge_cup_nodes_stay_specified_and_keep_the_published_hash() -> None:
    definition = build_challenge_cup_workflow_definition()
    assert all(node.routeMode is NodeRouteMode.SPECIFIED for node in definition.nodes)
    assert "routeMode" not in definition.nodes[0].to_dict()
    payload = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    assert definition.structureHash == payload["contentHash"]
    parsed = parse_snapshot_payload(payload)
    assert parsed.structureHash == definition.structureHash
    assert definition_structure_hash(parsed) == payload["contentHash"]


def test_agent_mode_is_in_the_hash_and_round_trips() -> None:
    definition = _definition(
        _node("review", mode=NodeRouteMode.AGENT),
        _node("revise"),
        _node("stop"),
        edges=(_edge("review", "revise"), _edge("review", "stop")),
    )
    validate_definition_routes(definition)
    hashed = definition_structure_hash(definition)
    projected = next(
        node.to_dict() for node in definition.nodes if node.nodeId == "review"
    )
    assert projected["routeMode"] == "agent"
    restored = WorkflowNodeSpec.from_dict(projected)
    assert restored.routeMode is NodeRouteMode.AGENT
    assert hashed != definition_structure_hash(
        _definition(
            _node("review"),
            _node("revise"),
            _node("stop"),
            edges=(_edge("review", "revise"), _edge("review", "stop")),
        )
    )


def test_agent_mode_rejects_a_human_node_and_a_single_exit() -> None:
    human = _definition(
        _node("freeze", actor=ActorKind.HUMAN, mode=NodeRouteMode.AGENT),
        _node("left"),
        _node("right"),
        edges=(_edge("freeze", "left"), _edge("freeze", "right")),
    )
    with pytest.raises(NodeRouteError) as human_error:
        validate_definition_routes(human)
    assert human_error.value.code == "agent_route_requires_agent"

    single = _definition(
        _node("review", mode=NodeRouteMode.AGENT),
        _node("next"),
        edges=(_edge("review", "next"),),
    )
    with pytest.raises(NodeRouteError) as single_error:
        validate_definition_routes(single)
    assert single_error.value.code == "agent_route_needs_menu"


def test_agent_choice_follows_a_designed_station_and_holds_otherwise() -> None:
    allowed = ("revise", "stop")
    assert resolve_agent_route(
        allowed=allowed,
        chosen="stop",
        prior_rejections=0,
        target_entry_count=0,
    ).status == "follow"
    first = resolve_agent_route(
        allowed=allowed,
        chosen="missing",
        prior_rejections=0,
        target_entry_count=0,
    )
    assert first.status == "retry"
    assert first.code == "agent_next_rejected"
    second = resolve_agent_route(
        allowed=allowed,
        chosen="missing",
        prior_rejections=1,
        target_entry_count=0,
    )
    assert second.status == "wait_human"
    capped = resolve_agent_route(
        allowed=allowed,
        chosen="revise",
        prior_rejections=0,
        target_entry_count=3,
    )
    assert capped.status == "wait_human"
    assert capped.code == "agent_next_reentry_cap"
    assert successors_for_decision(("revise", "stop"), None) == ("revise", "stop")
    followed = resolve_agent_route(
        allowed=allowed,
        chosen="stop",
        prior_rejections=0,
        target_entry_count=0,
    )
    assert successors_for_decision(("revise", "stop"), followed) == ("stop",)
    assert successors_for_decision(("revise", "stop"), first) is None


def test_worker_reads_next_node_only_for_agent_mode() -> None:
    from core.web.services.team_workflow.research_runtime import (
        adapter_dispatch_worker as dispatch_worker,
    )

    _agent_route_decision = dispatch_worker._agent_route_decision

    agent_definition = _definition(
        _node("review", mode=NodeRouteMode.AGENT),
        _node("revise"),
        _node("stop"),
        edges=(_edge("review", "revise"), _edge("review", "stop")),
    )
    agent_definition = WorkflowDefinition(
        workflowId=agent_definition.workflowId,
        schemaVersion=agent_definition.schemaVersion,
        label=agent_definition.label,
        stages=agent_definition.stages,
        nodes=agent_definition.nodes,
        edges=agent_definition.edges,
        structureHash=definition_structure_hash(agent_definition),
    )
    identity = register_definition(agent_definition)
    run = SimpleNamespace(
        workflow_version_id=identity.workflowVersionId,
        run_id="run-1",
    )
    action = SimpleNamespace(node_id="review", node_run_id="nr-review", run_id="run-1")
    uow = SimpleNamespace(
        repository=SimpleNamespace(list_attempts=lambda _run_id: [])
    )
    decision = _agent_route_decision(uow, run, action, {"nextNodeId": "stop"})
    assert decision is not None
    assert decision.status == "follow"
    assert decision.next_node_id == "stop"

    specified = _definition(
        _node("review"),
        _node("revise"),
        _node("stop"),
        edges=(_edge("review", "revise"), _edge("review", "stop")),
    )
    specified = WorkflowDefinition(
        workflowId="route-test-specified",
        schemaVersion=specified.schemaVersion,
        label=specified.label,
        stages=specified.stages,
        nodes=specified.nodes,
        edges=specified.edges,
        structureHash=definition_structure_hash(specified),
    )
    specified_identity = register_definition(specified)
    specified_run = SimpleNamespace(
        workflow_version_id=specified_identity.workflowVersionId,
        run_id="run-2",
    )
    assert (
        _agent_route_decision(uow, specified_run, action, {"nextNodeId": "stop"})
        is None
    )


def test_recorded_rejection_is_counted_on_the_same_attempt() -> None:
    decision = decision_from_attempts(
        allowed=("revise", "stop"),
        chosen="missing",
        attempts=[
            _attempt(
                "review",
                status="running",
                code="agent_next_rejected",
                node_run_id="nr-review",
            )
        ],
        node_id="review",
        node_run_id="nr-review",
    )
    assert decision.status == "wait_human"
    fresh = decision_from_attempts(
        allowed=("revise", "stop"),
        chosen="stop",
        attempts=[
            _attempt("stop", status="succeeded"),
            _attempt("stop", status="succeeded", node_run_id="nr-stop-2"),
        ],
        node_id="review",
        node_run_id="nr-review",
    )
    assert fresh.status == "follow"


def test_agent_text_keeps_the_last_named_station() -> None:
    assert extract_next_node_id("先写 nextNodeId: revise\nnextNodeId: stop") == "stop"
    assert extract_next_node_id('{"nextNodeId": "revise"}') == "revise"
    assert extract_next_node_id("没有选择") == ""
    assert route_choice_instruction(("only",)) == ""
    instruction = route_choice_instruction(("revise", "stop"))
    assert "revise" in instruction and "stop" in instruction
    assert "nextNodeId:" in instruction


def test_specified_task_message_stays_unchanged() -> None:
    from core.web.services.team_workflow import research_project_agent_tasks

    task = {
        "experimentName": "Project 1",
        "roleLabel": "实验规划",
        "taskTitle": "生成设计",
        "formalRetry": False,
    }
    contract = {"objective": "完成设计", "checklist": ["写回设计"]}
    plain = research_project_agent_tasks._task_message(task=task, contract=contract)
    assert "nextNodeId" not in plain
    routed = research_project_agent_tasks._task_message(
        task={**task, "agentRouteTargets": ["revise", "stop"]},
        contract=contract,
    )
    assert "请先读取受控项目上下文" in plain
    assert "请先读取受控项目上下文" in routed
    assert "nextNodeId:" in routed


def test_empty_handle_omits_next_node_and_a_choice_is_kept() -> None:
    from core.web.services.team_workflow.research_runtime.domain_ports import (
        AgentTaskHandle,
    )

    empty = AgentTaskHandle("s", 1, "task", "turn")
    assert "nextNodeId" not in empty.to_dict()
    chosen = AgentTaskHandle("s", 1, "task", "turn", next_node_id="stop")
    assert chosen.to_dict()["nextNodeId"] == "stop"


def test_graph_follows_the_named_station_and_stops_without_one() -> None:
    from langgraph.graph import END

    from core.research.workflow.challenge_cup_runtime import (
        _route_after_agent_choice,
        _route_after_linear,
        build_formal_graph,
    )

    route = _route_after_agent_choice("review", ("revise", "stop"))
    assert route({"agent_next_node_id": "stop"}) == "stop"
    assert route({}) == END
    assert route({"blocked_outcome": "failed"}) == END
    assert _route_after_linear("review", "revise")({}) == "revise"
    assert build_formal_graph().compile() is not None
