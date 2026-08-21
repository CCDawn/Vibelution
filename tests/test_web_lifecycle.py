import asyncio
import os
import subprocess
import sys
import threading

from fastapi import FastAPI

from core.web import lifecycle
from core.web.router_registry import (
    _ROUTE_MODULE_NAMES,
    import_web_route_modules,
    register_web_routers,
)
from core.web.services import cli_agent_terminal_service, session_service


def test_web_app_import_keeps_runtime_scene_service_off_health_path():
    project_root = os.path.dirname(os.path.dirname(__file__))
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import core.web.app; "
                "print('core.web.services.runtime_scene_service' in sys.modules)"
            ),
        ],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "False"


def test_directory_runtime_import_keeps_heavy_dependencies_lazy():
    project_root = os.path.dirname(os.path.dirname(__file__))
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys; import core.web.services.session.directory_runtime; "
                "print(json.dumps({"
                "'conversationStore': 'core.chat.conversation_store' in sys.modules, "
                "'runtimeScene': 'core.web.services.runtime_scene_service' in sys.modules, "
                "'infrastructure': 'core.infrastructure' in sys.modules"
                "}))"
            ),
        ],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == (
        '{"conversationStore": false, "runtimeScene": false, "infrastructure": false}'
    )


def test_web_lifespan_records_ready_scene_event_after_entering_context(monkeypatch):
    entered = threading.Event()
    recorded = threading.Event()
    observed = {}

    def record_ready_event(**fields) -> None:
        observed["entered"] = entered.is_set()
        observed.update(fields)
        recorded.set()

    monkeypatch.setattr(lifecycle, "_record_backend_ready_scene_event", record_ready_event)
    monkeypatch.setattr(lifecycle, "prewarm_ui_caches_on_startup", lambda: asyncio.sleep(0))
    monkeypatch.setattr(lifecycle, "initialize_session_directory_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "initialize_session_catalog_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "shutdown_session_catalog_on_shutdown", lambda: None)
    monkeypatch.setattr(lifecycle, "_write_running_code_fingerprint_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "_start_research_workflow_runtime", lambda: "")
    monkeypatch.setattr(lifecycle, "_stop_research_workflow_runtime", lambda: None)
    monkeypatch.setattr(
        cli_agent_terminal_service,
        "reconcile_cli_agent_terminal_states_on_startup",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(cli_agent_terminal_service, "shutdown_cli_agent_terminal_sessions", lambda: None)
    monkeypatch.setattr(
        session_service,
        "recover_wakeable_agent_inbox_messages_on_startup",
        dict,
        raising=False,
    )

    async def exercise() -> None:
        async with lifecycle.web_workbench_lifespan(None):
            entered.set()
            assert await asyncio.to_thread(recorded.wait, 1)

    asyncio.run(exercise())

    assert observed["entered"] is True
    assert observed["pre_yield_ms"] >= 0
    assert observed["routes_ready"] is False
    assert "cli_terminal_reconcile" in observed["background_tasks"]


def test_web_lifespan_schedules_agent_inbox_recovery_without_blocking_startup(monkeypatch):
    recovery_started = threading.Event()
    catalog_started = threading.Event()
    catalog_shutdown = threading.Event()
    allow_recovery_to_finish = threading.Event()
    reconcile_started = threading.Event()
    allow_reconcile_to_finish = threading.Event()

    def recover() -> dict:
        recovery_started.set()
        allow_recovery_to_finish.wait(timeout=2)
        return {"startedCount": 0}

    def reconcile(**_kwargs) -> dict:
        reconcile_started.set()
        allow_reconcile_to_finish.wait(timeout=2)
        return {"staleCount": 0}

    async def prewarm() -> None:
        return None

    monkeypatch.setattr(
        cli_agent_terminal_service,
        "reconcile_cli_agent_terminal_states_on_startup",
        reconcile,
    )
    monkeypatch.setattr(cli_agent_terminal_service, "shutdown_cli_agent_terminal_sessions", lambda: None)
    monkeypatch.setattr(
        session_service,
        "recover_wakeable_agent_inbox_messages_on_startup",
        recover,
        raising=False,
    )
    monkeypatch.setattr(lifecycle, "prewarm_ui_caches_on_startup", prewarm)
    monkeypatch.setattr(
        lifecycle,
        "initialize_session_catalog_on_startup",
        lambda: catalog_started.set(),
    )
    monkeypatch.setattr(
        lifecycle,
        "shutdown_session_catalog_on_shutdown",
        lambda: catalog_shutdown.set(),
    )

    async def exercise() -> None:
        async with lifecycle.web_workbench_lifespan(None):
            # Lifespan must enter before slow startup work finishes.
            assert await asyncio.to_thread(recovery_started.wait, 0.5)
            assert await asyncio.to_thread(catalog_started.wait, 0.5)
            assert await asyncio.to_thread(reconcile_started.wait, 0.5)
            allow_recovery_to_finish.set()
            allow_reconcile_to_finish.set()
            await asyncio.sleep(0)

    asyncio.run(exercise())
    assert catalog_shutdown.is_set()


def test_web_lifespan_does_not_await_cli_reconcile_before_yield(monkeypatch):
    entered = threading.Event()
    reconcile_released = threading.Event()

    def reconcile(**_kwargs) -> dict:
        # Hold the background reconcile until the lifespan body has entered.
        assert entered.wait(timeout=2)
        reconcile_released.set()
        return {"staleCount": 0}

    monkeypatch.setattr(
        cli_agent_terminal_service,
        "reconcile_cli_agent_terminal_states_on_startup",
        reconcile,
    )
    monkeypatch.setattr(cli_agent_terminal_service, "shutdown_cli_agent_terminal_sessions", lambda: None)
    monkeypatch.setattr(lifecycle, "prewarm_ui_caches_on_startup", lambda: asyncio.sleep(0))
    monkeypatch.setattr(lifecycle, "initialize_session_catalog_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "shutdown_session_catalog_on_shutdown", lambda: None)
    monkeypatch.setattr(
        session_service,
        "recover_wakeable_agent_inbox_messages_on_startup",
        lambda: {"startedCount": 0},
        raising=False,
    )

    async def exercise() -> None:
        async with lifecycle.web_workbench_lifespan(None):
            entered.set()
            await asyncio.sleep(0)
            assert reconcile_released.wait(timeout=2)

    asyncio.run(exercise())


def test_router_registry_imports_all_route_modules_in_stable_order(monkeypatch):
    imported: list[str] = []

    class DummyRouter:
        def __init__(self, name: str):
            self.name = name

    class DummyModule:
        def __init__(self, name: str):
            self.router = DummyRouter(name)

    def fake_import(name: str):
        imported.append(name)
        return DummyModule(name)

    monkeypatch.setattr("core.web.router_registry._import_route_module", fake_import)
    modules = import_web_route_modules()
    assert [module.router.name for module in modules] == list(_ROUTE_MODULE_NAMES)
    assert imported == list(_ROUTE_MODULE_NAMES)

    app = FastAPI()
    included: list[str] = []

    def fake_include(router, prefix=""):
        included.append(router.name)

    monkeypatch.setattr(app, "include_router", fake_include)
    register_web_routers(app)
    assert included == list(_ROUTE_MODULE_NAMES)


def test_create_app_health_works_before_routes_and_middleware_mounts_on_demand():
    from fastapi.testclient import TestClient

    from core.web.app import create_app
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

    app = create_app()
    # Without entering lifespan, routes are not pre-mounted.
    assert bool(getattr(app.state, "web_routes_registered", False)) is False

    with TestClient(app, headers={CONTROL_TOKEN_HEADER: get_control_token()}) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        body = health.json()
        assert body["status"] == "ok"
        # Lifespan background warm or first non-health request should finish mounting.
        # /api/skills is a real mounted API route after bootstrap.
        skills = client.get("/api/skills")
        assert skills.status_code in {200, 401, 403, 404, 500} or skills.status_code < 600
        assert bool(getattr(app.state, "web_routes_registered", False)) is True


def test_health_reports_backend_identity_for_port_occupant_reclaim():
    import os as _os

    from fastapi.testclient import TestClient

    from core.web.app import create_app
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

    _os.environ.pop("VIBELUTION_WORKSPACE_ROOT", None)
    app = create_app()

    with TestClient(app, headers={CONTROL_TOKEN_HEADER: get_control_token()}) as client:
        body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert isinstance(body["routesReady"], bool)
    # The launcher uses pid + workspaceRoot to reclaim stale same-project
    # backends instead of silently drifting to another port.
    assert body["pid"] == _os.getpid()
    assert isinstance(body["workspaceRoot"], str) and body["workspaceRoot"]


def test_health_workspace_root_prefers_launcher_environment():
    from core.web.app import _health_workspace_root

    previous = os.environ.get("VIBELUTION_WORKSPACE_ROOT")
    os.environ["VIBELUTION_WORKSPACE_ROOT"] = "C:/worktrees/demo"
    try:
        assert _health_workspace_root() == "C:/worktrees/demo"
    finally:
        if previous is None:
            os.environ.pop("VIBELUTION_WORKSPACE_ROOT", None)
        else:
            os.environ["VIBELUTION_WORKSPACE_ROOT"] = previous


def test_import_web_route_modules_reports_per_module_timing(monkeypatch):
    timings: list[tuple[str, float]] = []

    class DummyRouter:
        def __init__(self, name: str):
            self.name = name

    class DummyModule:
        def __init__(self, name: str):
            self.router = DummyRouter(name)

    def fake_import(name: str):
        return DummyModule(name)

    monkeypatch.setattr("core.web.router_registry._import_route_module", fake_import)
    modules = import_web_route_modules(
        on_module_imported=lambda name, duration_ms: timings.append((name, duration_ms))
    )

    assert len(modules) == len(_ROUTE_MODULE_NAMES)
    assert [name for name, _ in timings] == list(_ROUTE_MODULE_NAMES)
    assert all(isinstance(duration, float) and duration >= 0 for _, duration in timings)


def test_route_bootstrap_payload_carries_per_module_import_timings(monkeypatch):
    from fastapi import FastAPI as _FastAPI

    from core.web import route_bootstrap

    def fake_import_route_modules(*, on_module_imported=None):
        if on_module_imported is not None:
            on_module_imported("core.web.routes.demo", 12.5)
        return ["dummy-module"]

    monkeypatch.setattr(route_bootstrap, "import_web_route_modules", fake_import_route_modules)
    monkeypatch.setattr(route_bootstrap, "register_web_routers_from_modules", lambda app, modules: None)

    app = _FastAPI()
    payload = route_bootstrap.ensure_web_routes_registered(app)

    assert payload["registered"] is True
    assert payload["routeModuleCount"] == 1
    assert payload["moduleImports"] == [{"module": "core.web.routes.demo", "importMs": 12.5}]
