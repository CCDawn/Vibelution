from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from core.web.route_bootstrap import register_spa_routes
from core.web.middleware.wait_for_routes import WaitForWebRoutesMiddleware


def test_feature_wait_is_demand_driven_latched_and_cancellable(monkeypatch):
    from core.web import lifecycle, route_bootstrap

    monkeypatch.setattr(lifecycle, "_startup_cache_prewarm_gate_enabled", lambda: True)
    monkeypatch.setattr(lifecycle, "_startup_prewarm_stagger_seconds", lambda: 60.0)

    async def exercise():
        app = FastAPI()
        app.state.web_feature_routes_requested_event = asyncio.Event()
        waiter = asyncio.create_task(route_bootstrap._await_feature_route_demand(app))
        await asyncio.sleep(0)
        assert not waiter.done()
        route_bootstrap.request_feature_routes(app)
        assert await asyncio.wait_for(waiter, 1) >= 0
        # A request that arrived before startup readiness cannot lose its wake.
        assert await asyncio.wait_for(route_bootstrap._await_feature_route_demand(app), 1) >= 0

        app.state.web_feature_routes_requested_event = asyncio.Event()
        waiter = asyncio.create_task(route_bootstrap._await_feature_route_demand(app))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not app.state.web_feature_routes_requested_event.is_set()

    asyncio.run(exercise())


@pytest.mark.parametrize("enabled,timeout", [(True, 0.01), (False, 60.0), (True, 0.0)])
def test_feature_import_wait_has_a_headless_fallback_and_honors_existing_switch(monkeypatch, enabled, timeout):
    from core.web import lifecycle, route_bootstrap

    monkeypatch.setattr(lifecycle, "_startup_cache_prewarm_gate_enabled", lambda: enabled)
    monkeypatch.setattr(lifecycle, "_startup_prewarm_stagger_seconds", lambda: timeout)

    async def exercise():
        app = FastAPI()
        app.state.web_feature_routes_requested_event = asyncio.Event()
        await asyncio.wait_for(route_bootstrap._await_feature_route_demand(app), 1)
        assert not app.state.web_feature_routes_requested_event.is_set()

    asyncio.run(exercise())


@pytest.mark.parametrize("wake_path", ["/api/feature-demand", "/api/runtime/summary"])
def test_startup_reads_do_not_import_features_until_an_actual_request(monkeypatch, wake_path):
    from core.web import lifecycle, route_bootstrap
    from core.web.services.agent_directory import bootstrap

    monkeypatch.setattr(lifecycle, "_startup_cache_prewarm_gate_enabled", lambda: True)
    monkeypatch.setattr(lifecycle, "_startup_prewarm_stagger_seconds", lambda: 60.0)
    monkeypatch.setattr(bootstrap, "initialize_builtin_agent_catalog", lambda: {})
    monkeypatch.setattr(route_bootstrap, "register_spa_routes", lambda *args, **kwargs: None)
    for name in ("_start_financial_team_coordinator", "_start_financial_job_scheduler", "_start_financial_backtest_worker"):
        monkeypatch.setattr(route_bootstrap, name, lambda *args, **kwargs: None)

    startup = APIRouter()
    feature = APIRouter()
    startup.get("/sessions/bootstrap")(lambda: {"startup": True})
    startup.get("/runtime/summary")(lambda: {"summary": True})
    feature.get("/feature-demand")(lambda: {"feature": True})

    async def exercise():
        app = FastAPI()
        app.add_middleware(WaitForWebRoutesMiddleware)
        app.state.web_routes_registered = False
        app.state.web_routes_ready_event = asyncio.Event()
        app.state.web_startup_routes_ready_event = asyncio.Event()
        app.state.web_feature_routes_requested_event = asyncio.Event()
        imported = asyncio.Event()
        release = asyncio.Event()

        async def run_sync(name, callback, *args, **kwargs):
            if name == "web-route-import":
                if kwargs["startup_only"]:
                    return [SimpleNamespace(__name__="core.web.routes.sessions", router=startup)]
                imported.set()
                await release.wait()
                return [SimpleNamespace(router=feature)]
            return callback(*args, **kwargs)

        warming = asyncio.create_task(route_bootstrap.warm_web_routes_in_background(app, run_sync=run_sync))
        request = None
        try:
            await asyncio.wait_for(app.state.web_startup_routes_ready_event.wait(), 1)
            assert not imported.is_set()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
                assert (await client.get("/api/sessions/bootstrap")).json() == {"startup": True}
                assert not imported.is_set()
                request = asyncio.create_task(client.get(wake_path))
                await asyncio.wait_for(imported.wait(), 1)
                assert not app.state.web_routes_registered
                if wake_path == "/api/feature-demand":
                    assert not request.done()
                else:
                    assert (await request).json() == {"summary": True}
                release.set()
                payload = await asyncio.wait_for(warming, 1)
                assert payload["featureDemandWaitMs"] >= 0
                assert app.state.web_routes_registered
                assert (await request).status_code == 200
        finally:
            release.set()
            if not warming.done():
                warming.cancel()
            await asyncio.gather(warming, *([request] if request is not None else []), return_exceptions=True)

    asyncio.run(exercise())


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


def test_shell_bootstrap_reads_do_not_wait_for_catalog_but_session_reads_do(tmp_path, monkeypatch):
    from core.web import route_bootstrap
    from core.web.control import CONTROL_TOKEN_HEADER, WebControlGuardMiddleware, get_control_token
    from core.web.services.agent_directory import bootstrap

    app = FastAPI()
    app.state.web_routes_registered = False
    app.add_middleware(WebControlGuardMiddleware)
    app.add_middleware(WaitForWebRoutesMiddleware, timeout_seconds=2)
    (tmp_path / "index.html").write_text("shell", encoding="utf-8")
    register_spa_routes(app, web_dist=tmp_path)
    mounts = []
    original_include = app.include_router

    def include(router, **kwargs):
        mounts.append(router)
        return original_include(router, **kwargs)

    monkeypatch.setattr(app, "include_router", include)
    config = APIRouter()
    launcher = APIRouter()
    sessions = APIRouter()
    initialized = []

    @config.api_route("/config/bootstrap", methods=["GET", "HEAD"])
    @launcher.api_route("/launcher/current-instance", methods=["GET", "HEAD"])
    def shell_read():
        return {"shell": True}

    @config.get("/config/avatar-image/{filename}")
    @config.get("/config/theme-background-image/{filename}")
    def image_read(filename: str):
        assert initialized == []
        return {"image": filename}

    @sessions.get("/sessions/bootstrap")
    def session_read():
        assert initialized == [True]
        return {"sessions": True}

    @config.get("/config/public")
    @config.post("/config/bootstrap")
    @config.get("/config/bootstrap/extra")
    @launcher.get("/launcher/status")
    def full_read():
        return {"full": True}

    startup_modules = [
        SimpleNamespace(__name__="core.web.routes.config", router=config),
        SimpleNamespace(__name__="core.web.routes.launcher", router=launcher),
        SimpleNamespace(__name__="core.web.routes.sessions", router=sessions),
    ]
    monkeypatch.setattr(bootstrap, "initialize_builtin_agent_catalog", lambda: initialized.append(True))

    async def exercise():
        for name in ("web_routes_ready_event", "web_startup_routes_ready_event", "web_bootstrap_routes_ready_event"):
            setattr(app.state, name, asyncio.Event())
        catalog_entered = asyncio.Event()
        release_catalog = asyncio.Event()
        remaining_entered = asyncio.Event()
        release_remaining = asyncio.Event()
        waiting = asyncio.Event()
        wait_count = 0
        original_wait = route_bootstrap.wait_for_web_routes
        pending = []

        async def observe_wait(*args, **kwargs):
            nonlocal wait_count
            if not kwargs.get("bootstrap_only"):
                wait_count += 1
                if wait_count == 5:
                    waiting.set()
            return await original_wait(*args, **kwargs)

        async def run_sync(name, callback, *args, **kwargs):
            if name == "web-route-import":
                if kwargs["startup_only"]:
                    return startup_modules
                remaining_entered.set()
                await release_remaining.wait()
                return []
            if name == "builtin-agent-bootstrap":
                catalog_entered.set()
                await release_catalog.wait()
                return callback(*args, **kwargs)
            return None

        monkeypatch.setattr("core.web.middleware.wait_for_routes.wait_for_web_routes", observe_wait)
        warming = asyncio.create_task(route_bootstrap.warm_web_routes_in_background(app, web_dist=tmp_path, run_sync=run_sync))
        try:
            await asyncio.wait_for(catalog_entered.wait(), 1)
            assert app.state.web_bootstrap_routes_registered
            assert not getattr(app.state, "web_startup_routes_registered", False)
            headers = {CONTROL_TOKEN_HEADER: get_control_token()}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
                for path in ("/api/config/bootstrap", "/api/launcher/current-instance"):
                    assert (await client.get(path, headers=headers)).json() == {"shell": True}
                    assert (await client.head(path, headers=headers)).status_code == 200
                    assert (await client.get(path)).status_code == 403
                    assert (await client.get(path, headers={**headers, "Origin": "https://untrusted.invalid"})).status_code == 403
                assert initialized == []
                for path in (
                    "/api/config/avatar-image/avatar.png",
                    "/api/config/theme-background-image/background.png",
                ):
                    assert (await client.get(path)).status_code == 200
                    assert (await client.get(path, headers={"Origin": "https://untrusted.invalid"})).status_code == 403
                    assert not route_bootstrap.is_bootstrap_route_path(path, method="POST")
                    assert not route_bootstrap.is_bootstrap_route_path(path + "/extra")
                assert not route_bootstrap.is_bootstrap_route_path("/api/config/theme-background-image")
                pending = [asyncio.create_task(client.request(method, path, headers=headers)) for method, path in (
                    ("GET", "/api/sessions/bootstrap"),
                    ("GET", "/api/config/public"),
                    ("POST", "/api/config/bootstrap"),
                    ("GET", "/api/config/bootstrap/extra"),
                    ("GET", "/api/launcher/status"),
                )]
                await asyncio.wait_for(waiting.wait(), 1)
                assert not any(task.done() for task in pending)
                release_catalog.set()
                await asyncio.wait_for(remaining_entered.wait(), 1)
                assert (await asyncio.wait_for(pending[0], 1)).json() == {"sessions": True}
                assert not any(task.done() for task in pending[1:])
                release_remaining.set()
                await warming
                assert all(response.json() == {"full": True} for response in await asyncio.gather(*pending[1:]))
                assert mounts.count(config) == mounts.count(launcher) == mounts.count(sessions) == 1
        finally:
            release_catalog.set()
            release_remaining.set()
            if not warming.done():
                warming.cancel()
            await asyncio.gather(warming, *pending, return_exceptions=True)
            for name in ("financial_team_coordinator_task", "financial_job_scheduler_task", "financial_backtest_worker_task"):
                task = getattr(app.state, name, None)
                if task is not None:
                    await task

    asyncio.run(exercise())


@pytest.mark.parametrize("stage", ["import", "catalog", "remaining"])
@pytest.mark.parametrize("cancel", [False, True])
def test_failed_or_cancelled_warm_releases_waiters_and_preserves_completed_gates(monkeypatch, stage, cancel):
    from core.web import route_bootstrap

    app = FastAPI()
    app.state.web_routes_registered = False
    modules = [SimpleNamespace(__name__="core.web.routes.config", router=APIRouter())]
    monkeypatch.setattr(route_bootstrap, "register_spa_routes", lambda *a, **k: None)
    recoveries = []

    def unavailable(*args, **kwargs):
        recoveries.append(True)
        raise RuntimeError("recovery unavailable")

    monkeypatch.setattr(route_bootstrap, "ensure_web_routes_registered", unavailable)

    async def exercise():
        waiting = asyncio.Event()
        wait_count = 0
        expected_wait_count = {"import": 3, "catalog": 2, "remaining": 1}[stage]

        class ObservedEvent(asyncio.Event):
            async def wait(self):
                nonlocal wait_count
                wait_count += 1
                if wait_count == expected_wait_count:
                    waiting.set()
                return await super().wait()

        for name in ("web_routes_ready_event", "web_startup_routes_ready_event", "web_bootstrap_routes_ready_event"):
            setattr(app.state, name, ObservedEvent())
        entered = asyncio.Event()
        release = asyncio.Event()

        async def run_sync(name, callback, *args, **kwargs):
            current_stage = "catalog" if name == "builtin-agent-bootstrap" else (
                "import" if kwargs.get("startup_only") else "remaining"
            )
            if current_stage == stage:
                entered.set()
                await release.wait()
                raise RuntimeError("warm unavailable")
            return modules if current_stage == "import" else None

        warming = asyncio.create_task(route_bootstrap.warm_web_routes_in_background(app, run_sync=run_sync))
        await asyncio.wait_for(entered.wait(), 1)
        waiters = [asyncio.create_task(route_bootstrap.wait_for_web_routes(app, **kwargs)) for kwargs in (
            {"bootstrap_only": True}, {"startup_only": True}, {},
        )]
        await asyncio.wait_for(waiting.wait(), 1)
        if cancel:
            warming.cancel()
            with pytest.raises(asyncio.CancelledError):
                await warming
        else:
            release.set()
            with pytest.raises(RuntimeError, match="warm unavailable"):
                await warming
        assert await asyncio.wait_for(asyncio.gather(*waiters), 1) == [stage != "import", stage == "remaining", False]
        assert app.state.web_bootstrap_routes_ready_event.is_set()
        assert app.state.web_startup_routes_ready_event.is_set()
        assert app.state.web_routes_ready_event.is_set()
        if cancel:
            assert recoveries == []

    asyncio.run(exercise())


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


def test_chat_operations_work_with_real_router_while_remaining_imports_are_blocked(monkeypatch):
    from core.web import route_bootstrap
    from core.web.control import CONTROL_TOKEN_HEADER, WebControlGuardMiddleware, get_control_token
    from core.web.routes import sessions
    from core.web.services.agent_directory import bootstrap

    app = FastAPI()
    app.state.web_routes_registered = False
    app.add_middleware(WebControlGuardMiddleware)
    app.add_middleware(WaitForWebRoutesMiddleware, timeout_seconds=2)
    calls = []
    initialized = []

    def detail(session_id, **kwargs):
        assert initialized == [True]
        calls.append(("detail", session_id))
        return {"id": session_id, "messages": []}

    def create(**kwargs):
        assert initialized == [True]
        calls.append(("create", kwargs))
        return {"id": "chat-ready"}

    def submit(session_id, content, **kwargs):
        assert initialized == [True]
        calls.append(("send", session_id, content, kwargs))
        return {"accepted": True, "sessionId": session_id, "turnId": "turn-ready"}

    def initial(session_id, mode):
        assert initialized == [True]
        calls.append(("events", session_id, mode))
        return "light", None, {"sessionId": session_id}

    async def events(session_id, **kwargs):
        assert kwargs["initial_state"] == {"sessionId": session_id}
        yield 'event: session_state\ndata: {"sessionId":"chat-ready"}\n\n'

    monkeypatch.setattr(sessions, "get_session_detail", detail)
    monkeypatch.setattr(sessions, "create_chat_session", create)
    monkeypatch.setattr(sessions, "select_chat_session", detail)
    monkeypatch.setattr(sessions, "submit_session_message_lightweight", submit)
    monkeypatch.setattr(sessions, "resolve_session_stream_initial_payload", initial)
    monkeypatch.setattr(sessions, "stream_session_events_async", events)
    monkeypatch.setattr(sessions, "request_stop_session_turn", detail)
    monkeypatch.setattr(sessions, "delete_chat_session", lambda *a, **k: {"deleted": True})
    monkeypatch.setattr(sessions, "list_tool_approval_requests", lambda *a, **k: [])
    monkeypatch.setattr(sessions, "resolve_tool_approval_request", lambda *a, **k: {"requestId": "approval-ready", "status": "resolved"})
    monkeypatch.setattr(sessions, "_record_session_create_request_timing", lambda *a, **k: None)
    monkeypatch.setattr(bootstrap, "initialize_builtin_agent_catalog", lambda: initialized.append(True))
    monkeypatch.setattr(route_bootstrap, "register_spa_routes", lambda *a, **k: None)

    async def exercise():
        app.state.web_routes_ready_event = asyncio.Event()
        app.state.web_startup_routes_ready_event = asyncio.Event()
        deferred = asyncio.Event()
        release = asyncio.Event()
        waiting = asyncio.Event()
        wait_count = 0
        original_wait = route_bootstrap.wait_for_web_routes
        pending = []

        async def observe_wait(*args, **kwargs):
            nonlocal wait_count
            if not kwargs.get("startup_only"):
                wait_count += 1
                if wait_count == 5:
                    waiting.set()
            return await original_wait(*args, **kwargs)

        async def run_sync(name, callback, *args, **kwargs):
            if name == "web-route-import":
                if kwargs.get("startup_only"):
                    return [sessions]
                deferred.set()
                await release.wait()
                return []
            if name == "builtin-agent-bootstrap":
                return callback(*args, **kwargs)
            return None

        monkeypatch.setattr("core.web.middleware.wait_for_routes.wait_for_web_routes", observe_wait)
        warming = asyncio.create_task(route_bootstrap.warm_web_routes_in_background(app, run_sync=run_sync))
        try:
            await asyncio.wait_for(deferred.wait(), 1)
            assert app.state.web_startup_routes_registered
            assert not app.state.web_routes_registered
            headers = {CONTROL_TOKEN_HEADER: get_control_token(), "Prefer": "respond-async"}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
                assert (await client.get("/api/sessions/chat-ready", headers=headers)).json()["id"] == "chat-ready"
                created = await client.post("/api/sessions", headers=headers, json={"title": "Ready"})
                assert created.status_code == 201
                assert created.json()["id"] == "chat-ready"
                assert (await client.post("/api/sessions/chat-ready/select", headers=headers)).status_code == 200
                sent = await client.post("/api/sessions/chat-ready/messages", headers=headers, json={"content": "hello"})
                assert sent.status_code == 202
                assert sent.json()["accepted"] is True
                async with client.stream("GET", "/api/sessions/chat-ready/events", headers=headers) as response:
                    assert response.headers["content-type"].startswith("text/event-stream")
                    payload = await response.aread()
                    assert b"event: session_state" in payload
                    assert b'"sessionId":"chat-ready"' in payload
                assert (await client.post("/api/sessions/chat-ready/stop", headers=headers, json={"turnId": "turn-ready"})).status_code == 202
                assert (await client.get("/api/sessions/chat-ready/tool-approvals", headers=headers)).json() == []
                decision = await client.post("/api/sessions/chat-ready/tool-approvals/approval-ready/decision", headers=headers, json={"decision": "accept"})
                assert decision.json()["status"] == "resolved"

                call_count = len(calls)
                for method, path, body in (
                    ("GET", "/api/sessions/chat-ready", None),
                    ("POST", "/api/sessions", {}),
                    ("POST", "/api/sessions/chat-ready/messages", {"content": "blocked"}),
                    ("GET", "/api/sessions/chat-ready/events", None),
                ):
                    assert (await client.request(method, path, json=body)).status_code == 403
                    assert (await client.request(method, path, headers={**headers, "Origin": "https://untrusted.invalid"}, json=body)).status_code == 403
                assert len(calls) == call_count

                pending = [asyncio.create_task(client.request(method, path, headers=headers)) for method, path in (
                    ("GET", "/api/config/public"),
                    ("GET", "/api/sessions/chat-ready/unknown"),
                    ("POST", "/api/sessions/chat-ready/events"),
                    ("DELETE", "/api/sessions/chat-ready"),
                    ("POST", "/api/sessions/bootstrap"),
                )]
                await asyncio.wait_for(waiting.wait(), 1)
                assert not any(task.done() for task in pending)
                assert not app.state.web_routes_registered
                release.set()
                await warming
                # Once all imports finish, ordinary routing/validation takes over.
                assert all(response.status_code != 503 for response in await asyncio.gather(*pending))
        finally:
            release.set()
            if not warming.done():
                warming.cancel()
            await asyncio.gather(warming, *pending, return_exceptions=True)
            for name in ("financial_team_coordinator_task", "financial_job_scheduler_task", "financial_backtest_worker_task"):
                task = getattr(app.state, name, None)
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    with ThreadPoolExecutor(max_workers=1) as stream_executor:
        monkeypatch.setattr(sessions, "_SESSION_STREAM_EXECUTOR", stream_executor)
        asyncio.run(exercise())
    assert any(call[0] == "create" for call in calls)
    assert any(call[0] == "send" and call[2] == "hello" for call in calls)
    assert any(call[0] == "events" for call in calls)


def test_startup_operations_match_only_reviewed_methods_and_complete_route_shapes():
    from core.web.route_bootstrap import is_startup_route_path
    from core.web.routes import sessions

    for path in (
        "/api/config/bootstrap", "/api/launcher/current-instance", "/api/runtime/summary",
        "/api/sessions/bootstrap", "/api/sessions/query", "/api/sessions/active",
    ):
        assert is_startup_route_path(path, method="GET")
        assert is_startup_route_path(path, method="HEAD")
        assert not is_startup_route_path(path, method="POST")
    for path, method in (
        ("/sessions", "POST"), ("/sessions/{session_id}", "GET"),
        ("/sessions/{session_id}/select", "POST"), ("/sessions/{session_id}/messages", "POST"),
        ("/sessions/{session_id}/events", "GET"), ("/sessions/{session_id}/stop", "POST"),
        ("/sessions/{session_id}/guidance", "POST"), ("/sessions/{session_id}/tool-approvals", "GET"),
        ("/sessions/{session_id}/tool-approvals/{request_id}/decision", "POST"),
        ("/sessions/{session_id}/llm-options", "GET"), ("/sessions/{session_id}/model-parameters", "PATCH"),
        ("/sessions/{session_id}/budget-parameters", "GET"), ("/sessions/{session_id}/budget-parameters", "PATCH"),
    ):
        assert any(route.path == path and method in route.methods for route in sessions.router.routes)
        actual = "/api" + path.replace("{session_id}", "chat-ready").replace("{request_id}", "approval-ready")
        assert is_startup_route_path(actual + "?limit=20", method=method)
    for method, path in (
        ("GET", "/api/sessions/chat-ready/export-html"),
        ("POST", "/api/sessions/chat-ready/archive"),
        ("GET", "/api/sessions/chat-ready/unknown"),
        ("POST", "/api/sessions/chat-ready/events"),
        ("DELETE", "/api/sessions/chat-ready"),
        ("POST", "/api/sessions/bootstrap"),
        ("GET", "/api/sessions/chat-ready/tool-approvals/a/decision/extra"),
        ("GET", "/api/sessions//events"),
    ):
        assert not is_startup_route_path(path, method=method)


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
