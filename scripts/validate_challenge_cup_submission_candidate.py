"""Validate the single current Challenge Cup submission candidate manifest.

The validator is read-only.  An incomplete candidate can be structurally valid;
``--require-ready`` additionally requires every mandatory slot and hash to be
ready.  This keeps preparation truth separate from upload authorization and
official-submission evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

CANONICAL_FILENAME = "CURRENT_SUBMISSION_CANDIDATE.json"
CANDIDATE_KIND = "challenge_cup_submission_candidate"
SCHEMA_VERSION = 1
READY_STATUS = "READY"
ALLOWED_SLOT_STATUSES = {"MISSING", "READY", "OPTIONAL", "BLOCKED"}
EXPECTED_SLOTS = {
    "technical_proposal_pdf",
    "full_catalog_results",
    "source_code",
    "qwen_official_evidence",
    "deep_experiment_suite",
    "demo_video",
    "official_submission_receipt",
    "test_api",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _error(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _safe_relative(root: Path, value: Any) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    relative = Path(raw)
    if relative.is_absolute():
        return None
    resolved = (root / relative).resolve(strict=False)
    try:
        resolved.relative_to(root.resolve(strict=False))
    except ValueError:
        return None
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_candidate(candidate_path: Path) -> dict[str, Any]:
    candidate_path = Path(candidate_path).resolve(strict=False)
    root = candidate_path.parent
    errors: list[dict[str, str]] = []

    if candidate_path.name != CANONICAL_FILENAME:
        errors.append(
            _error(
                "noncanonical_candidate_filename",
                f"当前候选必须命名为 {CANONICAL_FILENAME}",
            )
        )
    root_candidates = sorted(root.glob("*SUBMISSION_CANDIDATE*.json"))
    if root_candidates != [candidate_path]:
        errors.append(
            _error(
                "multiple_current_candidates",
                "提交材料根目录必须且只能有一个 current candidate manifest",
            )
        )

    try:
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schemaVersion": 1,
            "candidatePath": str(candidate_path),
            "valid": False,
            "ready": False,
            "requiredReady": 0,
            "requiredCount": 0,
            "blockers": ["candidate_unreadable"],
            "errors": [_error("candidate_unreadable", str(exc))],
            "slots": [],
        }

    if not isinstance(payload, dict):
        errors.append(_error("candidate_not_object", "candidate manifest 必须是对象"))
        payload = {}
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(_error("schema_version_invalid", "schemaVersion 必须为 1"))
    if payload.get("candidateKind") != CANDIDATE_KIND:
        errors.append(_error("candidate_kind_invalid", "candidateKind 不匹配"))
    if not str(payload.get("candidateId") or "").strip():
        errors.append(_error("candidate_id_missing", "candidateId 不能为空"))
    if payload.get("current") is not True:
        errors.append(_error("candidate_not_current", "current 必须为 true"))

    raw_slots = payload.get("slots")
    if not isinstance(raw_slots, list):
        errors.append(_error("slots_invalid", "slots 必须是列表"))
        raw_slots = []

    seen_keys: set[str] = set()
    slot_reports: list[dict[str, Any]] = []
    required_count = 0
    required_ready = 0
    for raw_slot in raw_slots:
        if not isinstance(raw_slot, dict):
            errors.append(_error("slot_invalid", "slot 必须是对象"))
            continue
        key = str(raw_slot.get("key") or "").strip()
        if not key or key in seen_keys:
            errors.append(_error("slot_key_invalid", f"slot key 缺失或重复: {key!r}"))
            continue
        seen_keys.add(key)
        status = str(raw_slot.get("status") or "").strip().upper()
        required = raw_slot.get("required") is True
        if required:
            required_count += 1
        if status not in ALLOWED_SLOT_STATUSES:
            errors.append(_error("slot_status_invalid", f"{key} status={status!r}"))

        slot_root = _safe_relative(root, raw_slot.get("path"))
        if slot_root is None:
            errors.append(_error("unsafe_slot_path", f"{key} path 越界或为空"))
        elif not slot_root.exists():
            errors.append(_error("slot_path_missing", f"{key} path 不存在"))

        raw_files = raw_slot.get("files")
        if not isinstance(raw_files, list):
            errors.append(_error("slot_files_invalid", f"{key} files 必须是列表"))
            raw_files = []
        verified_files: list[dict[str, str]] = []
        if status == READY_STATUS and not raw_files:
            errors.append(_error("ready_slot_without_files", f"{key} READY 但没有文件"))
        for raw_file in raw_files:
            if not isinstance(raw_file, dict):
                errors.append(_error("slot_file_invalid", f"{key} files 含非对象"))
                continue
            file_path = _safe_relative(root, raw_file.get("path"))
            expected_hash = str(raw_file.get("sha256") or "").strip().lower()
            if file_path is None:
                errors.append(_error("unsafe_file_path", f"{key} 文件路径越界或为空"))
                continue
            if not file_path.is_file():
                errors.append(_error("candidate_file_missing", f"{key}: {file_path}"))
                continue
            if not SHA256_RE.fullmatch(expected_hash):
                errors.append(_error("candidate_hash_invalid", f"{key}: {file_path.name}"))
                continue
            actual_hash = _sha256(file_path)
            if actual_hash != expected_hash:
                errors.append(_error("candidate_hash_mismatch", f"{key}: {file_path.name}"))
                continue
            verified_files.append({"path": str(file_path), "sha256": actual_hash})

        slot_ready = status == READY_STATUS and len(verified_files) == len(raw_files) and bool(raw_files)
        if required and slot_ready:
            required_ready += 1
        slot_reports.append(
            {
                "key": key,
                "required": required,
                "status": status,
                "ready": slot_ready,
                "verifiedFileCount": len(verified_files),
            }
        )

    missing_slot_keys = sorted(EXPECTED_SLOTS - seen_keys)
    unexpected_slot_keys = sorted(seen_keys - EXPECTED_SLOTS)
    if missing_slot_keys:
        errors.append(_error("required_slot_definitions_missing", ",".join(missing_slot_keys)))
    if unexpected_slot_keys:
        errors.append(_error("unexpected_slot_definitions", ",".join(unexpected_slot_keys)))

    ready = not errors and required_count > 0 and required_ready == required_count
    blockers: list[str] = []
    if required_ready != required_count:
        blockers.append("required_slots_missing")
    if errors:
        blockers.append("candidate_manifest_invalid")

    authority = payload.get("authority") if isinstance(payload.get("authority"), dict) else {}
    if payload.get("status") == READY_STATUS and not ready:
        errors.append(_error("ready_status_not_derived", "status=READY 但必需槽位未闭合"))
        ready = False
    if authority.get("completionClaimsAllowed") is True and not ready:
        errors.append(
            _error(
                "completion_claims_not_derived",
                "completionClaimsAllowed 不能早于必需槽位和哈希闭合",
            )
        )
        ready = False
    receipt_ready = any(
        slot["key"] == "official_submission_receipt" and slot["ready"]
        for slot in slot_reports
    )
    if authority.get("officiallySubmitted") is True and not receipt_ready:
        errors.append(
            _error(
                "official_submission_without_receipt",
                "officiallySubmitted=true 需要官方回执槽位及哈希证据",
            )
        )
        ready = False

    valid = not errors
    if not valid and "candidate_manifest_invalid" not in blockers:
        blockers.append("candidate_manifest_invalid")
    return {
        "schemaVersion": 1,
        "candidatePath": str(candidate_path),
        "candidateId": str(payload.get("candidateId") or ""),
        "valid": valid,
        "ready": ready,
        "requiredReady": required_ready,
        "requiredCount": required_count,
        "blockers": blockers,
        "errors": errors,
        "slots": slot_reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="验证唯一挑战杯正式提交候选（只读）")
    parser.add_argument("candidate", type=Path, help=f"{CANONICAL_FILENAME} 路径")
    parser.add_argument("--require-ready", action="store_true", help="必需槽位未全部 READY 时返回非零")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告")
    args = parser.parse_args(argv)
    report = validate_candidate(args.candidate)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"candidate={report.get('candidateId') or '-'} valid={report['valid']} "
            f"ready={report['ready']} required={report['requiredReady']}/"
            f"{report['requiredCount']} blockers={','.join(report['blockers']) or '-'}"
        )
    if not report["valid"]:
        return 2
    if args.require_ready and not report["ready"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
