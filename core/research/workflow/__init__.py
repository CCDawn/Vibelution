"""Challenge Cup research workflow domain (LangGraph runtime authority).

Task 1: pure domain contracts and fixed definition. Runtime/checkpointer live in later tasks.
"""

from .definition import (
    CHALLENGE_CUP_WORKFLOW_ID,
    build_challenge_cup_workflow_definition,
    definition_structure_hash,
)
from .iteration_decisions import (
    CompletionKind,
    IterationDecisionKind,
    IterationDecisionRecord,
    PromotionOperation,
)
from .models import (
    ActorKind,
    ArtifactRef,
    GateKind,
    HandoffStatus,
    HumanTaskStatus,
    NodeHandoffRecord,
    NodeRunStatus,
    RunAgentBindingSnapshot,
    WorkflowDefinition,
    WorkflowNodeSpec,
    WorkflowRunStatus,
    WorkflowStageId,
    WorkflowStageSpec,
)

__all__ = [
    "ActorKind",
    "ArtifactRef",
    "CHALLENGE_CUP_WORKFLOW_ID",
    "CompletionKind",
    "GateKind",
    "HandoffStatus",
    "HumanTaskStatus",
    "IterationDecisionKind",
    "IterationDecisionRecord",
    "NodeHandoffRecord",
    "NodeRunStatus",
    "PromotionOperation",
    "RunAgentBindingSnapshot",
    "WorkflowDefinition",
    "WorkflowNodeSpec",
    "WorkflowRunStatus",
    "WorkflowStageId",
    "WorkflowStageSpec",
    "build_challenge_cup_workflow_definition",
    "definition_structure_hash",
]
