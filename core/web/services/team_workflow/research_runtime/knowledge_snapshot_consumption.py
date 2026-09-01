"""Durable, replay-idempotent knowledge snapshot consumption events."""

from __future__ import annotations

import json
import re
from typing import Any

from core.research.workflow.ledger import EventRecord, WorkflowLedgerStore

from .human_gate_artifacts import canonical_sha256

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def record_knowledge_snapshot_consumed(
    store: WorkflowLedgerStore,
    *,
    run_id: str,
    node_run_id: str,
    selection_id: str,
    snapshot_hash: str,
    now_ms: int,
) -> bool:
    """Append one parent-run consumption fact for a composite snapshot."""

    normalized_run_id = str(run_id or "").strip()
    normalized_node_run_id = str(node_run_id or "").strip()
    normalized_selection_id = str(selection_id or "").strip()
    normalized_hash = str(snapshot_hash or "").strip().lower()
    if (
        not normalized_run_id
        or not normalized_node_run_id
        or not normalized_selection_id
        or _SHA256.fullmatch(normalized_hash) is None
    ):
        raise ValueError("knowledge snapshot consumption identity is incomplete")
    identity = canonical_sha256(
        {"runId": normalized_run_id, "snapshotHash": normalized_hash}
    )
    event_id = f"evt-knowledge-snapshot-consumed-{identity[:32]}"

    def mutate(uow: Any) -> bool:
        if uow.repository.get_event_by_id(event_id) is not None:
            return False
        run = uow.repository.get_run(normalized_run_id)
        if run is None:
            raise ValueError("knowledge snapshot consumer run was not found")
        sequence = uow.repository.advance_last_sequence(
            normalized_run_id, 1, int(now_ms)
        )
        uow.repository.insert_event(
            EventRecord(
                run_id=normalized_run_id,
                sequence=sequence,
                event_id=event_id,
                run_version=int(run.run_version),
                event_type="knowledge_snapshot_consumed",
                actor_json=json.dumps(
                    {"actorType": "system", "actorId": "hypothesis-fanout"},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                correlation_id=normalized_node_run_id,
                causation_id=None,
                payload_json=json.dumps(
                    {
                        "nodeRunId": normalized_node_run_id,
                        "selectionId": normalized_selection_id,
                        "snapshotHash": normalized_hash,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                occurred_at_ms=int(now_ms),
            )
        )
        return True

    inserted = bool(store.submit(mutate, force_flush=True).result(timeout=30))
    if inserted:
        _record_snapshot_scene(
            run_id=normalized_run_id,
            node_run_id=normalized_node_run_id,
            snapshot_hash=normalized_hash,
        )
    return inserted


def _record_snapshot_scene(*, run_id: str, node_run_id: str, snapshot_hash: str) -> None:
    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow_orchestration",
            "knowledge_snapshot_consumption",
            "knowledge_sideflow.snapshot_consumed",
            level="info",
            outcome="success",
            fields={
                "runId": run_id,
                "nodeRunId": node_run_id,
                "snapshotHash": snapshot_hash,
            },
        )
    except Exception:
        pass


__all__ = ["record_knowledge_snapshot_consumed"]
