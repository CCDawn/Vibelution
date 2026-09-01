import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.launcher import app as launcher_app
from core.launcher import service as launcher_service
from core.web.routes import launcher as web_launcher_routes
from core.runtime_manager import work_run_store
from core.runtime_manager.work_run_store import WorkRunStore

_REAL_RESIDUAL_PROCESSES_PAYLOAD = launcher_service._residual_processes_payload

pytestmark = pytest.mark.serial


@pytest.fixture(autouse=True)
def isolate_residual_process_scan(monkeypatch):
    monkeypatch.setattr(
        launcher_service,
        "_residual_processes_payload",
        lambda **_kwargs: {"count": 0, "items": []},
    )


@pytest.fixture(autouse=True)
def isolate_desktop_session_store(tmp_path, monkeypatch):
    """Keep launcher status tests independent from a developer's live desktop session."""
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "DESKTOP_SESSION_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "desktop_sessions.sqlite3",
    )
    from core.launcher import lifecycle_intent_store

    monkeypatch.setattr(
        lifecycle_intent_store,
        "LIFECYCLE_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "lifecycle.sqlite3",
    )


def test_launcher_payload_contract_is_shared_between_standalone_and_web_routes():
    from core.launcher import api_contract

    assert launcher_app.LauncherStartupSettingsPayload is api_contract.LauncherStartupSettingsPayload
    assert web_launcher_routes.LauncherStartupSettingsPayload is api_contract.LauncherStartupSettingsPayload
    assert launcher_app.DesktopSessionWindowPayload is api_contract.DesktopSessionWindowPayload
    assert web_launcher_routes.DesktopSessionWindowPayload is api_contract.DesktopSessionWindowPayload
    assert launcher_app.WorkbenchCloseTransactionPayload is api_contract.WorkbenchCloseTransactionPayload
    assert web_launcher_routes.WorkbenchCloseTransactionPayload is api_contract.WorkbenchCloseTransactionPayload
    assert api_contract.launcher_error_detail("invalid_mode", ValueError("bad")) == {
        "code": "invalid_mode",
        "message": "bad",
    }


@pytest.mark.parametrize("action", ["request_app_exit", "restart_after_apply"])
def test_runtime_effect_lifecycle_intent_replay_dispatches_once(action, monkeypatch):
    """The same durable intent must not enqueue a second close or hot restart."""
    from core.launcher import lifecycle_action_dispatcher

    dispatched: list[dict[str, object]] = []
    monkeypatch.setattr(launcher_service, "launcher_active_work_runs", lambda: [])
    monkeypatch.setattr(
        lifecycle_action_dispatcher,
        "dispatch_runtime_effect_intent",
        lambda intent: dispatched.append(intent)
        or {"dispatched": True, "accepted": True, "commandId": f"cmd-{intent['action']}"},
    )
    payload = {
        "action": action,
        "reason": "pytest replay protection",
        "idempotencyKey": f"pytest:{action}:one",
    }

    first = launcher_service.submit_lifecycle_intent(payload)
    replay = launcher_service.submit_lifecycle_intent(payload)

    assert first["status"] == "executing"
    assert replay["intentId"] == first["intentId"]
    assert replay["commandId"] == first["commandId"]
    assert [item["action"] for item in dispatched] == [action]


def test_launcher_settings_cas_holds_config_lock_through_save(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[workbench]\nwindow_mode = "fullscreen"\n', encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    base_hash = launcher_service.get_workbench_window_mode_setting()["configHash"]
    lock_events: list[str] = []
    original_save = launcher_service._save_public_config_under_edit_lock

    from contextlib import contextmanager

    @contextmanager
    def tracking_lock(_path):
        lock_events.append("enter")
        try:
            yield
        finally:
            lock_events.append("exit")

    def save_under_lock(public_config, path):
        assert lock_events[-1] == "enter"
        return original_save(public_config, path)

    monkeypatch.setattr(launcher_service, "_config_edit_lock", tracking_lock)
    monkeypatch.setattr(launcher_service, "_save_public_config_under_edit_lock", save_under_lock)

    response = launcher_service.update_workbench_window_mode("windowed", base_hash=base_hash)

    assert response["ok"] is True
    assert lock_events == ["enter", "exit"]


def test_launcher_startup_settings_cas_holds_config_lock_through_save(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[workbench]\nwindow_size = "auto"\n', encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    base_hash = launcher_service.get_launcher_startup_settings()["configHash"]
    lock_events: list[str] = []
    original_save = launcher_service._save_public_config_under_edit_lock

    from contextlib import contextmanager

    @contextmanager
    def tracking_lock(_path):
        lock_events.append("enter")
        try:
            yield
        finally:
            lock_events.append("exit")

    def save_under_lock(public_config, path):
        assert lock_events[-1] == "enter"
        return original_save(public_config, path)

    monkeypatch.setattr(launcher_service, "_config_edit_lock", tracking_lock)
    monkeypatch.setattr(launcher_service, "_save_public_config_under_edit_lock", save_under_lock)

    response = launcher_service.update_launcher_startup_settings(
        {"baseHash": base_hash, "workbench": {"windowSize": "1600x900"}}
    )

    assert response["ok"] is True
    assert lock_events == ["enter", "exit"]


def test_workbench_close_transaction_is_durable_idempotent_and_requires_confirmed_force(tmp_path, monkeypatch):
    """A close command is never a substitute for a durable Electron-close transaction."""
    from core.launcher import lifecycle_action_dispatcher, lifecycle_intent_store

    monkeypatch.setattr(
        lifecycle_intent_store,
        "LIFECYCLE_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "lifecycle.sqlite3",
    )
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "DESKTOP_SESSION_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "desktop_sessions.sqlite3",
    )
    session = launcher_service.register_desktop_session(
        {
            "desktopSessionId": "desktop-close-1",
            "provider": "electron",
            "capabilities": ["workbench_close.transaction.v1"],
        }
    )
    opened = launcher_service.update_desktop_session_window(
        "desktop-close-1",
        "workbench",
        {"revision": session["revision"], "open": True, "windowId": 7},
    )
    dispatched: list[dict[str, object]] = []
    monkeypatch.setattr(launcher_service, "launcher_active_work_runs", lambda: [])
    monkeypatch.setattr(
        lifecycle_action_dispatcher,
        "dispatch_workbench_close_transaction",
        lambda transaction: dispatched.append(transaction)
        or {"dispatched": True, "accepted": True, "commandId": "close-command-1"},
        raising=False,
    )

    requested = launcher_service.submit_workbench_close_transaction(
        {
            "desktopSessionId": "desktop-close-1",
            "idempotencyKey": "desktop-close-1:normal:1",
            "mode": "normal",
            "reason": "user_requested_close",
        }
    )
    replayed = launcher_service.submit_workbench_close_transaction(
        {
            "desktopSessionId": "desktop-close-1",
            "idempotencyKey": "desktop-close-1:normal:1",
            "mode": "normal",
            "reason": "user_requested_close",
        }
    )

    assert requested["phase"] == "backend_closing"
    assert requested["commandId"] == "close-command-1"
    assert requested["expectedDesktopSessionRevision"] == opened["revision"]
    assert replayed["closeId"] == requested["closeId"]
    assert dispatched == [
        {
            "closeId": requested["closeId"],
            "desktopSessionId": "desktop-close-1",
            "expectedDesktopSessionRevision": opened["revision"],
            "mode": "normal",
            "reason": "user_requested_close",
            "confirmationCloseId": "",
        }
    ]

    monkeypatch.setattr(launcher_service, "launcher_active_work_runs", lambda: [{"runId": "chat-run-1"}])
    confirmation = launcher_service.submit_workbench_close_transaction(
        {
            "desktopSessionId": "desktop-close-1",
            "idempotencyKey": "desktop-close-1:normal:2",
            "mode": "normal",
            "reason": "user_requested_close",
        }
    )

    assert confirmation["phase"] == "confirmation_required"
    assert confirmation["activeWorkCount"] == 1
    assert confirmation["commandId"] == ""
    with pytest.raises(ValueError, match="confirmationCloseId"):
        launcher_service.submit_workbench_close_transaction(
            {
                "desktopSessionId": "desktop-close-1",
                "idempotencyKey": "desktop-close-1:force:missing",
                "mode": "force",
            }
        )

    force_requested = launcher_service.submit_workbench_close_transaction(
        {
            "desktopSessionId": "desktop-close-1",
            "idempotencyKey": "desktop-close-1:force:2",
            "mode": "force",
            "confirmationCloseId": confirmation["closeId"],
            "reason": "user_confirmed_force_close",
        }
    )

    assert force_requested["phase"] == "backend_closing"
    assert force_requested["confirmationCloseId"] == confirmation["closeId"]
    assert force_requested["commandId"] == "close-command-1"
    assert len(dispatched) == 2
    assert dispatched[-1]["mode"] == "force"
    with pytest.raises(ValueError, match="already been consumed"):
        launcher_service.submit_workbench_close_transaction(
            {
                "desktopSessionId": "desktop-close-1",
                "idempotencyKey": "desktop-close-1:force:duplicate",
                "mode": "force",
                "confirmationCloseId": confirmation["closeId"],
            }
        )


def test_workbench_close_transaction_requires_matching_closed_window_ack(tmp_path, monkeypatch):
    from core.launcher import lifecycle_action_dispatcher, lifecycle_intent_store

    monkeypatch.setattr(
        lifecycle_intent_store,
        "LIFECYCLE_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "lifecycle.sqlite3",
    )
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "DESKTOP_SESSION_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "desktop_sessions.sqlite3",
    )
    session = launcher_service.register_desktop_session(
        {
            "desktopSessionId": "desktop-close-ack-1",
            "provider": "electron",
            "capabilities": ["workbench_close.transaction.v1"],
        }
    )
    opened = launcher_service.update_desktop_session_window(
        "desktop-close-ack-1",
        "workbench",
        {"revision": session["revision"], "open": True, "windowId": 8},
    )
    monkeypatch.setattr(launcher_service, "launcher_active_work_runs", lambda: [])
    monkeypatch.setattr(
        lifecycle_action_dispatcher,
        "dispatch_workbench_close_transaction",
        lambda _transaction: {"dispatched": True, "accepted": True, "commandId": "close-command-ack-1"},
        raising=False,
    )
    requested = launcher_service.submit_workbench_close_transaction(
        {
            "desktopSessionId": "desktop-close-ack-1",
            "idempotencyKey": "desktop-close-ack-1:normal:1",
            "mode": "normal",
        }
    )
    monkeypatch.setattr(
        launcher_service,
        "_load_runtime_manager_command_result",
        lambda command_id: {"commandId": command_id, "completed": True, "ok": True},
    )

    authorized = launcher_service.get_workbench_close_transaction(requested["closeId"])

    assert authorized["phase"] == "window_close_authorized"
    with pytest.raises(ValueError, match="another desktop session"):
        launcher_service.ack_workbench_close_transaction_window_closed(
            requested["closeId"],
            {"desktopSessionId": "desktop-close-ack-other", "desktopSessionRevision": opened["revision"]},
        )
    with pytest.raises(ValueError, match="workbench window is still open"):
        launcher_service.ack_workbench_close_transaction_window_closed(
            requested["closeId"],
            {"desktopSessionId": "desktop-close-ack-1", "desktopSessionRevision": opened["revision"]},
        )

    closed_window = launcher_service.update_desktop_session_window(
        "desktop-close-ack-1",
        "workbench",
        {"revision": opened["revision"], "open": False, "windowId": 8},
    )
    completed = launcher_service.ack_workbench_close_transaction_window_closed(
        requested["closeId"],
        {
            "desktopSessionId": "desktop-close-ack-1",
            "desktopSessionRevision": closed_window["revision"],
        },
    )
    replayed = launcher_service.ack_workbench_close_transaction_window_closed(
        requested["closeId"],
        {
            "desktopSessionId": "desktop-close-ack-1",
            "desktopSessionRevision": closed_window["revision"],
        },
    )

    assert completed["phase"] == "succeeded"
    assert completed["completionSource"] == "electron_window_closed_ack"
    assert replayed["closeId"] == completed["closeId"]


def test_workbench_close_transaction_reconciles_backend_failure_without_authorizing_window_close(tmp_path, monkeypatch):
    from core.launcher import lifecycle_action_dispatcher, lifecycle_intent_store

    monkeypatch.setattr(
        lifecycle_intent_store,
        "LIFECYCLE_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "lifecycle.sqlite3",
    )
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "DESKTOP_SESSION_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "desktop_sessions.sqlite3",
    )
    session = launcher_service.register_desktop_session(
        {
            "desktopSessionId": "desktop-close-failure-1",
            "provider": "electron",
            "capabilities": ["workbench_close.transaction.v1"],
        }
    )
    launcher_service.update_desktop_session_window(
        "desktop-close-failure-1",
        "workbench",
        {"revision": session["revision"], "open": True, "windowId": 9},
    )
    monkeypatch.setattr(launcher_service, "launcher_active_work_runs", lambda: [])
    monkeypatch.setattr(
        lifecycle_action_dispatcher,
        "dispatch_workbench_close_transaction",
        lambda _transaction: {"dispatched": True, "accepted": True, "commandId": "close-command-failure-1"},
        raising=False,
    )
    requested = launcher_service.submit_workbench_close_transaction(
        {
            "desktopSessionId": "desktop-close-failure-1",
            "idempotencyKey": "desktop-close-failure-1:normal:1",
            "mode": "normal",
        }
    )
    monkeypatch.setattr(
        launcher_service,
        "_load_runtime_manager_command_result",
        lambda command_id: {
            "commandId": command_id,
            "completed": True,
            "ok": False,
            "status": "failed",
            "message": "backend close rejected",
        },
    )

    reconciled = launcher_service.get_workbench_close_transaction(requested["closeId"])

    assert reconciled["phase"] == "failed"
    assert reconciled["failureCode"] == "backend_close_failed"
    assert reconciled["result"]["commandId"] == "close-command-failure-1"


def test_window_provider_dispatcher_routes_electron_to_desktop_action_without_edge_call():
    from core.launcher.window_provider_dispatcher import WindowProviderDispatcher

    actions = []

    class EdgeProvider:
        def __init__(self):
            self.calls = []

        def open_workbench(self, *, reason: str):
            self.calls.append(("open_workbench", reason))
            return {"ok": True, "provider": "edge_app"}

        def focus_workbench(self, *, reason: str):
            self.calls.append(("focus_workbench", reason))
            return {"ok": True, "provider": "edge_app"}

    edge_provider = EdgeProvider()
    dispatcher = WindowProviderDispatcher(
        provider="electron",
        desktop_action_writer=lambda action, payload: actions.append((action, payload)) or {"ok": True, "provider": "electron"},
        edge_provider=edge_provider,
    )

    result = dispatcher.open_workbench(reason="launcher_start")

    assert result == {"ok": True, "provider": "electron"}
    assert actions == [("open_workbench", {"reason": "launcher_start"})]
    assert edge_provider.calls == []


def test_workbench_close_dispatch_declares_electron_as_external_window_owner(monkeypatch):
    from core.launcher import lifecycle_action_dispatcher

    calls = []
    monkeypatch.setattr(
        lifecycle_action_dispatcher.command_queue,
        "submit_command",
        lambda command_type, *, requested_by, args: calls.append((command_type, requested_by, args))
        or {"accepted": True, "commandId": "command-close-1"},
    )

    dispatched = lifecycle_action_dispatcher.dispatch_workbench_close_transaction(
        {
            "closeId": "workbench-close-1",
            "desktopSessionId": "desktop-session-1",
            "expectedDesktopSessionRevision": 4,
            "mode": "normal",
            "reason": "user_requested_close",
        }
    )

    assert dispatched == {"dispatched": True, "accepted": True, "commandId": "command-close-1"}
    assert calls == [
        (
            "close_workbench",
            "electron_workbench_close",
            {
                "reason": "user_requested_close",
                "source": "electron_workbench_close",
                "desktopSessionId": "desktop-session-1",
                "expectedDesktopSessionRevision": 4,
                "workbenchCloseId": "workbench-close-1",
                "confirmationCloseId": "",
                "externalWindowOwner": "electron",
            },
        )
    ]


def test_standalone_launcher_app_exposes_project_status_route(monkeypatch):
    monkeypatch.setattr(
        launcher_service,
        "get_launcher_status",
        lambda: {"launcher": {"mode": "standalone_control_plane"}, "projectBundle": {"observedState": "closed"}},
    )
    client = TestClient(launcher_app.create_launcher_app())

    response = client.get("/api/project/status")

    assert response.status_code == 200
    assert response.json()["launcher"]["mode"] == "standalone_control_plane"


def test_standalone_launcher_app_exposes_lifecycle_intent_and_desktop_action_routes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        launcher_service,
        "submit_lifecycle_intent",
        lambda payload: calls.append(("intent", payload))
        or {"intentId": "intent-1", "status": "accepted", "action": payload["action"]},
    )
    monkeypatch.setattr(
        launcher_service,
        "claim_desktop_action",
        lambda desktop_session_id, *, lease_seconds=30, wait_ms=0: calls.append(
            ("claim", desktop_session_id, lease_seconds, wait_ms)
        )
        or {"actionId": "action-1", "status": "claimed"},
    )
    monkeypatch.setattr(
        launcher_service,
        "ack_desktop_action",
        lambda action_id, desktop_session_id, result: calls.append(("ack", action_id, desktop_session_id, result))
        or {"actionId": action_id, "status": "succeeded"},
    )
    monkeypatch.setattr(
        launcher_service,
        "fail_desktop_action",
        lambda action_id, desktop_session_id, result: calls.append(("fail", action_id, desktop_session_id, result))
        or {"actionId": action_id, "status": "failed"},
    )
    client = TestClient(launcher_app.create_launcher_app())
    token_headers = {"X-Vibelution-Control-Token": client.get("/api/control-token").json()["controlToken"]}

    intent = client.post(
        "/api/launcher/lifecycle-intents",
        headers=token_headers,
        json={"action": "open_workbench", "reason": "pytest", "idempotencyKey": "intent-key-1"},
    )
    claim = client.post(
        "/api/launcher/desktop-actions/claim",
        headers=token_headers,
        json={"desktopSessionId": "desktop-session-1", "leaseSeconds": 12, "waitMs": 1750},
    )
    ack = client.post(
        "/api/launcher/desktop-actions/action-1/ack",
        headers=token_headers,
        json={"desktopSessionId": "desktop-session-1", "result": {"ok": True}},
    )
    fail = client.post(
        "/api/launcher/desktop-actions/action-2/fail",
        headers=token_headers,
        json={"desktopSessionId": "desktop-session-1", "result": {"ok": False}},
    )

    assert intent.status_code == 202
    assert claim.status_code == 200
    assert ack.status_code == 202
    assert fail.status_code == 202
    assert calls == [
        ("intent", {"action": "open_workbench", "reason": "pytest", "idempotencyKey": "intent-key-1"}),
        ("claim", "desktop-session-1", 12, 1750),
        ("ack", "action-1", "desktop-session-1", {"ok": True}),
        ("fail", "action-2", "desktop-session-1", {"ok": False}),
    ]


def test_standalone_launcher_app_exposes_controlled_workbench_close_transaction_routes(monkeypatch):
    from core.launcher.lifecycle_intent_store import WorkbenchCloseTransactionConflict

    calls = []
    transaction = {
        "closeId": "workbench-close-1",
        "phase": "backend_closing",
        "desktopSessionId": "desktop-session-1",
        "expectedDesktopSessionRevision": 4,
    }
    monkeypatch.setattr(
        launcher_service,
        "submit_workbench_close_transaction",
        lambda payload: calls.append(("submit", payload)) or transaction,
    )
    monkeypatch.setattr(
        launcher_service,
        "get_workbench_close_transaction",
        lambda close_id: calls.append(("get", close_id)) or transaction,
    )
    monkeypatch.setattr(
        launcher_service,
        "ack_workbench_close_transaction_window_closed",
        lambda close_id, payload: calls.append(("ack", close_id, payload))
        or {**transaction, "phase": "succeeded"},
    )
    client = TestClient(launcher_app.create_launcher_app())
    token_headers = {"X-Vibelution-Control-Token": client.get("/api/control-token").json()["controlToken"]}

    submitted = client.post(
        "/api/launcher/workbench-close-transactions",
        headers=token_headers,
        json={
            "desktopSessionId": "desktop-session-1",
            "idempotencyKey": "desktop-session-1:close:1",
            "mode": "normal",
            "reason": "user_requested_close",
        },
    )
    fetched = client.get(
        "/api/launcher/workbench-close-transactions/workbench-close-1",
        headers=token_headers,
    )
    acknowledged = client.post(
        "/api/launcher/workbench-close-transactions/workbench-close-1/window-closed",
        headers=token_headers,
        json={"desktopSessionId": "desktop-session-1", "desktopSessionRevision": 4},
    )

    assert submitted.status_code == 202
    assert fetched.status_code == 200
    assert acknowledged.status_code == 202
    assert calls == [
        (
            "submit",
            {
                "desktopSessionId": "desktop-session-1",
                "idempotencyKey": "desktop-session-1:close:1",
                "mode": "normal",
                "reason": "user_requested_close",
                "confirmationCloseId": "",
            },
        ),
        ("get", "workbench-close-1"),
        (
            "ack",
            "workbench-close-1",
            {"desktopSessionId": "desktop-session-1", "desktopSessionRevision": 4},
        ),
    ]

    monkeypatch.setattr(
        launcher_service,
        "ack_workbench_close_transaction_window_closed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            WorkbenchCloseTransactionConflict(
                "desktop_session_revision_conflict",
                "revision mismatch",
                expectedDesktopSessionRevision=4,
                actualDesktopSessionRevision=5,
            )
        ),
    )
    conflict = client.post(
        "/api/launcher/workbench-close-transactions/workbench-close-1/window-closed",
        headers=token_headers,
        json={"desktopSessionId": "desktop-session-1", "desktopSessionRevision": 4},
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {
        "code": "desktop_session_revision_conflict",
        "message": "revision mismatch",
        "expectedDesktopSessionRevision": 4,
        "actualDesktopSessionRevision": 5,
    }


def test_desktop_session_store_records_revisioned_window_state(tmp_path, monkeypatch):
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "DESKTOP_SESSION_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "desktop_sessions.sqlite3",
    )

    created = launcher_service.register_desktop_session(
        {
            "desktopSessionId": "desktop-session-1",
            "provider": "electron",
            "workspaceRoot": str(tmp_path),
            "capabilities": ["desktop_actions.claim"],
        }
    )
    updated = launcher_service.update_desktop_session_window(
        "desktop-session-1",
        "workbench",
        {
            "revision": created["revision"],
            "provider": "electron",
            "open": True,
            "focused": True,
            "windowId": 42,
            "rendererProcessId": 4242,
            "url": "http://127.0.0.1:8000/",
        },
    )
    heartbeat = launcher_service.heartbeat_desktop_session(
        "desktop-session-1", {"revision": updated["revision"]}
    )
    closed = launcher_service.close_desktop_session(
        "desktop-session-1", {"revision": heartbeat["revision"]}
    )

    assert created["desktopSessionId"] == "desktop-session-1"
    assert created["revision"] == 1
    assert updated["revision"] == 2
    assert updated["windows"]["workbench"]["rendererProcessId"] == 4242
    assert heartbeat["revision"] == 3
    assert closed["status"] == "closed"
    assert closed["revision"] == 4


def test_desktop_session_store_rejects_stale_revisions_and_late_heartbeats(tmp_path, monkeypatch):
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "DESKTOP_SESSION_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "desktop_sessions.sqlite3",
    )
    created = launcher_service.register_desktop_session(
        {
            "desktopSessionId": "desktop-session-1",
            "provider": "electron",
            "workspaceRoot": str(tmp_path),
            "capabilities": [],
        }
    )
    updated = launcher_service.update_desktop_session_window(
        "desktop-session-1",
        "workbench",
        {
            "revision": created["revision"],
            "provider": "electron",
            "open": True,
            "focused": True,
            "windowId": 42,
            "rendererProcessId": 4242,
            "url": "http://127.0.0.1:8000/",
        },
    )

    with pytest.raises(desktop_session_store.DesktopSessionRevisionConflict) as stale:
        launcher_service.update_desktop_session_window(
            "desktop-session-1",
            "workbench",
            {
                "revision": created["revision"],
                "provider": "electron",
                "open": True,
                "focused": True,
                "windowId": 43,
                "rendererProcessId": 4343,
                "url": "http://127.0.0.1:8000/",
            },
        )
    assert stale.value.expected_revision == created["revision"]
    assert stale.value.actual_revision == updated["revision"]

    closed = launcher_service.close_desktop_session(
        "desktop-session-1", {"revision": updated["revision"]}
    )
    with pytest.raises(desktop_session_store.DesktopSessionClosed):
        launcher_service.heartbeat_desktop_session(
            "desktop-session-1", {"revision": closed["revision"]}
        )
    with pytest.raises(desktop_session_store.DesktopSessionClosed):
        launcher_service.register_desktop_session(
            {
                "desktopSessionId": "desktop-session-1",
                "provider": "electron",
                "workspaceRoot": str(tmp_path),
                "capabilities": [],
            }
        )


def test_desktop_session_store_exposes_active_window_only_while_lease_valid(tmp_path, monkeypatch):
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "DESKTOP_SESSION_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "desktop_sessions.sqlite3",
    )
    created = launcher_service.register_desktop_session(
        {
            "desktopSessionId": "desktop-session-1",
            "provider": "electron",
            "workspaceRoot": str(tmp_path),
            "capabilities": ["desktop_actions.claim"],
        }
    )
    launcher_service.update_desktop_session_window(
        "desktop-session-1",
        "workbench",
        {
            "revision": created["revision"],
            "provider": "electron",
            "open": True,
            "focused": True,
            "windowId": 42,
            "rendererProcessId": 4242,
            "url": "http://127.0.0.1:8000/",
        },
    )

    active = desktop_session_store.latest_active_desktop_window("workbench")
    monkeypatch.setattr(desktop_session_store, "DESKTOP_SESSION_HEARTBEAT_LEASE_SECONDS", -1)
    expired = desktop_session_store.latest_active_desktop_window("workbench")

    assert active["desktopSessionId"] == "desktop-session-1"
    assert active["windowId"] == 42
    assert active["rendererProcessId"] == 4242
    assert active["desktopSessionLeaseExpiresAt"]
    assert expired == {}


def test_desktop_session_store_projects_launcher_only_electron_session(tmp_path, monkeypatch):
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "DESKTOP_SESSION_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "desktop_sessions.sqlite3",
    )
    created = launcher_service.register_desktop_session(
        {
            "desktopSessionId": "electron-launcher-only-1",
            "provider": "electron",
            "workspaceRoot": str(tmp_path),
            "capabilities": ["desktop_actions.claim"],
        }
    )

    projection = desktop_session_store.latest_active_window_provider_projection(
        workspace_root=str(tmp_path)
    )

    assert created["revision"] == 1
    assert projection["windowProvider"] == "electron"
    assert projection["windowManaged"] is False
    assert projection["browserManaged"] is False
    assert projection["browserWindowAlive"] is False
    assert projection["desktopSessionId"] == "electron-launcher-only-1"
    assert "observedState" not in projection


def test_desktop_session_store_closed_workbench_does_not_claim_observed_closed(tmp_path, monkeypatch):
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "DESKTOP_SESSION_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "desktop_sessions.sqlite3",
    )
    created = launcher_service.register_desktop_session(
        {
            "desktopSessionId": "electron-closed-window-1",
            "provider": "electron",
            "workspaceRoot": str(tmp_path),
            "capabilities": ["desktop_actions.claim"],
        }
    )
    launcher_service.update_desktop_session_window(
        "electron-closed-window-1",
        "workbench",
        {
            "revision": created["revision"],
            "provider": "electron",
            "open": False,
            "focused": False,
            "windowId": 0,
            "rendererProcessId": 0,
            "url": "",
        },
    )

    projection = desktop_session_store.latest_active_window_provider_projection(
        workspace_root=str(tmp_path)
    )
    workbench = desktop_session_store.latest_active_workbench_projection()

    assert projection["browserWindowAlive"] is False
    assert projection["windowManaged"] is False
    assert "observedState" not in projection
    assert workbench["browserWindowAlive"] is False
    assert "observedState" not in workbench


def test_launcher_payload_prefers_launcher_only_electron_provider_projection(tmp_path, monkeypatch):
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "DESKTOP_SESSION_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "desktop_sessions.sqlite3",
    )
    monkeypatch.setattr(launcher_service, "PROJECT_ROOT", tmp_path)
    launcher_service.register_desktop_session(
        {
            "desktopSessionId": "electron-launcher-only-2",
            "provider": "electron",
            "workspaceRoot": str(tmp_path),
            "capabilities": ["desktop_actions.claim"],
        }
    )

    workbench = launcher_service._workbench_payload(
        runtime_state={
            "daemonRunning": True,
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
            },
        },
        observed_workbench={
            "observedState": "open",
            "backendObserved": True,
            "backendAlive": True,
            "backendHealthy": True,
            "backendPortListening": True,
        },
    )

    assert workbench["windowProvider"] == "electron"
    assert workbench["windowManaged"] is False
    assert workbench["browserManaged"] is False
    assert workbench["desktopSessionId"] == "electron-launcher-only-2"


def test_launcher_status_projects_active_desktop_session_window(tmp_path, monkeypatch):
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "DESKTOP_SESSION_DB_PATH",
        tmp_path / ".runtime" / "launcher" / "desktop_sessions.sqlite3",
    )
    monkeypatch.setattr(launcher_service, "STATE_PATH", tmp_path / ".runtime" / "runtime-manager" / "state.json")
    monkeypatch.setattr(launcher_service, "INBOX_DIR", tmp_path / ".runtime" / "runtime-manager" / "inbox")
    monkeypatch.setattr(launcher_service, "PROCESSING_DIR", tmp_path / ".runtime" / "runtime-manager" / "processing")
    monkeypatch.setattr(launcher_service, "RESULTS_DIR", tmp_path / ".runtime" / "runtime-manager" / "results")
    monkeypatch.setattr(launcher_service, "EVENTS_PATH", tmp_path / ".runtime" / "runtime-manager" / "events.jsonl")
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", tmp_path / ".runtime" / "launcher" / "state.json")
    monkeypatch.setattr(
        launcher_service,
        "load_state",
        lambda: {
            "daemonRunning": True,
            "workbench": {"desiredState": "open", "observedState": "partial", "phase": "steady"},
        },
    )
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 0)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda *args, **kwargs: {
            "observedState": "partial",
            "sessionRole": "workbench",
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPortListening": True,
            "browserWindowAlive": False,
            "browserManaged": True,
            "lifecycleConsistency": "browser_missing",
            "url": "http://127.0.0.1:8000/",
        },
    )
    created = launcher_service.register_desktop_session(
        {
            "desktopSessionId": "desktop-session-1",
            "provider": "electron",
            "workspaceRoot": str(tmp_path),
            "capabilities": ["desktop_actions.claim"],
        }
    )
    launcher_service.update_desktop_session_window(
        "desktop-session-1",
        "workbench",
        {
            "revision": created["revision"],
            "provider": "electron",
            "open": True,
            "focused": True,
            "windowId": 42,
            "rendererProcessId": 4242,
            "url": "http://127.0.0.1:8000/",
        },
    )

    payload = launcher_service.get_launcher_status()

    assert payload["projectBundle"]["windowProvider"] == "electron"
    assert payload["projectBundle"]["windowManaged"] is True
    assert payload["projectBundle"]["windowId"] == 42
    assert payload["projectBundle"]["rendererProcessId"] == 4242
    assert payload["projectBundle"]["desktopSessionId"] == "desktop-session-1"
    assert payload["projectBundle"]["desktopSessionLeaseExpiresAt"]
    assert payload["projectBundle"]["browser"]["managed"] is False
    assert payload["lifecycleProof"]["browserManaged"] is False
    assert payload["projectBundle"]["observedState"] == "open"
    assert payload["projectBundle"]["lifecycleConsistency"] == "consistent"
    assert payload["projectBundle"]["statusLine"] == "工作台正在运行。"


@pytest.mark.parametrize("has_active_close_transaction", [False, True])
def test_workbench_payload_reconciles_stale_closed_state_against_active_electron_session(
    has_active_close_transaction, monkeypatch
):
    from core.launcher import lifecycle_intent_store

    desktop_session_id = "desktop-reconcile-1"
    if has_active_close_transaction:
        lifecycle_intent_store.submit_workbench_close_transaction(
            {
                "desktopSessionId": desktop_session_id,
                "idempotencyKey": "desktop-reconcile-1:close:1",
                "mode": "normal",
            },
            desktop_session={
                "desktopSessionId": desktop_session_id,
                "status": "active",
                "revision": 1,
                "capabilities": ["workbench_close.transaction.v1"],
            },
            active_work_runs=[],
        )
    monkeypatch.setattr(
        launcher_service,
        "_desktop_session_workbench_projection",
        lambda: {
            "observedState": "open",
            "browserWindowAlive": True,
            "browserManaged": False,
            "windowProvider": "electron",
            "windowManaged": True,
            "desktopSessionId": desktop_session_id,
        },
    )
    monkeypatch.setattr(launcher_service, "_desktop_session_window_provider_projection", dict)

    payload = launcher_service._workbench_payload(
        runtime_state={
            "daemonRunning": False,
            "command": {"activeCommandId": "", "activeType": ""},
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
            },
        },
        observed_workbench={
            "backendObserved": True,
            "backendAlive": True,
            "backendHealthy": True,
            "backendPortListening": True,
            "lifecycleConsistency": "consistent",
        },
    )

    assert payload["observedState"] == "open"
    if has_active_close_transaction:
        assert payload["desiredState"] == "closed"
        assert payload["phase"] == "closing"
        assert payload["statusLine"] == "正在关闭工作台。"
    else:
        assert payload["desiredState"] == "open"
        assert payload["phase"] == "steady"
        assert payload["statusLine"] == "工作台正在运行。"


def test_standalone_launcher_app_exposes_desktop_session_routes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        launcher_service,
        "register_desktop_session",
        lambda payload: calls.append(("register", payload))
        or {"desktopSessionId": payload["desktopSessionId"], "revision": 1, "status": "active"},
    )
    monkeypatch.setattr(
        launcher_service,
        "update_desktop_session_window",
        lambda desktop_session_id, role, payload: calls.append(("window", desktop_session_id, role, payload))
        or {"desktopSessionId": desktop_session_id, "revision": 2, "status": "active"},
    )
    monkeypatch.setattr(
        launcher_service,
        "heartbeat_desktop_session",
        lambda desktop_session_id, payload: calls.append(("heartbeat", desktop_session_id, payload))
        or {"desktopSessionId": desktop_session_id, "revision": 3, "status": "active"},
    )
    monkeypatch.setattr(
        launcher_service,
        "close_desktop_session",
        lambda desktop_session_id, payload: calls.append(("close", desktop_session_id, payload))
        or {"desktopSessionId": desktop_session_id, "revision": 4, "status": "closed"},
    )
    client = TestClient(launcher_app.create_launcher_app())
    token_headers = {"X-Vibelution-Control-Token": client.get("/api/control-token").json()["controlToken"]}

    registered = client.post(
        "/api/launcher/desktop-sessions",
        headers=token_headers,
        json={"desktopSessionId": "desktop-session-1", "provider": "electron", "capabilities": ["desktop_actions.claim"]},
    )
    window = client.put(
        "/api/launcher/desktop-sessions/desktop-session-1/windows/workbench",
        headers=token_headers,
        json={"revision": 1, "provider": "electron", "open": True, "focused": True, "windowId": 42, "rendererProcessId": 4242, "url": "http://127.0.0.1:8000/"},
    )
    heartbeat = client.post(
        "/api/launcher/desktop-sessions/desktop-session-1/heartbeat",
        headers=token_headers,
        json={"revision": 2},
    )
    closed = client.request(
        "DELETE",
        "/api/launcher/desktop-sessions/desktop-session-1",
        headers=token_headers,
        json={"revision": 3},
    )

    assert registered.status_code == 201
    assert window.status_code == 200
    assert heartbeat.status_code == 200
    assert closed.status_code == 200
    assert calls[0] == (
        "register",
        {"desktopSessionId": "desktop-session-1", "provider": "electron", "capabilities": ["desktop_actions.claim"], "workspaceRoot": ""},
    )
    assert calls[1][0:3] == ("window", "desktop-session-1", "workbench")
    assert calls[2:] == [
        ("heartbeat", "desktop-session-1", {"revision": 2}),
        ("close", "desktop-session-1", {"revision": 3}),
    ]


def test_standalone_launcher_app_maps_desktop_session_revision_conflict_to_409(monkeypatch):
    from core.launcher.desktop_session_store import DesktopSessionRevisionConflict

    monkeypatch.setattr(
        launcher_service,
        "update_desktop_session_window",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DesktopSessionRevisionConflict(1, 2)),
    )
    client = TestClient(launcher_app.create_launcher_app())
    token_headers = {"X-Vibelution-Control-Token": client.get("/api/control-token").json()["controlToken"]}

    conflict = client.put(
        "/api/launcher/desktop-sessions/desktop-session-1/windows/workbench",
        headers=token_headers,
        json={"revision": 1, "provider": "electron", "open": True},
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {
        "code": "desktop_session_revision_conflict",
        "message": "desktop session revision conflict: expected 1, actual 2",
        "expectedDesktopSessionRevision": 1,
        "actualDesktopSessionRevision": 2,
    }


def test_standalone_launcher_runtime_scene_event_route_requires_control_token(monkeypatch):
    calls = []
    monkeypatch.setattr(
        launcher_app.runtime_scene_service,
        "record_electron_supervisor_event",
        lambda event_code, **kwargs: calls.append((event_code, kwargs)) or {"accepted": True, "runtimeSceneId": "scene-1"},
    )
    client = TestClient(launcher_app.create_launcher_app())

    rejected = client.post(
        "/api/launcher/runtime-scene/events",
        json={"eventCode": "electron.desktop_action.claimed", "message": "claimed", "fields": {}},
    )
    token = client.get("/api/control-token").json()["controlToken"]
    accepted = client.post(
        "/api/launcher/runtime-scene/events",
        headers={"X-Vibelution-Control-Token": token},
        json={"eventCode": "electron.desktop_action.claimed", "message": "claimed", "fields": {"actionId": "a1"}},
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 202
    assert calls == [
        (
            "electron.desktop_action.claimed",
            {
                "message": "claimed",
                "fields": {"actionId": "a1"},
                "level": "info",
                "outcome": "observed",
                "occurred_at": "",
            },
        )
    ]


def test_standalone_launcher_browser_telemetry_route_requires_control_token(monkeypatch):
    calls = []
    monkeypatch.setattr(
        launcher_app.runtime_scene_service,
        "record_browser_telemetry",
        lambda payload: calls.append(payload) or {"accepted": True, "runtimeSceneId": "scene-1"},
    )
    client = TestClient(launcher_app.create_launcher_app())
    payload = {
        "phase": "stream",
        "eventCode": "browser.session_stream.assistant_delta_applied",
        "message": "assistant delta applied",
        "level": "info",
        "fields": {"sessionId": "session-1", "deltaLength": 128},
    }

    rejected = client.post("/api/runtime/browser-telemetry", json=payload)
    token = client.get("/api/control-token").json()["controlToken"]
    accepted = client.post(
        "/api/runtime/browser-telemetry",
        headers={"X-Vibelution-Control-Token": token},
        json=payload,
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 202
    assert calls == [payload]


def test_standalone_launcher_app_exposes_workbench_window_setting(monkeypatch):
    calls = []
    monkeypatch.setattr(
        launcher_service,
        "get_workbench_window_mode_setting",
        lambda: {"mode": "fullscreen", "effectiveMode": "fullscreen", "envOverride": "", "configHash": "hash-current", "options": []},
    )
    monkeypatch.setattr(
        launcher_service,
        "update_workbench_window_mode",
        lambda mode, *, base_hash="": calls.append((mode, base_hash)) or {"ok": True, "mode": mode, "setting": {"mode": mode}, "message": "saved"},
    )
    client = TestClient(launcher_app.create_launcher_app())

    current = client.get("/api/launcher/settings/workbench-window")
    updated = client.put("/api/launcher/settings/workbench-window", json={"mode": "windowed", "baseHash": "hash-current"})

    assert current.status_code == 200
    assert current.json()["mode"] == "fullscreen"
    assert updated.status_code == 200
    assert updated.json()["mode"] == "windowed"
    assert calls == [("windowed", "hash-current")]


def test_standalone_launcher_app_rejects_invalid_workbench_window_setting(monkeypatch):
    monkeypatch.setattr(
        launcher_service,
        "update_workbench_window_mode",
        lambda _mode, *, base_hash="": (_ for _ in ()).throw(ValueError("bad mode")),
    )
    client = TestClient(launcher_app.create_launcher_app())

    response = client.put("/api/launcher/settings/workbench-window", json={"mode": "floating", "baseHash": "hash-current"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_workbench_window_mode"


def test_standalone_launcher_app_rejects_stale_workbench_window_setting(monkeypatch):
    monkeypatch.setattr(
        launcher_service,
        "update_workbench_window_mode",
        lambda _mode, *, base_hash="": (_ for _ in ()).throw(launcher_service.LauncherSettingsConflict("stale config")),
    )
    client = TestClient(launcher_app.create_launcher_app())

    response = client.put("/api/launcher/settings/workbench-window", json={"mode": "windowed", "baseHash": "stale-hash"})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "launcher_workbench_window_mode_conflict"


def test_standalone_launcher_app_exposes_maintenance_reset_routes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        launcher_service,
        "get_launcher_maintenance_summary",
        lambda: calls.append(("summary", None)) or {"executionOwner": "launcher", "profiles": []},
    )
    monkeypatch.setattr(
        launcher_service,
        "preview_launcher_maintenance_plan",
        lambda payload: calls.append(("preview", payload))
        or {"ok": True, "plan": {"planId": "maintplan-1", "planHash": "hash-1"}},
    )
    monkeypatch.setattr(
        launcher_service,
        "apply_launcher_maintenance_plan",
        lambda payload: calls.append(("apply", payload))
        or {"ok": True, "planId": "maintplan-1", "planHash": "hash-1"},
    )
    client = TestClient(launcher_app.create_launcher_app())

    summary = client.get("/api/launcher/maintenance/reset/summary")
    preview = client.post("/api/launcher/maintenance/reset/preview", json={"profileId": "factory_runtime"})
    apply = client.post(
        "/api/launcher/maintenance/reset/apply",
        json={"planId": "maintplan-1", "planHash": "hash-1", "profileId": "factory_runtime", "confirm": True},
    )

    assert summary.status_code == 200
    assert summary.json()["executionOwner"] == "launcher"
    assert preview.status_code == 200
    assert preview.json()["plan"]["planId"] == "maintplan-1"
    assert apply.status_code == 200
    assert apply.json()["planHash"] == "hash-1"
    assert calls == [
        ("summary", None),
        ("preview", {"profileId": "factory_runtime", "itemIds": []}),
        ("apply", {"planId": "maintplan-1", "planHash": "hash-1", "profileId": "factory_runtime", "confirm": True}),
    ]


def test_standalone_launcher_app_rejects_invalid_maintenance_plan_id(monkeypatch):
    monkeypatch.setattr(
        launcher_service,
        "apply_launcher_maintenance_plan",
        lambda payload: (_ for _ in ()).throw(
            launcher_service.LauncherMaintenancePlanError("invalid_plan_id", "bad plan id")
        ),
    )
    client = TestClient(launcher_app.create_launcher_app())

    response = client.post(
        "/api/launcher/maintenance/reset/apply",
        json={"planId": "bad", "planHash": "hash-1", "profileId": "factory_runtime", "confirm": True},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_plan_id"


def test_workbench_launcher_adapter_exposes_workbench_window_setting(monkeypatch):
    calls = []
    monkeypatch.setattr(
        launcher_service,
        "get_workbench_window_mode_setting",
        lambda: {"mode": "fullscreen", "effectiveMode": "fullscreen", "envOverride": "", "configHash": "hash-current", "options": []},
    )
    monkeypatch.setattr(
        launcher_service,
        "update_workbench_window_mode",
        lambda mode, *, base_hash="": calls.append((mode, base_hash)) or {"ok": True, "mode": mode, "setting": {"mode": mode}, "message": "saved"},
    )
    app = FastAPI()
    app.include_router(web_launcher_routes.router, prefix="/api")
    client = TestClient(app)

    current = client.get("/api/launcher/settings/workbench-window")
    updated = client.put("/api/launcher/settings/workbench-window", json={"mode": "windowed", "baseHash": "hash-current"})

    assert current.status_code == 200
    assert current.json()["mode"] == "fullscreen"
    assert updated.status_code == 200
    assert updated.json()["mode"] == "windowed"
    assert calls == [("windowed", "hash-current")]


def test_standalone_launcher_app_serves_health_token_and_launcher_shell(monkeypatch, tmp_path):
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Launcher</title>", encoding="utf-8")
    (dist / "asset.txt").write_text("asset-ok", encoding="utf-8")
    monkeypatch.setattr(launcher_app, "WEB_DIST", dist)
    monkeypatch.setattr(launcher_app, "WEB_INDEX", dist / "index.html")
    client = TestClient(launcher_app.create_launcher_app())

    health = client.get("/api/health")
    token = client.get("/api/control-token")
    shell = client.get("/launcher")
    asset = client.get("/asset.txt")

    assert health.status_code == 200
    assert health.json()["service"] == "launcher"
    assert token.status_code == 200
    assert token.json()["controlToken"]
    assert shell.status_code == 200
    assert "Launcher" in shell.text
    assert asset.status_code == 200
    assert asset.text == "asset-ok"


def test_standalone_launcher_app_allows_workbench_origin_for_control_preflight():
    client = TestClient(launcher_app.create_launcher_app())

    response = client.options(
        "/api/launcher/status",
        headers={
            "Origin": "http://127.0.0.1:8000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Vibelution-Control-Token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:8000"
    assert "X-Vibelution-Control-Token" in response.headers["access-control-allow-headers"]


def test_standalone_launcher_app_reports_missing_shell_when_index_is_absent(monkeypatch, tmp_path):
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    monkeypatch.setattr(launcher_app, "WEB_DIST", dist)
    monkeypatch.setattr(launcher_app, "WEB_INDEX", dist / "index.html")
    client = TestClient(launcher_app.create_launcher_app())

    response = client.get("/launcher")

    assert response.status_code == 503
    assert "not been built" in response.json()["message"]


def test_launcher_status_is_independent_from_web_runtime_service(monkeypatch, tmp_path):
    import core.web.services.runtime_service as runtime_service

    def fail_web_runtime_summary():
        raise AssertionError("standalone Launcher status must not call Web runtime_service")

    monkeypatch.setattr(runtime_service, "get_runtime_summary", fail_web_runtime_summary)
    monkeypatch.setattr(launcher_service, "STATE_PATH", tmp_path / ".runtime" / "runtime-manager" / "state.json")
    monkeypatch.setattr(launcher_service, "INBOX_DIR", tmp_path / ".runtime" / "runtime-manager" / "inbox")
    monkeypatch.setattr(launcher_service, "PROCESSING_DIR", tmp_path / ".runtime" / "runtime-manager" / "processing")
    monkeypatch.setattr(launcher_service, "RESULTS_DIR", tmp_path / ".runtime" / "runtime-manager" / "results")
    monkeypatch.setattr(launcher_service, "EVENTS_PATH", tmp_path / ".runtime" / "runtime-manager" / "events.jsonl")
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", tmp_path / ".runtime" / "launcher" / "state.json")
    monkeypatch.setattr(launcher_service, "load_state", lambda: {})
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 0)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "sessionRole": "workbench",
            "backendAlive": False,
            "backendHealthy": False,
            "browserWindowAlive": False,
            "browserManaged": True,
            "url": "http://127.0.0.1:8000",
        },
    )

    payload = launcher_service.get_launcher_status()

    assert payload["launcher"]["mode"] == "standalone_control_plane"
    assert payload["launcher"]["controlPlane"]["independent"] is True
    assert payload["launcher"]["controlPlane"]["url"] == ""
    assert payload["launcher"]["controlPlane"]["port"] == 0
    assert payload["projectBundle"]["observedState"] == "closed"
    assert payload["projectBundle"]["windowProvider"] in {"none", "edge_app", "electron"}
    assert isinstance(payload["projectBundle"]["windowManaged"], bool)
    assert payload["projectBundle"]["browser"]["managed"] == (
        payload["projectBundle"]["windowProvider"] == "edge_app"
        and payload["projectBundle"]["windowManaged"]
    )


def test_launcher_status_exposes_configured_control_plane_url(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "launcherControlUrl": "http://127.0.0.1:8899/launcher",
                "launcherControlPort": 8899,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher_service, "STATE_PATH", tmp_path / ".runtime" / "runtime-manager" / "state.json")
    monkeypatch.setattr(launcher_service, "INBOX_DIR", tmp_path / ".runtime" / "runtime-manager" / "inbox")
    monkeypatch.setattr(launcher_service, "PROCESSING_DIR", tmp_path / ".runtime" / "runtime-manager" / "processing")
    monkeypatch.setattr(launcher_service, "RESULTS_DIR", tmp_path / ".runtime" / "runtime-manager" / "results")
    monkeypatch.setattr(launcher_service, "EVENTS_PATH", tmp_path / ".runtime" / "runtime-manager" / "events.jsonl")
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "load_state", lambda: {})
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 0)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "sessionRole": "workbench",
            "backendAlive": False,
            "backendHealthy": False,
            "browserWindowAlive": False,
            "browserManaged": True,
            "url": "http://127.0.0.1:8000",
        },
    )

    payload = launcher_service.get_launcher_status()

    assert payload["launcher"]["controlPlane"]["url"] == "http://127.0.0.1:8899/launcher"
    assert payload["launcher"]["controlPlane"]["port"] == 8899


def test_launcher_status_exposes_workbench_window_mode_setting(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workbench]\nwindow_mode = \"windowed\"\n", encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.delenv("VIBELUTION_WORKBENCH_WINDOW_MODE", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_WINDOW_MODE", raising=False)
    monkeypatch.setattr(launcher_service, "STATE_PATH", tmp_path / ".runtime" / "runtime-manager" / "state.json")
    monkeypatch.setattr(launcher_service, "INBOX_DIR", tmp_path / ".runtime" / "runtime-manager" / "inbox")
    monkeypatch.setattr(launcher_service, "PROCESSING_DIR", tmp_path / ".runtime" / "runtime-manager" / "processing")
    monkeypatch.setattr(launcher_service, "RESULTS_DIR", tmp_path / ".runtime" / "runtime-manager" / "results")
    monkeypatch.setattr(launcher_service, "EVENTS_PATH", tmp_path / ".runtime" / "runtime-manager" / "events.jsonl")
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", tmp_path / ".runtime" / "launcher" / "state.json")
    monkeypatch.setattr(launcher_service, "load_state", lambda: {})
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 0)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "sessionRole": "workbench",
            "backendAlive": False,
            "backendHealthy": False,
            "browserWindowAlive": False,
            "browserManaged": True,
            "url": "http://127.0.0.1:8000",
        },
    )

    payload = launcher_service.get_launcher_status()

    setting = payload["settings"]["workbenchWindow"]
    assert setting["mode"] == "windowed"
    assert setting["effectiveMode"] == "windowed"
    assert setting["envOverride"] == ""
    assert setting["configHash"]
    assert {item["mode"] for item in setting["options"]} == {"fullscreen", "windowed"}


def test_launcher_workbench_window_mode_update_persists_config_and_logs(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workbench]\nbackend_port = 8000\nwindow_mode = \"fullscreen\"\n", encoding="utf-8")
    events = []
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.delenv("VIBELUTION_WORKBENCH_WINDOW_MODE", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_WINDOW_MODE", raising=False)
    monkeypatch.setattr(
        launcher_service,
        "append_runtime_manager_file_event",
        lambda event_code, payload, **kwargs: events.append((event_code, payload)) or "2026-06-06T00:00:00+00:00",
    )

    base_hash = launcher_service.get_workbench_window_mode_setting()["configHash"]
    response = launcher_service.update_workbench_window_mode("windowed", base_hash=base_hash)

    assert response["ok"] is True
    assert response["setting"]["mode"] == "windowed"
    assert response["setting"]["configHash"] != base_hash
    assert 'window_mode = "windowed"' in config_path.read_text(encoding="utf-8")
    assert "launcher.settings.workbench_window_mode.updated" in [event[0] for event in events]


def test_launcher_workbench_window_mode_rejects_stale_config_hash(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workbench]\nbackend_port = 8000\nwindow_mode = \"fullscreen\"\n", encoding="utf-8")
    events = []
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.delenv("VIBELUTION_WORKBENCH_WINDOW_MODE", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_WINDOW_MODE", raising=False)
    monkeypatch.setattr(
        launcher_service,
        "append_runtime_manager_file_event",
        lambda event_code, payload, **kwargs: events.append((event_code, payload)) or "2026-06-06T00:00:00+00:00",
    )

    base_hash = launcher_service.get_workbench_window_mode_setting()["configHash"]
    launcher_service.update_workbench_window_mode("windowed", base_hash=base_hash)

    try:
        launcher_service.update_workbench_window_mode("fullscreen", base_hash=base_hash)
    except launcher_service.LauncherSettingsConflict as exc:
        error = str(exc)
    else:
        raise AssertionError("expected stale window mode update to be rejected")

    assert "配置" in error
    assert 'window_mode = "windowed"' in config_path.read_text(encoding="utf-8")
    assert events[-1][0] == "launcher.settings.workbench_window_mode.conflict"
    assert events[-1][1]["fields"]["requestedMode"] == "fullscreen"


def test_launcher_workbench_window_mode_reports_environment_override(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workbench]\nwindow_mode = \"windowed\"\n", encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.setenv("VIBELUTION_WORKBENCH_WINDOW_MODE", "fullscreen")
    monkeypatch.delenv("AGENT_WORKBENCH_WINDOW_MODE", raising=False)

    setting = launcher_service.get_workbench_window_mode_setting()

    assert setting["mode"] == "windowed"
    assert setting["effectiveMode"] == "fullscreen"
    assert setting["envOverride"] == "fullscreen"


def test_launcher_startup_settings_persist_workbench_window_size(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workbench]\nwindow_mode = \"windowed\"\nwindow_size = \"auto\"\n", encoding="utf-8")
    events = []
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.delenv("VIBELUTION_WORKBENCH_WINDOW_SIZE", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_WINDOW_SIZE", raising=False)
    monkeypatch.setattr(
        launcher_service,
        "append_runtime_manager_file_event",
        lambda event_code, payload, **kwargs: events.append((event_code, payload)) or "2026-06-06T00:00:00+00:00",
    )

    response = launcher_service.update_launcher_startup_settings(
        {
            "baseHash": launcher_service.get_launcher_startup_settings()["configHash"],
            "workbench": {"windowSize": "1600x900"},
        }
    )

    text = config_path.read_text(encoding="utf-8")
    assert response["ok"] is True
    assert response["setting"]["workbench"]["windowSize"] == "1600x900"
    assert response["setting"]["workbench"]["effectiveWindowSize"] == "1600x900"
    assert 'window_size = "1600x900"' in text
    assert events[-1][0] == "launcher.settings.startup.updated"
    assert events[-1][1]["fields"]["current"]["windowSize"] == "1600x900"


def test_launcher_startup_settings_persist_launcher_control_port(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n[workbench]\nbackend_port = 8000\n", encoding="utf-8")
    events = []
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.delenv("VIBELUTION_LAUNCHER_PORT", raising=False)
    monkeypatch.delenv("AGENT_LAUNCHER_CONTROL_PORT", raising=False)
    monkeypatch.setattr(
        launcher_service,
        "append_runtime_manager_file_event",
        lambda event_code, payload, **kwargs: events.append((event_code, payload)) or "2026-06-06T00:00:00+00:00",
    )

    response = launcher_service.update_launcher_startup_settings(
        {
            "baseHash": launcher_service.get_launcher_startup_settings()["configHash"],
            "launcher": {"controlPort": 8899},
        }
    )

    text = config_path.read_text(encoding="utf-8")
    assert response["ok"] is True
    assert response["setting"]["launcher"]["controlPort"] == 8899
    assert response["setting"]["launcher"]["effectiveControlPort"] == 8899
    assert 'control_port = 8899' in text
    assert events[-1][0] == "launcher.settings.startup.updated"
    assert events[-1][1]["fields"]["current"]["controlPort"] == 8899


def test_launcher_startup_settings_requires_current_config_hash(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[workbench]\nwindow_size = "auto"\n', encoding="utf-8")
    events = []
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.setattr(
        launcher_service,
        "append_runtime_manager_file_event",
        lambda event_code, payload, **kwargs: events.append((event_code, payload))
        or "2026-06-06T00:00:00+00:00",
    )
    base_hash = launcher_service.get_launcher_startup_settings()["configHash"]

    with pytest.raises(launcher_service.LauncherSettingsConflict, match="缺少配置版本"):
        launcher_service.update_launcher_startup_settings({"workbench": {"windowSize": "1600x900"}})
    assert config_path.read_text(encoding="utf-8") == '[workbench]\nwindow_size = "auto"\n'

    config_path.write_text('[workbench]\nwindow_size = "1280x800"\n', encoding="utf-8")
    with pytest.raises(launcher_service.LauncherSettingsConflict, match="已被其他页面或进程改动"):
        launcher_service.update_launcher_startup_settings(
            {"baseHash": base_hash, "workbench": {"windowSize": "1600x900"}}
        )

    assert config_path.read_text(encoding="utf-8") == '[workbench]\nwindow_size = "1280x800"\n'
    assert [event[0] for event in events] == [
        "launcher.settings.startup.conflict",
        "launcher.settings.startup.conflict",
    ]


def test_launcher_startup_settings_reports_launcher_control_port_env_override(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n[workbench]\nbackend_port = 8000\n", encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.setenv("VIBELUTION_LAUNCHER_PORT", "8899")
    monkeypatch.delenv("AGENT_LAUNCHER_CONTROL_PORT", raising=False)

    setting = launcher_service.get_launcher_startup_settings()

    assert setting["launcher"]["controlPort"] == 8765
    assert setting["launcher"]["effectiveControlPort"] == 8899
    assert setting["launcher"]["controlPortEnvOverride"] == 8899


def test_launcher_startup_settings_avoids_launcher_control_port_workbench_collision(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n[workbench]\nbackend_port = 8765\n", encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.delenv("VIBELUTION_LAUNCHER_PORT", raising=False)
    monkeypatch.delenv("AGENT_LAUNCHER_CONTROL_PORT", raising=False)

    setting = launcher_service.get_launcher_startup_settings()

    assert setting["launcher"]["controlPort"] == 8765
    assert setting["launcher"]["effectiveControlPort"] != 8765
    assert setting["launcher"]["effectiveControlPort"] == 8766


def test_launcher_startup_settings_reports_workbench_window_size_env_override(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workbench]\nwindow_size = \"1600x900\"\n", encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.setenv("VIBELUTION_WORKBENCH_WINDOW_SIZE", "1280x800")
    monkeypatch.delenv("AGENT_WORKBENCH_WINDOW_SIZE", raising=False)

    setting = launcher_service.get_launcher_startup_settings()

    assert setting["workbench"]["windowSize"] == "1600x900"
    assert setting["workbench"]["effectiveWindowSize"] == "1280x800"
    assert setting["workbench"]["windowSizeEnvOverride"] == "1280x800"


def test_launcher_startup_settings_includes_custom_window_size_in_options(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[workbench]\nwindow_size = "960x600"\n', encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.delenv("VIBELUTION_WORKBENCH_WINDOW_SIZE", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_WINDOW_SIZE", raising=False)

    setting = launcher_service.get_launcher_startup_settings()
    sizes = [item["size"] for item in setting["workbench"]["windowSizeOptions"]]

    assert setting["workbench"]["windowSize"] == "960x600"
    assert "auto" in sizes
    assert "960x600" in sizes


def test_lifecycle_proof_projects_residual_process_inventory(monkeypatch):
    monkeypatch.setattr(
        launcher_service,
        "_residual_processes_payload",
        lambda **_kwargs: {
            "count": 1,
            "items": [
                {
                    "pid": 44100,
                    "parentPid": 1200,
                    "kind": "unmanaged_workbench",
                    "name": "python.exe",
                    "commandLine": "python -m uvicorn",
                    "cwd": "C:/repo",
                    "port": 8001,
                }
            ],
        },
    )

    proof = launcher_service._lifecycle_proof(
        runtime_manager={"running": True, "managerPid": 200},
        workbench={
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
            "backendAlive": True,
            "backendHealthy": True,
            "backendPortConflict": False,
            "backendPid": 300,
            "browserManaged": True,
            "browserWindowAlive": True,
            "browserWindowPid": 400,
            "statusLine": "ready",
        },
        active_work_runs=[],
    )

    assert proof["residualProcesses"]["count"] == 1
    assert proof["residualProcesses"]["items"][0]["pid"] == 44100
    assert proof["residualProcesses"]["items"][0]["kind"] == "unmanaged_workbench"


def test_status_residual_inventory_defers_full_scan_when_control_surface_is_closed(monkeypatch):
    monkeypatch.setattr(launcher_service, "_residual_processes_payload", _REAL_RESIDUAL_PROCESSES_PAYLOAD)

    def fail_if_scanned(**_kwargs):
        raise AssertionError("status poll should not run a full residual inventory scan when closed")

    monkeypatch.setattr(
        "core.runtime_manager.process_inventory.residual_process_payload",
        fail_if_scanned,
    )

    payload = launcher_service._residual_processes_payload(
        runtime_manager={"running": False, "managerPid": 0},
        workbench={
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
        runtime_state={},
    )

    assert payload["count"] == 0
    assert payload["items"] == []
    assert payload["mode"] == "deferred_for_status_poll"


def test_status_residual_inventory_reuses_runtime_state_cache(monkeypatch):
    monkeypatch.setattr(launcher_service, "_residual_processes_payload", _REAL_RESIDUAL_PROCESSES_PAYLOAD)

    def fail_if_scanned(**_kwargs):
        raise AssertionError("cached runtime residual inventory should satisfy status poll")

    monkeypatch.setattr(
        "core.runtime_manager.process_inventory.residual_process_payload",
        fail_if_scanned,
    )

    payload = launcher_service._residual_processes_payload(
        runtime_manager={"running": True, "managerPid": 200},
        workbench={
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
        runtime_state={
            "residualProcesses": {
                "count": 1,
                "items": [{"pid": 44100, "kind": "unmanaged_workbench"}],
            }
        },
    )

    assert payload["count"] == 1
    assert payload["items"][0]["pid"] == 44100


def test_launcher_startup_settings_rejects_invalid_workbench_window_size(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workbench]\n", encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)

    try:
        launcher_service.update_launcher_startup_settings(
            {
                "baseHash": launcher_service.get_launcher_startup_settings()["configHash"],
                "workbench": {"windowSize": "tiny"},
            }
        )
    except ValueError as exc:
        error = str(exc)
    else:
        raise AssertionError("expected invalid window size to be rejected")

    assert "workbench.windowSize" in error


def test_launcher_startup_settings_rejects_tiny_edge_chrome_window_size(tmp_path, monkeypatch):
    """320x240 is Edge --app minimum chrome, not a usable workbench — never accept it."""
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workbench]\nwindow_size = \"1600x900\"\n", encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.delenv("VIBELUTION_WORKBENCH_WINDOW_SIZE", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_WINDOW_SIZE", raising=False)

    try:
        launcher_service.update_launcher_startup_settings(
            {
                "baseHash": launcher_service.get_launcher_startup_settings()["configHash"],
                "workbench": {"windowSize": "320x240"},
            }
        )
    except ValueError as exc:
        error = str(exc)
    else:
        raise AssertionError("expected 320x240 window size to be rejected")

    assert "workbench.windowSize" in error
    # Stale tiny values in config must not become the effective startup size.
    config_path.write_text("[workbench]\nwindow_size = \"320x240\"\n", encoding="utf-8")
    setting = launcher_service.get_launcher_startup_settings()
    assert setting["workbench"]["windowSize"] == "auto"
    assert setting["workbench"]["effectiveWindowSize"] == "auto"


def test_launcher_startup_settings_persist_workbench_window_position(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[workbench]\nwindow_mode = \"windowed\"\nwindow_size = \"1600x900\"\nwindow_position = \"auto\"\n",
        encoding="utf-8",
    )
    events = []
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.delenv("VIBELUTION_WORKBENCH_WINDOW_POSITION", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_WINDOW_POSITION", raising=False)
    monkeypatch.setattr(
        launcher_service,
        "append_runtime_manager_file_event",
        lambda event_code, payload, **kwargs: events.append((event_code, payload)) or "2026-06-06T00:00:00+00:00",
    )

    response = launcher_service.update_launcher_startup_settings(
        {
            "baseHash": launcher_service.get_launcher_startup_settings()["configHash"],
            "workbench": {"windowPosition": "120,80"},
        }
    )

    text = config_path.read_text(encoding="utf-8")
    assert response["ok"] is True
    assert response["setting"]["workbench"]["windowPosition"] == "120,80"
    assert response["setting"]["workbench"]["effectiveWindowPosition"] == "120,80"
    assert 'window_position = "120,80"' in text
    assert events[-1][0] == "launcher.settings.startup.updated"
    assert events[-1][1]["fields"]["current"]["windowPosition"] == "120,80"


def test_launcher_startup_settings_accepts_negative_multi_monitor_position(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workbench]\n", encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.delenv("VIBELUTION_WORKBENCH_WINDOW_POSITION", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_WINDOW_POSITION", raising=False)
    monkeypatch.setattr(
        launcher_service,
        "append_runtime_manager_file_event",
        lambda event_code, payload, **kwargs: "2026-06-06T00:00:00+00:00",
    )

    response = launcher_service.update_launcher_startup_settings(
        {
            "baseHash": launcher_service.get_launcher_startup_settings()["configHash"],
            "workbench": {"windowPosition": "-640,120"},
        }
    )

    assert response["ok"] is True
    assert response["setting"]["workbench"]["windowPosition"] == "-640,120"
    assert 'window_position = "-640,120"' in config_path.read_text(encoding="utf-8")


def test_launcher_startup_settings_rejects_invalid_workbench_window_position(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workbench]\n", encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)

    try:
        launcher_service.update_launcher_startup_settings(
            {
                "baseHash": launcher_service.get_launcher_startup_settings()["configHash"],
                "workbench": {"windowPosition": "center"},
            }
        )
    except ValueError as exc:
        error = str(exc)
    else:
        raise AssertionError("expected invalid window position to be rejected")

    assert "workbench.windowPosition" in error


def test_launcher_startup_settings_soft_falls_back_extreme_offscreen_position(tmp_path, monkeypatch):
    """-20000,-20000 is a clamp sentinel that hides Edge --app completely — treat as auto."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('[workbench]\nwindow_position = "-20000,-20000"\n', encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.delenv("VIBELUTION_WORKBENCH_WINDOW_POSITION", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_WINDOW_POSITION", raising=False)

    setting = launcher_service.get_launcher_startup_settings()
    assert setting["workbench"]["windowPosition"] == "auto"
    assert setting["workbench"]["effectiveWindowPosition"] == "auto"

    try:
        launcher_service.update_launcher_startup_settings(
            {
                "baseHash": launcher_service.get_launcher_startup_settings()["configHash"],
                "workbench": {"windowPosition": "-20000,-20000"},
            }
        )
    except ValueError as exc:
        error = str(exc)
    else:
        raise AssertionError("expected extreme off-screen position to be rejected on write")
    assert "workbench.windowPosition" in error



def test_targeted_desktop_action_cannot_be_claimed_by_another_electron_session(tmp_path, monkeypatch):
    """A close action must not be stolen by a different live Electron shell."""
    from core.launcher import lifecycle_intent_store

    monkeypatch.setattr(lifecycle_intent_store, "LIFECYCLE_DB_PATH", tmp_path / "launcher" / "lifecycle.sqlite3")
    created = lifecycle_intent_store.submit_lifecycle_intent(
        {"action": "close_workbench", "reason": "pytest", "idempotencyKey": "targeted-close-1"},
        actor_context={"actorType": "launcher_api", "actorId": "launcher", "sourceRunId": "", "sourceTaskId": ""},
        active_work_runs=[],
        desktop_action_payload={"desktopSessionId": "electron-target", "closeId": "workbench-close-target"},
    )

    assert created["status"] == "accepted"
    assert lifecycle_intent_store.claim_desktop_action(desktop_session_id="electron-other", lease_seconds=30) == {}
    claimed = lifecycle_intent_store.claim_desktop_action(desktop_session_id="electron-target", lease_seconds=30)
    assert claimed["targetDesktopSessionId"] == "electron-target"
    assert claimed["payload"]["closeId"] == "workbench-close-target"



def test_launcher_status_projects_last_close_request_audit():
    workbench = launcher_service._workbench_payload(
        runtime_state={
            "daemonRunning": True,
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "lastReason": "launcher_stop_button",
                "lastSource": "launcher_api",
                "lastTransitionAt": "2026-06-28T09:33:19+00:00",
                "lastRequestAudit": {
                    "operation": "stop",
                    "trigger": "launcher_route_stop_button",
                    "endpoint": "/api/launcher/stop",
                    "method": "POST",
                    "clientHost": "127.0.0.1",
                    "secret": "ignored",
                },
            },
        },
        observed_workbench={},
    )

    bundle = launcher_service._project_bundle_from_workbench(
        workbench,
        lifecycle_proof={"overallState": "closed"},
        launcher_state={},
    )

    assert workbench["lastRequestAudit"] == {
        "operation": "stop",
        "trigger": "launcher_route_stop_button",
        "endpoint": "/api/launcher/stop",
        "method": "POST",
        "clientHost": "127.0.0.1",
    }
    assert bundle["lastOperation"] == {
        "reason": "launcher_stop_button",
        "source": "launcher_api",
        "transitionAt": "2026-06-28T09:33:19+00:00",
        "requestAudit": workbench["lastRequestAudit"],
    }



def test_launcher_active_work_guard_scans_parallel_chat_turn_snapshots(tmp_path, monkeypatch):
    work_runs_dir = tmp_path / ".runtime" / "runtime-manager" / "work_runs"
    store = WorkRunStore(root=work_runs_dir)
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-turn-alpha",
            "runKind": "chat_turn",
            "sessionId": "session-alpha",
            "status": "running",
        },
        active_run_id="chat-turn-alpha",
    )
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-turn-beta",
            "runKind": "chat_turn",
            "sessionId": "session-beta",
            "status": "running",
        },
        active_run_id="chat-turn-alpha",
    )
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_dir)

    active = launcher_service.launcher_active_work_runs()

    assert {item["runId"] for item in active} == {"chat-turn-alpha", "chat-turn-beta"}


def test_launcher_active_work_guard_ignores_superseded_worktree_snapshot(tmp_path, monkeypatch):
    work_runs_dir = tmp_path / ".runtime" / "runtime-manager" / "work_runs"
    store = WorkRunStore(root=work_runs_dir)
    store.persist_snapshot(
        "supervised_worktree_evolution_run",
        {
            "runId": "worktree-superseded",
            "runKind": "supervised_worktree_evolution_run",
            "status": "running",
        },
        active_run_id="worktree-superseded",
    )
    store.persist_snapshot(
        "supervised_worktree_evolution_run",
        {
            "runId": "worktree-latest",
            "runKind": "supervised_worktree_evolution_run",
            "status": "completed",
            "finishedAt": datetime.now(timezone.utc).isoformat(),
        },
        active_run_id="",
    )
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_dir)

    # Multi-slot active sets: another run's terminal persist no longer clears
    # the superseded run's own active mark, so the guard keeps blocking until
    # the superseded run itself is terminalized.
    assert launcher_service.launcher_active_work_runs() != []

    store.persist_snapshot(
        "supervised_worktree_evolution_run",
        {
            "runId": "worktree-superseded",
            "runKind": "supervised_worktree_evolution_run",
            "status": "superseded",
            "finishedAt": datetime.now(timezone.utc).isoformat(),
        },
        active_run_id="",
    )

    assert launcher_service.launcher_active_work_runs() == []


def test_launcher_active_work_guard_keeps_indexed_worktree_snapshot(tmp_path, monkeypatch):
    work_runs_dir = tmp_path / ".runtime" / "runtime-manager" / "work_runs"
    store = WorkRunStore(root=work_runs_dir)
    store.persist_snapshot(
        "supervised_worktree_evolution_run",
        {
            "runId": "worktree-current",
            "runKind": "supervised_worktree_evolution_run",
            "status": "running",
        },
        active_run_id="worktree-current",
    )
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_dir)

    assert launcher_service.launcher_active_work_runs() == [
        {
            "kind": "supervised_worktree_evolution_run",
            "runId": "worktree-current",
            "status": "running",
            "sessionId": "",
        }
    ]


def test_launcher_active_work_guard_ignores_stale_non_current_snapshots(tmp_path, monkeypatch):
    work_runs_dir = tmp_path / ".runtime" / "runtime-manager" / "work_runs"
    stale_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    store = WorkRunStore(root=work_runs_dir)
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-turn-stale",
            "runKind": "chat_turn",
            "sessionId": "session-stale",
            "status": "running",
            "updatedAt": stale_at,
        },
        active_run_id="",
    )
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_dir)

    assert launcher_service.launcher_active_work_runs() == []


def test_launcher_active_work_guard_keeps_current_active_snapshot_even_if_old(tmp_path, monkeypatch):
    work_runs_dir = tmp_path / ".runtime" / "runtime-manager" / "work_runs"
    stale_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    store = WorkRunStore(root=work_runs_dir)
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-turn-current",
            "runKind": "chat_turn",
            "sessionId": "session-current",
            "status": "running",
            "updatedAt": stale_at,
        },
        active_run_id="chat-turn-current",
    )
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_dir)

    assert launcher_service.launcher_active_work_runs()[0]["runId"] == "chat-turn-current"


def test_launcher_status_exposes_guardian_adapter_migration_contract(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "supervisorPid": 4444,
                "supervisorStdout": "logs/runtime_scenes/scene-a/raw/supervisor.log",
                "supervisorStderr": "logs/runtime_scenes/scene-a/raw/supervisor.stderr.log",
                "runtimeSceneId": "scene-a",
                "runtimeSceneDir": "logs/runtime_scenes/scene-a",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(
        launcher_service,
        "load_state",
        lambda: {
            "runtimeState": "idle",
            "managerPid": 2001,
            "stateVersion": 3,
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "url": "http://127.0.0.1:8000",
            },
        },
    )
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 2001)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: int(pid) in {2001, 4444})
    monkeypatch.setattr(launcher_service, "is_runtime_manager_process", lambda pid: int(pid) == 2001)
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
            "backendPid": 3001,
            "backendAlive": True,
            "backendHealthy": True,
            "backendPort": 8000,
            "backendPortListening": True,
            "browserManaged": True,
            "browserWindowPid": 4001,
            "browserWindowAlive": True,
            "url": "http://127.0.0.1:8000",
        },
    )

    payload = launcher_service.get_launcher_status()

    guardian = payload["guardianAdapter"]
    assert guardian["schemaVersion"] == 1
    assert guardian["mode"] == "standalone_control_plane"
    assert guardian["targetMode"] == "standalone_launcher_guardian"
    assert guardian["ownedCount"] >= 3
    assert guardian["adapterCount"] >= 2
    assert guardian["supervisor"]["pid"] == 4444
    assert guardian["supervisor"]["alive"] is True
    assert guardian["supervisor"]["status"] == "running"
    assert guardian["supervisor"]["blocking"] is False
    assert guardian["supervisor"]["impact"] == "non_blocking"
    assert guardian["supervisor"]["stdoutPath"].endswith("raw/supervisor.log")
    assert guardian["supervisor"]["stderrPath"].endswith("raw/supervisor.stderr.log")
    assert guardian["supervisor"]["runtimeSceneId"] == "scene-a"
    responsibilities = {item["id"]: item for item in guardian["responsibilities"]}
    assert responsibilities["project_bundle_lifecycle"]["owner"] == "standalone_launcher"
    assert responsibilities["runtime_manager_daemon"]["status"] == "running"
    assert responsibilities["desktop_supervisor"]["adapter"] == "vibelution_launcher"
    assert responsibilities["desktop_supervisor"]["status"] == "running"
    assert responsibilities["desktop_supervisor"]["blocking"] is False
    assert responsibilities["desktop_supervisor"]["impact"] == "non_blocking"
    assert responsibilities["backend_process"]["status"] == "running"
    assert responsibilities["browser_window"]["status"] == "managed"
    assert responsibilities["runtime_scene_logging"]["owner"] == "runtime_manager_events"


def test_launcher_status_exposes_control_plane_evidence(tmp_path, monkeypatch):
    runtime_dir = tmp_path / ".runtime" / "runtime-manager"
    inbox_dir = runtime_dir / "inbox"
    processing_dir = runtime_dir / "processing"
    results_dir = runtime_dir / "results"
    for directory in (inbox_dir, processing_dir, results_dir):
        directory.mkdir(parents=True, exist_ok=True)
    state_path = runtime_dir / "state.json"
    events_path = runtime_dir / "events.jsonl"
    state_path.write_text(
        json.dumps(
            {
                "stateVersion": 7,
                "runtimeState": "running",
                "managerPid": 3210,
                "updatedAt": "2026-06-03T00:00:00+00:00",
                "command": {
                    "activeCommandId": "cmd-active",
                    "activeType": "open_workbench",
                    "requestedBy": "launcher_api",
                    "startedAt": "2026-06-03T00:00:01+00:00",
                    "noBrowser": False,
                },
            }
        ),
        encoding="utf-8",
    )
    (inbox_dir / "cmd-pending.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-pending",
                "type": "restart_workbench",
                "requestedBy": "launcher_api",
                "requestedAt": "2026-06-03T00:00:02+00:00",
                "args": {
                    "reason": "launcher_restart",
                    "source": "launcher_api",
                    "deferredUntilActiveWorkClear": True,
                    "queuedBecauseActiveWork": True,
                    "queuedActiveWorkCount": 2,
                    "deferUntil": "2026-06-03T00:00:12+00:00",
                    "activeWorkDeferCount": 1,
                    "lastActiveWorkCount": 2,
                },
            }
        ),
        encoding="utf-8",
    )
    (processing_dir / "cmd-processing.json").write_text(
        json.dumps({"commandId": "cmd-processing", "type": "close_workbench", "requestedBy": "web_ui"}),
        encoding="utf-8",
    )
    (results_dir / "cmd-result.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-result",
                "ok": True,
                "completed": True,
                "message": "Workbench opened.",
                "stateVersion": 8,
            }
        ),
        encoding="utf-8",
    )
    events_path.write_text(
        "\n".join(
            [
                json.dumps({"type": "command.completed", "at": "2026-06-03T00:00:03+00:00", "payload": {"commandId": "cmd-result", "ok": True, "message": "done"}}),
                json.dumps({"type": "daemon.stopped", "at": "2026-06-03T00:00:04+00:00", "payload": {"commandId": "cmd-stop"}}),
                json.dumps(
                    {
                        "type": "command_queue.processing_recovered",
                        "at": "2026-06-03T00:00:05+00:00",
                        "payload": {"commandId": "cmd-recovered", "type": "restart_workbench"},
                    }
                ),
                json.dumps(
                    {
                        "type": "command_queue.command_result_written",
                        "at": "2026-06-03T00:00:06+00:00",
                        "payload": {
                            "commandId": "cmd-recovered",
                            "type": "restart_workbench",
                            "requestedBy": "launcher_api",
                            "resultPath": "cmd-recovered.json",
                            "ok": True,
                            "message": "Workbench restarted.",
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (results_dir / "cmd-recovered.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-recovered",
                "ok": True,
                "completed": True,
                "message": "Workbench restarted.",
                "stateVersion": 9,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher_service, "STATE_PATH", state_path)
    monkeypatch.setattr(launcher_service, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(launcher_service, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(launcher_service, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(launcher_service, "EVENTS_PATH", events_path)
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", tmp_path / ".runtime" / "launcher" / "state.json")
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(launcher_service, "load_state", lambda: json.loads(state_path.read_text(encoding="utf-8")))
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 3210)
    monkeypatch.setattr(launcher_service, "observe_workbench", lambda: {})

    payload = launcher_service.get_launcher_status()

    evidence = payload["controlPlaneEvidence"]
    assert evidence["schemaVersion"] == 1
    assert evidence["state"]["stateVersion"] == 7
    assert evidence["state"]["activeCommand"]["commandId"] == "cmd-active"
    assert evidence["queue"]["pendingCount"] == 1
    assert evidence["queue"]["processingCount"] == 1
    assert evidence["queue"]["pending"][0]["reason"] == "launcher_restart"
    assert evidence["queue"]["pending"][0]["deferredUntilActiveWorkClear"] is True
    assert evidence["restartQueue"]["pending"] is True
    assert evidence["restartQueue"]["pendingCount"] == 1
    assert evidence["restartQueue"]["commandId"] == "cmd-pending"
    assert evidence["restartQueue"]["lastActiveWorkCount"] == 2
    assert "2" in evidence["restartQueue"]["statusLine"]
    assert evidence["results"]["recent"][0]["commandId"] in {"cmd-result", "cmd-recovered"}
    # get_launcher_status may append a launcher.status.stale_close_recovery_requested
    # audit event after the offline recovery probe, so the newest event is not
    # stable; pin the queue-events order contract instead of a brittle index.
    event_types = [str(event["type"]) for event in evidence["events"]["recent"]]
    assert "command_queue.command_result_written" in event_types
    assert event_types.index("command_queue.command_result_written") < event_types.index("command_queue.processing_recovered")
    result_event = next(event for event in evidence["events"]["recent"] if event["type"] == "command_queue.command_result_written")
    assert result_event["commandId"] == "cmd-recovered"
    assert result_event["commandType"] == "restart_workbench"
    assert result_event["requestedBy"] == "launcher_api"
    assert result_event["resultPath"] == "cmd-recovered.json"
    assert evidence["recovery"]["active"] is True
    assert evidence["recovery"]["commandId"] == "cmd-recovered"
    assert evidence["recovery"]["commandType"] == "restart_workbench"
    assert evidence["recovery"]["resultOk"] is True
    assert evidence["recovery"]["resultPath"] == "cmd-recovered.json"
    assert "Workbench restarted." in evidence["recovery"]["statusLine"]


def test_launcher_status_rejects_reused_foreign_runtime_manager_pid(tmp_path, monkeypatch):
    runtime_dir = tmp_path / ".runtime" / "runtime-manager"
    inbox_dir = runtime_dir / "inbox"
    processing_dir = runtime_dir / "processing"
    results_dir = runtime_dir / "results"
    for directory in (inbox_dir, processing_dir, results_dir):
        directory.mkdir(parents=True, exist_ok=True)
    state_path = runtime_dir / "state.json"
    events_path = runtime_dir / "events.jsonl"
    state_path.write_text(
        json.dumps(
            {
                "stateVersion": 17,
                "runtimeState": "running",
                "managerPid": 25820,
                "daemonRunning": True,
                "updatedAt": "2026-06-22T15:37:28+00:00",
                "workbench": {
                    "desiredState": "closed",
                    "observedState": "open",
                    "phase": "failed",
                    "backendPid": 0,
                    "backendHealthy": False,
                    "backendPort": 8000,
                    "browserWindowPid": 28792,
                    "browserWindowAlive": True,
                    "lifecycleConsistency": "orphaned_browser",
                    "failureMessage": "Workbench frontend window is still open, but no backend service is reachable.",
                },
                "command": {"activeCommandId": "", "activeType": "", "requestedBy": "", "startedAt": ""},
            }
        ),
        encoding="utf-8",
    )
    (inbox_dir / "cmd-pending.json").write_text(
        json.dumps({"commandId": "cmd-pending", "type": "open_workbench", "requestedBy": "launcher_api"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(launcher_service, "STATE_PATH", state_path)
    monkeypatch.setattr(launcher_service, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(launcher_service, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(launcher_service, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(launcher_service, "EVENTS_PATH", events_path)
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", tmp_path / ".runtime" / "launcher" / "state.json")
    monkeypatch.setattr(launcher_service, "load_state", lambda: json.loads(state_path.read_text(encoding="utf-8")))
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 25820)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: int(pid) == 25820)
    monkeypatch.setattr(launcher_service, "is_runtime_manager_process", lambda pid: False)
    monkeypatch.setattr(launcher_service, "observe_workbench", lambda: {})

    payload = launcher_service.get_launcher_status()

    assert payload["runtimeManager"]["running"] is False
    assert payload["runtimeManager"]["runtimeState"] == "idle"
    assert payload["runtimeManager"]["managerPid"] == 0
    evidence = payload["controlPlaneEvidence"]
    assert evidence["state"]["runtimeState"] == "idle"
    assert evidence["state"]["managerPid"] == 0
    assert payload["lifecycleProof"]["components"][0]["state"] == "missing"
    assert payload["controlPlaneEvidence"]["queue"]["pendingCount"] == 1


def test_launcher_status_recovers_offline_stale_close_processing(tmp_path, monkeypatch):
    runtime_dir = tmp_path / ".runtime" / "runtime-manager"
    inbox_dir = runtime_dir / "inbox"
    processing_dir = runtime_dir / "processing"
    results_dir = runtime_dir / "results"
    for directory in (inbox_dir, processing_dir, results_dir):
        directory.mkdir(parents=True, exist_ok=True)
    state_path = runtime_dir / "state.json"
    events_path = runtime_dir / "events.jsonl"
    command_id = "cmd-stale-close"
    state_path.write_text(
        json.dumps(
            {
                "stateVersion": 11,
                "runtimeState": "running",
                "managerPid": 50012,
                "daemonRunning": True,
                "updatedAt": "2026-06-19T06:19:17+00:00",
                "command": {
                    "activeCommandId": command_id,
                    "activeType": "close_workbench",
                    "requestedBy": "launcher_api",
                    "startedAt": "2026-06-19T06:19:16+00:00",
                },
                "workbench": {
                    "desiredState": "closed",
                    "observedState": "open",
                    "phase": "closing",
                    "statusLine": "Runtime manager is closing the workbench.",
                },
            }
        ),
        encoding="utf-8",
    )
    (processing_dir / f"{command_id}.json").write_text(
        json.dumps(
            {
                "commandId": command_id,
                "type": "close_workbench",
                "requestedBy": "launcher_api",
                "requestedAt": "2026-06-19T06:19:09+00:00",
                "args": {"reason": "launcher_stop_button", "source": "launcher_api"},
            }
        ),
        encoding="utf-8",
    )

    recover_calls: list[str] = []

    def recover_processing_queue():
        recover_calls.append("recover")
        (processing_dir / f"{command_id}.json").unlink()
        (results_dir / f"{command_id}.json").write_text(
            json.dumps(
                {
                    "commandId": command_id,
                    "accepted": True,
                    "completed": True,
                    "ok": True,
                    "message": "Recovered stale close command was already satisfied.",
                    "stateVersion": 12,
                    "staleRecoveredCommand": True,
                }
            ),
            encoding="utf-8",
        )
        events_path.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "command_queue.command_result_written",
                            "at": "2026-06-19T06:20:00+00:00",
                            "payload": {
                                "commandId": command_id,
                                "type": "close_workbench",
                                "requestedBy": "launcher_api",
                                "resultPath": f"{command_id}.json",
                                "ok": True,
                                "completed": True,
                                "message": "Recovered stale close command was already satisfied.",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "command_queue.recovered_stale_close_completed",
                            "at": "2026-06-19T06:20:00+00:00",
                            "payload": {"commandId": command_id, "type": "close_workbench", "requestedBy": "launcher_api"},
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(launcher_service, "STATE_PATH", state_path)
    monkeypatch.setattr(launcher_service, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(launcher_service, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(launcher_service, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(launcher_service, "EVENTS_PATH", events_path)
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", tmp_path / ".runtime" / "launcher" / "state.json")
    monkeypatch.setattr(launcher_service, "load_state", lambda: json.loads(state_path.read_text(encoding="utf-8")))
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 50012)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(launcher_service.command_queue, "recover_processing_queue", recover_processing_queue)
    monkeypatch.setattr(launcher_service, "launcher_active_work_runs", lambda: [])
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "sessionRole": "launcher_control_surface",
            "observedState": "closed",
            "backendPid": 0,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPort": 8000,
            "backendPortListening": False,
            "browserManaged": True,
            "browserWindowPid": 0,
            "browserWindowAlive": False,
            "lifecycleConsistency": "consistent",
            "url": "http://127.0.0.1:8000",
        },
    )

    payload = launcher_service.get_launcher_status()

    assert recover_calls == ["recover"]
    evidence = payload["controlPlaneEvidence"]
    assert evidence["queue"]["processingCount"] == 0
    assert evidence["queue"]["pendingCount"] == 0
    assert evidence["state"]["runtimeState"] == "idle"
    assert evidence["state"]["managerPid"] == 0
    assert evidence["state"]["activeCommand"]["commandId"] == ""
    assert evidence["results"]["recent"][0]["commandId"] == command_id
    # The status poll appends its launcher.status.stale_close_recovery_requested
    # audit event after the mocked recovery rewrote the events file, so the
    # audit event is legitimately the newest entry. Pin the recovery order
    # contract: the recovered-stale-close completion must be present and newer
    # than its command result event.
    event_types = [str(event["type"]) for event in evidence["events"]["recent"]]
    assert event_types[0] == "launcher.status.stale_close_recovery_requested"
    assert "command_queue.recovered_stale_close_completed" in event_types
    assert event_types.index("command_queue.recovered_stale_close_completed") < event_types.index("command_queue.command_result_written")
    recovered_event = next(event for event in evidence["events"]["recent"] if event["type"] == "command_queue.recovered_stale_close_completed")
    assert recovered_event["commandId"] == command_id
    assert recovered_event["commandType"] == "close_workbench"
    assert payload["projectBundle"]["observedState"] == "closed"
    assert payload["runtimeManager"]["running"] is False
    assert payload["runtimeManager"]["runtimeState"] == "idle"
    assert payload["runtimeManager"]["managerPid"] == 0


def test_launcher_status_shows_control_surface_when_project_window_is_closed(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "sessionRole": "launcher_control_surface",
                "url": "http://127.0.0.1:8000",
                "backendPid": 10952,
                "browserManaged": False,
                "browserWindowPid": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(
        launcher_service,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 3210,
            "stateVersion": 10,
            "workbench": {
                "sessionRole": "launcher_control_surface",
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "url": "http://127.0.0.1:8000",
            },
        },
    )
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 3210)
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "sessionRole": "launcher_control_surface",
            "observedState": "closed",
            "backendPid": 10952,
            "backendAlive": False,
            "backendHealthy": False,
            "backendPort": 8000,
            "backendPortListening": False,
            "browserManaged": False,
            "browserWindowPid": 0,
            "browserWindowAlive": False,
            "url": "http://127.0.0.1:8000",
        },
    )

    payload = launcher_service.get_launcher_status()

    bundle = payload["projectBundle"]
    assert bundle["sessionRole"] == "launcher_control_surface"
    assert bundle["desiredState"] == "closed"
    assert bundle["observedState"] == "closed"
    assert bundle["browser"]["managed"] is False
    assert "Launcher 控制台正在运行" in bundle["statusLine"]


def test_launcher_status_keeps_project_open_when_launcher_control_surface_stays_alive(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "sessionRole": "launcher_control_surface",
                "url": "http://127.0.0.1:8000",
                "backendPid": 10952,
                "browserManaged": False,
                "browserWindowPid": 0,
                "workbenchBrowserWindowPid": 4001,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: int(pid) in {3210, 4001, 10952})
    monkeypatch.setattr(
        launcher_service,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 3210,
            "stateVersion": 10,
            "workbench": {
                "sessionRole": "launcher_control_surface",
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "url": "http://127.0.0.1:8000",
            },
        },
    )
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 3210)
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "sessionRole": "launcher_control_surface",
            "observedState": "closed",
            "backendPid": 10952,
            "backendAlive": True,
            "backendHealthy": True,
            "backendPort": 8000,
            "backendPortListening": True,
            "browserManaged": True,
            "browserWindowPid": 4001,
            "browserWindowAlive": True,
            "url": "http://127.0.0.1:8000",
        },
    )

    payload = launcher_service.get_launcher_status()

    bundle = payload["projectBundle"]
    assert bundle["sessionRole"] == "workbench"
    assert bundle["desiredState"] == "open"
    assert bundle["observedState"] == "open"
    assert bundle["backend"]["alive"] is True
    assert bundle["browser"]["alive"] is True
    assert bundle["statusLine"] == "工作台正在运行。"


def test_launcher_status_uses_fresh_runtime_manager_state_without_deep_observation(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    runtime_state = {
        "runtimeState": "running",
        "managerPid": 3210,
        "stateVersion": 18,
        "updatedAt": now,
        "command": {
            "activeCommandId": "",
            "activeType": "",
        },
        "workbench": {
            "sessionRole": "workbench",
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
            "backendPid": 46284,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPort": 8000,
            "backendPortListening": True,
            "backendPortOwnerPid": 46284,
            "backendPortConflict": False,
            "browserManaged": True,
            "browserWindowPid": 59400,
            "browserWindowAlive": True,
            "lifecycleConsistency": "consistent",
            "url": "http://127.0.0.1:8000",
            "lastReason": "launcher_restart_button",
            "lastSource": "launcher_api",
        },
    }
    state_path = tmp_path / ".runtime" / "runtime-manager" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(runtime_state), encoding="utf-8")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "sessionRole": "launcher_control_surface",
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 0,
                "browserWindowPid": 3300,
                "workbenchBrowserWindowPid": 0,
                "launcherBrowserWindowPid": 3300,
                "launcherControlUrl": "http://127.0.0.1:8765/launcher",
                "launcherControlPort": 8765,
                "url": "http://127.0.0.1:8000",
                "statusLine": "Workbench is running.",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher_service, "STATE_PATH", state_path)
    monkeypatch.setattr(launcher_service, "INBOX_DIR", tmp_path / ".runtime" / "runtime-manager" / "inbox")
    monkeypatch.setattr(launcher_service, "PROCESSING_DIR", tmp_path / ".runtime" / "runtime-manager" / "processing")
    monkeypatch.setattr(launcher_service, "RESULTS_DIR", tmp_path / ".runtime" / "runtime-manager" / "results")
    monkeypatch.setattr(launcher_service, "EVENTS_PATH", tmp_path / ".runtime" / "runtime-manager" / "events.jsonl")
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "load_state", lambda: runtime_state)
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 3210)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: int(pid) == 3210)
    monkeypatch.setattr(launcher_service, "is_runtime_manager_process", lambda pid: int(pid) == 3210)
    monkeypatch.setattr(launcher_service, "launcher_active_work_runs", lambda: [])
    observe_calls = []
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: observe_calls.append("observe") or {},
    )

    payload = launcher_service.get_launcher_status()

    bundle = payload["projectBundle"]
    assert bundle["sessionRole"] == "workbench"
    assert bundle["overallState"] == "ready"
    assert bundle["backend"]["pid"] == 46284
    assert bundle["browser"]["windowPid"] == 59400
    assert bundle["statusLine"] == "工作台正在运行。"
    assert observe_calls == []


def test_launcher_status_reconciles_fresh_state_when_effective_backend_port_changes(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    runtime_state = {
        "runtimeState": "running",
        "managerPid": 3210,
        "daemonRunning": True,
        "stateVersion": 19,
        "updatedAt": now,
        "lastError": {
            "message": "Workbench cleanup failed 4 times; close the leftover window manually or restart the Launcher.",
        },
        "command": {"activeCommandId": "", "activeType": ""},
        "workbench": {
            "sessionRole": "workbench",
            "desiredState": "open",
            "observedState": "open",
            "phase": "failed",
            "backendPid": 0,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPort": 8000,
            "backendPortListening": False,
            "browserManaged": True,
            "browserWindowPid": 59400,
            "browserWindowAlive": True,
            "lifecycleConsistency": "orphaned_browser",
            "failureMessage": "Workbench frontend window is still open, but no backend service is reachable.",
        },
    }
    state_path = tmp_path / ".runtime" / "runtime-manager" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(runtime_state), encoding="utf-8")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_PORT", "8002")
    monkeypatch.setattr(launcher_service, "STATE_PATH", state_path)
    monkeypatch.setattr(launcher_service, "INBOX_DIR", tmp_path / ".runtime" / "runtime-manager" / "inbox")
    monkeypatch.setattr(launcher_service, "PROCESSING_DIR", tmp_path / ".runtime" / "runtime-manager" / "processing")
    monkeypatch.setattr(launcher_service, "RESULTS_DIR", tmp_path / ".runtime" / "runtime-manager" / "results")
    monkeypatch.setattr(launcher_service, "EVENTS_PATH", tmp_path / ".runtime" / "runtime-manager" / "events.jsonl")
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "load_state", lambda: runtime_state)
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 3210)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: int(pid) == 3210)
    monkeypatch.setattr(launcher_service, "is_runtime_manager_process", lambda pid: int(pid) == 3210)
    monkeypatch.setattr(launcher_service, "launcher_active_work_runs", list)
    observe_calls = []
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: observe_calls.append("observe")
        or {
            "sessionRole": "workbench",
            "desiredState": "open",
            "observedState": "open",
            "backendPid": 46284,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPort": 8002,
            "backendPortListening": True,
            "backendPortOwnerPid": 46284,
            "backendPortConflict": False,
            "browserManaged": True,
            "browserWindowPid": 59400,
            "browserWindowAlive": True,
            "lifecycleConsistency": "consistent",
            "url": "http://127.0.0.1:8002",
        },
    )

    payload = launcher_service.get_launcher_status()

    bundle = payload["projectBundle"]
    assert observe_calls == ["observe"]
    assert bundle["overallState"] == "ready"
    assert bundle["backend"]["port"] == 8002
    assert bundle["statusLine"] == "工作台正在运行。"
    assert bundle["failureMessage"] == ""
    assert payload["failureMessage"] == ""


def test_launcher_status_reclassifies_control_surface_with_managed_backend_as_partial(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "sessionRole": "launcher_control_surface",
                "url": "http://127.0.0.1:8000",
                "backendPid": 0,
                "browserManaged": True,
                "browserWindowPid": 0,
                "launcherBrowserWindowPid": 4001,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: int(pid) in {3210, 4001})
    monkeypatch.setattr(
        launcher_service,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 3210,
            "stateVersion": 10,
            "daemonRunning": True,
            "workbench": {
                "sessionRole": "launcher_control_surface",
                "desiredState": "open",
                "observedState": "closed",
                "phase": "steady",
                "url": "http://127.0.0.1:8000",
            },
        },
    )
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 3210)
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "sessionRole": "launcher_control_surface",
            "observedState": "closed",
            "backendPid": 23400,
            "backendAlive": False,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPort": 8000,
            "backendPortListening": True,
            "backendPortConflict": False,
            "browserManaged": True,
            "browserWindowPid": 0,
            "browserWindowAlive": False,
            "lifecycleConsistency": "browser_missing",
            "url": "http://127.0.0.1:8000",
        },
    )

    payload = launcher_service.get_launcher_status()

    bundle = payload["projectBundle"]
    assert bundle["sessionRole"] == "workbench"
    assert bundle["desiredState"] == "open"
    assert bundle["observedState"] == "partial"
    assert bundle["overallState"] == "partial"
    assert bundle["backend"]["alive"] is True
    assert bundle["backend"]["healthy"] is True
    assert bundle["backend"]["portListening"] is True
    assert bundle["browser"]["alive"] is False
    assert bundle["lifecycleConsistency"] == "browser_missing"
    assert bundle["statusLine"] == "工作台窗口已关闭，后端仍在运行。"


def test_launcher_status_marks_missing_managed_window_as_partial(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "sessionRole": "workbench",
                "url": "http://127.0.0.1:8000",
                "backendPid": 10952,
                "browserManaged": True,
                "browserWindowPid": 4001,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: int(pid) in {3210, 10952})
    monkeypatch.setattr(
        launcher_service,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 3210,
            "stateVersion": 10,
            "daemonRunning": True,
            "workbench": {
                "sessionRole": "workbench",
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "url": "http://127.0.0.1:8000",
            },
        },
    )
    monkeypatch.setattr(launcher_service, "load_pid", lambda: 3210)
    monkeypatch.setattr(
        launcher_service,
        "observe_workbench",
        lambda: {
            "sessionRole": "workbench",
            "observedState": "partial",
            "backendPid": 10952,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPort": 8000,
            "backendPortListening": True,
            "backendPortConflict": False,
            "browserManaged": True,
            "browserWindowPid": 4001,
            "browserWindowAlive": False,
            "lifecycleConsistency": "browser_missing",
            "url": "http://127.0.0.1:8000",
        },
    )

    payload = launcher_service.get_launcher_status()

    bundle = payload["projectBundle"]
    assert bundle["sessionRole"] == "workbench"
    assert bundle["desiredState"] == "open"
    assert bundle["observedState"] == "partial"
    assert bundle["overallState"] == "partial"
    assert bundle["backend"]["alive"] is True
    assert bundle["browser"]["alive"] is False
    assert bundle["lifecycleConsistency"] == "browser_missing"
    assert bundle["statusLine"] == "工作台窗口已关闭，后端仍在运行。"
    assert payload["lifecycleProof"]["overallState"] == "partial"
    assert payload["lifecycleProof"]["summary"] == bundle["statusLine"]


def test_workbench_payload_keeps_failed_window_start_when_backend_is_healthy(monkeypatch):
    failure_message = "Packaged Electron exited before registering a desktop session (exit code 0)."
    runtime_state = {
        "runtimeState": "running",
        "daemonRunning": True,
        "command": {"activeCommandId": "", "activeType": ""},
        "workbench": {
            "sessionRole": "workbench",
            "desiredState": "open",
            "observedState": "open",
            "phase": "failed",
            "backendPid": 10952,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPort": 8000,
            "backendPortListening": True,
            "backendPortConflict": False,
            "browserManaged": False,
            "browserWindowAlive": False,
            "lifecycleConsistency": "consistent",
            "failureMessage": failure_message,
        },
    }
    observed = {
        "sessionRole": "workbench",
        "observedState": "open",
        "backendPid": 10952,
        "backendAlive": True,
        "backendHealthy": True,
        "backendObserved": True,
        "backendPort": 8000,
        "backendPortListening": True,
        "backendPortConflict": False,
        "browserManaged": False,
        "browserWindowAlive": False,
        "lifecycleConsistency": "consistent",
    }
    monkeypatch.setattr(launcher_service, "_desktop_session_workbench_projection", dict)
    monkeypatch.setattr(launcher_service, "_desktop_session_window_provider_projection", dict)

    payload = launcher_service._workbench_payload(
        runtime_state=runtime_state,
        observed_workbench=observed,
    )

    assert payload["phase"] == "failed"
    assert payload["failureMessage"] == failure_message
    assert payload["statusLine"] == failure_message


def test_workbench_payload_marks_missing_expected_electron_window_as_partial(monkeypatch):
    runtime_state = {
        "runtimeState": "running",
        "daemonRunning": True,
        "command": {"activeCommandId": "", "activeType": ""},
        "workbench": {
            "sessionRole": "workbench",
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
            "externalWindowOwner": "electron",
            "windowProvider": "electron",
            "backendPid": 40368,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPort": 8002,
            "backendPortListening": True,
            "backendPortConflict": False,
            "browserManaged": False,
            "windowManaged": False,
            "browserWindowAlive": False,
            "lifecycleConsistency": "consistent",
        },
    }
    observed = {
        "sessionRole": "workbench",
        "observedState": "open",
        "windowProvider": "electron",
        "backendPid": 40368,
        "backendAlive": True,
        "backendHealthy": True,
        "backendObserved": True,
        "backendPort": 8002,
        "backendPortListening": True,
        "backendPortConflict": False,
        "browserManaged": False,
        "windowManaged": False,
        "browserWindowAlive": False,
        "lifecycleConsistency": "consistent",
    }
    monkeypatch.setattr(launcher_service, "_desktop_session_workbench_projection", dict)
    monkeypatch.setattr(launcher_service, "_desktop_session_window_provider_projection", dict)

    payload = launcher_service._workbench_payload(runtime_state=runtime_state, observed_workbench=observed)

    assert payload["observedState"] == "partial"
    assert payload["phase"] == "steady"
    assert payload["windowProvider"] == "electron"
    assert payload["windowManaged"] is False
    assert payload["lifecycleConsistency"] == "browser_missing"
    assert payload["statusLine"] == "工作台窗口已关闭，后端仍在运行。"


def test_launcher_supervisor_snapshot_reports_recorded_dead_pid(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(json.dumps({"supervisorPid": 5555}), encoding="utf-8")
    monkeypatch.setattr(launcher_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(launcher_service, "_is_process_alive", lambda pid: False)

    supervisor = launcher_service._launcher_supervisor_snapshot()

    assert supervisor["pid"] == 5555
    assert supervisor["alive"] is False
    assert supervisor["status"] == "stopped"
    assert supervisor["blocking"] is False
    assert supervisor["impact"] == "non_blocking"
    assert "不影响当前项目使用" in supervisor["userMessage"]
    assert "no longer alive" in supervisor["detail"]



def test_ensure_runtime_manager_daemon_alive_reuses_current_source_daemon(monkeypatch):
    calls = []
    monkeypatch.setattr(launcher_service, "is_daemon_running", lambda: True)
    monkeypatch.setattr(launcher_service, "ensure_daemon_running", lambda: calls.append("ensure") or False)
    monkeypatch.setattr(launcher_service, "command_queue", None)
    monkeypatch.setattr(launcher_service, "_record_launcher_event", lambda *a, **k: None)

    result = launcher_service.ensure_runtime_manager_daemon_alive()

    assert result["action"] == "already_running"
    assert result["daemonRunning"] is True
    assert calls == ["ensure"]


def test_ensure_runtime_manager_daemon_alive_recycles_stale_running_daemon(monkeypatch):
    calls = []

    class FakeQueue:
        @staticmethod
        def recover_processing_queue():
            calls.append("recover")
            raise AssertionError("the replacement daemon owns startup queue recovery")

    monkeypatch.setattr(launcher_service, "is_daemon_running", lambda: True)
    monkeypatch.setattr(launcher_service, "ensure_daemon_running", lambda: calls.append("ensure") or True)
    monkeypatch.setattr(launcher_service, "command_queue", FakeQueue)
    events = []
    monkeypatch.setattr(
        launcher_service,
        "_record_launcher_event",
        lambda event_code, **kwargs: events.append(event_code),
    )

    result = launcher_service.ensure_runtime_manager_daemon_alive()

    assert result["action"] == "restarted"
    assert result["ensured"] is True
    assert result["recoveredCommandCount"] == 0
    assert calls == ["ensure"]
    assert "launcher.daemon.watchdog.restarted" in events



def _launcher_fast_cleanup_state(*, backend_pid: int = 4242, manager_pid: int = 0) -> tuple[dict, dict]:
    updated_at = datetime.now(timezone.utc).isoformat()
    workbench = {
        "desiredState": "open",
        "observedState": "open",
        "phase": "steady",
        "backendPid": backend_pid,
        "backendLaunchPid": backend_pid,
        "backendPort": 8002,
        "backendPortListening": False,
        "browserManaged": True,
        "browserProfileDir": "",
        "launcherStatePresent": True,
        "lifecycleConsistency": "consistent",
    }
    runtime_state = {
        "managerPid": manager_pid,
        "daemonRunning": bool(manager_pid),
        "stateVersion": 7,
        "updatedAt": updated_at,
        "workbench": dict(workbench),
    }
    return runtime_state, workbench



def test_ensure_runtime_manager_daemon_alive_recovers_queue_and_restarts(monkeypatch):
    calls = []
    monkeypatch.setattr(launcher_service, "is_daemon_running", lambda: False)
    monkeypatch.setattr(launcher_service, "ensure_daemon_running", lambda: calls.append("ensure") or True)

    class FakeQueue:
        @staticmethod
        def recover_processing_queue():
            calls.append("recover")
            return ["cmd_force_stop_stuck"]

    monkeypatch.setattr(launcher_service, "command_queue", FakeQueue)
    events = []
    monkeypatch.setattr(
        launcher_service,
        "_record_launcher_event",
        lambda event_code, **kwargs: events.append(event_code),
    )

    result = launcher_service.ensure_runtime_manager_daemon_alive()

    assert result["action"] == "restarted"
    assert result["ensured"] is True
    assert result["recoveredCommandCount"] == 1
    assert calls == ["recover", "ensure"]
    assert "launcher.daemon.watchdog.restarted" in events


def test_status_watchdog_recovers_stuck_restart_when_daemon_is_offline(monkeypatch):
    calls = []
    monkeypatch.setattr(
        launcher_service,
        "_recent_command_files",
        lambda path, *, limit: [
            {
                "commandId": "cmd-stuck-restart",
                "type": "restart_workbench",
            }
        ],
    )
    monkeypatch.setattr(
        launcher_service,
        "ensure_runtime_manager_daemon_alive",
        lambda: calls.append("watchdog") or {"action": "restarted", "ensured": True},
    )

    recovered = launcher_service._recover_stale_open_command_when_manager_offline(
        {"daemonRunning": False}
    )

    assert recovered is True
    assert calls == ["watchdog"]


def test_status_watchdog_does_not_start_daemon_without_stuck_open_command(monkeypatch):
    monkeypatch.setattr(
        launcher_service,
        "_recent_command_files",
        lambda path, *, limit: [{"commandId": "cmd-stop", "type": "close_workbench"}],
    )
    monkeypatch.setattr(
        launcher_service,
        "ensure_runtime_manager_daemon_alive",
        lambda: (_ for _ in ()).throw(AssertionError("watchdog must not run")),
    )

    recovered = launcher_service._recover_stale_open_command_when_manager_offline(
        {"daemonRunning": False}
    )

    assert recovered is False


def test_status_watchdog_does_not_restart_daemon_for_fresh_open_command(monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr(
        launcher_service,
        "_recent_command_files",
        lambda path, *, limit: [
            {
                "commandId": "cmd-fresh-open",
                "type": "open_workbench",
                "requestedAt": datetime.now(timezone.utc).isoformat(),
            }
        ],
    )
    monkeypatch.setattr(
        launcher_service,
        "ensure_runtime_manager_daemon_alive",
        lambda: (_ for _ in ()).throw(AssertionError("watchdog must not run for a fresh start")),
    )

    recovered = launcher_service._recover_stale_open_command_when_manager_offline(
        {"daemonRunning": False}
    )

    assert recovered is False


def test_recent_result_files_skips_file_that_disappears_during_stat(tmp_path, monkeypatch):
    surviving = tmp_path / "surviving.json"
    disappearing = tmp_path / "disappearing.json"
    surviving.write_text(json.dumps({"commandId": "surviving", "ok": True}), encoding="utf-8")
    disappearing.write_text(json.dumps({"commandId": "disappearing", "ok": False}), encoding="utf-8")
    original_stat = Path.stat

    def stat_without_disappearing(self, *args, **kwargs):
        if self == disappearing:
            raise FileNotFoundError(str(self))
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_without_disappearing)

    results = launcher_service._recent_result_files(tmp_path, limit=5)

    assert len(results) == 1
    assert results[0]["commandId"] == "surviving"


def test_ensure_runtime_manager_daemon_alive_records_recovery_failure_but_still_restarts(monkeypatch):
    calls = []

    def _fail_recover():
        calls.append("recover")
        raise OSError("queue locked")

    class FakeQueue:
        recover_processing_queue = staticmethod(_fail_recover)

    monkeypatch.setattr(launcher_service, "is_daemon_running", lambda: False)
    monkeypatch.setattr(launcher_service, "ensure_daemon_running", lambda: calls.append("ensure") or True)
    monkeypatch.setattr(launcher_service, "command_queue", FakeQueue)
    events = []
    monkeypatch.setattr(
        launcher_service,
        "_record_launcher_event",
        lambda event_code, **kwargs: events.append(event_code),
    )

    result = launcher_service.ensure_runtime_manager_daemon_alive()

    assert result["action"] == "restarted"
    assert calls == ["recover", "ensure"]
    assert "launcher.daemon.watchdog.recovery_failed" in events
    assert "launcher.daemon.watchdog.restarted" in events



# ---------------------------------------------------------------------------
# 桌面会话查询下推 / 过期行 / 清理策略 / lifecycle 初始化与 FK


def _seed_desktop_row(
    desktop_session_id: str,
    *,
    workspace_root: str,
    heartbeat_iso: str,
    status: str = "active",
    provider: str = "electron",
    windows_json: str = "{}",
) -> None:
    import sqlite3

    from core.launcher import desktop_session_store

    desktop_session_store.DESKTOP_SESSION_DB_PATH.parent.mkdir(
        parents=True, exist_ok=True
    )
    conn = sqlite3.connect(str(desktop_session_store.DESKTOP_SESSION_DB_PATH))
    try:
        desktop_session_store._init_schema(conn)
        conn.execute(
            """
            INSERT INTO desktop_sessions (
              desktop_session_id, provider, status, revision, workspace_root,
              capabilities_json, windows_json, created_at, updated_at, last_heartbeat_at
            ) VALUES (?, ?, ?, 1, ?, '[]', ?, ?, ?, ?)
            """,
            (
                desktop_session_id,
                provider,
                status,
                workspace_root,
                windows_json,
                heartbeat_iso,
                heartbeat_iso,
                heartbeat_iso,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_latest_active_session_finds_target_beyond_32_newer_rows(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from core.launcher import desktop_session_store

    now = datetime.now(timezone.utc)
    other_workspace = str(tmp_path / "other-workspace")
    target_workspace = str(tmp_path / "target-workspace")
    for index in range(40):
        _seed_desktop_row(
            f"other-{index}",
            workspace_root=other_workspace,
            heartbeat_iso=(now - timedelta(seconds=index)).isoformat(),
        )
    _seed_desktop_row(
        "target-1",
        workspace_root=target_workspace,
        heartbeat_iso=(now - timedelta(seconds=40)).isoformat(),
    )

    result = desktop_session_store.latest_active_desktop_session(
        workspace_root=target_workspace
    )

    assert result.get("desktopSessionId") == "target-1"


def test_expired_rows_do_not_shadow_valid_rows(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from core.launcher import desktop_session_store

    now = datetime.now(timezone.utc)
    workspace = str(tmp_path / "shared-workspace")
    for index in range(12):
        _seed_desktop_row(
            f"expired-{index}",
            workspace_root=workspace,
            heartbeat_iso=(now - timedelta(seconds=600 + index)).isoformat(),
            windows_json='{"workbench": {"open": true, "role": "workbench"}}',
        )
    for index in range(20):
        _seed_desktop_row(
            f"live-without-role-{index}",
            workspace_root=workspace,
            heartbeat_iso=(now - timedelta(seconds=index)).isoformat(),
        )
    _seed_desktop_row(
        "target-with-role",
        workspace_root=workspace,
        heartbeat_iso=(now - timedelta(seconds=30)).isoformat(),
        windows_json='{"workbench": {"open": true, "role": "workbench"}}',
    )

    result = desktop_session_store.latest_active_desktop_session(
        workspace_root=workspace,
        window_role="workbench",
    )

    assert result.get("desktopSessionId") == "target-with-role"


def test_desktop_schema_init_runs_once_per_process(tmp_path, monkeypatch):
    from core.launcher import desktop_session_store

    getattr(desktop_session_store, "_schema_ready", {}).clear()
    original = desktop_session_store._init_schema
    calls = []

    def counting_init(conn):
        calls.append(1)
        return original(conn)

    monkeypatch.setattr(desktop_session_store, "_init_schema", counting_init)
    for _ in range(3):
        with desktop_session_store._connect() as conn:
            conn.execute("SELECT COUNT(*) FROM desktop_sessions").fetchone()

    assert len(calls) == 1


def test_prune_keeps_leased_sessions_and_removes_stale_rows(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from core.launcher import desktop_session_store

    now = datetime.now(timezone.utc)
    _seed_desktop_row(
        "leased-live",
        workspace_root=str(tmp_path / "ws"),
        heartbeat_iso=now.isoformat(),
    )
    _seed_desktop_row(
        "closed-old",
        workspace_root=str(tmp_path / "ws"),
        heartbeat_iso=(now - timedelta(days=10)).isoformat(),
        status="closed",
    )
    _seed_desktop_row(
        "active-stale",
        workspace_root=str(tmp_path / "ws"),
        heartbeat_iso=(now - timedelta(days=31)).isoformat(),
    )

    with desktop_session_store._connect() as conn:
        desktop_session_store._prune_sessions(conn)
        remaining = {
            str(row["desktop_session_id"])
            for row in conn.execute(
                "SELECT desktop_session_id FROM desktop_sessions"
            ).fetchall()
        }

    assert remaining == {"leased-live"}


def test_lifecycle_foreign_keys_are_enforced(tmp_path, monkeypatch):
    import sqlite3

    from core.launcher import lifecycle_intent_store

    conn = lifecycle_intent_store._connect()
    try:
        enabled = int(conn.execute("PRAGMA foreign_keys").fetchone()[0])
        assert enabled == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO desktop_actions (
                  action_id, intent_id, action, status, payload_json, created_at, updated_at
                ) VALUES ('action-orphan', 'intent-missing', 'focus_workbench', 'pending', '{}', '', '')
                """
            )
    finally:
        conn.close()


def test_lifecycle_terminal_retention_prunes_only_old_terminal_rows(tmp_path, monkeypatch):
    import sqlite3

    from core.launcher import lifecycle_intent_store

    db_path = tmp_path / "launcher" / "lifecycle.sqlite3"
    monkeypatch.setattr(lifecycle_intent_store, "LIFECYCLE_DB_PATH", db_path)
    actor = {
        "actorType": "pytest",
        "actorId": "retention",
        "sourceRunId": "",
        "sourceTaskId": "",
        "sourceWorktree": "",
    }
    old_terminal = lifecycle_intent_store.submit_lifecycle_intent(
        {"action": "focus_workbench", "reason": "old", "idempotencyKey": "retention:old-action"},
        actor_context=actor,
        active_work_runs=[],
    )
    claimed = lifecycle_intent_store.claim_desktop_action(desktop_session_id="desktop-1")
    lifecycle_intent_store.ack_desktop_action(
        claimed["actionId"],
        desktop_session_id="desktop-1",
        result={"ok": True},
    )
    old_runtime = lifecycle_intent_store.submit_lifecycle_intent(
        {"action": "restart_after_apply", "reason": "old", "idempotencyKey": "retention:old-runtime"},
        actor_context=actor,
        active_work_runs=[],
    )
    lifecycle_intent_store.record_runtime_dispatch(old_runtime["intentId"], command_id="old-command")
    lifecycle_intent_store.complete_lifecycle_intent(
        old_runtime["intentId"], status="succeeded", result={"ok": True}
    )
    desktop_session = {
        "desktopSessionId": "desktop-1",
        "status": "active",
        "revision": 1,
        "capabilities": ["workbench_close.transaction.v1"],
    }
    old_transaction = lifecycle_intent_store.submit_workbench_close_transaction(
        {
            "desktopSessionId": "desktop-1",
            "idempotencyKey": "retention:old-close",
            "mode": "normal",
        },
        desktop_session=desktop_session,
        active_work_runs=[],
    )
    lifecycle_intent_store.record_workbench_close_dispatch(old_transaction["closeId"], command_id="close-old")
    lifecycle_intent_store.authorize_workbench_close_window(
        old_transaction["closeId"], result={"ok": True}
    )
    lifecycle_intent_store.complete_workbench_close_transaction(
        old_transaction["closeId"], completion_source="pytest"
    )

    pending = lifecycle_intent_store.submit_lifecycle_intent(
        {"action": "focus_workbench", "reason": "pending", "idempotencyKey": "retention:pending"},
        actor_context=actor,
        active_work_runs=[],
    )
    executing = lifecycle_intent_store.submit_lifecycle_intent(
        {"action": "restart_after_apply", "reason": "executing", "idempotencyKey": "retention:executing"},
        actor_context=actor,
        active_work_runs=[],
    )
    lifecycle_intent_store.record_runtime_dispatch(executing["intentId"], command_id="live-command")
    pending_transaction = lifecycle_intent_store.submit_workbench_close_transaction(
        {
            "desktopSessionId": "desktop-1",
            "idempotencyKey": "retention:pending-close",
            "mode": "normal",
        },
        desktop_session=desktop_session,
        active_work_runs=[{"runId": "active"}],
    )

    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE lifecycle_intents SET updated_at = ?, completed_at = ? WHERE intent_id IN (?, ?)",
            (old, old, old_terminal["intentId"], old_runtime["intentId"]),
        )
        conn.execute(
            "UPDATE desktop_actions SET updated_at = ? WHERE action_id = ?",
            (old, claimed["actionId"]),
        )
        conn.execute(
            "UPDATE workbench_close_transactions SET updated_at = ? WHERE close_id = ?",
            (old, old_transaction["closeId"]),
        )
        conn.execute(
            "UPDATE lifecycle_store_meta SET value = '0' WHERE key = 'terminal_pruned_at'"
        )

    lifecycle_intent_store.submit_lifecycle_intent(
        {"action": "focus_workbench", "reason": "trigger", "idempotencyKey": "retention:trigger"},
        actor_context=actor,
        active_work_runs=[],
    )

    with sqlite3.connect(db_path) as conn:
        intent_ids = {row[0] for row in conn.execute("SELECT intent_id FROM lifecycle_intents")}
        action_ids = {row[0] for row in conn.execute("SELECT action_id FROM desktop_actions")}
        close_ids = {row[0] for row in conn.execute("SELECT close_id FROM workbench_close_transactions")}

    assert old_terminal["intentId"] not in intent_ids
    assert old_runtime["intentId"] not in intent_ids
    assert claimed["actionId"] not in action_ids
    assert old_transaction["closeId"] not in close_ids
    assert pending["intentId"] in intent_ids
    assert executing["intentId"] in intent_ids
    assert pending_transaction["closeId"] in close_ids


def test_lifecycle_concurrent_first_init_is_idempotent(tmp_path, monkeypatch):
    import threading

    from core.launcher import lifecycle_intent_store

    getattr(lifecycle_intent_store, "_schema_ready", {}).clear()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            conn = lifecycle_intent_store._connect()
            try:
                conn.execute("SELECT COUNT(*) FROM lifecycle_intents").fetchone()
            finally:
                conn.close()
        except BaseException as exc:  # noqa: BLE001 - test collects all failures
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
