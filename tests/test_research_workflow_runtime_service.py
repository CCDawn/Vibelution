"""Task 3: research workflow runtime service + route contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.service import (
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


@pytest.fixture()
def runtime_service(tmp_path: Path):
    store = WorkflowRunStore(tmp_path / "runs")
    ckpt = str(tmp_path / "ckpt.sqlite")
    return reset_research_workflow_runtime_service_for_tests(run_store=store, checkpoint_path=ckpt)


def test_create_run_waiting_human_and_resolve(runtime_service) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, team_id="research-team")
    assert run["status"] == "waiting_human"
    assert "knowledge_handoff" in run["runtimeCurrentNodeIds"]
    assert run["bindingSnapshots"]
    assert run["humanTasks"]
    task_id = run["humanTasks"][0]["taskId"]

    after = runtime_service.resolve_human_task(run["runId"], task_id, accept=True, resolved_by="tester")
    kh = [h for h in after["handoffs"] if h["fromNodeId"] == "knowledge_handoff"]
    assert kh and kh[-1]["status"] == "accepted"
    assert kh[-1]["toNodeId"] == "hypothesis_design"
    assert kh[-1]["outputArtifactRefs"][0]["kind"] == "knowledge_package"
    assert after["langGraph"].get("knowledgePackageAccepted") is True
    # Full topology continues to later human gates after knowledge handoff.
    assert after["status"] in {"waiting_human", "running", "succeeded", "blocked"}
    assert any(t["status"] == "pending" and t["nodeId"] == "protocol_freeze" for t in after["humanTasks"])


def test_command_idempotency(runtime_service) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, idempotency_key="create-once")
    again = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID, idempotency_key="create-once")
    assert again["runId"] == run["runId"]

    cancelled = runtime_service.apply_command(run["runId"], "cancel", idempotency_key="c1")
    cancelled2 = runtime_service.apply_command(run["runId"], "cancel", idempotency_key="c1")
    assert cancelled["status"] == "cancelled"
    assert cancelled2["status"] == "cancelled"


def test_node_detail_degraded_without_session_anchor(runtime_service) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    detail = runtime_service.get_node_detail(run["runId"], "source_finding")
    assert detail["sessionAnchorDegraded"] is True
    assert detail["chatDeepLink"] is None

    # Session binding is fail-closed: an unbound node must be rejected.
    with pytest.raises(Exception, match="unbound"):
        runtime_service.put_session_binding(
            run["runId"],
            "source_finding",
            {
                "sessionId": "sess-1",
                "taskId": "task-1",
                "turnId": "turn-1",
                "agentId": "agent-1",
                "roleKey": "source_finder",
            },
        )

    # Bind an agent first (controlled rebind), then attach the session anchor.
    runtime_service.apply_command(
        run["runId"],
        "rebind_node",
        payload={"nodeId": "source_finding", "agentId": "agent-1"},
    )
    runtime_service.put_session_binding(
        run["runId"],
        "source_finding",
        {
            "sessionId": "sess-1",
            "taskId": "task-1",
            "turnId": "turn-1",
            "agentId": "agent-1",
            "roleKey": "source_finder",
        },
    )
    detail2 = runtime_service.get_node_detail(run["runId"], "source_finding")
    assert detail2["sessionAnchorDegraded"] is False
    assert "focusTask=task-1" in (detail2["chatDeepLink"] or "")
    assert "focusTurn=turn-1" in (detail2["chatDeepLink"] or "")


def test_session_binding_rejects_agent_mismatch(runtime_service) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    runtime_service.apply_command(
        run["runId"],
        "rebind_node",
        payload={"nodeId": "source_finding", "agentId": "agent-bound"},
    )
    with pytest.raises(Exception, match="does not match"):
        runtime_service.put_session_binding(
            run["runId"],
            "source_finding",
            {
                "sessionId": "sess-1",
                "taskId": "task-1",
                "turnId": "turn-1",
                "agentId": "agent-other",
            },
        )


def test_session_binding_supersedes_keeps_lineage(runtime_service) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    runtime_service.apply_command(
        run["runId"],
        "rebind_node",
        payload={"nodeId": "source_finding", "agentId": "agent-1"},
    )
    first = runtime_service.put_session_binding(
        run["runId"],
        "source_finding",
        {
            "sessionId": "sess-a",
            "taskId": "task-a",
            "turnId": "turn-a",
            "agentId": "agent-1",
        },
    )
    second = runtime_service.put_session_binding(
        run["runId"],
        "source_finding",
        {
            "sessionId": "sess-b",
            "taskId": "task-b",
            "turnId": "turn-b",
            "agentId": "agent-1",
        },
    )
    assert second["supersedesBindingId"] == first["bindingId"]
    record = runtime_service.get_run(run["runId"])
    history = [h for h in record["bindingHistory"] if h.get("bindingId") == first["bindingId"]]
    assert history and history[0]["supersededAt"]


def test_rebind_node_updates_snapshot_not_silent(runtime_service) -> None:
    run = runtime_service.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    updated = runtime_service.apply_command(
        run["runId"],
        "rebind_node",
        payload={"nodeId": "source_finding", "agentId": "agent-new"},
    )
    snap = next(s for s in updated["bindingSnapshots"] if s["nodeId"] == "source_finding")
    assert snap["agentId"] == "agent-new"
    assert snap["resolvedFrom"] == "rebind"


def test_legacy_flow_canvas_execute_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.web.services import research_service

    monkeypatch.delenv("VIBELUTION_LEGACY_FLOW_CANVAS_EXECUTE", raising=False)
    with pytest.raises(ValueError, match="Legacy /api/research/flow-canvas/execute is disabled"):
        research_service.execute_research_flow_canvas_node("session-x", node_id="broad_search")


def test_http_definition_and_create_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = WorkflowRunStore(tmp_path / "runs")
    ckpt = str(tmp_path / "ckpt.sqlite")
    reset_research_workflow_runtime_service_for_tests(run_store=store, checkpoint_path=ckpt)

    from core.web.app import create_app
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})
    defn = client.get(f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/definition")
    assert defn.status_code == 200
    body = defn.json()
    assert body["definition"]["workflowId"] == CHALLENGE_CUP_WORKFLOW_ID
    assert len(body["definition"]["nodes"]) == 16
    assert "selectedNodeId" not in str(body)

    created = client.post(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/runs",
        json={"teamId": "research-team", "idempotencyKey": "http-1"},
    )
    assert created.status_code == 201
    run = created.json()
    run_id = run["runId"]
    got = client.get(f"/api/research/workflow-runs/{run_id}")
    assert got.status_code == 200
    canvas = client.get(f"/api/research/workflow-runs/{run_id}/canvas")
    assert canvas.status_code == 200
    assert "selectedNodeId" not in canvas.text
    assert canvas.json()["run"]["runtimeCurrentNodeIds"]

    task_id = run["humanTasks"][0]["taskId"]
    resolved = client.post(
        f"/api/research/workflow-runs/{run_id}/human-tasks/{task_id}/resolve",
        json={"accept": True, "resolvedBy": "qa"},
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["handoffs"][0]["status"] == "accepted"
    assert body["langGraph"].get("knowledgePackageAccepted") is True
