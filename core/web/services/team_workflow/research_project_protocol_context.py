"""Build bounded formal inputs for protocol-design tasks."""

from __future__ import annotations

import json
from typing import Any

from core.research.workflow.contracts import WorkflowRunInputSnapshot

from .research_runtime.artifact_readback_registry import (
    build_canonical_ref,
    load_scoped_artifact_payload,
)
from .research_runtime.human_gate_artifacts import canonical_sha256

_RESEARCH_PLAN_REQUIRED_FIELDS = (
    "objective",
    "method",
    "work_packages",
    "variables",
    "controls",
    "data_and_materials",
    "analysis",
    "success_criteria",
    "failure_criteria",
    "stop_conditions",
    "resources",
    "timeline",
    "risks",
    "human_gate",
)


def _text(value: Any, *, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def _authoritative_protocol_binding(
    team_id: str,
    task: dict[str, Any],
) -> tuple[Any, Any, WorkflowRunInputSnapshot]:
    """Read the run and attempt from one Ledger snapshot and reconcile them."""

    workflow_run_id = _text(task.get("workflowRunId"), limit=200)
    node_run_id = _text(task.get("nodeRunId"), limit=200)
    task_team_id = _text(task.get("teamId"), limit=160)
    project_id = _text(task.get("researchProjectId"), limit=200)
    question_id = _text(task.get("questionId"), limit=200)
    if not workflow_run_id or not node_run_id or not task_team_id:
        raise ValueError("Formal protocol task is missing Ledger binding.")
    if not project_id or not question_id:
        raise ValueError("Formal protocol task is missing project/question binding.")
    try:
        task_attempt = task.get("attempt")
        if isinstance(task_attempt, bool) or not isinstance(task_attempt, int):
            raise ValueError("Formal protocol task attempt is invalid.")
        if task_attempt <= 0:
            raise ValueError("Formal protocol task attempt is invalid.")
    except (TypeError, ValueError) as exc:
        raise ValueError("Formal protocol task attempt is invalid.") from exc

    from .research_runtime.runtime_factory import production_workflow_runtime

    runtime = production_workflow_runtime()
    if runtime is None:
        raise ValueError("Formal workflow Ledger runtime is unavailable.")
    run, attempt = runtime.store.read(
        lambda repo: (repo.get_run(workflow_run_id), repo.get_attempt(node_run_id))
    )
    if run is None:
        raise ValueError("Formal workflow run is missing from the Ledger.")
    if attempt is None:
        raise ValueError("Formal protocol node attempt is missing from the Ledger.")
    if (
        _text(run.run_id, limit=200) != workflow_run_id
        or _text(run.team_id, limit=160) != _text(team_id, limit=160)
        or task_team_id != _text(team_id, limit=160)
        or _text(run.project_id, limit=200) != project_id
        or _text(run.question_id, limit=200) != question_id
    ):
        raise ValueError("Formal protocol task does not reconcile with its run.")
    if (
        _text(attempt.node_run_id, limit=200) != node_run_id
        or _text(attempt.run_id, limit=200) != workflow_run_id
        or _text(attempt.node_id, limit=100) != "protocol_design"
        or attempt.attempt != task_attempt
    ):
        raise ValueError("Formal protocol task does not reconcile with its attempt.")
    run_hash = _text(run.input_snapshot_hash, limit=200)
    attempt_hash = _text(attempt.input_snapshot_hash, limit=200)
    if not run_hash or not attempt_hash or run_hash != attempt_hash:
        raise ValueError("Formal workflow input snapshot hashes do not match.")
    try:
        raw = json.loads(str(run.input_snapshot_json))
        if not isinstance(raw, dict):
            raise ValueError("Formal workflow input snapshot is not an object.")
        snapshot = WorkflowRunInputSnapshot.from_dict(raw)
    except (TypeError, ValueError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError("Formal workflow input snapshot is invalid.") from exc
    if snapshot.snapshotHash != run_hash or snapshot.snapshotHash != attempt_hash:
        raise ValueError("Formal workflow input snapshot hash is invalid.")
    run_workflow_version_id = _text(
        getattr(run, "workflow_version_id", ""), limit=200
    )
    if (
        snapshot.teamId != _text(team_id, limit=160)
        or snapshot.teamId != task_team_id
        or snapshot.projectId != project_id
        or snapshot.questionId != question_id
        or (
            run_workflow_version_id
            and snapshot.workflowVersionId != run_workflow_version_id
        )
    ):
        raise ValueError("Formal protocol task does not reconcile with its snapshot.")
    if not snapshot.researchScopeEnvelope or not snapshot.catalogScope:
        raise ValueError("Formal workflow input snapshot scope is incomplete.")
    return run, attempt, snapshot


def build_protocol_input_context(
    team_id: str,
    task: dict[str, Any],
) -> dict[str, Any]:
    """Read the exact workflow-scoped ``hypothesis_set`` for one task."""
    workflow_run_id = _text(task.get("workflowRunId"), limit=200)
    source_run_id = _text(task.get("sourceCollectionRunId"), limit=200)
    if not workflow_run_id or not source_run_id:
        return {
            "status": "missing_workflow_scope",
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": source_run_id,
            "hypothesisCount": 0,
            "candidates": [],
        }
    try:
        _run, _attempt, snapshot = _authoritative_protocol_binding(team_id, task)
    except ValueError as exc:
        return {
            "status": "blocked_formal_authority",
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": source_run_id,
            "hypothesisCount": 0,
            "candidates": [],
            "authorityError": str(exc),
        }
    envelope = load_scoped_artifact_payload(
        "hypothesis_set",
        team_id=_text(team_id, limit=160),
        authority_run_id=source_run_id,
        workflow_run_id=workflow_run_id,
    )
    if not isinstance(envelope, dict):
        return {
            "status": "missing_hypothesis_set",
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": source_run_id,
            "hypothesisCount": 0,
            "candidates": [],
        }
    payload = (
        envelope.get("payload")
        if isinstance(envelope.get("payload"), dict)
        else {}
    )
    envelope_hash = canonical_sha256(envelope) if payload else ""
    input_snapshot = snapshot.to_dict()
    candidates = []
    for item in list(payload.get("candidates") or [])[:16]:
        if not isinstance(item, dict):
            continue
        candidate_id = _text(item.get("candidateId"), limit=160)
        claim = _text(item.get("claim"))
        if not candidate_id or not claim:
            continue
        scores = item.get("scores") if isinstance(item.get("scores"), dict) else {}
        candidates.append(
            {
                "candidateId": candidate_id,
                "claim": claim,
                "counterEvidenceRefs": [
                    _text(ref, limit=200)
                    for ref in list(item.get("counterEvidenceRefs") or [])[:24]
                    if _text(ref, limit=200)
                ],
                "status": _text(item.get("status"), limit=80),
                "scores": dict(scores),
            }
        )
    return {
        "status": "ready" if candidates else "missing_hypothesis_set",
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_run_id,
        "teamId": _text(team_id, limit=160),
        "questionId": _text(input_snapshot.get("questionId"), limit=160),
        "portfolioId": _text(payload.get("portfolioId"), limit=160),
        "hypothesisCount": len(candidates),
        "candidates": candidates,
        "authority": "workflow_hypothesis_set",
        "hypothesisSetHash": envelope_hash,
        "hypothesisSetRef": (
            build_canonical_ref(
                kind="hypothesis_set",
                team_id=_text(team_id, limit=160),
                authority_run_id=source_run_id,
                content_hash=envelope_hash,
            )
            if payload
            else ""
        ),
        "inputSnapshot": input_snapshot,
        "researchPlanContract": {
            "required": True,
            "fieldName": "payload_json.researchPlan",
            "normalizer": "QuestionResultPackage.v2",
            "requiredFields": list(_RESEARCH_PLAN_REQUIRED_FIELDS),
        },
        "frozenBinding": {
            "teamId": _text(team_id, limit=160),
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": source_run_id,
            "questionId": _text(input_snapshot.get("questionId"), limit=160),
            "inputSnapshotHash": _text(input_snapshot.get("snapshotHash"), limit=200),
            "researchScopeEnvelope": dict(
                input_snapshot.get("researchScopeEnvelope") or {}
            ),
            "catalogScope": dict(input_snapshot.get("catalogScope") or {}),
        },
    }
