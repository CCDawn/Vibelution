"""repair 走查的逐 agent 修复指纹缓存回归（GIL 减负批十一）。

背景：轮次活动每次写 agents.json 都改变注册表文件签名，读路径 repair
快照缓存整体失效后对全部 agent（实测 53-127 个）重跑规范化套件，
1.4-1.7s/次的 CPU 持有在 GIL 下放大并发首帧。现下沉为 per-agent 修复
指纹：记录内容 sha 与上一轮修复产物一致、且兄弟身份上下文（id/agentCode/
displayName 三元组 + 原始 memory/tool policy 段）与外部输入签名（registry
路径 + 头像清单 + 模型库 id）未变时，跳过该 agent 的套件，仅保留 code
占位与 workspace 目录确保。锁定：同内容重写零套件、单 agent 更新仅该
agent 重跑且输出与全量走查等价、兄弟身份/外部输入变更全量重跑、挑战杯
config authority 记录保留原值并纳入指纹记账。
"""

from __future__ import annotations

import json

from core.web.services import agent_directory_service
from tests.test_agent_config_workspace_service import (
    _seed_agent_avatars,
    _use_tmp_project_root,
)


def _setup(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_agent_avatars(tmp_path)
    _reset_repair_caches()


def _reset_repair_caches():
    agent_directory_service._invalidate_repaired_state_cache()
    agent_directory_service._REPAIRED_RECORD_SHAS = None
    agent_directory_service._REPAIR_CONTEXT_SIGNATURE = None
    agent_directory_service._REPAIR_EXTERNAL_SIGNATURE = None


def _counting_suite(monkeypatch):
    """以 `_normalize_agent_legacy_metadata_fields` 计数套件进入：该函数只在
    循环套件内、命中跳过 continue 之后被调用（steward 预确保等其他路径不经过）。"""
    calls: list[str] = []
    real = agent_directory_service._normalize_agent_legacy_metadata_fields

    def counting(agent, *args, **kwargs):
        calls.append(str(agent.get("agentId") or ""))
        return real(agent, *args, **kwargs)

    monkeypatch.setattr(
        agent_directory_service,
        "_normalize_agent_legacy_metadata_fields",
        counting,
    )
    return calls


def _rewrite_registry(mutate) -> None:
    """模拟轮次活动写注册表：改写文件内容并使快照缓存失效（save_state 行为）。"""
    registry = agent_directory_service.registry_path()
    payload = json.loads(registry.read_text(encoding="utf-8"))
    mutate(payload)
    registry.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    agent_directory_service._invalidate_repaired_state_cache()


def _seed_agents():
    first = agent_directory_service.create_agent_instance(
        display_name="Alpha Agent", role_key="observer"
    )
    second = agent_directory_service.create_agent_instance(
        display_name="Beta Agent", role_key="observer"
    )
    third = agent_directory_service.create_agent_instance(
        display_name="Gamma Agent", role_key="observer"
    )
    return first, second, third


def _agent_by_id(state, agent_id):
    return next(
        agent
        for agent in state.get("agents") or []
        if str(agent.get("agentId") or "") == agent_id
    )


def test_repair_rewalk_with_identical_content_skips_all_suites(tmp_path, monkeypatch):
    """同内容重写（仅 mtime 变化）后重走查：零套件进入，产物与首轮等价。"""
    _setup(tmp_path, monkeypatch)
    _seed_agents()
    baseline = agent_directory_service.repair_agent_directory()
    suite_calls = _counting_suite(monkeypatch)

    _rewrite_registry(lambda payload: None)
    rerun = agent_directory_service.repair_agent_directory()

    assert suite_calls == []
    assert rerun == baseline


def test_repair_single_agent_update_reruns_suite_only_for_that_agent(tmp_path, monkeypatch):
    """单 agent 记录变更（usage + 触发 displayName 修复）只重跑该 agent，
    且增量走查产物与指纹禁用后的全量走查等价。"""
    _setup(tmp_path, monkeypatch)
    _first, second, _third = _seed_agents()
    agent_directory_service.repair_agent_directory()
    suite_calls = _counting_suite(monkeypatch)
    target_id = str(second["agentId"])

    def mutate(payload):
        for agent in payload.get("agents") or []:
            if str(agent.get("agentId") or "") == target_id:
                # 只动非身份字段：usage 模拟轮次活动写，清空 primaryMode 让套件
                # 对该 agent 有确定性修复动作（displayName/agentCode 属身份三元组，
                # 动了会触发上下文全量重跑，归 test 3 语义；promptTemplateId 的
                # 未知非空值套件本就原样保留，不构成修复触发）。
                agent["primaryMode"] = ""
                agent.setdefault("metadata", {})
                agent["metadata"]["usage"] = {"turns": 1}

    _rewrite_registry(mutate)
    incremental = agent_directory_service.repair_agent_directory()

    assert suite_calls == [target_id]
    assert str(_agent_by_id(incremental, target_id).get("primaryMode") or "").strip()

    agent_directory_service._invalidate_repaired_state_cache()
    agent_directory_service._REPAIRED_RECORD_SHAS = None
    full = agent_directory_service.repair_agent_directory()
    # state 级 updatedAt 是写入时间戳：走查 2 落盘后的文件在走查 3 读到新值，
    # 而走查 2 返回的内存态保留旧值（存量行为，与跳过路径无关）。其余全等。
    incremental.pop("updatedAt", None)
    full.pop("updatedAt", None)
    assert full == incremental


def test_repair_sibling_identity_change_reruns_all_suites(tmp_path, monkeypatch):
    """兄弟身份字段（displayName）变更改变上下文签名：全部 agent 重跑套件。"""
    _setup(tmp_path, monkeypatch)
    first, second, third = _seed_agents()
    agent_directory_service.repair_agent_directory()
    suite_calls = _counting_suite(monkeypatch)
    gamma_id = str(third["agentId"])

    def mutate(payload):
        for agent in payload.get("agents") or []:
            if str(agent.get("agentId") or "") == gamma_id:
                agent["displayName"] = "Renamed Gamma"

    _rewrite_registry(mutate)
    agent_directory_service.repair_agent_directory()

    expected_all = sorted(
        [str(first["agentId"]), str(second["agentId"]), gamma_id, s_knowledge_steward_id()]
    )
    assert sorted(suite_calls) == expected_all


def s_knowledge_steward_id() -> str:
    return str(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID)


def test_repair_model_library_change_reruns_all_suites(tmp_path, monkeypatch):
    """外部输入（模型库 id 集合）变更改变外部签名：全部 agent 重跑套件。"""
    _setup(tmp_path, monkeypatch)
    first, second, third = _seed_agents()
    agent_directory_service.repair_agent_directory()
    suite_calls = _counting_suite(monkeypatch)

    real_model_ids = agent_directory_service._configured_model_library_ids
    base_ids = set(real_model_ids())
    monkeypatch.setattr(
        agent_directory_service,
        "_configured_model_library_ids",
        lambda *args, **kwargs: set(base_ids) | {"new_relay_model_for_signature"},
    )

    _rewrite_registry(lambda payload: None)
    agent_directory_service.repair_agent_directory()

    expected_all = sorted(
        [str(first["agentId"]), str(second["agentId"]), str(third["agentId"]), s_knowledge_steward_id()]
    )
    assert sorted(suite_calls) == expected_all


def test_repair_preserves_challenge_cup_authority_and_bookkeeps_it(tmp_path, monkeypatch):
    """挑战杯 config authority 记录字段原样保留；无关 agent 更新后其记录不变。"""
    _setup(tmp_path, monkeypatch)
    _seed_agents()

    def add_challenge_agent(payload):
        payload.setdefault("agents", []).append(
            {
                "agentId": "cup-agent-1",
                "agentCode": "cup-1",
                "displayName": "挑战杯权威配置",
                "metadata": {"challengeCupTeamId": "research-team"},
                "customField": {"persona": "agent-owned-copy"},
            }
        )

    _rewrite_registry(add_challenge_agent)
    first = agent_directory_service.repair_agent_directory()
    cup_first = _agent_by_id(first, "cup-agent-1")
    assert cup_first.get("customField") == {"persona": "agent-owned-copy"}
    assert cup_first.get("metadata", {}).get("challengeCupTeamId") == "research-team"

    suite_calls = _counting_suite(monkeypatch)
    normal_ids = [
        str(agent.get("agentId") or "")
        for agent in first.get("agents") or []
        if str(agent.get("agentId") or "") != "cup-agent-1"
    ]

    def touch_one_normal_agent(payload):
        for agent in payload.get("agents") or []:
            if str(agent.get("agentId") or "") in normal_ids[:1]:
                agent.setdefault("metadata", {})
                agent["metadata"]["usage"] = {"turns": 2}
                return

    _rewrite_registry(touch_one_normal_agent)
    rerun = agent_directory_service.repair_agent_directory()

    assert sorted(suite_calls) == sorted(normal_ids[:1])
    assert _agent_by_id(rerun, "cup-agent-1") == cup_first
    assert "cup-agent-1" in (agent_directory_service._REPAIRED_RECORD_SHAS or {})
