from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.challenge_cup_truth_snapshot import (
    SnapshotInputError,
    _overall_snapshot,
    build_snapshot,
    submission_snapshot,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _fixture_roots(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    project_root = tmp_path / "project"
    challenge_root = tmp_path / "挑战杯"
    data_root = tmp_path / "data"
    runtime_root = tmp_path / "runtime"
    project_root.mkdir()
    runtime_root.mkdir()
    _write_json(
        challenge_root / "01-项目材料" / "data" / "full_catalog_result_set_v1.json",
        {
            "status": "planned_not_started",
            "counts": {
                "expected": 125,
                "approved": 0,
                "needsRevision": 0,
                "blocked": 0,
                "failed": 0,
                "missing": 125,
                "duplicates": 0,
            },
        },
    )
    return project_root, challenge_root, data_root, runtime_root


def _git_evidence() -> dict:
    return {
        "disk": {"head": "d" * 40, "branch": "main", "worktreeClean": True},
        "running": {"backendHead": "b" * 40, "frontendBuiltFromCommit": "f" * 40},
    }


def test_snapshot_keeps_historical_receipts_out_of_formal_results(tmp_path: Path) -> None:
    project_root, challenge_root, data_root, runtime_root = _fixture_roots(tmp_path)
    team_root = data_root / "workspace" / "teams" / "research-team"
    _write_json(
        team_root / "challenge_program" / "question_runs" / "index.json",
        {"records": []},
    )
    receipt_root = team_root / "challenge_program" / "model_invocation_receipts"
    _write_json(
        receipt_root / "q1" / "run-a.json",
        {
            "questionId": "SCI-001",
            "workflowRunId": "run-a",
            "receipts": [
                {"provider": "relay_autodl", "model": "GLM-5.3-flash"},
                {"provider": "local", "model": "Qwen3-local"},
            ],
        },
    )
    _write_json(
        receipt_root / "q2" / "run-b.json",
        {
            "questionId": "SCI-002",
            "workflowRunId": "run-b",
            "receipts": [{"provider": "dashscope", "model": "qwen-plus"}],
        },
    )

    snapshot = build_snapshot(
        project_root,
        challenge_root,
        data_root=data_root,
        runtime_root=runtime_root,
        git_evidence=_git_evidence(),
        generated_at="2026-08-30T00:00:00+00:00",
    )

    assert snapshot["devDiagnostic"]["receiptCount"] == 3
    assert snapshot["devDiagnostic"]["workflowRunCount"] == 2
    assert snapshot["devDiagnostic"]["questionCount"] == 2
    assert snapshot["devDiagnostic"]["formalProviderCompatibleReceiptCount"] == 1
    assert snapshot["formal"]["catalogRecordCount"] == 0
    assert snapshot["formal"]["acceptedFormalResultCount"] == 0
    assert snapshot["formal"]["state"] == "planned_not_started"
    assert snapshot["overall"]["phase"] == "PRE_FORMAL_G1"


def test_formal_candidate_requires_dashscope_qwen_and_full_persisted_gates(tmp_path: Path) -> None:
    project_root, challenge_root, data_root, runtime_root = _fixture_roots(tmp_path)
    team_root = data_root / "workspace" / "teams" / "research-team"
    base = {
        "schemaVersion": 2,
        "questionId": "SCI-001",
        "submissionEligible": True,
        "status": "approved",
        "modelProvider": "dashscope",
        "modelId": "qwen-plus",
        "validation": {
            "schemaValidation": "passed",
            "citationValidation": "passed",
            "semanticValidation": "passed",
            "officialModelCall": True,
        },
        "humanGates": {
            "allApproved": True,
            "decisions": {"H1": "approved", "H2": "approved"},
        },
        "resultPackage": {"canonicalHash": "a" * 64},
    }
    rejected = {**base, "questionId": "SCI-002", "modelProvider": "relay_autodl", "modelId": "GLM"}
    _write_json(
        team_root / "challenge_program" / "question_runs" / "index.json",
        {"records": [base, rejected]},
    )
    _write_json(
        team_root
        / "challenge_program"
        / "question_runs"
        / "SCI-001"
        / "run-a.result-package.v2.json",
        {"packageId": "package-a"},
    )

    snapshot = build_snapshot(
        project_root,
        challenge_root,
        data_root=data_root,
        runtime_root=runtime_root,
        git_evidence=_git_evidence(),
    )

    assert snapshot["formal"]["catalogRecordCount"] == 2
    assert snapshot["formal"]["resultPackageRecordCount"] == 2
    assert snapshot["formal"]["resultPackageFileCount"] == 1
    assert snapshot["formal"]["persistedStrictCandidateCount"] == 1
    assert snapshot["formal"]["acceptedFormalResultCount"] == 1
    assert snapshot["formal"]["state"] == "in_progress"
    assert snapshot["formal"]["formalG1Ready"] is False


def test_formal_result_count_deduplicates_question_identity(tmp_path: Path) -> None:
    project_root, challenge_root, data_root, runtime_root = _fixture_roots(tmp_path)
    team_root = data_root / "workspace" / "teams" / "research-team"
    candidate = {
        "schemaVersion": 2,
        "questionId": "SCI-001",
        "submissionEligible": True,
        "status": "approved",
        "modelProvider": "dashscope",
        "modelId": "qwen-plus",
        "validation": {
            "schemaValidation": "passed",
            "citationValidation": "passed",
            "semanticValidation": "passed",
            "officialModelCall": True,
        },
        "humanGates": {"allApproved": True, "decisions": {"H1": "approved"}},
        "resultPackage": {"canonicalHash": "a" * 64},
    }
    _write_json(
        team_root / "challenge_program" / "question_runs" / "index.json",
        {"records": [candidate for _ in range(125)]},
    )

    snapshot = build_snapshot(
        project_root,
        challenge_root,
        data_root=data_root,
        runtime_root=runtime_root,
        git_evidence=_git_evidence(),
    )

    assert snapshot["formal"]["persistedStrictCandidateCount"] == 125
    assert snapshot["formal"]["acceptedFormalResultCount"] == 1
    assert snapshot["formal"]["state"] == "in_progress"
    assert snapshot["overall"]["phase"] == "FORMAL_RESULTS_IN_PROGRESS"


def test_submission_counts_only_section_artifacts_as_candidates(tmp_path: Path) -> None:
    project_root, challenge_root, data_root, runtime_root = _fixture_roots(tmp_path)
    team_root = data_root / "workspace" / "teams" / "research-team"
    _write_json(team_root / "challenge_program" / "question_runs" / "index.json", {"records": []})
    submission_root = challenge_root / "06-提交材料"
    (submission_root / "README.md").parent.mkdir(parents=True, exist_ok=True)
    (submission_root / "README.md").write_text("instructions", encoding="utf-8")
    for name in (
        "01-最终作品PDF",
        "02-125题逐题结果",
        "03-源码与复现",
        "04-Qwen调用证据",
        "05-深实验",
        "06-可选演示视频",
        "07-官方提交回执",
    ):
        (submission_root / name).mkdir(parents=True)
    (submission_root / "01-最终作品PDF" / "draft.pdf").write_bytes(b"pdf")

    snapshot = build_snapshot(
        project_root,
        challenge_root,
        data_root=data_root,
        runtime_root=runtime_root,
        git_evidence=_git_evidence(),
    )

    assert snapshot["submission"]["candidateFileCount"] == 1
    assert snapshot["submission"]["rootInstructionFileCount"] == 1
    assert snapshot["submission"]["requiredPopulatedSectionCount"] == 1
    assert snapshot["submission"]["officialReceiptFileCount"] == 0
    assert snapshot["submission"]["readinessState"] == "not_ready"
    assert snapshot["submission"]["submissionState"] == "not_submitted"


def test_submission_readiness_does_not_require_post_submission_receipt(tmp_path: Path) -> None:
    submission_root = tmp_path / "06-提交材料"
    for name in (
        "01-最终作品PDF",
        "02-125题逐题结果",
        "03-源码与复现",
        "04-Qwen调用证据",
        "05-深实验",
        "06-可选演示视频",
        "07-官方提交回执",
    ):
        section = submission_root / name
        section.mkdir(parents=True)
        if name.startswith(("01-", "02-", "03-", "04-", "05-")):
            (section / "artifact.txt").write_text("ready", encoding="utf-8")

    before_submit = submission_snapshot(submission_root, accepted_formal_results=125)

    assert before_submit["preSubmissionRequiredSectionCount"] == 5
    assert before_submit["preSubmissionPopulatedSectionCount"] == 5
    assert before_submit["requiredSectionCount"] == 6
    assert before_submit["requiredPopulatedSectionCount"] == 5
    assert before_submit["readinessState"] == "ready_for_final_submission_check"
    assert before_submit["submissionState"] == "not_submitted"

    receipt = submission_root / "07-官方提交回执" / "success-screenshot.png"
    receipt.write_bytes(b"not machine verified")
    after_receipt_file = submission_snapshot(submission_root, accepted_formal_results=125)

    assert after_receipt_file["officialReceiptFileCount"] == 1
    assert after_receipt_file["submissionState"] == "receipt_present_unverified"


@pytest.mark.parametrize(
    ("accepted", "readiness", "submission", "expected"),
    [
        (
            0,
            "not_ready",
            "not_submitted",
            {
                "phase": "PRE_FORMAL_G1",
                "closedLoopState": "BLOCKED_BEFORE_FORMAL_RUN",
                "nextGate": "QWEN_G1_ACCEPTANCE_PACKAGE_APPROVAL",
            },
        ),
        (
            1,
            "not_ready",
            "not_submitted",
            {
                "phase": "FORMAL_RESULTS_IN_PROGRESS",
                "closedLoopState": "FORMAL_RESULTS_INCOMPLETE",
                "nextGate": "COMPLETE_REMAINING_CANONICAL_FORMAL_RESULTS",
            },
        ),
        (
            125,
            "not_ready",
            "not_submitted",
            {
                "phase": "FORMAL_RESULTS_COMPLETE",
                "closedLoopState": "SUBMISSION_ARTIFACTS_INCOMPLETE",
                "nextGate": "POPULATE_PRE_SUBMISSION_ARTIFACTS",
            },
        ),
        (
            125,
            "ready_for_final_submission_check",
            "not_submitted",
            {
                "phase": "READY_FOR_FINAL_SUBMISSION_CHECK",
                "closedLoopState": "AWAITING_FINAL_SUBMISSION_CHECK",
                "nextGate": "FINAL_SUBMISSION_CHECK",
            },
        ),
        (
            125,
            "ready_for_final_submission_check",
            "receipt_present_unverified",
            {
                "phase": "SUBMISSION_RECEIPT_PRESENT_UNVERIFIED",
                "closedLoopState": "AWAITING_OFFICIAL_RECEIPT_VERIFICATION",
                "nextGate": "VERIFY_OFFICIAL_SUBMISSION_RECEIPT",
            },
        ),
    ],
)
def test_overall_snapshot_tracks_canonical_formal_and_submission_evidence(
    accepted: int,
    readiness: str,
    submission: str,
    expected: dict[str, str],
) -> None:
    assert _overall_snapshot(
        {"acceptedFormalResultCount": accepted},
        {"readinessState": readiness, "submissionState": submission},
    ) == expected


def test_unreadable_declared_catalog_fails_closed(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    challenge_root = tmp_path / "挑战杯"
    project_root.mkdir()
    catalog = challenge_root / "01-项目材料" / "data" / "full_catalog_result_set_v1.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("{broken", encoding="utf-8")

    with pytest.raises(SnapshotInputError, match="JSON is unreadable"):
        build_snapshot(
            project_root,
            challenge_root,
            data_root=tmp_path / "data",
            runtime_root=tmp_path / "runtime",
            git_evidence=_git_evidence(),
        )
