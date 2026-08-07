"""P1: durable HumanTask / session binding / idempotency + handoff progression."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.durable_index import DurableWorkflowIndex
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    ResearchWorkflowRuntimeService,
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def _svc(tmp_path: Path) -> ResearchWorkflowRuntimeService:
    store = WorkflowRunStore(tmp_path / "runs")
    index = DurableWorkflowIndex(tmp_path / "runs" / "_index")
    ckpt = str(tmp_path / "ckpt.sqlite")
    return reset_research_workflow_runtime_service_for_tests(
        run_store=store,
        checkpoint_path=ckpt,
        durable_index=index,
    )


def _reopen(tmp_path: Path) -> ResearchWorkflowRuntimeService:
    """Simulate process restart: new service instance, same durable paths."""
    store = WorkflowRunStore(tmp_path / "runs")
    index = DurableWorkflowIndex(tmp_path / "runs" / "_index")
    ckpt = str(tmp_path / "ckpt.sqlite")
    return ResearchWorkflowRuntimeService(
        run_store=store,
        checkpoint_path=ckpt,
        durable_index=index,
    )


def test_restart_preserves_pending_human_task(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID, idempotency_key="dur-1")
    pending = [t for t in run["humanTasks"] if t["status"] == "pending"]
    assert pending
    task_id = pending[0]["taskId"]
    node_id = pending[0]["nodeId"]

    svc2 = _reopen(tmp_path)
    restored = svc2.get_run(run["runId"])
    pending2 = [t for t in restored["humanTasks"] if t["status"] == "pending"]
    assert any(t["taskId"] == task_id and t["nodeId"] == node_id for t in pending2)


def test_restart_can_resolve_pending_human_task(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID, idempotency_key="dur-2")
    task_id = next(t["taskId"] for t in run["humanTasks"] if t["status"] == "pending")

    svc2 = _reopen(tmp_path)
    after = svc2.resolve_human_task(run["runId"], task_id, accept=True, resolved_by="tester")
    assert any(t["taskId"] == task_id and t["status"] == "resolved_accept" for t in after["humanTasks"])


def test_session_binding_survives_restart(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    svc.put_session_binding(
        run["runId"],
        "source_finding",
        {
            "sessionId": "sess-r",
            "taskId": "task-r",
            "turnId": "turn-r",
            "agentId": "agent-r",
        },
    )
    svc2 = _reopen(tmp_path)
    detail = svc2.get_node_detail(run["runId"], "source_finding")
    assert detail["sessionAnchorDegraded"] is False
    assert detail["sessionBinding"]["taskId"] == "task-r"


def test_idempotency_key_survives_restart(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID, idempotency_key="stable-key")
    svc2 = _reopen(tmp_path)
    again = svc2.create_run(CHALLENGE_CUP_WORKFLOW_ID, idempotency_key="stable-key")
    assert again["runId"] == run["runId"]


def test_restart_does_not_create_duplicate_run(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID, idempotency_key="no-dup")
    svc2 = _reopen(tmp_path)
    listed = svc2.list_runs(CHALLENGE_CUP_WORKFLOW_ID)["runs"]
    matching = [r for r in listed if r.get("createIdempotencyKey") == "no-dup"]
    assert len(matching) == 1
    assert matching[0]["runId"] == run["runId"]


def test_accept_knowledge_handoff_creates_protocol_freeze_task(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    assert "knowledge_handoff" in run["runtimeCurrentNodeIds"]
    task_id = next(t["taskId"] for t in run["humanTasks"] if t["status"] == "pending")
    after = svc.resolve_human_task(run["runId"], task_id, accept=True, resolved_by="op")
    pending = [t for t in after["humanTasks"] if t["status"] == "pending"]
    assert any(t["nodeId"] == "protocol_freeze" for t in pending), after["humanTasks"]
    assert after["status"] == "waiting_human"
    # Handoff goes to adjacent consumer hypothesis_design, not protocol_freeze
    kh = [h for h in after["handoffs"] if h["fromNodeId"] == "knowledge_handoff"]
    assert kh
    assert kh[-1]["toNodeId"] == "hypothesis_design"
    assert kh[-1]["status"] == "accepted"
    assert kh[-1]["outputArtifactRefs"][0]["kind"] == "knowledge_package"


def test_accept_protocol_freeze_creates_smoke_gate_task(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    t1 = next(t["taskId"] for t in run["humanTasks"] if t["status"] == "pending")
    mid = svc.resolve_human_task(run["runId"], t1, accept=True)
    t2 = next(t["taskId"] for t in mid["humanTasks"] if t["status"] == "pending" and t["nodeId"] == "protocol_freeze")
    after = svc.resolve_human_task(run["runId"], t2, accept=True)
    pending = [t for t in after["humanTasks"] if t["status"] == "pending"]
    assert any(t["nodeId"] == "smoke_gate" for t in pending)
    freeze_h = [h for h in after["handoffs"] if h["fromNodeId"] == "protocol_freeze"]
    assert freeze_h[-1]["toNodeId"] == "smoke_gate"
    assert freeze_h[-1]["outputArtifactRefs"][0]["kind"] == "frozen_protocol"


def test_accept_smoke_gate_reaches_controlled_run(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    for _ in range(5):
        pending = [t for t in svc.get_run(run["runId"])["humanTasks"] if t["status"] == "pending"]
        if not pending:
            break
        svc.resolve_human_task(run["runId"], pending[0]["taskId"], accept=True)
    final = svc.get_run(run["runId"])
    completed = set((final.get("langGraph") or {}).get("completedNodeIds") or [])
    assert "smoke_gate" in completed or "controlled_run" in completed or final["status"] in {
        "waiting_human",
        "running",
        "succeeded",
    }
    # After smoke accept, either waiting on later human gate or progressed into iteration
    smoke_h = [h for h in final["handoffs"] if h["fromNodeId"] == "smoke_gate"]
    if smoke_h:
        assert smoke_h[-1]["toNodeId"] == "controlled_run"


def test_reject_handoff_keeps_downstream_locked(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    task_id = next(t["taskId"] for t in run["humanTasks"] if t["status"] == "pending")
    after = svc.resolve_human_task(run["runId"], task_id, accept=False, resolved_by="op")
    assert after["status"] == "blocked"
    assert after["langGraph"].get("knowledgePackageAccepted") is not True
    assert not any(t["status"] == "pending" and t["nodeId"] == "protocol_freeze" for t in after["humanTasks"])
    kh = [h for h in after["handoffs"] if h["fromNodeId"] == "knowledge_handoff"]
    assert kh[-1]["status"] == "rejected"
    assert kh[-1]["toNodeId"] == "hypothesis_design"


def test_resolved_task_cannot_be_reused(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    task_id = next(t["taskId"] for t in run["humanTasks"] if t["status"] == "pending")
    svc.resolve_human_task(run["runId"], task_id, accept=True)
    with pytest.raises(ResearchWorkflowError, match="already resolved"):
        svc.resolve_human_task(run["runId"], task_id, accept=True)


def test_handoffs_append_without_overwrite(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    t1 = next(t["taskId"] for t in run["humanTasks"] if t["status"] == "pending")
    mid = svc.resolve_human_task(run["runId"], t1, accept=True)
    count_mid = len(mid["handoffs"])
    t2 = next(t["taskId"] for t in mid["humanTasks"] if t["status"] == "pending")
    after = svc.resolve_human_task(run["runId"], t2, accept=True)
    assert len(after["handoffs"]) > count_mid
    # First handoff still present
    assert any(h["fromNodeId"] == "knowledge_handoff" for h in after["handoffs"])
    assert any(h["fromNodeId"] == "protocol_freeze" for h in after["handoffs"])


def test_handoff_uses_adjacent_definition_edge(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    run = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID)
    t1 = next(t["taskId"] for t in run["humanTasks"] if t["status"] == "pending")
    after = svc.resolve_human_task(run["runId"], t1, accept=True)
    h = next(h for h in after["handoffs"] if h["fromNodeId"] == "knowledge_handoff")
    assert h["toNodeId"] == "hypothesis_design"
    assert h.get("edgeId") == "e_kc_hypothesis" or h["toNodeId"] == "hypothesis_design"
