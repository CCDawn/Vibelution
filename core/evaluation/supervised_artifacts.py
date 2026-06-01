# -*- coding: utf-8 -*-
"""Shared supervised artifact readers.

These helpers keep dashboard, workbench, and Web surfaces on the same
decision/proposal artifact interpretation without changing ownership of the
underlying records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SupervisedPolicyProposalArtifact:
    path: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class SupervisedJsonArtifact:
    path: str | None
    payload: dict[str, Any] | None
    status: str
    error: str = ""


@dataclass(frozen=True)
class SupervisedDecisionRecordArtifacts:
    policy_action: dict[str, Any]
    gates: list[dict[str, Any]]
    case_summaries: list[dict[str, Any]]
    decision_path: str
    lineage_index_path: Any
    gym_proposal_path: Any
    gym_decision_path: Any


def resolve_project_artifact_path(raw_path: Any, *, project_root: Path) -> Path | None:
    text = str(raw_path or "").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (project_root / path).resolve()
    try:
        resolved.relative_to(project_root.resolve())
    except ValueError:
        return None
    return resolved


def load_project_json_artifact(
    raw_path: Any,
    *,
    project_root: Path,
    label: str = "artifact",
) -> SupervisedJsonArtifact:
    text = str(raw_path or "").strip()
    if not text:
        return SupervisedJsonArtifact(
            path=None,
            payload=None,
            status="missing",
            error=f"Missing {label} path.",
        )
    resolved = resolve_project_artifact_path(text, project_root=project_root)
    if resolved is None:
        return SupervisedJsonArtifact(
            path=None,
            payload=None,
            status="unsafe",
            error=f"Unsafe {label} path outside project root: {text}",
        )
    if not resolved.exists():
        return SupervisedJsonArtifact(
            path=str(resolved),
            payload=None,
            status="missing",
            error=f"Missing {label}: {resolved}",
        )
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return SupervisedJsonArtifact(
            path=str(resolved),
            payload=None,
            status="invalid",
            error=f"Invalid {label}: {resolved}",
        )
    if not isinstance(payload, dict):
        return SupervisedJsonArtifact(
            path=str(resolved),
            payload=None,
            status="invalid",
            error=f"Invalid {label}: expected object at {resolved}",
        )
    return SupervisedJsonArtifact(path=str(resolved), payload=payload, status="loaded")


def load_project_json_object(raw_path: Any, *, project_root: Path) -> dict[str, Any] | None:
    artifact = load_project_json_artifact(raw_path, project_root=project_root)
    return artifact.payload if artifact.status == "loaded" else None


def load_required_project_json_object(raw_path: Any, *, project_root: Path, label: str) -> dict[str, Any]:
    artifact = load_project_json_artifact(raw_path, project_root=project_root, label=label)
    if artifact.status == "loaded" and artifact.payload is not None:
        return artifact.payload
    raise ValueError(artifact.error or f"Invalid {label}.")


def load_policy_proposal_artifacts(
    decision_payload: dict[str, Any],
    *,
    project_root: Path,
) -> list[SupervisedPolicyProposalArtifact]:
    policy_action = (
        decision_payload.get("policy_action")
        if isinstance(decision_payload.get("policy_action"), dict)
        else {}
    )
    raw_paths = policy_action.get("proposal_paths") if isinstance(policy_action.get("proposal_paths"), list) else []
    artifacts: list[SupervisedPolicyProposalArtifact] = []
    for raw_path in raw_paths:
        loaded = load_project_json_artifact(raw_path, project_root=project_root, label="policy proposal")
        if loaded.status == "loaded" and loaded.path and loaded.payload is not None:
            artifacts.append(SupervisedPolicyProposalArtifact(path=loaded.path, payload=loaded.payload))
    return artifacts


def policy_target_key(payload: dict[str, Any]) -> str | None:
    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    if not target:
        return None
    try:
        return "target:" + json.dumps(target, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(target)


def load_policy_proposal_artifact(
    decision_payload: dict[str, Any],
    *,
    project_root: Path,
) -> SupervisedPolicyProposalArtifact | None:
    artifacts = load_policy_proposal_artifacts(decision_payload, project_root=project_root)
    return artifacts[0] if artifacts else None


def build_decision_record_artifacts(
    decision_payload: dict[str, Any],
    *,
    fallback_decision_path: Any = "",
) -> SupervisedDecisionRecordArtifacts:
    policy_action = (
        decision_payload.get("policy_action")
        if isinstance(decision_payload.get("policy_action"), dict)
        else {}
    )
    gates = [gate for gate in _list_of_dicts(decision_payload.get("gates"))]
    case_summaries = [case for case in _list_of_dicts(decision_payload.get("case_summaries"))]
    gym_proposal_path = None
    gym_decision_path = None
    for gate in gates:
        metrics = gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {}
        gym_proposal_path = gym_proposal_path or metrics.get("promotion_proposal_path")
        gym_decision_path = gym_decision_path or metrics.get("decision_path")
    return SupervisedDecisionRecordArtifacts(
        policy_action=policy_action,
        gates=gates,
        case_summaries=case_summaries,
        decision_path=str(decision_payload.get("decision_path") or fallback_decision_path),
        lineage_index_path=policy_action.get("lineage_index_path"),
        gym_proposal_path=gym_proposal_path,
        gym_decision_path=gym_decision_path,
    )


def build_case_diagnostic(case: dict[str, Any]) -> dict[str, Any] | None:
    metrics = case.get("difference_metrics") if isinstance(case.get("difference_metrics"), dict) else {}
    reasons = case.get("difference_reasons") if isinstance(case.get("difference_reasons"), list) else []
    score_breakdown = case.get("score_breakdown") if isinstance(case.get("score_breakdown"), dict) else {}
    failure_taxonomy = case.get("failure_taxonomy") if isinstance(case.get("failure_taxonomy"), list) else []
    evidence_paths = case.get("evidence_paths") if isinstance(case.get("evidence_paths"), dict) else {}
    intake_provenance = case.get("intake_provenance") if isinstance(case.get("intake_provenance"), dict) else {}
    evaluation_metadata = case.get("evaluation_metadata") if isinstance(case.get("evaluation_metadata"), dict) else {}
    if not evaluation_metadata:
        evaluation_metadata = _case_evaluation_metadata(intake_provenance)
    case_type = str(case.get("case_type") or intake_provenance.get("case_type") or "static").strip()
    expected_final_state = _case_dict_field(case, intake_provenance, "expected_final_state")
    expected_infeasible_outcome = _case_dict_field(case, intake_provenance, "expected_infeasible_outcome")
    dynamic_events = case.get("dynamic_events") or intake_provenance.get("dynamic_events")
    summary = str(case.get("difference_summary") or "")
    if (
        not summary
        and not metrics
        and not reasons
        and not score_breakdown
        and not failure_taxonomy
        and not evidence_paths
        and case_type == "static"
        and not expected_final_state
        and not expected_infeasible_outcome
        and not dynamic_events
    ):
        return None
    diagnostic = {
        "caseId": str(case.get("case_id") or ""),
        "caseType": case_type or "static",
        "baselineStatus": str(case.get("baseline_status") or ""),
        "candidateStatus": str(case.get("candidate_status") or ""),
        "decisionSignal": str(case.get("decision_signal") or ""),
        "summary": summary,
        "metrics": metrics,
        "reasons": [str(item) for item in reasons],
    }
    if expected_final_state:
        diagnostic["expectedFinalState"] = expected_final_state
    if expected_infeasible_outcome:
        diagnostic["expectedInfeasibleOutcome"] = expected_infeasible_outcome
    if isinstance(dynamic_events, list) and dynamic_events:
        diagnostic["dynamicEvents"] = dynamic_events
    if score_breakdown:
        diagnostic["scoreBreakdown"] = score_breakdown
    if failure_taxonomy:
        diagnostic["failureTaxonomy"] = [str(item) for item in failure_taxonomy]
    if evidence_paths:
        diagnostic["evidencePaths"] = evidence_paths
    if evaluation_metadata:
        diagnostic["evaluationMetadata"] = evaluation_metadata
    return diagnostic


def build_case_diagnostics(case_summaries: Any) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for case in list(case_summaries or []):
        if not isinstance(case, dict):
            continue
        diagnostic = build_case_diagnostic(case)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
    return diagnostics


def _case_dict_field(case: dict[str, Any], intake_provenance: dict[str, Any], key: str) -> dict[str, Any]:
    value = case.get(key)
    if not isinstance(value, dict):
        value = intake_provenance.get(key)
    return value if isinstance(value, dict) else {}


def _case_evaluation_metadata(intake_provenance: dict[str, Any]) -> dict[str, Any]:
    evaluation_mode = str(intake_provenance.get("evaluation_mode") or "").strip()
    official_status = str(intake_provenance.get("official_verifier_status") or "").strip()
    score_label = str(intake_provenance.get("score_label") or "").strip()
    metadata: dict[str, Any] = {}
    if evaluation_mode:
        metadata["evaluationMode"] = evaluation_mode
    if score_label:
        metadata["scoreLabel"] = score_label
    if official_status:
        metadata["officialVerifierStatus"] = official_status
    if evaluation_mode == "custom_harness" or official_status == "harbor_pending":
        metadata["officialScore"] = None
        metadata["officialScoreAvailable"] = False
    return metadata


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


__all__ = [
    "SupervisedDecisionRecordArtifacts",
    "SupervisedJsonArtifact",
    "SupervisedPolicyProposalArtifact",
    "build_decision_record_artifacts",
    "build_case_diagnostic",
    "build_case_diagnostics",
    "load_project_json_artifact",
    "load_project_json_object",
    "load_required_project_json_object",
    "load_policy_proposal_artifacts",
    "load_policy_proposal_artifact",
    "policy_target_key",
    "resolve_project_artifact_path",
]
