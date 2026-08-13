from __future__ import annotations

import json
import threading
from types import SimpleNamespace

from core.web.services import team_workflow_orchestration_service
from core.web.services.team_workflow import research_project_agent_tasks
from core.web.services.team_workflow.research_project_protocol_review_context import (
    build_protocol_review_input_context,
)
from core.web.services.team_workflow.research_runtime import (
    protocol_review_artifact_writer,
    workflow_artifact_store,
)
from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
    load_scoped_artifact_payload,
)
from core.web.services.team_workflow.research_runtime.protocol_review_artifact_writer import (
    record_protocol_review_report,
)
from core.web.services.team_workflow.research_runtime.task_adapter_registry import (
    resolve_agent_task_adapter,
)
from tools.challenge_cup_operations_tools import (
    challenge_cup_experiment_writeback_tool,
)


def _review_task() -> dict[str, object]:
    return {
        "taskId": "task-review-1",
        "taskKind": "protocol_review",
        "taskTitle": "复核并登记正式实验协议",
        "teamId": "research-team",
        "researchProjectId": "project-1",
        "workflowRunId": "run-1",
        "workflowNodeId": "protocol_review",
        "sourceCollectionRunId": "source-run-1",
        "experimentName": "Project 1",
        "targetRef": "node-run:nr-run-1-protocol_review-a1",
        "agentId": "agent-reviewer",
        "roleLabel": "协议评审",
        "sessionId": "session-1",
        "turn": {"turnId": "turn-1"},
        "formalRetry": False,
    }


def _protocol_draft() -> dict[str, object]:
    return {
        "protocolId": "plan-1",
        "planId": "plan-1",
        "status": "draft",
        "dataset": "DANDI:000121@v0.230629.1955",
        "baseline": "rate-only logistic decoder",
        "metric": "held-out balanced accuracy",
        "seed": [42, 2026],
        "budget": {"maxGpuHours": 2},
        "stop_condition": ["delta <= 0", "bootstrap interval crosses zero"],
        "smoke_plan": {"subset": "2 sessions", "maxSteps": 100},
        "hypothesisRefs": ["H1", "H2", "H3"],
    }


def _review_payload() -> dict[str, object]:
    return {
        "status": "approved",
        "blocking_issue_count": 0,
        "open_waivers": 0,
        "checks": {
            "dataset": "pass",
            "baseline": "pass",
            "metric": "pass",
            "seed": "pass",
            "budget": "pass",
            "stop_condition": "pass",
            "smoke_plan": "pass",
        },
        "findings": [],
    }


def test_protocol_review_uses_its_own_formal_task_contract() -> None:
    spec = resolve_agent_task_adapter("protocol_review")

    assert spec is not None
    assert spec.task_key == "protocol_review"


def test_protocol_review_context_reads_formal_protocol_draft(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_protocol_review_context.load_scoped_artifact_payload",
        lambda *args, **kwargs: {"payload": _protocol_draft()},
    )

    context = build_protocol_review_input_context("research-team", _review_task())

    assert context["status"] == "ready"
    assert context["authority"] == "workflow_protocol_draft"
    assert context["workflowRunId"] == "run-1"
    assert context["protocolDraft"]["planId"] == "plan-1"
    writeback = context["writebackContract"]
    assert writeback["tool"] == "challenge_cup_experiment_writeback_tool"
    assert writeback["operation"] == "record_protocol_review"
    assert writeback["payloadSchema"]["blocking_issue_count"] == (
        "non-negative integer"
    )
    assert writeback["approvedPayloadExample"]["checks"] == {
        "dataset": "pass",
        "baseline": "pass",
        "metric": "pass",
        "seed": "pass",
        "budget": "pass",
        "stop_condition": "pass",
        "smoke_plan": "pass",
    }
    assert writeback["approvedPayloadExample"]["findings"] == []


def test_protocol_review_task_context_exposes_formal_input(monkeypatch) -> None:
    task = _review_task()
    service = SimpleNamespace(
        _WORKFLOW_LOCK=threading.RLock(),
        get_research_project=lambda *_args: {"name": "Project 1"},
        _load_experiment_plan_store=lambda _team_id: {"plans": []},
    )
    monkeypatch.setattr(research_project_agent_tasks, "_service", lambda: service)
    monkeypatch.setattr(
        research_project_agent_tasks,
        "require_research_project_agent_task",
        lambda *_args, **_kwargs: task,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_protocol_review_context.build_protocol_review_input_context",
        lambda team_id, bound_task: {
            "status": "ready",
            "teamId": team_id,
            "workflowRunId": bound_task["workflowRunId"],
            "protocolDraft": _protocol_draft(),
        },
    )

    context = research_project_agent_tasks.get_research_project_agent_task_context(
        "research-team",
        "project-1",
        "task-review-1",
    )

    assert context["protocolReviewInput"]["protocolDraft"]["planId"] == "plan-1"


def test_protocol_review_task_message_embeds_formal_input(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_protocol_review_context.build_protocol_review_input_context",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "authority": "workflow_protocol_draft",
            "workflowRunId": "run-1",
            "protocolDraft": _protocol_draft(),
            "writebackContract": {
                "tool": "challenge_cup_experiment_writeback_tool",
                "operation": "record_protocol_review",
                "approvedPayloadExample": _review_payload(),
            },
        },
    )

    message = research_project_agent_tasks._task_message(
        task=_review_task(),
        contract=research_project_agent_tasks.TASK_KIND_CONTRACTS["protocol_review"],
    )

    assert "正式输入 protocolReviewInput" in message
    assert '"authority":"workflow_protocol_draft"' in message
    assert '"planId":"plan-1"' in message
    assert "operation=record_protocol_review" in message
    assert '"blocking_issue_count":0' in message
    assert '"dataset":"pass"' in message
    assert '"findings":[]' in message
    assert "旧实验结果账本不得覆盖" in message


def test_protocol_review_writer_persists_approved_report(monkeypatch) -> None:
    writes: list[dict[str, object]] = []
    monkeypatch.setattr(
        protocol_review_artifact_writer,
        "put_workflow_artifact",
        lambda team_id, **kwargs: writes.append({"teamId": team_id, **kwargs})
        or {"recordId": "review-task-review-1", "contentHash": "sha-review"},
    )

    result = record_protocol_review_report(
        team_id="research-team",
        task_context={
            "task": _review_task(),
            "protocolReviewInput": {
                "status": "ready",
                "protocolDraft": _protocol_draft(),
            },
        },
        payload=_review_payload(),
    )

    assert writes[0]["kind"] == "protocol_review_report"
    assert writes[0]["workflow_run_id"] == "run-1"
    assert writes[0]["source_collection_run_id"] == "source-run-1"
    assert writes[0]["artifact_identity"] == "review-task-review-1"
    assert writes[0]["payload"]["protocolId"] == "plan-1"
    assert writes[0]["payload"]["blocking_issue_count"] == 0
    assert result["artifact"]["kind"] == "protocol_review_report"


def test_protocol_review_report_reads_back_from_formal_store(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    workflow_artifact_store.put_workflow_artifact(
        "research-team",
        kind="protocol_review_report",
        workflow_run_id="run-1",
        source_collection_run_id="source-run-1",
        artifact_identity="review-task-review-1",
        payload={
            "reviewId": "review-task-review-1",
            "protocolId": "plan-1",
            "status": "approved",
            "blocking_issue_count": 0,
            "open_waivers": 0,
        },
    )

    envelope = load_scoped_artifact_payload(
        "protocol_review_report",
        team_id="research-team",
        authority_run_id="source-run-1",
        workflow_run_id="run-1",
    )

    assert envelope is not None
    assert envelope["payload"]["protocolId"] == "plan-1"


def test_protocol_review_writeback_updates_task_result_refs(monkeypatch) -> None:
    task_context = {
        "task": _review_task(),
        "protocolReviewInput": {
            "status": "ready",
            "protocolDraft": _protocol_draft(),
        },
    }
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "require_research_project_agent_task",
        lambda *_args, **_kwargs: task_context["task"],
        raising=False,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "get_research_project_agent_task_context",
        lambda *_args, **_kwargs: task_context,
        raising=False,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "update_research_project_agent_task_status",
        lambda *_args, **kwargs: {
            "taskId": "task-review-1",
            "status": kwargs["status"],
            "resultRefs": kwargs["result_refs"],
        },
    )
    monkeypatch.setattr(
        protocol_review_artifact_writer,
        "record_protocol_review_report",
        lambda **_kwargs: {
            "artifact": {
                "recordId": "review-task-review-1",
                "kind": "protocol_review_report",
            }
        },
    )

    result = json.loads(
        challenge_cup_experiment_writeback_tool(
            team_id="research-team",
            research_project_id="project-1",
            task_id="task-review-1",
            operation="record_protocol_review",
            payload_json=json.dumps(_review_payload()),
            recorded_by_agent="agent-reviewer",
        )
    )

    assert result["status"] == "ok"
    assert result["operation"] == "record_protocol_review"
    assert result["response"]["artifact"]["kind"] == "protocol_review_report"
    assert result["task"]["resultRefs"] == ["review-task-review-1"]
