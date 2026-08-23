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


def _frozen_input_snapshot(task: dict[str, Any]) -> dict[str, Any]:
    """Read and re-verify the immutable snapshot for this formal run."""

    explicit = task.get("inputSnapshot")
    if isinstance(explicit, dict) and explicit:
        parsed = WorkflowRunInputSnapshot.from_dict(explicit)
        expected_hash = _text(task.get("inputSnapshotHash"), limit=200)
        if expected_hash and parsed.snapshotHash != expected_hash:
            raise ValueError(
                "Formal workflow inputSnapshotHash does not match snapshot."
            )
        return parsed.to_dict()

    run_id = _text(task.get("workflowRunId"), limit=200)
    if not run_id:
        return {}
    try:
        from .research_runtime.runtime_factory import production_workflow_runtime

        runtime = production_workflow_runtime()
        run = runtime.store.get_run(run_id) if runtime is not None else None
        raw = json.loads(str(run.input_snapshot_json)) if run is not None else None
        if not isinstance(raw, dict):
            return {}
        parsed = WorkflowRunInputSnapshot.from_dict(raw)
        stored_hash = _text(getattr(run, "input_snapshot_hash", ""), limit=200)
        if stored_hash and parsed.snapshotHash != stored_hash:
            raise ValueError("Formal workflow input snapshot hash is invalid.")
        return parsed.to_dict()
    except (TypeError, ValueError, json.JSONDecodeError, AttributeError, KeyError):
        return {}


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
    envelope = load_scoped_artifact_payload(
        "hypothesis_set",
        team_id=_text(team_id, limit=160),
        authority_run_id=source_run_id,
        workflow_run_id=workflow_run_id,
    )
    payload = (
        envelope.get("payload")
        if isinstance(envelope, dict) and isinstance(envelope.get("payload"), dict)
        else {}
    )
    input_snapshot = _frozen_input_snapshot(task)
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
        "questionId": _text(input_snapshot.get("questionId"), limit=160),
        "portfolioId": _text(payload.get("portfolioId"), limit=160),
        "hypothesisCount": len(candidates),
        "candidates": candidates,
        "authority": "workflow_hypothesis_set",
        "hypothesisSetHash": canonical_sha256(payload) if payload else "",
        "hypothesisSetRef": (
            build_canonical_ref(
                kind="hypothesis_set",
                team_id=_text(team_id, limit=160),
                authority_run_id=source_run_id,
                content_hash=canonical_sha256(payload),
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
