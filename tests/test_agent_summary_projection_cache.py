"""GET /agents?detail=summary 投影缓存与 repair 收敛回归。

背景：summary 列表是导航热点。曾经 repair 对 profileless session agent
反复注入会被存储规范化剥除的 persona/taskProfile，导致注册表每轮 repair
都被无条件重写（mtime 抖动 + 全量写放大），读路径 repair 缓存反复失效，
接口冷读叠加秒级修复；同时 summary 投影本身无缓存，后台 agent 活跃时
单次重建被放大至 ~1s。这里锁定：repair 收敛不再空转重写、summary 命中
缓存、agent 增删改即时失效、并发首击安全。

缓存粒度回归（GIL 减负 T1）：整表缓存以注册表文件签名为 key，任一 agent
写入（如 agent.model_parameters.updated）都会整体失效并全量重投影；现
下沉为 per-agent 内容签名条目，锁定：无关 agent 更新不失效、相关 agent
正确失效、缓存命中输出与直连投影字节等价、快拷与 deepcopy 等价。
"""

from __future__ import annotations

import copy
import hashlib
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


def _counting_summary(target, real):
    calls: list[int] = []

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    return calls, counting


def _canonical_digest(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _seed_fixture_agents():
    # roleKey 非空：避免被判定为 profileless session agent 而剥除 persona。
    with_persona = agent_directory_service.create_agent_instance(
        display_name="Persona Agent",
        role_key="observer",
    )
    agent_directory_service.update_agent_instance(
        str(with_persona["agentId"]),
        persona_profile={
            "gender": "female",
            "age": "30",
            "personality": "严谨、克制",
            "expertise": ["code review", "测试"],
        },
        task_profile={"mission": "守护回归质量"},
    )
    plain = agent_directory_service.create_agent_instance(display_name="Plain Agent")
    session_like = agent_directory_service.create_agent_instance(
        display_name="Chat Session Agent",
        primary_mode="chat",
    )
    return with_persona, plain, session_like


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


def test_summary_cache_per_agent_hit_survives_unrelated_update(tmp_path, monkeypatch):
    """无关 agent 更新只重投影该 agent，其余 per-agent 条目继续命中。"""

    _setup(tmp_path, monkeypatch)
    with_persona, plain, _session_like = _seed_fixture_agents()
    first = agent_directory_service.list_agents(detail="summary")
    assert len(first) >= 3

    calls, counting = _counting_summary(
        agent_directory_service, agent_directory_service._agent_to_api_summary
    )
    monkeypatch.setattr(agent_directory_service, "_agent_to_api_summary", counting)
    try:
        agent_directory_service.update_agent_instance(
            str(with_persona["agentId"]), display_name="Persona Agent v2"
        )
        second = agent_directory_service.list_agents(detail="summary")
        assert len(calls) == 1, "only the updated agent must be re-projected"
        assert len(second) == len(first)

        # 再列一次：全部命中，零重投影。
        agent_directory_service.list_agents(detail="summary")
        assert len(calls) == 1
    finally:
        monkeypatch.setattr(
            agent_directory_service,
            "_agent_to_api_summary",
            agent_directory_projections._agent_to_api_summary,
        )

    unrelated_keys = [
        key for key in agent_directory_projections._AGENT_SUMMARY_CACHE
        if key[0] == plain["agentId"]
    ]
    assert len(unrelated_keys) == 1, "unrelated agent cache entry must survive"


def test_summary_cache_invalidates_only_updated_agent_content(tmp_path, monkeypatch):
    """被更新 agent 的新内容立即可见，无关 agent 输出逐字节不变。"""

    _setup(tmp_path, monkeypatch)
    with_persona, plain, _session_like = _seed_fixture_agents()
    first = agent_directory_service.list_agents(detail="summary")
    plain_before = next(
        item for item in first if item["agentId"] == plain["agentId"]
    )

    agent_directory_service.update_agent_instance(
        str(with_persona["agentId"]), display_name="Persona Agent v2"
    )
    second = agent_directory_service.list_agents(detail="summary")
    persona_after = next(
        item for item in second if item["agentId"] == with_persona["agentId"]
    )
    assert persona_after["displayName"] == "Persona Agent v2"

    plain_after = next(
        item for item in second if item["agentId"] == plain["agentId"]
    )
    assert _canonical_digest(plain_after) == _canonical_digest(plain_before)


def test_summary_projection_byte_equivalent_cached_vs_direct(tmp_path, monkeypatch):
    """冻结 fixture：缓存冷建/命中输出与直连投影 sha256 一致（含/不含 personaProfile）。"""

    _setup(tmp_path, monkeypatch)
    _with_persona, _plain, _session_like = _seed_fixture_agents()

    repaired = agent_directory_service.repair_agent_directory()
    raw_agents = [
        item
        for item in repaired.get("agents") or []
        if isinstance(item, dict) and str(item.get("status") or "active") != "archived"
    ]
    assert len(raw_agents) >= 3
    available_avatars = agent_directory_service._available_agent_avatar_filenames()

    # 直连投影（绕过缓存，"改前"参照实现）。
    direct = [
        agent_directory_projections._agent_to_api_summary(
            item,
            avatar_url_cache={},
            available_avatar_filenames=available_avatars,
        )
        for item in raw_agents
    ]
    direct_digest = _canonical_digest(sorted(direct, key=lambda item: item["agentId"]))

    # 缓存冷建（清缓存后首列，全部 miss 构建）。
    agent_directory_projections._reset_agent_summary_cache()
    cold = agent_directory_service.list_agents(detail="summary")
    cold_digest = _canonical_digest(sorted(cold, key=lambda item: item["agentId"]))

    # 缓存命中（第二次列，全部 hit 快拷）。
    warm = agent_directory_service.list_agents(detail="summary")
    warm_digest = _canonical_digest(sorted(warm, key=lambda item: item["agentId"]))

    assert cold_digest == direct_digest
    assert warm_digest == direct_digest

    # 带/不带 personaProfile 的情形都必须存在且两路一致。
    by_id = {item["agentId"]: item for item in cold}
    persona_item = by_id[_with_persona["agentId"]]
    plain_item = by_id[_plain["agentId"]]
    assert persona_item["metadata"].get("personaProfile", {}).get("personality") == "严谨、克制"
    assert not plain_item["metadata"].get("personaProfile")
    direct_by_id = {item["agentId"]: item for item in direct}
    assert _canonical_digest(persona_item) == _canonical_digest(direct_by_id[_with_persona["agentId"]])
    assert _canonical_digest(plain_item) == _canonical_digest(direct_by_id[_plain["agentId"]])


def test_copy_json_safe_equivalent_to_deepcopy_and_isolated():
    fixture = {
        "personaProfile": {
            "personality": "严谨、克制",
            "age": "30",
            "score": 0.5,
            "flags": [True, False, None],
            "expertise": ["code review", "测试"],
            "nested": {"a": [1, {"b": 2.25}], "empty": {}, "none": None},
        },
        "llmModelParameters": {"model_ref": "gpt-x", "contextWindow": 40000},
        "emptyList": [],
    }

    fast = agent_directory_projections._copy_json_safe(fixture)
    deep = copy.deepcopy(fixture)
    assert _canonical_digest(fast) == _canonical_digest(deep)

    # 独立性：修改快拷不影响源，源修改不影响快拷。
    fast["personaProfile"]["expertise"].append("mutated")
    fast["personaProfile"]["nested"]["a"][1]["b"] = 999
    assert fixture["personaProfile"]["expertise"] == ["code review", "测试"]
    assert fixture["personaProfile"]["nested"]["a"][1]["b"] == 2.25

    # 标量与非 JSON 类型：标量直接返回，异常类型回落 deepcopy 且结果等价。
    assert agent_directory_projections._copy_json_safe("raw") == "raw"
    assert agent_directory_projections._copy_json_safe(3.14) == 3.14
    assert agent_directory_projections._copy_json_safe(None) is None
    tuple_value = (1, [2])
    fast_tuple = agent_directory_projections._copy_json_safe(tuple_value)
    assert fast_tuple == copy.deepcopy(tuple_value)
    assert fast_tuple is not tuple_value
    assert fast_tuple[1] is not tuple_value[1]


def test_summary_cache_content_signature_stable_and_sensitive():
    base = {
        "agentId": "agent-1",
        "displayName": "A",
        "metadata": {"personaProfile": {"personality": "严谨"}, "z": 1},
    }
    same_content_reordered = {
        "metadata": {"z": 1, "personaProfile": {"personality": "严谨"}},
        "displayName": "A",
        "agentId": "agent-1",
    }
    changed = dict(base)
    changed["metadata"] = {"personaProfile": {"personality": "严谨"}, "z": 2}

    signature = agent_directory_projections._agent_summary_content_signature
    assert signature(base) == signature(same_content_reordered)
    assert signature(base) != signature(changed)
    assert signature(base) != ""
