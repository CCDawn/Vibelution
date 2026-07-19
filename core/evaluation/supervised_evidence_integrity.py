from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from core.infrastructure import developer_sandbox


class FormalSupervisedEvidenceWriteBlocked(RuntimeError):
    """Raised when a test process targets the operator's formal evidence store."""


def _resolved(path: Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(_resolved(left))) == os.path.normcase(str(_resolved(right)))


def _is_test_process(environ: Mapping[str, str]) -> bool:
    return bool(environ.get("PYTEST_CURRENT_TEST") or environ.get("PYTEST_XDIST_WORKER"))


def _looks_like_pytest_isolation(path: Path) -> bool:
    normalized = str(_resolved(path)).replace("\\", "/").lower()
    return "/pytest-of-" in normalized or bool(re.search(r"/pytest-\d+/", normalized))


def assert_supervised_evidence_write_allowed(
    *,
    project_root: Path,
    evidence_root: Path,
    formal_evidence_root: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> None:
    """Fail closed when pytest would write supervised evidence to the formal store."""

    active_environ = os.environ if environ is None else environ
    if not _is_test_process(active_environ):
        return
    formal_root_was_explicit = formal_evidence_root is not None
    formal_root = (
        _resolved(formal_evidence_root)
        if formal_root_was_explicit
        else developer_sandbox.formal_workspace_path(project_root, "supervised_evolution")
    )
    # Test fixtures may deliberately redirect the workspace resolver itself into
    # pytest's unique temp tree. That is isolated evidence, not the operator store.
    if not formal_root_was_explicit and _looks_like_pytest_isolation(evidence_root):
        return
    if _same_path(evidence_root, formal_root):
        raise FormalSupervisedEvidenceWriteBlocked(
            "pytest 进程禁止写入正式监督进化证据区；请启用隔离的 developer sandbox/workspace"
        )


def _walk_values(value: Any, *, key: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            yield from _walk_values(child_value, key=str(child_key))
    elif isinstance(value, list):
        for child_value in value:
            yield from _walk_values(child_value, key=key)
    else:
        yield key, value


def _signals(payload: Dict[str, Any]) -> tuple[List[str], List[str]]:
    strong: Set[str] = set()
    weak: Set[str] = set()
    for key, value in _walk_values(payload):
        text = str(value or "").strip()
        normalized = text.replace("\\", "/").lower()
        if key in {"bundle_path", "report_path"} and (
            "/pytest-of-" in normalized or re.search(r"/pytest-\d+/", normalized)
        ):
            strong.add("pytest_temporary_path")
        if key == "creator_version" and normalized.startswith("pytest"):
            strong.add("pytest_creator_version")
        if "worktree_path" in key and (
            "/.tmp/" in normalized or normalized.startswith("c:/repo/")
        ):
            strong.add("synthetic_worktree_path")
        if key == "generation_reason" and "test" in normalized:
            weak.add("test_generation_reason")
    return sorted(strong), sorted(weak)


def _is_within(path: Path, root: Path) -> bool:
    try:
        _resolved(path).relative_to(_resolved(root))
        return True
    except ValueError:
        return False


def _safe_reference_paths(payload: Dict[str, Any], allowed_roots: Iterable[Path]) -> Set[Path]:
    accepted: Set[Path] = set()
    path_keys = {
        "policy_record_path",
        "proposal_path",
        "proposal_paths",
        "lineage_index_path",
        "report_path",
        "baseline_report_path",
        "candidate_report_path",
    }
    roots = tuple(_resolved(root) for root in allowed_roots)
    for key, value in _walk_values(payload):
        if key not in path_keys or not isinstance(value, str) or not value.strip():
            continue
        candidate = _resolved(Path(value))
        if any(_is_within(candidate, root) for root in roots):
            accepted.add(candidate)
    return accepted


def _contains_session_id(path: Path, session_id: str) -> bool:
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            return any(session_id in line for line in handle)
    except (OSError, UnicodeError):
        return False


def _path_record(path: Path) -> Dict[str, Any]:
    resolved = _resolved(path)
    exists = resolved.exists()
    record: Dict[str, Any] = {
        "path": str(resolved),
        "exists": exists,
        "kind": "directory" if exists and resolved.is_dir() else "file",
        "size_bytes": None,
        "sha256": None,
    }
    if exists and resolved.is_file():
        data = resolved.read_bytes()
        record["size_bytes"] = len(data)
        record["sha256"] = hashlib.sha256(data).hexdigest()
    return record


def build_supervised_evidence_preview(evidence_root: Path) -> Dict[str, Any]:
    """Build a deterministic, read-only contamination and association report."""

    root = _resolved(evidence_root)
    decisions_dir = root / "decisions"
    sessions: List[Dict[str, Any]] = []
    for decision_path in sorted(decisions_dir.glob("*.json")) if decisions_dir.exists() else []:
        try:
            payload = json.loads(decision_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        session_id = str(payload.get("session_id") or decision_path.stem).strip()
        strong, weak = _signals(payload)
        classification = "test_contamination" if len(strong) >= 2 else "unverified"
        associated: Set[Path] = {decision_path}
        session_dir = root / "sessions" / session_id
        if session_dir.exists():
            associated.update(path for path in session_dir.rglob("*") if path.is_file())
        policy_path = root / "policy" / f"{session_id}.json"
        if policy_path.exists():
            associated.add(policy_path)
        for jsonl_path in (
            root / "history.jsonl",
            root / "policy" / "candidate_observation_pool.jsonl",
        ):
            if _contains_session_id(jsonl_path, session_id):
                associated.add(jsonl_path)
        associated.update(
            _safe_reference_paths(
                payload,
                allowed_roots=(root, root.parent / "evolution"),
            )
        )
        sessions.append(
            {
                "session_id": session_id,
                "decision_path": str(_resolved(decision_path)),
                "classification": classification,
                "strong_signals": strong,
                "weak_signals": weak,
                "associated_paths": [
                    _path_record(path) for path in sorted(associated, key=lambda item: str(item).lower())
                ],
            }
        )
    return {
        "mode": "read_only_preview",
        "evidence_root": str(root),
        "summary": {
            "total_sessions": len(sessions),
            "contaminated_sessions": sum(
                session["classification"] == "test_contamination" for session in sessions
            ),
            "unverified_sessions": sum(session["classification"] == "unverified" for session in sessions),
        },
        "sessions": sessions,
    }
