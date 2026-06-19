from __future__ import annotations

from pathlib import Path

import pytest

from core.infrastructure import developer_sandbox


def _enable_sandbox(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: project_root / "workspace")
    status = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    enabled = developer_sandbox.update_developer_mode_status(
        True,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=project_root,
    )
    return config_path, project_root, enabled


def test_developer_write_policy_classifies_high_risk_surfaces():
    assert developer_sandbox.developer_write_policy("launcher", "state") == "formal_only"
    assert developer_sandbox.developer_write_policy("runtime_manager", "control_state") == "formal_only"
    assert developer_sandbox.developer_write_policy("computer_use", "state") == "sandboxed"
    assert developer_sandbox.developer_write_policy("memory", "state") == "sandboxed"
    assert developer_sandbox.developer_write_policy("team_knowledge", "central_promotion") == "blocked_in_dev"
    assert developer_sandbox.developer_write_policy("config", "experiment") == "overlay"
    assert developer_sandbox.developer_write_policy("unknown_surface", "state") == "sandboxed"


def test_route_workspace_path_sends_sandboxed_state_to_active_sandbox(tmp_path, monkeypatch):
    _config_path, project_root, enabled = _enable_sandbox(tmp_path, monkeypatch)
    formal_path = project_root / "workspace" / "memory" / "tasks.json"
    formal_path.parent.mkdir(parents=True)
    formal_path.write_text('{"formal": true}', encoding="utf-8")

    routed = developer_sandbox.route_workspace_path(
        project_root,
        "memory",
        "memory",
        "tasks.json",
        intent="state",
        seed=True,
    )

    assert routed == (
        project_root
        / ".runtime"
        / "developer-mode"
        / "sandboxes"
        / enabled["sandbox"]["sandboxId"]
        / "workspace"
        / "memory"
        / "tasks.json"
    )
    assert routed.read_text(encoding="utf-8") == '{"formal": true}'
    assert formal_path.read_text(encoding="utf-8") == '{"formal": true}'


def test_blocked_policy_rejects_formal_promotion_only_in_developer_mode(tmp_path, monkeypatch):
    config_path, project_root, _enabled = _enable_sandbox(tmp_path, monkeypatch)

    with pytest.raises(developer_sandbox.DeveloperSandboxWriteBlocked) as exc_info:
        developer_sandbox.route_workspace_path(
            project_root,
            "team_knowledge",
            "teams",
            "alpha",
            "knowledge",
            intent="central_promotion",
        )

    assert exc_info.value.surface == "team_knowledge"
    assert exc_info.value.intent == "central_promotion"

    developer_sandbox.update_developer_mode_status(
        False,
        base_hash=developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)["configHash"],
        config_path=config_path,
        project_root=project_root,
    )

    assert developer_sandbox.route_workspace_path(
        project_root,
        "team_knowledge",
        "teams",
        "alpha",
        "knowledge",
        intent="central_promotion",
    ) == project_root / "workspace" / "teams" / "alpha" / "knowledge"


def test_legacy_direct_workspace_write_modules_are_explicitly_classified():
    project_root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for relative_path, surface in developer_sandbox.LEGACY_DIRECT_WORKSPACE_WRITE_SURFACES.items():
        path = project_root / relative_path
        if not path.exists():
            offenders.append(f"{relative_path}: missing")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if '"workspace"' not in text and "'workspace'" not in text:
            continue
        policy = developer_sandbox.developer_write_policy(surface, "state")
        if policy not in {"sandboxed", "overlay", "blocked_in_dev"}:
            offenders.append(f"{relative_path}: unsafe policy {policy!r} for {surface!r}")

    assert offenders == []
