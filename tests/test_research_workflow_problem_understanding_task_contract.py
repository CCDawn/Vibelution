from __future__ import annotations

import pytest

from core.web.services.team_workflow import research_project_agent_tasks
from core.web.services.team_workflow.research_runtime import (
    problem_understanding_artifact_writer as writer,
)


def _payload() -> dict[str, object]:
    return {
        "scope": "可证伪的记忆提取机制",
        "subquestions": ["哪些机制可以被区分？"],
        "assumptions": ["输入数据能够覆盖对照条件"],
        "known_unknowns": ["跨任务泛化仍未知"],
        "human_gate": {
            "required": True,
            "decision": "pending",
            "rationale": "需要研究负责人确认范围后再搜集资料。",
        },
    }


def _task(**overrides: object) -> dict[str, object]:
    task: dict[str, object] = {
        "taskId": "task-problem-1",
        "taskKind": "problem_understanding",
        "teamId": "research-team",
        "researchProjectId": "project-1",
        "questionId": "SCI-096",
        "workflowRunId": "run-1",
        "workflowNodeId": "problem_understanding",
        "nodeRunId": "node-run-1",
        "attempt": 1,
        "sourceCollectionRunId": "source-run-1",
        "agentId": "agent-search",
        "teamRole": "source_finder",
        "roleKey": "challenge_cup_search",
        "sessionId": "session-1",
        "turn": {"turnId": "turn-1"},
    }
    task.update(overrides)
    return task


def test_problem_understanding_contract_is_bound_to_search_seat_and_node() -> None:
    contract = research_project_agent_tasks.TASK_KIND_CONTRACTS[
        "problem_understanding"
    ]

    assert contract["teamRole"] == "source_finder"
    assert contract["roleKey"] == "challenge_cup_search"
    assert contract["workflowNodeId"] == "problem_understanding"
    assert contract["requiresWorkflowAuthority"] is True
    assert "record_problem_understanding" in " ".join(contract["checklist"])


@pytest.mark.parametrize(
    "field",
    ["taskKind", "workflowNodeId", "workflowRunId", "nodeRunId", "sessionId"],
)
def test_problem_writer_fails_closed_when_task_authority_is_incomplete(field: str) -> None:
    task = _task()
    task[field] = "wrong" if field in {"taskKind", "workflowNodeId"} else ""

    with pytest.raises(ValueError):
        writer.write_problem_understanding_artifact(
            team_id="research-team",
            task_context={"teamId": "research-team", "task": task},
            problem_understanding=_payload(),
        )


def test_problem_writer_uses_server_task_scope_not_payload_identity(monkeypatch) -> None:
    binding = {
        "workflowRunId": "run-server",
        "sourceCollectionRunId": "source-server",
        "nodeRunId": "node-server",
    }
    writes: list[dict[str, object]] = []
    monkeypatch.setattr(
        writer,
        "_authoritative_problem_understanding_binding",
        lambda *_args, **_kwargs: binding,
    )
    monkeypatch.setattr(
        writer,
        "put_workflow_artifact",
        lambda team_id, **kwargs: writes.append({"teamId": team_id, **kwargs})
        or {
            "recordId": "node-server",
            "teamId": team_id,
            "kind": "problem_understanding",
            "workflowRunId": "run-server",
            "sourceCollectionRunId": "source-server",
            "contentHash": "a" * 64,
        },
    )

    result = writer.write_problem_understanding_artifact(
        team_id="research-team",
        task_context={"teamId": "research-team", "task": _task()},
        problem_understanding=_payload(),
    )

    assert writes[0]["workflow_run_id"] == "run-server"
    assert writes[0]["source_collection_run_id"] == "source-server"
    assert writes[0]["artifact_identity"] == "node-server"
    assert result["scopeBinding"]["nodeRunId"] == "node-server"


def test_problem_payload_keeps_exact_shape() -> None:
    with pytest.raises(ValueError, match="unsupported fields"):
        writer.validate_problem_understanding({**_payload(), "summary": "noise"})
