"""进程内路径解析缓存的命中 / 失效 / 线程安全契约测试。

覆盖 perf-path-resolution-cache 任务引入的三处缓存：
- vibelution_storage：root resolve / identity / storage paths / active paths / data|workspace home
- developer_sandbox：root resolve / config path / active state / config 读取
- agent_directory repair_store：_workspace_path 与 load_state

失效正确性优先于命中率：任何底层文件 / 环境变量 / 显式写入变化都必须立即可见。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import vibelution_storage as storage
from core.infrastructure import developer_sandbox
from core.web.services import agent_directory_service


def _write_identity(root: Path, project_id: str = "demo-project") -> Path:
    identity_path = root / ".vibelution" / "project.json"
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity_path.write_text(
        json.dumps({"schemaVersion": 1, "projectId": project_id}),
        encoding="utf-8",
    )
    return identity_path


def _write_marker(paths: storage.ProjectStoragePaths, *, status: str = "completed") -> Path:
    marker = storage.storage_migration_state_path(paths)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": status,
                "projectId": paths.project_id,
                "instanceId": paths.instance_id,
            }
        ),
        encoding="utf-8",
    )
    return marker


@pytest.fixture()
def project_env(tmp_path, monkeypatch):
    """隔离的项目存储环境：identity + projects home 全部落在 tmp_path。"""

    projects_home = tmp_path / "projects"
    monkeypatch.setenv(storage.PROJECTS_HOME_ENV, str(projects_home))
    monkeypatch.delenv("VIBELUTION_DATA_HOME", raising=False)
    root = tmp_path / "project"
    root.mkdir()
    _write_identity(root)
    return root


# ---------------------------------------------------------------------------
# vibelution_storage


def test_resolve_project_storage_paths_caches_and_invalidates_on_identity_change(project_env):
    first = storage.resolve_project_storage_paths(project_env)
    second = storage.resolve_project_storage_paths(project_env)
    assert first is second  # 命中缓存：同一进程相同输入零重算

    _write_identity(project_env, project_id="renamed-project")
    refreshed = storage.resolve_project_storage_paths(project_env)

    assert refreshed is not first
    assert refreshed.project_id == "renamed-project"
    assert refreshed.project_home.name == "renamed-project"


def test_load_project_identity_caches_errors_and_invalidates(project_env):
    identity_path = project_env / ".vibelution" / "project.json"
    first = storage.load_project_identity(project_env)
    assert storage.load_project_identity(project_env) is first

    identity_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(storage.ProjectIdentityError):
        storage.load_project_identity(project_env)

    _write_identity(project_env, project_id="recovered-project")
    assert storage.load_project_identity(project_env).project_id == "recovered-project"


def test_resolve_active_project_storage_paths_caches_migrated_state(project_env):
    target = storage.resolve_project_storage_paths(project_env)
    _write_marker(target)

    first = storage.resolve_active_project_storage_paths(project_env)
    second = storage.resolve_active_project_storage_paths(str(project_env))
    assert first is second
    assert first == target

    # marker 被改写为非法内容 → 立即 fail closed，不得返回陈旧结果
    marker = storage.storage_migration_state_path(target)
    marker.write_text(json.dumps({"schemaVersion": 1, "status": "in_progress"}), encoding="utf-8")
    with pytest.raises(storage.ProjectStorageMigrationStateError):
        storage.resolve_active_project_storage_paths(project_env)

    _write_marker(target)
    assert storage.resolve_active_project_storage_paths(project_env) == target


def test_resolve_active_project_storage_paths_premigration_branch_stays_live(project_env, monkeypatch):
    # legacy.data 解析到运营者 data home；用空目录隔离宿主机真实数据。
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(project_env.parent / "operator-data"))
    (project_env / ".git").mkdir()  # 主 checkout 形态

    first = storage.resolve_active_project_storage_paths(project_env)
    assert first.migrated is True  # 无 marker 无 legacy → 直接 target

    legacy_runtime = project_env / ".runtime"
    legacy_runtime.mkdir()
    (legacy_runtime / "state.json").write_text("{}", encoding="utf-8")
    second = storage.resolve_active_project_storage_paths(project_env)
    assert second.migrated is False  # legacy 出现必须立即可见（该分支不缓存）
    assert second.runtime == legacy_runtime

    target = storage.resolve_project_storage_paths(project_env)
    _write_marker(target)
    third = storage.resolve_active_project_storage_paths(project_env)
    assert third.migrated is True
    assert third == target


def test_storage_paths_cache_key_includes_projects_home_env(project_env, monkeypatch):
    first = storage.resolve_project_storage_paths(project_env)

    other_home = project_env.parent / "other-projects"
    monkeypatch.setenv(storage.PROJECTS_HOME_ENV, str(other_home))
    refreshed = storage.resolve_project_storage_paths(project_env)

    assert refreshed != first
    assert refreshed.projects_home == other_home.resolve()


def test_resolve_project_data_home_honors_env_change_after_caching(project_env, monkeypatch):
    target = storage.resolve_project_storage_paths(project_env)
    _write_marker(target)

    first = storage.resolve_project_data_home(project_env)
    assert first == target.data

    override = project_env.parent / "override-data"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(override))
    assert storage.resolve_project_data_home(project_env) == override.resolve()

    monkeypatch.delenv("VIBELUTION_DATA_HOME", raising=False)
    assert storage.resolve_project_data_home(project_env) == target.data


def test_resolve_project_workspace_home_caches_final_resolve(project_env):
    target = storage.resolve_project_storage_paths(project_env)
    _write_marker(target)

    first = storage.resolve_project_workspace_home(project_env)
    second = storage.resolve_project_workspace_home(project_env)
    assert first is second
    assert first == (target.data / "workspace").resolve()


def test_storage_resolution_caches_are_thread_safe(project_env):
    target = storage.resolve_project_storage_paths(project_env)
    _write_marker(target)
    expected = storage.resolve_active_project_storage_paths(project_env)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(25):
                assert storage.resolve_project_storage_paths(project_env) == expected
                assert storage.resolve_active_project_storage_paths(project_env) == expected
                assert storage.resolve_project_data_home(project_env) == expected.data
                storage.resolve_project_workspace_home(project_env)
        except BaseException as exc:  # noqa: BLE001 - 汇聚线程内所有失败
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: worker(), range(8)))

    assert not errors


# ---------------------------------------------------------------------------
# developer_sandbox


def _prepare_sandbox_env(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(
        developer_sandbox,
        "resolve_workspace_home",
        lambda *args, **kwargs: project_root / "workspace",
    )
    developer_sandbox._clear_developer_mode_config_cache()
    return config_path, project_root


def test_is_developer_mode_enabled_reflects_config_rewrite(tmp_path, monkeypatch):
    config_path, _root = _prepare_sandbox_env(tmp_path, monkeypatch)

    assert developer_sandbox.is_developer_mode_enabled() is False
    assert developer_sandbox.is_developer_mode_enabled() is False  # 命中缓存

    config_path.write_text(
        "[launcher]\ncontrol_port = 8765\n[launcher.developer_mode]\nenabled = true\n",
        encoding="utf-8",
    )
    assert developer_sandbox.is_developer_mode_enabled() is True

    config_path.write_text(
        "[launcher]\ncontrol_port = 8765\n[launcher.developer_mode]\nenabled = false\n",
        encoding="utf-8",
    )
    assert developer_sandbox.is_developer_mode_enabled() is False


def test_active_state_cache_invalidates_on_external_rewrite(tmp_path, monkeypatch):
    config_path, project_root = _prepare_sandbox_env(tmp_path, monkeypatch)
    status = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    enabled = developer_sandbox.update_developer_mode_status(
        True,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=project_root,
    )
    sandbox_id = enabled["sandbox"]["sandboxId"]
    assert developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)[
        "sandbox"
    ]["sandboxId"] == sandbox_id  # 命中缓存

    state_path = Path(enabled["sandbox"]["statePath"])
    state_path.write_text(
        json.dumps({"schemaVersion": 1, "sandboxId": "dev-external-rewrite", "createdAt": "now"}),
        encoding="utf-8",
    )
    refreshed = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    assert refreshed["sandbox"]["sandboxId"] == "dev-external-rewrite"


def test_clear_active_sandbox_invalidates_state_cache(tmp_path, monkeypatch):
    config_path, project_root = _prepare_sandbox_env(tmp_path, monkeypatch)
    status = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    developer_sandbox.update_developer_mode_status(
        True,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=project_root,
    )

    developer_sandbox.clear_active_sandbox(project_root=project_root)

    refreshed = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    assert refreshed["sandbox"]["sandboxId"] == ""
    assert refreshed["sandbox"]["active"] is False


def test_developer_sandbox_status_is_thread_safe(tmp_path, monkeypatch):
    config_path, project_root = _prepare_sandbox_env(tmp_path, monkeypatch)
    expected = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)[
        "configHash"
    ]
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(25):
                assert developer_sandbox.is_developer_mode_enabled() is False
                status = developer_sandbox.get_developer_mode_status(
                    config_path=config_path, project_root=project_root
                )
                assert status["configHash"] == expected
                developer_sandbox.workspace_routing_fingerprint(project_root)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: worker(), range(8)))

    assert not errors


# ---------------------------------------------------------------------------
# agent_directory repair_store


@pytest.fixture()
def agent_registry_env(tmp_path, monkeypatch):
    """隔离的 Agent 注册表环境；同时固定 developer_sandbox 配置文件保证密闭。"""

    projects_home = tmp_path / "projects"
    monkeypatch.setenv(storage.PROJECTS_HOME_ENV, str(projects_home))
    monkeypatch.delenv("VIBELUTION_DATA_HOME", raising=False)
    root = tmp_path / "project"
    root.mkdir()
    _write_identity(root)
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    developer_sandbox._clear_developer_mode_config_cache()
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", root)
    agent_directory_service._invalidate_repaired_state_cache()
    yield root, config_path
    agent_directory_service._invalidate_repaired_state_cache()


def test_load_state_caches_and_returns_independent_copies(agent_registry_env):
    agent_directory_service.save_state(
        {
            "agents": [
                {
                    "agentId": "agent-cache-probe",
                    "displayName": "Cache Probe",
                    "primaryMode": "general",
                }
            ]
        }
    )

    first = agent_directory_service.load_state()
    second = agent_directory_service.load_state()
    assert first is not second
    assert [a["agentId"] for a in second["agents"]] == ["agent-cache-probe"]

    # 调用方修改返回值不得污染缓存快照
    first["agents"].append({"agentId": "mutation-probe"})
    third = agent_directory_service.load_state()
    assert [a["agentId"] for a in third["agents"]] == ["agent-cache-probe"]


def test_load_state_invalidates_on_external_registry_rewrite(agent_registry_env):
    agent_directory_service.save_state({"agents": [{"agentId": "agent-before", "displayName": "Before"}]})
    assert [a["agentId"] for a in agent_directory_service.load_state()["agents"]] == ["agent-before"]

    registry = agent_directory_service.registry_path()
    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["agents"] = [{"agentId": "agent-after-external", "displayName": "After External"}]
    registry.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    reloaded = agent_directory_service.load_state()
    assert [a["agentId"] for a in reloaded["agents"]] == ["agent-after-external"]


def test_load_state_invalidates_on_save_state(agent_registry_env):
    agent_directory_service.save_state({"agents": [{"agentId": "agent-v1", "displayName": "V1"}]})
    assert [a["agentId"] for a in agent_directory_service.load_state()["agents"]] == ["agent-v1"]

    agent_directory_service.save_state(
        {"agents": [{"agentId": "agent-v1", "displayName": "V1"}, {"agentId": "agent-v2", "displayName": "V2"}]}
    )
    assert [a["agentId"] for a in agent_directory_service.load_state()["agents"]] == ["agent-v1", "agent-v2"]


def test_workspace_path_caches_formal_route_and_reflects_dev_toggle(agent_registry_env):
    project_root, config_path = agent_registry_env

    first = agent_directory_service._workspace_path("agents")
    second = agent_directory_service._workspace_path("agents")
    assert first == second
    assert "sandboxes" not in str(first)

    status = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    developer_sandbox.update_developer_mode_status(
        True,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=project_root,
    )
    try:
        routed = agent_directory_service._workspace_path("agents")
        assert "sandboxes" in str(routed)  # dev 开启后必须立即改路由，不得吃旧缓存
    finally:
        developer_sandbox.update_developer_mode_status(
            False,
            base_hash=developer_sandbox.get_developer_mode_status(
                config_path=config_path, project_root=project_root
            )["configHash"],
            config_path=config_path,
            project_root=project_root,
        )
    assert agent_directory_service._workspace_path("agents") == first


def test_load_state_is_thread_safe(agent_registry_env):
    agent_directory_service.save_state({"agents": [{"agentId": "agent-thread", "displayName": "Thread"}]})
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(20):
                state = agent_directory_service.load_state()
                assert [a["agentId"] for a in state["agents"]] == ["agent-thread"]
                state["agents"].append({"agentId": "local-mutation"})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: worker(), range(8)))

    assert not errors
    assert [a["agentId"] for a in agent_directory_service.load_state()["agents"]] == ["agent-thread"]


@pytest.mark.parametrize("warm", [False, True])
def test_load_agent_record_copies_only_selected_record(agent_registry_env, monkeypatch, warm):
    from core.web.services.agent_directory import repair_store

    agent_directory_service.save_state({"agents": [
        {"agentId": "selected", "metadata": {"nested": ["original"]}},
        {"agentId": "unrelated", "metadata": {"nested": ["other"]}},
    ]})
    if warm:
        agent_directory_service.load_state()
    original_copy = repair_store._copy_json_value
    copied_agents = []

    def tracked_copy(value):
        if isinstance(value, dict) and "agentId" in value:
            copied_agents.append(value["agentId"])
        return original_copy(value)

    monkeypatch.setattr(repair_store, "_copy_json_value", tracked_copy)
    first = agent_directory_service.load_agent_record(" selected ")
    first["metadata"]["nested"].append("local mutation")
    second = agent_directory_service.load_agent_record("selected")

    assert copied_agents == ["selected", "selected"]
    assert second["metadata"]["nested"] == ["original"]
    assert agent_directory_service.load_agent_record("missing") is None
    assert agent_directory_service.load_agent_record("") is None
    assert agent_directory_service.load_state()["agents"][0] == second


@pytest.mark.parametrize("consumer", ["territory", "financial_config"])
def test_background_agent_consumers_never_copy_unrelated_registry_rows(agent_registry_env, monkeypatch, consumer):
    from core.web.services.agent_directory import repair_store
    from core.web.services.financial_team import provisioning

    agent_directory_service.save_state({"agents": [
        {"agentId": "selected", "status": "archived", "workspacePath": "workspace/agents/selected",
         "metadata": {"nested": ["original"]}},
        {"agentId": "unrelated", "metadata": {"nested": ["unrelated"]}},
    ]})
    copied_agents = []
    original_copy = repair_store._copy_json_value

    def tracked_copy(value):
        if isinstance(value, dict) and "agentId" in value:
            copied_agents.append(value["agentId"])
        return original_copy(value)

    def forbidden_full_copy():
        raise AssertionError("single-Agent reads must not copy the full registry")

    monkeypatch.setattr(repair_store, "_copy_json_value", tracked_copy)
    monkeypatch.setattr(agent_directory_service, "load_state", forbidden_full_copy)
    if consumer == "territory":
        read = agent_directory_service.resolve_agent_workspace_territory
        first = read(" selected ")
        assert first["privateRoot"] == "workspace/agents/selected"
        first["subdirs"]["artifacts"] = "local mutation"
        assert read("selected")["subdirs"]["artifacts"] != "local mutation"
        assert read("missing") == {}
        assert read("") == {}
    else:
        def project(raw, *, include_activity):
            assert include_activity is False
            return raw

        monkeypatch.setattr(agent_directory_service, "_agent_to_api", project)
        first = provisioning._agent_config(" selected ")
        assert first["status"] == "archived"
        first["metadata"]["nested"].append("local mutation")
        assert provisioning._agent_config("selected")["metadata"]["nested"] == ["original"]
        assert provisioning._agent_config("missing") is None
        assert provisioning._agent_config("") is None
    assert copied_agents == ["selected", "selected"]


def test_load_agent_record_preserves_archived_selection_order(agent_registry_env):
    from core.web.services import agent_tool_governance_service

    agent_directory_service.save_state({"agents": [
        {"agentId": "duplicate", "status": " archived ", "displayName": "Archived"},
        {"agentId": "duplicate", "status": "active", "displayName": "Active"},
    ]})
    assert agent_directory_service.load_agent_record("duplicate")["displayName"] == "Archived"
    assert agent_tool_governance_service._raw_agent("duplicate", include_archived=False)["displayName"] == "Active"
    assert agent_tool_governance_service._raw_agent("duplicate", include_archived=True)["displayName"] == "Archived"


@pytest.mark.parametrize("write_mode", ["save", "external", "delete"])
def test_load_agent_record_observes_registry_changes(agent_registry_env, write_mode):
    agent_directory_service.save_state({"agents": [{"agentId": "target", "displayName": "Before"}]})
    assert agent_directory_service.load_agent_record("target")["displayName"] == "Before"
    state = agent_directory_service.load_state()
    state["agents"][0]["displayName"] = "After"
    registry = agent_directory_service.registry_path()
    if write_mode == "save":
        agent_directory_service.save_state(state)
    elif write_mode == "external":
        registry.write_text(json.dumps(state, indent=2), encoding="utf-8")
    else:
        registry.unlink()
    result = agent_directory_service.load_agent_record("target")
    assert result is None if write_mode == "delete" else result["displayName"] == "After"


@pytest.mark.parametrize("payload", ["{bad json", "[]"])
@pytest.mark.parametrize("agent_id", ["target", ""])
def test_load_agent_record_rejects_corruption_after_warm_read(agent_registry_env, payload, agent_id):
    agent_directory_service.save_state({"agents": [{"agentId": "target"}]})
    assert agent_directory_service.load_agent_record("target")
    agent_directory_service.registry_path().write_text(payload, encoding="utf-8")
    with pytest.raises(agent_directory_service.AgentDirectoryError):
        agent_directory_service.load_agent_record(agent_id)


def test_load_agent_record_isolates_project_roots(agent_registry_env):
    root, _ = agent_registry_env
    other_root = root.parent / "other-project"
    other_root.mkdir()
    _write_identity(other_root, "other-project")
    agent_directory_service.save_state({"agents": [{"agentId": "same-id", "displayName": "First"}]})
    assert agent_directory_service.load_agent_record("same-id")["displayName"] == "First"
    with agent_directory_service.scoped_project_root(other_root):
        agent_directory_service.save_state({"agents": [{"agentId": "same-id", "displayName": "Second"}]})
        assert agent_directory_service.load_agent_record("same-id")["displayName"] == "Second"
    assert agent_directory_service.load_agent_record("same-id")["displayName"] == "First"


def test_load_agent_record_is_thread_safe(agent_registry_env):
    agent_directory_service.save_state({"agents": [{"agentId": "target", "metadata": {"values": ["original"]}}]})

    def read_and_mutate(_):
        for _ in range(20):
            record = agent_directory_service.load_agent_record("target")
            assert record["metadata"]["values"] == ["original"]
            record["metadata"]["values"].append("local")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(read_and_mutate, range(8)))
    assert agent_directory_service.load_state()["agents"][0]["metadata"]["values"] == ["original"]


@pytest.mark.parametrize("warm", [False, True])
def test_load_agent_records_copies_only_matching_rows(agent_registry_env, monkeypatch, warm):
    from core.web.services.agent_directory import repair_store

    agent_directory_service.save_state({"agents": [
        {"agentId": "by-id", "metadata": {"nested": ["original"]}},
        {"agentId": "unrelated", "metadata": {"large": ["untouched"] * 100}},
        {"agentId": "by-session", "directSessionId": "direct", "metadata": {"nested": ["original"]}},
    ]})
    if warm:
        agent_directory_service.load_state()
    original_copy = repair_store._copy_json_value
    copied_agents = []

    def tracked_copy(value):
        if isinstance(value, dict) and "agentId" in value:
            assert value["agentId"] != "unrelated"
            copied_agents.append(value["agentId"])
        assert not (isinstance(value, dict) and "agents" in value)
        return original_copy(value)

    def unexpected_full_read_or_write(*args, **kwargs):
        pytest.fail("Targeted reads must not copy the full registry, repair, or write")

    monkeypatch.setattr(repair_store, "_copy_json_value", tracked_copy)
    monkeypatch.setattr(agent_directory_service, "load_state", unexpected_full_read_or_write)
    monkeypatch.setattr(agent_directory_service, "repair_agent_directory", unexpected_full_read_or_write)
    monkeypatch.setattr(agent_directory_service, "save_state", unexpected_full_read_or_write)
    first = agent_directory_service.load_agent_records(agent_ids=(value for value in [" by-id ", "by-id"]), direct_session_ids=[" direct "])
    assert copied_agents == ["by-id", "by-session"]
    first[0]["metadata"]["nested"].append("local mutation")
    first[1]["metadata"]["nested"].append("local mutation")
    first.append({"agentId": "local"})
    second = agent_directory_service.load_agent_records(agent_ids=["by-id"], direct_session_ids=["direct"])
    assert copied_agents == ["by-id", "by-session", "by-id", "by-session"]
    assert [row["metadata"]["nested"] for row in second] == [["original"], ["original"]]
    assert agent_directory_service.load_agent_records(agent_ids=["missing"], direct_session_ids=["missing"]) == []


def test_load_agent_records_does_not_visit_unrelated_nested_values(agent_registry_env, monkeypatch):
    from core.web.services.agent_directory import repair_store

    class UnrelatedContents(dict):
        def items(self):
            pytest.fail("Unselected record contents must not be traversed")

    snapshot = {"agents": [
        {"agentId": "unrelated", "metadata": UnrelatedContents(secret="untouched")},
        {"agentId": "selected", "metadata": {"nested": ["original"]}},
    ]}
    monkeypatch.setattr(repair_store, "_load_state_snapshot_locked", lambda: snapshot)
    assert agent_directory_service.load_agent_records(agent_ids=["selected"]) == [snapshot["agents"][1]]


@pytest.mark.parametrize("selection", [{}, {"agent_ids": ["", " "]}, {"direct_session_ids": ["", " "]}])
def test_load_agent_records_empty_selection_does_not_widen_or_load(monkeypatch, selection):
    from core.web.services.agent_directory import repair_store

    def unexpected_load():
        pytest.fail("Empty selection must not load or copy the registry")

    monkeypatch.setattr(repair_store, "_load_state_snapshot_locked", unexpected_load)
    monkeypatch.setattr(repair_store, "_copy_json_value", unexpected_load)
    assert agent_directory_service.load_agent_records(**selection) == []


def test_load_agent_records_preserves_union_collisions_archived_and_duplicate_order(agent_registry_env):
    agents = [
        {"agentId": "duplicate", "directSessionId": "shared", "status": "archived", "displayName": "First"},
        {"agentId": "unrelated", "directSessionId": "other"},
        {"agentId": "duplicate", "directSessionId": "different", "status": "active", "displayName": "Second"},
        {"agentId": "collision", "directSessionId": "shared", "status": "archived", "displayName": "Third"},
        {"agentId": "duplicate", "directSessionId": "shared", "status": "active", "displayName": "Fourth"},
    ]
    agent_directory_service.save_state({"agents": agents})
    rows = agent_directory_service.load_agent_records(agent_ids=["duplicate"], direct_session_ids=(value for value in ["shared", "shared"]))
    assert [row["displayName"] for row in rows] == ["First", "Second", "Third", "Fourth"]
    assert [row["status"] for row in rows] == ["archived", "active", "archived", "active"]


def test_load_agent_records_direct_match_includes_last_duplicate_identity_record(agent_registry_env):
    agent_directory_service.save_state({"agents": [
        {"agentId": "duplicate", "directSessionId": "target", "status": "active", "displayName": "Earlier"},
        {"agentId": "unrelated", "directSessionId": "other", "status": "active"},
        {"agentId": "duplicate", "directSessionId": "other", "status": "archived", "displayName": "Last"},
    ]})
    full_rows = agent_directory_service.load_state()["agents"]
    rows = agent_directory_service.load_agent_records(direct_session_ids=["target"])

    assert [row["displayName"] for row in rows] == ["Earlier", "Last"]
    assert {row["agentId"]: row for row in rows} == {
        row["agentId"]: row for row in full_rows if row["agentId"] == "duplicate"
    }
    assert rows[-1]["status"] == "archived"
    assert rows[-1]["directSessionId"] == "other"


def test_load_agent_records_does_not_expand_anonymous_direct_matches(monkeypatch):
    from core.web.services.agent_directory import repair_store

    matched = {"directSessionId": "target", "displayName": "Anonymous match"}
    unrelated = {"agentId": "", "directSessionId": "other", "displayName": "Unrelated anonymous"}
    monkeypatch.setattr(repair_store, "_load_state_snapshot_locked", lambda: {"agents": [matched, unrelated]})
    assert agent_directory_service.load_agent_records(direct_session_ids=["target"]) == [matched]


@pytest.mark.parametrize("write_mode", ["save", "external", "replace", "delete"])
def test_load_agent_records_observes_registry_changes(agent_registry_env, write_mode):
    agent_directory_service.save_state({"agents": [{"agentId": "target", "directSessionId": "before"}]})
    assert agent_directory_service.load_agent_records(direct_session_ids=["before"])[0]["agentId"] == "target"
    state = agent_directory_service.load_state()
    state["agents"][0]["directSessionId"] = "after-external-change"
    registry = agent_directory_service.registry_path()
    if write_mode == "save":
        agent_directory_service.save_state(state)
    elif write_mode == "external":
        registry.write_text(json.dumps(state, indent=2), encoding="utf-8")
    elif write_mode == "replace":
        replacement = registry.with_name("replacement.json")
        replacement.write_text(json.dumps(state, indent=2), encoding="utf-8")
        replacement.replace(registry)
    else:
        registry.unlink()
    assert agent_directory_service.load_agent_records(direct_session_ids=["before"]) == []
    rows = agent_directory_service.load_agent_records(direct_session_ids=["after-external-change"])
    assert rows == [] if write_mode == "delete" else rows[0]["agentId"] == "target"


def test_load_agent_records_isolates_project_roots(agent_registry_env):
    root, _ = agent_registry_env
    other_root = root.parent / "other-project"
    other_root.mkdir()
    _write_identity(other_root, "other-project")
    agent_directory_service.save_state({"agents": [{"agentId": "same-id", "directSessionId": "same-direct", "displayName": "First"}]})
    assert agent_directory_service.load_agent_records(agent_ids=["same-id"])[0]["displayName"] == "First"
    with agent_directory_service.scoped_project_root(other_root):
        agent_directory_service.save_state({"agents": [{"agentId": "same-id", "directSessionId": "same-direct", "displayName": "Second"}]})
        assert agent_directory_service.load_agent_records(direct_session_ids=["same-direct"])[0]["displayName"] == "Second"
    assert agent_directory_service.load_agent_records(direct_session_ids=["same-direct"])[0]["displayName"] == "First"
