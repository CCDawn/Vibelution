"""Version-pinned terminal policy for operator optimization runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.research.workflow.definition_registry import (
    WorkflowDefinitionRegistryError,
    resolve_definition_by_version_id,
)
from core.research.workflow.operator_optimization_definition import (
    OPERATOR_WORKFLOW_ID,
)


@dataclass(frozen=True, slots=True)
class OperatorRoundTerminalPolicy:
    node_id: str
    completion_kind: str
    terminal_reason: str


def operator_round_terminal_policy(run: Any) -> OperatorRoundTerminalPolicy | None:
    """Resolve terminal semantics from the definition pinned to ``run``.

    Non-operator runs return ``None``. Operator runs fail closed when their
    frozen definition identity is absent, unknown, belongs to another
    workflow, or has an unsupported terminal shape.
    """
    workflow_id = str(getattr(run, "workflow_id", "") or "").strip()
    if workflow_id != OPERATOR_WORKFLOW_ID:
        return None

    workflow_version_id = str(
        getattr(run, "workflow_version_id", "") or ""
    ).strip()
    definition = resolve_definition_by_version_id(workflow_version_id)
    if definition.workflowId != workflow_id:
        raise WorkflowDefinitionRegistryError(
            "pinned operator definition belongs to another workflow: "
            f"workflowId={workflow_id} "
            f"workflowVersionId={workflow_version_id} "
            f"resolvedWorkflowId={definition.workflowId}"
        )

    source_nodes = {edge.fromNodeId for edge in definition.edges}
    terminal_nodes = tuple(
        node.nodeId for node in definition.nodes if node.nodeId not in source_nodes
    )
    if terminal_nodes == ("optimization_feedback",):
        reason = "optimization_feedback_verified"
    elif terminal_nodes == ("optimization_decision",):
        reason = "optimization_decision_verified"
    else:
        raise WorkflowDefinitionRegistryError(
            "unsupported operator terminal definition: "
            f"workflowVersionId={workflow_version_id} "
            f"terminalNodes={list(terminal_nodes)}"
        )
    return OperatorRoundTerminalPolicy(
        node_id=terminal_nodes[0],
        completion_kind="operator_round_completed",
        terminal_reason=reason,
    )
