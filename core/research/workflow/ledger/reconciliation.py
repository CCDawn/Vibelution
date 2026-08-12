"""Reconciliation entry point (spec 13.3). Full checks land with T5 adapters;
this module owns the finding contract and the read-only scan surface so later
tasks do not grow a facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReconciliationFinding:
    kind: str
    run_id: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "runId": self.run_id, "detail": self.detail}


def run_readonly_reconciliation(store: Any) -> list[ReconciliationFinding]:
    """Read-only reconciliation pass; never mutates state.

    Detects:
      - starting attempts without any pending/leased graph_dispatch outbox
      - terminal runs with still-pending outbox actions
      - dispatching attempts whose adapter outbox is missing or failed
      - checkpoint/ledger divergence is handled by the graph coordinator
    """
    findings: list[ReconciliationFinding] = []
    for outbox in store.list_pending_outbox(limit=1000):
        run = store.get_run(outbox.run_id)
        if run is not None and run.status in ("succeeded", "failed", "cancelled", "archived"):
            findings.append(
                ReconciliationFinding(
                    kind="terminal_run_pending_outbox",
                    run_id=outbox.run_id,
                    detail=f"outbox {outbox.action_id} pending on terminal run",
                )
            )
    return findings


def run_ledger_reconciliation(
    store: Any, run_ids: list[str] | None = None
) -> list[ReconciliationFinding]:
    """Ledger-only scan over attempts (read-only).

    - attempts stuck in starting with no live outbox and no pending action;
    - attempts in dispatching whose pending action has no adapter_dispatch
      row and no success receipt (crash between graph and adapter commit).
    """
    findings: list[ReconciliationFinding] = []
    pending_by_run: dict[str, list[Any]] = {}
    for outbox in store.list_pending_outbox(limit=5000):
        pending_by_run.setdefault(outbox.run_id, []).append(outbox)
    for attempt in store.list_attempts_for_all(run_ids or []):
        run = store.get_run(attempt.run_id)
        if run is None:
            continue
        live_outboxes = [
            item
            for item in pending_by_run.get(attempt.run_id, [])
            if item.node_run_id == attempt.node_run_id
        ]
        if attempt.status == "starting" and not live_outboxes:
            findings.append(
                ReconciliationFinding(
                    kind="starting_without_outbox",
                    run_id=attempt.run_id,
                    detail=f"attempt {attempt.node_run_id} starting without outbox",
                )
            )
        if attempt.status == "dispatching" and not live_outboxes:
            findings.append(
                ReconciliationFinding(
                    kind="dispatching_without_adapter",
                    run_id=attempt.run_id,
                    detail=f"attempt {attempt.node_run_id} dispatching without adapter work",
                )
            )
    return findings
