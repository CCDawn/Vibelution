"""Agent node command capabilities own deterministic budget allocation."""

from __future__ import annotations

from core.web.services.team_workflow.research_runtime.node_command_adapter import (
    node_command_capabilities,
)


def _record(*, completed_node_ids: list[str] | None = None) -> dict:
    return {
        "projectId": "project-budget-capability",
        "bindingSnapshots": [
            {
                "nodeId": "source_finding",
                "roleKey": "source_finder",
                "agentId": "agent-source-finder",
            }
        ],
        "completedNodeIds": list(completed_node_ids or []),
        "nodeRuns": [],
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
