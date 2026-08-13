"""Formal store for Ledger System-node workflow artifacts.

Authority for ``run_artifacts``, ``research_result_package``, ``smoke_evidence``
(and related experiment kinds). Never uses ``data/domain_artifacts``.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.infrastructure.path_containment import PROJECT_ROOT

from .atomic_fs import CorruptWorkflowStoreError, atomic_write_text
from .human_gate_artifacts import canonical_sha256

_LOCK = threading.RLock()

_SUPPORTED_KINDS = frozenset(
    {
        "run_artifacts",
        "research_result_package",
        "smoke_evidence",
        "smoke_release",
        "frozen_protocol",
        "evaluation_report",
        "hypothesis_set",
        "protocol_draft",
        "protocol_review_report",
    }
)


def _root() -> Path:
    return Path(PROJECT_ROOT)


def _path(team_id: str, kind: str) -> Path:
    team = str(team_id or "").strip()
    kind_key = str(kind or "").strip()
    if not team or kind_key not in _SUPPORTED_KINDS:
        raise ValueError(f"unsupported workflow artifact kind/team: {kind_key}/{team}")
    return _root() / "workspace" / "teams" / team / "workflow_artifacts" / f"{kind_key}.jsonl"


class WorkflowArtifactConflictError(RuntimeError):
    """Raised when an immutable artifact identity is reused with new content."""


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            item = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CorruptWorkflowStoreError(
                path,
                f"invalid JSON at line {line_number}",
                cause=exc,
            ) from exc
        if not isinstance(item, dict):
            raise CorruptWorkflowStoreError(
                path,
                f"record at line {line_number} is not an object",
            )
        rows.append(item)
    return rows


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in rows
    )
    atomic_write_text(path, payload)


def put_workflow_artifact(
    team_id: str,
    *,
    kind: str,
    workflow_run_id: str,
    payload: dict[str, Any],
    source_collection_run_id: str = "",
    artifact_identity: str = "",
) -> dict[str, Any]:
    """Append an immutable scoped artifact; exact replay is idempotent."""
    team = str(team_id or "").strip()
    kind_key = str(kind or "").strip()
    run_id = str(workflow_run_id or "").strip()
    sc_run = str(source_collection_run_id or "").strip()
    if not team or not run_id or kind_key not in _SUPPORTED_KINDS:
        raise ValueError("teamId, workflowRunId and supported kind are required")
    if not isinstance(payload, dict) or not payload:
        raise ValueError("workflow artifact payload must be a non-empty object")
    content_hash = canonical_sha256(payload)
    record_id = str(artifact_identity or "").strip() or content_hash
    record = {
        "recordId": record_id,
        "teamId": team,
        "kind": kind_key,
        "workflowRunId": run_id,
        "sourceCollectionRunId": sc_run or run_id,
        "contentHash": content_hash,
        "payload": payload,
        "updatedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    path = _path(team, kind_key)
    with _LOCK:
        rows = _read(path)
        for item in rows:
            if (
                str(item.get("workflowRunId") or "") == run_id
                and str(item.get("kind") or "") == kind_key
                and str(item.get("recordId") or item.get("contentHash") or "") == record_id
            ):
                if str(item.get("contentHash") or "") != content_hash:
                    raise WorkflowArtifactConflictError(
                        f"workflow artifact identity conflict: {kind_key}/{run_id}/{record_id}"
                    )
                return item
        rows.append(record)
        _write(path, rows)
    return record


def list_workflow_artifacts(
    team_id: str,
    *,
    kind: str,
    workflow_run_id: str = "",
    source_collection_run_id: str = "",
) -> list[dict[str, Any]]:
    team = str(team_id or "").strip()
    kind_key = str(kind or "").strip()
    if not team or kind_key not in _SUPPORTED_KINDS:
        return []
    path = _path(team, kind_key)
    with _LOCK:
        rows = _read(path)
    scoped: list[dict[str, Any]] = []
    want_wf = str(workflow_run_id or "").strip()
    want_sc = str(source_collection_run_id or "").strip()
    for item in rows:
        if str(item.get("kind") or "") != kind_key:
            continue
        item_wf = str(item.get("workflowRunId") or "").strip()
        item_sc = str(item.get("sourceCollectionRunId") or "").strip()
        if not item_wf and not item_sc:
            continue
        if want_wf and item_wf != want_wf:
            continue
        if want_sc and item_sc != want_sc:
            continue
        scoped.append(item)
    return scoped


def load_workflow_artifact_payload(
    kind: str,
    *,
    team_id: str,
    authority_run_id: str,
    workflow_run_id: str = "",
    content_hash: str = "",
) -> dict[str, Any] | None:
    """Return the latest scoped payload envelope for hashing/read-back.

    The envelope shape is stable and is what ``collect_required_artifact_refs`` /
    ``read_domain_artifact`` hash — do not embed a precomputed contentHash.
    """
    kind_key = str(kind or "").strip()
    team = str(team_id or "").strip()
    authority = str(authority_run_id or "").strip()
    workflow = str(workflow_run_id or "").strip()
    if not kind_key or not team or not authority:
        return None
    rows = list_workflow_artifacts(
        team,
        kind=kind_key,
        workflow_run_id=workflow,
        source_collection_run_id=authority,
    )
    if not rows:
        return None
    expected_hash = str(content_hash or "").strip()
    for latest in reversed(rows):
        payload = latest.get("payload")
        if not isinstance(payload, dict) or not payload:
            continue
        envelope = {
            "teamId": team,
            "kind": kind_key,
            "workflowRunId": str(latest.get("workflowRunId") or workflow or authority),
            "sourceCollectionRunId": str(latest.get("sourceCollectionRunId") or authority),
            "payload": payload,
        }
        if expected_hash and canonical_sha256(envelope) != expected_hash:
            continue
        return envelope
    return None
