"""Create child WorkflowRun for revise_protocol (protocol revision fork)."""

from __future__ import annotations

import uuid
from typing import Any, Callable

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID


def build_child_run_skeleton(
    *,
    parent: dict[str, Any],
    decision: dict[str, Any],
    fork_checkpoint_id: str,
    utc_now: Callable[[], str],
    child_run_id: str | None = None,
) -> dict[str, Any]:
    """Build the durable record fields for a revision child (not yet started in graph)."""
    parent_id = str(parent.get("runId") or "")
    decision_id = str(decision.get("decisionId") or "")
    artifacts = dict((parent.get("langGraph") or {}).get("artifacts") or {})
    child_id = child_run_id or f"run-{uuid.uuid4().hex[:12]}"
    return {
        "runId": child_id,
        "workflowId": parent.get("workflowId") or CHALLENGE_CUP_WORKFLOW_ID,
        "workflowVersionId": parent.get("workflowVersionId") or "",
        "structureHash": parent.get("structureHash") or "",
        "teamId": parent.get("teamId") or "",
        "projectId": parent.get("projectId") or "",
        "threadId": f"thread-{child_id}",
        "status": "queued",
        "runtimeCurrentNodeIds": ["protocol_design"],
        "parentRunId": parent_id,
        "forkedFromRunId": parent_id,
        "forkedFromNodeId": "iteration_decision",
        "forkedFromCheckpointId": fork_checkpoint_id,
        "forkDecisionId": decision_id,
        "inheritedKnowledgePackageRef": str(artifacts.get("knowledge_package") or ""),
        "inheritedEvaluationReportRef": str(artifacts.get("evaluation_report") or ""),
        "inheritedFrozenProtocolRef": str(artifacts.get("frozen_protocol") or ""),
        "bindingSnapshots": list(parent.get("bindingSnapshots") or []),
        "events": [],
        "humanTasks": [],
        "handoffs": [],
        "sessionBindings": {},
        "iterationDecisions": [],
        "nodeAttempts": {},
        "officialCandidateRef": "",
        "baselineCandidateRef": str(parent.get("baselineCandidateRef") or parent.get("officialCandidateRef") or ""),
        "completionKind": "",
        "createdAt": utc_now(),
        "langGraph": {
            "engine": "challenge_cup_graph",
            "completedNodeIds": [],
            "startNodeId": "protocol_design",
            "inheritedFromParent": True,
            "artifacts": {
                "knowledge_package": artifacts.get("knowledge_package") or "",
                "evaluation_report": artifacts.get("evaluation_report") or "",
                # Intentionally omit frozen_protocol so child produces a new lineage
            },
        },
    }


def link_parent_after_fork(
    parent: dict[str, Any],
    *,
    child_run_id: str,
    decision_id: str,
    checkpoint_id: str,
) -> dict[str, Any]:
    """Immutable parent history: succeeded + branched_revision + childRunIds."""
    children = list(parent.get("childRunIds") or [])
    if child_run_id not in children:
        children.append(child_run_id)
    return {
        "status": "succeeded",
        "completionKind": "branched_revision",
        "childRunIds": children,
        "runtimeCurrentNodeIds": [],
        "forkCheckpointId": checkpoint_id,
        "lastForkDecisionId": decision_id,
    }
