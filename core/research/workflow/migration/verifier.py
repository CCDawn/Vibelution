"""Verify imported Ledger counts/hash/lineage against the apply report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from core.research.workflow.ledger import WorkflowLedgerStore

from .manifest import (
    APPLY_NAME,
    VERIFY_NAME,
    ManifestStatus,
    load_manifest,
    migration_dir,
    write_json,
    write_manifest,
)


def verify_migration(data_root: Path, *, ledger_filename: str = "workflow-ledger.sqlite") -> dict[str, Any]:
    data_root = Path(data_root)
    apply_path = migration_dir(data_root) / APPLY_NAME
    if not apply_path.exists():
        raise FileNotFoundError(f"missing apply report: {apply_path}")
    apply_report = json.loads(apply_path.read_text(encoding="utf-8"))
    ledger_path = data_root / str(apply_report.get("ledgerRelativePath") or ledger_filename)
    if not ledger_path.exists():
        raise FileNotFoundError(f"missing ledger database: {ledger_path}")

    store = WorkflowLedgerStore(ledger_path, queue_size=8, enqueue_timeout_ms=100)
    store.open()
    try:
        imported = list(apply_report.get("imported") or [])
        observed: list[dict[str, Any]] = []
        for item in imported:
            run_id = str(item.get("runId") or "")
            run = store.get_run(run_id)
            if run is None:
                raise ValueError(f"imported run missing from ledger: {run_id}")
            events = store.list_events(run_id, after_sequence=0, limit=10_000)
            attempts = store.list_attempts(run_id)
            handoffs = store.read(lambda repo: repo.list_handoffs_for_run(run_id))
            observed.append(
                {
                    "runId": run_id,
                    "eventCount": len(events),
                    "attemptCount": len(attempts),
                    "handoffCount": len(handoffs),
                }
            )
            if int(item.get("eventCount") or 0) != len(events):
                raise ValueError(f"event count mismatch for {run_id}")
            if int(item.get("attemptCount") or 0) != len(attempts):
                raise ValueError(f"attempt count mismatch for {run_id}")
            if int(item.get("handoffCount") or 0) != len(handoffs):
                raise ValueError(f"handoff count mismatch for {run_id}")
    finally:
        store.close()

    lineage_hash = hashlib.sha256(
        json.dumps(observed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    expected_hash = str(apply_report.get("lineageHash") or "")
    if lineage_hash != expected_hash:
        raise ValueError("lineage hash mismatch")

    report = {
        "schemaVersion": 1,
        "ok": True,
        "importedCount": len(observed),
        "lineageHash": lineage_hash,
        "observed": observed,
    }
    write_json(migration_dir(data_root) / VERIFY_NAME, report)
    manifest = load_manifest(data_root)
    write_manifest(
        data_root,
        {
            **manifest,
            "status": ManifestStatus.ACTIVATED.value,
            "lineageHash": lineage_hash,
            "importedCount": len(observed),
        },
    )
    return report
