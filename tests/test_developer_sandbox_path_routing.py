from __future__ import annotations

from core.infrastructure import developer_sandbox
from core.gym import episodes as gym_episodes
from core.prompt_manager import prompt_manager
from core.web.services import (
    computer_use_service,
    memory_service,
    project_agent_bus_service,
    rag_vector_index_service,
    reset_service,
    session_service,
    supervised_control_service,
    supervised_worktree_evolution_service,
)


def _enable_sandbox(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    project_root = tmp_path / "project"
    data_home = tmp_path / "operator-data"
    project_root.mkdir()
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: data_home / "workspace")
    status = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    enabled = developer_sandbox.update_developer_mode_status(
        True,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=project_root,
    )
    return project_root, data_home, enabled["sandbox"]["sandboxId"]


def test_high_roi_state_paths_route_to_developer_sandbox(tmp_path, monkeypatch):
    project_root, _data_home, sandbox_id = _enable_sandbox(tmp_path, monkeypatch)
    sandbox_workspace = project_root / ".runtime" / "developer-mode" / "sandboxes" / sandbox_id / "workspace"

    monkeypatch.setattr(prompt_manager, "_resolve_project_root", lambda: project_root)
    monkeypatch.setattr(computer_use_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(rag_vector_index_service.team_knowledge_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(reset_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", project_root)

    assert prompt_manager._get_dynamic_root() == sandbox_workspace / "prompts"
    assert memory_service._managed_memory_path(project_root) == sandbox_workspace / "memory" / "user_memory_overrides.json"
    assert rag_vector_index_service._index_root() == sandbox_workspace / "knowledge" / "rag"
    assert project_agent_bus_service._bus_events_path() == sandbox_workspace / "project_agent_bus" / "events.jsonl"
    assert gym_episodes._gym_workspace(project_root) == sandbox_workspace / "gym"
    assert computer_use_service._session_dir("debug-session") == sandbox_workspace / "computer_use_sessions" / "debug-session"
    assert supervised_worktree_evolution_service._run_store_root(project_root) == sandbox_workspace / "supervised_evolution" / "worktree_runs"
    assert session_service._cli_agent_lifecycle_sidecar_path("debug-session") == (
        sandbox_workspace / "sessions" / "debug-session" / "logs" / "cli_agent_lifecycle.jsonl"
    )
    assert reset_service._collect_workspace_sessions()[0].path == sandbox_workspace / "sessions"
    assert reset_service._collect_chat_rooms()[0].path == sandbox_workspace / "chat_rooms"
    assert supervised_control_service._supervised_decision_path("debug-session") == (
        sandbox_workspace / "supervised_evolution" / "decisions" / "debug-session.json"
    )
    assert supervised_control_service._supervised_history_path() == (
        sandbox_workspace / "supervised_evolution" / "history.jsonl"
    )


def test_high_roi_state_paths_stay_formal_when_developer_mode_is_off(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    project_root = tmp_path / "project"
    data_home = tmp_path / "operator-data"
    project_root.mkdir()
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: data_home / "workspace")
    monkeypatch.setattr(prompt_manager, "_resolve_project_root", lambda: project_root)
    monkeypatch.setattr(computer_use_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(rag_vector_index_service.team_knowledge_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(reset_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", project_root)

    workspace = data_home / "workspace"
    assert prompt_manager._get_dynamic_root() == workspace / "prompts"
    assert memory_service._managed_memory_path(project_root) == workspace / "memory" / "user_memory_overrides.json"
    assert rag_vector_index_service._index_root() == workspace / "knowledge" / "rag"
    assert project_agent_bus_service._bus_events_path() == workspace / "project_agent_bus" / "events.jsonl"
    assert gym_episodes._gym_workspace(project_root) == workspace / "gym"
    assert computer_use_service._session_dir("debug-session") == workspace / "computer_use_sessions" / "debug-session"
    assert supervised_worktree_evolution_service._run_store_root(project_root) == workspace / "supervised_evolution" / "worktree_runs"
    assert session_service._cli_agent_lifecycle_sidecar_path("debug-session") == (
        workspace / "sessions" / "debug-session" / "logs" / "cli_agent_lifecycle.jsonl"
    )
    assert reset_service._collect_workspace_sessions()[0].path == workspace / "sessions"
    assert reset_service._collect_chat_rooms()[0].path == workspace / "chat_rooms"
    assert supervised_control_service._supervised_decision_path("debug-session") == (
        workspace / "supervised_evolution" / "decisions" / "debug-session.json"
    )
    assert supervised_control_service._supervised_history_path() == workspace / "supervised_evolution" / "history.jsonl"
