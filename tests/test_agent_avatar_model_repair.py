import json
from types import SimpleNamespace

from core.infrastructure import developer_sandbox
from core.web.services import agent_directory_service


def _use_isolated_agent_directory(tmp_path, monkeypatch):
    project_root = tmp_path / "repo"
    data_home = tmp_path / "data"
    project_root.mkdir()
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(
        developer_sandbox,
        "resolve_workspace_home",
        lambda *args, **kwargs: data_home / "workspace",
    )
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda **kwargs: False)
    agent_directory_service._invalidate_repaired_state_cache()
    return project_root, data_home


def _patch_primary_model(monkeypatch, model_id="relay_openai_gpt_5_5"):
    fake_llm = SimpleNamespace(
        model_library={model_id: {"model": "gpt-test"}},
        get_profile=lambda profile_id=None, role="primary": SimpleNamespace(profile_id=profile_id or "primary"),
        get_model_library_entry_for_profile=lambda profile: (model_id, {"model": "gpt-test"}),
    )
    monkeypatch.setattr("config.settings.get_config", lambda: SimpleNamespace(llm=fake_llm))


def test_agent_avatar_options_read_external_workspace_home_when_project_root_differs(tmp_path, monkeypatch):
    project_root, data_home = _use_isolated_agent_directory(tmp_path, monkeypatch)
    _patch_primary_model(monkeypatch)
    avatar_dir = data_home / "workspace" / "avatars"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "06-deep-investigator.png").write_bytes(b"\x89PNG\r\n\x1a\navatar")

    agent = agent_directory_service.create_agent_instance(
        display_name="Deep Research",
        primary_mode="research",
        role_key="research_deep",
    )
    options = agent_directory_service.list_agent_avatar_options()
    resolved = agent_directory_service.resolve_agent_avatar_file("06-deep-investigator.png")

    assert not (project_root / "workspace" / "avatars").exists()
    assert agent["avatarImagePath"] == "workspace/avatars/06-deep-investigator.png"
    assert options["options"][0]["path"] == "workspace/avatars/06-deep-investigator.png"
    assert resolved == avatar_dir / "06-deep-investigator.png"


def test_agent_avatar_options_fall_back_to_legacy_project_avatar_dir(tmp_path, monkeypatch):
    project_root, data_home = _use_isolated_agent_directory(tmp_path, monkeypatch)
    _patch_primary_model(monkeypatch)
    legacy_avatar_dir = project_root / "workspace" / "avatars"
    legacy_avatar_dir.mkdir(parents=True)
    (legacy_avatar_dir / "06-deep-investigator.png").write_bytes(b"\x89PNG\r\n\x1a\navatar")

    options = agent_directory_service.list_agent_avatar_options()

    assert not (data_home / "workspace" / "avatars").exists()
    assert options["options"][0]["path"] == "workspace/avatars/06-deep-investigator.png"


def test_agent_directory_repairs_model_primary_to_configured_primary_profile(tmp_path, monkeypatch):
    _use_isolated_agent_directory(tmp_path, monkeypatch)
    _patch_primary_model(monkeypatch, model_id="relay_openai_gpt_5_5")
    registry_path = agent_directory_service.registry_path()
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "agents": [
                    {
                        "agentId": "agent-legacy-primary",
                        "displayName": "Legacy Primary",
                        "primaryMode": "chat",
                        "llmBindings": {"dialogue": {"modelId": "model-primary"}},
                        "workspacePath": "workspace/agents/agent-legacy-primary",
                        "toolPolicyId": "default",
                        "memoryPolicyId": "memory-agent-legacy-primary",
                        "metadata": {},
                    }
                ],
                "toolPolicies": {},
                "memoryPolicies": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    repaired = agent_directory_service.repair_agent_directory()
    repaired_agent = next(item for item in repaired["agents"] if item["agentId"] == "agent-legacy-primary")

    assert repaired_agent["llmBindings"]["dialogue"]["modelId"] == "relay_openai_gpt_5_5"
