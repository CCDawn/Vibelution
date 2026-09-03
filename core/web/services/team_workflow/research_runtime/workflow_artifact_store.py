"""Formal store for Ledger System-node workflow artifacts.

Authority for ``run_artifacts``, ``research_result_package``, ``smoke_evidence``
(and related experiment kinds). Never uses ``data/domain_artifacts``.
"""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.infrastructure.path_containment import PROJECT_ROOT
from vibelution_storage import resolve_project_workspace_home

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
        "hypothesis_fragment",
        "hypothesis_set",
        "research_plan",
        "stage1_research_plan",
        "competition_alignment",
        "stage_one_completion_manifest",
        "protocol_draft",
        "protocol_review_report",
        "iteration_decision",
        "version_governance_record",
        "delivery_orchestration_result",
        "problem_understanding",
        "dimension_reviews",
        "feedback_iterations",
        "review_independence",
        "review_disagreement",
        "evolution_lineage",
        "candidate_screening",
        "core_hypothesis_coherence",
    }
)


def _root() -> Path:
    return Path(PROJECT_ROOT)


def _path(team_id: str, kind: str) -> Path:
    team = str(team_id or "").strip()
    kind_key = str(kind or "").strip()
    if not team or kind_key not in _SUPPORTED_KINDS:
        raise ValueError(f"unsupported workflow artifact kind/team: {kind_key}/{team}")
    return resolve_project_workspace_home(_root()) / "teams" / team / "workflow_artifacts" / f"{kind_key}.jsonl"


# The stage-one closure writers embed the human gate / model receipts as new
# append-only rows whose identity derives from the base row they upgrade
# (``<baseRecordId>:human-gate`` / ``<baseRecordId>:model-receipts``).  The
# read-back below merges those authority rows into the base payload so every
# consumer (refs collection, adapter verify, stage-one closeout) reads ONE
# payload that carries the embedded authorities, even when another row was
# appended after the embedding.  Writers deliberately read the raw rows via
# ``list_workflow_artifacts`` and must never see this merge.
_HYPOTHESIS_SET_AUTHORITY_KEYS: dict[str, str] = {
    ":human-gate": "human_gate",
    ":model-receipts": "modelInvocationReceipts",
}


def _hypothesis_set_row_scope(row: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("workflowRunId") or "").strip(),
        str(row.get("sourceCollectionRunId") or "").strip(),
    )


def merge_hypothesis_set_authority_payload(
    payload: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    base_row: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge ``:human-gate`` / ``:model-receipts`` sub-rows into a base payload.

    Only sub-rows whose identity derives from the traversed row's ``recordId``
    AND whose scope (workflowRunId + sourceCollectionRunId) matches the base
    row exactly are merged, and only into keys the payload does not already
    carry (idempotent: base keys win, replay merges are no-ops).  The writers
    chain identities (gate row → receipts row), so the merge follows the same
    identity chain.  The input payload is never mutated; a plain dict copy is
    returned.
    """

    merged = dict(payload)
    base_id = str(base_row.get("recordId") or "").strip()
    if not base_id:
        return merged
    base_scope = _hypothesis_set_row_scope(base_row)
    index = {
        str(row.get("recordId") or "").strip(): row
        for row in rows
        if str(row.get("recordId") or "").strip()
    }
    frontier = [base_id]
    seen = {base_id}
    while frontier:
        next_frontier: list[str] = []
        for current_id in frontier:
            for suffix, key in _HYPOTHESIS_SET_AUTHORITY_KEYS.items():
                if key in merged:
                    continue
                row = index.get(f"{current_id}{suffix}")
                if row is None:
                    continue
                # Scope drift (e.g. a re-scoped replay) disqualifies the
                # sub-row: its authority was bound to a different run identity.
                if _hypothesis_set_row_scope(row) != base_scope:
                    continue
                row_payload = row.get("payload")
                value = (
                    row_payload.get(key) if isinstance(row_payload, Mapping) else None
                )
                if isinstance(value, Mapping) and value:
                    merged[key] = dict(value)
                elif isinstance(value, list) and value:
                    merged[key] = list(value)
                sub_id = str(row.get("recordId") or "").strip()
                if sub_id not in seen:
                    seen.add(sub_id)
                    next_frontier.append(sub_id)
        frontier = next_frontier
    return merged


class WorkflowArtifactConflictError(RuntimeError):
    """Raised when an immutable artifact identity is reused with new content."""


class WorkflowArtifactResetError(RuntimeError):
    """Base error for the governed, reversible workflow-artifact reset port."""


class WorkflowArtifactResetValidationError(WorkflowArtifactResetError):
    """Raised when team/reset scope or an artifact manifest is not trustworthy."""


class WorkflowArtifactResetConflictError(WorkflowArtifactResetError):
    """Raised when a reset identity or staged record conflicts with live data."""


class WorkflowArtifactResetStateError(WorkflowArtifactResetError):
    """Raised when a reset operation is requested in an invalid lifecycle state."""


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
    record_id: str = "",
) -> dict[str, Any] | None:
    """Return the latest scoped payload envelope for hashing/read-back.

    The envelope shape is stable and is what ``collect_required_artifact_refs`` /
    ``read_domain_artifact`` hash — do not embed a precomputed contentHash.
    ``record_id`` optionally pins the read to one immutable artifact identity
    instead of the latest record in scope.
    """
    kind_key = str(kind or "").strip()
    team = str(team_id or "").strip()
    authority = str(authority_run_id or "").strip()
    workflow = str(workflow_run_id or "").strip()
    wanted_record = str(record_id or "").strip()
    if not kind_key or not team or not authority:
        return None
    rows = list_workflow_artifacts(
        team,
        kind=kind_key,
        workflow_run_id=workflow,
        source_collection_run_id=authority,
    )
    # Sub-row lookup stays over the full scope so a pinned base read still
    # finds its ``:human-gate`` / ``:model-receipts`` authority rows.
    scoped_rows = list(rows)
    if wanted_record:
        rows = [
            row
            for row in rows
            if str(row.get("recordId") or "") == wanted_record
        ]
    if not rows:
        return None
    expected_hash = str(content_hash or "").strip()
    for latest in reversed(rows):
        payload = latest.get("payload")
        if not isinstance(payload, dict) or not payload:
            continue
        if kind_key == "hypothesis_set":
            payload = merge_hypothesis_set_authority_payload(
                payload, scoped_rows, latest
            )
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


# ---------------------------------------------------------------------------
# Governed, reversible reset port
# ---------------------------------------------------------------------------

# The reset service owns the cross-store transaction.  This store owns only
# its own JSONL files and keeps a managed manifest while a reset is in flight.
# Staging moves records out of the active files, but does not discard their
# payloads.  ``destroy_workflow_artifact_reset`` is the final irreversible
# cleanup after the caller has verified and re-bootstraped the other stores.
_RESET_SCHEMA_VERSION = 1
_RESET_OPERATION = "workflow_artifact_reset"
_RESET_STAGING_DIRECTORY = ".reset_staging"
_RESET_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_RESET_STAGE_STATUSES = frozenset({"stage_failed", "staged", "purged", "restored", "destroyed"})


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _reset_scope(team_id: Any, reset_id: Any) -> tuple[str, str]:
    team = str(team_id or "").strip()
    reset = str(reset_id or "").strip()
    if not team or not _RESET_KEY.fullmatch(team):
        raise WorkflowArtifactResetValidationError("A safe team_id is required for artifact reset.")
    if not reset or not _RESET_KEY.fullmatch(reset):
        raise WorkflowArtifactResetValidationError("A safe reset_id is required for artifact reset.")
    return team, reset


def _reset_stage_path(team_id: str, reset_id: str) -> Path:
    return _path(team_id, "run_artifacts").parent / _RESET_STAGING_DIRECTORY / f"{reset_id}.json"


def _reset_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_reset_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path,
        json.dumps(dict(manifest), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
    )


def _read_reset_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowArtifactResetValidationError("Managed artifact reset manifest is unreadable.") from exc
    if not isinstance(value, dict):
        raise WorkflowArtifactResetValidationError("Managed artifact reset manifest must be an object.")
    return value


def _manifest_hash(manifest: Mapping[str, Any]) -> str:
    body = {
        key: value
        for key, value in manifest.items()
        if key not in {"manifestHash", "status", "createdAt", "updatedAt", "purgedAt", "restoredAt", "destroyedAt"}
    }
    return canonical_sha256(body)


def _manifest_records(manifest: Mapping[str, Any], *, allow_metadata_only: bool = False) -> list[dict[str, Any]]:
    raw_records = manifest.get("records")
    if not isinstance(raw_records, list):
        raise WorkflowArtifactResetValidationError("Artifact reset stage records are missing.")
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in raw_records:
        if not isinstance(entry, Mapping):
            raise WorkflowArtifactResetValidationError("Artifact reset stage contains a non-object record.")
        kind = str(entry.get("kind") or "").strip()
        record = entry.get("record")
        if kind not in _SUPPORTED_KINDS or not isinstance(record, Mapping):
            raise WorkflowArtifactResetValidationError("Artifact reset stage contains an incomplete record.")
        row = dict(record)
        team = str(row.get("teamId") or "").strip()
        workflow_run = str(row.get("workflowRunId") or "").strip()
        record_id = str(row.get("recordId") or "").strip()
        source_run = str(row.get("sourceCollectionRunId") or "").strip()
        content_hash = str(row.get("contentHash") or "").strip()
        identity = (kind, workflow_run, record_id)
        if team != str(manifest.get("teamId") or "").strip() or not workflow_run or not source_run or not record_id:
            raise WorkflowArtifactResetValidationError("Artifact reset stage record scope is incomplete.")
        if identity in seen:
            raise WorkflowArtifactResetConflictError("Artifact reset stage contains duplicate record identities.")
        seen.add(identity)
        if allow_metadata_only:
            if not content_hash:
                raise WorkflowArtifactResetValidationError("Destroyed artifact reset metadata is incomplete.")
        else:
            payload = row.get("payload")
            if not isinstance(payload, dict) or not payload or not content_hash:
                raise WorkflowArtifactResetValidationError("Artifact reset stage payload is incomplete.")
            if canonical_sha256(payload) != content_hash:
                raise WorkflowArtifactResetConflictError("Artifact reset stage payload hash does not match.")
        if str(row.get("kind") or "") != kind:
            raise WorkflowArtifactResetConflictError("Artifact reset stage record kind does not match its envelope.")
        records.append({"kind": kind, "record": row})
    expected_count = manifest.get("artifactCount")
    if expected_count is not None:
        try:
            if int(expected_count) != len(records):
                raise WorkflowArtifactResetValidationError("Artifact reset stage count does not match its records.")
        except (TypeError, ValueError) as exc:
            raise WorkflowArtifactResetValidationError("Artifact reset stage count is invalid.") from exc
    expected_kind_counts = manifest.get("kindCounts")
    if expected_kind_counts is not None:
        if not isinstance(expected_kind_counts, Mapping):
            raise WorkflowArtifactResetValidationError("Artifact reset stage kind counts are invalid.")
        actual_kind_counts = Counter(str(entry["kind"]) for entry in records)
        try:
            normalized_expected = {
                str(kind): int(count)
                for kind, count in expected_kind_counts.items()
            }
        except (TypeError, ValueError) as exc:
            raise WorkflowArtifactResetValidationError("Artifact reset stage kind counts are invalid.") from exc
        if dict(sorted(actual_kind_counts.items())) != dict(sorted(normalized_expected.items())):
            raise WorkflowArtifactResetValidationError("Artifact reset stage kind counts do not match its records.")
    return records


def _validate_reset_manifest(
    manifest: Mapping[str, Any],
    *,
    team_id: str,
    reset_id: str,
) -> dict[str, Any]:
    if str(manifest.get("teamId") or "").strip() != team_id:
        raise WorkflowArtifactResetValidationError("Artifact reset manifest belongs to another team.")
    if str(manifest.get("resetId") or "").strip() != reset_id:
        raise WorkflowArtifactResetValidationError("Artifact reset manifest belongs to another reset.")
    if manifest.get("schemaVersion") != _RESET_SCHEMA_VERSION or manifest.get("operation") != _RESET_OPERATION:
        raise WorkflowArtifactResetValidationError("Artifact reset manifest version or operation is invalid.")
    status = str(manifest.get("status") or "").strip().lower()
    if status not in _RESET_STAGE_STATUSES:
        raise WorkflowArtifactResetStateError(f"Unsupported artifact reset stage status: {status or 'missing'}")
    expected_hash = str(manifest.get("manifestHash") or "").strip()
    if not expected_hash or expected_hash != _manifest_hash(manifest):
        raise WorkflowArtifactResetConflictError("Artifact reset manifest hash is invalid.")
    _manifest_records(manifest, allow_metadata_only=status == "destroyed")
    return dict(manifest)


def _active_rows_by_kind(team_id: str) -> dict[str, list[dict[str, Any]]]:
    """Read and validate every active row before a reset can move anything."""

    rows_by_kind: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for kind in sorted(_SUPPORTED_KINDS):
        rows = _read(_path(team_id, kind))
        validated: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise WorkflowArtifactResetValidationError("Workflow artifact row must be an object.")
            current = dict(row)
            if str(current.get("teamId") or "").strip() != team_id:
                raise WorkflowArtifactResetValidationError("Workflow artifact has missing or mismatched team ownership.")
            if str(current.get("kind") or "").strip() != kind:
                raise WorkflowArtifactResetConflictError("Workflow artifact kind does not match its store file.")
            workflow_run = str(current.get("workflowRunId") or "").strip()
            record_id = str(current.get("recordId") or "").strip()
            source_run = str(current.get("sourceCollectionRunId") or "").strip()
            content_hash = str(current.get("contentHash") or "").strip()
            payload = current.get("payload")
            if not workflow_run or not source_run or not record_id or not content_hash:
                raise WorkflowArtifactResetValidationError("Workflow artifact identity or lineage is incomplete.")
            if not isinstance(payload, dict) or not payload:
                raise WorkflowArtifactResetValidationError("Workflow artifact payload is incomplete.")
            if canonical_sha256(payload) != content_hash:
                raise WorkflowArtifactResetConflictError("Workflow artifact payload hash does not match.")
            identity = (kind, workflow_run, record_id)
            if identity in seen:
                raise WorkflowArtifactResetConflictError("Workflow artifact identity is duplicated.")
            seen.add(identity)
            validated.append(current)
        rows_by_kind[kind] = validated
    return rows_by_kind


def _flatten_rows(rows_by_kind: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind in sorted(rows_by_kind):
        rows.extend(dict(row) for row in rows_by_kind[kind])
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("kind") or ""),
            str(row.get("workflowRunId") or ""),
            str(row.get("recordId") or ""),
        ),
    )


def _plan_artifact_ids(plan: Mapping[str, Any] | None) -> list[str] | None:
    """Extract the preview's artifact ids without guessing across stores."""

    if not isinstance(plan, Mapping):
        return None
    direct = plan.get("workflowArtifactIds") or plan.get("artifactIds") or plan.get("artifact_ids")
    if isinstance(direct, Sequence) and not isinstance(direct, (str, bytes, bytearray)):
        return [str(value or "").strip() for value in direct]
    for container_key in ("deleteSet", "delete_set"):
        container = plan.get(container_key)
        if not isinstance(container, Mapping):
            continue
        ids: list[str] = []
        found = False
        for family in ("artifacts", "plans", "candidates", "selections", "results", "workflow_artifacts"):
            if family not in container:
                continue
            found = True
            values = container.get(family)
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
                ids.extend(str(value or "").strip() for value in values)
        if found:
            return ids
    impact = plan.get("impact")
    if isinstance(impact, Mapping):
        object_ids = impact.get("deleteObjectIds") or impact.get("delete_object_ids")
        if isinstance(object_ids, Mapping):
            ids: list[str] = []
            found = False
            for family in ("artifacts", "plans", "candidates", "selections", "results", "workflow_artifacts"):
                if family not in object_ids:
                    continue
                found = True
                values = object_ids.get(family)
                if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
                    ids.extend(str(value or "").strip() for value in values)
            if found:
                return ids
    return None


def _validate_plan_scope(team_id: str, plan: Mapping[str, Any] | None) -> None:
    if not isinstance(plan, Mapping):
        return
    plan_team = str(plan.get("teamId") or plan.get("team_id") or "").strip()
    if plan_team and plan_team != team_id:
        raise WorkflowArtifactResetValidationError("Artifact reset plan belongs to another team.")


def _build_reset_manifest(team_id: str, reset_id: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    records = [
        {"kind": str(row["kind"]), "record": _json_clone(dict(row))}
        for row in rows
    ]
    kind_counts: dict[str, int] = {}
    for entry in records:
        kind = str(entry["kind"])
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    manifest: dict[str, Any] = {
        "schemaVersion": _RESET_SCHEMA_VERSION,
        "operation": _RESET_OPERATION,
        "teamId": team_id,
        "resetId": reset_id,
        "status": "staged",
        "artifactCount": len(records),
        "kindCounts": dict(sorted(kind_counts.items())),
        "records": records,
        "createdAt": _reset_now(),
        "updatedAt": _reset_now(),
    }
    manifest["manifestHash"] = _manifest_hash(manifest)
    return manifest


def _stage_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": _RESET_SCHEMA_VERSION,
        "operation": _RESET_OPERATION,
        "status": str(manifest.get("status") or ""),
        "teamId": str(manifest.get("teamId") or ""),
        "resetId": str(manifest.get("resetId") or ""),
        "stageId": str(manifest.get("resetId") or ""),
        "manifestHash": str(manifest.get("manifestHash") or ""),
        "artifactCount": int(manifest.get("artifactCount") or 0),
        "kindCounts": _json_clone(manifest.get("kindCounts") or {}),
        "remainingCount": 0,
        "stagingManaged": True,
        "stagingDestroyed": str(manifest.get("status") or "") == "destroyed",
    }


def _stage_handle(stage: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(stage, Mapping):
        raise WorkflowArtifactResetValidationError("A managed artifact reset stage handle is required.")
    nested = stage.get("stage")
    if isinstance(nested, Mapping):
        return nested
    return stage


def _resolve_stage_scope(
    team_id: Any,
    reset_id: Any,
    stage: Mapping[str, Any] | None,
) -> tuple[str, str, Mapping[str, Any]]:
    handle = _stage_handle(stage)
    explicit_reset = str(reset_id or "").strip()
    handle_team = str(handle.get("teamId") or handle.get("team_id") or "").strip()
    handle_reset = str(handle.get("resetId") or handle.get("stageId") or "").strip()
    if not handle_team or not handle_reset:
        raise WorkflowArtifactResetValidationError("Stage handle team_id and reset_id are required.")
    if explicit_reset and handle_reset and explicit_reset != handle_reset:
        raise WorkflowArtifactResetValidationError("Stage handle reset_id does not match the requested reset.")
    team, reset = _reset_scope(team_id, explicit_reset or handle_reset)
    if handle_team and handle_team != team:
        raise WorkflowArtifactResetValidationError("Stage handle belongs to another team.")
    manifest = _read_reset_manifest(_reset_stage_path(team, reset))
    if manifest is None:
        raise WorkflowArtifactResetStateError("Managed artifact reset stage is missing.")
    validated = _validate_reset_manifest(manifest, team_id=team, reset_id=reset)
    handle_hash = str(handle.get("manifestHash") or "").strip()
    valid_hashes = {str(validated.get("manifestHash") or "")}
    if str(validated.get("status") or "") == "destroyed":
        valid_hashes.add(str(validated.get("sourceManifestHash") or ""))
    if not handle_hash or handle_hash not in valid_hashes:
        raise WorkflowArtifactResetConflictError("Stage handle does not match the managed reset manifest.")
    return team, reset, validated


def prepare_workflow_artifact_reset(
    team_id: str,
    *,
    reset_id: str,
    plan: Mapping[str, Any] | None = None,
    artifact_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Stage every validated artifact for one team under a managed reset id.

    The active JSONL rows are moved to a reset manifest before the operation
    returns.  The manifest retains the original records so a later
    ``restore_workflow_artifact_reset`` can put them back exactly.
    """

    team, reset = _reset_scope(team_id, reset_id)
    _validate_plan_scope(team, plan)
    requested_ids = list(artifact_ids) if artifact_ids is not None else _plan_artifact_ids(plan)
    if requested_ids is not None:
        requested_ids = [str(value or "").strip() for value in requested_ids]
        if any(not value for value in requested_ids):
            raise WorkflowArtifactResetValidationError("Artifact reset plan contains an empty artifact id.")

    with _LOCK:
        stage_path = _reset_stage_path(team, reset)
        existing = _read_reset_manifest(stage_path)
        if existing is not None:
            manifest = _validate_reset_manifest(existing, team_id=team, reset_id=reset)
            status = str(manifest.get("status") or "")
            if status == "destroyed":
                raise WorkflowArtifactResetStateError("The reset id has already been finalized.")
            if status == "restored":
                return _stage_summary(manifest)
            active = _active_rows_by_kind(team)
            if _flatten_rows(active):
                raise WorkflowArtifactResetConflictError("Active workflow artifacts appeared after staging.")
            return _stage_summary(manifest)

        active_by_kind = _active_rows_by_kind(team)
        active_rows = _flatten_rows(active_by_kind)
        if requested_ids is not None:
            actual_ids = Counter(str(row.get("recordId") or "") for row in active_rows)
            expected_ids = Counter(requested_ids)
            if actual_ids != expected_ids:
                raise WorkflowArtifactResetConflictError("Artifact reset plan does not match the active artifact set.")

        manifest = _build_reset_manifest(team, reset, active_rows)
        # Persist the recovery manifest before touching active files.  A crash
        # after this point leaves a bounded, inspectable recovery authority.
        manifest_preparing = dict(manifest)
        manifest_preparing["status"] = "preparing"
        manifest_preparing["manifestHash"] = _manifest_hash(manifest_preparing)
        _write_reset_manifest(stage_path, manifest_preparing)

        snapshots: dict[Path, list[dict[str, Any]]] = {
            _path(team, kind): list(rows) for kind, rows in active_by_kind.items()
        }
        changed: list[Path] = []
        try:
            for path, rows in snapshots.items():
                if not rows:
                    continue
                _write(path, [])
                changed.append(path)
        except Exception as exc:
            rollback_error: Exception | None = None
            for path in reversed(changed):
                try:
                    _write(path, snapshots[path])
                except Exception as rollback_exc:  # noqa: BLE001 - preserve the recovery manifest
                    rollback_error = rollback_exc
            failed = dict(manifest_preparing)
            failed["status"] = "stage_failed"
            failed["updatedAt"] = _reset_now()
            failed["failure"] = type(exc).__name__
            failed["manifestHash"] = _manifest_hash(failed)
            try:
                _write_reset_manifest(stage_path, failed)
            except Exception:  # noqa: BLE001 - original failure remains authoritative
                pass
            if rollback_error is not None:
                raise WorkflowArtifactResetError("Artifact reset staging failed and rollback was incomplete.") from rollback_error
            raise WorkflowArtifactResetError("Artifact reset staging failed; recovery manifest retained.") from exc

        manifest["updatedAt"] = _reset_now()
        _write_reset_manifest(stage_path, manifest)
        return _stage_summary(manifest)


def stage_workflow_artifacts(
    team_id: str,
    reset_id: str,
    plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility name for reset adapters that call the step ``stage``."""

    return prepare_workflow_artifact_reset(team_id, reset_id=reset_id, plan=plan)


def purge_workflow_artifact_reset(
    team_id: str,
    *,
    reset_id: str = "",
    stage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Commit a previously staged move while retaining its restore manifest."""

    with _LOCK:
        team, reset, manifest = _resolve_stage_scope(team_id, reset_id, stage)
        status = str(manifest.get("status") or "")
        if status == "restored":
            raise WorkflowArtifactResetStateError("A restored artifact stage cannot be purged.")
        if status == "destroyed":
            raise WorkflowArtifactResetStateError("A finalized artifact stage cannot be purged.")
        if status not in {"staged", "purged"}:
            raise WorkflowArtifactResetStateError("Artifact stage is not ready for purge.")
        if _flatten_rows(_active_rows_by_kind(team)):
            raise WorkflowArtifactResetConflictError("Active workflow artifacts remain after staging.")
        if status == "purged":
            return _stage_summary(manifest)
        updated = dict(manifest)
        updated["status"] = "purged"
        updated["purgedAt"] = _reset_now()
        updated["updatedAt"] = updated["purgedAt"]
        updated["manifestHash"] = _manifest_hash(updated)
        _write_reset_manifest(_reset_stage_path(team, reset), updated)
        return _stage_summary(updated)


def purge_workflow_artifacts(
    team_id: str,
    reset_id: str,
    stage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility name for reset adapters that call the step ``commit``."""

    return purge_workflow_artifact_reset(team_id, reset_id=reset_id, stage=stage)


def restore_workflow_artifact_reset(
    team_id: str,
    *,
    reset_id: str = "",
    stage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Restore staged records exactly once; repeated restore is idempotent."""

    with _LOCK:
        team, reset, manifest = _resolve_stage_scope(team_id, reset_id, stage)
        status = str(manifest.get("status") or "")
        if status == "destroyed":
            raise WorkflowArtifactResetStateError("A finalized artifact stage cannot be restored.")
        if status == "restored":
            return _stage_summary(manifest)
        if status not in {"stage_failed", "staged", "purged"}:
            raise WorkflowArtifactResetStateError("Artifact stage is not restorable.")
        staged_records = _manifest_records(manifest)
        active_by_kind = _active_rows_by_kind(team)
        active_index = {
            (kind, str(row.get("workflowRunId") or ""), str(row.get("recordId") or "")): row
            for kind, rows in active_by_kind.items()
            for row in rows
        }
        additions: dict[str, list[dict[str, Any]]] = {}
        for entry in staged_records:
            kind = str(entry["kind"])
            row = dict(entry["record"])
            identity = (kind, str(row.get("workflowRunId") or ""), str(row.get("recordId") or ""))
            current = active_index.get(identity)
            if current is not None:
                if str(current.get("contentHash") or "") != str(row.get("contentHash") or ""):
                    raise WorkflowArtifactResetConflictError("Active artifact conflicts with the restore manifest.")
                continue
            additions.setdefault(kind, []).append(row)

        snapshots = { _path(team, kind): list(rows) for kind, rows in active_by_kind.items() }
        changed: list[Path] = []
        try:
            for kind, rows in additions.items():
                if not rows:
                    continue
                path = _path(team, kind)
                _write(path, [*active_by_kind[kind], *rows])
                changed.append(path)
        except Exception as exc:
            rollback_error: Exception | None = None
            for path in reversed(changed):
                try:
                    _write(path, snapshots[path])
                except Exception as rollback_exc:  # noqa: BLE001 - keep manifest restorable
                    rollback_error = rollback_exc
            if rollback_error is not None:
                raise WorkflowArtifactResetError("Artifact reset restore failed and rollback was incomplete.") from rollback_error
            raise WorkflowArtifactResetError("Artifact reset restore failed; manifest retained.") from exc

        updated = dict(manifest)
        updated["status"] = "restored"
        updated["restoredAt"] = _reset_now()
        updated["updatedAt"] = updated["restoredAt"]
        updated["manifestHash"] = _manifest_hash(updated)
        _write_reset_manifest(_reset_stage_path(team, reset), updated)
        return _stage_summary(updated)


def restore_workflow_artifacts(
    team_id: str,
    reset_id: str,
    stage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility name for reset adapters that call the step ``restore``."""

    return restore_workflow_artifact_reset(team_id, reset_id=reset_id, stage=stage)


def discard_restored_workflow_artifact_reset(
    team_id: str,
    *,
    reset_id: str,
) -> dict[str, Any]:
    """Remove a verified-restored reset manifest before retrying that plan.

    The reset service owns compensation.  Once this store proves that all of
    the manifest's records are back in the active owner files, the manifest is
    no longer recovery material and would otherwise make the same plan
    permanently non-retryable.
    """

    team, reset = _reset_scope(team_id, reset_id)
    with _LOCK:
        stage_path = _reset_stage_path(team, reset)
        existing = _read_reset_manifest(stage_path)
        if existing is None:
            return {
                "status": "absent",
                "teamId": team,
                "resetId": reset,
                "stagingDestroyed": False,
            }
        manifest = _validate_reset_manifest(existing, team_id=team, reset_id=reset)
        if str(manifest.get("status") or "") != "restored":
            raise WorkflowArtifactResetStateError(
                "Only a verified restored artifact stage can be discarded."
            )
        expected_by_kind: dict[str, list[dict[str, Any]]] = {
            kind: [] for kind in _SUPPORTED_KINDS
        }
        for entry in _manifest_records(manifest):
            expected_by_kind[str(entry["kind"])].append(dict(entry["record"]))
        expected = _flatten_rows(expected_by_kind)
        actual = _flatten_rows(_active_rows_by_kind(team))
        if actual != expected:
            raise WorkflowArtifactResetConflictError(
                "Active workflow artifacts no longer exactly match the restored reset manifest."
            )
        stage_path.unlink()
        return {
            "status": "discarded",
            "teamId": team,
            "resetId": reset,
            "artifactCount": len(expected),
            "stagingDestroyed": True,
        }


def destroy_workflow_artifact_reset(
    team_id: str,
    *,
    reset_id: str = "",
    stage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Drop staged payloads after commit, retaining only a managed audit manifest."""

    with _LOCK:
        team, reset, manifest = _resolve_stage_scope(team_id, reset_id, stage)
        status = str(manifest.get("status") or "")
        if status == "destroyed":
            return _stage_summary(manifest)
        if status != "purged":
            raise WorkflowArtifactResetStateError("Only a purged artifact stage can be finalized.")
        if _flatten_rows(_active_rows_by_kind(team)):
            raise WorkflowArtifactResetConflictError("Active workflow artifacts remain before staging cleanup.")
        metadata_records = []
        for entry in _manifest_records(manifest):
            row = entry["record"]
            metadata_records.append(
                {
                    "kind": entry["kind"],
                    "record": {
                        "teamId": team,
                        "kind": entry["kind"],
                        "workflowRunId": row["workflowRunId"],
                        "sourceCollectionRunId": row["sourceCollectionRunId"],
                        "recordId": row["recordId"],
                        "contentHash": row["contentHash"],
                    },
                }
            )
        updated = dict(manifest)
        updated["status"] = "destroyed"
        updated["sourceManifestHash"] = str(manifest.get("manifestHash") or "")
        updated["records"] = metadata_records
        updated["payloadRetained"] = False
        updated["destroyedAt"] = _reset_now()
        updated["updatedAt"] = updated["destroyedAt"]
        updated["manifestHash"] = _manifest_hash(updated)
        _write_reset_manifest(_reset_stage_path(team, reset), updated)
        return _stage_summary(updated)


def destroy_workflow_artifacts(
    team_id: str,
    reset_id: str,
    stage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility name for reset adapters that call the step ``destroy_staging``."""

    return destroy_workflow_artifact_reset(team_id, reset_id=reset_id, stage=stage)
