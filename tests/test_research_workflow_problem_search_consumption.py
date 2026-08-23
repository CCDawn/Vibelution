"""Static contracts for the problem-understanding search lane.

The task adapter owns the research-project task kind, while model routing owns
the ``source_discovery`` purpose and the product Agent role.  Receipt mapping
is kept beside NodeRun execution so a formal task cannot silently lose its
source-evidence outcome.
"""

from __future__ import annotations

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
