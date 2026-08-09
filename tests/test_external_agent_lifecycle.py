from __future__ import annotations

import asyncio

import pytest

from core.web import lifecycle


def test_startup_reconcile_uses_backend_task_projection(monkeypatch) -> None:
    calls: list[str] = []

    class FakeService:
        def reconcile(self):
            calls.append("reconcile")
            return [{"taskId": "eat-1", "status": "running"}]

    monkeypatch.setattr(
        "core.web.services.external_agent.service.get_default_service",
        lambda _root: FakeService(),
    )

    result = lifecycle.reconcile_external_agent_tasks_once()

    assert result == [{"taskId": "eat-1", "status": "running"}]
    assert calls == ["reconcile"]


@pytest.mark.anyio
async def test_reconcile_loop_runs_until_backend_lifespan_cancels_it(
    monkeypatch,
) -> None:
    called = asyncio.Event()

    def reconcile_once():
        called.set()
        return []

    monkeypatch.setattr(
        lifecycle, "reconcile_external_agent_tasks_once", reconcile_once
    )
    task = asyncio.create_task(
        lifecycle.reconcile_external_agent_tasks_forever(interval_seconds=0.01)
    )
    await asyncio.wait_for(called.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.anyio
async def test_reconcile_loop_recovers_after_one_iteration_failure(monkeypatch) -> None:
    recovered = asyncio.Event()
    attempts = 0

    def reconcile_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary reconcile failure")
        recovered.set()
        return []

    monkeypatch.setattr(
        lifecycle, "reconcile_external_agent_tasks_once", reconcile_once
    )
    task = asyncio.create_task(
        lifecycle.reconcile_external_agent_tasks_forever(interval_seconds=0.01)
    )
    await asyncio.wait_for(recovered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert attempts >= 2
