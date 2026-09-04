"""Generic data processing substrate for agent-driven intake pipelines."""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.web.services.runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
DEFAULT_PROFILE_ID = "generic_document_processing"
RUN_STATUSES = {"draft", "collecting", "processing", "reviewing", "completed", "cancelled", "failed"}
RECORD_STATUSES = {"collected", "processing", "ready_for_review", "accepted", "rejected", "archived"}
ASSIGNMENT_STATUSES = {"open", "in_progress", "completed", "returned", "cancelled"}
OUTPUT_STATUSES = {"completed", "returned", "partial", "failed"}
COLLECTION_AGENT_ROLES = {
    "data_intake_coordinator",
    "source_finder",
    "source_extractor",
    "source_relation_mapper",
    "source_ingestor",
    "intake_review",
}
SOURCE_TYPES = {"url", "file", "paper", "dataset", "note", "api", "manual", "unknown"}
_LOCK = threading.RLock()


class DataProcessingError(ValueError):
    """Base error for data processing service validation failures."""


class DataProcessingNotFoundError(DataProcessingError):
    """Raised when a data processing resource does not exist."""


def list_profiles() -> dict[str, Any]:
    profiles = [_generic_document_processing_profile()]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "defaultProfileId": DEFAULT_PROFILE_ID,
        "profiles": profiles,
    }


def get_profile(profile_id: str) -> dict[str, Any]:
    normalized = _safe_token(profile_id, default="")
    if normalized != DEFAULT_PROFILE_ID:
        raise DataProcessingNotFoundError(f"Unknown data processing profile: {profile_id}")
    return _generic_document_processing_profile()


def create_processing_run(profile_id: str = DEFAULT_PROFILE_ID, *, title: str = "", scope: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = get_profile(profile_id or DEFAULT_PROFILE_ID)
    now = _now_utc()
    run_id = _new_id("dprun")
    run = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "profileId": profile["profileId"],
        "title": _trim_text(title, max_length=180) or profile["displayName"],
        "status": "draft",
        "scope": _normalize_map(scope, max_items=80),
        "metadata": _normalize_map(metadata, max_items=80),
        "createdAt": now,
        "updatedAt": now,
        "storage": {
            "runPath": _relative_path(_run_path(run_id)),
            "recordsPath": _relative_path(_records_path(run_id)),
            "collectionAssignmentsPath": _relative_path(_assignments_path(run_id)),
            "collectionOutputsPath": _relative_path(_outputs_path(run_id)),
            "eventsPath": _relative_path(_events_path(run_id)),
        },
    }
    with _LOCK:
        _write_json(_run_path(run_id), run)
        _append_jsonl(_events_path(run_id), _run_event("data_processing.run.created", run_id, {"profileId": profile["profileId"]}))
    _record_data_processing_event(
        "data_processing.run.created",
        run_id=run_id,
        fields={"profileId": profile["profileId"], "status": run["status"]},
    )
    return run


def list_processing_runs(
    *,
    limit: int = 50,
    profile_id: str = "",
    metadata_filters: dict[str, Any] | None = None,
    scope_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_limit = min(200, max(1, int(limit or 50)))
    normalized_profile_id = _trim_text(profile_id, max_length=120)
    normalized_metadata_filters = _normalize_filter_map(metadata_filters)
    normalized_scope_filters = _normalize_filter_map(scope_filters)
    runs: list[dict[str, Any]] = []
    runs_root = _runs_root()
    if runs_root.exists():
        for run_path in runs_root.glob("*/run.json"):
            run = _read_json(run_path)
            if run and _processing_run_matches_filters(
                run,
                profile_id=normalized_profile_id,
                metadata_filters=normalized_metadata_filters,
                scope_filters=normalized_scope_filters,
            ):
                runs.append(run)
    runs.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    returned_runs = runs[:normalized_limit]
    hydrated_runs = [
        {**run, "summary": get_processing_status(str(run.get("runId") or ""))["summary"]}
        for run in returned_runs
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runs": hydrated_runs,
        "summary": {
            "runCount": len(runs),
            "returnedCount": min(len(runs), normalized_limit),
            "filtered": bool(normalized_profile_id or normalized_metadata_filters or normalized_scope_filters),
        },
    }


def _normalize_filter_map(value: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _trim_text(raw_key, max_length=120)
        item = _trim_text(raw_value, max_length=300)
        if key and item:
            normalized[key] = item
    return normalized


def _processing_run_matches_filters(
    run: dict[str, Any],
    *,
    profile_id: str,
    metadata_filters: dict[str, str],
    scope_filters: dict[str, str],
) -> bool:
    if profile_id and _trim_text(run.get("profileId"), max_length=120) != profile_id:
        return False
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    for key, expected in metadata_filters.items():
        if _trim_text(metadata.get(key), max_length=300) != expected:
            return False
    for key, expected in scope_filters.items():
        if _trim_text(scope.get(key), max_length=300) != expected:
            return False
    return True


def get_processing_run(run_id: str) -> dict[str, Any]:
    run = _load_run(run_id)
    status = get_processing_status(run_id)
    return {
        **run,
        "summary": status["summary"],
        "processingStatus": status,
    }


def get_processing_run_scope(run_id: str) -> dict[str, Any]:
    """Lightweight run-scope read (run.json only; no records/status computation).

    Storage-layout callers only need ``scope``/``metadata`` identity fields;
    routing them through :func:`get_processing_run` would pay a full status
    recomputation on every path resolution.
    """

    run = _load_run(run_id)
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    return {"scope": dict(scope), "metadata": dict(metadata)}


def delete_processing_run(run_id: str) -> dict[str, Any]:
    """Delete one generic run after its domain owner has applied its guards.

    This substrate deliberately has no opinion about whether a run may be
    deleted.  Domain services must first prove that no downstream artifact or
    active worker depends on it; this helper only removes the bounded run
    directory and its local event history atomically under the service lock.
    """

    normalized_run_id = _safe_token(run_id, default="", max_length=96)
    if not normalized_run_id:
        raise DataProcessingNotFoundError("Data processing run id is required.")
    root = _run_root(normalized_run_id)
    with _LOCK:
        if not root.is_dir():
            raise DataProcessingNotFoundError(f"Data processing run not found: {run_id}")
        shutil.rmtree(root)
    _record_data_processing_event(
        "data_processing.run.deleted",
        run_id=normalized_run_id,
        fields={"reason": "domain_guarded_reset"},
    )
    return {"schemaVersion": SCHEMA_VERSION, "runId": normalized_run_id, "deleted": True}


def cancel_processing_run(run_id: str, *, reason: str = "operator_cancelled") -> dict[str, Any]:
    """Mark one active run cancelled so domain workers can stop cooperatively."""

    normalized_run_id = _safe_token(run_id, default="", max_length=96)
    if not normalized_run_id:
        raise DataProcessingNotFoundError("Data processing run id is required.")
    with _LOCK:
        run = _load_run(normalized_run_id)
        if str(run.get("status") or "") != "cancelled":
            _touch_run(normalized_run_id, status="cancelled")
        cancelled = _load_run(normalized_run_id)
        _append_jsonl(
            _events_path(normalized_run_id),
            _run_event(
                "data_processing.run.cancelled",
                normalized_run_id,
                {"reason": _trim_text(reason, max_length=300) or "operator_cancelled"},
            ),
        )
    _record_data_processing_event(
        "data_processing.run.cancelled",
        run_id=normalized_run_id,
        fields={"reason": _trim_text(reason, max_length=300) or "operator_cancelled"},
    )
    return cancelled


def fail_processing_run(run_id: str, *, reason: str = "execution_failed") -> dict[str, Any]:
    """Mark one active run failed so liveness gates treat it as terminal.

    Idempotent and terminal-preserving: a run already ``completed``,
    ``cancelled``, or ``failed`` keeps its status (a cancelled run is never
    overwritten by a late failure report).  Returns the refreshed run.
    """

    normalized_run_id = _safe_token(run_id, default="", max_length=96)
    if not normalized_run_id:
        raise DataProcessingNotFoundError("Data processing run id is required.")
    normalized_reason = _trim_text(reason, max_length=300) or "execution_failed"
    with _LOCK:
        run = _load_run(normalized_run_id)
        if str(run.get("status") or "") not in {"completed", "cancelled", "failed"}:
            _touch_run(normalized_run_id, status="failed")
        failed = _load_run(normalized_run_id)
        _append_jsonl(
            _events_path(normalized_run_id),
            _run_event(
                "data_processing.run.failed",
                normalized_run_id,
                {"reason": normalized_reason},
            ),
        )
    _record_data_processing_event(
        "data_processing.run.failed",
        run_id=normalized_run_id,
        fields={"reason": normalized_reason},
    )
    return failed


def complete_collection_batch(
    run_id: str,
    *,
    terminal_status: str = "completed",
    reason: str = "source_collection_batch_finished",
) -> dict[str, Any]:
    """Write one finished collection batch's outcome back onto the run.

    Called by the source-collection search tail when a batch ends — either
    with more batches pending (``needs_continue``) or with the query budget
    exhausted (``completed``).  Two things land durably:

    - a ``data_processing.run.collection_batch_completed`` event in the
      run's event history, carrying the batch terminal status;
    - an advanced run.json status following the existing collection-output
      semantics (``_advance_run_status_after_collection_output``): open
      assignments keep ``collecting``, closed assignments with records move
      to ``reviewing`` (records waiting on review), and a drained run
      without records ``completed``.

    Terminal statuses (``completed``/``cancelled``/``failed``) are
    preserved; the caller reports hard failures through
    :func:`fail_processing_run` instead.
    """

    normalized_run_id = _safe_token(run_id, default="", max_length=96)
    if not normalized_run_id:
        raise DataProcessingNotFoundError("Data processing run id is required.")
    normalized_terminal_status = _trim_text(terminal_status, max_length=80) or "completed"
    normalized_reason = _trim_text(reason, max_length=300) or "source_collection_batch_finished"
    with _LOCK:
        run = _load_run(normalized_run_id)
        assignments = _read_jsonl(_assignments_path(normalized_run_id))
        record_count = len(_read_jsonl(_records_path(normalized_run_id)))
        next_status = _advance_run_status_after_collection_output(
            run,
            assignments=assignments,
            record_count=record_count,
            preferred="collecting",
        )
        if str(run.get("status") or "") != next_status:
            _touch_run(normalized_run_id, status=next_status)
        advanced = _load_run(normalized_run_id)
        open_assignments = [
            item for item in assignments if item.get("status") in {"open", "in_progress", "returned"}
        ]
        _append_jsonl(
            _events_path(normalized_run_id),
            _run_event(
                "data_processing.run.collection_batch_completed",
                normalized_run_id,
                {
                    "terminalStatus": normalized_terminal_status,
                    "runStatus": next_status,
                    "openAssignmentCount": len(open_assignments),
                    "recordCount": record_count,
                    "reason": normalized_reason,
                },
            ),
        )
    _record_data_processing_event(
        "data_processing.run.collection_batch_completed",
        run_id=normalized_run_id,
        fields={
            "terminalStatus": normalized_terminal_status,
            "runStatus": next_status,
            "reason": normalized_reason,
        },
    )
    return advanced


def list_records(run_id: str) -> dict[str, Any]:
    run = _load_run(run_id)
    records = _read_jsonl(_records_path(run["runId"]))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run["runId"],
        "records": records,
        "summary": _record_summary(records),
    }


def list_collection_outputs(run_id: str) -> dict[str, Any]:
    run = _load_run(run_id)
    outputs = _read_jsonl(_outputs_path(run["runId"]))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run["runId"],
        "outputs": outputs,
        "summary": {"outputCount": len(outputs)},
    }


def add_record(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    run = _load_run(run_id)
    record = _build_record(run["runId"], payload)
    with _LOCK:
        _append_jsonl(_records_path(run["runId"]), record)
        _touch_run(run["runId"], status=_advance_run_status(run, preferred="collecting"))
        _append_jsonl(_events_path(run["runId"]), _run_event("data_processing.record.created", run["runId"], {"recordId": record["recordId"], "sourceType": record["sourceType"]}))
    _record_data_processing_event(
        "data_processing.record.created",
        run_id=run["runId"],
        fields={"recordId": record["recordId"], "sourceType": record["sourceType"]},
    )
    return record


def list_collection_assignments(run_id: str) -> dict[str, Any]:
    run = _load_run(run_id)
    assignments = _read_jsonl(_assignments_path(run["runId"]))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run["runId"],
        "assignments": assignments,
        "summary": _assignment_summary(assignments),
    }


def create_collection_assignment(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    run = _load_run(run_id)
    agent_role = _safe_token(payload.get("agentRole") or payload.get("agent_role"), default="")
    if agent_role not in COLLECTION_AGENT_ROLES:
        raise DataProcessingError(f"Unsupported collection agent role: {agent_role or '<empty>'}")
    now = _now_utc()
    assignment = {
        "schemaVersion": SCHEMA_VERSION,
        "assignmentId": _new_id("dpassign"),
        "runId": run["runId"],
        "agentRole": agent_role,
        "agentId": _trim_text(payload.get("agentId") or payload.get("agent_id"), max_length=160),
        "status": _normalize_choice(payload.get("status"), ASSIGNMENT_STATUSES, default="open"),
        "scope": _normalize_map(payload.get("scope"), max_items=80),
        "inputRefs": _normalize_string_list(payload.get("inputRefs") or payload.get("input_refs"), max_items=120, max_length=240),
        "expectedRecordTypes": _normalize_string_list(payload.get("expectedRecordTypes") or payload.get("expected_record_types"), max_items=40, max_length=120),
        "acceptance": _normalize_map(payload.get("acceptance"), max_items=60),
        "createdAt": now,
        "updatedAt": now,
    }
    with _LOCK:
        _append_jsonl(_assignments_path(run["runId"]), assignment)
        _touch_run(run["runId"], status=_advance_run_status(run, preferred="collecting"))
        _append_jsonl(
            _events_path(run["runId"]),
            _run_event(
                "data_processing.collection_assignment.created",
                run["runId"],
                {"assignmentId": assignment["assignmentId"], "agentRole": agent_role, "status": assignment["status"]},
            ),
        )
    _record_data_processing_event(
        "data_processing.collection_assignment.created",
        run_id=run["runId"],
        fields={"assignmentId": assignment["assignmentId"], "agentRole": agent_role, "status": assignment["status"]},
    )
    return assignment


def record_collection_output(run_id: str, assignment_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    run = _load_run(run_id)
    assignments = _read_jsonl(_assignments_path(run["runId"]))
    assignment = next((item for item in assignments if item.get("assignmentId") == assignment_id), None)
    if assignment is None:
        raise DataProcessingNotFoundError(f"Collection assignment not found: {assignment_id}")
    now = _now_utc()
    output_status = _normalize_choice(payload.get("status"), OUTPUT_STATUSES, default="completed")
    output_id = _new_id("dpout")
    raw_records = payload.get("records")
    if raw_records is None:
        raw_records = []
    if not isinstance(raw_records, list):
        raise DataProcessingError("records must be a list")
    created_records = [
        _build_record(
            run["runId"],
            item if isinstance(item, dict) else {"title": str(item), "sourceType": "manual"},
            collection_trace={"assignmentId": assignment_id, "outputId": output_id, "agentRole": assignment.get("agentRole", "")},
        )
        for item in raw_records[:200]
    ]
    output = {
        "schemaVersion": SCHEMA_VERSION,
        "outputId": output_id,
        "runId": run["runId"],
        "assignmentId": assignment_id,
        "agentRole": assignment.get("agentRole", ""),
        "agentId": assignment.get("agentId", ""),
        "status": output_status,
        "recordIds": [item["recordId"] for item in created_records],
        "notes": _trim_text(payload.get("notes"), max_length=4000),
        "qualitySignals": _normalize_map(payload.get("qualitySignals") or payload.get("quality_signals"), max_items=80),
        "blockingIssues": _normalize_string_list(payload.get("blockingIssues") or payload.get("blocking_issues"), max_items=80, max_length=500),
        "createdAt": now,
    }
    next_assignment_status = "returned" if output_status == "returned" else "completed"
    with _LOCK:
        for record in created_records:
            _append_jsonl(_records_path(run["runId"]), record)
        _append_jsonl(_outputs_path(run["runId"]), output)
        _replace_assignment(run["runId"], assignment_id, {"status": next_assignment_status, "updatedAt": now})
        next_assignments = _read_jsonl(_assignments_path(run["runId"]))
        next_record_count = len(_read_jsonl(_records_path(run["runId"])))
        _touch_run(
            run["runId"],
            status=_advance_run_status_after_collection_output(
                run,
                assignments=next_assignments,
                record_count=next_record_count,
                preferred="processing" if created_records else "collecting",
            ),
        )
        _append_jsonl(
            _events_path(run["runId"]),
            _run_event(
                "data_processing.collection_output.recorded",
                run["runId"],
                {
                    "assignmentId": assignment_id,
                    "outputId": output_id,
                    "outputStatus": output_status,
                    "createdRecordCount": len(created_records),
                },
            ),
        )
    _record_data_processing_event(
        "data_processing.collection_output.recorded",
        run_id=run["runId"],
        fields={
            "assignmentId": assignment_id,
            "outputId": output_id,
            "outputStatus": output_status,
            "createdRecordCount": len(created_records),
        },
    )
    return {
        "output": output,
        "createdRecords": created_records,
    }


def get_processing_status(run_id: str) -> dict[str, Any]:
    run = _load_run(run_id)
    records = _read_jsonl(_records_path(run["runId"]))
    assignments = _read_jsonl(_assignments_path(run["runId"]))
    outputs = _read_jsonl(_outputs_path(run["runId"]))
    open_assignments = [item for item in assignments if item.get("status") in {"open", "in_progress", "returned"}]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run["runId"],
        "profileId": run.get("profileId", ""),
        "runStatus": run.get("status", ""),
        "summary": {
            "recordCount": len(records),
            "assignmentCount": len(assignments),
            "openAssignmentCount": len(open_assignments),
            "outputCount": len(outputs),
            "recordStatusCounts": _count_by(records, "status"),
            "sourceTypeCounts": _count_by(records, "sourceType"),
            "assignmentStatusCounts": _count_by(assignments, "status"),
        },
        "nextActions": _status_next_actions(run, records, assignments, outputs),
        "boundaries": {
            "generic": True,
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesKnowledgeGraph": False,
            "requiresDownstreamPublisher": True,
        },
    }


def _generic_document_processing_profile() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "profileId": DEFAULT_PROFILE_ID,
        "displayName": "Generic document processing",
        "description": "A domain-neutral intake profile for collecting, extracting, deduplicating, quality-checking, and reviewing source records before any domain-specific publication.",
        "stages": [
            {"stageId": "intake", "displayName": "Intake", "writes": ["DataRecord"]},
            {"stageId": "collection", "displayName": "Agent collection", "writes": ["CollectionAssignment", "CollectionOutput"]},
            {"stageId": "extraction", "displayName": "Extraction", "writes": ["DataRecord.extracted"]},
            {"stageId": "deduplication", "displayName": "Deduplication", "writes": ["DataRecord.links"]},
            {"stageId": "quality", "displayName": "Quality gate", "writes": ["DataRecord.qualitySignals"]},
            {"stageId": "review", "displayName": "Review", "writes": ["DataRecord.status"]},
        ],
        "collectionRoles": [
            {"agentRole": "data_intake_coordinator", "purpose": "Owns run scope, assigns collection work, and monitors status."},
            {"agentRole": "source_finder", "purpose": "Finds, fetches, downloads, and registers traceable source records."},
            {"agentRole": "source_extractor", "purpose": "Extracts useful content and reviews source quality in one pass."},
            {"agentRole": "source_relation_mapper", "purpose": "Builds candidate-only topic, source, and evidence relationships."},
            {"agentRole": "source_ingestor", "purpose": "Performs final governed ingestion into formal team knowledge."},
            {"agentRole": "intake_review", "purpose": "Reviews records before downstream domain pipelines publish them."},
        ],
        "publishBoundary": {
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesKnowledgeGraph": False,
        },
    }


def _build_record(run_id: str, payload: dict[str, Any], *, collection_trace: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DataProcessingError("record payload must be an object")
    source_type = _safe_token(payload.get("sourceType") or payload.get("source_type"), default="unknown")
    if source_type not in SOURCE_TYPES:
        source_type = "unknown"
    source_ref = _trim_text(payload.get("sourceRef") or payload.get("source_ref"), max_length=1000)
    raw_location = _trim_text(payload.get("rawLocation") or payload.get("raw_location"), max_length=1000)
    title = _trim_text(payload.get("title"), max_length=260)
    if not (source_ref or raw_location or title):
        raise DataProcessingError("record requires at least one of sourceRef, rawLocation, or title")
    now = _now_utc()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "recordId": _new_id("dprec"),
        "runId": run_id,
        "sourceType": source_type,
        "sourceRef": source_ref,
        "rawLocation": raw_location,
        "title": title,
        "summary": _trim_text(payload.get("summary"), max_length=4000),
        "status": _normalize_choice(payload.get("status"), RECORD_STATUSES, default="collected"),
        "metadata": _normalize_map(payload.get("metadata"), max_items=120),
        "qualitySignals": _normalize_map(payload.get("qualitySignals") or payload.get("quality_signals"), max_items=80),
        "collectionTrace": _normalize_map(collection_trace or payload.get("collectionTrace") or payload.get("collection_trace"), max_items=40),
        "createdAt": now,
        "updatedAt": now,
    }


def _load_run(run_id: str) -> dict[str, Any]:
    normalized = _safe_token(run_id, default="")
    if not normalized:
        raise DataProcessingNotFoundError("Data processing run id is required")
    run = _read_json(_run_path(normalized))
    if not run:
        raise DataProcessingNotFoundError(f"Data processing run not found: {run_id}")
    return run


def _touch_run(run_id: str, *, status: str | None = None) -> None:
    run = _load_run(run_id)
    run["updatedAt"] = _now_utc()
    # Cancellation and failure are terminal. A search call already in flight
    # may finish after the operator stops the run or after its failure was
    # recorded; its stale preferred status must not reopen the run.
    if status and str(run.get("status") or "") not in {"cancelled", "failed"}:
        run["status"] = _normalize_choice(status, RUN_STATUSES, default=run.get("status") or "draft")
    _write_json(_run_path(run_id), run)


def _replace_assignment(run_id: str, assignment_id: str, updates: dict[str, Any]) -> None:
    assignments = _read_jsonl(_assignments_path(run_id))
    replaced = False
    next_assignments = []
    for item in assignments:
        if item.get("assignmentId") == assignment_id:
            next_assignments.append({**item, **updates})
            replaced = True
        else:
            next_assignments.append(item)
    if not replaced:
        raise DataProcessingNotFoundError(f"Collection assignment not found: {assignment_id}")
    _write_jsonl(_assignments_path(run_id), next_assignments)


def _advance_run_status(run: dict[str, Any], *, preferred: str) -> str:
    current = str(run.get("status") or "draft")
    if current in {"completed", "cancelled", "failed"}:
        return current
    return _normalize_choice(preferred, RUN_STATUSES, default=current)


def _advance_run_status_after_collection_output(
    run: dict[str, Any],
    *,
    assignments: list[dict[str, Any]],
    record_count: int,
    preferred: str,
) -> str:
    current = str(run.get("status") or "draft")
    if current in {"completed", "cancelled", "failed"}:
        return current
    if not assignments:
        return _normalize_choice(preferred, RUN_STATUSES, default=current)
    open_assignments = [item for item in assignments if item.get("status") in {"open", "in_progress", "returned"}]
    if open_assignments:
        return _normalize_choice(preferred, RUN_STATUSES, default=current)
    if record_count > 0:
        return "reviewing"
    return "completed"


def _status_next_actions(run: dict[str, Any], records: list[dict[str, Any]], assignments: list[dict[str, Any]], outputs: list[dict[str, Any]]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if not assignments:
        actions.append({"action": "create_collection_assignment", "reason": "No agent collection assignment exists for this run."})
    if assignments and not outputs:
        actions.append({"action": "record_collection_output", "reason": "Collection assignments exist but no agent output has been recorded."})
    if records and not any(item.get("status") in {"ready_for_review", "accepted"} for item in records):
        actions.append({"action": "run_quality_or_review_gate", "reason": "Records are collected but not yet ready for downstream publication."})
    if not records and run.get("status") != "draft":
        actions.append({"action": "add_record", "reason": "The run has started but has no collected data records."})
    return actions


def _record_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "recordCount": len(records),
        "recordStatusCounts": _count_by(records, "status"),
        "sourceTypeCounts": _count_by(records, "sourceType"),
    }


def _assignment_summary(assignments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "assignmentCount": len(assignments),
        "assignmentStatusCounts": _count_by(assignments, "status"),
    }


def _count_by(items: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = str(item.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _run_event(event_code: str, run_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "eventId": _new_id("dpevt"),
        "eventCode": event_code,
        "runId": run_id,
        "fields": _normalize_map(fields, max_items=80),
        "createdAt": _now_utc(),
    }


def _record_data_processing_event(event_code: str, *, run_id: str, fields: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "data_processing",
            "pipeline",
            event_code,
            message=event_code,
            fields={"runId": run_id, **_normalize_map(fields, max_items=80)},
            lifecycle=True,
        )
    except Exception:
        return


def _run_path(run_id: str) -> Path:
    return _run_root(run_id) / "run.json"


def _records_path(run_id: str) -> Path:
    return _run_root(run_id) / "records.jsonl"


def _assignments_path(run_id: str) -> Path:
    return _run_root(run_id) / "collection_assignments.jsonl"


def _outputs_path(run_id: str) -> Path:
    return _run_root(run_id) / "collection_outputs.jsonl"


def _events_path(run_id: str) -> Path:
    return _run_root(run_id) / "events.jsonl"


def _run_root(run_id: str) -> Path:
    return _runs_root() / _safe_token(run_id, default="run", max_length=96)


def _runs_root() -> Path:
    return developer_sandbox.route_workspace_path(
        _project_root(),
        "data_processing",
        "data_processing",
        "runs",
        intent="state",
        seed=True,
    )


def _project_root() -> Path:
    root = Path(PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _relative_path(path: Path) -> str:
    resolved = path.resolve()
    workspace_root = developer_sandbox.formal_workspace_path(_project_root()).resolve()
    try:
        return f"workspace/{resolved.relative_to(workspace_root).as_posix()}"
    except ValueError:
        pass
    sandbox_root = developer_sandbox.sandbox_workspace_path(_project_root())
    if sandbox_root is not None:
        try:
            return f"workspace/{resolved.relative_to(sandbox_root.resolve()).as_posix()}"
        except ValueError:
            pass
    try:
        return str(resolved.relative_to(_project_root())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            value = json.loads(raw)
            if isinstance(value, dict):
                items.append(value)
    except (OSError, json.JSONDecodeError):
        return []
    return items


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in payloads), encoding="utf-8")


def _normalize_choice(value: Any, allowed: set[str], *, default: str) -> str:
    normalized = _safe_token(value, default="")
    return normalized if normalized in allowed else default


def _normalize_string_list(value: Any, *, max_items: int, max_length: int) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    results: list[str] = []
    for item in raw_items[:max_items]:
        text = _trim_text(item, max_length=max_length)
        if text:
            results.append(text)
    return results


def _normalize_map(value: Any, *, max_items: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= max_items:
            break
        safe_key = _safe_token(key, default=f"field_{index}", max_length=80)
        result[safe_key] = _normalize_value(item)
    return result


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return _trim_text(value, max_length=4000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_normalize_value(item) for item in value[:120]]
    if isinstance(value, dict):
        return _normalize_map(value, max_items=80)
    return _trim_text(value, max_length=1000)


def _trim_text(value: Any, *, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].rstrip() + "..."


def _safe_token(value: Any, *, default: str, max_length: int = 96) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    chars: list[str] = []
    for char in text:
        if char.isalnum() or char in {"_", "-", "."}:
            chars.append(char)
        elif char.isspace():
            chars.append("_")
    token = "".join(chars).strip("._-")
    return (token or default)[:max_length]


def _new_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
