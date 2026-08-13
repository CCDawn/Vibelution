"""Production outbox pump must lease graph_dispatch without a manual run_once."""

from __future__ import annotations

import time
from pathlib import Path

from core.web.services.team_workflow.research_runtime.outbox_pump import (
    WorkflowOutboxPump,
)


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[int] = []
        self._remaining = 2

    def run_workers_once(self, limit: int = 4) -> int:
        self.calls.append(limit)
        if self._remaining <= 0:
            return 0
        self._remaining -= 1
        return 1


def test_outbox_pump_drains_until_idle_on_wake() -> None:
    runtime = _FakeRuntime()
    pump = WorkflowOutboxPump(idle_poll_s=0.05, batch_limit=8)
    pump.attach(runtime)
    try:
        deadline = time.time() + 2
        while time.time() < deadline and len(runtime.calls) < 3:
            time.sleep(0.02)
        assert runtime.calls[:3] == [8, 8, 8]
        assert runtime.calls[0] == 8
    finally:
        pump.stop()


def test_outbox_pump_stop_is_idempotent() -> None:
    pump = WorkflowOutboxPump(idle_poll_s=0.05)
    pump.attach(_FakeRuntime())
    pump.stop()
    pump.stop()
