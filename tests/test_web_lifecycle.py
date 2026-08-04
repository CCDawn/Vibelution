import asyncio
import threading

from core.web import lifecycle
from core.web.router_registry import _ROUTE_MODULE_NAMES, import_web_route_modules, register_web_routers
from core.web.services import cli_agent_terminal_service, session_service
from fastapi import FastAPI


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
    modules = import_web_route_modules(max_workers=4)
    assert [module.router.name for module in modules] == list(_ROUTE_MODULE_NAMES)
    assert set(imported) == set(_ROUTE_MODULE_NAMES)

    app = FastAPI()
    included: list[str] = []

    def fake_include(router, prefix=""):
        included.append(router.name)

    monkeypatch.setattr(app, "include_router", fake_include)
    register_web_routers(app)
    assert included == list(_ROUTE_MODULE_NAMES)
