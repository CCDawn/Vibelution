"""Host-owned file target contract for autonomous self-evolution candidates."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .runtime_scene_service import record_runtime_scene_event


MAX_PLAN_TARGET_FILES = 8
_PLAN_TARGET_FILES_PATTERN = re.compile(
    r"(?im)^\s*TARGET_FILES_JSON\s*:\s*(?P<payload>\[[^\r\n]*\])\s*$"
)
_FORBIDDEN_PLAN_TARGETS = {
    ".env",
    "AGENTS.md",
}
_FORBIDDEN_PLAN_TARGET_PREFIXES = (
    ".git/",
    ".runtime/",
    ".docs/project-memory/",
    "config/",
    "data/",
    "docs/standards/",
    "logs/",
    "workspace/",
)


class CandidateTargetContractError(RuntimeError):
    """Raised when a plan or candidate violates the exact file target contract."""


def extract_plan_target_files(
    result: dict[str, Any],
    *,
    summary: str,
) -> list[str]:
    """Extract and validate exact repository-relative files from a planner result."""

    raw_targets: Any = None
    for key in ("targetFiles", "target_files", "plannedFiles", "planned_files"):
        if key in result:
            raw_targets = result.get(key)
            break
    if raw_targets is None:
        match = _PLAN_TARGET_FILES_PATTERN.search(str(summary or ""))
        if match:
            try:
                raw_targets = json.loads(match.group("payload"))
            except json.JSONDecodeError as exc:
                raise CandidateTargetContractError(
                    "Plan TARGET_FILES_JSON is invalid JSON."
                ) from exc
    if not isinstance(raw_targets, list) or not raw_targets:
        raise CandidateTargetContractError(
            "Plan did not declare structured target files."
        )
    return normalize_target_files(raw_targets)


def normalize_target_files(raw_targets: list[Any]) -> list[str]:
    """Normalize a bounded exact-file set and reject governance/data paths."""

    if len(raw_targets) > MAX_PLAN_TARGET_FILES:
        raise CandidateTargetContractError(
            f"Plan target file count exceeds {MAX_PLAN_TARGET_FILES}."
        )
    normalized: list[str] = []
    seen: set[str] = set()
    forbidden_targets = {path.casefold() for path in _FORBIDDEN_PLAN_TARGETS}
    for item in raw_targets:
        value = str(item or "").strip().replace("\\", "/")
        if not value:
            raise CandidateTargetContractError("Plan target file is empty.")
        if (
            Path(value).is_absolute()
            or re.match(r"^[A-Za-z]:", value)
            or value.startswith("/")
        ):
            raise CandidateTargetContractError(
                f"Plan target file must be repository-relative: {value}"
            )
        path = PurePosixPath(value)
        parts = path.parts
        if (
            not parts
            or any(part in {"", ".", ".."} for part in parts)
            or value.endswith("/")
            or any(char in value for char in ("*", "?", "\x00"))
        ):
            raise CandidateTargetContractError(
                f"Plan target file is unsafe: {value}"
            )
        canonical = path.as_posix()
        lowered = canonical.casefold()
        if (
            lowered in forbidden_targets
            or any(
                lowered.startswith(prefix.casefold())
                for prefix in _FORBIDDEN_PLAN_TARGET_PREFIXES
            )
        ):
            raise CandidateTargetContractError(
                f"Plan target file is forbidden: {canonical}"
            )
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(canonical)
    if not normalized:
        raise CandidateTargetContractError(
            "Plan did not declare structured target files."
        )
    return normalized


def candidate_target_paths(
    worktree_path: str,
    target_files: list[str],
) -> list[str]:
    """Resolve exact target files inside one candidate worktree."""

    root = Path(worktree_path).resolve()
    paths: list[str] = []
    for target_file in target_files:
        candidate = (root / Path(target_file)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise CandidateTargetContractError(
                f"Plan target file escapes candidate worktree: {target_file}"
            ) from exc
        paths.append(str(candidate))
    return paths


def validate_candidate_changes(
    inspection: dict[str, Any],
    *,
    run_id: str,
    target_files: list[str],
) -> list[str]:
    """Fail closed if candidate Git changes exceed the accepted exact-file set."""

    raw_changes = inspection.get("changedFiles")
    if not isinstance(raw_changes, list):
        return []
    normalized_changes = (
        normalize_target_files(raw_changes) if raw_changes else []
    )
    target_set = {path.casefold() for path in target_files}
    outside = [
        path for path in normalized_changes if path.casefold() not in target_set
    ]
    if outside:
        _record_candidate_boundary_blocked(
            run_id=run_id,
            changed_files=normalized_changes,
            outside_files=outside,
        )
        raise CandidateTargetContractError(
            "Candidate changed files outside planned target files: "
            + ", ".join(outside)
        )
    return normalized_changes


def record_plan_target_contract(
    *,
    run_id: str,
    target_files: list[str],
) -> None:
    """Record the accepted bounded target set without logging prompt content."""

    try:
        record_runtime_scene_event(
            "work_run",
            "planning",
            "self_evolution.autonomous_loop.target_contract_accepted",
            message="Self-evolution plan declared a bounded candidate target contract.",
            outcome="accepted",
            fields={
                "runKind": "self_evolution_autonomous_loop",
                "runId": run_id,
                "targetFileCount": len(target_files),
                "targetFiles": target_files[:MAX_PLAN_TARGET_FILES],
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_candidate_boundary_blocked(
    *,
    run_id: str,
    changed_files: list[str],
    outside_files: list[str],
) -> None:
    try:
        record_runtime_scene_event(
            "work_run",
            "evolving",
            "self_evolution.autonomous_loop.candidate_boundary_blocked",
            message="Candidate changed files outside the host-approved target contract.",
            level="error",
            outcome="blocked",
            fields={
                "runKind": "self_evolution_autonomous_loop",
                "runId": run_id,
                "changedFileCount": len(changed_files),
                "outsideTargetCount": len(outside_files),
                "outsideTargetFiles": outside_files[:MAX_PLAN_TARGET_FILES],
            },
            lifecycle=True,
        )
    except Exception:
        return
