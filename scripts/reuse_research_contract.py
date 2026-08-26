#!/usr/bin/env python3
"""Task-scoped, locally verifiable evidence for mature-project reuse research."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from core.web.services import github_project_library_service as github_library


SCHEMA_VERSION = 1
DECISIONS = frozenset({"REUSE", "ADAPT", "REFERENCE_ONLY", "BUILD_IN_HOUSE"})
LOCAL_REUSE_DECISIONS = frozenset({"REUSE", "ADAPT", "REPLACE", "UNUSED"})
UNVERIFIED_LICENSES = frozenset({"", "NOASSERTION", "OTHER"})
IMPLEMENTATION_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".css",
        ".go",
        ".h",
        ".html",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".mjs",
        ".py",
        ".pyi",
        ".rs",
        ".scss",
        ".sql",
        ".ts",
        ".tsx",
        ".vue",
    }
)
EXEMPT_PREFIXES = ("docs/", "tests/", "test/", "fixtures/", "examples/")
MAX_CANDIDATES = 5
MAX_OWNER_PATHS = 8
MAX_LIST_ITEMS = 8
MAX_SHORT_TEXT = 240
MAX_LONG_TEXT = 800
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+$")
SECRET_RE = re.compile(
    r"(?:\b(?:api[_-]?key|token|secret|password)\b\s*[:=]|\bsk-[A-Za-z0-9_-]{12,})",
    re.IGNORECASE,
)


class ReuseResearchEvidenceError(ValueError):
    """Raised when reuse-research evidence is missing, unsafe, or unverifiable."""


def normalize_path(value: str) -> str:
    return str(value or "").replace("\\", "/").removeprefix("./")


def reuse_research_required(files: Sequence[str]) -> bool:
    """Require evidence when the task changes implementation-bearing files."""

    for raw in files:
        path = normalize_path(raw).lower()
        if not path or path.startswith(EXEMPT_PREFIXES):
            continue
        if Path(path).suffix in IMPLEMENTATION_SUFFIXES:
            return True
    return False


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.longpaths=true", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _git_text(root: Path, *args: str) -> str:
    completed = _git(root, *args)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).splitlines()
        raise ReuseResearchEvidenceError(detail[0][:300] if detail else "Git evidence check failed.")
    return completed.stdout.strip()


def _repository_root(root: Path | str) -> Path:
    candidate = Path(root).expanduser().resolve()
    resolved = _git_text(candidate, "rev-parse", "--show-toplevel")
    return Path(resolved).resolve()


def _branch(root: Path) -> str:
    return _git_text(root, "rev-parse", "--abbrev-ref", "HEAD")


def _task_id(branch: str) -> str:
    if not branch.startswith("codex/") or branch == "codex/":
        raise ReuseResearchEvidenceError("Reuse research must be recorded on a codex/* task branch.")
    return branch.removeprefix("codex/")


def _git_common_dir(root: Path) -> Path:
    raw = Path(_git_text(root, "rev-parse", "--git-common-dir"))
    return (raw if raw.is_absolute() else root / raw).resolve()


def evidence_path(root: Path | str, task_id: str) -> Path:
    repository = _repository_root(root)
    safe_task_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(task_id or "")).strip("-")
    if not safe_task_id:
        raise ReuseResearchEvidenceError("taskId is required.")
    directory = _git_common_dir(repository) / "vibelution-cache" / "reuse_research"
    return directory / f"{safe_task_id}.json"


def _text(value: str, *, field: str, limit: int, required: bool = True) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if required and not normalized:
        raise ReuseResearchEvidenceError(f"{field} is required.")
    if len(normalized) > limit:
        raise ReuseResearchEvidenceError(f"{field} exceeds {limit} characters.")
    if SECRET_RE.search(normalized):
        raise ReuseResearchEvidenceError(f"{field} must not contain secrets.")
    return normalized


def _text_list(
    values: Iterable[str],
    *,
    field: str,
    limit: int = MAX_LIST_ITEMS,
    required: bool = True,
) -> list[str]:
    normalized = [_text(value, field=field, limit=MAX_LONG_TEXT) for value in values]
    normalized = list(dict.fromkeys(normalized))
    if required and not normalized:
        raise ReuseResearchEvidenceError(f"{field} requires at least one item.")
    if len(normalized) > limit:
        raise ReuseResearchEvidenceError(f"{field} exceeds {limit} items.")
    return normalized


def _owner_paths(root: Path, values: Iterable[str]) -> list[str]:
    owners = _text_list(values, field="localOwnerPaths", limit=MAX_OWNER_PATHS)
    normalized: list[str] = []
    for owner in owners:
        path = normalize_path(owner)
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ReuseResearchEvidenceError("localOwnerPaths must stay inside the task repository.")
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ReuseResearchEvidenceError("localOwnerPaths must stay inside the task repository.") from exc
        if not resolved.exists():
            raise ReuseResearchEvidenceError(f"Local owner does not exist: {path}")
        normalized.append(path)
    return normalized


def _read_registry(project_root: Path) -> tuple[Path, dict[str, Any]]:
    library_root = github_library.github_project_library_root(project_root=project_root)
    registry_path = library_root / github_library.REGISTRY_NAME
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReuseResearchEvidenceError(f"GitHub project registry is unavailable: {registry_path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("projects"), list):
        raise ReuseResearchEvidenceError("GitHub project registry has an invalid schema.")
    return library_root, payload


def _safe_repo_path(library_root: Path, project_id: str) -> Path:
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise ReuseResearchEvidenceError(f"Invalid candidate projectId: {project_id}")
    repos_root = (library_root / github_library.REPOS_DIRNAME).resolve()
    repo = (repos_root / project_id).resolve()
    if repo.parent != repos_root:
        raise ReuseResearchEvidenceError("Candidate path escapes the GitHub project library.")
    return repo


def _candidate_records(
    project_root: Path,
    candidate_ids: Iterable[str],
    *,
    decision: str,
    risk_notes: Sequence[str],
) -> tuple[list[dict[str, str]], str]:
    ids = list(dict.fromkeys(_text(value, field="candidateIds", limit=MAX_SHORT_TEXT) for value in candidate_ids))
    if not ids:
        raise ReuseResearchEvidenceError("candidateIds requires at least one local mature-project candidate.")
    if len(ids) > MAX_CANDIDATES:
        raise ReuseResearchEvidenceError(f"candidateIds exceeds {MAX_CANDIDATES} items.")
    library_root, registry = _read_registry(project_root)
    projects = {
        str(item.get("projectId") or ""): item
        for item in registry["projects"]
        if isinstance(item, dict)
    }
    records: list[dict[str, str]] = []
    for project_id in ids:
        project = projects.get(project_id)
        if project is None:
            raise ReuseResearchEvidenceError(
                f"Candidate is not in the local GitHub project library: {project_id}"
            )
        if str(project.get("status") or "") != "ready":
            raise ReuseResearchEvidenceError(f"Candidate is not ready: {project_id}")
        head = str(project.get("headSha") or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", head):
            raise ReuseResearchEvidenceError(f"Candidate HEAD is invalid: {project_id}")
        license_id = str(project.get("license") or "").strip()
        if license_id.upper() in UNVERIFIED_LICENSES and decision in {"REUSE", "ADAPT"}:
            raise ReuseResearchEvidenceError(
                f"Candidate license is unverified for {decision}: {project_id}"
            )
        if license_id.upper() in UNVERIFIED_LICENSES and not risk_notes:
            raise ReuseResearchEvidenceError(
                f"Unverified candidate license requires an explicit risk note: {project_id}"
            )
        repo = _safe_repo_path(library_root, project_id)
        if not repo.is_dir():
            raise ReuseResearchEvidenceError(f"Candidate clone is missing: {project_id}")
        actual_head = _git_text(repo, "rev-parse", "HEAD")
        if actual_head != head:
            raise ReuseResearchEvidenceError(f"Candidate HEAD drifted from registry: {project_id}")
        if _git_text(repo, "status", "--porcelain"):
            raise ReuseResearchEvidenceError(f"Candidate clone is dirty: {project_id}")
        records.append(
            {
                "projectId": project_id,
                "fullName": str(project.get("fullName") or "").strip(),
                "githubUrl": str(project.get("githubUrl") or "").strip(),
                "localPath": f"repos/{project_id}",
                "headSha": head,
                "license": license_id,
                "status": "ready",
            }
        )
    return records, str(registry.get("updatedAt") or "")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def record_evidence(
    root: Path | str,
    *,
    feature: str,
    decision: str,
    local_reuse_decision: str,
    local_owner_paths: Sequence[str],
    candidate_ids: Sequence[str],
    borrowed_slices: Sequence[str],
    rejected_alternatives: Sequence[str],
    reason: str,
    implementation_boundary: str,
    verification_strategy: str,
    risk_notes: Sequence[str],
    project_root: Path | str | None = None,
) -> dict[str, object]:
    repository = _repository_root(root)
    branch = _branch(repository)
    task_id = _task_id(branch)
    normalized_decision = str(decision or "").strip().upper()
    if normalized_decision not in DECISIONS:
        raise ReuseResearchEvidenceError(f"Unknown reuse decision: {decision}")
    normalized_local_decision = str(local_reuse_decision or "").strip().upper()
    if normalized_local_decision not in LOCAL_REUSE_DECISIONS:
        raise ReuseResearchEvidenceError(f"Unknown local reuse decision: {local_reuse_decision}")
    risks = _text_list(risk_notes, field="riskNotes", required=False)
    active_project_root = Path(project_root or repository).expanduser().resolve()
    candidates, registry_updated_at = _candidate_records(
        active_project_root,
        candidate_ids,
        decision=normalized_decision,
        risk_notes=risks,
    )
    payload: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "taskId": task_id,
        "branch": branch,
        "feature": _text(feature, field="feature", limit=MAX_SHORT_TEXT),
        "decision": normalized_decision,
        "localReuseDecision": normalized_local_decision,
        "localOwnerPaths": _owner_paths(repository, local_owner_paths),
        "candidates": candidates,
        "borrowedSlices": _text_list(borrowed_slices, field="borrowedSlices"),
        "rejectedAlternatives": _text_list(rejected_alternatives, field="rejectedAlternatives"),
        "reason": _text(reason, field="reason", limit=MAX_LONG_TEXT),
        "implementationBoundary": _text(
            implementation_boundary,
            field="implementationBoundary",
            limit=MAX_LONG_TEXT,
        ),
        "verificationStrategy": _text(
            verification_strategy,
            field="verificationStrategy",
            limit=MAX_LONG_TEXT,
        ),
        "riskNotes": risks,
        "sourceRegistryUpdatedAt": registry_updated_at,
        "recordedAt": _utc_now(),
    }
    validate_evidence_payload(payload, repository, task_id=task_id, branch=branch)
    path = evidence_path(repository, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return payload


def validate_evidence_payload(
    payload: object,
    root: Path | str,
    *,
    task_id: str,
    branch: str,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ReuseResearchEvidenceError("Reuse research evidence must be a JSON object.")
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise ReuseResearchEvidenceError("Reuse research evidence schemaVersion is invalid.")
    if payload.get("taskId") != task_id or payload.get("branch") != branch:
        raise ReuseResearchEvidenceError("Reuse research evidence is bound to another task branch.")
    decision = str(payload.get("decision") or "")
    if decision not in DECISIONS:
        raise ReuseResearchEvidenceError("Reuse research decision is invalid.")
    local_decision = str(payload.get("localReuseDecision") or "")
    if local_decision not in LOCAL_REUSE_DECISIONS:
        raise ReuseResearchEvidenceError("Local reuse decision is invalid.")
    repository = _repository_root(root)
    _owner_paths(repository, payload.get("localOwnerPaths") or [])
    for field in ("borrowedSlices", "rejectedAlternatives"):
        _text_list(payload.get(field) or [], field=field)
    _text_list(payload.get("riskNotes") or [], field="riskNotes", required=False)
    for field, limit in (
        ("feature", MAX_SHORT_TEXT),
        ("reason", MAX_LONG_TEXT),
        ("implementationBoundary", MAX_LONG_TEXT),
        ("verificationStrategy", MAX_LONG_TEXT),
    ):
        _text(str(payload.get(field) or ""), field=field, limit=limit)
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_CANDIDATES:
        raise ReuseResearchEvidenceError("Reuse research candidates must contain 1-5 entries.")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ReuseResearchEvidenceError("Reuse research candidate must be an object.")
        project_id = str(candidate.get("projectId") or "")
        if not PROJECT_ID_RE.fullmatch(project_id):
            raise ReuseResearchEvidenceError("Reuse research candidate projectId is invalid.")
        if candidate.get("localPath") != f"repos/{project_id}":
            raise ReuseResearchEvidenceError("Reuse research candidate localPath is invalid.")
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", str(candidate.get("headSha") or "")):
            raise ReuseResearchEvidenceError("Reuse research candidate HEAD is invalid.")
        if candidate.get("status") != "ready":
            raise ReuseResearchEvidenceError("Reuse research candidate is not ready.")
        license_id = str(candidate.get("license") or "")
        if license_id.upper() in UNVERIFIED_LICENSES and decision in {"REUSE", "ADAPT"}:
            raise ReuseResearchEvidenceError("Reuse research candidate license is unverified.")
    return payload


def load_and_validate_evidence(
    root: Path | str,
    *,
    task_id: str,
    branch: str,
    project_root: Path | str | None = None,
) -> dict[str, object] | None:
    repository = _repository_root(root)
    path = evidence_path(repository, task_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReuseResearchEvidenceError("Reuse research evidence is unreadable.") from exc
    validated = validate_evidence_payload(payload, repository, task_id=task_id, branch=branch)
    active_project_root = Path(project_root or repository).expanduser().resolve()
    candidate_ids = [str(item["projectId"]) for item in validated["candidates"]]
    live_candidates, _ = _candidate_records(
        active_project_root,
        candidate_ids,
        decision=str(validated["decision"]),
        risk_notes=list(validated.get("riskNotes") or []),
    )
    if live_candidates != validated["candidates"]:
        raise ReuseResearchEvidenceError("Candidate metadata or HEAD drifted from recorded evidence.")
    return validated


def validate_manifest_snapshot(
    payload: object,
    root: Path | str,
    *,
    project_root: Path | str | None = None,
) -> dict[str, object]:
    repository = _repository_root(root)
    if not isinstance(payload, dict):
        raise ReuseResearchEvidenceError("Reuse research manifest snapshot must be an object.")
    task_id = str(payload.get("taskId") or "")
    branch = str(payload.get("branch") or "")
    validated = validate_evidence_payload(payload, repository, task_id=task_id, branch=branch)
    active_project_root = Path(project_root or repository).expanduser().resolve()
    library_root = github_library.github_project_library_root(project_root=active_project_root)
    for candidate in validated["candidates"]:
        project_id = str(candidate["projectId"])
        repo = _safe_repo_path(library_root, project_id)
        if not repo.is_dir():
            raise ReuseResearchEvidenceError(f"Candidate clone is missing: {project_id}")
        completed = _git(repo, "cat-file", "-e", f"{candidate['headSha']}^{{commit}}")
        if completed.returncode != 0:
            raise ReuseResearchEvidenceError(
                f"Candidate commit is unavailable for manifest verification: {project_id}"
            )
    return validated


__all__ = [
    "DECISIONS",
    "LOCAL_REUSE_DECISIONS",
    "ReuseResearchEvidenceError",
    "evidence_path",
    "load_and_validate_evidence",
    "record_evidence",
    "reuse_research_required",
    "validate_evidence_payload",
    "validate_manifest_snapshot",
]
