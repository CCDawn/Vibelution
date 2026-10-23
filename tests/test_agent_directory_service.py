from __future__ import annotations

from pathlib import Path

import pytest

from core.infrastructure.developer_sandbox import _filesystem_path
from core.web.services import agent_directory_service
from tests.test_agent_config_workspace_service import (
    _seed_agent_avatars,
    _use_tmp_project_root,
)


def test_replace_agent_llm_bindings_if_current_updates_under_current_timestamp(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="CAS Agent",
        llm_bindings={"dialogue": {"modelId": "ai-pixel/old"}},
    )
    recorded = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )
    secret = "raw-binding-secret"

    updated = agent_directory_service.replace_agent_llm_bindings_if_current(
        agent["agentId"],
        expected_updated_at=agent["updatedAt"],
        llm_bindings={"dialogue": {"modelId": secret}},
    )

    assert updated["updatedAt"] != agent["updatedAt"]
    assert updated["llmBindings"]["dialogue"]["modelId"] == secret
    assert (
        agent_directory_service.get_agent(agent["agentId"])["updatedAt"]
        == updated["updatedAt"]
    )
    assert recorded[0][1]["fields"]["bindingSlots"] == ["dialogue"]
    assert secret not in str(recorded)


def test_replace_agent_llm_bindings_if_current_rejects_stale_timestamp_without_overwrite(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="CAS Agent",
        llm_bindings={"dialogue": {"modelId": "ai-pixel/old"}},
    )
    concurrent = agent_directory_service.update_agent_instance(
        agent["agentId"],
        llm_bindings={"dialogue": {"modelId": "ai-pixel/concurrent"}},
    )

    with pytest.raises(agent_directory_service.AgentStateConflictError):
        agent_directory_service.replace_agent_llm_bindings_if_current(
            agent["agentId"],
            expected_updated_at=agent["updatedAt"],
            llm_bindings={"dialogue": {"modelId": "ai-pixel/gpt-5.6-luna"}},
        )

    current = agent_directory_service.get_agent(agent["agentId"])
    assert current["updatedAt"] == concurrent["updatedAt"]
    assert current["llmBindings"]["dialogue"]["modelId"] == "ai-pixel/concurrent"


def test_session_agent_tool_policy_exposes_explicit_terminal_protocol_without_widening_custom_policy(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Terminal Session Agent")

    default_policy = agent_directory_service.resolve_tool_policy_for_agent(agent["agentId"])

    assert "exec_command" in default_policy["allowedTools"]
    assert "write_stdin" in default_policy["allowedTools"]
    assert default_policy["preferredTools"][:2] == ["exec_command", "write_stdin"]
    preferred = default_policy["preferredTools"]
    assert preferred.index("github_project_library_search_tool") < preferred.index("apply_patch_tool")
    assert default_policy["maxCallsPerTurn"] == 32

    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={
            "allowedTools": ["grep_search_tool"],
            "preferredTools": ["grep_search_tool"],
        },
    )

    custom_policy = agent_directory_service.resolve_tool_policy_for_agent(agent["agentId"])

    assert custom_policy["allowedTools"] == ["grep_search_tool"]
    assert custom_policy["preferredTools"] == ["grep_search_tool"]


def test_repair_reuses_shared_workspace_and_avatar_inventory(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_agent_avatars(tmp_path)
    for index in range(8):
        agent_directory_service.create_agent_instance(display_name=f"Agent {index}")

    shared_workspace_calls = 0
    avatar_inventory_calls = 0
    tool_policy_normalization_calls = 0
    real_ensure_shared_workspace = agent_directory_service.ensure_agent_shared_workspace
    real_available_avatar_filenames = agent_directory_service._available_agent_avatar_filenames
    real_tool_policies = agent_directory_service._tool_policies

    def tracked_ensure_shared_workspace():
        nonlocal shared_workspace_calls
        shared_workspace_calls += 1
        return real_ensure_shared_workspace()

    def tracked_available_avatar_filenames():
        nonlocal avatar_inventory_calls
        avatar_inventory_calls += 1
        return real_available_avatar_filenames()

    def tracked_tool_policies(state):
        nonlocal tool_policy_normalization_calls
        tool_policy_normalization_calls += 1
        return real_tool_policies(state)

    monkeypatch.setattr(
        agent_directory_service,
        "ensure_agent_shared_workspace",
        tracked_ensure_shared_workspace,
    )
    monkeypatch.setattr(
        agent_directory_service,
        "_available_agent_avatar_filenames",
        tracked_available_avatar_filenames,
    )
    monkeypatch.setattr(
        agent_directory_service,
        "_tool_policies",
        tracked_tool_policies,
    )

    repaired = agent_directory_service.repair_agent_directory()

    assert len(repaired["agents"]) >= 8
    assert shared_workspace_calls == 1
    assert avatar_inventory_calls == 1
    assert tool_policy_normalization_calls <= 5
    assert tool_policy_normalization_calls < len(repaired["agents"])


def test_ensure_agent_workspace_only_creates_missing_directories(tmp_path, monkeypatch):
    agents_root = tmp_path / "workspace" / "agents"
    workspace = agents_root / "agent-test"
    workspace.mkdir(parents=True)
    for subdir in agent_directory_service.AGENT_WORKSPACE_SUBDIRS:
        (workspace / subdir).mkdir()

    monkeypatch.setattr(agent_directory_service, "_resolve_project_path", lambda _value: workspace)
    monkeypatch.setattr(
        agent_directory_service,
        "_workspace_path",
        lambda *_parts, **_kwargs: agents_root,
    )
    mkdir_calls: list[Path] = []
    real_mkdir = Path.mkdir

    def tracked_mkdir(path, *args, **kwargs):
        mkdir_calls.append(path)
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", tracked_mkdir)

    agent_directory_service._ensure_agent_workspace("workspace/agents/agent-test", ensure_shared=False)

    assert mkdir_calls == []

    missing = workspace / agent_directory_service.AGENT_WORKSPACE_SUBDIRS[0]
    missing.rmdir()
    agent_directory_service._ensure_agent_workspace("workspace/agents/agent-test", ensure_shared=False)

    assert mkdir_calls == [missing]
    assert missing.is_dir()


def test_workspace_ensure_uses_bound_root_without_repeating_routing(tmp_path, monkeypatch):
    root = (tmp_path / "agents").resolve()

    def unexpected_resolution(*args, **kwargs):
        pytest.fail("A bound formal repair must not repeat workspace routing")

    monkeypatch.setattr(agent_directory_service, "_resolve_project_path", unexpected_resolution)
    monkeypatch.setattr(agent_directory_service, "_workspace_path", unexpected_resolution)
    result = agent_directory_service._ensure_agent_workspace(
        "workspace/agents/bounded", ensure_shared=False, agents_root=root,
    )
    assert result == root / "bounded"
    assert all((result / name).is_dir() for name in agent_directory_service.AGENT_WORKSPACE_SUBDIRS)
    with pytest.raises(agent_directory_service.AgentDirectoryError, match="Invalid agent workspace path"):
        agent_directory_service._ensure_agent_workspace(
            "workspace/agents/../escape", ensure_shared=False, agents_root=root,
        )
    assert not (tmp_path / "escape").exists()


def test_workspace_ensure_cache_does_not_cross_bound_roots(tmp_path):
    first_root = (tmp_path / "first" / "agents").resolve()
    second_root = (tmp_path / "second" / "agents").resolve()
    first = agent_directory_service._ensure_agent_workspace(
        "workspace/agents/same-agent", ensure_shared=False, agents_root=first_root,
    )
    second = agent_directory_service._ensure_agent_workspace(
        "workspace/agents/same-agent", ensure_shared=False, agents_root=second_root,
    )
    assert first == first_root / "same-agent"
    assert second == second_root / "same-agent"
    assert second != first
    assert second.is_dir()


def test_workspace_ensure_revalidates_retargeted_link_before_cache_reuse(tmp_path):
    root = (tmp_path / "agents").resolve()
    inside = root / "inside"
    outside = tmp_path / "outside"
    inside.mkdir(parents=True)
    outside.mkdir()
    link = root / "linked-agent"
    try:
        link.symlink_to(inside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Directory symlinks unavailable: {error}")
    agent_directory_service._ensure_agent_workspace(
        "workspace/agents/linked-agent", ensure_shared=False, agents_root=root,
    )
    link.unlink()
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(agent_directory_service.AgentDirectoryError, match="Invalid agent workspace path"):
        agent_directory_service._ensure_agent_workspace(
            "workspace/agents/linked-agent", ensure_shared=False, agents_root=root,
        )
    assert list(outside.iterdir()) == []


def test_workspace_ensure_falls_back_when_enumeration_is_denied(tmp_path, monkeypatch):
    from core.web.services.agent_directory import repair_store

    root = (tmp_path / "agents").resolve()
    target = agent_directory_service._ensure_agent_workspace(
        "workspace/agents/enumeration-denied", ensure_shared=False, agents_root=root,
    )

    def denied_scan(*args, **kwargs):
        raise PermissionError("enumeration denied")

    def unexpected_mkdir(*args, **kwargs):
        pytest.fail("Attribute-readable existing directories must not require writes")

    monkeypatch.setattr(repair_store.os, "scandir", denied_scan)
    monkeypatch.setattr(Path, "mkdir", unexpected_mkdir)
    assert agent_directory_service._ensure_agent_workspace(
        "workspace/agents/enumeration-denied", ensure_shared=False, agents_root=root,
    ) == target


def test_workspace_ensure_rejects_file_in_place_of_required_directory(tmp_path):
    root = (tmp_path / "agents").resolve()
    target = agent_directory_service._ensure_agent_workspace(
        "workspace/agents/file-collision", ensure_shared=False, agents_root=root,
    )
    child = target / agent_directory_service.AGENT_WORKSPACE_SUBDIRS[0]
    child.rmdir()
    child.write_text("occupied", encoding="utf-8")
    with pytest.raises(FileExistsError):
        agent_directory_service._ensure_agent_workspace(
            "workspace/agents/file-collision", ensure_shared=False, agents_root=root,
        )
    assert child.read_text(encoding="utf-8") == "occupied"


def test_memory_policy_normalize_defaults_enabled_and_keeps_explicit_false(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Memory Switch Agent"
    )

    legacy_policy = agent_directory_service.resolve_memory_policy_for_agent(
        agent["agentId"]
    )
    assert legacy_policy["enabled"] is True

    normalized = agent_directory_service.normalize_memory_policy(
        {"readSharedGroups": ["project"]},
        "memory-custom",
        "workspace/agents/agent-x",
    )
    assert normalized["enabled"] is True
    assert normalized["readSharedGroups"] == ["project"]

    assert (
        agent_directory_service.normalize_memory_policy(
            {"enabled": 0}, "memory-custom", "workspace/agents/agent-x"
        )["enabled"]
        is False
    )
    assert (
        agent_directory_service.normalize_memory_policy(
            {"enabled": 1}, "memory-custom", "workspace/agents/agent-x"
        )["enabled"]
        is True
    )


def test_active_agent_runtime_strips_personal_memory_write_tools_when_disabled(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Memory Off Agent"
    )
    agent_id = agent["agentId"]

    with agent_directory_service.active_agent_runtime(agent_id) as runtime:
        allowed = runtime["toolPolicy"]["allowedTools"]
        assert "append_personal_memory_tool" in allowed
        assert "supersede_personal_memory_tool" in allowed

    agent_directory_service.update_agent_instance(
        agent_id, memory_policy={"enabled": False}
    )

    with agent_directory_service.active_agent_runtime(agent_id) as runtime:
        allowed = runtime["toolPolicy"]["allowedTools"]
        preferred = runtime["toolPolicy"]["preferredTools"]
        for name in (
            "append_personal_memory_tool",
            "supersede_personal_memory_tool",
            "append_episodic_memory_tool",
            "supersede_episodic_memory_tool",
        ):
            assert name not in allowed
            assert name not in preferred
        assert runtime["memoryPolicy"]["enabled"] is False

    persisted = agent_directory_service.get_agent(agent_id)
    assert "append_personal_memory_tool" in persisted["toolPolicy"]["allowedTools"]
    assert persisted["memoryPolicy"]["enabled"] is False


def test_runtime_context_block_skips_personal_memory_section_when_disabled(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Memory Context Agent"
    )
    agent_id = agent["agentId"]

    enabled_block = agent_directory_service.build_agent_runtime_context_block(agent_id)
    assert "## 个人记忆" in enabled_block

    agent_directory_service.update_agent_instance(
        agent_id, memory_policy={"enabled": False}
    )
    read_calls: list[str] = []
    real_list = agent_directory_service.list_current_episodic_events

    def tracked_list_episodes(tracked_agent_id, **kwargs):
        read_calls.append(str(tracked_agent_id))
        return real_list(tracked_agent_id, **kwargs)

    monkeypatch.setattr(
        agent_directory_service, "list_current_episodic_events", tracked_list_episodes
    )
    disabled_block = agent_directory_service.build_agent_runtime_context_block(agent_id)
    assert "## 个人记忆" not in disabled_block
    assert read_calls == []


def test_team_knowledge_access_lines_cache_hits_and_invalidates_on_agent_update(
    tmp_path, monkeypatch
):
    """访问行解析缓存：同状态重复构建零重读；agent 记录更新后立即失效。"""

    from core.web.services import chat_room_service, team_knowledge_service, team_service
    from core.web.services.agent_directory import projections as agent_directory_projections

    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    for module in (agent_directory_service, chat_room_service, team_service, team_knowledge_service):
        monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    agent_directory_projections._reset_team_knowledge_access_cache()

    agent = agent_directory_service.create_agent_instance(display_name="Cache Probe Agent")
    agent_id = agent["agentId"]

    overview_calls: list[str] = []
    real_overview = team_knowledge_service.list_knowledge_overview

    def counting_overview(*args, **kwargs):
        overview_calls.append(str(kwargs.get("agent_id") or ""))
        return real_overview(*args, **kwargs)

    monkeypatch.setattr(team_knowledge_service, "list_knowledge_overview", counting_overview)

    first_block = agent_directory_service.build_agent_runtime_context_block(agent_id)
    assert "未配置可读知识库" in first_block
    assert overview_calls == [agent_id]

    second_block = agent_directory_service.build_agent_runtime_context_block(agent_id)
    assert overview_calls == [agent_id]
    assert second_block == first_block

    agent_directory_service.update_agent_instance(agent_id, memory_policy={"enabled": False})
    third_block = agent_directory_service.build_agent_runtime_context_block(agent_id)
    assert overview_calls == [agent_id, agent_id]
    assert "未配置可读知识库" in third_block


def test_ensure_agent_shared_workspace_tolerates_extended_length_prefix_form(
    tmp_path, monkeypatch
):
    """Regression: ``\\\\?\\``-prefixed resolve() output must not fail the compare.

    ``Path.resolve`` (``ntpath.realpath``) can retain the ``\\\\?\\`` prefix
    when its post-strip re-verification loses a transient filesystem race,
    and prefixed inputs survive resolve round-trips.  The shared-workspace
    guard compares two resolutions of the same location, so one prefixed
    operand used to raise ``Invalid shared workspace path`` even though both
    sides name the same directory.
    """

    _use_tmp_project_root(tmp_path, monkeypatch)
    real_resolve_project_path = agent_directory_service._resolve_project_path

    def prefixed_resolve_project_path(path_value):
        # _filesystem_path is the product's canonical extended-length prefix
        # producer (developer_sandbox); used here so the fixture does not
        # hand-roll backslash literals.
        return _filesystem_path(real_resolve_project_path(path_value))

    monkeypatch.setattr(
        agent_directory_service,
        "_resolve_project_path",
        prefixed_resolve_project_path,
    )

    shared_root = agent_directory_service.ensure_agent_shared_workspace()

    assert str(shared_root).startswith("\\\\?\\") is False
    for subdir in ("memory", "artifacts", "notes", "logs", "research", "tmp"):
        assert (shared_root / subdir).is_dir()


def test_runtime_context_block_split_renderers_are_byte_identical_to_join(
    tmp_path, monkeypatch
):
    """static/dynamic 渲染器直出 == 兼容 wrapper + 旧 split 语义（P4a 硬门）。"""

    from core.orchestration.context_engine import _split_agent_runtime_context_block

    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Split Render Agent"
    )
    agent_id = agent["agentId"]
    agent_directory_service.write_group_context_event(
        agent_id,
        {
            "sourceRoomId": "room-split",
            "sourceRoundId": "round-split",
            "topic": "拆分等价",
            "summary": "静态与动态半段拼接必须与整块逐字节一致",
            "ownMessage": "覆盖群事件路径",
        },
    )
    agent_directory_service.write_agent_inbox_message(
        agent_id, content="覆盖收件箱路径", summary="收件箱", created_by="test"
    )

    joined = agent_directory_service.build_agent_runtime_context_block(agent_id)
    static_via_split, dynamic_via_split = _split_agent_runtime_context_block(joined)

    tool_policy = agent_directory_service.resolve_tool_policy_for_agent(agent_id)
    static_direct = "\n".join(
        line
        for line in agent_directory_service.build_agent_runtime_static_lines(
            agent_id, tool_policy_snapshot=tool_policy
        )
        if line is not None
    ).strip()
    dynamic_direct = "\n".join(
        line
        for line in agent_directory_service.build_agent_runtime_dynamic_lines(agent_id)
        if line is not None
    ).strip()

    assert static_direct == static_via_split
    assert dynamic_direct == dynamic_via_split
    assert joined == "\n".join([static_direct, dynamic_direct]).strip()
    # 冻结边界假设：动态半段首行必须命中动态标记，静态半段不含任何标记行。
    markers = ("## 个人记忆", "PersonalEpisodes:", "GroupContextEvents:", "AgentInboxMessages:")
    assert dynamic_direct
    first_line = dynamic_direct.splitlines()[0].strip()
    assert any(first_line.startswith(marker) for marker in markers)
    for line in static_direct.splitlines():
        stripped = line.strip()
        assert not any(stripped.startswith(marker) for marker in markers)
    # 不传 tool_policy_snapshot（内部自行解析）与传入解析结果字节一致。
    static_self_resolved = "\n".join(
        line
        for line in agent_directory_service.build_agent_runtime_static_lines(agent_id)
        if line is not None
    ).strip()
    assert static_self_resolved == static_direct


def test_workspace_write_decision_cache_reuses_allowed_and_keeps_blocked_fresh(
    tmp_path, monkeypatch
):
    """allowed 决策键控缓存命中；blocked 决策每次都重新评估并重复记录事件。"""

    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Decision Cache Agent")
    agent_id = agent["agentId"]
    workspace = agent_directory_service._ensure_agent_workspace(agent["workspacePath"])
    # get_agent(include_archived=True) 的 repair 分支自带解析噪声（每轮还可能
    # 不同）；固定为静态记录，把断言面收敛到 evaluate 自身的解析行为。
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda aid, include_archived=True: dict(agent),
    )

    resolve_calls: list[str] = []
    real_resolve = agent_directory_service._resolve_project_path

    def counting_resolve(path_value):
        resolve_calls.append(str(path_value))
        return real_resolve(path_value)

    monkeypatch.setattr(agent_directory_service, "_resolve_project_path", counting_resolve)
    blocked_events: list = []
    real_record = agent_directory_service._record_agent_territory_write_blocked

    def counting_record(agent, decision, *, purpose=""):
        blocked_events.append(decision)
        return real_record(agent, decision, purpose=purpose)

    monkeypatch.setattr(
        agent_directory_service, "_record_agent_territory_write_blocked", counting_record
    )

    first = agent_directory_service.evaluate_agent_workspace_write(
        agent_id, workspace, purpose="test"
    )
    assert first.allowed is True
    assert first.scope == "private"
    baseline_resolves = len(resolve_calls)

    second = agent_directory_service.evaluate_agent_workspace_write(
        agent_id, workspace, purpose="test"
    )
    assert second.allowed is True
    assert second is first
    assert len(resolve_calls) == baseline_resolves
    assert blocked_events == []

    outside = agent_directory_service.evaluate_agent_workspace_write(
        agent_id, tmp_path / "outside.txt", purpose="test"
    )
    assert outside.allowed is False
    assert blocked_events, "blocked decision must record territory events"

    outside_again = agent_directory_service.evaluate_agent_workspace_write(
        agent_id, tmp_path / "outside.txt", purpose="test"
    )
    assert outside_again.allowed is False
    assert len(blocked_events) == 2, "blocked decisions must not be cached"

    # 快照直传：跳过目录读取仍得到同一缓存决策（worker 热路径形态）。
    def _fail_get_agent(*args, **kwargs):
        raise AssertionError("agent_snapshot must bypass directory lookup")

    monkeypatch.setattr(agent_directory_service, "get_agent", _fail_get_agent)
    via_snapshot = agent_directory_service.evaluate_agent_workspace_write(
        agent_id,
        workspace,
        purpose="test",
        agent_snapshot=dict(agent),
    )
    assert via_snapshot.allowed is True
    assert via_snapshot is first


def test_ensure_agent_workspace_cache_heals_deleted_subdirs(tmp_path, monkeypatch):
    """缓存命中要求全部子目录仍在；外部删除后回落全量 ensure 重建。"""

    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Ensure Cache Agent")
    workspace = agent_directory_service._ensure_agent_workspace(agent["workspacePath"])
    assert workspace.is_dir()

    import shutil

    shutil.rmtree(workspace / "memory")
    healed = agent_directory_service._ensure_agent_workspace(agent["workspacePath"])
    assert (healed / "memory").is_dir()
