"""G4-1: Launcher status/settings JSON routes are typed without dropping extras."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from core.launcher.api_contract import (
    LauncherAcceptedCommandResponse,
    LauncherBranchInstanceListResponse,
    LauncherCleanupPlanResponse,
    LauncherDesktopActionResponse,
    LauncherDesktopSessionResponse,
    LauncherDeveloperModeSettingResponse,
    LauncherDeveloperModeUpdateResponse,
    LauncherDeveloperNoiseOverviewResponse,
    LauncherFreshnessResponse,
    LauncherLifecycleIntentResponse,
    LauncherRuntimeSceneEventResponse,
    LauncherStartupSettingsResponse,
    LauncherStartupSettingsUpdateResponse,
    LauncherStatusResponse,
    LauncherWorkbenchCloseResponse,
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
    "launcher_branch_instances_cleanup",
    "launcher_workbench_window_setting",
    "launcher_startup_settings",
    "launcher_update_startup_settings",
    "launcher_update_workbench_window_setting",
    "launcher_developer_mode_setting",
    "launcher_update_developer_mode",
    "launcher_developer_mode_noise_overview",
    "launcher_preview_developer_cleanup",
    "launcher_apply_developer_cleanup",
    "launcher_submit_lifecycle_intent",
    "launcher_get_lifecycle_intent",
    "launcher_submit_workbench_close_transaction",
    "launcher_get_workbench_close_transaction",
    "launcher_ack_workbench_close_transaction_window_closed",
    "launcher_claim_desktop_action",
    "launcher_ack_desktop_action",
    "launcher_fail_desktop_action",
    "launcher_register_desktop_session",
    "launcher_update_desktop_session_window",
    "launcher_heartbeat_desktop_session",
    "launcher_close_desktop_session",
    "launcher_runtime_scene_event",
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


def test_launcher_response_models_publish_known_schema_fields() -> None:
    expected_properties = {
        LauncherStatusResponse: {
            "launcher",
            "projectBundle",
            "runtimeManager",
            "lifecycleProof",
            "overallState",
            "observedState",
        },
        LauncherFreshnessResponse: {
            "schemaVersion",
            "current",
            "runningCommit",
            "headCommit",
            "startedAt",
        },
        LauncherBranchInstanceListResponse: {
            "schemaVersion",
            "integrationRoot",
            "currentId",
            "items",
        },
        WorkbenchWindowModeSettingResponse: {
            "mode",
            "effectiveMode",
            "configHash",
            "options",
        },
        WorkbenchWindowModeUpdateResponse: {"ok", "mode", "setting", "message"},
        LauncherStartupSettingsResponse: {
            "launcher",
            "runtime",
            "workbench",
            "interface",
            "configHash",
        },
        LauncherStartupSettingsUpdateResponse: {"ok", "setting", "message"},
        LauncherDeveloperModeSettingResponse: {
            "schemaVersion",
            "enabled",
            "configHash",
            "sandbox",
            "policy",
        },
        LauncherDeveloperModeUpdateResponse: {"ok", "setting", "message"},
        LauncherDeveloperNoiseOverviewResponse: {
            "schemaVersion",
            "developerMode",
            "projectRoot",
            "items",
            "updatedAt",
        },
        LauncherAcceptedCommandResponse: {"accepted", "commandId", "message", "instanceId", "operation"},
        LauncherCleanupPlanResponse: {"planId", "action", "ok"},
        LauncherLifecycleIntentResponse: {"intentId", "status", "action"},
        LauncherWorkbenchCloseResponse: {"closeId", "phase", "desktopSessionId"},
        LauncherDesktopActionResponse: {"actionId", "desktopSessionId"},
        LauncherDesktopSessionResponse: {"desktopSessionId", "revision", "status"},
        LauncherRuntimeSceneEventResponse: {"accepted", "runtimeSceneId"},
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, f"{model.__name__} is missing fields: {sorted(expected - properties)}"


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

    freshness = LauncherFreshnessResponse.model_validate(
        {"current": True, "headCommit": "abc", "customFreshness": 7}
    )
    freshness_dump = freshness.model_dump(exclude_unset=True)
    assert freshness_dump["current"] is True
    assert freshness_dump["headCommit"] == "abc"
    assert freshness_dump["customFreshness"] == 7

    instances = LauncherBranchInstanceListResponse.model_validate(
        {
            "schemaVersion": 1,
            "currentId": "main",
            "items": [{"instanceId": "i1", "customInstance": True}],
            "customList": True,
        }
    )
    instances_dump = instances.model_dump(exclude_unset=True)
    assert instances_dump["currentId"] == "main"
    assert instances_dump["customList"] is True
    assert instances_dump["items"][0]["customInstance"] is True

    window = WorkbenchWindowModeSettingResponse.model_validate(
        {"mode": "windowed", "effectiveMode": "windowed", "customWindow": True}
    )
    window_dump = window.model_dump(exclude_unset=True)
    assert window_dump["effectiveMode"] == "windowed"
    assert window_dump["customWindow"] is True

    window_update = WorkbenchWindowModeUpdateResponse.model_validate(
        {
            "ok": True,
            "mode": "windowed",
            "setting": {"mode": "windowed", "customSetting": True},
            "customUpdate": True,
        }
    )
    window_update_dump = window_update.model_dump(exclude_unset=True)
    assert window_update_dump["mode"] == "windowed"
    assert window_update_dump["customUpdate"] is True
    assert window_update_dump["setting"]["customSetting"] is True

    startup = LauncherStartupSettingsResponse.model_validate(
        {"launcher": {"controlPort": 8765, "customPort": True}, "customStartup": True}
    )
    startup_dump = startup.model_dump(exclude_unset=True)
    assert startup_dump["customStartup"] is True
    assert startup_dump["launcher"]["customPort"] is True

    startup_update = LauncherStartupSettingsUpdateResponse.model_validate(
        {
            "ok": True,
            "setting": {"launcher": {"controlPort": 8765}},
            "customStartupUpdate": True,
        }
    )
    startup_update_dump = startup_update.model_dump(exclude_unset=True)
    assert startup_update_dump["setting"]["launcher"]["controlPort"] == 8765
    assert startup_update_dump["customStartupUpdate"] is True

    developer = LauncherDeveloperModeSettingResponse.model_validate({"enabled": True, "customDeveloper": True})
    developer_dump = developer.model_dump(exclude_unset=True)
    assert developer_dump["enabled"] is True
    assert developer_dump["customDeveloper"] is True

    developer_update = LauncherDeveloperModeUpdateResponse.model_validate(
        {
            "ok": True,
            "setting": {"enabled": True, "customSetting": True},
            "customDeveloperUpdate": True,
        }
    )
    developer_update_dump = developer_update.model_dump(exclude_unset=True)
    assert developer_update_dump["setting"]["customSetting"] is True
    assert developer_update_dump["customDeveloperUpdate"] is True

    noise = LauncherDeveloperNoiseOverviewResponse.model_validate(
        {
            "schemaVersion": 1,
            "developerMode": {"enabled": True},
            "projectRoot": "C:/repo",
            "items": [],
            "customNoise": True,
        }
    )
    noise_dump = noise.model_dump(exclude_unset=True)
    assert noise_dump["developerMode"]["enabled"] is True
    assert noise_dump["customNoise"] is True

    command = LauncherAcceptedCommandResponse.model_validate(
        {"accepted": True, "commandId": "cmd-1", "port": 8001, "customCommand": True}
    ).model_dump(exclude_unset=True)
    assert command == {
        "accepted": True,
        "commandId": "cmd-1",
        "port": 8001,
        "customCommand": True,
    }
    assert "message" not in command

    cleanup = LauncherCleanupPlanResponse.model_validate(
        {"ok": True, "cleaned": [{"id": "branch:task"}], "customCleanup": True}
    ).model_dump(exclude_unset=True)
    assert cleanup["cleaned"][0]["id"] == "branch:task"
    assert cleanup["customCleanup"] is True
    assert "planId" not in cleanup

    intent = LauncherLifecycleIntentResponse.model_validate(
        {"intentId": "intent-1", "status": "accepted", "customIntent": True}
    ).model_dump(exclude_unset=True)
    assert intent == {"intentId": "intent-1", "status": "accepted", "customIntent": True}
    assert "action" not in intent

    close_txn = LauncherWorkbenchCloseResponse.model_validate(
        {"closeId": "close-1", "phase": "waiting_window_closed", "customClose": True}
    ).model_dump(exclude_unset=True)
    assert close_txn["phase"] == "waiting_window_closed"
    assert close_txn["customClose"] is True
    assert "desktopSessionId" not in close_txn

    empty_claim = LauncherDesktopActionResponse.model_validate({}).model_dump(exclude_unset=True)
    assert empty_claim == {}

    claimed = LauncherDesktopActionResponse.model_validate(
        {"actionId": "action-1", "status": "claimed", "customAction": True}
    ).model_dump(exclude_unset=True)
    assert claimed == {"actionId": "action-1", "status": "claimed", "customAction": True}
    assert "desktopSessionId" not in claimed

    session = LauncherDesktopSessionResponse.model_validate(
        {"desktopSessionId": "desktop-session-1", "revision": 2, "customSession": True}
    ).model_dump(exclude_unset=True)
    assert session["revision"] == 2
    assert session["customSession"] is True
    assert "status" not in session

    scene = LauncherRuntimeSceneEventResponse.model_validate(
        {"accepted": True, "runtimeSceneId": "scene-1", "customScene": True}
    ).model_dump(exclude_unset=True)
    assert scene == {"accepted": True, "runtimeSceneId": "scene-1", "customScene": True}


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

    expected_freshness = {"current": False, "headCommit": "abc", "customFreshness": True}
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

    seen_cleanup: list[dict[str, object]] = []

    def capture_list(*args, **kwargs):
        seen_cleanup.append({"args": args, "kwargs": kwargs})
        return expected_instances

    monkeypatch.setattr(launcher_routes.launcher_service, "list_launcher_branch_instances", capture_list)
    default_list = client.get("/api/launcher/branch-instances")
    annotated_list = client.get("/api/launcher/branch-instances", params={"cleanupMetadata": True})
    assert default_list.status_code == 200
    assert annotated_list.status_code == 200
    assert seen_cleanup[0]["kwargs"] == {}
    assert seen_cleanup[1]["kwargs"] == {"include_cleanup_metadata": True}

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

    expected_noise = {
        "schemaVersion": 1,
        "developerMode": {"enabled": True},
        "projectRoot": "C:/repo",
        "items": [{"id": "logs", "customNoiseItem": True}],
        "updatedAt": "2026-08-15T00:00:00Z",
        "customNoise": True,
    }
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "get_launcher_developer_noise_overview",
        lambda: expected_noise,
    )
    noise = client.get("/api/launcher/developer-mode/noise-overview")
    assert noise.status_code == 200
    assert noise.json() == expected_noise


def test_launcher_lifecycle_json_routes_keep_unknown_fields(monkeypatch) -> None:
    expected_command = {
        "accepted": True,
        "commandId": "cmd-1",
        "instanceId": "worktree:task",
        "port": 8001,
        "customCommand": True,
    }
    del expected_command  # branch-instance lifecycle writes are Electron-owned now

    expected_cleanup = {"ok": True, "cleaned": [{"id": "branch:task", "customCleaned": True}], "customCleanup": True}
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "cleanup_launcher_branch_instances",
        lambda *_args, **_kwargs: expected_cleanup,
    )
    cleanup = client.post(
        "/api/launcher/branch-instances/cleanup",
        json={"instanceIds": ["branch:task"], "confirm": True},
    )
    assert cleanup.status_code == 200
    assert cleanup.json() == expected_cleanup

    expected_preview = {"planId": "plan-1", "action": "quick_clean", "planHash": "h1", "customPreview": True}
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "preview_launcher_developer_cleanup",
        lambda *_args, **_kwargs: expected_preview,
    )
    preview = client.post("/api/launcher/developer-mode/cleanup/preview", json={"action": "quick_clean"})
    assert preview.status_code == 200
    assert preview.json() == expected_preview

    expected_apply = {"ok": True, "planId": "plan-1", "action": "quick_clean", "customApply": True}
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "apply_launcher_developer_cleanup",
        lambda *_args, **_kwargs: expected_apply,
    )
    applied = client.post(
        "/api/launcher/developer-mode/cleanup/apply",
        json={"action": "quick_clean", "planId": "plan-1", "planHash": "h1", "confirm": True},
    )
    assert applied.status_code == 200
    assert applied.json() == expected_apply

    expected_intent = {"intentId": "intent-1", "status": "accepted", "action": "open_workbench", "customIntent": True}
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "submit_lifecycle_intent",
        lambda *_args, **_kwargs: expected_intent,
    )
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "get_lifecycle_intent",
        lambda *_args, **_kwargs: expected_intent,
    )
    intent = client.post(
        "/api/launcher/lifecycle-intents",
        json={"action": "open_workbench", "reason": "pytest", "idempotencyKey": "key-1"},
    )
    assert intent.status_code == 202
    assert intent.json() == expected_intent
    fetched_intent = client.get("/api/launcher/lifecycle-intents/intent-1")
    assert fetched_intent.status_code == 200
    assert fetched_intent.json() == expected_intent

    expected_close = {
        "closeId": "close-1",
        "phase": "waiting_window_closed",
        "desktopSessionId": "desktop-session-1",
        "customClose": True,
    }
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "submit_workbench_close_transaction",
        lambda *_args, **_kwargs: expected_close,
    )
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "get_workbench_close_transaction",
        lambda *_args, **_kwargs: expected_close,
    )
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "ack_workbench_close_transaction_window_closed",
        lambda *_args, **_kwargs: expected_close,
    )
    close_submit = client.post(
        "/api/launcher/workbench-close-transactions",
        json={"desktopSessionId": "desktop-session-1", "idempotencyKey": "close-key-1"},
    )
    assert close_submit.status_code == 202
    assert close_submit.json() == expected_close
    close_get = client.get("/api/launcher/workbench-close-transactions/close-1")
    assert close_get.status_code == 200
    assert close_get.json() == expected_close
    close_ack = client.post(
        "/api/launcher/workbench-close-transactions/close-1/window-closed",
        json={"desktopSessionId": "desktop-session-1", "desktopSessionRevision": 2},
    )
    assert close_ack.status_code == 202
    assert close_ack.json() == expected_close

    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "claim_desktop_action",
        lambda *_args, **_kwargs: {},
    )
    empty_claim = client.post(
        "/api/launcher/desktop-actions/claim",
        json={"desktopSessionId": "desktop-session-1", "leaseSeconds": 30, "waitMs": 0},
    )
    assert empty_claim.status_code == 200
    assert empty_claim.json() == {}

    expected_action = {"actionId": "action-1", "status": "claimed", "customAction": True}
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "claim_desktop_action",
        lambda *_args, **_kwargs: expected_action,
    )
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "ack_desktop_action",
        lambda *_args, **_kwargs: expected_action,
    )
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "fail_desktop_action",
        lambda *_args, **_kwargs: expected_action,
    )
    claim = client.post(
        "/api/launcher/desktop-actions/claim",
        json={"desktopSessionId": "desktop-session-1", "leaseSeconds": 30, "waitMs": 0},
    )
    assert claim.status_code == 200
    assert claim.json() == expected_action
    ack = client.post(
        "/api/launcher/desktop-actions/action-1/ack",
        json={"desktopSessionId": "desktop-session-1", "result": {"ok": True}},
    )
    assert ack.status_code == 202
    assert ack.json() == expected_action
    fail = client.post(
        "/api/launcher/desktop-actions/action-1/fail",
        json={"desktopSessionId": "desktop-session-1", "result": {"ok": False}},
    )
    assert fail.status_code == 202
    assert fail.json() == expected_action

    expected_session = {
        "desktopSessionId": "desktop-session-1",
        "revision": 2,
        "status": "active",
        "customSession": True,
    }
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "register_desktop_session",
        lambda *_args, **_kwargs: expected_session,
    )
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "update_desktop_session_window",
        lambda *_args, **_kwargs: expected_session,
    )
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "heartbeat_desktop_session",
        lambda *_args, **_kwargs: expected_session,
    )
    monkeypatch.setattr(
        launcher_routes.launcher_service,
        "close_desktop_session",
        lambda *_args, **_kwargs: expected_session,
    )
    registered = client.post(
        "/api/launcher/desktop-sessions",
        json={"desktopSessionId": "desktop-session-1", "provider": "electron"},
    )
    assert registered.status_code == 201
    assert registered.json() == expected_session
    window = client.put(
        "/api/launcher/desktop-sessions/desktop-session-1/windows/workbench",
        json={"revision": 1, "provider": "electron", "open": True},
    )
    assert window.status_code == 200
    assert window.json() == expected_session
    heartbeat = client.post(
        "/api/launcher/desktop-sessions/desktop-session-1/heartbeat",
        json={"revision": 2},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json() == expected_session
    closed = client.request(
        "DELETE",
        "/api/launcher/desktop-sessions/desktop-session-1",
        json={"revision": 3},
    )
    assert closed.status_code == 200
    assert closed.json() == expected_session

    expected_scene = {"accepted": True, "runtimeSceneId": "scene-1", "customScene": True}
    monkeypatch.setattr(
        launcher_routes.runtime_scene_service,
        "record_electron_supervisor_event",
        lambda *_args, **_kwargs: expected_scene,
    )
    scene = client.post(
        "/api/launcher/runtime-scene/events",
        json={"eventCode": "electron.desktop_action.claimed", "message": "claimed"},
    )
    assert scene.status_code == 202
    assert scene.json() == expected_scene
