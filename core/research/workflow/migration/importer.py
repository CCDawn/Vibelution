"""Import migratable JSON Runs into a temporary Workflow Ledger database."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.research.workflow.ledger import (
    CommandRecord,
    EventRecord,
    NodeAttemptRecord,
    RunRecord,
    WorkflowLedgerStore,
)
from core.research.workflow.transitions import (
    HandoffStatus,
    NodeAttemptStatus,
    can_transition_handoff,
    can_transition_node_attempt,
)

from .inventory import build_inventory
from .manifest import (
    APPLY_NAME,
    AUDIT_NAME,
    ManifestStatus,
    migration_dir,
    write_json,
    write_manifest,
)
from .validator import unknown_entries

_RUN_STATUS = {
    "queued": "created",
    "created": "created",
    "running": "running",
    "waiting_human": "waiting_human",
    "blocked": "blocked",
    "reconciliation_required": "reconciliation_required",
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "archived": "archived",
}

_ATTEMPT_STATUS = {
    "pending": "starting",
    "ready": "starting",
    "starting": "starting",
    "dispatching": "dispatching",
    "running": "running",
    "waiting_human": "waiting_human",
    "succeeded": "succeeded",
    "failed": "failed",
    "blocked": "blocked",
    "cancelled": "cancelled",
    "stale": "stale",
    "skipped": "cancelled",
}

_EVENT_TYPE = {
    "run.queued": "run_created",
    "run.created": "run_created",
}


def apply_migration(
    data_root: Path,
    *,
    project_root: Path,
    backup_root: Path,
    workspace_root: Path | None = None,
    ledger_filename: str = "workflow-ledger.sqlite",
) -> dict[str, Any]:
    data_root = Path(data_root)
    backup_root = Path(backup_root)
    inventory = build_inventory(
        data_root,
        project_root=project_root,
        workspace_root=workspace_root,
    )
    unknown = unknown_entries(list(inventory.get("runs") or []))
    if unknown:
        write_manifest(
            data_root,
            {"status": ManifestStatus.FAILED.value, "reason": "unknown_classification"},
        )
        raise ValueError(f"dry-run has {len(unknown)} unknown classifications")

    write_json(migration_dir(data_root) / AUDIT_NAME, inventory)
    write_manifest(data_root, {"status": ManifestStatus.AUDITED.value, "unknownCount": 0})

    backup_meta = _backup_data_root(data_root, backup_root)
    write_manifest(
        data_root,
        {
            "status": ManifestStatus.BACKUP_VERIFIED.value,
            "backup": backup_meta,
            "unknownCount": 0,
        },
    )

    staging = data_root / "migration" / "staging-workflow-ledger.sqlite"
    if staging.exists():
        staging.unlink()
    store = WorkflowLedgerStore(staging)
    store.open()
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    try:
        for entry in inventory.get("runs") or []:
            classification = str(entry.get("classification") or "")
            if classification != "migratable":
                skipped.append(
                    {
                        "runId": entry.get("runId"),
                        "classification": classification,
                    }
                )
                continue
            record = _read_record(Path(str(entry["file"])))
            if record is None:
                skipped.append(
                    {
                        "runId": entry.get("runId"),
                        "classification": "corrupt",
                        "reason": "unreadable_after_audit",
                    }
                )
                continue
            counts = _import_record(store, record)
            imported.append({"runId": record.get("runId"), **counts})
    except Exception:
        store.close()
        write_manifest(
            data_root,
            {"status": ManifestStatus.FAILED.value, "reason": "import_failed"},
        )
        raise

    store.close()
    live = data_root / ledger_filename
    if live.exists():
        live.unlink()
    staging.replace(live)

    apply_report = {
        "schemaVersion": 1,
        "importedCount": len(imported),
        "skipped": skipped,
        "imported": imported,
        "backup": backup_meta,
        "ledgerRelativePath": ledger_filename,
        "lineageHash": _lineage_hash(imported),
    }
    write_json(migration_dir(data_root) / APPLY_NAME, apply_report)
    write_manifest(
        data_root,
        {
            "status": ManifestStatus.IMPORTED.value,
            "importedCount": len(imported),
            "lineageHash": apply_report["lineageHash"],
            "ledgerRelativePath": ledger_filename,
            "backup": backup_meta,
        },
    )
    return apply_report


def _backup_data_root(data_root: Path, backup_root: Path) -> dict[str, Any]:
    backup_root = Path(backup_root)
    if backup_root.exists():
        shutil.rmtree(backup_root)
    shutil.copytree(data_root, backup_root, dirs_exist_ok=False)
    digest = hashlib.sha256()
    file_count = 0
    for path in sorted(backup_root.rglob("*")):
        if not path.is_file():
            continue
        file_count += 1
        relative = path.relative_to(backup_root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(path.read_bytes())
    if file_count == 0:
        raise ValueError("backup is empty")
    return {
        "path": str(backup_root),
        "fileCount": file_count,
        "sha256": digest.hexdigest(),
        "readable": True,
    }


def _read_record(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _import_record(store: WorkflowLedgerStore, record: Mapping[str, Any]) -> dict[str, int]:
    run = _run_record(record)
    events = _event_records(record, run)
    attempts = _attempt_records(record, run)

    def mutate(uow) -> None:
        uow.repository.insert_run(run)
        for attempt in attempts:
            uow.repository.insert_command(_migrated_command(run, attempt))
            uow.repository.insert_attempt(attempt)
            target = _ATTEMPT_STATUS.get(str(_node_status(record, attempt.node_run_id)), "starting")
            _walk_attempt(uow.repository, attempt.node_run_id, target)
        for event in events:
            uow.repository.insert_event(event)
        for handoff in record.get("handoffs") or []:
            if not isinstance(handoff, dict):
                continue
            _import_handoff(uow.repository, run.run_id, handoff)

    store.submit(mutate, force_flush=True).result(timeout=30)
    return {
        "eventCount": len(events),
        "attemptCount": len(attempts),
        "handoffCount": len(record.get("handoffs") or []),
    }


def _run_record(record: Mapping[str, Any]) -> RunRecord:
    created_ms = _parse_ms(record.get("createdAt"))
    updated_ms = _parse_ms(record.get("updatedAt")) or created_ms
    snapshot = record.get("inputSnapshot") if isinstance(record.get("inputSnapshot"), dict) else {}
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    safety = snapshot.get("budgetPolicy") if isinstance(snapshot.get("budgetPolicy"), dict) else {}
    status = _RUN_STATUS.get(str(record.get("status") or ""), "created")
    events = record.get("events") if isinstance(record.get("events"), list) else []
    return RunRecord(
        run_id=str(record.get("runId") or ""),
        team_id=str(record.get("teamId") or ""),
        workflow_id=str(record.get("workflowId") or ""),
        workflow_version_id=str(record.get("workflowVersionId") or ""),
        thread_id=str(record.get("threadId") or f"thread-{record.get('runId')}"),
        project_id=str(record.get("projectId") or ""),
        question_id=str(record.get("questionId") or ""),
        status=status,
        run_version=max(1, int(record.get("runVersion") or 1)),
        last_event_sequence=len(events),
        input_snapshot_json=snapshot_json,
        input_snapshot_hash=str(snapshot.get("snapshotHash") or record.get("structureHash") or ("a" * 64)),
        safety_limits_json=json.dumps(safety, ensure_ascii=False, sort_keys=True),
        binding_snapshot_set_id=str(
            ((record.get("bindingSnapshots") or [{}])[0] or {}).get("snapshotId")
            or "binding-migrated"
        ),
        active_node_id=_active_node_id(record),
        parent_run_id=None,
        forked_from_checkpoint_id=None,
        completion_kind=str(record.get("completionKind") or "") or None,
        terminal_reason=str(record.get("terminalReason") or "") or None,
        blocked_problem_json=None,
        created_at_ms=created_ms,
        updated_at_ms=updated_ms,
        completed_at_ms=updated_ms if status in {"succeeded", "failed", "cancelled", "archived"} else None,
    )


def _event_records(record: Mapping[str, Any], run: RunRecord) -> list[EventRecord]:
    events: list[EventRecord] = []
    raw_events = record.get("events") if isinstance(record.get("events"), list) else []
    for index, item in enumerate(raw_events, start=1):
        if not isinstance(item, dict):
            continue
        event_type = str(item.get("type") or "run_created")
        events.append(
            EventRecord(
                run_id=run.run_id,
                sequence=int(item.get("sequence") or index),
                event_id=str(item.get("eventId") or f"evt-migrated-{run.run_id}-{index}"),
                run_version=run.run_version,
                event_type=_EVENT_TYPE.get(event_type, event_type.replace(".", "_")),
                actor_json=json.dumps({"actorType": "system", "actorId": "migration"}),
                correlation_id=str(item.get("eventId") or f"corr-{run.run_id}-{index}"),
                causation_id=None,
                payload_json=json.dumps(item.get("summary") or {}, ensure_ascii=False),
                occurred_at_ms=_parse_ms(item.get("occurredAt")) or run.created_at_ms,
            )
        )
    return events


def _attempt_records(record: Mapping[str, Any], run: RunRecord) -> list[NodeAttemptRecord]:
    attempts: list[NodeAttemptRecord] = []
    for item in record.get("nodeRuns") or []:
        if not isinstance(item, dict):
            continue
        node_run_id = str(item.get("nodeRunId") or "")
        if not node_run_id:
            continue
        actor = str(item.get("actorType") or item.get("actorKind") or "agent")
        if actor not in {"agent", "system", "human"}:
            actor = "agent"
        started = _parse_ms(item.get("startedAt")) or run.created_at_ms
        attempts.append(
            NodeAttemptRecord(
                node_run_id=node_run_id,
                run_id=run.run_id,
                node_id=str(item.get("nodeId") or "source_finding"),
                attempt=max(1, int(item.get("attempt") or 1)),
                actor_kind=actor,
                status="starting",
                command_id=f"cmd-migrated-{node_run_id}",
                binding_snapshot_id=None,
                input_snapshot_hash=str(item.get("inputSnapshotHash") or run.input_snapshot_hash),
                pending_action_id=None,
                execution_anchor_id=None,
                retry_of_node_run_id=None,
                problem_json=None,
                started_at_ms=started,
                updated_at_ms=started,
                finished_at_ms=_parse_ms(item.get("finishedAt")) or None,
            )
        )
    return attempts


def _import_handoff(repository: Any, run_id: str, handoff: Mapping[str, Any]) -> None:
    handoff_id = str(handoff.get("handoffId") or "")
    from_node_run_id = str(handoff.get("fromNodeRunId") or "")
    if not handoff_id or not from_node_run_id:
        return
    repository.insert_handoff(
        handoff_id=handoff_id,
        run_id=run_id,
        edge_id=str(handoff.get("edgeId") or f"edge-{handoff_id}"),
        from_node_run_id=from_node_run_id,
        to_node_id=str(handoff.get("toNodeId") or ""),
        to_node_run_id=str(handoff.get("toNodeRunId") or "") or None,
        gate_kind=str(handoff.get("gateKind") or "auto"),
        input_snapshot_hash=str(handoff.get("inputSnapshotHash") or ("a" * 64)),
        offered_at_ms=_parse_ms(handoff.get("offeredAt")) or 0,
    )
    target = str(handoff.get("status") or "pending")
    _walk_handoff(repository, handoff_id, target)


def _migrated_command(run: RunRecord, attempt: NodeAttemptRecord) -> CommandRecord:
    return CommandRecord(
        command_id=attempt.command_id,
        run_id=run.run_id,
        team_id=run.team_id,
        node_id=attempt.node_id,
        command_kind="start_node",
        expected_run_version=run.run_version,
        accepted_run_version=run.run_version,
        idempotency_key=f"migrate:{attempt.node_run_id}",
        request_hash="m" * 64,
        request_json=json.dumps({"command": "start_node", "nodeId": attempt.node_id}),
        requested_by_json=json.dumps({"actorType": "system", "actorId": "migration"}),
        status="accepted",
        result_json=None,
        problem_json=None,
        created_at_ms=attempt.started_at_ms,
        completed_at_ms=None,
    )


def _walk_attempt(repository: Any, node_run_id: str, target: str) -> None:
    current = NodeAttemptStatus.STARTING
    wanted = NodeAttemptStatus(target) if target in {item.value for item in NodeAttemptStatus} else NodeAttemptStatus.STARTING
    for status in _bfs_attempt(current, wanted):
        if status == current:
            continue
        repository.update_attempt_status(node_run_id, status.value, now_ms=0)
        current = status


def _walk_handoff(repository: Any, handoff_id: str, target: str) -> None:
    current = HandoffStatus.PENDING
    wanted = HandoffStatus(target) if target in {item.value for item in HandoffStatus} else HandoffStatus.PENDING
    for status in _bfs_handoff(current, wanted):
        if status == current:
            continue
        repository.update_handoff_status(handoff_id, status.value, now_ms=0)
        current = status


def _bfs_attempt(start: NodeAttemptStatus, goal: NodeAttemptStatus) -> list[NodeAttemptStatus]:
    return _bfs(start, goal, can_transition_node_attempt, list(NodeAttemptStatus))


def _bfs_handoff(start: HandoffStatus, goal: HandoffStatus) -> list[HandoffStatus]:
    return _bfs(start, goal, can_transition_handoff, list(HandoffStatus))


def _bfs(start: Any, goal: Any, allowed, values: list[Any]) -> list[Any]:
    if start == goal:
        return [start]
    queue: list[list[Any]] = [[start]]
    seen = {start}
    while queue:
        path = queue.pop(0)
        current = path[-1]
        for candidate in values:
            if candidate in seen or not allowed(current, candidate):
                continue
            next_path = path + [candidate]
            if candidate == goal:
                return next_path
            seen.add(candidate)
            queue.append(next_path)
    return [start]


def _active_node_id(record: Mapping[str, Any]) -> str | None:
    current = record.get("runtimeCurrentNodeIds") or []
    if isinstance(current, list) and current:
        return str(current[0])
    return None


def _node_status(record: Mapping[str, Any], node_run_id: str) -> str:
    for item in record.get("nodeRuns") or []:
        if isinstance(item, dict) and str(item.get("nodeRunId") or "") == node_run_id:
            return str(item.get("status") or "ready")
    return "ready"


def _parse_ms(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _lineage_hash(imported: list[dict[str, Any]]) -> str:
    canonical = json.dumps(imported, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
