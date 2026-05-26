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
    policy_action = (
        decision_payload.get("policy_action")
        if isinstance(decision_payload.get("policy_action"), dict)
        else {}
    )
    raw_paths = policy_action.get("proposal_paths") if isinstance(policy_action.get("proposal_paths"), list) else []
    for raw_path in raw_paths:
        proposal_path = resolve_project_artifact_path(raw_path, project_root=project_root)
        if proposal_path is None or not proposal_path.exists():
            continue
        try:
            proposal_payload = json.loads(proposal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(proposal_payload, dict):
            return SupervisedPolicyProposalArtifact(
                path=str(proposal_path),
                payload=proposal_payload,
            )
    return None


def build_case_diagnostic(case: dict[str, Any]) -> dict[str, Any] | None:
    metrics = case.get("difference_metrics") if isinstance(case.get("difference_metrics"), dict) else {}
    reasons = case.get("difference_reasons") if isinstance(case.get("difference_reasons"), list) else []
    score_breakdown = case.get("score_breakdown") if isinstance(case.get("score_breakdown"), dict) else {}
    failure_taxonomy = case.get("failure_taxonomy") if isinstance(case.get("failure_taxonomy"), list) else []
    evidence_paths = case.get("evidence_paths") if isinstance(case.get("evidence_paths"), dict) else {}
    intake_provenance = case.get("intake_provenance") if isinstance(case.get("intake_provenance"), dict) else {}
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


__all__ = [
    "SupervisedPolicyProposalArtifact",
    "build_case_diagnostic",
    "build_case_diagnostics",
    "load_policy_proposal_artifact",
    "policy_target_key",
    "resolve_project_artifact_path",
]
