"""Agent binding + session binding closed-loop contracts for research workflow runs.

Covers the acceptance matrix:
1. research-team's executable roles resolve into all 10 agent-node run snapshots;
2. missing roles stay unbound (no random fallback);
3. node > stage > workflow override priority is honored;
4. run snapshots are frozen — later team-config changes never rewrite history;
5. starting an agent task writes the full session/task/turn binding;
6. every one of the 16 nodes serves node detail;
7. with multiple pending HumanTasks only the current node's task resolves;
8. run list filters by teamId;
9. rebind keeps lineage and never silently overwrites.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.research.workflow.definition import (
    CHALLENGE_CUP_WORKFLOW_ID,
    build_challenge_cup_workflow_definition,
)
from core.research.workflow.models import ActorKind
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services.team_workflow.research_runtime.node_command_adapter import (
    NodeCommandUnavailable,
    _require_project,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore

# research-team org canvas with the 9 challenge-cup agent roles.
ROLE_AGENTS = {
    "source_finder": "agent-finder",
    "source_extractor": "agent-extractor",
    "source_relation_mapper": "agent-relations",
    "source_ingestor": "agent-ingestor",
    "experiment_planner": "agent-planner",
    "experiment_ledger": "agent-ledger",
    "iteration_planner": "agent-iteration-planner",
    "iteration_versioning": "agent-versioning",
    # knowledge_handoff / protocol_freeze / smoke_gate / candidate_promotion
    # are HUMAN gates; research_owner/formal_runner/package_builder are
    # non-agent nodes handled by the graph.
}


def _fake_canvas(*, roles: dict[str, str]) -> dict:
    return {
        "teamId": "research-team",
        "nodes": [
            {"agentId": agent_id, "role": role, "label": f"{role} agent"}
            for role, agent_id in roles.items()
        ],
        "edges": [],
    }


def _fake_team(*, members: list[dict]) -> dict:
    return {"teamId": "research-team", "members": members}


@pytest.fixture()
def runtime_service(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.web.services.team_service.get_team_canvas",
        lambda team_id: _fake_canvas(roles=ROLE_AGENTS),
    )
    monkeypatch.setattr(
        "core.web.services.team_service.get_team",
        lambda team_id: _fake_team(members=[]),
    )
    store = WorkflowRunStore(tmp_path / "runs")
    ckpt = str(tmp_path / "ckpt.sqlite")
    return reset_research_workflow_runtime_service_for_tests(run_store=store, checkpoint_path=ckpt)


def test_executable_roles_resolve_into_all_ten_agent_snapshots(runtime_service) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    snaps = {s["nodeId"]: s for s in run["bindingSnapshots"]}
    agent_nodes = [n for n in build_challenge_cup_workflow_definition().nodes if n.actorKind is ActorKind.AGENT]
    assert len(agent_nodes) == 10
    for node in agent_nodes:
        snap = snaps[node.nodeId]
        assert snap["agentId"] == ROLE_AGENTS[node.primaryRoleKey], node.nodeId
        assert snap["resolvedFrom"] == "workflow_default"


def test_missing_role_stays_unbound_no_random_fallback(runtime_service, monkeypatch) -> None:
    partial = {k: v for k, v in ROLE_AGENTS.items() if k != "source_finder"}
    monkeypatch.setattr(
        "core.web.services.team_service.get_team_canvas",
        lambda team_id: _fake_canvas(roles=partial),
    )
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    snaps = {s["nodeId"]: s for s in run["bindingSnapshots"]}
    assert snaps["source_finding"]["agentId"] == ""
    assert snaps["source_finding"]["resolvedFrom"] == "unbound"
    assert snaps["source_extraction"]["agentId"] == ROLE_AGENTS["source_extractor"]


def test_override_priority_node_stage_workflow(runtime_service) -> None:
    layers_payload = {
        "workflowDefaults": {"source_finder": "agent-default"},
        "stageOverrides": {"knowledge_collection": {"source_finder": "agent-stage"}},
        "nodeOverrides": {"source_finding": "agent-node"},
    }
    runtime_service.put_agent_binding_config(CHALLENGE_CUP_WORKFLOW_ID, layers_payload, team_id="research-team")
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    snaps = {s["nodeId"]: s for s in run["bindingSnapshots"]}
    assert snaps["source_finding"]["agentId"] == "agent-node"
    assert snaps["source_finding"]["resolvedFrom"] == "node_override"

    # stage override wins over workflow default (remove node override).
    runtime_service.put_agent_binding_config(
        CHALLENGE_CUP_WORKFLOW_ID,
        {"nodeOverrides": {}},
        team_id="research-team",
    )
    run2 = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    snaps2 = {s["nodeId"]: s for s in run2["bindingSnapshots"]}
    assert snaps2["source_finding"]["agentId"] == "agent-stage"
    assert snaps2["source_finding"]["resolvedFrom"] == "stage_override"

    # workflow default wins over team role (remove stage override).
    runtime_service.put_agent_binding_config(
        CHALLENGE_CUP_WORKFLOW_ID,
        {"stageOverrides": {}},
        team_id="research-team",
    )
    run3 = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    snaps3 = {s["nodeId"]: s for s in run3["bindingSnapshots"]}
    assert snaps3["source_finding"]["agentId"] == "agent-default"
    assert snaps3["source_finding"]["resolvedFrom"] == "workflow_default"


def test_run_snapshot_immune_to_later_team_config(runtime_service, monkeypatch) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    first_snaps = {s["nodeId"]: s["agentId"] for s in run["bindingSnapshots"]}

    # Team config changes after the run was created.
    changed = dict(ROLE_AGENTS)
    changed["source_finder"] = "agent-finder-replaced"
    monkeypatch.setattr(
        "core.web.services.team_service.get_team_canvas",
        lambda team_id: _fake_canvas(roles=changed),
    )

    record = runtime_service.get_run(run["runId"])
    snaps = {s["nodeId"]: s["agentId"] for s in record["bindingSnapshots"]}
    assert snaps == first_snaps
    assert snaps["source_finding"] == ROLE_AGENTS["source_finder"]


def test_effective_bindings_view_reflects_current_config(runtime_service) -> None:
    effective = runtime_service.get_effective_agent_bindings(
        CHALLENGE_CUP_WORKFLOW_ID,
        team_id="research-team",
    )
    by_node = {b["nodeId"]: b for b in effective["bindings"]}
    assert by_node["source_finding"]["agentId"] == ROLE_AGENTS["source_finder"]
    assert by_node["source_finding"]["resolvedFrom"] == "workflow_default"


def test_team_scoped_read_routes_require_camel_team_id(runtime_service) -> None:
    """The public HTTP contract has one canonical teamId query key only."""
    research_run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="other-team")
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})
    base = f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}"

    canonical_runs = client.get(f"{base}/runs?teamId=research-team")
    assert canonical_runs.status_code == 200, canonical_runs.text
    assert [item["runId"] for item in canonical_runs.json()["runs"]] == [research_run["runId"]]

    canonical_bindings = client.get(f"{base}/agent-bindings/effective?teamId=research-team")
    assert canonical_bindings.status_code == 200, canonical_bindings.text
    assert canonical_bindings.json()["teamId"] == "research-team"

    for path in (f"{base}/runs?team_id=research-team", f"{base}/agent-bindings/effective?team_id=research-team"):
        legacy = client.get(path)
        assert legacy.status_code == 422, legacy.text

    blank = client.get(f"{base}/runs?teamId=%20%20")
    assert blank.status_code == 422, blank.text
    missing_body = client.post(f"{base}/runs", json={"idempotencyKey": "missing-team"})
    assert missing_body.status_code == 422, missing_body.text


def test_node_commands_are_scoped_to_real_node_handlers(runtime_service) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")

    source_detail = runtime_service.get_node_detail(run["runId"], "source_finding")
    source_commands = {item["command"]: item for item in source_detail["commands"]}
    assert "start_agent_task" not in source_commands
    assert "run_smoke" not in source_commands
    assert "start_controlled_run" not in source_commands
    assert source_commands["open_session"]["available"] is False

    # A later human gate has no pending task yet, so it must not advertise a
    # clickable resolution action.
    assert runtime_service.get_node_detail(run["runId"], "protocol_freeze")["commands"] == []

    hypothesis_detail = runtime_service.get_node_detail(run["runId"], "hypothesis_design")
    hypothesis_commands = {item["command"]: item for item in hypothesis_detail["commands"]}
    assert hypothesis_commands["start_agent_task"]["available"] is False
    assert "projectId" in hypothesis_commands["start_agent_task"]["reason"]

    with pytest.raises(ResearchWorkflowError) as exc:
        runtime_service.apply_node_command(
            run["runId"],
            "source_finding",
            "start_agent_task",
            payload={},
        )
    assert exc.value.code == "command_not_allowed_for_node"


def test_node_command_project_context_cannot_be_supplied_by_request_payload() -> None:
    with pytest.raises(NodeCommandUnavailable) as exc:
        _require_project({"teamId": "research-team", "projectId": ""}, {"projectId": "spoofed"})
    assert exc.value.code == "no_project_context"


def test_controlled_write_rejects_unknown_role_and_node(runtime_service) -> None:
    with pytest.raises(ResearchWorkflowError) as exc:
        runtime_service.put_agent_binding_config(
            CHALLENGE_CUP_WORKFLOW_ID,
            {"workflowDefaults": {"not_a_role": "agent-x"}},
            team_id="research-team",
        )
    assert exc.value.code == "unknown_role"
    with pytest.raises(ResearchWorkflowError) as exc:
        runtime_service.put_agent_binding_config(
            CHALLENGE_CUP_WORKFLOW_ID,
            {"nodeOverrides": {"knowledge_handoff": "agent-x"}},
            team_id="research-team",
        )
    assert exc.value.code == "unknown_node"  # human gate is not an agent node


def test_all_sixteen_nodes_serve_node_detail(runtime_service) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    definition = build_challenge_cup_workflow_definition()
    for node in definition.nodes:
        detail = runtime_service.get_node_detail(run["runId"], node.nodeId)
        assert detail["nodeId"] == node.nodeId
        assert detail["primaryRoleKey"] == node.primaryRoleKey
        assert "bindingSnapshot" in detail
        assert "commands" in detail
    assert len(definition.nodes) == 16


def test_multiple_pending_human_tasks_only_current_resolves(runtime_service) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    # Inject two pending human tasks for two different gates.
    store = runtime_service._store
    gate_tasks = [
        {"taskId": "ht-a", "runId": run["runId"], "nodeId": "knowledge_handoff", "nodeRunId": "nr-a", "status": "pending", "prompt": "p"},
        {"taskId": "ht-b", "runId": run["runId"], "nodeId": "protocol_freeze", "nodeRunId": "nr-b", "status": "pending", "prompt": "p"},
    ]
    for task in gate_tasks:
        store.upsert_human_task(run["runId"], task)

    runtime_service.resolve_human_task(run["runId"], "ht-a", accept=True, resolved_by="tester")
    record = runtime_service.get_run(run["runId"])
    by_id = {t["taskId"]: t for t in record["humanTasks"]}
    assert by_id["ht-a"]["status"] == "resolved_accept"
    # The other gate's task is untouched.
    assert by_id["ht-b"]["status"] == "pending"


def test_run_list_filters_by_team(runtime_service) -> None:
    run_a = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    run_b = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="other-team")
    only_a = runtime_service.list_runs(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")["runs"]
    only_b = runtime_service.list_runs(CHALLENGE_CUP_WORKFLOW_ID, team_id="other-team")["runs"]
    all_runs = runtime_service.list_runs(CHALLENGE_CUP_WORKFLOW_ID)["runs"]
    assert [r["runId"] for r in only_a] == [run_a["runId"]]
    assert [r["runId"] for r in only_b] == [run_b["runId"]]
    assert {r["runId"] for r in all_runs} == {run_a["runId"], run_b["runId"]}


def test_start_agent_task_writes_full_session_task_turn_binding(
    runtime_service, monkeypatch
) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    # Add a research project context (projectId) so the adapter can resolve.
    runtime_service._store.update_run(run["runId"], {"projectId": "proj-1"})

    started_task = {
        "task": {
            "taskId": "research-agent-task-abc123",
            "taskKind": "experiment_design",
            "agentId": ROLE_AGENTS["experiment_planner"],
            "roleKey": "challenge_cup_experiment_planner",
            "sessionId": "sess-project-1",
            "sessionAttempt": 1,
            "turn": {"turnId": "turn-xyz"},
            "status": "running",
        },
        "researchProjectId": "proj-1",
        "sessionId": "sess-project-1",
        "sessionAttempt": 1,
        "chatRoute": "/chat?session=sess-project-1",
        "idempotentReplay": False,
    }

    def _fake_start(team_id, project_id, payload):
        assert team_id == "research-team"
        assert payload["taskKind"] == "experiment_design"
        return started_task

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks.start_research_project_agent_task",
        _fake_start,
    )

    result = runtime_service.apply_node_command(
        run["runId"],
        "hypothesis_design",
        "start_agent_task",
        payload={},
    )
    assert result["command"] == "start_agent_task"
    binding = result["sessionBinding"]
    assert binding["agentId"] == ROLE_AGENTS["experiment_planner"]
    assert binding["sessionId"] == "sess-project-1"
    assert binding["taskId"] == "research-agent-task-abc123"
    assert binding["turnId"] == "turn-xyz"
    assert binding["status"] == "bound"

    detail = runtime_service.get_node_detail(run["runId"], "hypothesis_design")
    assert detail["sessionAnchorDegraded"] is False
    assert "focusTask=research-agent-task-abc123" in (detail["chatDeepLink"] or "")
    assert "focusTurn=turn-xyz" in (detail["chatDeepLink"] or "")
    assert {item["command"]: item for item in detail["commands"]}["open_session"]["available"] is True


def test_start_agent_task_fails_closed_without_project(runtime_service) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    with pytest.raises(ResearchWorkflowError) as exc:
        runtime_service.apply_node_command(
            run["runId"],
            "hypothesis_design",
            "start_agent_task",
            payload={},
        )
    assert exc.value.code == "no_project_context"


def test_rebind_keeps_lineage_and_history(runtime_service) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    runtime_service.apply_command(
        run["runId"],
        "rebind_node",
        payload={"nodeId": "source_finding", "agentId": "agent-v1"},
    )
    second = runtime_service.apply_command(
        run["runId"],
        "rebind_node",
        payload={"nodeId": "source_finding", "agentId": "agent-v2"},
    )
    snaps = {s["nodeId"]: s for s in second["bindingSnapshots"]}
    assert snaps["source_finding"]["agentId"] == "agent-v2"
    assert snaps["source_finding"]["resolvedFrom"] == "rebind"
    history = [
        h
        for h in second["bindingHistory"]
        if h.get("nodeId") == "source_finding" and h.get("agentId") == "agent-v1"
    ]
    assert history and history[0].get("supersededAt")
    assert history[0]["snapshotId"] != snaps["source_finding"]["snapshotId"]
