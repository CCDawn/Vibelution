"""Operator-tier gating of the Launcher platform action catalog.

The catalog ships in two tiers: the default tier (read-only and everyday-safe
writes) is always visible; the operator tier (destructive, lifecycle,
permission-reducing, one-shot migration and cleanup actions) stays hidden
until the operator opens ``[assistant] operator_tier_enabled`` in the active
operator config. These tests pin the config-read seam directly; the
suite-wide conftest pin keeps the gate open for the historical full-catalog
tests, so every closed-gate test here re-pins the seam explicitly.
"""

import asyncio
from types import SimpleNamespace

import pytest

from core.assistant_runtime import action_tiers
from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions


_APPROVED_OPERATOR_ACTIONS = frozenset({
    # 不可逆删除
    "agent_purge", "agent_purge_batch", "model_remove", "provider_remove",
    # 生命周期与归档
    "agent_archive", "team_archive", "team_member_remove", "team_member_add",
    "session_stop", "session_delete", "project_lifecycle", "runtime_command",
    # 团队/流程编排写
    "team_create", "team_update", "team_run", "flow_save", "flow_start",
    "team_recovery_confirm_deployment", "research_command",
    # 权限收缩与 ACL
    "authorization_reduce", "authorization_revoke",
    "knowledge_acl_grant", "knowledge_acl_revoke", "agent_dispatch_access_set",
    # 一次性迁移写
    "history_import", "affairs_sync", "episodic_sync", "initial_migration_queue",
    "knowledge_sync_queue", "knowledge_sync_recover",
    "reminder_handoff_queue", "reminder_handoff_recover",
    # 清理执行
    "branch_cleanup_execute",
})


class Dispatch:
    """Minimal dispatch surface, mirroring test_assistant_runtime_actions."""

    projects = {"test-project": "/private/source/path"}

    def project_ids(self):
        return list(self.projects)

    async def available_projects(self, **_kwargs):
        return {"projects": [{"projectId": key} for key in self.projects], "skippedProjects": []}

    async def discover(self, project_id):
        return {"agents": [{"agentId": "agent-1"}], "projectId": project_id}


def _full_universe() -> set:
    """Every action the assembled catalog exposes with the gate open."""
    from core.assistant_runtime import actions, local_actions

    expected = set(actions._SCHEMAS) | set(actions._documentation_contracts()) | set(actions._project_read_contracts())
    expected |= set(local_actions.contracts()) | set(actions._management_contracts())
    return expected


async def _walk_index(**query) -> dict:
    names, rows, offset = [], [], 0
    while True:
        page = await asyncio.to_thread(execute_action, "index", {"offset": offset, "limit": 12, **query})
        names.extend(row["action"] for row in page["actions"])
        rows.extend(page["actions"])
        if page["nextOffset"] is None:
            return {"names": names, "rows": rows, "total": page["total"]}
        offset = page["nextOffset"]


@pytest.fixture
def closed_gate(monkeypatch):
    """Re-pin the config-read seam so the operator tier stays closed."""
    monkeypatch.setattr(action_tiers, "read_operator_config_snapshot", lambda: {})


def test_operator_tier_set_is_exactly_the_approved_catalog():
    assert len(action_tiers.OPERATOR_TIER_ACTIONS) == 33
    assert action_tiers.OPERATOR_TIER_ACTIONS == _APPROVED_OPERATOR_ACTIONS
    # 只读对账/预览的对应动作必须留在默认档。
    assert not action_tiers.OPERATOR_TIER_ACTIONS & {
        "branch_cleanup_plan", "agent_purge_preview", "team_archive_preview",
        "history_import_receipt", "affairs_sync_receipt", "episodic_sync_receipt",
        "initial_migration_receipt", "knowledge_sync_receipt", "reminder_handoff_receipt",
        "project_lifecycle_receipt", "management_receipt",
    }


# --- 默认（开关关）：index 隐藏、describe 拒、两条执行路径拒 -----------------


@pytest.mark.anyio
async def test_closed_gate_hides_every_operator_action_from_index(closed_gate):
    dispatch = Dispatch()
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        page = await _walk_index()
        full = _full_universe()
        hidden = full & action_tiers.OPERATOR_TIER_ACTIONS
        expected_default = full - hidden
        assert page["total"] == len(expected_default)
        assert len(page["names"]) == len(set(page["names"])) and page["names"] == sorted(page["names"])
        assert set(page["names"]) == expected_default
        # 33 个 operator 档动作在装配出的目录中全部不可见。
        assert hidden and not set(page["names"]) & hidden
        assert page["total"] == len(full) - len(hidden)
    finally:
        unbind_actions(dispatch)


@pytest.mark.anyio
async def test_closed_gate_keeps_readonly_and_preview_counterparts_visible(closed_gate):
    dispatch = Dispatch()
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        page = await _walk_index()
        present = set(page["names"])
        for name in ("branch_cleanup_plan", "agent_purge_preview", "provider_update",
                     "model_add", "model_default", "settings_update", "agent_create"):
            assert name in present, name
    finally:
        unbind_actions(dispatch)


@pytest.mark.anyio
@pytest.mark.parametrize(("visible", "hidden"), [
    ("branch_cleanup_plan", "branch_cleanup_execute"),
    ("provider_update", "provider_remove"),
    ("model_add", "model_remove"),
    ("agent_purge_preview", "agent_purge"),
])
async def test_closed_gate_boundary_pairs_split_exactly_at_the_tier_line(closed_gate, visible, hidden):
    dispatch = Dispatch()
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        page = await asyncio.to_thread(execute_action, "index", {"query": visible})
        assert visible in {row["action"] for row in page["actions"]}
        contract = await asyncio.to_thread(execute_action, "describe", {"action": visible})
        assert contract["action"] == visible and "parameters" in contract
        rejection = await asyncio.to_thread(execute_action, "describe", {"action": hidden})
        assert rejection["ok"] is False and rejection["code"] == "operator_tier_disabled"
        assert rejection["action"] == hidden and "parameters" not in rejection
        executed = await asyncio.to_thread(execute_action, hidden, {})
        assert executed["ok"] is False and executed["code"] == "operator_tier_disabled"
    finally:
        unbind_actions(dispatch)


@pytest.mark.anyio
async def test_closed_gate_describe_rejection_is_distinguishable_from_unknown(closed_gate):
    dispatch = Dispatch()
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        rejection = await asyncio.to_thread(execute_action, "describe", {"action": "agent_archive"})
        assert rejection["code"] == "operator_tier_disabled" and rejection["ok"] is False
        with pytest.raises(ValueError, match="Unknown Launcher action"):
            await asyncio.to_thread(execute_action, "describe", {"action": "definitely_unknown_action"})
    finally:
        unbind_actions(dispatch)


@pytest.mark.anyio
async def test_closed_gate_blocks_both_tool_paths_before_any_dispatch(closed_gate):
    invoked = []
    async def invoke(*args, **kwargs):
        invoked.append((args, kwargs))
        return {"status": "completed"}

    dispatch = Dispatch()
    dispatch.management = SimpleNamespace(invoke=invoke)
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        # 非治理路径（personal_assistant_action_tool）：被拒的是档位，不是审批。
        blocked = await asyncio.to_thread(execute_action, "agent_archive", {
            "project_id": "test-project", "agent_id": "agent-a",
            "expected_config_revision": 1, "request_id": "r-1"})
        assert blocked["code"] == "operator_tier_disabled" and blocked["ok"] is False
        assert "approval_required" not in blocked
        # 治理路径（personal_assistant_manage_tool）：同样在分发前拦截。
        governed = await asyncio.to_thread(execute_action, "agent_purge",
            {"project_id": "test-project", "agent_id": "agent-a", "request_id": "r-2"}, governed=True)
        assert governed["code"] == "operator_tier_disabled" and governed["ok"] is False
        # 本地治理写同样拦截。
        local = await asyncio.to_thread(execute_action, "branch_cleanup_execute", {}, governed=True)
        assert local["code"] == "operator_tier_disabled" and local["ok"] is False
        # 分发层一次都未触达：直呼动作名无法绕过目录。
        assert invoked == []
    finally:
        unbind_actions(dispatch)


# --- 开关开：全量恢复现状，代表动作可执行到分发层 ----------------------------


@pytest.mark.anyio
async def test_open_gate_restores_the_full_catalog_and_dispatch():
    invoked = []
    async def invoke(project_id, *, action, request_id, parameters):
        invoked.append((project_id, action, request_id))
        return {"schemaVersion": 1, "action": action, "requestId": request_id,
                "status": "completed", "verified": True}

    dispatch = Dispatch()
    dispatch.management = SimpleNamespace(invoke=invoke)
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        page = await _walk_index()
        expected = _full_universe()
        assert page["total"] == len(expected)
        assert set(page["names"]) == expected
        for name in ("agent_archive", "branch_cleanup_execute", "model_remove"):
            row = next(r for r in page["rows"] if r["action"] == name)
            description = await asyncio.to_thread(execute_action, "describe", {"action": name})
            assert description["parameters"]["additionalProperties"] is False
            assert row["governed"] == description.get("governed", False)
        # managed 治理写放行到 management 分发层。
        receipt = await asyncio.to_thread(execute_action, "agent_archive", {
            "project_id": "test-project", "agent_id": "agent-a",
            "expected_config_revision": 3, "request_id": "open-1"}, governed=True)
        assert receipt["status"] == "completed" and receipt["requestId"] == "open-1"
        assert invoked == [("test-project", "agent_archive", "open-1")]
        # 本地治理写放行到动作自身的审批层（审批语义原样保留）。
        runtime = {"agentId": "assistant", "sessionId": "own", "turnId": "turn"}
        approval = await asyncio.to_thread(execute_action, "branch_cleanup_execute", {}, runtime=runtime)
        assert approval["status"] == "approval_required" and approval["action"] == "branch_cleanup_execute"
        # 本地删除写放行到既有引用校验闸（环境不可用时的原语义拒绝，非档位拒绝）。
        guarded = await asyncio.to_thread(execute_action, "model_remove",
            {"project_id": "test-project", "model_id": "m-1"}, runtime=runtime)
        assert guarded["status"] == "unavailable"
        assert guarded["error"] == "cross_project_reference_validation_unavailable"
    finally:
        unbind_actions(dispatch)


# --- 开关读取：只来自 config，严格 bool，失败保持关闭 ------------------------


def test_reader_accepts_only_strict_true_from_config_dict():
    assert action_tiers.operator_tier_enabled({"assistant": {"operator_tier_enabled": True}}) is True
    for config in ({}, {"assistant": {}}, {"assistant": {"operator_tier_enabled": False}},
                   {"assistant": {"operator_tier_enabled": "true"}},
                   {"assistant": {"operator_tier_enabled": 1}},
                   {"assistant": None}, {"operator_tier_enabled": True}):
        assert action_tiers.operator_tier_enabled(config) is False, config


def test_reader_failure_keeps_the_tier_closed(monkeypatch):
    def unavailable():
        raise ValueError("EXISTING_CONFIG_UNAVAILABLE")

    monkeypatch.setattr(action_tiers, "read_operator_config_snapshot", unavailable)
    assert action_tiers.operator_tier_enabled() is False


def test_reader_follows_the_live_operator_config_file_per_call(tmp_path, monkeypatch):
    from config.paths import resolve_config_path
    from config.public_config import read_existing_config_snapshot

    def real_chain():
        return read_existing_config_snapshot(resolve_config_path())

    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(action_tiers, "read_operator_config_snapshot", real_chain)
    # 缺失文件：保持关闭。
    assert action_tiers.operator_tier_enabled() is False
    config_path.write_text("[assistant]\noperator_tier_enabled = true\n", encoding="utf-8")
    assert action_tiers.operator_tier_enabled() is True
    # 同一进程内手动改回即关闭：每次装配重新读取，无进程级缓存。
    config_path.write_text("[ui]\nlanguage = \"zh\"\n", encoding="utf-8")
    assert action_tiers.operator_tier_enabled() is False


def test_config_model_defaults_the_switch_closed():
    from config.models import AppConfig, AssistantConfig

    assert AppConfig().assistant.operator_tier_enabled is False
    assert AssistantConfig.model_validate({"operator_tier_enabled": True}).operator_tier_enabled is True
    assert AppConfig.model_validate({"assistant": {"operator_tier_enabled": True}}).assistant.operator_tier_enabled is True
    # 模型层只是声明；档位开启只认读取链里的严格 bool True（见上方 reader 测试），
    # 字符串等弱类型值在读取链处一律视为关闭。
    assert action_tiers.operator_tier_enabled({"assistant": {"operator_tier_enabled": "yes"}}) is False


# --- 安全：开关不出现在任何默认档动作参数面 ----------------------------------


def _collect_schema_keys(node, keys):
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(key)
            _collect_schema_keys(value, keys)
    elif isinstance(node, list):
        for item in node:
            _collect_schema_keys(item, keys)


@pytest.mark.anyio
async def test_switch_is_absent_from_every_action_parameter_surface():
    dispatch = Dispatch()
    bind_actions(dispatch, asyncio.get_running_loop())
    try:
        page = await _walk_index()
        assert page["names"], "catalog must not be empty"
        for name in page["names"]:
            contract = await asyncio.to_thread(execute_action, "describe", {"action": name})
            keys = set()
            _collect_schema_keys(contract.get("parameters", {}), keys)
            assert "operator_tier_enabled" not in keys, name
            assert "assistant" not in keys, name
    finally:
        unbind_actions(dispatch)


def test_config_update_whitelist_rejects_the_assistant_section():
    from tools import pa_managed_writes

    with pytest.raises(ValueError):
        pa_managed_writes._validate_one_update("assistant", "operator_tier_enabled", True)
    with pytest.raises(ValueError):
        pa_managed_writes._validate_one_update("assistant", "anything", True)


def test_settings_update_whitelist_rejects_the_assistant_section(tmp_path):
    from tools.pa_settings_actions import _validate_updates

    with pytest.raises(ValueError):
        _validate_updates([{"section": "assistant", "key": "operator_tier_enabled", "value": True}],
                          tmp_path / "config.toml")
