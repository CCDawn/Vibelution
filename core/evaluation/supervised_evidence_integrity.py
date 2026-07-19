from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
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
        "touched_files",
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


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _write_bytes_atomic(path, content)


def _matching_bounded_files(workspace_root: Path, tokens: Set[str]) -> Set[Path]:
    matches: Set[Path] = set()
    allowed_suffixes = {".json", ".jsonl", ".html"}
    for search_root in (workspace_root / "supervised_evolution", workspace_root / "evolution"):
        if not search_root.exists():
            continue
        for path in search_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if any(token in text for token in tokens):
                matches.add(_resolved(path))
    return matches


def _archive_relative_path(source: Path, workspace_root: Path) -> Path:
    try:
        return source.relative_to(workspace_root)
    except ValueError:
        digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:12]
        return Path("external") / digest / source.name


def _filter_jsonl(path: Path, tokens: Set[str]) -> None:
    retained = [
        line
        for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
        if not any(token in line for token in tokens)
    ]
    _write_bytes_atomic(path, "".join(retained).encode("utf-8"))


def _remove_lineage_proposals(path: Path, proposal_ids: Set[str]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        raise ValueError(f"lineage 索引结构无法安全清理: {path}")
    retained_cases: List[Dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            retained_cases.append(case)
            continue
        chain = case.get("chain")
        entries = chain if isinstance(chain, list) else []
        retained_chain = [
            entry
            for entry in entries
            if not (
                isinstance(entry, dict)
                and str(entry.get("proposal_id") or "").strip() in proposal_ids
            )
        ]
        if retained_chain:
            updated = dict(case)
            updated["chain"] = retained_chain
            updated["proposal_count"] = len(retained_chain)
            updated["observation_cycles"] = sum(
                int(entry.get("observation_count") or 0)
                for entry in retained_chain
                if isinstance(entry, dict)
            )
            retained_cases.append(updated)
    if not retained_cases:
        path.unlink()
        return
    payload["cases"] = retained_cases
    payload["case_count"] = len(retained_cases)
    payload["proposal_count"] = sum(
        len(case.get("chain") or []) for case in retained_cases if isinstance(case, dict)
    )
    _write_json_atomic(path, payload)


def archive_supervised_test_contamination(
    *,
    evidence_root: Path,
    session_ids: Iterable[str],
    archive_root: Path,
) -> Dict[str, Any]:
    """Archive exact bytes, then remove only strongly verified test contamination."""

    root = _resolved(evidence_root)
    workspace_root = root.parent
    archive = _resolved(archive_root)
    requested = {str(session_id).strip() for session_id in session_ids if str(session_id).strip()}
    if not requested:
        raise ValueError("至少需要一个 session_id")
    if archive.exists():
        raise FileExistsError(f"归档目录已存在，拒绝覆盖: {archive}")

    preview = build_supervised_evidence_preview(root)
    sessions_by_id = {session["session_id"]: session for session in preview["sessions"]}
    missing = sorted(requested - sessions_by_id.keys())
    if missing:
        raise ValueError(f"未找到监督进化会话: {', '.join(missing)}")
    unverified = sorted(
        session_id
        for session_id in requested
        if sessions_by_id[session_id]["classification"] != "test_contamination"
    )
    if unverified:
        raise ValueError(f"会话未被强证据确认为测试污染: {', '.join(unverified)}")

    decision_payloads: Dict[str, Dict[str, Any]] = {}
    proposal_ids: Set[str] = set()
    dedicated_paths: Set[Path] = set()
    for session_id in requested:
        decision_path = Path(sessions_by_id[session_id]["decision_path"])
        payload = json.loads(decision_path.read_text(encoding="utf-8"))
        decision_payloads[session_id] = payload
        dedicated_paths.add(_resolved(decision_path))
        dedicated_paths.add(_resolved(root / "policy" / f"{session_id}.json"))
        session_dir = root / "sessions" / session_id
        if session_dir.exists():
            dedicated_paths.update(_resolved(path) for path in session_dir.rglob("*") if path.is_file())
        for key, value in _walk_values(payload):
            if key == "proposal_id" and isinstance(value, str) and value.strip():
                proposal_ids.add(value.strip())
        for path in _safe_reference_paths(
            payload,
            allowed_roots=(root, workspace_root / "evolution"),
        ):
            if path.parent == workspace_root / "evolution" / "proposals" and path.name != "lineage_index.json":
                dedicated_paths.add(path)

    tokens = set(requested) | proposal_ids
    matched_paths = _matching_bounded_files(workspace_root, tokens)
    shared_jsonl = {
        _resolved(root / "history.jsonl"),
        _resolved(root / "policy" / "candidate_observation_pool.jsonl"),
        _resolved(workspace_root / "evolution" / "audit.jsonl"),
    }
    lineage_path = _resolved(workspace_root / "evolution" / "proposals" / "lineage_index.json")
    dashboard_path = _resolved(root / "dashboard" / "index.html")
    supported_paths = dedicated_paths | shared_jsonl | {lineage_path, dashboard_path}
    unsupported = sorted(matched_paths - supported_paths, key=lambda path: str(path).lower())
    if unsupported:
        raise ValueError(
            "发现未分类的关联证据，拒绝自动归档: " + ", ".join(str(path) for path in unsupported)
        )
    affected_paths = sorted(
        (matched_paths | {path for path in dedicated_paths if path.exists()}),
        key=lambda path: str(path).lower(),
    )

    archive.mkdir(parents=True)
    files_root = archive / "files"
    records: List[Dict[str, Any]] = []
    for source in affected_paths:
        relative = _archive_relative_path(source, workspace_root)
        destination = files_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        archive_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
        if source_hash != archive_hash:
            raise OSError(f"归档哈希校验失败: {source}")
        records.append(
            {
                "source_path": str(source),
                "archive_path": str(destination),
                "relative_path": str(relative),
                "size_bytes": source.stat().st_size,
                "sha256": source_hash,
            }
        )
    manifest = {
        "schema_version": 1,
        "status": "prepared",
        "operation": "archive_supervised_test_contamination",
        "evidence_root": str(root),
        "session_ids": sorted(requested),
        "proposal_ids": sorted(proposal_ids),
        "files": records,
    }
    _write_json_atomic(archive / "manifest.json", manifest)

    for path in sorted(shared_jsonl & matched_paths, key=lambda item: str(item).lower()):
        _filter_jsonl(path, tokens)
    if lineage_path in matched_paths:
        _remove_lineage_proposals(lineage_path, proposal_ids)
    for path in sorted(dedicated_paths, key=lambda item: str(item).lower()):
        if path.exists():
            path.unlink()
    if dashboard_path in matched_paths and dashboard_path.exists():
        dashboard_path.unlink()
    for session_id in requested:
        session_dir = root / "sessions" / session_id
        if session_dir.exists():
            try:
                session_dir.rmdir()
            except OSError:
                pass

    completion = {
        "schema_version": 1,
        "status": "completed",
        "manifest_path": str(archive / "manifest.json"),
        "session_ids": sorted(requested),
        "archived_files": len(records),
        "remaining_preview": build_supervised_evidence_preview(root)["summary"],
    }
    _write_json_atomic(archive / "completion.json", completion)
    return completion
