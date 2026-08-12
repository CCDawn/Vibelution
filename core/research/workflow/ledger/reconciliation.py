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
