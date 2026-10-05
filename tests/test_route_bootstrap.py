from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI

from core.web.route_bootstrap import register_spa_routes


def test_register_spa_routes_fails_closed_when_pinned_release_disappears(tmp_path: Path) -> None:
    app = FastAPI()
    app.state.serving_frontend_dist = str(tmp_path / "release-missing")

    with pytest.raises(RuntimeError, match="Pinned serving frontend release is unavailable"):
        register_spa_routes(app)


def test_register_spa_routes_accepts_explicit_test_dist_even_without_pinned_state(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    app = FastAPI()
    app.state.serving_frontend_dist = str(tmp_path / "release-missing")

    register_spa_routes(app, web_dist=dist)

    assert len(app.routes) >= 2


def test_ready_routes_start_financial_coordinator_only_once(monkeypatch) -> None:
    from core.web import route_bootstrap

    app = FastAPI()
    app.state.web_routes_registered = True
    app.state.web_routes_error = ""

    async def exercise() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        calls: list[str] = []

        async def fake_run_sync(name, _callback, *args, **kwargs):
            calls.append(name)
            started.set()
            await release.wait()

        first_result = await route_bootstrap.warm_web_routes_in_background(
            app, run_sync=fake_run_sync
        )
        owner_task = app.state.financial_team_coordinator_task
        scheduler_task = app.state.financial_job_scheduler_task
        assert first_result["alreadyReady"] is True
        await asyncio.wait_for(started.wait(), timeout=1)

        second_result = await route_bootstrap.warm_web_routes_in_background(
            app, run_sync=fake_run_sync
        )
        assert second_result["alreadyReady"] is True
        assert app.state.financial_team_coordinator_task is owner_task
        assert app.state.financial_job_scheduler_task is scheduler_task
        assert sorted(calls) == ["financial-job-scheduler", "financial-team-coordinator"]

        release.set()
        await owner_task
        await scheduler_task

    asyncio.run(exercise())


def test_failed_or_error_marked_routes_do_not_start_financial_coordinator(monkeypatch) -> None:
    from core.web import route_bootstrap

    app = FastAPI()
    app.state.web_routes_registered = False
    app.state.web_routes_error = ""
    coordinator_calls: list[str] = []

    async def fake_run_sync(name, _callback, *args, **kwargs):
        if name == "web-route-import":
            raise RuntimeError("route import failed")
        coordinator_calls.append(name)

    async def exercise_failed_mount() -> None:
        with pytest.raises(RuntimeError, match="route import failed"):
            await route_bootstrap.warm_web_routes_in_background(
                app, run_sync=fake_run_sync
            )

    asyncio.run(exercise_failed_mount())
    assert app.state.web_routes_registered is False
    assert "route import failed" in app.state.web_routes_error
    assert not hasattr(app.state, "financial_team_coordinator_task")
    assert not hasattr(app.state, "financial_job_scheduler_task")
    assert coordinator_calls == []

    app.state.web_routes_registered = True
    app.state.web_routes_error = "previous route error"

    async def exercise_error_ready_state() -> None:
        await route_bootstrap.warm_web_routes_in_background(
            app, run_sync=fake_run_sync
        )
        await asyncio.sleep(0)

    asyncio.run(exercise_error_ready_state())
    assert not hasattr(app.state, "financial_team_coordinator_task")
    assert not hasattr(app.state, "financial_job_scheduler_task")
    assert coordinator_calls == []
