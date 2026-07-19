from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from core.evaluation.supervised_evidence_integrity import (
    FormalSupervisedEvidenceWriteBlocked,
    archive_supervised_test_contamination,
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


def test_archive_creates_verified_rollback_copy_and_removes_only_target_records(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    root = workspace_root / "supervised_evolution"
    session_id = "supervised_test"
    real_session_id = "supervised_real"
    proposal_id = "bundle:probe:test"
    decision_path = root / "decisions" / f"{session_id}.json"
    session_report = root / "sessions" / session_id / "probe.json"
    policy_path = root / "policy" / f"{session_id}.json"
    proposal_path = workspace_root / "evolution" / "proposals" / "test-proposal.json"
    lineage_path = workspace_root / "evolution" / "proposals" / "lineage_index.json"
    audit_path = workspace_root / "evolution" / "audit.jsonl"
    dashboard_path = root / "dashboard" / "index.html"
    history_path = root / "history.jsonl"
    observation_path = root / "policy" / "candidate_observation_pool.jsonl"
    for path in (
        decision_path,
        session_report,
        policy_path,
        proposal_path,
        lineage_path,
        audit_path,
        dashboard_path,
        history_path,
        observation_path,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "policy_action": {
                    "bundle_path": str(tmp_path / "pytest-of-user" / "pytest-1" / "bundle.json"),
                    "proposal_paths": [str(proposal_path)],
                    "lineage_index_path": str(lineage_path),
                    "case_evidence": [
                        {
                            "intake_provenance": {
                                "provenance": {"creator_version": "pytest"}
                            },
                            "evidence_paths": {"baseline_worktree_path": "C:/repo/.tmp/baseline"},
                            "proposal_id": proposal_id,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    session_report.write_text("test report", encoding="utf-8")
    policy_path.write_text(json.dumps({"session_id": session_id}), encoding="utf-8")
    proposal_path.write_text(
        json.dumps({"session_id": session_id, "proposal_id": proposal_id}), encoding="utf-8"
    )
    lineage_path.write_text(
        json.dumps(
            {
                "proposal_count": 2,
                "case_count": 2,
                "cases": [
                    {"case_id": "probe", "chain": [{"proposal_id": proposal_id}]},
                    {"case_id": "real", "chain": [{"proposal_id": "bundle:real:1"}]},
                ],
            }
        ),
        encoding="utf-8",
    )
    target_line = json.dumps({"session_id": session_id}) + "\n"
    real_line = json.dumps({"session_id": real_session_id}) + "\n"
    history_path.write_text(target_line + real_line, encoding="utf-8")
    observation_path.write_text(target_line + real_line, encoding="utf-8")
    audit_path.write_text(target_line + real_line, encoding="utf-8")
    dashboard_path.write_text(f"<html>{session_id}</html>", encoding="utf-8")
    tracked = [
        decision_path,
        session_report,
        policy_path,
        proposal_path,
        lineage_path,
        audit_path,
        dashboard_path,
        history_path,
        observation_path,
    ]
    originals = {str(path.resolve()): path.read_bytes() for path in tracked}
    archive_root = tmp_path / "backups" / "archive-one"

    result = archive_supervised_test_contamination(
        evidence_root=root,
        session_ids=[session_id],
        archive_root=archive_root,
    )

    assert result["status"] == "completed"
    manifest = json.loads((archive_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "prepared"
    for record in manifest["files"]:
        source = record["source_path"]
        archived = Path(record["archive_path"])
        assert archived.read_bytes() == originals[source]
        assert _sha256(archived) == record["sha256"]
    assert not decision_path.exists()
    assert not session_report.exists()
    assert not policy_path.exists()
    assert not proposal_path.exists()
    assert not dashboard_path.exists()
    assert real_session_id in history_path.read_text(encoding="utf-8")
    assert session_id not in history_path.read_text(encoding="utf-8")
    assert real_session_id in observation_path.read_text(encoding="utf-8")
    assert session_id not in observation_path.read_text(encoding="utf-8")
    assert real_session_id in audit_path.read_text(encoding="utf-8")
    assert session_id not in audit_path.read_text(encoding="utf-8")
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    assert [case["case_id"] for case in lineage["cases"]] == ["real"]
    assert lineage["case_count"] == 1
    assert lineage["proposal_count"] == 1
    assert build_supervised_evidence_preview(root)["summary"]["contaminated_sessions"] == 0


def test_archive_refuses_unverified_session(tmp_path: Path) -> None:
    root = tmp_path / "workspace" / "supervised_evolution"
    decision_path = root / "decisions" / "supervised_real.json"
    decision_path.parent.mkdir(parents=True)
    decision_path.write_text(
        json.dumps({"session_id": "supervised_real", "policy_action": {}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="未被强证据确认为测试污染"):
        archive_supervised_test_contamination(
            evidence_root=root,
            session_ids=["supervised_real"],
            archive_root=tmp_path / "backups" / "archive-real",
        )

    assert decision_path.exists()
