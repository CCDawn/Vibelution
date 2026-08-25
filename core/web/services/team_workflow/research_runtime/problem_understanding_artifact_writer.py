"""Canonical writer for the Challenge Cup problem-understanding artifact.

The problem-understanding artifact is deliberately small and schema-shaped.  It
is the only accepted input contract for ``source_finding``; task summaries and
search result projections are not allowed to backfill it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from core.research.workflow.contracts import WorkflowRunInputSnapshot

from .artifact_readback_registry import build_canonical_ref
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import put_workflow_artifact

PROBLEM_UNDERSTANDING_KIND = "problem_understanding"
HUMAN_GATE_DECISIONS = frozenset(
    {"pending", "approved", "revision_requested", "rejected"}
)
_REQUIRED_FIELDS = frozenset(
    {"scope", "subquestions", "assumptions", "known_unknowns", "human_gate"}
)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"problemUnderstanding.{field} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"problemUnderstanding.{field} must be an array")
    result: list[str] = []
    for item in value:
        text = _text(item, f"{field}[]")
        if text in result:
            raise ValueError(f"problemUnderstanding.{field} must contain unique values")
        result.append(text)
    return result


def validate_problem_understanding(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and detach the exact v2 ``problemUnderstanding`` shape."""

    if not isinstance(value, Mapping):
        raise ValueError("problemUnderstanding must be an object")
    supplied = set(value)
    missing = _REQUIRED_FIELDS - supplied
    extra = supplied - _REQUIRED_FIELDS
    if missing:
        raise ValueError(f"problemUnderstanding missing fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"problemUnderstanding has unsupported fields: {sorted(extra)}")
    gate = value.get("human_gate")
    if not isinstance(gate, Mapping):
        raise ValueError("problemUnderstanding.human_gate must be an object")
    gate_keys = set(gate)
    allowed_gate_keys = {"required", "decision", "reviewer", "decided_at", "rationale"}
    if gate_keys - allowed_gate_keys:
        raise ValueError("problemUnderstanding.human_gate has unsupported fields")
    if gate.get("required") is not True:
        raise ValueError("problemUnderstanding.human_gate.required must be true")
    decision = gate.get("decision")
    if decision not in HUMAN_GATE_DECISIONS:
        raise ValueError("problemUnderstanding.human_gate.decision is invalid")
    normalized_gate: dict[str, Any] = {
        "required": True,
        "decision": decision,
        "rationale": _text(gate.get("rationale"), "human_gate.rationale"),
    }
    for field in ("reviewer", "decided_at"):
        if field in gate:
            normalized_gate[field] = _text(gate.get(field), f"human_gate.{field}")
    return {
        "scope": _text(value.get("scope"), "scope"),
        "subquestions": _string_list(value.get("subquestions"), "subquestions"),
        "assumptions": _string_list(value.get("assumptions"), "assumptions"),
        "known_unknowns": _string_list(value.get("known_unknowns"), "known_unknowns"),
        "human_gate": normalized_gate,
    }


def _task_text(task: Mapping[str, Any], field: str, *, limit: int = 240) -> str:
    value = task.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Formal problem-understanding task requires {field}.")
    return value.strip()[:limit]


def _task_attempt(task: Mapping[str, Any], contract: Mapping[str, Any]) -> int:
    value = task.get("attempt")
    if value in (None, "", 0):
        value = contract.get("nodeAttempt")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Formal problem-understanding task attempt is invalid.")
    return value


def _require_source_collection_binding(
    *,
    team_id: str,
    source_collection_run_id: str,
    workflow_run_id: str,
    research_project_id: str,
) -> dict[str, Any]:
    """Verify the source run that will own the canonical artifact envelope."""

    from core.web.services import data_processing_service

    try:
        source_run = data_processing_service.get_processing_run(
            source_collection_run_id
        )
    except data_processing_service.DataProcessingError as exc:
        raise ValueError(
            "Formal problem-understanding source collection run is unavailable."
        ) from exc
    scope = source_run.get("scope") if isinstance(source_run.get("scope"), dict) else {}
    expected_scope = {
        "teamId": team_id,
        "workflowRunId": workflow_run_id,
        "researchProjectId": research_project_id,
    }
    if (
        str(source_run.get("runId") or "").strip() != source_collection_run_id
        or any(
            str(scope.get(field) or "").strip() != expected
            for field, expected in expected_scope.items()
        )
    ):
        raise ValueError(
            "Formal problem-understanding source collection scope does not match."
        )
    return dict(source_run)


def _formal_task_context(task_context: Mapping[str, Any]) -> dict[str, Any]:
    task = task_context.get("task")
    if not isinstance(task, Mapping):
        raise ValueError("Formal problem-understanding writeback requires a bound task.")
    task = dict(task)
    if task.get("taskKind") != "problem_understanding":
        raise ValueError("Problem-understanding writeback requires a problem_understanding task.")
    if task.get("workflowNodeId") != "problem_understanding":
        raise ValueError("Problem-understanding writeback requires the problem_understanding node.")
    contract = task.get("challengeTaskContract")
    if not isinstance(contract, Mapping):
        contract = {}
    contract = dict(contract)
    # Internal contract values are server-owned.  A public task projection may
    # omit them, but it may never replace them with payload values.
    for field, contract_field in (
        ("questionId", "questionId"),
        ("workflowRunId", "workflowRunId"),
        ("nodeRunId", "nodeRunId"),
        ("sourceCollectionRunId", "sourceCollectionRunId"),
        ("workflowVersionId", "workflowVersionId"),
        ("inputSnapshotHash", "inputSnapshotHash"),
    ):
        expected = str(contract.get(contract_field) or "").strip()
        supplied = str(task.get(field) or "").strip()
        if expected and supplied and expected != supplied:
            raise ValueError(f"Formal problem-understanding task {field} binding conflicts with its server contract.")
        if expected and not supplied:
            task[field] = expected
    return {"task": task, "contract": contract}


def _authoritative_problem_understanding_binding(
    team_id: str,
    task_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconcile task identity with the immutable workflow Ledger records."""

    context = _formal_task_context(task_context)
    task = context["task"]
    contract = context["contract"]
    normalized_team = str(team_id or "").strip()
    task_team = str(task.get("teamId") or task_context.get("teamId") or "").strip()
    if not normalized_team or task_team != normalized_team:
        raise ValueError("Formal problem-understanding task team binding does not match.")
    project_id = _task_text(task, "researchProjectId")
    workflow_run_id = _task_text(task, "workflowRunId")
    source_run_id = _task_text(task, "sourceCollectionRunId")
    contract_source_run_id = str(contract.get("sourceCollectionRunId") or "").strip()
    if contract_source_run_id and contract_source_run_id != source_run_id:
        raise ValueError(
            "Formal problem-understanding task source collection binding does not match."
        )
    node_run_id = _task_text(task, "nodeRunId")
    question_id = _task_text(task, "questionId", limit=200)
    task_id = _task_text(task, "taskId")
    session_id = _task_text(task, "sessionId")
    turn = task.get("turn") if isinstance(task.get("turn"), Mapping) else {}
    turn_id = str(turn.get("turnId") or "").strip()
    if not turn_id:
        raise ValueError("Formal problem-understanding task requires turn binding.")
    agent_id = _task_text(task, "agentId")
    if task.get("teamRole") and str(task.get("teamRole")).strip() != "source_finder":
        raise ValueError("Problem-understanding task has an unexpected team role.")
    if task.get("roleKey") and str(task.get("roleKey")).strip() != "challenge_cup_search":
        raise ValueError("Problem-understanding task has an unexpected Agent role.")
    attempt_number = _task_attempt(task, contract)

    _require_source_collection_binding(
        team_id=normalized_team,
        source_collection_run_id=source_run_id,
        workflow_run_id=workflow_run_id,
        research_project_id=project_id,
    )

    from .runtime_factory import production_workflow_runtime

    runtime = production_workflow_runtime()
    if runtime is None:
        raise ValueError("Formal workflow Ledger runtime is unavailable.")
    run, attempt = runtime.store.read(
        lambda repo: (repo.get_run(workflow_run_id), repo.get_attempt(node_run_id))
    )
    if run is None:
        raise ValueError("Formal workflow run is missing from the Ledger.")
    if attempt is None:
        raise ValueError("Formal problem-understanding node attempt is missing from the Ledger.")
    if (
        str(getattr(run, "run_id", "") or "").strip() != workflow_run_id
        or str(getattr(run, "team_id", "") or "").strip() != normalized_team
        or str(getattr(run, "project_id", "") or "").strip() != project_id
        or str(getattr(run, "question_id", "") or "").strip().upper()
        != question_id.upper()
    ):
        raise ValueError("Formal problem-understanding task does not reconcile with its run.")
    if (
        str(getattr(attempt, "node_run_id", "") or "").strip() != node_run_id
        or str(getattr(attempt, "run_id", "") or "").strip() != workflow_run_id
        or str(getattr(attempt, "node_id", "") or "").strip() != "problem_understanding"
        or getattr(attempt, "attempt", 0) != attempt_number
    ):
        raise ValueError("Formal problem-understanding task does not reconcile with its attempt.")

    run_hash = str(getattr(run, "input_snapshot_hash", "") or "").strip()
    attempt_hash = str(getattr(attempt, "input_snapshot_hash", "") or "").strip()
    if not run_hash or not attempt_hash or run_hash != attempt_hash:
        raise ValueError("Formal workflow input snapshot hashes do not match.")
    contract_hash = str(contract.get("inputSnapshotHash") or task.get("inputSnapshotHash") or "").strip()
    if contract_hash and contract_hash != run_hash:
        raise ValueError("Formal problem-understanding task input snapshot binding does not match.")

    raw_snapshot = str(getattr(run, "input_snapshot_json", "") or "")
    if not raw_snapshot:
        raise ValueError("Formal workflow input snapshot is missing.")
    try:
        decoded = json.loads(raw_snapshot)
        snapshot = WorkflowRunInputSnapshot.from_dict(decoded)
    except (TypeError, ValueError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError("Formal workflow input snapshot is invalid.") from exc
    if str(decoded.get("sourceCollectionRunId") or "").strip() != source_run_id:
        raise ValueError(
            "Formal problem-understanding source collection binding is not frozen."
        )
    if snapshot.snapshotHash != run_hash:
        raise ValueError("Formal workflow input snapshot hash is invalid.")
    if (
        snapshot.teamId != normalized_team
        or snapshot.projectId != project_id
        or snapshot.questionId.upper() != question_id.upper()
        or not snapshot.researchScopeEnvelope
        or not snapshot.catalogScope
    ):
        raise ValueError("Formal problem-understanding task frozen scope is incomplete or mismatched.")

    return {
        "task": task,
        "contract": contract,
        "run": run,
        "attempt": attempt,
        "snapshot": snapshot,
        "teamId": normalized_team,
        "researchProjectId": project_id,
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_run_id,
        "questionId": question_id,
        "workflowNodeId": "problem_understanding",
        "nodeRunId": node_run_id,
        "attemptNumber": attempt_number,
        "taskId": task_id,
        "sessionId": session_id,
        "turnId": turn_id,
        "agentId": agent_id,
    }


def build_problem_understanding_task_context(
    team_id: str,
    task: Mapping[str, Any],
) -> dict[str, Any]:
    """Expose only frozen scope needed by the problem-understanding Agent."""

    try:
        binding = _authoritative_problem_understanding_binding(
            team_id,
            {"teamId": str(team_id or "").strip(), "task": dict(task)},
        )
    except ValueError as exc:
        return {
            "status": "blocked_formal_authority",
            "teamId": str(team_id or "").strip(),
            "authority": "workflow_run_input_snapshot",
            "authorityError": str(exc),
            "rawLogsIncluded": False,
        }
    snapshot = binding["snapshot"]
    return {
        "status": "ready",
        "authority": "workflow_run_input_snapshot",
        "teamId": binding["teamId"],
        "researchProjectId": binding["researchProjectId"],
        "questionId": binding["questionId"],
        "workflowRunId": binding["workflowRunId"],
        "sourceCollectionRunId": binding["sourceCollectionRunId"],
        "workflowNodeId": binding["workflowNodeId"],
        "nodeRunId": binding["nodeRunId"],
        "attempt": binding["attemptNumber"],
        "inputSnapshotHash": snapshot.snapshotHash,
        "researchScopeEnvelope": dict(snapshot.researchScopeEnvelope),
        "catalogScope": dict(snapshot.catalogScope),
        "rawLogsIncluded": False,
    }


def write_problem_understanding_artifact(
    *,
    team_id: str,
    workflow_run_id: str = "",
    problem_understanding: Mapping[str, Any],
    source_collection_run_id: str = "",
    node_run_id: str = "",
    task_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and append one immutable canonical artifact, idempotently."""

    payload = validate_problem_understanding(problem_understanding)
    if task_context is not None:
        binding = _authoritative_problem_understanding_binding(team_id, task_context)
        run_id = binding["workflowRunId"]
        source_id = binding["sourceCollectionRunId"]
        identity = binding["nodeRunId"]
    else:
        # Kept for the low-level artifact-store compatibility test.  The
        # Challenge Cup writeback tool always supplies task_context and hence
        # always takes the fail-closed authority path above.
        run_id = str(workflow_run_id or "").strip()
        source_id = str(source_collection_run_id or "").strip() or run_id
        identity = str(node_run_id or "").strip()
        if not run_id or not source_id or not identity:
            raise ValueError(
                "Unbound problem-understanding writes require workflow, source and node identities."
            )
    record = put_workflow_artifact(
        team_id,
        kind=PROBLEM_UNDERSTANDING_KIND,
        workflow_run_id=run_id,
        source_collection_run_id=source_id,
        artifact_identity=identity,
        payload=payload,
    )
    envelope = {
        "teamId": str(team_id or "").strip(),
        "kind": PROBLEM_UNDERSTANDING_KIND,
        "workflowRunId": str(record.get("workflowRunId") or run_id),
        "sourceCollectionRunId": str(record.get("sourceCollectionRunId") or run_id),
        "payload": payload,
    }
    content_hash = canonical_sha256(envelope)
    return {
        "artifact": record,
        "canonicalRef": build_canonical_ref(
            kind=PROBLEM_UNDERSTANDING_KIND,
            team_id=str(team_id or "").strip(),
            authority_run_id=str(record.get("sourceCollectionRunId") or run_id),
            content_hash=content_hash,
        ),
        "contentHash": content_hash,
        "payload": payload,
        "scopeBinding": {
            "workflowRunId": run_id,
            "sourceCollectionRunId": source_id,
            "nodeRunId": identity,
            "source": "bound_problem_understanding_task"
            if task_context is not None
            else "low_level_artifact_store",
        },
    }


__all__ = [
    "HUMAN_GATE_DECISIONS",
    "PROBLEM_UNDERSTANDING_KIND",
    "build_problem_understanding_task_context",
    "validate_problem_understanding",
    "write_problem_understanding_artifact",
]
