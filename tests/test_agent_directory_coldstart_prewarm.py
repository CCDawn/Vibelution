"""Cold-start prewarm and lightweight registry read contracts.

Covers the backend cold-start window fixes:
- ``count_active_agents``: bus-style counters must read the repaired shared
  state without the summary projection path or repair recompute.
- ``prewarm_registry_caches``: the first registry reader must not pay repair
  (p90≈2.6s) and summary rebuild (p50≈1.0s) inside the first user request.
- ``_ensure_config_agent_instances`` signature gate: hot GET /api/agents must
  skip the presence ``load_state`` path until a relevant file changes.
"""

from __future__ import annotations

from core.web.routes import agents as agents_route
from core.web.services import agent_directory_service
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
