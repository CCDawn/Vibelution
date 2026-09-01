"""Build a redacted, read-only Challenge Cup truth snapshot.

The snapshot keeps three evidence layers separate:

* DEV_DIAGNOSTIC: observed workflow/model receipts, useful for diagnosis only;
* FORMAL: canonical catalog records and result packages;
* SUBMISSION: files staged in the official submission workspace and receipts.

The command never mutates product state.  ``--output`` writes only the requested
snapshot file; omitting it prints JSON to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vibelution_storage import resolve_project_data_home, resolve_project_runtime_home


SCHEMA_VERSION = 1
TEAM_ID = "research-team"
FORMAL_PROVIDER = "dashscope"
FORMAL_MODEL_FAMILY = "qwen"
EXPECTED_CATALOG_COUNT = 125
PRE_SUBMISSION_REQUIRED_SECTIONS = (
    "01-最终作品PDF",
    "02-125题逐题结果",
    "03-源码与复现",
    "04-Qwen调用证据",
    "05-深实验",
)
POST_SUBMISSION_EVIDENCE_SECTIONS = (
    "07-官方提交回执",
)
REQUIRED_SUBMISSION_SECTIONS = (
    *PRE_SUBMISSION_REQUIRED_SECTIONS,
    *POST_SUBMISSION_EVIDENCE_SECTIONS,
)
OPTIONAL_SUBMISSION_SECTIONS = ("06-可选演示视频",)


class SnapshotInputError(RuntimeError):
    """Raised when a declared truth source exists but cannot be trusted."""


def _io_path(path: Path) -> Path:
    """Use the Windows extended-length form for deeply nested receipt stores."""

    resolved = path.resolve(strict=False)
    if os.name != "nt":
        return resolved
    value = str(resolved)
    if value.startswith("\\\\?\\"):
        return resolved
    if value.startswith("\\\\"):
        return Path(f"\\\\?\\UNC\\{value[2:]}")
    return Path(f"\\\\?\\{value}")


def _read_json(path: Path, *, required: bool = False) -> dict[str, Any]:
    io_path = _io_path(path)
    if not io_path.exists():
        if required:
            raise SnapshotInputError(f"required JSON is missing: {path}")
        return {}
    try:
        value = json.loads(io_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotInputError(f"JSON is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise SnapshotInputError(f"JSON root must be an object: {path}")
    return value


def _run_git(project_root: Path, *args: str) -> str:
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        ["git", *args],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _ahead_count(project_root: Path, older: str, newer: str) -> int | None:
    if not older or not newer or older == newer:
        return 0 if older and newer else None
    raw = _run_git(project_root, "rev-list", "--count", f"{older}..{newer}")
    try:
        return int(raw)
    except ValueError:
        return None


def git_snapshot(project_root: Path, runtime_root: Path) -> dict[str, Any]:
    head = _run_git(project_root, "rev-parse", "HEAD")
    branch = _run_git(project_root, "branch", "--show-current")
    origin_main = _run_git(project_root, "rev-parse", "origin/main")
    status_lines = [
        line
        for line in _run_git(project_root, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
        if line
    ]
    fingerprint_path = runtime_root / "running-code-fingerprint.json"
    fingerprint = _read_json(fingerprint_path)
    backend_head = str(fingerprint.get("runningHead") or "")
    frontend_head = str(fingerprint.get("servingFrontendBuiltFromCommit") or "")
    return {
        "disk": {
            "head": head,
            "branch": branch,
            "originMain": origin_main,
            "worktreeClean": not status_lines,
            "changedPathCount": len(status_lines),
        },
        "running": {
            "fingerprintPresent": bool(fingerprint),
            "backendHead": backend_head,
            "frontendBuiltFromCommit": frontend_head,
            "backendCommitsBehindDisk": _ahead_count(project_root, backend_head, head),
            "frontendCommitsBehindDisk": _ahead_count(project_root, frontend_head, head),
            "startedAt": str(fingerprint.get("startedAt") or ""),
        },
    }


def _receipt_identity(receipt: Mapping[str, Any], store: Mapping[str, Any]) -> tuple[str, str, str, str]:
    scope = receipt.get("scope") if isinstance(receipt.get("scope"), Mapping) else {}
    provider = str(receipt.get("provider") or "unknown").strip().lower() or "unknown"
    model = str(
        receipt.get("model")
        or receipt.get("modelId")
        or receipt.get("modelRef")
        or "unknown"
    ).strip() or "unknown"
    question_id = str(
        store.get("questionId") or scope.get("questionId") or "unknown"
    ).strip().upper() or "unknown"
    workflow_run_id = str(
        store.get("workflowRunId")
        or scope.get("workflowRunId")
        or receipt.get("runId")
        or "unknown"
    ).strip() or "unknown"
    return provider, model, question_id, workflow_run_id


def _counter_rows(counter: Counter[tuple[str, ...]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {**dict(zip(keys, identity)), "count": count}
        for identity, count in sorted(counter.items())
    ]


def receipt_snapshot(receipt_root: Path) -> dict[str, Any]:
    by_provider: Counter[tuple[str, ...]] = Counter()
    by_model: Counter[tuple[str, ...]] = Counter()
    by_question: Counter[tuple[str, ...]] = Counter()
    workflow_run_ids: set[str] = set()
    question_ids: set[str] = set()
    total = 0
    formal_provider_compatible = 0
    store_count = 0

    for path in sorted(receipt_root.rglob("*.json")) if receipt_root.exists() else ():
        store = _read_json(path)
        receipts = store.get("receipts")
        if not isinstance(receipts, list):
            raise SnapshotInputError(f"receipt store has no receipts array: {path}")
        store_count += 1
        for raw_receipt in receipts:
            if not isinstance(raw_receipt, Mapping):
                raise SnapshotInputError(f"receipt entry is not an object: {path}")
            provider, model, question_id, workflow_run_id = _receipt_identity(raw_receipt, store)
            total += 1
            by_provider[(provider,)] += 1
            by_model[(provider, model)] += 1
            by_question[(question_id,)] += 1
            workflow_run_ids.add(workflow_run_id)
            question_ids.add(question_id)
            if provider == FORMAL_PROVIDER and FORMAL_MODEL_FAMILY in model.lower():
                formal_provider_compatible += 1

    return {
        "storeCount": store_count,
        "receiptCount": total,
        "workflowRunCount": len(workflow_run_ids),
        "questionCount": len(question_ids),
        "formalProviderCompatibleReceiptCount": formal_provider_compatible,
        "byProvider": _counter_rows(by_provider, ("provider",)),
        "byProviderModel": _counter_rows(by_model, ("provider", "model")),
        "byQuestion": _counter_rows(by_question, ("questionId",)),
        "classification": "DEV_DIAGNOSTIC_ONLY_UNLESS_BOUND_TO_FORMAL_CATALOG_PACKAGE",
    }


def _all_human_gates_approved(value: Any) -> bool:
    if not isinstance(value, Mapping) or value.get("allApproved") is not True:
        return False
    decisions = value.get("decisions")
    return isinstance(decisions, Mapping) and bool(decisions) and all(
        str(decision) == "approved" for decision in decisions.values()
    )


def _strict_persisted_formal_candidate(record: Mapping[str, Any]) -> bool:
    validation = record.get("validation") if isinstance(record.get("validation"), Mapping) else {}
    model_provider = str(record.get("modelProvider") or "").lower()
    model_id = str(record.get("modelId") or "").lower()
    return bool(
        record.get("schemaVersion") == 2
        and str(record.get("questionId") or "").strip()
        and validation.get("schemaValidation") == "passed"
        and validation.get("citationValidation") == "passed"
        and validation.get("semanticValidation") == "passed"
        and validation.get("officialModelCall") is True
        and model_provider == FORMAL_PROVIDER
        and FORMAL_MODEL_FAMILY in model_id
        and record.get("submissionEligible") is True
        and str(record.get("status") or "") == "approved"
        and _all_human_gates_approved(record.get("humanGates"))
        and isinstance(record.get("resultPackage"), Mapping)
    )


def formal_snapshot(team_root: Path, full_catalog: Mapping[str, Any]) -> dict[str, Any]:
    question_runs_root = team_root / "challenge_program" / "question_runs"
    index = _read_json(question_runs_root / "index.json")
    raw_records = index.get("records")
    records = raw_records if isinstance(raw_records, list) else []
    if raw_records is not None and not isinstance(raw_records, list):
        raise SnapshotInputError("question_runs/index.json records must be an array")
    record_values = [record for record in records if isinstance(record, Mapping)]
    if len(record_values) != len(records):
        raise SnapshotInputError("question_runs/index.json contains a non-object record")

    result_package_files = list(question_runs_root.rglob("*.result-package.v2.json"))
    registered_questions = {
        str(record.get("questionId") or "").strip().upper()
        for record in record_values
        if str(record.get("questionId") or "").strip()
    }
    package_records = [
        record for record in record_values if isinstance(record.get("resultPackage"), Mapping)
    ]
    persisted_formal_candidates = [
        record for record in record_values if _strict_persisted_formal_candidate(record)
    ]
    accepted_question_ids = {
        str(record.get("questionId") or "").strip().upper()
        for record in persisted_formal_candidates
    }
    declared_counts = full_catalog.get("counts") if isinstance(full_catalog.get("counts"), Mapping) else {}
    expected = int(declared_counts.get("expected") or EXPECTED_CATALOG_COUNT)
    declared_approved = int(declared_counts.get("approved") or 0)
    declared_missing = int(declared_counts.get("missing") or max(0, expected - declared_approved))
    formal_state = str(full_catalog.get("status") or "unknown")
    if persisted_formal_candidates or package_records or record_values:
        formal_state = "in_progress"
    if len(accepted_question_ids) == expected:
        formal_state = "catalog_candidates_complete_pending_readiness_audit"

    return {
        "state": formal_state,
        "providerPolicy": {
            "provider": FORMAL_PROVIDER,
            "modelFamily": FORMAL_MODEL_FAMILY,
            "rule": "Only official DashScope Qwen evidence may enter the formal competition chain.",
        },
        "catalogRecordCount": len(record_values),
        "registeredQuestionCount": len(registered_questions),
        "resultPackageRecordCount": len(package_records),
        "resultPackageFileCount": len(result_package_files),
        "persistedStrictCandidateCount": len(persisted_formal_candidates),
        "declaredFullCatalogCounts": {
            "expected": expected,
            "approved": declared_approved,
            "needsRevision": int(declared_counts.get("needsRevision") or 0),
            "blocked": int(declared_counts.get("blocked") or 0),
            "failed": int(declared_counts.get("failed") or 0),
            "missing": declared_missing,
            "duplicates": int(declared_counts.get("duplicates") or 0),
        },
        "acceptedFormalResultCount": len(accepted_question_ids),
        "formalG1Ready": False,
        "formalG1ReadyReason": "requires a separately approved readiness and run-authorization package",
    }


def _files_under(path: Path) -> Iterable[Path]:
    if not path.exists():
        return ()
    return (item for item in path.rglob("*") if item.is_file())


def submission_snapshot(submission_root: Path, *, accepted_formal_results: int) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    for name in (*REQUIRED_SUBMISSION_SECTIONS, *OPTIONAL_SUBMISSION_SECTIONS):
        path = submission_root / name
        files = list(_files_under(path))
        sections.append(
            {
                "name": name,
                "required": name in REQUIRED_SUBMISSION_SECTIONS,
                "exists": path.is_dir(),
                "fileCount": len(files),
                "byteCount": sum(item.stat().st_size for item in files),
            }
        )
    root_files = [item for item in submission_root.glob("*") if item.is_file()] if submission_root.exists() else []
    pre_submission_ready = all(
        section["exists"] and section["fileCount"] > 0
        for section in sections
        if section["name"] in PRE_SUBMISSION_REQUIRED_SECTIONS
    )
    receipt_files = next(
        (section["fileCount"] for section in sections if section["name"] == "07-官方提交回执"),
        0,
    )
    candidate_file_count = sum(section["fileCount"] for section in sections)
    return {
        "readinessState": "ready_for_final_submission_check" if pre_submission_ready and accepted_formal_results == 125 else "not_ready",
        "submissionState": "receipt_present_unverified" if receipt_files > 0 else "not_submitted",
        "candidateFileCount": candidate_file_count,
        "rootInstructionFileCount": len(root_files),
        "preSubmissionPopulatedSectionCount": sum(
            1
            for section in sections
            if section["name"] in PRE_SUBMISSION_REQUIRED_SECTIONS and section["fileCount"] > 0
        ),
        "preSubmissionRequiredSectionCount": len(PRE_SUBMISSION_REQUIRED_SECTIONS),
        "requiredPopulatedSectionCount": sum(
            1 for section in sections if section["required"] and section["fileCount"] > 0
        ),
        "requiredSectionCount": len(REQUIRED_SUBMISSION_SECTIONS),
        "officialReceiptFileCount": receipt_files,
        "sections": sections,
    }


def _overall_snapshot(
    formal: Mapping[str, Any],
    submission: Mapping[str, Any],
) -> dict[str, str]:
    """Project the highest evidence-backed phase without promoting weaker layers."""

    accepted = int(formal.get("acceptedFormalResultCount") or 0)
    if accepted <= 0:
        return {
            "phase": "PRE_FORMAL_G1",
            "closedLoopState": "BLOCKED_BEFORE_FORMAL_RUN",
            "nextGate": "QWEN_G1_ACCEPTANCE_PACKAGE_APPROVAL",
        }
    if accepted < EXPECTED_CATALOG_COUNT:
        return {
            "phase": "FORMAL_RESULTS_IN_PROGRESS",
            "closedLoopState": "FORMAL_RESULTS_INCOMPLETE",
            "nextGate": "COMPLETE_REMAINING_CANONICAL_FORMAL_RESULTS",
        }
    if submission.get("readinessState") != "ready_for_final_submission_check":
        return {
            "phase": "FORMAL_RESULTS_COMPLETE",
            "closedLoopState": "SUBMISSION_ARTIFACTS_INCOMPLETE",
            "nextGate": "POPULATE_PRE_SUBMISSION_ARTIFACTS",
        }
    if submission.get("submissionState") != "receipt_present_unverified":
        return {
            "phase": "READY_FOR_FINAL_SUBMISSION_CHECK",
            "closedLoopState": "AWAITING_FINAL_SUBMISSION_CHECK",
            "nextGate": "FINAL_SUBMISSION_CHECK",
        }
    return {
        "phase": "SUBMISSION_RECEIPT_PRESENT_UNVERIFIED",
        "closedLoopState": "AWAITING_OFFICIAL_RECEIPT_VERIFICATION",
        "nextGate": "VERIFY_OFFICIAL_SUBMISSION_RECEIPT",
    }


def build_snapshot(
    project_root: Path,
    challenge_root: Path,
    *,
    team_id: str = TEAM_ID,
    data_root: Path | None = None,
    runtime_root: Path | None = None,
    git_evidence: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    resolved_project_root = project_root.expanduser().resolve()
    resolved_challenge_root = challenge_root.expanduser().resolve()
    resolved_data_root = (data_root or resolve_project_data_home(resolved_project_root)).resolve()
    resolved_runtime_root = (runtime_root or resolve_project_runtime_home(resolved_project_root)).resolve()
    team_root = resolved_data_root / "workspace" / "teams" / team_id
    full_catalog = _read_json(
        resolved_challenge_root / "01-项目材料" / "data" / "full_catalog_result_set_v1.json",
        required=True,
    )
    receipts = receipt_snapshot(team_root / "challenge_program" / "model_invocation_receipts")
    formal = formal_snapshot(team_root, full_catalog)
    submission = submission_snapshot(
        resolved_challenge_root / "06-提交材料",
        accepted_formal_results=int(formal["acceptedFormalResultCount"]),
    )
    git_value = dict(git_evidence) if git_evidence is not None else git_snapshot(
        resolved_project_root, resolved_runtime_root
    )
    now = generated_at or datetime.now(timezone.utc).isoformat()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "challenge_cup_truth_snapshot",
        "generatedAt": now,
        "scope": {
            "projectRoot": str(resolved_project_root),
            "challengeRoot": str(resolved_challenge_root),
            "teamId": team_id,
        },
        "truthPolicy": {
            "layers": ["DEV_DIAGNOSTIC", "FORMAL", "SUBMISSION"],
            "formalPromotionRule": "DashScope official Qwen + canonical catalog package + readiness + explicit run authorization",
            "noPromotionFrom": [
                "historical receipts",
                "DEV fixtures",
                "local Qwen",
                "GLM",
                "DeepSeek",
                "PPT preset numbers",
            ],
        },
        "gitAndRuntime": git_value,
        "devDiagnostic": receipts,
        "formal": formal,
        "submission": submission,
        "overall": _overall_snapshot(formal, submission),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--challenge-root", type=Path, default=Path.home() / "Desktop" / "挑战杯")
    parser.add_argument("--team-id", default=TEAM_ID)
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--runtime-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        snapshot = build_snapshot(
            args.project_root,
            args.challenge_root,
            team_id=args.team_id,
            data_root=args.data_root,
            runtime_root=args.runtime_root,
        )
    except SnapshotInputError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    encoded = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(encoded, end="")
        return 0
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8", newline="\n")
    print(json.dumps({"ok": True, "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
