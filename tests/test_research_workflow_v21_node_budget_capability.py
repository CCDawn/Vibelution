"""Agent node command capabilities own deterministic budget allocation."""

from __future__ import annotations

from core.web.services.team_workflow.research_runtime.node_command_adapter import (
    node_command_capabilities,
)


def _record(*, completed_node_ids: list[str] | None = None) -> dict:
    return {
        "runId": "run-budget-capability",
        "projectId": "project-budget-capability",
        "bindingSnapshots": [
            {
                "nodeId": "source_finding",
                "roleKey": "source_finder",
                "agentId": "agent-source-finder",
            }
        ],
        "completedNodeIds": list(completed_node_ids or []),
        "nodeRuns": [
            {
                "nodeRunId": "nr-run-budget-capability-source_finding-a1",
                "nodeId": "source_finding",
                "attempt": 1,
                "status": "ready",
            }
        ],
        "budgetLedgers": [
            {
                "stageId": "knowledge_collection",
                "remaining": {
                    "tokens": 1000,
                    "toolCalls": 12,
                    "wallClockSeconds": 120,
                    "experiments": 4,
                    "computeUnits": 20,
                },
                "stopReason": "",
            }
        ],
    }


def _start_capability(record: dict) -> dict:
    return next(
        item
        for item in node_command_capabilities(record, "source_finding")
        if item["command"] == "start_agent_task"
    )


def test_start_agent_capability_carries_backend_allocated_budget_request() -> None:
    capability = _start_capability(_record())

    assert capability == {
        "command": "start_agent_task",
        "available": True,
        "reason": "",
        "idempotencyKey": "agent-task:nr-run-budget-capability-source_finding-a1",
        "payload": {
            "budgetRequest": {
                "tokens": 250,
                "toolCalls": 3,
                "wallClockSeconds": 30,
                "experiments": 1,
                "computeUnits": 5,
            }
        },
    }


def test_start_agent_capability_fails_closed_when_stage_budget_is_exhausted() -> None:
    record = _record()
    record["budgetLedgers"][0]["remaining"] = {
        "tokens": 0,
        "toolCalls": 0,
        "wallClockSeconds": 0,
        "experiments": 0,
        "computeUnits": 0,
    }

    capability = _start_capability(record)

    assert capability["available"] is False
    assert capability["reason"] == "当前阶段预算已耗尽"
    assert "payload" not in capability


def test_start_agent_capability_replays_reserved_budget_and_key_after_partial_failure() -> None:
    record = _record()
    original_request = {
        "tokens": 250,
        "toolCalls": 3,
        "wallClockSeconds": 30,
        "experiments": 1,
        "computeUnits": 5,
    }
    record["budgetLedgers"][0]["remaining"] = {
        "tokens": 750,
        "toolCalls": 9,
        "wallClockSeconds": 90,
        "experiments": 3,
        "computeUnits": 15,
    }
    record["budgetReservations"] = [
        {
            "reservationId": "reservation-nr-run-budget-capability-source_finding-a1",
            "nodeRunId": "nr-run-budget-capability-source_finding-a1",
            "idempotencyKey": "node:run-budget-capability:source_finding:start_agent_task:v1",
            "requested": original_request,
        }
    ]
    record["taskBundles"] = [
        {
            "parentNodeRunId": "nr-run-budget-capability-source_finding-a1",
            "idempotencyKey": "node:run-budget-capability:source_finding:start_agent_task:v1",
        }
    ]

    capability = _start_capability(record)

    assert capability == {
        "command": "start_agent_task",
        "available": True,
        "reason": "",
        "idempotencyKey": "node:run-budget-capability:source_finding:start_agent_task:v1",
        "payload": {"budgetRequest": original_request},
    }


def test_start_agent_capability_fails_closed_before_node_is_scheduled() -> None:
    record = _record()
    record["nodeRuns"] = []

    capability = _start_capability(record)

    assert capability["available"] is False
    assert capability["reason"] == "node is not scheduled: source_finding"
    assert "idempotencyKey" not in capability
    assert "payload" not in capability
