from __future__ import annotations

from core.infrastructure import developer_sandbox
from core.gym import episodes as gym_episodes
from core.prompt_manager import prompt_manager
from core.web.services import memory_service, project_agent_bus_service, rag_vector_index_service


def _enable_sandbox(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    status = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    enabled = developer_sandbox.update_developer_mode_status(
        True,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=project_root,
    )
    return project_root, enabled["sandbox"]["sandboxId"]


def test_high_roi_state_paths_route_to_developer_sandbox(tmp_path, monkeypatch):
    project_root, sandbox_id = _enable_sandbox(tmp_path, monkeypatch)
    sandbox_workspace = project_root / ".runtime" / "developer-mode" / "sandboxes" / sandbox_id / "workspace"

    monkeypatch.setattr(prompt_manager, "_resolve_project_root", lambda: project_root)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(rag_vector_index_service.team_knowledge_service, "PROJECT_ROOT", project_root)

    assert prompt_manager._get_dynamic_root() == sandbox_workspace / "prompts"
    assert memory_service._managed_memory_path(project_root) == sandbox_workspace / "memory" / "user_memory_overrides.json"
    assert rag_vector_index_service._index_root() == sandbox_workspace / "knowledge" / "rag"
    assert project_agent_bus_service._bus_events_path() == sandbox_workspace / "project_agent_bus" / "events.jsonl"
    assert gym_episodes._gym_workspace(project_root) == sandbox_workspace / "gym"


def test_high_roi_state_paths_stay_formal_when_developer_mode_is_off(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(prompt_manager, "_resolve_project_root", lambda: project_root)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(rag_vector_index_service.team_knowledge_service, "PROJECT_ROOT", project_root)

    assert prompt_manager._get_dynamic_root() == project_root / "workspace" / "prompts"
    assert memory_service._managed_memory_path(project_root) == project_root / "workspace" / "memory" / "user_memory_overrides.json"
    assert rag_vector_index_service._index_root() == project_root / "workspace" / "knowledge" / "rag"
    assert project_agent_bus_service._bus_events_path() == project_root / "workspace" / "project_agent_bus" / "events.jsonl"
    assert gym_episodes._gym_workspace(project_root) == project_root / "workspace" / "gym"
