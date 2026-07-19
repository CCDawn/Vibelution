from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from core.evaluation.supervised_evidence_integrity import (
    FormalSupervisedEvidenceWriteBlocked,
    assert_supervised_evidence_write_allowed,
    build_supervised_evidence_preview,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pytest_cannot_write_to_formal_supervised_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    formal_root = tmp_path / "formal" / "supervised_evolution"
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_guard (call)")

    with pytest.raises(FormalSupervisedEvidenceWriteBlocked):
        assert_supervised_evidence_write_allowed(
            project_root=project_root,
            evidence_root=formal_root,
            formal_evidence_root=formal_root,
        )


def test_pytest_can_write_to_isolated_supervised_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_guard (call)")
    assert_supervised_evidence_write_allowed(
        project_root=tmp_path / "project",
        evidence_root=tmp_path / "sandbox" / "supervised_evolution",
        formal_evidence_root=tmp_path / "formal" / "supervised_evolution",
    )


def test_preview_identifies_strong_test_contamination_without_mutating_files(tmp_path: Path) -> None:
    root = tmp_path / "supervised_evolution"
    session_id = "supervised_20260619_140149"
    decision_path = root / "decisions" / f"{session_id}.json"
    session_report = root / "sessions" / session_id / "probe_baseline.json"
    policy_path = root / "policy" / f"{session_id}.json"
    history_path = root / "history.jsonl"
    observation_path = root / "policy" / "candidate_observation_pool.jsonl"
    proposal_path = tmp_path / "evolution" / "proposals" / "proposal.json"
    lineage_path = tmp_path / "evolution" / "proposals" / "lineage_index.json"
    for path in (
        decision_path,
        session_report,
        policy_path,
        history_path,
        observation_path,
        proposal_path,
        lineage_path,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)

    decision = {
        "session_id": session_id,
        "policy_action": {
            "bundle_path": str(
                tmp_path / "pytest-of-user" / "pytest-1" / "workspace" / "evaluation" / "bundle.json"
            ),
            "policy_record_path": str(policy_path),
            "proposal_paths": [str(proposal_path)],
            "lineage_index_path": str(lineage_path),
            "case_evidence": [
                {
                    "intake_provenance": {
                        "provenance": {
                            "creator_version": "pytest",
                            "generation_reason": "test provenance propagation",
                        }
                    },
                    "evidence_paths": {"baseline_worktree_path": "C:/repo/.tmp/baseline"},
                }
            ],
        },
    }
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    session_report.write_text('{"status":"success"}', encoding="utf-8")
    policy_path.write_text(json.dumps({"session_id": session_id}), encoding="utf-8")
    history_path.write_text(json.dumps({"session_id": session_id}) + "\n", encoding="utf-8")
    observation_path.write_text(json.dumps({"source_session_id": session_id}) + "\n", encoding="utf-8")
    proposal_path.write_text(json.dumps({"source_session_id": session_id}), encoding="utf-8")
    lineage_path.write_text(json.dumps({"entries": [{"source_session_id": session_id}]}), encoding="utf-8")
    tracked = [
        decision_path,
        session_report,
        policy_path,
        history_path,
        observation_path,
        proposal_path,
        lineage_path,
    ]
    before = {str(path): _sha256(path) for path in tracked}

    preview = build_supervised_evidence_preview(root)

    assert preview["mode"] == "read_only_preview"
    assert preview["summary"]["contaminated_sessions"] == 1
    session = preview["sessions"][0]
    assert session["classification"] == "test_contamination"
    assert len(session["strong_signals"]) >= 2
    associated = {record["path"] for record in session["associated_paths"]}
    assert {str(path.resolve()) for path in tracked}.issubset(associated)
    assert all(record["sha256"] for record in session["associated_paths"] if record["exists"])
    assert before == {str(path): _sha256(path) for path in tracked}


def test_preview_does_not_classify_a_single_weak_signal_as_contamination(tmp_path: Path) -> None:
    root = tmp_path / "supervised_evolution"
    decision_path = root / "decisions" / "supervised_one.json"
    decision_path.parent.mkdir(parents=True)
    decision_path.write_text(
        json.dumps(
            {
                "session_id": "supervised_one",
                "policy_action": {
                    "case_evidence": [
                        {
                            "intake_provenance": {
                                "provenance": {"generation_reason": "test-like exploratory case"}
                            }
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    preview = build_supervised_evidence_preview(root)

    assert preview["sessions"][0]["classification"] == "unverified"
    assert preview["summary"]["contaminated_sessions"] == 0
