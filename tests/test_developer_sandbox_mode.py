import json

from core.chat.conversation_ledger import (
    EVENT_USER_MESSAGE,
    append_conversation_event,
    conversation_visible_messages_from_events,
    load_conversation_events,
)
from core.infrastructure import developer_sandbox
from core.ui.chat_state import formal_chat_state_path, load_chat_state, save_chat_state
from core.web.services import team_service


def _prepare_project(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: project_root / "workspace")
    return config_path, project_root


def _enable_sandbox(tmp_path, monkeypatch):
    config_path, project_root = _prepare_project(tmp_path, monkeypatch)
    status = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    enabled = developer_sandbox.update_developer_mode_status(
        True,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=project_root,
    )
    return config_path, project_root, enabled


def _append_user_message(project_root, content: str, *, turn_id: str) -> None:
    append_conversation_event(
        project_root,
        "default",
        turn_id,
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": content},
    )


def _visible_message_content(project_root) -> str:
    messages = conversation_visible_messages_from_events(load_conversation_events(project_root, "default"))
    return messages[-1]["content"]


def test_chat_state_writes_to_sandbox_without_mutating_formal_state(tmp_path, monkeypatch):
    config_path, project_root = _prepare_project(tmp_path, monkeypatch)
    formal_path = formal_chat_state_path(project_root)
    formal_path.parent.mkdir(parents=True)
    formal_payload = {"version": 1, "conversations": [{"conversation_id": "default"}]}
    formal_path.write_text(json.dumps(formal_payload, ensure_ascii=False), encoding="utf-8")
    _append_user_message(project_root, "formal", turn_id="formal-001")

    assert _visible_message_content(project_root) == "formal"

    status = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    enabled = developer_sandbox.update_developer_mode_status(
        True,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=project_root,
    )

    debug_payload = {"version": 1, "conversations": [{"conversation_id": "default", "messages": [{"role": "user", "content": "debug"}]}]}
    save_chat_state(project_root, debug_payload)
    _append_user_message(project_root, "debug", turn_id="debug-001")

    sandbox_path = project_root / ".runtime" / "developer-mode" / "sandboxes" / enabled["sandbox"]["sandboxId"] / "workspace" / "chat" / "chat_state.json"
    assert sandbox_path.exists()
    assert json.loads(formal_path.read_text(encoding="utf-8")) == formal_payload
    assert _visible_message_content(project_root) == "debug"

    developer_sandbox.update_developer_mode_status(
        False,
        base_hash=developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)["configHash"],
        config_path=config_path,
        project_root=project_root,
    )

    assert not sandbox_path.exists()
    assert _visible_message_content(project_root) == "formal"


def test_team_root_is_seeded_into_sandbox_before_writes(tmp_path, monkeypatch):
    _config_path, project_root, enabled = _enable_sandbox(tmp_path, monkeypatch)
    formal_teams = project_root / "workspace" / "teams"
    formal_teams.mkdir(parents=True)
    (formal_teams / "teams.json").write_text(
        json.dumps({"schemaVersion": 1, "teams": [{"teamId": "alpha", "name": "Alpha"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(team_service, "PROJECT_ROOT", project_root)

    sandbox_root = team_service._teams_root()

    assert str(sandbox_root).startswith(str(project_root / ".runtime" / "developer-mode" / "sandboxes" / enabled["sandbox"]["sandboxId"]))
    assert (sandbox_root / "teams.json").exists()
    assert (formal_teams / "teams.json").exists()


def test_debug_log_fields_are_added_only_when_sandbox_enabled(tmp_path, monkeypatch):
    _config_path, project_root, enabled = _enable_sandbox(tmp_path, monkeypatch)

    fields = developer_sandbox.enrich_debug_fields({"event": "sample"}, project_root=project_root)

    assert fields["event"] == "sample"
    assert fields["developerMode"] is True
    assert fields["developerSandboxId"] == enabled["sandbox"]["sandboxId"]
    assert fields["recordKind"] == "debug"
    assert fields["retention"] == "diagnostic_only"


def test_developer_mode_status_reuses_config_parse_until_file_changes(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    project_root = tmp_path / "project"
    project_root.mkdir()
    calls = 0
    original_load_public_config = developer_sandbox.load_public_config

    def counted_load_public_config(path=None):
        nonlocal calls
        calls += 1
        return original_load_public_config(path)

    monkeypatch.setattr(developer_sandbox, "load_public_config", counted_load_public_config)
    developer_sandbox._clear_developer_mode_config_cache()

    first = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    second = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)

    assert first["configHash"] == second["configHash"]
    assert calls == 1

    config_path.write_text(
        "[launcher]\ncontrol_port = 8765\n[launcher.developer_mode]\nenabled = true\n",
        encoding="utf-8",
    )
    refreshed = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)

    assert refreshed["enabled"] is True
    assert calls == 2
