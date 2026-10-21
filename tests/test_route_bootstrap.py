from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from core.web.route_bootstrap import register_spa_routes
from core.web.middleware.wait_for_routes import WaitForWebRoutesMiddleware


def test_shell_and_assets_are_served_while_api_waits_for_bootstrap(tmp_path, monkeypatch):
    from core.web import route_bootstrap
    from core.web.router_registry import register_web_routers_from_modules

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
    (dist / "assets" / "app.js").write_text("window.shellLoaded = true", encoding="utf-8")
    app = FastAPI()
    app.state.web_routes_registered = False
    app.state.web_routes_error = ""
    app.add_middleware(WaitForWebRoutesMiddleware, timeout_seconds=1)
    register_spa_routes(app, web_dist=dist)
    shell_routes = app.state.web_shell_routes
    assert app.state.web_shell_ready is True

    async def exercise():
        app.state.web_routes_ready_event = asyncio.Event()
        waiting = asyncio.Event()
        original_wait = route_bootstrap.wait_for_web_routes

        async def observe_wait(*args, **kwargs):
            waiting.set()
            return await original_wait(*args, **kwargs)

        monkeypatch.setattr("core.web.middleware.wait_for_routes.wait_for_web_routes", observe_wait)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
            assert (await client.get("/chat")).status_code == 200
            assert (await client.get("/assets/app.js")).text == "window.shellLoaded = true"
            assert (await client.get("/assets/missing.js")).status_code == 404
            assert "no-store" in (await client.get("/")).headers["cache-control"]
            pending = asyncio.create_task(client.get("/api/probe"))
            await asyncio.wait_for(waiting.wait(), 1)
            assert not pending.done()
            api = APIRouter()

            @api.get("/probe")
            def probe():
                return {"ready": True}

            register_web_routers_from_modules(app, [SimpleNamespace(router=api)])
            register_spa_routes(app)
            assert app.state.web_shell_routes is shell_routes
            assert sum(route in shell_routes for route in app.routes) == 2
            route_bootstrap._mark_routes_ready(app)
            response = await asyncio.wait_for(pending, 1)
            assert response.status_code == 200
            assert response.json() == {"ready": True}

    asyncio.run(exercise())


def test_shell_readiness_rejects_missing_referenced_assets(tmp_path):
    (tmp_path / "index.html").write_text('<script src="/assets/missing.js"></script>', encoding="utf-8")
    app = FastAPI()
    register_spa_routes(app, web_dist=tmp_path)
    assert app.state.web_shell_ready is False
    assert "missing asset" in app.state.web_shell_error


def test_first_frame_reads_work_before_unrelated_imports_finish(monkeypatch):
    from core.web import route_bootstrap
    from core.web.control import CONTROL_TOKEN_HEADER, WebControlGuardMiddleware, get_control_token
    from core.web.services.agent_directory import bootstrap

    app = FastAPI()
    app.state.web_routes_registered = False
    app.add_middleware(WebControlGuardMiddleware)
    app.add_middleware(WaitForWebRoutesMiddleware, timeout_seconds=2)
    initial = APIRouter()
    remaining = APIRouter()
    initialized = []

    @initial.get("/sessions/bootstrap")
    def first_frame():
        assert initialized == [True]
        return {"ready": True}

    @initial.post("/sessions/bootstrap")
    @initial.get("/config/public")
    @remaining.get("/sessions/later/feature")
    def other_operation():
        return {"complete": True}

    def import_modules(*, startup_only=None, **_kwargs):
        return [SimpleNamespace(router=initial if startup_only else remaining)]

    monkeypatch.setattr(route_bootstrap, "import_web_route_modules", import_modules)
    monkeypatch.setattr(route_bootstrap, "register_spa_routes", lambda *a, **k: None)
    monkeypatch.setattr(bootstrap, "initialize_builtin_agent_catalog", lambda: initialized.append(True))

    async def exercise():
        app.state.web_routes_ready_event = asyncio.Event()
        app.state.web_startup_routes_ready_event = asyncio.Event()
        deferred = asyncio.Event()
        release = asyncio.Event()
        waiting = asyncio.Event()
        wait_count = 0
        original_wait = route_bootstrap.wait_for_web_routes

        async def observe_wait(*args, **kwargs):
            nonlocal wait_count
            if not kwargs.get("startup_only"):
                wait_count += 1
                if wait_count == 3:
                    waiting.set()
            return await original_wait(*args, **kwargs)

        async def run_sync(name, callback, *args, **kwargs):
            if name not in {"web-route-import", "builtin-agent-bootstrap"}:
                return None
            if name == "web-route-import" and kwargs.get("startup_only") is False:
                deferred.set()
                await release.wait()
            return callback(*args, **kwargs)

        monkeypatch.setattr("core.web.middleware.wait_for_routes.wait_for_web_routes", observe_wait)
        warming = asyncio.create_task(route_bootstrap.warm_web_routes_in_background(app, run_sync=run_sync))
        try:
            await asyncio.wait_for(deferred.wait(), 1)
            assert app.state.web_startup_routes_registered
            assert not app.state.web_routes_registered
            headers = {CONTROL_TOKEN_HEADER: get_control_token()}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
                response = await client.get("/api/sessions/bootstrap", headers=headers)
                assert response.json() == {"ready": True}
                assert (await client.get("/api/sessions/bootstrap")).status_code == 403
                invalid_source = {**headers, "Origin": "https://untrusted.invalid"}
                assert (await client.get("/api/sessions/bootstrap", headers=invalid_source)).status_code == 403
                pending = [
                    asyncio.create_task(client.get("/api/config/public", headers=headers)),
                    asyncio.create_task(client.post("/api/sessions/bootstrap", headers=headers)),
                    asyncio.create_task(client.get("/api/sessions/later/feature", headers=headers)),
                ]
                await asyncio.wait_for(waiting.wait(), 1)
                assert not any(task.done() for task in pending)
                release.set()
                await warming
                responses = await asyncio.gather(*pending)
                assert all(response.json() == {"complete": True} for response in responses)
                assert app.state.web_routes_registered
        finally:
            release.set()
            if not warming.done():
                warming.cancel()
            await asyncio.gather(warming, return_exceptions=True)
            for name in ("financial_team_coordinator_task", "financial_job_scheduler_task", "financial_backtest_worker_task"):
                task = getattr(app.state, name, None)
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_partial_registration_can_be_retried_without_duplicate_routes(monkeypatch):
    from core.web.router_registry import register_web_routers_from_modules

    app = FastAPI()
    router = APIRouter()

    @router.get("/config/bootstrap")
    def endpoint():
        return {"ok": True}

    modules = [SimpleNamespace(router=router)]
    mounts = []
    original_mount = app.include_router

    def mount(*args, **kwargs):
        mounts.append(args[0])
        return original_mount(*args, **kwargs)

    monkeypatch.setattr(app, "include_router", mount)
    register_web_routers_from_modules(app, modules)
    register_web_routers_from_modules(app, modules)
    assert mounts == [router]
    assert TestClient(app).get("/api/config/bootstrap").json() == {"ok": True}


def test_startup_import_partition_loads_each_router_once(monkeypatch):
    from core.web import router_registry

    names = []
    monkeypatch.setattr(router_registry, "_import_route_module", lambda name: names.append(name) or name)
    first = router_registry.import_web_route_modules(startup_only=True)
    later = router_registry.import_web_route_modules(startup_only=False)
    assert set(first) == {
        "core.web.routes.config", "core.web.routes.launcher",
        "core.web.routes.runtime", "core.web.routes.sessions",
    }
    assert set(first).isdisjoint(later)
    assert len(names) == len(set(names)) == len(router_registry._ROUTE_MODULE_NAMES)


@pytest.mark.parametrize("fail_startup", [False, True])
def test_import_failure_wakes_waiters_and_retains_only_completed_startup(monkeypatch, fail_startup):
    from core.web import route_bootstrap
    from core.web.services.agent_directory import bootstrap

    app = FastAPI()
    app.state.web_routes_registered = False
    monkeypatch.setattr(bootstrap, "initialize_builtin_agent_catalog", lambda: None)
    monkeypatch.setattr(route_bootstrap, "register_spa_routes", lambda *a, **k: None)

    def fail_sync(*args, **kwargs):
        raise RuntimeError("import unavailable")

    monkeypatch.setattr(route_bootstrap, "ensure_web_routes_registered", fail_sync)

    async def exercise():
        app.state.web_routes_ready_event = asyncio.Event()
        app.state.web_startup_routes_ready_event = asyncio.Event()

        async def run_sync(name, callback, *args, **kwargs):
            if name == "web-route-import":
                if kwargs["startup_only"] is fail_startup:
                    raise RuntimeError("import unavailable")
                return []
            return callback(*args, **kwargs)

        with pytest.raises(RuntimeError, match="import unavailable"):
            await route_bootstrap.warm_web_routes_in_background(app, run_sync=run_sync)
        assert app.state.web_routes_ready_event.is_set()
        assert app.state.web_startup_routes_ready_event.is_set()
        assert await route_bootstrap.wait_for_web_routes(app, startup_only=True) is not fail_startup
        assert await route_bootstrap.wait_for_web_routes(app) is False
        assert app.state.web_routes_registered is False

    asyncio.run(exercise())


def test_missing_hashed_asset_is_served_from_retained_release(tmp_path):
    releases_dir = tmp_path / ".vibelution-builds"
    retained = releases_dir / "release-retained"
    current = releases_dir / "release-current"
    (retained / "assets").mkdir(parents=True)
    (current / "assets").mkdir(parents=True)
    (retained / "index.html").write_text("retained shell", encoding="utf-8")
    (current / "index.html").write_text("current shell", encoding="utf-8")
    (retained / "assets" / "AgentContextSectionsView-CeXSITa3.js").write_text("retained chunk", encoding="utf-8")
    (current / "assets" / "AgentContextSectionsView-C6H2VnC4.js").write_text("current chunk", encoding="utf-8")
    (retained / "retained.txt").write_text("not an asset", encoding="utf-8")

    app = FastAPI()
    register_spa_routes(app, web_dist=current)
    client = TestClient(app)

    retained_response = client.get("/assets/AgentContextSectionsView-CeXSITa3.js")
    current_response = client.get("/assets/AgentContextSectionsView-C6H2VnC4.js")
    unknown_response = client.get("/assets/AgentContextSectionsView-UNKNOWN.js")
    outside_assets_response = client.get("/retained.txt")

    assert retained_response.status_code == 200
    assert retained_response.text == "retained chunk"
    assert current_response.status_code == 200
    assert current_response.text == "current chunk"
    assert unknown_response.status_code == 404
    assert outside_assets_response.status_code == 404


@pytest.mark.parametrize("background", [False, True])
def test_agent_assets_exist_before_functional_routes_become_ready(monkeypatch, background):
    from core.web import route_bootstrap
    from core.web.services.agent_directory import bootstrap
    app = FastAPI()
    app.state.web_routes_registered = False
    calls = []

    def seed():
        assert not app.state.web_routes_registered
        calls.append("agents")

    monkeypatch.setattr(route_bootstrap, "import_web_route_modules", lambda **kwargs: [])
    monkeypatch.setattr(route_bootstrap, "register_web_routers_from_modules", lambda *args: calls.append("routes"))
    monkeypatch.setattr(route_bootstrap, "register_spa_routes", lambda *args, **kwargs: None)
    monkeypatch.setattr(route_bootstrap, "_log_routes_bootstrap_summary", lambda payload: None)
    monkeypatch.setattr(bootstrap, "initialize_builtin_agent_catalog", seed)
    if background:
        asyncio.run(route_bootstrap.warm_web_routes_in_background(app))
    else:
        route_bootstrap.ensure_web_routes_registered(app)
    assert calls == ["agents", "routes"]
    assert app.state.web_routes_registered


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
        backtest_task = app.state.financial_backtest_worker_task
        assert first_result["alreadyReady"] is True
        await asyncio.wait_for(started.wait(), timeout=1)

        second_result = await route_bootstrap.warm_web_routes_in_background(
            app, run_sync=fake_run_sync
        )
        assert second_result["alreadyReady"] is True
        assert app.state.financial_team_coordinator_task is owner_task
        assert app.state.financial_job_scheduler_task is scheduler_task
        assert app.state.financial_backtest_worker_task is backtest_task
        assert sorted(calls) == ["financial-ai-backtest-worker", "financial-job-scheduler", "financial-team-coordinator"]

        release.set()
        await owner_task
        await scheduler_task
        await backtest_task

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
    assert not hasattr(app.state, "financial_backtest_worker_task")
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
    assert not hasattr(app.state, "financial_backtest_worker_task")
    assert coordinator_calls == []
