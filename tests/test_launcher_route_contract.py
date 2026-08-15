"""G4-1: Launcher status/settings JSON routes are typed without dropping extras."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from core.launcher.api_contract import (
    LauncherBranchInstanceListResponse,
    LauncherDeveloperModeSettingResponse,
    LauncherDeveloperModeUpdateResponse,
    LauncherDeveloperNoiseOverviewResponse,
    LauncherFreshnessResponse,
    LauncherStartupSettingsResponse,
    LauncherStartupSettingsUpdateResponse,
    LauncherStatusResponse,
    WorkbenchWindowModeSettingResponse,
    WorkbenchWindowModeUpdateResponse,
)
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import launcher as launcher_routes

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_ROUTE = REPO_ROOT / "core" / "web" / "routes" / "launcher.py"

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

JSON_ROUTE_FUNCTIONS = {
    "launcher_status",
    "launcher_freshness",
    "launcher_branch_instances",
    "launcher_workbench_window_setting",
    "launcher_startup_settings",
    "launcher_update_startup_settings",
    "launcher_update_workbench_window_setting",
    "launcher_developer_mode_setting",
    "launcher_update_developer_mode",
    "launcher_developer_mode_noise_overview",
}


def _is_router_decorator(decorator: ast.Call) -> bool:
    function = decorator.func
    return (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id.lower().endswith("router")
    )


def _route_decorators() -> dict[str, ast.Call]:
    tree = ast.parse(LAUNCHER_ROUTE.read_text(encoding="utf-8"))
    found: dict[str, ast.Call] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and _is_router_decorator(decorator):
                found[node.name] = decorator
    return found


def test_launcher_status_settings_routes_declare_response_model() -> None:
    decorators = _route_decorators()
    missing = []
    for name in sorted(JSON_ROUTE_FUNCTIONS):
        decorator = decorators.get(name)
        if decorator is None:
            missing.append(name)
            continue
        has_response_model = any(
            keyword.arg == "response_model"
            and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
            for keyword in decorator.keywords
        )
        has_exclude_unset = any(
            keyword.arg == "response_model_exclude_unset"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in decorator.keywords
        )
        if not has_response_model or not has_exclude_unset:
            missing.append(name)
    assert missing == [], f"launcher status/settings routes must declare response_model: {missing}"


def test_launcher_response_models_keep_unknown_fields() -> None:
    status = LauncherStatusResponse.model_validate(
        {
            "launcher": {"mode": "standalone_control_plane", "customLauncher": True},
            "projectBundle": {"schemaVersion": 1, "customBundle": True},
            "overallState": "open",
            "customTrayField": "keep-me",
        }
    )
    dumped = status.model_dump(exclude_unset=True)
    assert dumped["launcher"]["customLauncher"] is True
    assert dumped["projectBundle"]["customBundle"] is True
    assert dumped["overallState"] == "open"
    assert dumped["customTrayField"] == "keep-me"
    assert "phase" not in dumped

    freshness = LauncherFreshnessResponse.model_validate({"fresh": True, "customFreshness": 7})
    assert freshness.model_dump(exclude_unset=True)["customFreshness"] == 7

    instances = LauncherBranchInstanceListResponse.model_validate(
        {"items": [{"instanceId": "i1", "customInstance": True}], "customList": True}
    )
    instances_dump = instances.model_dump(exclude_unset=True)
    assert instances_dump["customList"] is True
    assert instances_dump["items"][0]["customInstance"] is True

    window = WorkbenchWindowModeSettingResponse.model_validate({"mode": "windowed", "customWindow": True})
    assert window.model_dump(exclude_unset=True)["customWindow"] is True

    window_update = WorkbenchWindowModeUpdateResponse.model_validate(
        {"ok": True, "setting": {"mode": "windowed", "customSetting": True}, "customUpdate": True}
    )
    window_update_dump = window_update.model_dump(exclude_unset=True)
    assert window_update_dump["customUpdate"] is True
    assert window_update_dump["setting"]["customSetting"] is True

    startup = LauncherStartupSettingsResponse.model_validate(
        {"launcher": {"controlPort": 8765, "customPort": True}, "customStartup": True}
    )
    startup_dump = startup.model_dump(exclude_unset=True)
    assert startup_dump["customStartup"] is True
    assert startup_dump["launcher"]["customPort"] is True

    startup_update = LauncherStartupSettingsUpdateResponse.model_validate({"ok": True, "customStartupUpdate": True})
    assert startup_update.model_dump(exclude_unset=True)["customStartupUpdate"] is True

    developer = LauncherDeveloperModeSettingResponse.model_validate({"enabled": True, "customDeveloper": True})
    assert developer.model_dump(exclude_unset=True)["customDeveloper"] is True

    developer_update = LauncherDeveloperModeUpdateResponse.model_validate({"ok": True, "customDeveloperUpdate": True})
    assert developer_update.model_dump(exclude_unset=True)["customDeveloperUpdate"] is True

    noise = LauncherDeveloperNoiseOverviewResponse.model_validate({"items": [], "customNoise": True})
    assert noise.model_dump(exclude_unset=True)["customNoise"] is True


def test_launcher_status_settings_routes_keep_unknown_fields(monkeypatch) -> None:
    expected_status = {
        "launcher": {"mode": "standalone_control_plane", "customLauncher": True},
        "projectBundle": {"schemaVersion": 1, "customBundle": True},
        "overallState": "open",
        "customTrayField": "keep-me",
    }
    monkeypatch.setattr(launcher_routes.launcher_service, "get_launcher_status", lambda: expected_status)
    status = client.get("/api/launcher/status")
    assert status.status_code == 200
    assert status.json() == expected_status

    expected_freshness = {"fresh": False, "head": "abc", "customFreshness": True}
    monkeypatch.setattr(launcher_routes.launcher_service, "get_launcher_freshness", lambda: expected_freshness)
    freshness = client.get("/api/launcher/freshness")
    assert freshness.status_code == 200
    assert freshness.json() == expected_freshness

    expected_instances = {"items": [{"instanceId": "i1", "customInstance": True}], "customList": True}
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "list_launcher_branch_instances",
        lambda: expected_instances,
    )
    instances = client.get("/api/launcher/branch-instances")
    assert instances.status_code == 200
    assert instances.json() == expected_instances

    expected_window = {"mode": "windowed", "effectiveMode": "windowed", "customWindow": True}
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "get_workbench_window_mode_setting",
        lambda: expected_window,
    )
    window = client.get("/api/launcher/settings/workbench-window")
    assert window.status_code == 200
    assert window.json() == expected_window

    expected_startup = {"launcher": {"controlPort": 8765, "customPort": True}, "customStartup": True}
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "get_launcher_startup_settings",
        lambda: expected_startup,
    )
    startup = client.get("/api/launcher/settings/startup")
    assert startup.status_code == 200
    assert startup.json() == expected_startup

    expected_startup_update = {"ok": True, "setting": expected_startup, "customStartupUpdate": True}
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "update_launcher_startup_settings",
        lambda *_args, **_kwargs: expected_startup_update,
    )
    startup_update = client.put(
        "/api/launcher/settings/startup",
        json={"launcher": {}, "runtime": {}, "workbench": {}, "interface": {}, "baseHash": "h1"},
    )
    assert startup_update.status_code == 200
    assert startup_update.json() == expected_startup_update

    expected_window_update = {"ok": True, "mode": "windowed", "setting": expected_window, "customUpdate": True}
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "update_workbench_window_mode",
        lambda *_args, **_kwargs: expected_window_update,
    )
    window_update = client.put(
        "/api/launcher/settings/workbench-window",
        json={"mode": "windowed", "baseHash": "h1"},
    )
    assert window_update.status_code == 200
    assert window_update.json() == expected_window_update

    expected_developer = {"enabled": True, "configHash": "h1", "customDeveloper": True}
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "get_launcher_developer_mode_setting",
        lambda: expected_developer,
    )
    developer = client.get("/api/launcher/developer-mode")
    assert developer.status_code == 200
    assert developer.json() == expected_developer

    expected_developer_update = {"ok": True, "setting": expected_developer, "customDeveloperUpdate": True}
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "update_launcher_developer_mode",
        lambda *_args, **_kwargs: expected_developer_update,
    )
    developer_update = client.put("/api/launcher/developer-mode", json={"enabled": True, "baseHash": "h1"})
    assert developer_update.status_code == 200
    assert developer_update.json() == expected_developer_update

    expected_noise = {"categories": [{"id": "logs", "customNoiseItem": True}], "customNoise": True}
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "get_launcher_developer_noise_overview",
        lambda: expected_noise,
    )
    noise = client.get("/api/launcher/developer-mode/noise-overview")
    assert noise.status_code == 200
    assert noise.json() == expected_noise
