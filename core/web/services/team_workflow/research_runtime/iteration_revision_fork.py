"""Deterministic child WorkflowRun for revise_protocol decisions."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from core.research.workflow.definition import build_challenge_cup_workflow_definition

from .budget_lifecycle import build_initial_budget_ledgers
from .checkpoint_lifecycle import fork_checkpoint_at_node
from .human_gate_artifacts import canonical_sha256
from .node_execution_support import build_event, iso, utc_now
from .store import WorkflowRunStore
from .successor_records import build_node_run


def _child_run_id(parent_run_id: str, decision_id: str) -> str:
    identity = f"{parent_run_id}:revise_protocol:{decision_id}".encode()
    return f"run-{hashlib.sha256(identity).hexdigest()[:12]}"


def _remaining_budget_policy(parent: dict[str, Any]) -> dict[str, Any]:
    stage_budgets: dict[str, dict[str, int]] = {}
    for ledger in parent.get("budgetLedgers") or []:
        limits = dict(ledger.get("limits") or {})
        consumed = dict(ledger.get("consumed") or {})
        reserved = dict(ledger.get("reserved") or {})
        stage_budgets[str(ledger.get("stageId") or "")] = {
            key: max(
                0,
                int(limits.get(key) or 0)
                - int(consumed.get(key) or 0)
                - int(reserved.get(key) or 0),
            )
            for key in limits
        }
    original = dict((parent.get("inputSnapshot") or {}).get("budgetPolicy") or {})
    return {
        **original,
        "stageBudgets": stage_budgets,
    }


def fork_iteration_revision(
    store: WorkflowRunStore,
    checkpoint_path: str,
    *,
    parent: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    parent_run_id = str(parent["runId"])
    decision_id = str(decision.get("decisionId") or "").strip()
    if not decision_id:
        raise ValueError("revise_protocol decisionId is required")
    child_run_id = _child_run_id(parent_run_id, decision_id)
    existing = store.get_run(child_run_id)
    if existing is not None:
        if (
            existing.get("parentRunId") == parent_run_id
            and existing.get("forkDecisionId") == decision_id
        ):
            child = existing
        else:
            raise ValueError("deterministic iteration child identity collision")
    else:
        source_checkpoint_id = str(
            (parent.get("langGraph") or {}).get("checkpointId") or ""
        )
        child_thread_id = f"thread-{child_run_id}"
        child_checkpoint_id = fork_checkpoint_at_node(
            checkpoint_path,
            source_thread_id=str(parent["threadId"]),
            source_checkpoint_id=source_checkpoint_id,
            child_thread_id=child_thread_id,
            predecessor_node_id="hypothesis_design",
            resume_node_id="protocol_design",
            state_patch={
                "current_node_id": "hypothesis_design",
                "iteration_decision": {},
            },
        )
        definition = build_challenge_cup_workflow_definition()
        protocol_spec = next(
            item for item in definition.nodes if item.nodeId == "protocol_design"
        )
        binding = next(
            (
                item
                for item in parent.get("bindingSnapshots") or []
                if item.get("nodeId") == "protocol_design"
            ),
            {},
        )
        inherited_refs = [
            str(item.get("artifactId") or "")
            for item in parent.get("artifactManifests") or []
            if str(item.get("artifactId") or "")
        ]
        input_hash = canonical_sha256(
            {
                "parentRunId": parent_run_id,
                "decisionId": decision_id,
                "checkpointId": source_checkpoint_id,
                "inheritedArtifactRefs": inherited_refs,
            }
        )
        protocol_run = build_node_run(
            run_id=child_run_id,
            node_id="protocol_design",
            actor_type=protocol_spec.actorKind.value,
            agent_id=str(binding.get("agentId") or ""),
            input_hash=input_hash,
            checkpoint_id=child_checkpoint_id,
        )
        completed_before_protocol = [
            "source_finding",
            "source_extraction",
            "evidence_relations",
            "knowledge_ingestion",
            "knowledge_handoff",
            "hypothesis_design",
        ]
        created_at = iso(utc_now())
        budget_policy = _remaining_budget_policy(parent)
        child = store.create_run(
            {
                "runId": child_run_id,
                "workflowId": parent["workflowId"],
                "workflowVersionId": parent["workflowVersionId"],
                "structureHash": parent["structureHash"],
                "teamId": parent["teamId"],
                "projectId": parent["projectId"],
                "questionId": parent.get("questionId") or "",
                "threadId": child_thread_id,
                "status": "queued",
                "inputSnapshot": dict(parent.get("inputSnapshot") or {}),
                "bindingSnapshots": list(parent.get("bindingSnapshots") or []),
                "runtimeCurrentNodeIds": ["protocol_design"],
                "completedNodeIds": completed_before_protocol,
                "nodeRuns": [protocol_run],
                "artifactManifests": [],
                "artifactPayloads": {},
                "inheritedArtifactRefs": inherited_refs,
                "events": [
                    {
                        "eventId": f"evt-{uuid.uuid4().hex[:10]}",
                        "sequence": 1,
                        "occurredAt": created_at,
                        "workflowId": parent["workflowId"],
                        "workflowVersionId": parent["workflowVersionId"],
                        "runId": child_run_id,
                        "threadId": child_thread_id,
                        "checkpointId": child_checkpoint_id,
                        "nodeId": "protocol_design",
                        "nodeRunId": protocol_run["nodeRunId"],
                        "attempt": 1,
                        "type": "RunForked",
                        "summary": {
                            "parentRunId": parent_run_id,
                            "decisionId": decision_id,
                            "decisionKind": "revise_protocol",
                        },
                    }
                ],
                "humanTasks": [],
                "handoffs": [],
                "sessionBindings": {},
                "iterationDecisions": [],
                "taskLeases": [],
                "commandReceipts": [],
                "outbox": [],
                "taskBundles": [],
                "budgetLedgers": build_initial_budget_ledgers(
                    run_id=child_run_id,
                    budget_policy=budget_policy,
                    created_at=created_at,
                ),
                "budgetReservations": [],
                "iterationBudgetMax": min(
                    int(parent.get("iterationBudgetMax") or 1),
                    max(
                        1,
                        int(
                            (
                                budget_policy.get("stageBudgets", {}).get(
                                    "execution_iteration", {}
                                )
                            ).get("experiments")
                            or 1
                        ),
                    ),
                ),
                "officialCandidateRef": str(
                    parent.get("officialCandidateRef") or ""
                ),
                "officialVersion": dict(parent.get("officialVersion") or {}),
                "baselineCandidateRef": str(
                    parent.get("baselineCandidateRef") or ""
                ),
                "childRunIds": [],
                "parentRunId": parent_run_id,
                "supersedesRunId": parent_run_id,
                "forkedFromRunId": parent_run_id,
                "forkedFromNodeId": "iteration_decision",
                "forkedFromCheckpointId": source_checkpoint_id,
                "forkDecisionId": decision_id,
                "completionKind": "",
                "terminalReason": "",
                "createdAt": created_at,
                "langGraph": {
                    "engine": "challenge_cup_graph",
                    "checkpointId": child_checkpoint_id,
                    "completedNodeIds": completed_before_protocol,
                    "startNodeId": "protocol_design",
                    "inheritedFromParent": True,
                    "sourceCheckpointId": source_checkpoint_id,
                },
            }
        )

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        children = list(current.get("childRunIds") or [])
        if child_run_id in children and current.get("supersededByRunId") == child_run_id:
            return current
        children.append(child_run_id)
        event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId") or "",
            nodeId="iteration_decision",
            nodeRunId=str(decision.get("nodeRunId") or ""),
            attempt=int(decision.get("iterationAttempt") or 1),
            type="RunSuperseded",
            summary={
                "decisionId": decision_id,
                "childRunId": child_run_id,
                "reason": "revise_protocol",
            },
        )
        return {
            **current,
            "status": "superseded",
            "runtimeCurrentNodeIds": [],
            "childRunIds": children,
            "supersededByRunId": child_run_id,
            "completionKind": "branched_revision",
            "terminalReason": "revise_protocol",
            "events": [*(current.get("events") or []), event],
        }

    store.mutate_run(parent_run_id, mutation)
    return child
