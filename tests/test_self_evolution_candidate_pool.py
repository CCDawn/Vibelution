#!/usr/bin/env python3
"""Self-evolution candidate pool tests."""

import json
from pathlib import Path

import pytest

from core.evaluation.self_evolution_candidate_pool import (
    CANDIDATE_JSONL_BY_TYPE,
    append_candidate_record,
    build_candidate_from_reflection,
    candidate_pool_paths,
    list_candidate_records,
)


def _reflection_record() -> dict:
    return {
        "reflection_id": "refl_verify",
        "source_experience_id": "exp_failed_verify",
        "source_run_id": "web-self-failed",
        "source_turn": 2,
        "txn_id": "txn-verify",
        "dedupe_key": "self_reflection:exp_failed_verify",
        "summary": "pytest failure needs a bounded retry plan",
        "bounded": True,
        "candidate_only": True,
        "auto_apply": False,
        "supervised_required": True,
        "self_questioning": [
            {
                "candidate_type": "question_candidate",
                "question": "What bounded pytest check should run before retry?",
                "bounded": True,
                "evidence_refs": ["logs/runtime_scenes/pkg/agent/self_evolution_runs/web-self-failed.jsonl"],
            }
        ],
        "self_navigating": [
            {
                "candidate_type": "navigation_hint",
                "hint": "Recheck worktree and rerun the smallest pytest slice.",
                "bounded": True,
                "must_recheck_current_state": True,
                "auto_apply": False,
                "evidence_refs": ["logs/runtime_scenes/pkg/agent/self_evolution_runs/web-self-failed.jsonl"],
            }
        ],
        "self_attributing": [
            {
                "candidate_type": "attribution_record",
                "claim": "Run status failed is associated with tool pytest",
                "bounded": True,
                "confidence": 0.6,
                "evidence_refs": ["logs/runtime_scenes/pkg/agent/self_evolution_runs/web-self-failed.jsonl"],
            }
        ],
        "created_at": "2026-05-24T10:00:00Z",
    }


@pytest.mark.parametrize(
    ("candidate_type", "expected_path", "blocked_use"),
    [
        ("skill_candidate", "skill_candidates.jsonl", "skill_registry_install"),
        ("prompt_candidate", "prompt_candidates.jsonl", "runtime_prompt_override"),
        ("proposal_candidate", "proposal_candidates.jsonl", "accepted_baseline"),
    ],
)
def test_build_candidate_from_reflection_keeps_candidate_pending(candidate_type: str, expected_path: str, blocked_use: str):
    candidate = build_candidate_from_reflection(_reflection_record(), candidate_type=candidate_type)

    assert candidate["candidate_id"].startswith(f"{candidate_type}:")
    assert candidate["candidate_type"] == candidate_type
    assert candidate["source_experience_id"] == "exp_failed_verify"
    assert candidate["source_reflection_id"] == "refl_verify"
    assert candidate["source_run_id"] == "web-self-failed"
    assert candidate["txn_id"] == "txn-verify"
    assert candidate["review_state"] == "pending"
    assert candidate["supervised_required"] is True
    assert candidate["candidate_only"] is True
    assert candidate["auto_apply"] is False
    assert candidate["risk_level"] == "pending_review"
    assert candidate["supervised_intake_boundary"]["contract"] == "self_evolution_candidate"
    assert candidate["supervised_intake_boundary"]["risk_level"] == "pending_review"
    assert candidate["supervised_intake_boundary"]["runtime_effect"] == "not_applied"
    assert blocked_use in candidate["blocked_downstream_uses"]
    assert "accepted_baseline" in candidate["blocked_downstream_uses"]
    assert "selection_policy" in candidate["blocked_downstream_uses"]
    assert candidate["target_path"].endswith(expected_path)
    assert candidate["provenance"]["source_reflection_id"] == "refl_verify"
    assert candidate["provenance"]["evidence_refs"]


def test_append_candidate_record_routes_by_type_and_dedupes(tmp_path: Path):
    candidate = build_candidate_from_reflection(_reflection_record(), candidate_type="prompt_candidate")
    first = append_candidate_record(candidate, project_root=tmp_path)
    second = append_candidate_record(candidate, project_root=tmp_path)

    path = first.path
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    records = list_candidate_records("prompt_candidate", project_root=tmp_path)
    paths = candidate_pool_paths(project_root=tmp_path)

    assert first.created is True
    assert second.created is False
    assert second.record == first.record
    assert rows == [first.record]
    assert records == [first.record]
    assert paths.root == tmp_path / "workspace" / "self_evolution" / "candidates"


def test_candidate_pool_rejects_unknown_type(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown self-evolution candidate type"):
        append_candidate_record(
            {
                "candidate_type": "accepted_baseline",
                "source_experience_id": "exp",
                "source_run_id": "run",
                "provenance": {},
            },
            project_root=tmp_path,
        )


def test_append_candidate_record_forces_candidate_only_boundaries(tmp_path: Path):
    result = append_candidate_record(
        {
            "candidate_id": "prompt_candidate:manual",
            "candidate_type": "prompt_candidate",
            "source_experience_id": "exp_manual",
            "source_reflection_id": "refl_manual",
            "source_run_id": "web-self-manual",
            "txn_id": "txn-manual",
            "provenance": {
                "source_experience_id": "exp_manual",
                "source_reflection_id": "refl_manual",
                "source_run_id": "web-self-manual",
                "evidence_refs": ["reflection:web-self-manual"],
            },
            "review_state": "accepted",
            "supervised_required": False,
            "candidate_only": False,
            "auto_apply": True,
            "risk_level": "high",
            "allowed_downstream_uses": ["supervised_review", "accepted_baseline", "runtime_prompt_override"],
            "blocked_downstream_uses": "manual_block",
        },
        project_root=tmp_path,
    )

    record = result.record

    assert record["review_state"] == "pending"
    assert record["supervised_required"] is True
    assert record["candidate_only"] is True
    assert record["auto_apply"] is False
    assert record["risk_level"] == "high"
    assert record["allowed_downstream_uses"] == ["supervised_review"]
    assert "accepted_baseline" not in record["allowed_downstream_uses"]
    assert "runtime_prompt_override" not in record["allowed_downstream_uses"]
    assert "runtime_prompt_override" in record["blocked_downstream_uses"]
    assert "manual_block" in record["blocked_downstream_uses"]
    assert "m" not in record["blocked_downstream_uses"]
    assert record["supervised_intake_boundary"]["formal_supervised_review_allowed"] is True
    assert record["supervised_intake_boundary"]["risk_level"] == "high"
    assert record["supervised_intake_boundary"]["candidate_only"] is True


def test_append_candidate_record_defaults_unknown_risk_to_pending_review(tmp_path: Path):
    result = append_candidate_record(
        {
            "candidate_id": "proposal_candidate:unknown-risk",
            "candidate_type": "proposal_candidate",
            "source_experience_id": "exp_risk",
            "source_run_id": "web-self-risk",
            "risk_level": "accepted",
            "provenance": {
                "source_experience_id": "exp_risk",
                "source_run_id": "web-self-risk",
                "evidence_refs": ["reflection:web-self-risk"],
            },
        },
        project_root=tmp_path,
    )

    assert result.record["risk_level"] == "pending_review"
    assert result.record["supervised_intake_boundary"]["risk_level"] == "pending_review"
