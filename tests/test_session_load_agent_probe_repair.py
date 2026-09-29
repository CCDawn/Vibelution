"""会话列表加载修复收敛回归：无主会话的 agent 绑定反查。

覆盖三条回归线：
- 无主会话在 ``_load_conversations(repair=True)`` 里的 archived/active 反查
  走 ``agent_by_id`` 定向映射，不再触发 ``list_agents`` 全量投影（切会话卡死主根因）；
- 「未找到」的探查结果按进程按会话短路，目录签名变更后自动失效重探，
  后绑定 / 新会话仍能正常物化 agent；
- ``agent_by_id`` 定向反查与原 ``list_agents`` 全量扫描对消费方字段等价。
"""

from __future__ import annotations

from typing import Any

import pytest

from core.infrastructure import developer_sandbox
from core.ui.chat_state import save_chat_state
from core.web.services import (
    agent_directory_service,
    config_service,
    session_service,
)
from core.web.services.session import conversation_index
from tests.test_agent_config_workspace_service import (
    _fake_config_workspace,
    _use_tmp_project_root,
)

_TEST_MODEL_ID = "relay_gpt_5_6_luna"


@pytest.fixture(autouse=True)
def _isolated_probe_cache():
    conversation_index._CONVERSATION_AGENT_PROBE_STATE.clear()
    yield
    conversation_index._CONVERSATION_AGENT_PROBE_STATE.clear()


def _patch_stale_running_owner_stubs(monkeypatch) -> None:
    class _StubWorkRunStore:
        def __init__(self):
            self._active = None

        def load_active_snapshot(self, run_kind):
            return self._active

    class _StubTurnScheduler:
        def queued_session_turn_ids(self):
            return set()

        def clear(self):
            return None

    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", _StubWorkRunStore())
    monkeypatch.setattr(session_service, "_SESSION_TURN_SCHEDULER", _StubTurnScheduler())
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    monkeypatch.setattr(session_service, "reconcile_stale_chat_turn_work_runs", lambda **_kwargs: [])
    monkeypatch.setattr(session_service, "_release_stale_chat_turn_work_run", lambda **_kwargs: None)
    monkeypatch.setattr(
        session_service,
        "_repair_child_root_agent_direct_session_bindings",
        lambda *args, **kwargs: False,
    )


def _patch_probe_counters(monkeypatch):
    """Count the expensive reverse lookups and full agent projections."""

    calls = {
        "list_agents": [],
        "archived_lookups": [],
        "active_lookups": [],
    }
    original_list_agents = agent_directory_service.list_agents
    monkeypatch.setattr(
        agent_directory_service,
        "list_agents",
        lambda *args, **kwargs: calls["list_agents"].append(1) or original_list_agents(*args, **kwargs),
    )
    original_archived = session_service._archived_agent_for_direct_session
    monkeypatch.setattr(
        session_service,
        "_archived_agent_for_direct_session",
        lambda session_id, **kwargs: calls["archived_lookups"].append(str(session_id))
        or original_archived(session_id, **kwargs),
    )
    original_active = session_service._agent_for_direct_session
    monkeypatch.setattr(
        session_service,
        "_agent_for_direct_session",
        lambda session_id, **kwargs: calls["active_lookups"].append(str(session_id))
        or original_active(session_id, **kwargs),
    )
    return calls


def _seed_masterless_conversations(tmp_path, session_ids, *, extra: dict | None = None) -> None:
    payload = {
        "version": 1,
        "conversations": [
            {
                "conversation_id": session_id,
                "title": session_id,
                "workspace_path": f"workspaces/{session_id}",
                "last_turn_status": "ready",
                "messages": [],
                **(extra or {}),
            }
            for session_id in session_ids
        ],
    }
    save_chat_state(tmp_path, payload)


def test_masterless_probe_converges_and_never_projects_full_agent_list(tmp_path, monkeypatch):
    """两次加载：第一次逐会话定向反查且零全量投影；第二次探查整体短路。"""

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    _patch_stale_running_owner_stubs(monkeypatch)
    calls = _patch_probe_counters(monkeypatch)

    session_ids = [f"probe-session-{index}" for index in range(6)]
    for index in range(2):
        agent_directory_service.create_agent_instance(display_name=f"loose-agent-{index}")
    _seed_masterless_conversations(tmp_path, session_ids)

    session_service._load_conversations(repair=True)

    assert sorted(calls["archived_lookups"]) == sorted(session_ids)
    assert sorted(calls["active_lookups"]) == sorted(session_ids)
    # 任务 A 主断言：定向反查走 agent_by_id 映射，不再触发 list_agents 全量投影。
    assert calls["list_agents"] == []

    calls["archived_lookups"].clear()
    calls["active_lookups"].clear()

    session_service._load_conversations(repair=True)

    # 任务 B 主断言：同目录签名下，无主会话的昂贵反查每进程每会话最多跑一次。
    assert calls["archived_lookups"] == []
    assert calls["active_lookups"] == []
    assert calls["list_agents"] == []


def test_directory_change_invalidates_probe_and_binds_late_agent(tmp_path, monkeypatch):
    """探查落空后目录发生绑定变更：下次加载零全量投影且绑定不回归。"""

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    _patch_stale_running_owner_stubs(monkeypatch)
    calls = _patch_probe_counters(monkeypatch)

    session_id = "late-binding-session"
    _seed_masterless_conversations(tmp_path, [session_id])

    session_service._load_conversations(repair=True)
    assert calls["archived_lookups"] == [session_id]
    assert calls["active_lookups"] == [session_id]
    assert calls["list_agents"] == []

    agent = session_service.ensure_agent_for_session(
        session_id,
        display_name="后绑定 Agent",
        llm_bindings={"dialogue": {"modelId": _TEST_MODEL_ID}},
    )

    calls["archived_lookups"].clear()
    calls["active_lookups"].clear()
    _active_id, conversations = session_service._load_conversations(repair=True)

    # 绑定经内存恢复路径完成（projection._recover_active_direct_session_agent），
    # 不需要 list_agents 全量投影，也不需要重跑昂贵反查。
    by_id = {str(item.get("id") or ""): item for item in conversations}
    assert by_id[session_id].get("agentId") == agent["agentId"]
    assert calls["archived_lookups"] == []
    assert calls["active_lookups"] == []
    assert calls["list_agents"] == []


def test_probe_cache_invalidates_when_agent_directory_changes(monkeypatch):
    """同签名短路、跨会话互不影响；目录签名一变立即失效重探。"""

    from pathlib import Path

    monkeypatch.setattr(session_service, "PROJECT_ROOT", Path("//probe-cache-root"))
    conversation_index._CONVERSATION_AGENT_PROBE_STATE.clear()

    empty: dict[str, dict[str, Any]] = {}
    assert session_service._conversation_agent_binding_probe_pending("s1", agent_by_id=empty) is True
    session_service._conversation_agent_binding_probe_completed("s1", agent_by_id=empty)
    # 同签名：已探会话短路，未探会话仍探。
    assert session_service._conversation_agent_binding_probe_pending("s1", agent_by_id=empty) is False
    assert session_service._conversation_agent_binding_probe_pending("s2", agent_by_id=empty) is True

    grown = {
        "a1": {"agentId": "a1", "directSessionId": "s1", "status": "active", "updatedAt": "t1"}
    }
    # 目录新增 agent → 签名变更 → 已探会话失效重探。
    assert session_service._conversation_agent_binding_probe_pending("s1", agent_by_id=grown) is True
    session_service._conversation_agent_binding_probe_completed("s1", agent_by_id=grown)
    assert session_service._conversation_agent_binding_probe_pending("s1", agent_by_id=grown) is False

    rebound = {
        "a1": {"agentId": "a1", "directSessionId": "s9", "status": "active", "updatedAt": "t1"}
    }
    # 绑定字段变更 → 重探。
    assert session_service._conversation_agent_binding_probe_pending("s1", agent_by_id=rebound) is True

    # 无映射的直接调用保持原行为：永远探查，且不写标记。
    assert session_service._conversation_agent_binding_probe_pending("s1", agent_by_id=None) is True
    session_service._conversation_agent_binding_probe_completed("s1", agent_by_id=None)
    assert session_service._conversation_agent_binding_probe_pending("s1", agent_by_id=None) is True


def test_new_masterless_session_still_materializes_after_convergence(tmp_path, monkeypatch):
    """已收敛的旧会话被短路跳过，新建无主会话首次加载仍正常物化 agent。"""

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    _patch_stale_running_owner_stubs(monkeypatch)
    calls = _patch_probe_counters(monkeypatch)

    settled_id = "settled-session"
    _seed_masterless_conversations(tmp_path, [settled_id])
    session_service._load_conversations(repair=True)
    assert calls["archived_lookups"] == [settled_id]

    new_id = "fresh-session"
    _seed_masterless_conversations(
        tmp_path,
        [settled_id, new_id],
    )
    # 让新会话命中物化分支：带消息 ⇒ _conversation_requires_agent_materialization 为 True。
    from core.ui.chat_state import load_chat_state

    payload = load_chat_state(tmp_path)
    for raw in payload.get("conversations") or []:
        if str(raw.get("conversation_id") or "") == new_id:
            raw["messages"] = [{"id": "m1", "role": "user", "content": "你好"}]
    save_chat_state(tmp_path, payload)

    calls["archived_lookups"].clear()
    calls["active_lookups"].clear()
    _active_id, conversations = session_service._load_conversations(repair=True)

    by_id = {str(item.get("id") or ""): item for item in conversations}
    # 旧会话短路：不再反查。
    assert settled_id not in calls["archived_lookups"]
    assert settled_id not in calls["active_lookups"]
    # 新会话仍走完整物化：反查执行且 agent 被创建绑定。
    assert new_id in calls["active_lookups"]
    assert str(by_id[new_id].get("agentId") or "").strip()
    assert str(by_id[settled_id].get("agentId") or "").strip() == ""


def test_lookup_map_path_matches_full_projection(tmp_path, monkeypatch):
    """agent_by_id 定向反查与 list_agents 全量扫描在消费方字段上等价。"""

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)

    active = agent_directory_service.create_agent_instance(
        display_name="等价-活跃",
        role_key="engineer",
        llm_bindings={"dialogue": {"modelId": _TEST_MODEL_ID}},
    )
    agent_directory_service.update_agent_instance(
        active["agentId"], direct_session_id="eq-active-session"
    )
    archived = agent_directory_service.create_agent_instance(
        display_name="等价-归档",
        role_key="engineer",
    )
    agent_directory_service.update_agent_instance(
        archived["agentId"], direct_session_id="eq-archived-session"
    )
    agent_directory_service.archive_agent_instance(archived["agentId"])
    agent_directory_service.create_agent_instance(display_name="等价-无绑定")

    agent_by_id = session_service._agent_lookup_for_conversations()

    consumed_fields = (
        "agentId",
        "agentCode",
        "displayName",
        "kind",
        "primaryMode",
        "roleKey",
        "promptTemplateId",
        "llmBindings",
        "directSessionId",
        "createdBy",
        "status",
        "createdAt",
        "updatedAt",
    )

    def _pick(agent: dict | None) -> dict | None:
        if not isinstance(agent, dict):
            return None
        # conversationIndexKind 不进裸字段对比：全投影会回填计算出的分类值
        # （如 "invalid"），映射保留目录 raw 值；消费方读取的是分类决策结果，
        # 由下面的 classification kind 断言覆盖。
        return {key: agent.get(key) for key in consumed_fields}

    def _assert_equivalent(fallback: dict | None, fast: dict | None) -> None:
        assert _pick(fallback) == _pick(fast)
        assert agent_directory_service.agent_conversation_index_classification(
            fallback
        ).get("kind") == agent_directory_service.agent_conversation_index_classification(
            fast
        ).get("kind")
        assert session_service._agent_directory_stub_hidden_from_user_index(
            fallback, set()
        ) == session_service._agent_directory_stub_hidden_from_user_index(fast, set())

    fallback_active = session_service._agent_for_direct_session("eq-active-session")
    fast_active = session_service._agent_for_direct_session(
        "eq-active-session", agent_by_id=agent_by_id
    )
    assert fast_active is not None
    _assert_equivalent(fallback_active, fast_active)

    fallback_archived = session_service._archived_agent_for_direct_session("eq-archived-session")
    fast_archived = session_service._archived_agent_for_direct_session(
        "eq-archived-session", agent_by_id=agent_by_id
    )
    assert fast_archived is not None
    _assert_equivalent(fallback_archived, fast_archived)

    # 活跃/归档过滤语义不交叉：归档会话查不到活跃 agent，反之亦然。
    assert session_service._agent_for_direct_session(
        "eq-archived-session", agent_by_id=agent_by_id
    ) is None
    assert session_service._archived_agent_for_direct_session(
        "eq-active-session", agent_by_id=agent_by_id
    ) is None

    # 未命中语义不变。
    assert session_service._agent_for_direct_session("missing-session") is None
    assert (
        session_service._agent_for_direct_session("missing-session", agent_by_id=agent_by_id)
        is None
    )
    assert session_service._archived_agent_for_direct_session("missing-session") is None
    assert (
        session_service._archived_agent_for_direct_session("missing-session", agent_by_id=agent_by_id)
        is None
    )
