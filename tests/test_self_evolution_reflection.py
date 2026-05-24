#!/usr/bin/env python3
"""Bounded self-evolution reflection tests."""

import json
from pathlib import Path

from core.evaluation.self_evolution_reflection import (
    REFLECTION_JSONL,
    build_bounded_self_evolution_reflection,
    list_reflection_records,
    record_bounded_self_evolution_reflection,
)


def _failed_experience() -> dict:
    return {
        "experience_id": "exp_failed_verify",
        "kind": "failure_pattern",
        "source_run_id": "web-self-failed",
        "source_turn": 2,
        "txn_id": "txn-verify",
        "runtime_scene_refs": ["logs/runtime_scenes/pkg/agent/self_evolution_runs/web-self-failed.jsonl"],
        "audit_refs": ["workspace/self_evolution/rollback/web-self-failed/manifest.json"],
        "summary": "The run failed during pytest verification after a bounded tool attempt.",
        "evidence": {
            "status": "failed",
            "phase": "failed",
            "tool_name": "pytest",
            "tool_call_count": 4,
            "rollback_status": "available",
            "rollback_entry_count": 1,
            "error_present": True,
        },
        "quality_score": 0.4,
        "confidence": 0.6,
        "dedupe_key": "self_terminal:web-self-failed",
        "downstream_use": ["self_questioning", "self_attributing", "diagnostic_case"],
        "supervised_required": True,
        "created_at": "2026-05-24T10:00:00Z",
    }


def test_build_bounded_reflection_keeps_three_mechanisms_as_candidates():
    record = build_bounded_self_evolution_reflection(_failed_experience())

    assert record["reflection_id"].startswith("refl_")
    assert record["source_experience_id"] == "exp_failed_verify"
    assert record["source_run_id"] == "web-self-failed"
    assert record["dedupe_key"] == "self_reflection:exp_failed_verify"
    assert record["supervised_required"] is True
    assert record["auto_apply"] is False
    assert record["candidate_only"] is True
    assert "accepted_baseline" not in record
    assert "selection_policy" not in record

    assert 1 <= len(record["self_questioning"]) <= 3
    assert 1 <= len(record["self_navigating"]) <= 3
    assert 1 <= len(record["self_attributing"]) <= 3

    question = record["self_questioning"][0]
    assert question["candidate_type"] == "question_candidate"
    assert question["bounded"] is True
    assert "logs/runtime_scenes/pkg/agent/self_evolution_runs/web-self-failed.jsonl" in question["evidence_refs"]
    assert "pytest" in question["question"]

    navigation = record["self_navigating"][0]
    assert navigation["candidate_type"] == "navigation_hint"
    assert navigation["must_recheck_current_state"] is True
    assert navigation["auto_apply"] is False

    attribution = record["self_attributing"][0]
    assert attribution["candidate_type"] == "attribution_record"
    assert attribution["bounded"] is True
    assert attribution["confidence"] <= 1.0
    assert "pytest" in attribution["claim"]


def test_record_bounded_reflection_materializes_and_dedupes(tmp_path: Path):
    first = record_bounded_self_evolution_reflection(_failed_experience(), project_root=tmp_path)
    second = record_bounded_self_evolution_reflection(_failed_experience(), project_root=tmp_path)

    rows = [
        json.loads(line)
        for line in (tmp_path / REFLECTION_JSONL).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records = list_reflection_records(project_root=tmp_path)

    assert first.created is True
    assert second.created is False
    assert second.record == first.record
    assert rows == [first.record]
    assert records == [first.record]
