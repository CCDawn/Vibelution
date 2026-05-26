#!/usr/bin/env python3
"""Shared supervised artifact reader tests."""

import json
from pathlib import Path

from core.evaluation.supervised_artifacts import (
    build_case_diagnostic,
    build_case_diagnostics,
    load_policy_proposal_artifact,
    policy_target_key,
    resolve_project_artifact_path,
)


def test_load_policy_proposal_artifact_reads_first_safe_existing_path(tmp_path: Path):
    proposal_path = tmp_path / "workspace" / "evolution" / "proposals" / "case.json"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(
        json.dumps(
            {
                "proposal_id": "demo:case:hash",
                "target": {"case_id": "case_1", "kind": "bundle_prompt_case"},
                "status": "observing",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    decision_payload = {
        "policy_action": {
            "proposal_paths": [
                "workspace/evolution/proposals/missing.json",
                str(proposal_path),
            ],
        }
    }

    artifact = load_policy_proposal_artifact(decision_payload, project_root=tmp_path)

    assert artifact is not None
    assert artifact.path == str(proposal_path.resolve())
    assert artifact.payload["proposal_id"] == "demo:case:hash"
    assert policy_target_key(artifact.payload) == 'target:{"case_id": "case_1", "kind": "bundle_prompt_case"}'


def test_load_policy_proposal_artifact_rejects_paths_outside_project(tmp_path: Path):
    outside_path = tmp_path.parent / "outside-proposal.json"
    outside_path.write_text(json.dumps({"proposal_id": "outside"}, ensure_ascii=False), encoding="utf-8")
    decision_payload = {"policy_action": {"proposal_paths": [str(outside_path)]}}

    artifact = load_policy_proposal_artifact(decision_payload, project_root=tmp_path)

    assert artifact is None
    assert resolve_project_artifact_path(str(outside_path), project_root=tmp_path) is None


def test_build_case_diagnostic_filters_empty_static_case():
    assert build_case_diagnostic({"case_id": "plain_static"}) is None
    assert build_case_diagnostics([{"case_id": "plain_static"}, "ignored"]) == []


def test_build_case_diagnostics_preserves_dynamic_and_impossible_evidence():
    diagnostics = build_case_diagnostics(
        [
            {
                "case_id": "dynamic_calendar_change",
                "case_type": "dynamic_replanning",
                "baseline_status": "success",
                "candidate_status": "success",
                "decision_signal": "stable_success",
                "difference_summary": "dynamic case stayed stable",
                "difference_metrics": {"wall_clock_seconds_delta": 0.5},
                "difference_reasons": ["same_status"],
                "score_breakdown": {
                    "baseline": {"overall_score": 1.0},
                    "candidate": {"overall_score": 0.95},
                    "delta": {"overall_score": -0.05},
                },
                "failure_taxonomy": ["dynamic_replanning_case", "post_adaptation_verification_missing"],
                "evidence_paths": {"candidate_report_path": "workspace/sessions/dynamic/candidate.json"},
                "intake_provenance": {
                    "case_type": "dynamic_replanning",
                    "expected_final_state": {"calendar_event": "rescheduled"},
                    "dynamic_events": [{"event": "deadline_changed"}],
                },
            },
            {
                "case_id": "impossible_missing_permission",
                "baseline_status": "success",
                "candidate_status": "success",
                "decision_signal": "stable_success",
                "difference_summary": "impossible case stayed stable",
                "failure_taxonomy": ["impossible_task_case"],
                "intake_provenance": {
                    "case_type": "impossible_task",
                    "expected_infeasible_outcome": {"status": "infeasible", "reason": "missing_permission"},
                },
            },
        ]
    )

    by_case = {item["caseId"]: item for item in diagnostics}
    assert by_case["dynamic_calendar_change"] == {
        "caseId": "dynamic_calendar_change",
        "caseType": "dynamic_replanning",
        "baselineStatus": "success",
        "candidateStatus": "success",
        "decisionSignal": "stable_success",
        "summary": "dynamic case stayed stable",
        "metrics": {"wall_clock_seconds_delta": 0.5},
        "reasons": ["same_status"],
        "expectedFinalState": {"calendar_event": "rescheduled"},
        "dynamicEvents": [{"event": "deadline_changed"}],
        "scoreBreakdown": {
            "baseline": {"overall_score": 1.0},
            "candidate": {"overall_score": 0.95},
            "delta": {"overall_score": -0.05},
        },
        "failureTaxonomy": ["dynamic_replanning_case", "post_adaptation_verification_missing"],
        "evidencePaths": {"candidate_report_path": "workspace/sessions/dynamic/candidate.json"},
    }
    assert by_case["impossible_missing_permission"]["caseType"] == "impossible_task"
    assert by_case["impossible_missing_permission"]["expectedInfeasibleOutcome"] == {
        "status": "infeasible",
        "reason": "missing_permission",
    }
