"""GET /agents?detail=summary 投影缓存与 repair 收敛回归。

背景：summary 列表是导航热点。曾经 repair 对 profileless session agent
反复注入会被存储规范化剥除的 persona/taskProfile，导致注册表每轮 repair
都被无条件重写（mtime 抖动 + 全量写放大），读路径 repair 缓存反复失效，
接口冷读叠加秒级修复；同时 summary 投影本身无缓存，后台 agent 活跃时
单次重建被放大至 ~1s。这里锁定：repair 收敛不再空转重写、summary 命中
缓存、agent 增删改即时失效、并发首击安全。
"""

from __future__ import annotations

import json
import threading

from core.web.services import agent_directory_service
from core.web.services.agent_directory import projections as agent_directory_projections
from tests.test_agent_config_workspace_service import (
    _seed_agent_avatars,
    _use_tmp_project_root,
)


def _setup(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_agent_avatars(tmp_path)
    agent_directory_projections._reset_agent_summary_cache()


def test_summary_cache_hits_and_returns_mutable_copies(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    agent_directory_service.create_agent_instance(display_name="Summary Cache Agent")

    first = agent_directory_service.list_agents(detail="summary")

    summary_calls: list[int] = []
    real_summary = agent_directory_projections._agent_to_api_summary

    def counting_summary(*args, **kwargs):
        summary_calls.append(1)
        return real_summary(*args, **kwargs)

    monkeypatch.setattr(
        agent_directory_projections, "_agent_to_api_summary", counting_summary
    )
    try:
        second = agent_directory_service.list_agents(detail="summary")
    finally:
        monkeypatch.setattr(agent_directory_projections, "_agent_to_api_summary", real_summary)

    assert summary_calls == []
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    # 命中返回深拷贝：调用方修改返回值不得污染缓存。
    second[0]["displayName"] = "caller-mutated"
    third = agent_directory_service.list_agents(detail="summary")
    assert third[0]["displayName"] != "caller-mutated"


def test_summary_cache_invalidates_on_create_update_archive(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    baseline = agent_directory_service.list_agents(detail="summary")

    created = agent_directory_service.create_agent_instance(display_name="Fresh Agent")
    after_create = agent_directory_service.list_agents(detail="summary")
    assert any(item["agentId"] == created["agentId"] for item in after_create)
    assert len(after_create) == len(baseline) + 1

    agent_directory_service.update_agent_instance(
        created["agentId"], display_name="Renamed Agent"
    )
    after_update = agent_directory_service.list_agents(detail="summary")
    renamed = next(
        item for item in after_update if item["agentId"] == created["agentId"]
    )
    assert renamed["displayName"] == "Renamed Agent"

    agent_directory_service.update_agent_instance(
        created["agentId"], status="archived"
    )
    after_archive = agent_directory_service.list_agents(detail="summary")
    assert not any(item["agentId"] == created["agentId"] for item in after_archive)

    archived_view = agent_directory_service.list_agents(
        detail="summary", include_archived=True
    )
    archived = next(
        item for item in archived_view if item["agentId"] == created["agentId"]
    )
    assert archived["status"] == "archived"


def test_summary_cache_concurrent_first_build_returns_complete_results(
    tmp_path, monkeypatch
):
    _setup(tmp_path, monkeypatch)
    for index in range(6):
        agent_directory_service.create_agent_instance(display_name=f"Concurrent {index}")

    results: list[list[dict]] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def worker():
        try:
            barrier.wait()
            results.append(
                agent_directory_service.list_agents(detail="summary")
            )
        except BaseException as exc:  # pragma: no cover - surfaced via assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == 4
    canonical = json.dumps(results[0], sort_keys=True)
    assert all(json.dumps(item, sort_keys=True) == canonical for item in results[1:])
    serial = agent_directory_service.list_agents(detail="summary")
    assert len(results[0]) == len(serial)
    assert {item["agentId"] for item in results[0]} >= {
        item["agentId"] for item in serial
    }


def test_repair_is_convergent_for_profileless_session_agent(tmp_path, monkeypatch):
    """profileless session agent 不得被注入必然被存储规范化剥除的 profile。

    回归：capability_steward 等 research_org 角色标记曾让 repair 每轮给
    chat 模式无 roleKey 的 agent 注入 persona/taskProfile，保存时又被剥除，
    注册表被无条件重写（mtime 每轮变化、读路径缓存反复失效）。
    """

    _setup(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Capability Steward Session",
        metadata={"researchOrgRole": "capability_steward"},
    )

    agent_directory_service.repair_agent_directory()  # 结算首轮真实修复
    registry = agent_directory_service.registry_path()
    assert registry.exists()
    mtime_before = registry.stat().st_mtime_ns

    agent_directory_service.repair_agent_directory()
    mtime_after = registry.stat().st_mtime_ns

    assert mtime_after == mtime_before, (
        "repair must not rewrite the registry when no real repair is needed; "
        "an unconditional rewrite defeats read-path caches and stalls /api/agents"
    )

    persisted = json.loads(registry.read_text(encoding="utf-8"))
    record = next(
        item
        for item in persisted["agents"]
        if item.get("agentId") == agent["agentId"]
    )
    metadata = record.get("metadata") or {}
    assert "personaProfile" not in metadata
    assert "taskProfile" not in metadata
