"""Static contracts for the problem-understanding search lane.

The task adapter owns the research-project task kind, while model routing owns
the ``source_discovery`` purpose and the product Agent role.  Receipt mapping
is kept beside NodeRun execution so a formal task cannot silently lose its
source-evidence outcome.
"""

from __future__ import annotations

from core.web.services.team_workflow.research_runtime import agent_node_execution
from core.web.services.team_workflow.research_runtime.agent_node_execution import (
    _MODEL_INVOCATION_OUTCOME_KINDS,
    _MODEL_INVOCATION_STAGES,
)
from core.web.services.team_workflow.research_runtime.model_routing import (
    NODE_MODEL_PRODUCT_ROLE,
    NODE_MODEL_PURPOSE,
)
from core.web.services.team_workflow.research_runtime.task_adapter_registry import (
    PROJECT_NODE_TASKS,
    SOURCE_NODE_TASKS,
    resolve_agent_task_adapter,
)


def test_problem_understanding_uses_project_search_task_adapter() -> None:
    spec = resolve_agent_task_adapter("problem_understanding")

    assert spec is not None
    assert spec.family == "research_project"
    assert spec.task_key == "problem_understanding"
    assert PROJECT_NODE_TASKS["problem_understanding"] == "problem_understanding"
    assert "problem_understanding" not in SOURCE_NODE_TASKS


def test_problem_understanding_routes_to_search_agent_source_discovery() -> None:
    assert NODE_MODEL_PURPOSE["problem_understanding"] == "source_discovery"
    assert NODE_MODEL_PRODUCT_ROLE["problem_understanding"] == "challenge_cup_search"


def test_problem_understanding_emits_source_evidence_receipt() -> None:
    assert _MODEL_INVOCATION_OUTCOME_KINDS["problem_understanding"] == (
        "source_evidence",
    )
    assert _MODEL_INVOCATION_STAGES["problem_understanding"] == "generation"


def test_problem_understanding_creates_source_run_before_project_task(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []
    record = {
        "teamId": "team-a",
        "projectId": "project-a",
        "runId": "workflow-a",
    }

    def ensure_source_run(_store, current):
        calls.append({"ensure": True})
        return {**current, "sourceCollectionRunId": "source-a"}, "source-a"

    monkeypatch.setattr(
        agent_node_execution, "_ensure_source_collection_run", ensure_source_run
    )
    monkeypatch.setattr(
        agent_node_execution, "_challenge_task_contract", lambda *_args, **_kwargs: {}
    )
    monkeypatch.setattr(
        agent_node_execution,
        "_model_invocation_receipt_binding",
        lambda *_args, **_kwargs: {},
    )

    from core.web.services.team_workflow import research_project_agent_tasks

    monkeypatch.setattr(
        research_project_agent_tasks,
        "start_research_project_agent_task",
        lambda team_id, project_id, payload: calls.append(
            {"teamId": team_id, "projectId": project_id, "payload": payload}
        )
        or {"task": {"taskId": "task-a"}},
    )

    updated, _started = agent_node_execution._start_external_task(
        object(),
        record,
        node_id="problem_understanding",
        node_run_id="node-a",
        agent_id="agent-search",
        idempotency_key="problem-a",
        payload={},
    )

    assert updated["sourceCollectionRunId"] == "source-a"
    assert calls[0] == {"ensure": True}
    assert calls[1]["payload"]["sourceCollectionRunId"] == "source-a"
