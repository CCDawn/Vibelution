"""Cold-start prewarm and lightweight registry read contracts.

Covers the backend cold-start window fixes:
- ``count_active_agents``: bus-style counters must read the repaired shared
  state without the summary projection path or repair recompute.
- ``prewarm_registry_caches`` + lifecycle scheduling: the first registry reader
  must not pay repair (p90≈2.6s) and summary rebuild (p50≈1.0s) inside the
  first user request.
- ``_ensure_config_agent_instances`` signature gate: hot GET /api/agents must
  skip the presence ``load_state`` path until a relevant file changes.
"""

from __future__ import annotations

import asyncio
import threading

from fastapi import FastAPI

from core.web import lifecycle
from core.web.routes import agents as agents_route
from core.web.services import agent_directory_service
from core.web.services.session import directory_runtime
from core.web.services import runtime_scene_service
from tests.helpers.system_agent_state import _mark_config_agent_instances_present
from tests.test_agent_config_workspace_service import _use_tmp_project_root


def test_count_active_agents_counts_from_repaired_state_without_projection(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    kept = agent_directory_service.create_agent_instance(display_name="Alpha")
    archived = agent_directory_service.create_agent_instance(display_name="Beta")
    agent_directory_service.archive_agent_instance(str(archived["agentId"]))
    list_agents_calls: list[tuple] = []

    def fail_list_agents(*args, **kwargs):
        list_agents_calls.append((args, kwargs))
        return []

    monkeypatch.setattr(agent_directory_service, "list_agents", fail_list_agents)

    repaired = agent_directory_service.repair_agent_directory()
    expected = sum(
        1
        for item in repaired.get("agents") or []
        if isinstance(item, dict) and str(item.get("status") or "active") != "archived"
    )
    count = agent_directory_service.count_active_agents()

    assert expected >= 1
    assert count == expected
    assert count != sum(1 for item in repaired.get("agents") or [] if isinstance(item, dict))
    assert str(kept["agentId"])
    assert list_agents_calls == []


def test_count_active_agents_reuses_repair_cache_without_recompute(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent_directory_service.create_agent_instance(display_name="Alpha")
    # First read builds the repaired-state cache (registry just changed).
    agent_directory_service.count_active_agents()

    repair_calls: list[int] = []
    real_repair = agent_directory_service.repair_agent_directory

    def tracked_repair(*args, **kwargs):
        repair_calls.append(1)
        return real_repair(*args, **kwargs)

    monkeypatch.setattr(agent_directory_service, "repair_agent_directory", tracked_repair)

    count = agent_directory_service.count_active_agents()

    assert count >= 1
    assert repair_calls == []


def test_prewarm_registry_caches_fills_summary_projection_cache(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent_directory_service.create_agent_instance(display_name="Alpha")

    agent_directory_service.prewarm_registry_caches()
    second = agent_directory_service.prewarm_registry_caches()
    assert second["repairCacheHit"] is True

    projection_calls: list[int] = []
    real_summary = agent_directory_service._agent_to_api_summary

    def tracked_summary(*args, **kwargs):
        projection_calls.append(1)
        return real_summary(*args, **kwargs)

    monkeypatch.setattr(agent_directory_service, "_agent_to_api_summary", tracked_summary)
    agents = agent_directory_service.list_agents(detail="summary")

    assert agents
    assert projection_calls == []


def test_prewarm_agent_registry_waits_for_directory_startup_then_warms(monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(directory_runtime, "should_skip_directory_runtime_for_pytest", lambda: False)

    def fake_wait(*, timeout=None):
        order.append("wait")
        return "ready"

    monkeypatch.setattr(directory_runtime, "wait_for_directory_startup", fake_wait)

    def fake_prewarm():
        order.append("warm")
        return {"repairCacheHit": True, "repairMs": 0.0, "summaryPrewarmMs": 0.0}

    monkeypatch.setattr(agent_directory_service, "prewarm_registry_caches", fake_prewarm)
    monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event", lambda *args, **kwargs: None)

    result = lifecycle._prewarm_agent_registry_on_startup()

    assert order == ["wait", "warm"]
    assert result["totalMs"] >= 0


def test_prewarm_agent_registry_skips_under_pytest(monkeypatch):
    monkeypatch.setattr(directory_runtime, "should_skip_directory_runtime_for_pytest", lambda: True)

    def fail_wait(*, timeout=None):
        raise AssertionError("pytest skip must not wait on the directory startup")

    monkeypatch.setattr(directory_runtime, "wait_for_directory_startup", fail_wait)
    result = lifecycle._prewarm_agent_registry_on_startup()
    assert result == {"skipped": "pytest"}


def test_gated_agent_registry_prewarm_waits_for_routes_ready_then_warms(monkeypatch):
    """门控顺序：routes ready 事件 set 前不预热；set + settle 后目录等待→预热。"""

    monkeypatch.setenv("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS", "0.01")
    order: list[str] = []
    monkeypatch.setattr(directory_runtime, "should_skip_directory_runtime_for_pytest", lambda: False)

    def fake_wait(*, timeout=None):
        order.append("wait")
        return "ready"

    monkeypatch.setattr(directory_runtime, "wait_for_directory_startup", fake_wait)

    def fake_prewarm():
        order.append("warm")
        return {"repairCacheHit": True, "repairMs": 0.0, "summaryPrewarmMs": 0.0}

    monkeypatch.setattr(agent_directory_service, "prewarm_registry_caches", fake_prewarm)
    monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event", lambda *args, **kwargs: None)

    app = FastAPI()
    app.state.web_routes_ready_event = asyncio.Event()

    async def exercise():
        worker = asyncio.create_task(lifecycle._run_agent_registry_prewarm_after_routes_ready(app))
        await asyncio.sleep(0.05)
        assert order == [], "routes-ready 事件 set 前不得启动目录等待或预热"
        app.state.web_routes_ready_event.set()
        await asyncio.wait_for(worker, timeout=5)

    asyncio.run(exercise())

    assert order == ["wait", "warm"]


def test_web_lifespan_schedules_agent_registry_prewarm(monkeypatch):
    entered = threading.Event()
    prewarm_started = threading.Event()
    observed: dict = {}

    def record_ready_event(**fields) -> None:
        observed.update(fields)

    def prewarm() -> dict:
        prewarm_started.set()
        return {}

    async def gated_prewarm(app) -> dict:
        # 默认门控下 lifespan 必须经 routes-ready 包装器调度 registry 预热。
        return await asyncio.to_thread(prewarm)

    monkeypatch.setattr(lifecycle, "_record_backend_ready_scene_event", record_ready_event)
    monkeypatch.setattr(lifecycle, "_run_agent_registry_prewarm_after_routes_ready", gated_prewarm)
    monkeypatch.setattr(lifecycle, "_prewarm_agent_registry_on_startup", prewarm)
    monkeypatch.setattr(lifecycle, "prewarm_ui_caches_on_startup", lambda: asyncio.sleep(0))
    monkeypatch.setattr(lifecycle, "initialize_session_directory_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "initialize_session_catalog_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "shutdown_session_catalog_on_shutdown", lambda: None)
    monkeypatch.setattr(lifecycle, "_write_running_code_fingerprint_on_startup", lambda: None)
    monkeypatch.setattr(lifecycle, "_start_research_workflow_runtime", lambda: "")
    monkeypatch.setattr(lifecycle, "_stop_research_workflow_runtime", lambda: None)
    from core.web.services import cli_agent_terminal_service, session_service

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
            assert await asyncio.to_thread(prewarm_started.wait, 1)

    asyncio.run(exercise())

    assert entered.is_set()
    assert "agent_registry_prewarm" in observed["background_tasks"]


def test_ensure_config_agent_instances_gate_skips_load_state_until_signature_changes(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(agents_route, "_CONFIG_PRESENCE_GATE_SIGNATURE", None)
    _mark_config_agent_instances_present()

    load_state_calls: list[int] = []
    real_load_state = agent_directory_service.load_state

    def counted_load_state(*args, **kwargs):
        load_state_calls.append(1)
        return real_load_state(*args, **kwargs)

    monkeypatch.setattr(agent_directory_service, "load_state", counted_load_state)

    agents_route._ensure_config_agent_instances()
    assert load_state_calls, "first ensure must evaluate presence via load_state"
    calls_after_first = len(load_state_calls)

    agents_route._ensure_config_agent_instances()
    assert len(load_state_calls) == calls_after_first, (
        "unchanged registry + mode binding signatures must skip the presence load_state path"
    )

    agent_directory_service.create_agent_instance(display_name="Gate Probe")
    agents_route._ensure_config_agent_instances()
    assert len(load_state_calls) > calls_after_first, (
        "registry signature change must re-run the presence check"
    )
