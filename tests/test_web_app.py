import base64
import copy
import json
import shutil
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.evaluation.chat_next_state_signals import append_chat_next_state_signal, list_chat_next_state_signals
from core.evaluation.chat_dataset_capture import ChatDatasetCaptureService, resolve_chat_dataset_paths
from core.evaluation.chat_segmenter import ChatTurnRecord
from core.evaluation.self_evolution_candidate_pool import append_candidate_record
from config.public_config import UNCONFIGURED_MODEL_REF, load_public_config, public_config_hash
from core.gym import run_gym_collection_episode
from core.gym.promotion import (
    activate_gym_promotion_proposal,
    apply_gym_promotion_proposal,
    rollback_gym_promotion_proposal,
)
from core.web import app as web_app
from core.chat.slash_commands import parse_skill_slash_command
from core.ui.chat_state import load_chat_state, save_chat_state
from core.runtime_manager import constants as runtime_manager_constants
from core.runtime_manager.work_run_store import WorkRunStore
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    agent_mode_binding_service,
    agent_directory_service,
    chat_room_service,
    chat_review_service,
    config_service,
    evolution_service,
    log_service,
    runtime_service,
    runtime_scene_service,
    session_service,
    skill_service,
    self_evolution_control_service,
    self_evolution_service,
    supervised_agent_service,
    supervised_control_service,
    supervised_worktree_evolution_service,
    workbench_contract_service,
)
import core.web.services.avatar_image_service as avatar_image_service
from tests.test_gym_runner import RunnerFakeAdapter


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.fixture(autouse=True)
def disable_runtime_manager_live_control(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervised_control_service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "_runtime_manager_live_control_enabled", lambda: False)


def _read_first_sse_event(response):
    event_name = ""
    data_lines = []
    for line in response.iter_lines():
        if line.startswith("event: "):
            event_name = line[len("event: ") :]
            continue
        if line.startswith("data: "):
            data_lines.append(line[len("data: ") :])
            continue
        if line == "":
            if event_name or data_lines:
                return {
                    "event": event_name,
                    "data": "\n".join(data_lines),
                }
    raise AssertionError("Expected at least one SSE event")


def _real_runtime_manager_evolution_paths(kind: str, run_id: str) -> tuple[Path, Path]:
    root = runtime_manager_constants.PROJECT_ROOT / ".runtime" / "runtime-manager" / "evolution" / kind
    return root / "runs" / f"{run_id}.json", root / "index.json"


def _read_optional_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _restore_real_runtime_index_if_touched(kind: str, run_id: str, original_index_text: str | None) -> None:
    run_path, index_path = _real_runtime_manager_evolution_paths(kind, run_id)
    if run_path.exists():
        run_path.unlink()
    if index_path.exists() and run_id in index_path.read_text(encoding="utf-8"):
        if original_index_text is None:
            index_path.unlink()
        else:
            index_path.write_text(original_index_text, encoding="utf-8")


def test_web_control_token_endpoint_is_local_and_required_for_mutations():
    guarded_client = TestClient(create_app())

    token_response = guarded_client.get("/api/control-token")
    assert token_response.status_code == 200
    token_payload = token_response.json()
    assert token_payload["header"] == CONTROL_TOKEN_HEADER
    assert token_payload["controlToken"]

    read_response = guarded_client.get("/api/health")
    assert read_response.status_code == 200

    rejected_response = guarded_client.post("/api/runtime/shutdown")
    assert rejected_response.status_code == 403
    assert "control token" in rejected_response.json()["detail"]

    accepted_client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: token_payload["controlToken"]})
    accepted_response = accepted_client.post(
        "/api/runtime/browser-telemetry",
        json={"phase": "page", "eventCode": "probe", "message": "accepted"},
    )
    assert accepted_response.status_code == 202


def test_web_control_guard_rejects_untrusted_origin_even_with_token():
    guarded_client = TestClient(create_app())

    response = guarded_client.post(
        "/api/runtime/browser-telemetry",
        headers={
            CONTROL_TOKEN_HEADER: get_control_token(),
            "Origin": "https://example.invalid",
        },
        json={"phase": "page", "eventCode": "probe", "message": "blocked"},
    )

    assert response.status_code == 403
    assert "origin" in response.json()["detail"].lower()


def test_web_control_token_endpoint_rejects_untrusted_origin():
    guarded_client = TestClient(create_app())

    response = guarded_client.get(
        "/api/control-token",
        headers={"Origin": "https://example.invalid"},
    )

    assert response.status_code == 403
    assert "origin" in response.json()["detail"].lower()


def test_static_assets_allow_same_origin_referer_on_custom_port(tmp_path, monkeypatch):
    dist_dir = tmp_path / "web-dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<!doctype html><html><body>app</body></html>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")

    monkeypatch.setattr("core.web.app.WEB_DIST", dist_dir)
    temp_client = TestClient(create_app(), base_url="http://127.0.0.1:8012")

    response = temp_client.get("/assets/app.js", headers={"Referer": "http://127.0.0.1:8012/"})

    assert response.status_code == 200, response.text
    assert "console.log" in response.text


def test_static_assets_reject_cross_origin_referer(tmp_path, monkeypatch):
    dist_dir = tmp_path / "web-dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<!doctype html><html><body>app</body></html>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")

    monkeypatch.setattr("core.web.app.WEB_DIST", dist_dir)
    temp_client = TestClient(create_app(), base_url="http://127.0.0.1:8012")

    response = temp_client.get("/assets/app.js", headers={"Referer": "https://example.invalid/"})

    assert response.status_code == 403
    assert "referer" in response.json()["detail"].lower()


def _seed_runtime_scene_bundle(project_root: Path, scene_id: str = "scene-1", status: str = "stopped") -> Path:
    scene_dir = project_root / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}"
    events_dir = scene_dir / "events"
    raw_dir = scene_dir / "raw"
    events_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime_scene_id": scene_id,
                "title": f"Managed workbench run {scene_id}",
                "package": {
                    "schema_version": 2,
                    "timeline_path": "timeline.jsonl",
                    "lifecycle_path": "lifecycle.jsonl",
                    "raw_dir": "raw",
                    "conversations_dir": "conversations",
                    "agent_dir": "agent",
                    "artifacts_dir": "artifacts",
                },
                "started_at": "2026-05-18T12:00:00Z",
                "ended_at": "" if status == "running" else "2026-05-18T12:03:00Z",
                "status": status,
                "result": "" if status == "running" else "explicit_stop",
                "stop_reason": "" if status == "running" else "explicit stop",
                "trigger": "start",
                "session_mode": "managed",
                "project_root": str(project_root),
                "host": "127.0.0.1",
                "port": 8000,
                "url": "http://127.0.0.1:8000",
                "frontend": {
                    "build_status": "success",
                    "build_reason": "frontend sources changed",
                    "log_path": "raw/frontend.build.log",
                },
                "backend": {
                    "pid": 12345,
                    "health_status": "stopped",
                    "stdout_path": "raw/backend.stdout.log",
                    "stderr_path": "raw/backend.stderr.log",
                },
                "browser": {
                    "managed": True,
                    "status": "stopped",
                    "log_path": "raw/browser.log",
                    "launch_pid": 222,
                    "window_pid": 333,
                },
                "supervisor": {
                    "pid": 444,
                    "status": "stopped",
                    "log_path": "raw/supervisor.log",
                    "stderr_path": "raw/supervisor.stderr.log",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (events_dir / "frontend.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "runtime_scene_id": scene_id,
                        "ts": "2026-05-18T12:00:01Z",
                        "seq": 1,
                        "component": "frontend",
                        "phase": "build",
                        "event_code": "frontend.build.started",
                        "level": "info",
                        "outcome": "started",
                        "message": "Starting frontend build.",
                        "fields": {"reason": "frontend sources changed"},
                        "raw_refs": [{"path": "raw/frontend.build.log", "tail_lines": 40}],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "runtime_scene_id": scene_id,
                        "ts": "2026-05-18T12:00:03Z",
                        "seq": 2,
                        "component": "frontend",
                        "phase": "build",
                        "event_code": "frontend.build.succeeded",
                        "level": "info",
                        "outcome": "succeeded",
                        "message": "Frontend build completed successfully.",
                        "fields": {"output": "web/dist/index.html"},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "runtime_scene_id": scene_id,
                        "ts": "2026-05-18T12:00:04Z",
                        "seq": 3,
                        "component": "frontend",
                        "phase": "build",
                        "event_code": "frontend.build.cache_warning",
                        "level": "warning",
                        "outcome": "succeeded",
                        "message": "Frontend build cache was cold.",
                        "fields": {},
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (events_dir / "backend.jsonl").write_text(
        json.dumps(
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:05Z",
                "seq": 1,
                "component": "backend",
                "phase": "health",
                "event_code": "backend.health.succeeded",
                "level": "info",
                "outcome": "succeeded",
                "message": "Backend passed health checks.",
                "fields": {"pid": 12345, "url": "http://127.0.0.1:8000"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (events_dir / "supervisor.jsonl").write_text(
        json.dumps(
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:06Z",
                "seq": 1,
                "component": "supervisor",
                "phase": "session",
                "event_code": "supervisor.unexpected_exit",
                "level": "info",
                "outcome": "failed",
                "message": "Supervisor exited unexpectedly.",
                "fields": {"errorType": "SupervisorExited"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (raw_dir / "frontend.build.log").write_text("vite build ok\n", encoding="utf-8")
    (raw_dir / "backend.stdout.log").write_text("uvicorn started\n", encoding="utf-8")
    (raw_dir / "backend.stderr.log").write_text("", encoding="utf-8")
    (raw_dir / "supervisor.log").write_text("supervisor ok\n", encoding="utf-8")
    (raw_dir / "supervisor.stderr.log").write_text("", encoding="utf-8")
    (raw_dir / "browser.log").write_text("browser open\n", encoding="utf-8")
    timeline_payloads = [
        line
        for path in sorted(events_dir.glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    (scene_dir / "timeline.jsonl").write_text("\n".join(timeline_payloads) + "\n", encoding="utf-8")
    (scene_dir / "lifecycle.jsonl").write_text("\n".join(timeline_payloads) + "\n", encoding="utf-8")
    return scene_dir


def _runtime_scene_local_index_parts(iso_value: str) -> tuple[str, str, str]:
    parsed = datetime.fromisoformat(iso_value.replace("Z", "+00:00")).astimezone()
    return parsed.strftime("%Y-%m-%d"), parsed.strftime("%H:%M:%S"), parsed.strftime("%H-%M-%S")


def test_runtime_summary_shape():
    response = client.get("/api/runtime/summary")
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["agentName"] == "Vibelution"
    assert isinstance(payload["userName"], str)
    assert "userProfile" in payload
    assert set(payload["userProfile"]) == {"displayName", "bio", "preferences", "avatarPreset", "avatarImageUrl"}
    assert "mode" in payload
    assert "profile" in payload
    assert "sessionState" in payload
    assert "sessionStateLine" in payload
    assert "sessionNeedsResponse" in payload
    assert "sessionUpdatedAt" in payload
    assert "mentalState" in payload
    assert "runtimeManager" in payload
    assert "contextCompression" in payload
    assert "strategy" in payload["contextCompression"]
    assert [item["level"] for item in payload["contextCompression"]["strategy"]["levels"]] == [
        "light",
        "standard",
        "deep",
        "emergency",
    ]
    assert "workbench" in payload
    assert "workRuns" in payload
    assert "lifecycleProof" in payload
    assert "overallState" in payload["lifecycleProof"]
    assert "components" in payload["lifecycleProof"]


def test_runtime_summary_prefers_configured_user_profile(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["user_profile"] = {
        "display_name": "Vibe Owner",
        "bio": "Prefers direct operational summaries.",
        "preferences": ["Keep answers compact", "Mention validation evidence"],
        "avatar_preset": "codex",
        "avatar_image_path": "workspace/user_avatars/avatar-test.png",
    }
    monkeypatch.setattr(runtime_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(runtime_service, "_local_user_name", lambda: "os-user")

    payload = runtime_service.get_runtime_summary()

    assert payload["userName"] == "Vibe Owner"
    assert payload["userProfile"] == {
        "displayName": "Vibe Owner",
        "bio": "Prefers direct operational summaries.",
        "preferences": ["Keep answers compact", "Mention validation evidence"],
        "avatarPreset": "codex",
        "avatarImageUrl": "/api/config/avatar-image/avatar-test.png",
    }


def test_runtime_summary_ignores_unsafe_user_avatar_path(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["user_profile"] = {
        "display_name": "Vibe Owner",
        "avatar_preset": "codex",
        "avatar_image_path": "../outside.png",
    }
    monkeypatch.setattr(runtime_service, "load_public_config", lambda: copy.deepcopy(public_config))

    payload = runtime_service.get_runtime_summary()

    assert payload["userProfile"]["avatarImageUrl"] == ""


def test_runtime_summary_exposes_real_context_compression_snapshot(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "current_context_tokens": 7000,
            "context_token_limit": 12000,
            "updated_at": "2026-05-25T10:00:00",
            "context_compression": {
                "enabled": True,
                "effectiveTokenLimit": 12000,
                "contextWindowLimit": 24000,
                "compressionCount": 2,
                "updatedAt": "2026-05-25T10:01:00",
                "lastCompression": {
                    "level": "standard",
                    "reason": "测试压缩",
                    "beforeTokens": 13000,
                    "afterTokens": 6200,
                    "savedTokens": 6800,
                    "iteration": 8,
                    "summaryWritten": True,
                    "timestamp": "2026-05-25T10:01:00",
                },
            },
        },
    )

    payload = runtime_service.get_runtime_summary()
    compression = payload["contextCompression"]

    assert compression["currentTokens"] == 7000
    assert compression["effectiveTokenLimit"] == 12000
    assert compression["contextWindowLimit"] == 24000
    assert compression["usageRatio"] == pytest.approx(0.5833)
    assert compression["compressionCount"] == 2
    assert compression["lastCompression"]["level"] == "standard"
    assert compression["lastCompression"]["summaryWritten"] is True
    assert compression["strategy"]["levels"][0]["thresholdTokens"] == 7200


def test_ignores_windows_proactor_disconnect_noise(monkeypatch):
    monkeypatch.setattr(web_app.os, "name", "nt", raising=False)

    context = {
        "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)",
        "exception": ConnectionResetError(10054, "connection reset"),
        "handle": "<Handle _ProactorBasePipeTransport._call_connection_lost(None)>",
    }

    assert web_app._is_windows_proactor_disconnect_noise(context) is True


def test_keeps_non_proactor_or_non_windows_disconnects_visible(monkeypatch):
    monkeypatch.setattr(web_app.os, "name", "nt", raising=False)

    assert web_app._is_windows_proactor_disconnect_noise(
        {
            "message": "Exception in callback some_other_handle",
            "exception": ConnectionResetError(10054, "connection reset"),
            "handle": "<Handle some_other_handle>",
        }
    ) is False

    monkeypatch.setattr(web_app.os, "name", "posix", raising=False)
    assert web_app._is_windows_proactor_disconnect_noise(
        {
            "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)",
            "exception": ConnectionResetError(10054, "connection reset"),
            "handle": "<Handle _ProactorBasePipeTransport._call_connection_lost(None)>",
        }
    ) is False


def test_runtime_shutdown_queues_runtime_manager_when_state_exists(tmp_path, monkeypatch):
    script_path = tmp_path / "vibelution_launcher.ps1"
    script_path.write_text("Write-Host managed\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    calls: list[object] = []
    scene_events: list[tuple[str, str, str, dict]] = []

    def record_scene_event(component, phase, event_code, **kwargs):
        scene_events.append((component, phase, event_code, kwargs))
        return {"accepted": True}

    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", script_path)
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", state_path)
    monkeypatch.setattr(runtime_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(runtime_service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(runtime_service, "record_runtime_scene_event", record_scene_event, raising=False)
    monkeypatch.setattr(runtime_service, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)),
    )

    response = client.post("/api/runtime/shutdown")

    assert response.status_code == 202
    assert response.json()["accepted"] is True
    assert response.json()["mode"] == "runtime_manager"
    assert response.json()["chatTurns"] == []
    assert calls[0] == "ensure"
    assert calls[1] == (
        "close_workbench",
        {"reason": "web_close_button", "source": "web_ui", "stopManager": True},
        "web_ui",
    )
    event_codes = [item[2] for item in scene_events]
    assert "runtime.shutdown.requested" in event_codes
    assert "runtime.shutdown.accepted" in event_codes
    accepted_event = next(item for item in scene_events if item[2] == "runtime.shutdown.accepted")
    assert accepted_event[1] == "shutdown"
    assert accepted_event[3]["lifecycle"] is True
    assert accepted_event[3]["fields"]["mode"] == "runtime_manager"
    assert accepted_event[3]["fields"]["chatTurnCount"] == 0


def test_runtime_restart_queues_runtime_manager_and_records_lifecycle(monkeypatch):
    calls: list[object] = []
    scene_events: list[tuple[str, str, str, dict]] = []

    def record_scene_event(component, phase, event_code, **kwargs):
        scene_events.append((component, phase, event_code, kwargs))
        return {"accepted": True}

    monkeypatch.setattr(runtime_service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(runtime_service, "record_runtime_scene_event", record_scene_event, raising=False)
    monkeypatch.setattr(runtime_service, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by))
        or {"commandId": "cmd-restart-web"},
    )

    response = client.post("/api/runtime/restart")

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["mode"] == "runtime_manager"
    assert payload["commandId"] == "cmd-restart-web"
    assert payload["chatTurns"] == []
    assert calls == [
        "ensure",
        (
            "restart_workbench",
            {"reason": "web_restart_button", "source": "web_ui", "noBrowser": False},
            "web_ui",
        ),
    ]
    event_codes = [item[2] for item in scene_events]
    assert "runtime.restart.requested" in event_codes
    assert "runtime.restart.accepted" in event_codes
    accepted_event = next(item for item in scene_events if item[2] == "runtime.restart.accepted")
    assert accepted_event[1] == "restart"
    assert accepted_event[3]["lifecycle"] is True
    assert accepted_event[3]["fields"]["mode"] == "runtime_manager"
    assert accepted_event[3]["fields"]["commandId"] == "cmd-restart-web"


def test_runtime_restart_releases_active_work_before_manager_restart(monkeypatch):
    calls: list[object] = []
    self_calls: list[str] = []
    supervised_calls: list[str] = []
    worktree_calls: list[str] = []

    def fail_stop(session_id):
        raise RuntimeError(f"stop failed for {session_id}")

    monkeypatch.setattr(
        runtime_service,
        "list_active_session_work_runs",
        lambda: [{"sessionId": "session-live", "runId": "chat-turn-live", "status": "running"}],
    )
    monkeypatch.setattr(runtime_service, "request_stop_session_turn", fail_stop)
    monkeypatch.setattr(runtime_service, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by))
        or {"commandId": "cmd-restart-web"},
    )
    monkeypatch.setattr(
        runtime_service,
        "_force_cancel_self_evolution_for_shutdown",
        lambda reason: self_calls.append(reason) or [{"runId": "web-self-active", "status": "cancelled"}],
    )
    monkeypatch.setattr(
        runtime_service,
        "_force_cancel_supervised_evolution_for_shutdown",
        lambda reason: supervised_calls.append(reason) or [{"runId": "web-supervised-active", "status": "cancelled"}],
    )
    monkeypatch.setattr(
        runtime_service,
        "_force_cancel_supervised_worktree_evolution_for_shutdown",
        lambda reason: worktree_calls.append(reason) or [{"runId": "web-worktree-active", "status": "cancelled"}],
        raising=False,
    )

    response = client.post("/api/runtime/restart")

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["chatTurns"][0]["sessionId"] == "session-live"
    assert payload["chatTurns"][0]["status"] == "failed"
    assert "RuntimeError" in payload["chatTurns"][0]["error"]
    assert payload["evolutionRuns"] == [
        {"kind": "self_evolution_run", "runId": "web-self-active", "status": "cancelled"},
        {"kind": "supervised_evolution_run", "runId": "web-supervised-active", "status": "cancelled"},
        {"kind": "supervised_worktree_evolution_run", "runId": "web-worktree-active", "status": "cancelled"},
    ]
    assert self_calls
    assert supervised_calls
    assert worktree_calls
    assert calls[-1] == (
        "restart_workbench",
        {"reason": "web_restart_button", "source": "web_ui", "noBrowser": False},
        "web_ui",
    )


def test_runtime_shutdown_stops_active_chat_turn_before_manager_close(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    script_path = tmp_path / "vibelution_launcher.ps1"
    script_path.write_text("Write-Host managed\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    calls: list[object] = []

    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", script_path)
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", state_path)
    monkeypatch.setattr(runtime_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(runtime_service, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)),
    )

    try:
        submit_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "关闭前保存当前对话现场"},
        )
        assert submit_response.status_code == 202
        turn_control = session_service._get_session_turn_control("session-live")
        assert turn_control is not None
        session_service._set_session_live_output(
            "session-live",
            turn_id=turn_control.turn_id,
            thought="关闭前已经捕获到思考片段。",
            content="当前回答已经输出了一半。",
            tool_calls=[{"name": "read_file_tool", "status": "done", "summary": "runtime_service.py"}],
        )

        response = client.post("/api/runtime/shutdown")

        assert response.status_code == 202
        payload = response.json()
        assert payload["accepted"] is True
        assert payload["mode"] == "runtime_manager"
        assert payload["chatTurns"] == [
            {"sessionId": "session-live", "runId": turn_control.turn_id, "status": "stopped"}
        ]
        assert calls == [
            "ensure",
            (
                "close_workbench",
                {"reason": "web_close_button", "source": "web_ui", "stopManager": True},
                "web_ui",
            ),
        ]

        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["currentPhase"] == "ready"
        assert detail["messages"][-1]["role"] == "assistant"
        assert "当前回答已经输出了一半" in detail["messages"][-1]["content"]
        assert "本轮已按请求停止" in detail["messages"][-1]["content"]
        assert detail["messages"][-1]["thought"] == "关闭前已经捕获到思考片段。"
        assert detail["messages"][-1]["toolCalls"][0]["name"] == "read_file_tool"
        assert session_service.load_chat_turn_work_run_summary()["active"] is None
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_runtime_shutdown_stops_active_chat_room_round_before_manager_close(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    script_path = tmp_path / "vibelution_launcher.ps1"
    script_path.write_text("Write-Host managed\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    calls: list[object] = []

    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", script_path)
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", state_path)
    monkeypatch.setattr(runtime_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(runtime_service, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)),
    )
    monkeypatch.setattr(runtime_service, "list_active_session_work_runs", lambda: [])

    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    room = chat_room_service.create_chat_room(
        title="关闭前群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
        config={"maxSpeakers": 1},
    )
    room_started = threading.Event()
    release_room = threading.Event()

    def blocking_runner(participant, prompt, context):
        room_started.set()
        assert release_room.wait(2.0)
        return {
            "status": "completed",
            "raw_output": "room done",
            "summary": "room done",
        }

    room_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pytest-runtime-shutdown-room")
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", room_executor)
    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "关闭前保存群聊现场",
        agent_runner=blocking_runner,
        background=True,
    )
    round_id = detail["activeRoundId"]
    assert round_id
    assert room_started.wait(1.0)

    try:
        response = client.post("/api/runtime/shutdown")

        assert response.status_code == 202
        payload = response.json()
        assert payload["accepted"] is True
        assert payload["mode"] == "runtime_manager"
        assert payload["chatRoomRounds"] == [
            {
                "kind": "chat_room_round",
                "roomId": room["roomId"],
                "runId": round_id,
                "roundId": round_id,
                "status": "stopped",
            }
        ]
        final_detail = chat_room_service.get_chat_room_detail(room["roomId"])
        assert final_detail["status"] == "ready"
        assert final_detail["activeRoundId"] == ""
        assert final_detail["rounds"][-1]["status"] == "stopped"
        assert chat_room_service.load_chat_room_work_run_summary()["active"] is None
        assert calls == [
            "ensure",
            (
                "close_workbench",
                {"reason": "web_close_button", "source": "web_ui", "stopManager": True},
                "web_ui",
            ),
        ]
    finally:
        release_room.set()
        room_executor.shutdown(wait=True, cancel_futures=True)


def test_runtime_shutdown_releases_active_evolution_runs_before_manager_close(tmp_path, monkeypatch):
    script_path = tmp_path / "vibelution_launcher.ps1"
    script_path.write_text("Write-Host managed\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    calls: list[object] = []
    self_calls: list[str] = []
    supervised_calls: list[str] = []
    worktree_calls: list[str] = []

    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", script_path)
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", state_path)
    monkeypatch.setattr(runtime_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(runtime_service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(runtime_service, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)),
    )
    monkeypatch.setattr(
        runtime_service,
        "_force_cancel_self_evolution_for_shutdown",
        lambda reason: self_calls.append(reason) or [{"runId": "web-self-active", "status": "cancelled"}],
    )
    monkeypatch.setattr(
        runtime_service,
        "_force_cancel_supervised_evolution_for_shutdown",
        lambda reason: supervised_calls.append(reason) or [{"runId": "web-supervised-active", "status": "cancelled"}],
    )
    monkeypatch.setattr(
        runtime_service,
        "_force_cancel_supervised_worktree_evolution_for_shutdown",
        lambda reason: worktree_calls.append(reason) or [{"runId": "web-worktree-active", "status": "cancelled"}],
        raising=False,
    )

    response = client.post("/api/runtime/shutdown")

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["mode"] == "runtime_manager"
    assert payload["evolutionRuns"] == [
        {"kind": "self_evolution_run", "runId": "web-self-active", "status": "cancelled"},
        {"kind": "supervised_evolution_run", "runId": "web-supervised-active", "status": "cancelled"},
        {"kind": "supervised_worktree_evolution_run", "runId": "web-worktree-active", "status": "cancelled"},
    ]
    assert self_calls
    assert supervised_calls
    assert worktree_calls
    assert calls == [
        "ensure",
        (
            "close_workbench",
            {"reason": "web_close_button", "source": "web_ui", "stopManager": True},
            "web_ui",
        ),
    ]


def test_runtime_shutdown_continues_when_chat_stop_fails(tmp_path, monkeypatch):
    script_path = tmp_path / "vibelution_launcher.ps1"
    script_path.write_text("Write-Host managed\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    calls: list[object] = []

    def fail_stop(session_id):
        raise RuntimeError(f"stop failed for {session_id}")

    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", script_path)
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", state_path)
    monkeypatch.setattr(runtime_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        runtime_service,
        "list_active_session_work_runs",
        lambda: [{"sessionId": "session-live", "runId": "chat-turn-live", "status": "running"}],
    )
    monkeypatch.setattr(runtime_service, "request_stop_session_turn", fail_stop)
    monkeypatch.setattr(runtime_service, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by)),
    )

    response = client.post("/api/runtime/shutdown")

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["mode"] == "runtime_manager"
    assert payload["chatTurns"][0]["sessionId"] == "session-live"
    assert payload["chatTurns"][0]["runId"] == "chat-turn-live"
    assert payload["chatTurns"][0]["status"] == "failed"
    assert "RuntimeError" in payload["chatTurns"][0]["error"]
    assert calls == [
        "ensure",
        (
            "close_workbench",
            {"reason": "web_close_button", "source": "web_ui", "stopManager": True},
            "web_ui",
        ),
    ]


def test_runtime_shutdown_falls_back_to_launcher_stop_when_manager_queue_fails(tmp_path, monkeypatch):
    script_path = tmp_path / "vibelution_launcher.ps1"
    script_path.write_text("Write-Host managed\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", script_path)
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", state_path)
    monkeypatch.setattr(runtime_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(runtime_service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(runtime_service, "ensure_daemon_running", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(runtime_service, "_spawn_managed_launcher_shutdown", lambda: calls.append("fallback"))

    response = client.post("/api/runtime/shutdown")

    assert response.status_code == 202
    assert response.json()["accepted"] is True
    assert response.json()["mode"] == "managed_fallback"
    assert response.json()["chatTurns"] == []
    assert calls == ["fallback"]


def test_runtime_shutdown_falls_back_to_local_exit_when_not_managed(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", Path("missing-launcher.ps1"))
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", Path("missing-state.json"))
    monkeypatch.setattr(runtime_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(runtime_service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(runtime_service, "_schedule_local_backend_exit", lambda delay_seconds=0.35: calls.append("local"))

    response = client.post("/api/runtime/shutdown")

    assert response.status_code == 202
    assert response.json()["accepted"] is True
    assert response.json()["mode"] == "local"
    assert response.json()["chatTurns"] == []
    assert calls == ["local"]


def test_runtime_scene_endpoints_list_detail_content_and_delete(tmp_path, monkeypatch):
    _seed_runtime_scene_bundle(tmp_path, scene_id="scene-a")
    _seed_runtime_scene_bundle(tmp_path, scene_id="scene-b")
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    list_response = client.get("/api/logs/runtime-scenes")
    assert list_response.status_code == 200
    scenes = list_response.json()
    assert {item["runtimeSceneId"] for item in scenes} == {"scene-a", "scene-b"}
    scene_a = next(item for item in scenes if item["runtimeSceneId"] == "scene-a")
    local_date, local_time, local_time_key = _runtime_scene_local_index_parts("2026-05-18T12:00:00Z")
    assert scene_a["displayName"] != "scene-a"
    assert scene_a["packageIndex"]["packageId"] == "scene-a"
    assert scene_a["packageIndex"]["displayName"] == scene_a["displayName"]
    assert scene_a["packageIndex"]["startedDate"] == local_date
    assert scene_a["packageIndex"]["startedTime"] == local_time
    assert scene_a["packageIndex"]["durationSeconds"] == 180
    assert scene_a["packageIndex"]["indexKey"] == f"{local_date}_{local_time_key}_workbench-start_manual-stop"
    assert "scene-a" in scene_a["packageIndex"]["searchText"]
    assert local_date in scene_a["packageIndex"]["searchText"]
    assert "workbench-lifecycle" in scene_a["packageIndex"]["tags"]
    assert "工作台启动" in scene_a["displayName"]
    assert "手动停止" in scene_a["displayName"]
    assert scenes[0]["eventCount"] >= 3
    assert scenes[0]["rawLogCount"] >= 5
    assert scene_a["eventLogCount"] == 3
    assert scene_a["warningCount"] == 1
    assert scene_a["errorCount"] == 1

    detail_response = client.get("/api/logs/runtime-scenes/scene-a")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["runtimeSceneId"] == "scene-a"
    assert detail["displayName"] == scene_a["displayName"]
    assert detail["packageIndex"] == scene_a["packageIndex"]
    assert detail["status"] == "stopped"
    assert detail["frontend"]["build_status"] == "success"
    assert detail["timeline"][0]["eventCode"] == "frontend.build.started"
    assert any(item["eventCode"] == "backend.health.succeeded" for item in detail["timeline"])
    assert detail["timeline"][-1]["eventCode"] == "supervisor.unexpected_exit"
    assert any(item["path"] == "raw/backend.stdout.log" for item in detail["rawFiles"])
    assert [item["path"] for item in detail["eventLogs"]] == [
        "events/backend.jsonl",
        "events/frontend.jsonl",
        "events/supervisor.jsonl",
    ]
    assert detail["packageSummary"]["schemaVersion"] == 2
    assert detail["packageSummary"]["lifecycleEventCount"] >= 3
    assert detail["packageSummary"]["eventLogCount"] == 3
    assert detail["packageSummary"]["warningCount"] == 1
    assert detail["packageSummary"]["errorCount"] == 1
    assert detail["lifecycle"][0]["eventCode"] == "backend.health.succeeded" or detail["lifecycle"][0]["eventCode"].startswith("frontend.")

    content_response = client.get(
        "/api/logs/runtime-scenes/scene-a/content",
        params={"path": "raw/backend.stdout.log"},
    )
    assert content_response.status_code == 200
    content_payload = content_response.json()
    assert content_payload["rootId"] == "runtime_scenes"
    assert content_payload["relativePath"] == "raw/backend.stdout.log"
    assert "uvicorn started" in content_payload["content"]
    assert content_payload["diagnostics"]["severity"] == "info"
    assert content_payload["diagnostics"]["agentHint"] == "runtime_scenes/scene-a/raw/backend.stdout.log; severity=info"

    event_response = client.get(
        "/api/logs/runtime-scenes/scene-a/content",
        params={"path": "events/backend.jsonl"},
    )
    assert event_response.status_code == 200
    assert event_response.json()["relativePath"] == "events/backend.jsonl"

    delete_response = client.post(
        "/api/logs/runtime-scenes/delete",
        json={"sceneIds": ["scene-a"]},
    )
    assert delete_response.status_code == 200
    delete_payload = delete_response.json()
    assert delete_payload["deletedCount"] == 1
    assert delete_payload["deletedSceneIds"] == ["scene-a"]
    assert not (tmp_path / "logs" / "runtime_scenes" / "20260518T120000Z__scene-a").exists()
    assert (tmp_path / "logs" / "runtime_scenes" / "20260518T120000Z__scene-b").exists()


def test_runtime_scene_endpoints_read_timeline_package_without_legacy_events(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-package-only")
    shutil.rmtree(scene_dir / "events")
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)

    list_response = client.get("/api/logs/runtime-scenes")
    assert list_response.status_code == 200
    [summary] = list_response.json()
    local_date, _, local_time_key = _runtime_scene_local_index_parts("2026-05-18T12:00:00Z")
    assert summary["runtimeSceneId"] == "scene-package-only"
    assert summary["eventCount"] >= 3
    assert summary["packageIndex"]["startedDate"] == local_date
    assert summary["packageIndex"]["indexKey"] == f"{local_date}_{local_time_key}_workbench-start_manual-stop"

    detail_response = client.get("/api/logs/runtime-scenes/scene-package-only")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["timeline"][0]["eventCode"] == "frontend.build.started"
    assert any(item["eventCode"] == "backend.health.succeeded" for item in detail["timeline"])
    assert detail["packageSummary"]["eventCount"] >= 3
    assert detail["packageSummary"]["lifecycleEventCount"] >= 3
    assert detail["packageSummary"]["eventLogCount"] == 0
    assert detail["eventLogs"] == []
    assert "scene-package-only" in detail["packageIndex"]["searchText"]


def test_agent_runtime_evidence_api_returns_matching_runtime_scene_events(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-agent-evidence")
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    from core.web.services import agent_directory_service

    agent = agent_directory_service.create_agent_instance(
        display_name="证据 Agent",
        direct_session_id="session-evidence",
    )
    evidence_event = {
        "runtime_scene_id": "scene-agent-evidence",
        "ts": "2026-05-18T12:00:07Z",
        "seq": 1,
        "component": "agent_directory",
        "phase": "message",
        "event_code": "agent.message.consumed",
        "level": "info",
        "outcome": "succeeded",
        "message": "Agent message consumed.",
        "fields": {
            "agentId": agent["agentId"],
            "sessionId": "session-evidence",
            "runId": "run-evidence",
        },
        "raw_refs": [{"path": "events/agent_directory.jsonl", "tail_lines": 80}],
    }
    with (scene_dir / "timeline.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(evidence_event, ensure_ascii=False) + "\n")

    response = client.get(
        f"/api/agents/{agent['agentId']}/runtime-evidence",
        params={"sessionId": "session-evidence", "runId": "run-evidence"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["agentId"] == agent["agentId"]
    assert payload["matches"][0]["runtimeSceneId"] == "scene-agent-evidence"
    assert payload["matches"][0]["eventCode"] == "agent.message.consumed"
    assert payload["matches"][0]["rawRefs"] == [{"path": "events/agent_directory.jsonl", "tail_lines": 80}]
    assert payload["matches"][0]["matchedFields"] == {
        "agentId": agent["agentId"],
        "sessionId": "session-evidence",
        "runId": "run-evidence",
    }


def test_runtime_scene_package_records_conversation_as_child_log(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-chat", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-chat",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    payload = runtime_scene_service.record_runtime_scene_conversation_event(
        "session-demo",
        "user",
        "帮我分析这个周期日志",
        event="user_message",
        status="running",
        tool_calls=[{"name": "inspect_logs", "status": "done", "summary": "read package"}],
    )

    assert payload["accepted"] is True
    conversation_log = scene_dir / "conversations" / "session-demo.jsonl"
    assert conversation_log.exists()
    assert "帮我分析这个周期日志" in conversation_log.read_text(encoding="utf-8")
    assert (scene_dir / "agent" / "turns.jsonl").exists()
    assert (scene_dir / "agent" / "tool_calls.jsonl").exists()
    timeline_text = (scene_dir / "timeline.jsonl").read_text(encoding="utf-8")
    assert "conversation.user_message" in timeline_text

    detail_response = client.get("/api/logs/runtime-scenes/scene-chat")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    local_date, _, local_time_key = _runtime_scene_local_index_parts("2026-05-18T12:00:00Z")
    assert detail["packageIndex"]["indexKey"] == f"{local_date}_{local_time_key}_workbench-start_running"
    assert detail["packageIndex"]["durationSeconds"] is None
    assert detail["packageSummary"]["conversationLogCount"] == 1
    assert detail["packageSummary"]["agentLogCount"] == 2
    assert detail["timeline"][-1]["eventCode"] == "conversation.user_message"
    assert detail["timeline"][-1]["rawRefs"] == [{"path": "conversations/session-demo.jsonl", "tail_lines": 80}]
    assert detail["conversationLogs"][0]["path"] == "conversations/session-demo.jsonl"


def test_runtime_scene_event_helper_records_structured_lifecycle_event(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-event", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-event",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = runtime_scene_service.record_runtime_scene_event(
        "work_run",
        "state",
        "work_run.snapshot.persisted",
        message="Snapshot persisted",
        outcome="succeeded",
        fields={
            "runId": "run-1",
            "status": "running",
            "apiKey": "secret-value",
            "longText": "x" * 1400,
        },
        raw_refs=[{"path": "raw/work.log", "tail_lines": 20}],
        lifecycle=True,
    )

    assert response["accepted"] is True
    event_rows = [
        json.loads(line)
        for line in (scene_dir / "events" / "work_run.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event = event_rows[-1]
    assert event["component"] == "work_run"
    assert event["phase"] == "state"
    assert event["event_code"] == "work_run.snapshot.persisted"
    assert event["fields"]["runId"] == "run-1"
    assert event["fields"]["apiKey"] == "[redacted]"
    assert event["fields"]["longText"].endswith("...")
    assert len(event["fields"]["longText"]) == runtime_scene_service.MAX_TELEMETRY_FIELD_TEXT_CHARS
    assert event["raw_refs"] == [{"path": "raw/work.log", "tail_lines": 20}]

    lifecycle_text = (scene_dir / "lifecycle.jsonl").read_text(encoding="utf-8")
    assert "work_run.snapshot.persisted" in lifecycle_text

    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["package"]["timeline_path"] == "timeline.jsonl"
    assert manifest["package"]["lifecycle_path"] == "lifecycle.jsonl"


def test_runtime_scene_reconciliation_closes_running_package(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-reconciled", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-reconciled",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = runtime_scene_service.record_runtime_scene_event(
        "runtime_manager",
        "runtime",
        "runtime.snapshot.reconciled",
        message="Runtime manager runtime event: runtime.snapshot.reconciled",
        outcome="observed",
        occurred_at="2026-05-18T12:05:00Z",
        fields={
            "managerRunning": False,
            "managerPid": 0,
            "desiredState": "closed",
            "observedState": "closed",
            "backendPid": 0,
            "browserWindowPid": 0,
            "lifecycleConsistency": "consistent",
        },
        lifecycle=True,
    )

    assert response["accepted"] is True
    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "stopped"
    assert manifest["result"] == "state_reconciled"
    assert manifest["ended_at"] == "2026-05-18T12:05:00+00:00"
    assert manifest["backend"]["pid"] == 0
    assert manifest["backend"]["health_status"] == "stopped"
    assert manifest["browser"]["window_pid"] == 0
    assert manifest["browser"]["status"] == "stopped"
    assert manifest["runtime_manager"]["observed_state"] == "closed"

    package_index = json.loads((scene_dir / "package_index.json").read_text(encoding="utf-8"))
    assert package_index["ended_at"] == "2026-05-18T12:05:00+00:00"
    assert package_index["duration_seconds"] == 300
    assert package_index["index_key"].endswith("_workbench-start_state-reconciled")
    assert "state-reconciled" in package_index["tags"]

    summary = json.loads((scene_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "stopped"
    assert summary["result"] == "state_reconciled"
    assert summary["display_name"].endswith("状态校准")


def test_runtime_scene_detail_repairs_historical_running_package_from_reconciliation(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-history", status="running")
    with (scene_dir / "timeline.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "runtime_scene_id": "scene-history",
                    "ts": "2026-05-18T12:05:00Z",
                    "seq": 1,
                    "component": "runtime_manager",
                    "phase": "runtime",
                    "event_code": "runtime.snapshot.reconciled",
                    "level": "info",
                    "outcome": "observed",
                    "message": "Runtime manager runtime event: runtime.snapshot.reconciled",
                    "fields": {
                        "managerRunning": False,
                        "managerPid": 0,
                        "desiredState": "closed",
                        "observedState": "closed",
                        "backendPid": 0,
                        "browserWindowPid": 0,
                        "lifecycleConsistency": "consistent",
                    },
                    "raw_refs": [],
                    "lifecycle": True,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    manifest_before = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_before["status"] == "running"
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)

    detail = runtime_scene_service.get_runtime_scene_detail("scene-history")

    assert detail["status"] == "stopped"
    assert detail["result"] == "state_reconciled"
    assert detail["packageIndex"]["indexKey"].endswith("_workbench-start_state-reconciled")
    manifest_after = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_after["status"] == "stopped"
    assert manifest_after["ended_at"] == "2026-05-18T12:05:00+00:00"


def test_runtime_scene_lifecycle_fallback_indexes_operational_phases(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-lifecycle-fallback", status="running")
    timeline_path = scene_dir / "timeline.jsonl"
    timeline_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "runtime_scene_id": "scene-lifecycle-fallback",
                    "ts": f"2026-05-18T12:00:{index:02d}Z",
                    "seq": index,
                    "component": component,
                    "phase": phase,
                    "event_code": event_code,
                    "level": "info",
                    "outcome": "observed",
                    "message": event_code,
                    "fields": {},
                },
                ensure_ascii=False,
            )
            for index, (component, phase, event_code) in enumerate(
                [
                    ("frontend", "dependencies", "frontend.dependencies.current"),
                    ("launcher", "python_dependencies", "backend.dependencies.current"),
                    ("browser", "window", "browser.window.opened"),
                    ("backend", "api", "backend.api.request"),
                    ("browser_page", "lifecycle", "browser.visibility.changed"),
                    ("browser_page", "navigation", "browser.route.changed"),
                    ("browser_page", "focus", "browser.focus.changed"),
                ],
                start=1,
            )
        )
        + "\n",
        encoding="utf-8",
    )
    lifecycle_path = scene_dir / "lifecycle.jsonl"
    lifecycle_path.unlink()
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)

    detail = runtime_scene_service.get_runtime_scene_detail("scene-lifecycle-fallback")

    lifecycle_codes = [event["eventCode"] for event in detail["lifecycle"]]
    assert "frontend.dependencies.current" in lifecycle_codes
    assert "backend.dependencies.current" in lifecycle_codes
    assert "browser.window.opened" in lifecycle_codes
    assert "backend.api.request" in lifecycle_codes
    assert "browser.visibility.changed" in lifecycle_codes
    assert "browser.route.changed" in lifecycle_codes
    assert "browser.focus.changed" not in lifecycle_codes


def test_runtime_scene_event_helper_rejects_stopped_launcher_scene(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-event-stopped", status="stopped")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-event-stopped",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = runtime_scene_service.record_runtime_scene_event(
        "work_run",
        "state",
        "work_run.snapshot.persisted",
    )

    assert response == {"accepted": False, "reason": "no_runtime_scene"}
    assert not (scene_dir / "events" / "work_run.jsonl").exists()


def test_runtime_scene_event_helper_rejects_foreign_project_scene(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-event-foreign", status="running")
    manifest_path = scene_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["project_root"] = str(tmp_path / "other-repo")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-event-foreign",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = runtime_scene_service.record_runtime_scene_event(
        "work_run",
        "state",
        "work_run.snapshot.persisted",
    )

    assert response == {"accepted": False, "reason": "no_runtime_scene"}
    assert not (scene_dir / "events" / "work_run.jsonl").exists()


def test_runtime_scene_event_helper_ignores_absolute_child_log_path(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-event-absolute-child", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-event-absolute-child",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = runtime_scene_service.record_runtime_scene_event(
        "work_run",
        "state",
        "work_run.snapshot.persisted",
        child_log_path=str(tmp_path / "outside.jsonl"),
        child_log_payload={"status": "running"},
    )

    assert response["accepted"] is True
    assert response["path"] == ""
    assert not (tmp_path / "outside.jsonl").exists()
    event_rows = [
        json.loads(line)
        for line in (scene_dir / "events" / "work_run.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert event_rows[-1]["raw_refs"] == []


def test_runtime_scene_event_helper_ignores_traversal_child_log_path(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-event-traversal-child", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-event-traversal-child",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = runtime_scene_service.record_runtime_scene_event(
        "work_run",
        "state",
        "work_run.snapshot.persisted",
        child_log_path="agent/../outside.jsonl",
        child_log_payload={"status": "running"},
    )

    assert response["accepted"] is True
    assert response["path"] == ""
    assert not (scene_dir / "outside.jsonl").exists()
    event_rows = [
        json.loads(line)
        for line in (scene_dir / "events" / "work_run.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert event_rows[-1]["raw_refs"] == []


def test_runtime_scene_event_helper_returns_false_without_active_scene(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = runtime_scene_service.record_runtime_scene_event(
        "work_run",
        "state",
        "work_run.snapshot.persisted",
    )

    assert response == {"accepted": False, "reason": "no_runtime_scene"}
    assert not (tmp_path / "logs" / "runtime_scenes").exists()


def test_pytest_runtime_scene_recording_defaults_to_isolated_launcher_state(tmp_path):
    response = runtime_scene_service.record_runtime_scene_event(
        "work_run",
        "state",
        "work_run.snapshot.persisted",
    )

    assert response == {"accepted": False, "reason": "no_runtime_scene"}
    assert runtime_scene_service.PROJECT_ROOT == tmp_path
    assert runtime_scene_service.LAUNCHER_STATE_PATH == tmp_path / ".runtime" / "launcher" / "state.json"
    assert not (tmp_path / "logs" / "runtime_scenes").exists()


def test_work_run_store_records_snapshot_into_active_runtime_scene(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-work-run", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-work-run",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    store = WorkRunStore(root=tmp_path / ".runtime" / "runtime-manager" / "work_runs")
    store.persist_snapshot(
        "supervised",
        {
            "runId": "run-1",
            "status": "failed",
            "currentPhase": "failed",
            "runtimeStatus": "failed",
            "updatedAt": "2026-05-18T12:01:00Z",
            "error": "boom",
        },
        active_run_id="run-1",
    )

    rows = [
        json.loads(line)
        for line in (scene_dir / "events" / "work_run.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event = rows[-1]
    assert event["event_code"] == "work_run.snapshot.persisted"
    assert event["level"] == "error"
    assert event["fields"]["runKind"] == "supervised"
    assert event["fields"]["runId"] == "run-1"
    assert event["fields"]["status"] == "failed"
    assert event["fields"]["error"] == "boom"
    assert "work_run.snapshot.persisted" in (scene_dir / "lifecycle.jsonl").read_text(encoding="utf-8")


def test_work_run_store_records_chat_completed_and_stopped_snapshots_in_lifecycle(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-work-run-chat-terminal", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-work-run-chat-terminal",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    store = WorkRunStore(root=tmp_path / ".runtime" / "runtime-manager" / "work_runs")
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "turn-completed",
            "status": "completed",
            "currentPhase": "completed",
            "updatedAt": "2026-05-18T12:02:00Z",
            "finishedAt": "2026-05-18T12:02:00Z",
        },
        active_run_id="",
    )
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "turn-stopped",
            "status": "stopped",
            "currentPhase": "stopped",
            "updatedAt": "2026-05-18T12:03:00Z",
            "finishedAt": "2026-05-18T12:03:00Z",
        },
        active_run_id="",
    )

    lifecycle_events = [
        json.loads(line)
        for line in (scene_dir / "lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    statuses = [
        event["fields"]["status"]
        for event in lifecycle_events
        if event.get("event_code") == "work_run.snapshot.persisted"
    ]
    assert statuses[-2:] == ["completed", "stopped"]


def test_work_run_store_keeps_duplicate_snapshot_out_of_lifecycle(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-work-run-dedupe", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-work-run-dedupe",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    store = WorkRunStore(root=tmp_path / ".runtime" / "runtime-manager" / "work_runs")
    base_snapshot = {
        "runId": "run-dedupe",
        "status": "running",
        "currentPhase": "running",
        "runtimeStatus": "running",
        "updatedAt": "2026-05-18T12:01:00Z",
    }
    store.persist_snapshot("supervised", base_snapshot, active_run_id="run-dedupe")
    store.persist_snapshot(
        "supervised",
        {**base_snapshot, "updatedAt": "2026-05-18T12:01:01Z"},
        active_run_id="run-dedupe",
    )
    store.persist_snapshot(
        "supervised",
        {
            **base_snapshot,
            "status": "done",
            "currentPhase": "completed",
            "runtimeStatus": "idle",
            "updatedAt": "2026-05-18T12:02:00Z",
            "finishedAt": "2026-05-18T12:02:00Z",
        },
        active_run_id="",
    )

    work_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "work_run.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["fields"]["status"] for event in work_events[-3:]] == ["running", "running", "done"]

    lifecycle_events = [
        json.loads(line)
        for line in (scene_dir / "lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    work_lifecycle = [
        event for event in lifecycle_events
        if event.get("event_code") == "work_run.snapshot.persisted"
    ]
    assert [event["fields"]["status"] for event in work_lifecycle] == ["running", "done"]


def test_supervised_progress_records_child_log_into_runtime_scene(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-supervised", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-supervised",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    supervised_control_service._record_supervised_progress_scene_event(
        "web-supervised-demo",
        {
            "timestamp": "2026-05-18T12:01:00Z",
            "event": "role_finish",
            "title": "Case 完成",
            "summary": "case-1 candidate status=success reason=improved",
            "status": "success",
            "caseId": "case-1",
            "caseIndex": 1,
            "caseTotal": 2,
            "role": "candidate",
            "scenario": "compare prompt",
            "mode": "supervised",
            "bundleName": "demo-bundle",
            "sessionId": "session-1",
            "decision": "",
            "reason": "improved",
            "errorType": "",
            "elapsedSeconds": 1.5,
            "resultStatus": "success",
        },
    )

    child_log = scene_dir / "agent" / "supervised_runs" / "web-supervised-demo.jsonl"
    assert child_log.exists()
    child_event = json.loads(child_log.read_text(encoding="utf-8").splitlines()[-1])
    assert child_event["event"] == "role_finish"
    assert child_event["caseId"] == "case-1"
    assert child_event["role"] == "candidate"
    assert "prompt" not in child_event

    event_rows = [
        json.loads(line)
        for line in (scene_dir / "events" / "supervised_run.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event = event_rows[-1]
    assert event["event_code"] == "supervised_run.progress.role_finish"
    assert event["raw_refs"] == [{"path": "agent/supervised_runs/web-supervised-demo.jsonl", "tail_lines": 80}]
    assert "supervised_run.progress.role_finish" in (scene_dir / "timeline.jsonl").read_text(encoding="utf-8")
    assert "supervised_run.progress.role_finish" not in (scene_dir / "lifecycle.jsonl").read_text(encoding="utf-8")


def test_self_evolution_state_records_child_log_into_runtime_scene(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-self", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-self",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    self_evolution_control_service._record_self_state_change_scene_event(
        "web-self-demo",
        {
            "runId": "web-self-demo",
            "status": "done",
            "phase": "completed",
            "runtimeStatus": "idle",
            "toolCallCount": 3,
            "lastToolName": "read_file",
            "summary": "finished current bounded pass",
            "updatedAt": "2026-05-18T12:02:00Z",
            "finishedAt": "2026-05-18T12:02:00Z",
            "rollback": {
                "status": "available",
                "manifestPath": "workspace/web_self_evolution/web-self-demo/rollback_manifest.json",
            },
        },
        {"status": "done", "phase": "completed"},
        clear_active=True,
    )

    child_log = scene_dir / "agent" / "self_evolution_runs" / "web-self-demo.jsonl"
    assert child_log.exists()
    child_event = json.loads(child_log.read_text(encoding="utf-8").splitlines()[-1])
    assert child_event["status"] == "done"
    assert child_event["toolCallCount"] == 3
    assert child_event["lastToolName"] == "read_file"
    assert child_event["rollbackStatus"] == "available"

    event_rows = [
        json.loads(line)
        for line in (scene_dir / "events" / "self_evolution_run.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event = event_rows[-1]
    assert event["event_code"] == "self_evolution_run.state.changed"
    assert event["raw_refs"] == [{"path": "agent/self_evolution_runs/web-self-demo.jsonl", "tail_lines": 80}]
    assert "self_evolution_run.state.changed" in (scene_dir / "timeline.jsonl").read_text(encoding="utf-8")
    assert "self_evolution_run.state.changed" in (scene_dir / "lifecycle.jsonl").read_text(encoding="utf-8")


def test_self_evolution_control_paths_record_child_log_before_agent_turn(tmp_path, monkeypatch):
    _reset_self_evolution_live_state()
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-self-control", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-self-control",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(self_evolution_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(self_evolution_control_service, "ROLLBACK_ROOT", tmp_path / "workspace" / "web_self_evolution")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {"modeAvailability": {"self_evolution": True}},
    )
    monkeypatch.setattr(self_evolution_control_service, "active_session_has_write_leases", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(self_evolution_control_service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        self_evolution_control_service,
        "_capture_preflight_state",
        lambda run_id: {
            "runDir": "",
            "backupDir": "",
            "manifestPath": "",
            "baseRev": "base-rev",
        },
    )
    monkeypatch.setattr(self_evolution_control_service._RUN_EXECUTOR, "submit", lambda *args, **kwargs: None)

    started = self_evolution_control_service.start_self_evolution_run({"goal": "只验证日志包"})
    paused = self_evolution_control_service.request_pause_self_evolution_run(started["runId"])

    assert paused["status"] == "paused"
    child_log = scene_dir / "agent" / "self_evolution_runs" / f"{started['runId']}.jsonl"
    assert child_log.exists()
    child_events = [
        json.loads(line)
        for line in child_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["status"] for event in child_events[-2:]] == ["queued", "paused"]

    event_rows = [
        json.loads(line)
        for line in (scene_dir / "events" / "self_evolution_run.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    state_events = [event for event in event_rows if event["event_code"] == "self_evolution_run.state.changed"]
    assert state_events[-1]["raw_refs"] == [
        {"path": f"agent/self_evolution_runs/{started['runId']}.jsonl", "tail_lines": 80}
    ]
    assert state_events[-1]["fields"]["status"] == "paused"
    assert state_events[-1]["fields"]["clearActive"] is False


def test_runtime_browser_telemetry_records_into_active_scene(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-live", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-live",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = client.post(
        "/api/runtime/browser-telemetry",
        json={
            "phase": "navigation",
            "eventCode": "browser.route.changed",
            "message": "React route changed to /chat",
            "level": "info",
            "fields": {
                "pathname": "/chat",
                "href": "http://127.0.0.1:8000/chat",
                "title": "Chat",
                "activeNavHref": "/self-evolution",
                "heading": "Self evolution",
            },
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["runtimeSceneId"] == "scene-live"

    telemetry_raw = (scene_dir / "raw" / "browser.telemetry.log").read_text(encoding="utf-8")
    assert "browser.route.changed" in telemetry_raw
    assert "/chat" in telemetry_raw

    telemetry_events = (scene_dir / "events" / "browser_page.jsonl").read_text(encoding="utf-8")
    assert "browser.route.changed" in telemetry_events
    assert "\"activeNavHref\":\"/self-evolution\"" in telemetry_events

    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["browser"]["telemetry_path"] == "raw/browser.telemetry.log"
    assert manifest["browser"]["current_pathname"] == "/chat"
    assert manifest["browser"]["active_nav_href"] == "/self-evolution"
    assert manifest["browser"]["current_heading"] == "Self evolution"


def test_runtime_browser_memory_telemetry_updates_manifest_summary(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-memory", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-memory",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = client.post(
        "/api/runtime/browser-telemetry",
        json={
            "phase": "memory",
            "eventCode": "browser.memory.sampled",
            "message": "Browser memory sampled: route_settled",
            "level": "info",
            "fields": {
                "pathname": "/config",
                "reason": "route_settled",
                "available": True,
                "usedJSHeapMB": 512.5,
                "totalJSHeapMB": 640.0,
                "jsHeapLimitMB": 4096.0,
                "queryCount": 17,
                "activeQueryCount": 6,
                "fetchingQueryCount": 1,
                "staleQueryCount": 3,
                "sessionQueryCount": 2,
                "logQueryCount": 1,
            },
        },
    )

    assert response.status_code == 202
    telemetry_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "browser_page.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert telemetry_events[-1]["phase"] == "memory"
    assert telemetry_events[-1]["event_code"] == "browser.memory.sampled"
    assert telemetry_events[-1]["fields"]["usedJSHeapMB"] == 512.5

    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["browser"]["last_memory_used_js_heap_mb"] == 512.5
    assert manifest["browser"]["last_memory_query_count"] == 17
    assert manifest["browser"]["last_memory_pathname"] == "/config"


def test_runtime_browser_stream_lifecycle_telemetry_updates_manifest(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-stream", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-stream",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = client.post(
        "/api/runtime/browser-telemetry",
        json={
            "phase": "session_stream",
            "eventCode": "browser.session_stream.closed",
            "message": "Session detail stream closed.",
            "level": "info",
            "fields": {
                "sessionId": "session-1",
                "readyState": 1,
            },
        },
    )

    assert response.status_code == 202
    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["browser"]["last_session_stream_event_code"] == "browser.session_stream.closed"
    assert manifest["browser"]["last_session_stream_session_id"] == "session-1"


def test_runtime_browser_visibility_noise_stays_in_raw_log(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-browser-noise", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-browser-noise",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    def post_visibility(value: str):
        return client.post(
            "/api/runtime/browser-telemetry",
            json={
                "phase": "lifecycle",
                "eventCode": "browser.visibility.changed",
                "message": f"Visibility changed to {value}",
                "level": "info",
                "fields": {
                    "pathname": "/supervised-evolution/runs",
                    "visibilityState": value,
                },
            },
        )

    assert post_visibility("visible").status_code == 202
    assert post_visibility("hidden").status_code == 202
    route_response = client.post(
        "/api/runtime/browser-telemetry",
        json={
            "phase": "navigation",
            "eventCode": "browser.route.changed",
            "message": "React route changed to /chat",
            "level": "info",
            "fields": {
                "pathname": "/chat",
                "visibilityState": "hidden",
            },
        },
    )
    assert route_response.status_code == 202

    raw_lines = [
        line for line in (scene_dir / "raw" / "browser.telemetry.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(raw_lines) == 3
    assert sum("browser.visibility.changed" in line for line in raw_lines) == 2

    browser_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "browser_page.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["event_code"] for event in browser_events] == [
        "browser.visibility.changed",
        "browser.route.changed",
    ]

    timeline_events = [
        json.loads(line)
        for line in (scene_dir / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    browser_timeline_events = [
        event for event in timeline_events
        if event.get("component") == "browser_page"
    ]
    assert [event["event_code"] for event in browser_timeline_events] == [
        "browser.visibility.changed",
        "browser.route.changed",
    ]
    lifecycle_events = [
        json.loads(line)
        for line in (scene_dir / "lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    browser_lifecycle_events = [
        event for event in lifecycle_events
        if event.get("component") == "browser_page"
    ]
    assert [event["event_code"] for event in browser_lifecycle_events] == [
        "browser.visibility.changed",
        "browser.route.changed",
    ]

    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["browser"]["visibility_state"] == "hidden"
    assert manifest["browser"]["last_event_indexed"] is True
    assert manifest["browser"]["last_visibility_event_at"]
    assert manifest["browser"]["last_indexed_visibility_event_at"]


def test_backend_api_runtime_event_records_mutating_request(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-api", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-api",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(runtime_service, "_schedule_local_backend_exit", lambda delay_seconds=0.35: None)
    monkeypatch.setattr(runtime_service, "LAUNCHER_SCRIPT_PATH", tmp_path / "missing-launcher.ps1")
    monkeypatch.setattr(runtime_service, "LAUNCHER_STATE_PATH", tmp_path / "missing-state.json")

    response = client.post("/api/runtime/shutdown")

    assert response.status_code == 202
    backend_raw = (scene_dir / "raw" / "backend.api.log").read_text(encoding="utf-8")
    assert "backend.api.request" in backend_raw
    assert "/api/runtime/shutdown" in backend_raw

    backend_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "backend.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    api_event = backend_events[-1]
    assert api_event["phase"] == "api"
    assert api_event["event_code"] == "backend.api.request"
    assert api_event["fields"]["method"] == "POST"
    assert api_event["fields"]["pathTemplate"] == "/api/runtime/shutdown"
    assert api_event["fields"]["statusCode"] == 202
    assert api_event["raw_refs"] == [{"path": "raw/backend.api.log", "tail_lines": 80}]
    lifecycle_text = (scene_dir / "lifecycle.jsonl").read_text(encoding="utf-8")
    assert "backend.api.request" in lifecycle_text

    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["backend"]["api_log_path"] == "raw/backend.api.log"
    assert manifest["backend"]["last_api_path"] == "/api/runtime/shutdown"


def test_backend_api_runtime_event_marks_model_discovery_client_error_operational(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-model-discovery-api", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-model-discovery-api",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    runtime_scene_service.record_backend_api_event(
        {
            "method": "POST",
            "path": "/api/config/discover-models",
            "path_template": "/api/config/discover-models",
            "status_code": 422,
            "duration_ms": 12.3,
            "client": "127.0.0.1",
        }
    )

    backend_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "backend.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    api_event = backend_events[-1]
    assert api_event["level"] == "info"
    assert api_event["outcome"] == "operational_client_error"
    assert api_event["fields"]["statusCode"] == 422
    assert api_event["fields"]["operationalClientError"] is True
    summary = json.loads((scene_dir / "summary.json").read_text(encoding="utf-8"))
    active_codes = {
        cluster["eventCode"]
        for cluster in summary["diagnosis"]["issueState"]["activeClusters"]
    }
    assert "backend.api.request" not in active_codes


def test_backend_api_runtime_event_skips_health_noise(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-health", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-health",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert not (scene_dir / "raw" / "backend.api.log").exists()


def test_runtime_logs_reject_runtime_scene_path_operations(tmp_path, monkeypatch):
    _seed_runtime_scene_bundle(tmp_path, scene_id="scene-guard")
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/logs/delete",
        json={"root": "runtime_logs", "paths": ["runtime_scenes/20260518T120000Z__scene-guard/manifest.json"]},
    )

    assert response.status_code == 400
    assert "runtime scenes surface" in response.json()["detail"].lower()


def test_runtime_scene_delete_rejects_running_bundle(tmp_path, monkeypatch):
    _seed_runtime_scene_bundle(tmp_path, scene_id="scene-live", status="running")
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/logs/runtime-scenes/delete",
        json={"sceneIds": ["scene-live"]},
    )

    assert response.status_code == 400
    assert "still running" in response.json()["detail"]


def test_missing_static_asset_returns_404_instead_of_index(tmp_path, monkeypatch):
    dist_dir = tmp_path / "web-dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<!doctype html><html><body>app</body></html>", encoding="utf-8")

    monkeypatch.setattr("core.web.app.WEB_DIST", dist_dir)
    temp_client = TestClient(create_app())

    response = temp_client.get("/assets/FilePreview-missing.js")

    assert response.status_code == 404
    assert response.json()["detail"] == "Not Found"


def test_spa_route_still_falls_back_to_index_html(tmp_path, monkeypatch):
    dist_dir = tmp_path / "web-dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    index_html = "<!doctype html><html><body>app shell</body></html>"
    (dist_dir / "index.html").write_text(index_html, encoding="utf-8")

    monkeypatch.setattr("core.web.app.WEB_DIST", dist_dir)
    temp_client = TestClient(create_app())

    response = temp_client.get("/logs")

    assert response.status_code == 200
    assert "app shell" in response.text


def _seed_chat_state(project_root, *, task_status="reading", active_task=None):
    save_chat_state(
        project_root,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-18T12:00:00",
                    "last_turn_status": "failed" if task_status == "failed" else "ready",
                    "active_task": active_task,
                    "messages": [
                        {
                            "role": "user",
                            "content": "继续前端开发",
                            "timestamp": "2026-05-18T11:55:00",
                        },
                        {
                            "role": "assistant",
                            "content": "<think>internal</think>\n\n已经接到真实状态了。",
                            "timestamp": "2026-05-18T11:56:00",
                            "tool_calls": [
                                {"name": "read_file_tool"},
                                {"function": {"name": "search_code_tool"}},
                            ],
                        },
                    ],
                }
            ],
        },
    )


def _read_next_state_signals(project_root: Path, *, session_id: str = "", turn_id: str = "") -> list[dict]:
    return list_chat_next_state_signals(project_root=project_root, session_id=session_id, turn_id=turn_id)


def test_session_detail_exists(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    sessions_response = client.get("/api/sessions")
    assert sessions_response.status_code == 200
    sessions = sessions_response.json()
    assert sessions
    assert sessions[0]["id"] == "session-live"

    response = client.get("/api/sessions/session-live")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["messages"]
    assert payload["messages"][1]["content"] == "已经接到真实状态了。"
    assert payload["messages"][1]["thought"] == "internal"
    assert payload["messages"][1]["toolCalls"] == [
        {"name": "read_file_tool", "status": "done"},
        {"name": "search_code_tool", "status": "done"},
    ]
    assert payload["lastTurnError"] is None
    assert payload["taskSummary"] == "已经接到真实状态了。"
    assert payload["previewTabs"] == []
    assert payload["currentPhase"] == "ready"
    assert payload["contextUsage"]["source"] == "session_messages"
    assert payload["contextUsage"]["messageCount"] == 2
    assert payload["contextUsage"]["userMessageCount"] == 1
    assert payload["contextUsage"]["assistantMessageCount"] == 1
    assert payload["contextUsage"]["toolCallCount"] == 2
    assert payload["contextUsage"]["used"] > 0
    assert payload["contextUsage"]["limit"] > 0


def test_skills_api_lists_read_only_skill_library(tmp_path, monkeypatch):
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nStop before implementation.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_service, "default_skill_roots", lambda: [skill_root])

    response = client.get("/api/skills")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "read_only"
    assert payload["counts"]["total"] == 1
    assert payload["skills"][0]["command"] == "/brt"
    assert "content" not in payload["skills"][0]


def test_skills_api_returns_skill_detail(tmp_path, monkeypatch):
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nAsk one question at a time.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_service, "default_skill_roots", lambda: [skill_root])

    response = client.get("/api/skills/brt")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "brt"
    assert payload["command"] == "/brt"
    assert "Ask one question at a time." in payload["content"]


def test_session_detail_surfaces_missing_agent_placeholder(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "断链会话",
                    "agent_id": "agent-missing",
                    "agentId": "agent-missing",
                    "updated_at": "2026-05-18T12:00:00",
                    "last_turn_status": "ready",
                    "messages": [
                        {
                            "role": "user",
                            "content": "继续",
                            "timestamp": "2026-05-18T11:55:00",
                        }
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    sessions_response = client.get("/api/sessions")
    detail_response = client.get("/api/sessions/session-live")

    assert sessions_response.status_code == 200
    session_summary = sessions_response.json()[0]
    assert session_summary["agentId"] == "agent-missing"
    assert session_summary["agentMissing"] is True
    assert session_summary["agentStatusCode"] == "missing_agent"
    assert session_summary["agentDisplayName"] == "缺少有效 Agent"
    assert "缺少有效 Agent" in session_summary["agentStatusMessage"]
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["agentMissing"] is True
    assert detail["groupContextEvents"] == []
    assert detail["agentInboxMessages"] == []
    assert detail["toolPolicy"] is None
    assert detail["memoryPolicy"] is None


def test_session_detail_context_usage_comes_from_persisted_messages_after_restart(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].extend(
        [
            {
                "role": "user",
                "content": "重启后仍然应该统计这一条历史用户消息。",
                "timestamp": "2026-05-18T11:57:00",
            },
            {
                "role": "assistant",
                "content": "收到，当前对话上下文应来自持久化消息，而不是运行时临时计数。",
                "timestamp": "2026-05-18T11:58:00",
            },
        ]
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["messages"]) == 4
    assert payload["contextUsage"]["messageCount"] == 4
    assert payload["contextUsage"]["userMessageCount"] == 2
    assert payload["contextUsage"]["assistantMessageCount"] == 2
    assert payload["contextUsage"]["source"] == "session_messages"
    assert payload["contextUsage"]["used"] == payload["contextUsage"]["estimatedTokens"]
    assert payload["contextUsage"]["used"] > 0


def test_session_detail_context_limit_prefers_model_window_over_compression_default(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    cfg = session_service.get_config().model_copy(deep=True)
    primary = cfg.llm.get_profile(role="primary")
    provider = cfg.llm.get_provider(primary.provider_id)
    provider.context_window = 1_000_000
    cfg.context_compression.max_token_limit = 32_768
    monkeypatch.setattr(session_service, "get_config", lambda: cfg)
    monkeypatch.setattr(
        session_service,
        "_resolved_model_context_window",
        lambda _cfg, _profile_id: 1_000_000,
    )

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contextUsage"]["limit"] == 1_000_000


def test_session_detail_context_limit_prefers_live_runtime_window(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    runtime_state_path = tmp_path / "workspace" / "ui_runtime_state.json"
    runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_state_path.write_text(
        json.dumps(
            {
                "context_token_limit": 900_000,
                "context_compression": {
                    "effectiveTokenLimit": 450_000,
                    "contextWindowLimit": 900_000,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    cfg = session_service.get_config().model_copy(deep=True)
    cfg.context_compression.max_token_limit = 32_768
    monkeypatch.setattr(session_service, "get_config", lambda: cfg)
    monkeypatch.setattr(
        session_service,
        "_resolved_model_context_window",
        lambda _cfg, _profile_id: 1_000_000,
    )

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contextUsage"]["limit"] == 900_000


def test_session_detail_exposes_prompt_cache_observation(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    runtime_state = {
        "turn_input_tokens": 1000,
        "turn_cached_input_tokens": 640,
        "last_input_tokens": 500,
        "last_cached_input_tokens": 320,
        "total_input_tokens": 5000,
        "total_cached_input_tokens": 2500,
        "updated_at": "2026-05-18T12:03:00",
    }
    runtime_state_path = tmp_path / "workspace" / "ui_runtime_state.json"
    runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_state_path.write_text(json.dumps(runtime_state), encoding="utf-8")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    cache_usage = response.json()["cacheUsage"]
    assert cache_usage["turnInputTokens"] == 1000
    assert cache_usage["turnCachedInputTokens"] == 640
    assert cache_usage["lastInputTokens"] == 500
    assert cache_usage["lastCachedInputTokens"] == 320
    assert cache_usage["turnCacheHitRate"] == pytest.approx(0.64)
    assert cache_usage["totalCacheHitRate"] == pytest.approx(0.5)
    assert cache_usage["source"] == "ui_runtime_state"


def test_session_detail_keeps_persisted_tool_only_assistant_message(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].append(
        {
            "role": "assistant",
            "content": "<state",
            "timestamp": "2026-05-18T11:57:00",
            "tool_calls": [
                {"name": "read_file_tool", "status": "done", "summary": "session_service.py"},
            ],
        }
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == ""
    assert assistant["toolCalls"] == [
        {"name": "read_file_tool", "status": "done", "summary": "session_service.py"},
    ]


def test_history_seed_omits_state_only_assistant_messages():
    history = session_service._history_messages_for_agent_seed(
        [
            {"role": "user", "content": "审查对话日志并汇报"},
            {"role": "assistant", "content": "<state>{\"mood\":\"open\"}</state>"},
            {"role": "assistant", "content": "<state"},
            {"role": "assistant", "content": "已完成审查。"},
        ]
    )

    assert [
        {"role": item["role"], "content": item["content"]}
        for item in history
    ] == [
        {"role": "user", "content": "审查对话日志并汇报"},
        {"role": "assistant", "content": "已完成审查。"},
    ]


def test_build_followup_prompt_unwraps_nested_continue_goal():
    prompt = session_service._build_followup_prompt(
        original_prompt="审查对话日志并汇报",
        effective_prompt=(
            "继续完成同一个用户目标：继续完成同一个用户目标：审查对话日志并汇报\n"
            "上一内部回合仍未完成用户目标（第 1 轮）。"
        ),
        latest_result={
            "status": "completed",
            "outcome": "progress",
            "recommended_next_action": "基于已读证据输出结论。",
        },
        history_messages=[{"role": "user", "content": "审查对话日志并汇报"}],
        turn_index=2,
    )

    assert prompt.count("继续完成同一个用户目标：") == 1
    assert "继续完成同一个用户目标：审查对话日志并汇报" in prompt
    assert "继续完成同一个用户目标：继续完成" not in prompt


def test_normalize_persisted_tool_calls_preserves_timeout_as_failed():
    tool_calls = session_service._normalize_persisted_tool_calls(
        [
            {
                "name": "grep_search_tool",
                "status": "done",
                "summary": "[超时] grep_search_tool 执行超时 (30秒)",
            },
            {
                "name": "read_file_tool",
                "summary": "read ok",
            },
        ]
    )

    assert tool_calls[0]["status"] == "failed"
    assert tool_calls[1]["status"] == "done"


def test_normalize_persisted_tool_calls_preserves_safe_details():
    tool_calls = session_service._normalize_persisted_tool_calls(
        [
            {
                "name": "image2_generate_tool",
                "status": "failed",
                "summary": "Read timed out.",
                "args": {
                    "prompt": "生成美女图片",
                    "size": "1024x1024",
                    "_cancel_checker": "internal",
                    "api_key": "secret",
                },
                "error": "HTTPSConnectionPool read timed out",
                "durationMs": 180452,
                "timeoutSeconds": 180,
                "resultType": "str",
                "resultLength": 755,
                "tracePath": "conversations/session/tool_calls.jsonl",
            },
        ]
    )

    assert tool_calls == [
        {
            "name": "image2_generate_tool",
            "status": "failed",
            "summary": "Read timed out.",
            "arguments": {
                "prompt": "生成美女图片",
                "size": "1024x1024",
            },
            "error": "HTTPSConnectionPool read timed out",
            "durationMs": 180452,
            "timeoutSeconds": 180,
            "resultType": "str",
            "resultLength": 755,
            "tracePath": "conversations/session/tool_calls.jsonl",
        }
    ]


def test_chat_turn_records_keep_tool_names_when_persisted_calls_have_details():
    records = session_service._build_chat_turn_records_from_messages(
        [
            {"role": "user", "content": "生成图片"},
            {
                "role": "assistant",
                "content": "已调用工具。",
                "tool_calls": [
                    {
                        "name": "image2_generate_tool",
                        "status": "failed",
                        "args": {"prompt": "生成美女图片"},
                        "error": "timeout",
                    }
                ],
            },
        ]
    )

    assert records[0].tool_calls == ["image2_generate_tool"]
    assert records[0].tool_call_count == 1


def test_session_detail_exposes_recent_next_state_signal_summaries(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    append_chat_next_state_signal(
        project_root=tmp_path,
        session_id="session-live",
        turn_id="turn-signal",
        source="runtime",
        kind="provider_failure",
        polarity="negative",
        mode="evaluative",
        related_event_code="conversation.turn_circuit_breaker",
        summary="Provider failed after a partial tool pass.",
        metadata={"rawError": "full provider payload should stay out of session detail"},
        created_at="2026-05-18T11:58:00Z",
        record_scene=False,
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["nextStateSignals"] == [
        {
            "signalId": payload["nextStateSignals"][0]["signalId"],
            "sessionId": "session-live",
            "turnId": "turn-signal",
            "source": "runtime",
            "kind": "provider_failure",
            "polarity": "negative",
            "mode": "evaluative",
            "relatedEventCode": "conversation.turn_circuit_breaker",
            "createdAt": "2026-05-18T11:58:00Z",
            "summary": "Provider failed after a partial tool pass.",
        }
    ]
    assert "metadata" not in payload["nextStateSignals"][0]
    assert payload["messages"][0]["content"] == "继续前端开发"
    assert all(message["role"] in {"user", "assistant"} for message in payload["messages"])


def test_create_session_persists_new_active_empty_conversation(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.post("/api/sessions")

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"].startswith("session-")
    assert payload["title"] == "新会话"
    assert payload["messages"] == []
    assert payload["currentPhase"] == "ready"

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == payload["id"]
    assert [item["conversation_id"] for item in state["conversations"]] == [
        "session-live",
        payload["id"],
    ]
    created = state["conversations"][-1]
    assert "agent_profile_id" not in created
    assert "agentProfileId" not in created


def test_update_session_title_persists_to_list_and_detail(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.patch(
        "/api/sessions/session-live",
        json={"title": "重命名后的会话"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["title"] == "重命名后的会话"

    sessions_response = client.get("/api/sessions")
    assert sessions_response.status_code == 200
    assert sessions_response.json()[0]["title"] == "重命名后的会话"

    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["title"] == "重命名后的会话"


def test_update_session_agent_profile_persists_to_list_and_detail(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["subagent_explorer"] = base_config.llm.profiles["primary"].model_copy(deep=True)
    base_config.llm.profiles["subagent_explorer"].profile_id = "subagent_explorer"
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)

    response = client.patch(
        "/api/sessions/session-live",
        json={"agentProfileId": "subagent_explorer"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["agentProfileId"] == "subagent_explorer"
    assert payload["agentTemplateId"] == "subagent_explorer"

    sessions_response = client.get("/api/sessions")
    assert sessions_response.status_code == 200
    assert sessions_response.json()[0]["agentProfileId"] == "subagent_explorer"

    state = load_chat_state(tmp_path)
    assert "agent_profile_id" not in state["conversations"][0]
    assert "agentProfileId" not in state["conversations"][0]
    agent = agent_directory_service.get_agent(payload["agentId"])
    assert agent is not None
    assert agent["profileId"] == "subagent_explorer"


def test_update_session_agent_id_persists_as_primary_binding(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["subagent_explorer"] = base_config.llm.profiles["primary"].model_copy(deep=True)
    base_config.llm.profiles["subagent_explorer"].profile_id = "subagent_explorer"
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    agent = agent_directory_service.create_agent_instance(
        display_name="备用会话 Agent",
        profile_id="subagent_explorer",
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
    )

    response = client.patch(
        "/api/sessions/session-live",
        json={"agentId": agent["agentId"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["agentId"] == agent["agentId"]
    assert payload["agentProfileId"] == "subagent_explorer"

    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["agent_id"] == agent["agentId"]
    assert state["conversations"][0]["agentId"] == agent["agentId"]
    assert "agent_profile_id" not in state["conversations"][0]
    assert "agentProfileId" not in state["conversations"][0]
    rebound_agent = agent_directory_service.get_agent(agent["agentId"])
    assert rebound_agent is not None
    assert rebound_agent["directSessionId"] == "session-live"


def test_session_agent_templates_list_config_profiles(monkeypatch):
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["subagent_explorer"] = base_config.llm.profiles["primary"].model_copy(deep=True)
    base_config.llm.profiles["subagent_explorer"].profile_id = "subagent_explorer"
    base_config.llm.profiles["subagent_explorer"].model = "explorer-model"
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)

    response = client.get("/api/sessions/agent-templates")

    assert response.status_code == 200
    payload = response.json()
    templates = {item["templateId"]: item for item in payload}
    assert templates["primary"]["profileId"] == "primary"
    assert templates["subagent_explorer"]["model"] == "explorer-model"


def test_update_session_title_rejects_empty_title(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.patch(
        "/api/sessions/session-live",
        json={"title": "   "},
    )

    assert response.status_code == 422
    assert "名称" in response.json()["detail"]
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["title"] == "真实会话"


def test_delete_session_switches_to_latest_remaining_session(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "当前会话",
                    "updated_at": "2026-05-18T12:00:00",
                    "last_turn_status": "ready",
                    "messages": [{"role": "user", "content": "删除我", "timestamp": "2026-05-18T12:00:00"}],
                },
                {
                    "conversation_id": "session-older",
                    "title": "旧会话",
                    "updated_at": "2026-05-18T10:00:00",
                    "last_turn_status": "ready",
                    "messages": [{"role": "user", "content": "旧", "timestamp": "2026-05-18T10:00:00"}],
                },
                {
                    "conversation_id": "session-newer",
                    "title": "新会话",
                    "updated_at": "2026-05-18T11:00:00",
                    "last_turn_status": "ready",
                    "messages": [{"role": "user", "content": "新", "timestamp": "2026-05-18T11:00:00"}],
                },
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.delete("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-newer"

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == "session-newer"
    assert [item["conversation_id"] for item in state["conversations"]] == [
        "session-older",
        "session-newer",
    ]


def test_delete_session_keeps_bound_agent_active(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="科研复核 Agent",
        primary_mode="research",
        role_key="research_review",
        prompt_template_id="prompt-research-review",
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["agent_id"] = agent["agentId"]
    state["conversations"][0]["agentId"] = agent["agentId"]
    save_chat_state(tmp_path, state)

    response = client.delete("/api/sessions/session-live")

    assert response.status_code == 200
    kept_agent = agent_directory_service.get_agent(agent["agentId"], include_archived=True)
    assert kept_agent is not None
    assert kept_agent["status"] == "active"


def test_delete_last_session_creates_replacement(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.delete("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"].startswith("session-")
    assert payload["id"] != "session-live"
    assert payload["messages"] == []

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == payload["id"]
    assert [item["conversation_id"] for item in state["conversations"]] == [payload["id"]]


def test_delete_session_rejects_running_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    try:
        response = client.delete("/api/sessions/session-live")
    finally:
        session_service._set_session_running("session-live", False)

    assert response.status_code == 409
    assert "运行" in response.json()["detail"]
    state = load_chat_state(tmp_path)
    assert [item["conversation_id"] for item in state["conversations"]] == ["session-live"]


def test_session_detail_uses_live_phase_while_turn_is_running(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "running"


def test_session_detail_exposes_pre_model_progress_stage(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True, turn_id="turn-progress")
    try:
        session_service._set_session_waiting_live_output("session-live", turn_id="turn-progress")
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False, turn_id="turn-progress")

    assert response.status_code == 200
    payload = response.json()
    live_message = payload["messages"][-1]
    assert live_message["streaming"] is True
    assert live_message["streamStage"] == "context_prepare"
    assert live_message["content"] == "正在准备对话上下文..."


def test_session_detail_hydrates_file_context_from_saved_active_task(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "done",
            "title": "修复会话页面文件上下文",
            "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
            "changed_files": ["core/web/services/session_service.py"],
            "verification_status": "passed",
            "verification_summary": "2 passed in 0.31s",
            "default_file_context": "core/web/services/session_service.py",
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["readFiles"] == ["web/src/routes/ChatCodingRoute.tsx"]
    assert payload["changedFiles"] == ["core/web/services/session_service.py"]
    assert payload["defaultFileContext"] == "core/web/services/session_service.py"
    assert payload["previewTabs"] == [
        "core/web/services/session_service.py",
        "web/src/routes/ChatCodingRoute.tsx",
    ]
    assert payload["activePreviewPath"] == "core/web/services/session_service.py"
    assert payload["activeTask"]["title"] == "修复会话页面文件上下文"
    assert payload["activeTask"]["changedFiles"] == ["core/web/services/session_service.py"]
    assert payload["activeTask"]["readFiles"] == ["web/src/routes/ChatCodingRoute.tsx"]


def test_session_events_stream_initial_detail(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    detail = session_service.get_session_detail("session-live")
    assert detail is not None

    stream = session_service.stream_session_events("session-live", initial_detail=detail)
    raw_event = next(stream)
    stream.close()

    class _SingleEventResponse:
        def iter_lines(self):
            for line in str(raw_event).splitlines():
                yield line
            yield ""

    event = _read_first_sse_event(_SingleEventResponse())

    assert event["event"] == "session_detail"
    payload = json.loads(event["data"])
    assert payload["type"] == "session_detail"
    assert payload["sessionId"] == "session-live"
    assert payload["detail"]["id"] == "session-live"
    assert payload["detail"]["messages"][1]["content"] == "已经接到真实状态了。"


def test_session_events_stream_rejects_missing_session():
    response = client.get("/api/sessions/missing-session/events")
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


def test_submit_session_message_runs_turn_and_persists_reply(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            assert "ChatCodingRoute.tsx" in initial_prompt
            return {
                "status": "completed",
                "summary": "已完成网页对话提交接线。",
                "raw_output": "已完成网页对话提交接线。",
                "reasoning_content": "先确认消息模型，再把思考与心智快照一起落盘。",
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "主链路已经清楚了。",
                    "whisper": "把思考和回答放在同一张卡片里。",
                    "summary": "主链路已经清楚了。",
                    "cognitiveState": "productive",
                    "confidence": 0.86,
                    "sampleSize": 4,
                    "interventionCount": 1,
                    "updatedAt": "2026-05-18T12:01:00",
                    "source": "state",
                },
                "outcome": "done",
                "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
                "changed_files": ["core/web/services/session_service.py"],
                "verification_status": "passed",
                "verification_summary": "2 passed in 0.31s",
                "tool_call_count": 2,
                "tool_trace": [
                    {"name": "read_file_tool"},
                    {"function": {"name": "apply_patch_tool"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请继续修复 web/src/routes/ChatCodingRoute.tsx 并验证"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "请继续修复 web/src/routes/ChatCodingRoute.tsx 并验证"
    assert payload["messages"][-1]["role"] == "assistant"
    assert payload["messages"][-1]["content"] == "已完成网页对话提交接线。"
    assert payload["messages"][-1]["thought"] == "先确认消息模型，再把思考与心智快照一起落盘。"
    assert payload["messages"][-1]["mentalSnapshot"]["mood"] == "专注"
    assert payload["messages"][-1]["mentalSnapshot"]["cognitiveState"] == "productive"
    assert payload["messages"][-1]["toolCalls"] == [
        {"name": "read_file_tool", "status": "done"},
        {"name": "apply_patch_tool", "status": "done"},
    ]
    assert payload["taskSummary"] == "已完成网页对话提交接线。"
    assert payload["currentPhase"] == "ready"
    assert payload["readFiles"] == ["web/src/routes/ChatCodingRoute.tsx"]
    assert payload["changedFiles"] == ["core/web/services/session_service.py"]
    assert payload["defaultFileContext"] == "core/web/services/session_service.py"
    assert payload["previewTabs"] == [
        "core/web/services/session_service.py",
        "web/src/routes/ChatCodingRoute.tsx",
    ]
    assert payload["activePreviewPath"] == "core/web/services/session_service.py"
    assert payload["activeTask"]["goal"] == "请继续修复 web/src/routes/ChatCodingRoute.tsx 并验证"
    assert payload["activeTask"]["latestSummary"] == "已完成网页对话提交接线。"
    assert payload["activeTask"]["changedFiles"] == ["core/web/services/session_service.py"]
    assert payload["activeTask"]["verificationStatus"] == "passed"
    turn_events = [
        (args[2], kwargs)
        for args, kwargs in recorded_scene_events
        if len(args) >= 3 and str(args[2]).startswith("conversation.turn.")
    ]
    event_codes = [event_code for event_code, _kwargs in turn_events]
    for expected in [
        "conversation.turn.started",
        "conversation.turn.scheduled",
        "conversation.turn.worker_started",
        "conversation.turn.ui_capture_started",
        "conversation.turn.agent_created",
        "conversation.turn.history_seeded",
        "conversation.turn.agent_turn_started",
        "conversation.turn.agent_turn_returned",
        "conversation.turn.terminal_result",
        "conversation.turn.capture_attached",
        "conversation.turn.result_persisted",
        "conversation.turn.worker_finished",
    ]:
        assert expected in event_codes
    persisted_event = next(kwargs for event_code, kwargs in turn_events if event_code == "conversation.turn.result_persisted")
    assert persisted_event["outcome"] == "completed"
    assert persisted_event["fields"]["sessionId"] == "session-live"
    assert persisted_event["fields"]["assistantTextLength"] == len("已完成网页对话提交接线。")
    assert persisted_event["child_log_path"] == "conversations/session-live-turns.jsonl"


def test_session_submit_message_routes_slash_skill_into_scheduled_context(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nStop before implementation.\n",
        encoding="utf-8",
    )
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        session_service,
        "parse_skill_slash_command",
        lambda content: parse_skill_slash_command(content, skill_roots=[skill_root]),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "/brt 设计斜杠 skill 调用"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "/brt 设计斜杠 skill 调用"
    persisted_skill = payload["messages"][-2]["metadata"]["slashSkillCommand"]
    assert persisted_skill["command"] == "brt"
    assert persisted_skill["skillName"] == "brt"
    assert persisted_skill["skillHash"]
    assert "content" not in persisted_skill
    assert len(scheduled_contexts) == 1
    invocation = scheduled_contexts[0]["skill_invocation"]
    assert invocation["command"] == "brt"
    assert invocation["args"] == "设计斜杠 skill 调用"
    assert invocation["skillName"] == "brt"
    assert invocation["skillHash"]


def test_session_worker_seeds_slash_skill_runtime_context(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nAsk one question at a time.\n",
        encoding="utf-8",
    )
    seen_contexts: list[str] = []
    seen_prompt: dict[str, str] = {}
    scene_events: list[dict] = []

    class DummyAgent:
        def set_mental_model_enabled_override(self, _enabled):
            pass

        def seed_chat_history(self, _messages):
            pass

        def seed_runtime_context(self, content):
            seen_contexts.append(content)

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen_prompt["value"] = initial_prompt
            return {"status": "completed", "summary": "ok", "raw_output": "ok", "outcome": "done"}

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    monkeypatch.setattr(
        session_service,
        "parse_skill_slash_command",
        lambda content: parse_skill_slash_command(content, skill_roots=[skill_root]),
    )
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: scene_events.append(
            {"component": component, "phase": phase, "eventCode": event_code, **kwargs}
        ),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "/brt 设计斜杠 skill 调用"},
    )

    assert response.status_code == 202
    assert seen_prompt["value"] == "/brt 设计斜杠 skill 调用"
    slash_contexts = [context for context in seen_contexts if "## Slash Skill Context" in context]
    assert slash_contexts
    assert "Command: /brt" in slash_contexts[-1]
    assert "Ask one question at a time." in slash_contexts[-1]
    assert any(event["eventCode"] == "conversation.skill_command.routed" for event in scene_events)


def test_edit_resubmit_session_message_routes_slash_skill_into_scheduled_context(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:03:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-18T12:03:00",
                    "last_turn_status": "ready",
                    "messages": [
                        {"role": "user", "content": "原始需求", "timestamp": "2026-05-18T12:00:00"},
                        {"role": "assistant", "content": "原始回答", "timestamp": "2026-05-18T12:01:00"},
                        {"role": "user", "content": "后续追问", "timestamp": "2026-05-18T12:02:00"},
                        {"role": "assistant", "content": "后续回答", "timestamp": "2026-05-18T12:03:00"},
                    ],
                }
            ],
        },
    )
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nStop before implementation.\n",
        encoding="utf-8",
    )
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        session_service,
        "parse_skill_slash_command",
        lambda content: parse_skill_slash_command(content, skill_roots=[skill_root]),
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": "session-live-message-3",
            "content": "/brt 重新设计斜杠入口",
            "mentalModelEnabled": False,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "/brt 重新设计斜杠入口"
    persisted_skill = payload["messages"][-2]["metadata"]["slashSkillCommand"]
    assert persisted_skill["command"] == "brt"
    assert persisted_skill["skillName"] == "brt"
    assert persisted_skill["skillHash"]
    assert "content" not in persisted_skill
    assert len(scheduled_contexts) == 1
    invocation = scheduled_contexts[0]["skill_invocation"]
    assert invocation["command"] == "brt"
    assert invocation["args"] == "重新设计斜杠入口"
    assert invocation["skillName"] == "brt"

    session_service._set_session_running("session-live", False)
    session_service._clear_session_turn_control("session-live")
    session_service._clear_session_live_output("session-live")


def test_session_user_image_attachment_upload_and_submit_reaches_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["primary"].supports_image_input = True
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    seen: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen["initial_prompt"] = initial_prompt
            seen["attachments"] = list(attachments or [])
            return {
                "status": "completed",
                "summary": "我已经看到了图片。",
                "raw_output": "我已经看到了图片。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201
    attachment = upload_response.json()

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请看图", "attachmentIds": [attachment["artifactId"]], "mentalModelEnabled": False},
    )

    assert response.status_code == 202
    payload = response.json()
    user_message = payload["messages"][-2]
    assert user_message["attachments"][0]["artifactId"] == attachment["artifactId"]
    assert user_message["attachments"][0]["filename"] == "sketch.png"
    assert seen["initial_prompt"] == "请看图"
    seen_attachment = seen["attachments"][0]
    assert seen_attachment["artifactId"] == attachment["artifactId"]
    assert seen_attachment["dataUrl"].startswith("data:image/png;base64,")

    state = load_chat_state(tmp_path)
    stored_user = state["conversations"][0]["messages"][-2]
    assert stored_user["attachments"][0]["artifactId"] == attachment["artifactId"]
    assert "dataUrl" not in stored_user["attachments"][0]


def test_session_user_image_attachment_vision_intent_blocks_unsupported_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析这张图里有什么", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["currentPhase"] == "failed"
    assert "未确认支持图像输入" in payload["messages"][-1]["content"]
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["last_turn_status"] == "failed"


def test_session_user_image_attachment_picture_content_phrase_stays_vision_intent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "画面里有什么", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    assert "未确认支持图像输入" in response.json()["messages"][-1]["content"]


def test_session_user_image_attachment_vision_intent_reaches_supported_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["primary"].supports_image_input = True
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    seen: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen["initial_prompt"] = initial_prompt
            seen["attachments"] = list(attachments or [])
            return {"status": "completed", "summary": "看到了图片。", "raw_output": "看到了图片。", "outcome": "done"}

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析这张图", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    assert seen["initial_prompt"] == "分析这张图"
    assert seen["attachments"][0]["dataUrl"].startswith("data:image/png;base64,")


def test_session_user_image_attachment_edit_intent_routes_to_image2(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    captured: dict[str, object] = {}

    def fake_image2_generate_tool(**kwargs):
        captured.update(kwargs)
        session_service.append_session_assistant_artifact_message(
            "session-live",
            "已生成图片。",
            metadata={
                "kind": "image2_generation",
                "status": "succeeded",
                "imageUrl": "/api/sessions/session-live/artifacts/generated.png",
                "artifactId": "generated.png",
            },
        )
        return json.dumps({"ok": True, "status": "succeeded", "artifactId": "generated.png"})

    monkeypatch.setattr("tools.image2_tools.image2_generate_tool", fake_image2_generate_tool)

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201
    artifact_id = upload_response.json()["artifactId"]

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "把这张图改成 2D 卡通头像", "attachmentIds": [artifact_id]},
    )

    assert response.status_code == 202
    assert captured["prompt"] == "把这张图改成 2D 卡通头像"
    assert captured["input_artifact_id"] == artifact_id
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["last_turn_status"] == "ready"
    assert state["conversations"][0]["messages"][-1]["metadata"]["kind"] == "image2_generation"


def test_session_user_image_attachment_empty_text_asks_for_clarification(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["currentPhase"] == "ready"
    assert "分析这张图片" in payload["messages"][-1]["content"]


def test_session_user_image_attachment_rejects_unsupported_type(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/sessions/session-live/attachments",
        content=b"not an image",
        headers={"Content-Type": "text/plain", "X-Vibelution-Filename": "note.txt"},
    )

    assert response.status_code == 422


def test_session_user_image_attachment_rejects_spoofed_image_payload(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/sessions/session-live/attachments",
        content=b"not really a png",
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "spoof.png"},
    )

    assert response.status_code == 422


def test_submit_session_message_preserves_chinese_content_round_trip(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    content = "修复中文编码：runtime circuit breaker validation ping"

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": content},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == content
    assert payload["messages"][-1]["role"] == "assistant"
    assert payload["messages"][-1]["streaming"] is True

    state = load_chat_state(tmp_path)
    persisted = state["conversations"][0]["messages"][-1]
    assert persisted["role"] == "user"
    assert persisted["content"] == content

    workspace_log = tmp_path / "workspace" / "sessions" / "session-live" / "logs" / "conversation.jsonl"
    log_records = [json.loads(line) for line in workspace_log.read_text(encoding="utf-8").splitlines()]
    assert log_records[-1]["content"] == content


def test_submit_session_message_shows_waiting_live_message_while_turn_runs(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "检查为什么对话看起来卡住"},
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["currentPhase"] == "running"
        live_message = payload["messages"][-1]
        assert live_message["role"] == "assistant"
        assert live_message["streaming"] is True
        assert live_message["content"] == "正在准备对话上下文..."
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_submit_session_message_recovers_content_from_utf8_base64_fallback(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    content = "请继续检查中文输入链路"
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "???????:runtime circuit breaker validation ping", "contentUtf8Base64": encoded},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["content"] == content
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == "正在准备对话上下文..."
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["messages"][-1]["content"] == content
    assert _read_next_state_signals(tmp_path, session_id="session-live") == []


def test_submit_session_message_rejects_encoding_replacement_pollution(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "???????:runtime circuit breaker validation ping"},
    )

    assert response.status_code == 422
    assert "编码损坏" in response.json()["detail"]
    state = load_chat_state(tmp_path)
    assert [item["content"] for item in state["conversations"][0]["messages"]] == [
        "继续前端开发",
        "<think>internal</think>\n\n已经接到真实状态了。",
    ]


def test_submit_session_message_ignores_non_meaningful_user_message_for_prompt_and_task(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "继续前端开发",
            "goal": "继续前端开发",
            "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
            "default_file_context": "web/src/routes/ChatCodingRoute.tsx",
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "继续前端开发",
                "raw_output": "继续前端开发",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "?"},
    )

    assert response.status_code == 202
    assert captured["prompt"] == "继续前端开发"
    assert all(item["content"] != "?" for item in captured["seeded"])
    payload = response.json()
    assert payload["activeTask"]["goal"] == "继续前端开发"
    assert payload["activeTask"]["title"] == "继续前端开发"
    event_codes = [args[2] for args, _kwargs in recorded_events]
    assert "conversation.user_message_filtered" in event_codes


def test_submit_session_message_continue_uses_previous_meaningful_goal_not_punctuation(tmp_path, monkeypatch):
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "修复对话消息流程",
            "goal": "修复对话消息流程",
            "read_files": ["core/web/services/session_service.py"],
            "default_file_context": "core/web/services/session_service.py",
        },
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].append(
        {"role": "user", "content": "?", "timestamp": "2026-05-18T11:57:00"}
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "修复对话消息流程",
                "raw_output": "修复对话消息流程",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    assert captured["prompt"] == "修复对话消息流程"
    assert all(item["content"] != "?" for item in captured["seeded"])


def test_submit_session_message_does_not_promote_contextual_confirmation_to_task_goal(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "优化日志摘要入口",
            "goal": "优化日志摘要入口",
            "latest_summary": "已经形成日志摘要优化计划。",
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已开始按计划修改日志摘要入口。",
                "raw_output": "已开始按计划修改日志摘要入口。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "好的开始修改"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["activeTask"]["goal"] == "优化日志摘要入口"
    assert payload["activeTask"]["title"] != "好的开始修改"
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["active_task"]["goal"] == "优化日志摘要入口"


def test_submit_session_contextual_confirmation_preserves_action_intent_in_prompt(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "agent-avatar-task",
            "kind": "coding",
            "status": "editing",
            "title": "现在agent可以设置默认头像吗",
            "goal": "现在agent可以设置默认头像吗",
            "changed_files": ["workspace/avatars/avatars.json"],
            "latest_summary": "Agent 目前不能设置默认图片头像。要我现在开始实现吗？",
            "next_action": "",
            "metadata": {"outcome": "no_change"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "已开始实现 Agent 默认头像支持。",
                "raw_output": "已开始实现 Agent 默认头像支持。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "开始实现"},
    )

    assert response.status_code == 202
    assert "用户确认：开始实现" in captured["prompt"]
    assert "请基于已确认的当前目标继续执行：现在agent可以设置默认头像吗" in captured["prompt"]
    assert captured["prompt"] != "现在agent可以设置默认头像吗"
    payload = response.json()
    assert payload["activeTask"]["goal"] == "现在agent可以设置默认头像吗"
    assert payload["activeTask"]["title"] == "现在agent可以设置默认头像吗"


def test_submit_session_continue_recovers_context_when_active_task_goal_is_confirmation(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "好的开始修改",
            "goal": "好的开始修改",
            "read_files": ["core/web/services/runtime_scene_service.py"],
        },
    )
    state = load_chat_state(tmp_path)
    messages = state["conversations"][0]["messages"]
    messages.append(
        {
            "role": "user",
            "content": "检查日志系统摘要一致性并给出优化方案",
            "timestamp": "2026-05-18T11:57:00",
        }
    )
    messages.append(
        {
            "role": "assistant",
            "content": "建议先定位 summary 与 package_index 的生成链路，再补测试。",
            "timestamp": "2026-05-18T11:58:00",
        }
    )
    messages.append(
        {"role": "user", "content": "好的开始修改", "timestamp": "2026-05-18T11:59:00"}
    )
    messages.append(
        {
            "role": "assistant",
            "content": "已达到 Web Chat 任务级持续上限（4 轮），本次先暂停，避免后台无限运行。",
            "timestamp": "2026-05-18T12:00:00",
        }
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "已恢复到日志摘要一致性任务并完成收束。",
                "raw_output": "已恢复到日志摘要一致性任务并完成收束。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    prompt = str(captured["prompt"])
    assert "继续完成当前会话中尚未完成的真实用户目标" in prompt
    assert "检查日志系统摘要一致性并给出优化方案" in prompt
    assert "好的开始修改" in prompt
    assert prompt != "好的开始修改"


def test_edit_resubmit_session_message_recovers_content_from_utf8_base64_fallback(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    content = "编辑后保留中文"
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": "session-live-message-1",
            "content": "???????:runtime circuit breaker validation ping",
            "contentUtf8Base64": encoded,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["content"] == content
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == "正在准备对话上下文..."
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["messages"][-1]["content"] == content


def test_edit_resubmit_session_message_truncates_following_history_and_starts_turn(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:03:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-18T12:03:00",
                    "last_turn_status": "ready",
                    "messages": [
                        {"role": "user", "content": "原始需求", "timestamp": "2026-05-18T12:00:00"},
                        {"role": "assistant", "content": "原始回答", "timestamp": "2026-05-18T12:01:00"},
                        {"role": "user", "content": "后续追问", "timestamp": "2026-05-18T12:02:00"},
                        {"role": "assistant", "content": "后续回答", "timestamp": "2026-05-18T12:03:00"},
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    scheduled_contexts: list[dict] = []
    events: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: events.append(
            {"component": component, "phase": phase, "eventCode": event_code, **kwargs}
        ),
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": "session-live-message-3",
            "content": "编辑后的需求",
            "mentalModelEnabled": False,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["currentPhase"] == "running"
    assert [item["content"] for item in payload["messages"][:-1]] == ["原始需求", "原始回答", "编辑后的需求"]
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == "正在准备对话上下文..."
    assert len(scheduled_contexts) == 1
    assert scheduled_contexts[0]["user_message"] == "编辑后的需求"
    assert [item["content"] for item in scheduled_contexts[0]["history_messages"]] == ["原始需求", "原始回答"]
    assert scheduled_contexts[0]["mental_model_enabled"] is False
    state = load_chat_state(tmp_path)
    stored_messages = state["conversations"][0]["messages"]
    assert [item["content"] for item in stored_messages] == ["原始需求", "原始回答", "编辑后的需求"]
    assert any(event["eventCode"] == "conversation.message_edited_resubmitted" for event in events)
    signals = _read_next_state_signals(tmp_path, session_id="session-live")
    assert any(item["kind"] == "assistant_output_edited" and item["turnId"] for item in signals)

    session_service._set_session_running("session-live", False)
    session_service._clear_session_turn_control("session-live")
    session_service._clear_session_live_output("session-live")


def test_edit_resubmit_session_message_allows_latest_user_message(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:03:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-18T12:03:00",
                    "last_turn_status": "ready",
                    "messages": [
                        {"role": "user", "content": "原始需求", "timestamp": "2026-05-18T12:00:00"},
                        {"role": "assistant", "content": "原始回答", "timestamp": "2026-05-18T12:01:00"},
                        {"role": "user", "content": "后续追问", "timestamp": "2026-05-18T12:02:00"},
                        {"role": "assistant", "content": "后续回答", "timestamp": "2026-05-18T12:03:00"},
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    scheduled_contexts: list[dict] = []
    events: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: events.append(
            {"component": component, "phase": phase, "eventCode": event_code, **kwargs}
        ),
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": "session-live-message-3",
            "content": "编辑最新的需求",
            "mentalModelEnabled": False,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert [item["content"] for item in payload["messages"][:-1]] == ["原始需求", "原始回答", "编辑最新的需求"]
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == "正在准备对话上下文..."
    assert len(scheduled_contexts) == 1
    assert scheduled_contexts[0]["user_message"] == "编辑最新的需求"
    assert [item["content"] for item in scheduled_contexts[0]["history_messages"]] == ["原始需求", "原始回答"]
    assert any(event["eventCode"] == "conversation.message_edited_resubmitted" for event in events)

    session_service._set_session_running("session-live", False)
    session_service._clear_session_turn_control("session-live")
    session_service._clear_session_live_output("session-live")


def test_edit_resubmit_session_message_rejects_assistant_message(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    before_state = load_chat_state(tmp_path)

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={"messageId": "session-live-message-2", "content": "不能编辑助手消息"},
    )

    assert response.status_code == 422
    assert load_chat_state(tmp_path) == before_state


def test_edit_resubmit_session_message_rejects_non_latest_user_message(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    state = load_chat_state(tmp_path)
    conversation = state["conversations"][0]
    conversation["messages"].extend(
        [
            {"role": "user", "content": "后续追问", "timestamp": "2026-05-18T12:02:00"},
            {"role": "assistant", "content": "后续回答", "timestamp": "2026-05-18T12:03:00"},
        ]
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    before_state = load_chat_state(tmp_path)
    rejected_events: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: rejected_events.append({"args": args, "kwargs": kwargs}) or {"accepted": True},
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={"messageId": "session-live-message-1", "content": "不能改旧消息"},
    )

    assert response.status_code == 422
    assert load_chat_state(tmp_path) == before_state
    assert any(
        event["args"][:3] == ("conversation", "message_edit_resubmit_rejected", "conversation.message_edit_resubmit_rejected")
        for event in rejected_events
    )


def test_chat_turn_registers_as_work_run_until_finished(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "解释当前状态"},
    )

    assert response.status_code == 202
    running_summary = runtime_service.get_runtime_summary()
    active_chat = running_summary["workRuns"]["active"]["chat_turn"]
    assert active_chat["runKind"] == "chat_turn"
    assert active_chat["status"] == "running"
    assert active_chat["sessionId"] == "session-live"
    assert active_chat["leases"] == ["readonly_chat"]

    turn_id = active_chat["runId"]
    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "已解释当前状态。",
            "raw_output": "已解释当前状态。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
        },
        turn_id=turn_id,
    )
    session_service._set_session_running("session-live", False, turn_id=turn_id)

    finished_summary = runtime_service.get_runtime_summary()
    assert finished_summary["workRuns"]["active"]["chat_turn"] is None
    latest_chat = finished_summary["workRuns"]["latest"]["chat_turn"]
    assert latest_chat["runId"] == turn_id
    assert latest_chat["status"] == "completed"


def test_persist_turn_result_blocks_phantom_image_generation_success(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    turn_id = "turn-image2"
    session_service._set_session_running("session-live", True, turn_id=turn_id)
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append({"args": args, "kwargs": kwargs}) or {"accepted": True},
    )

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "已生成图片。",
            "raw_output": "已生成图片。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
        },
        turn_id=turn_id,
    )
    session_service._set_session_running("session-live", False, turn_id=turn_id)

    conversation = load_chat_state(tmp_path)["conversations"][0]
    message = conversation["messages"][-1]
    assert message["role"] == "assistant"
    assert "没有实际生成新的图片" in message["content"]
    assert not message.get("tool_calls")
    assert message.get("metadata") is None
    assert conversation["last_turn_status"] == "failed"
    assert any(
        event["args"][:3]
        == ("conversation", "turn_phantom_image_success_blocked", "conversation.turn.phantom_image_success_blocked")
        for event in events
    )


def test_different_agent_sessions_run_chat_turns_concurrently(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-concurrent")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)

    started_sessions: set[str] = set()
    started_lock = threading.Lock()
    both_started = threading.Event()
    release = threading.Event()

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            session_id = alpha["id"] if "alpha" in prompt else beta["id"]
            with started_lock:
                started_sessions.add(session_id)
                if started_sessions == {alpha["id"], beta["id"]}:
                    both_started.set()
            assert release.wait(2.0)
            return {
                "status": "completed",
                "summary": f"{session_id} done",
                "raw_output": f"{session_id} done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        first = session_service.submit_session_message(alpha["id"], "alpha 并行任务")
        second = session_service.submit_session_message(beta["id"], "beta 并行任务")

        assert first["currentPhase"] == "running"
        assert second["currentPhase"] == "running"
        assert both_started.wait(1.0), "expected different agents to overlap"
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert session_service.get_session_detail(alpha["id"])["messages"][-1]["content"] == f"{alpha['id']} done"
    assert session_service.get_session_detail(beta["id"])["messages"][-1]["content"] == f"{beta['id']} done"


def test_same_agent_sessions_queue_chat_turns_serially(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-queue")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()
    prompts: list[str] = []

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            prompts.append(prompt)
            if "alpha" in prompt:
                first_started.set()
                assert release_first.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "alpha done",
                    "raw_output": "alpha done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            second_started.set()
            assert release_second.wait(2.0)
            return {
                "status": "completed",
                "summary": "beta done",
                "raw_output": "beta done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        first = session_service.submit_session_message(alpha["id"], "alpha 串行任务")
        assert first["currentPhase"] == "running"
        assert first_started.wait(1.0)

        second = session_service.submit_session_message(beta["id"], "beta 串行任务")
        assert second["currentPhase"] == "queued"
        assert not second_started.wait(0.2)

        release_first.set()
        assert second_started.wait(1.0), "expected queued turn to start after first turn"
    finally:
        release_first.set()
        release_second.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert prompts == ["alpha 串行任务", "beta 串行任务"]
    assert session_service.get_session_detail(alpha["id"])["messages"][-1]["content"] == "alpha done"
    assert session_service.get_session_detail(beta["id"])["messages"][-1]["content"] == "beta done"


def test_stopping_queued_same_agent_turn_prevents_later_start(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-stop-queued")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()
    prompts: list[str] = []

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            prompts.append(prompt)
            if "alpha" in prompt:
                first_started.set()
                assert release_first.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "alpha done",
                    "raw_output": "alpha done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            second_started.set()
            assert release_second.wait(2.0)
            return {
                "status": "completed",
                "summary": "beta done",
                "raw_output": "beta done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        first = session_service.submit_session_message(alpha["id"], "alpha 串行任务")
        assert first["currentPhase"] == "running"
        assert first_started.wait(1.0)

        second = session_service.submit_session_message(beta["id"], "beta 串行任务")
        assert second["currentPhase"] == "queued"
        assert not second_started.wait(0.2)

        stopped = session_service.request_stop_session_turn(beta["id"])
        assert stopped["currentPhase"] == "ready"
        assert "本轮已按请求停止" in stopped["messages"][-1]["content"]

        release_first.set()
        assert not second_started.wait(0.5), "stopped queued turn must not be started after the active turn releases"
    finally:
        release_first.set()
        release_second.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert prompts == ["alpha 串行任务"]
    beta_detail = session_service.get_session_detail(beta["id"])
    assert beta_detail["messages"][-1]["role"] == "assistant"
    assert "本轮已按请求停止" in beta_detail["messages"][-1]["content"]


def test_shutdown_stops_queued_same_agent_turn_before_it_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-shutdown-queued")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()
    prompts: list[str] = []

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            prompts.append(prompt)
            if "alpha" in prompt:
                first_started.set()
                assert release_first.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "alpha done",
                    "raw_output": "alpha done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            second_started.set()
            assert release_second.wait(2.0)
            return {
                "status": "completed",
                "summary": "beta done",
                "raw_output": "beta done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        session_service.submit_session_message(alpha["id"], "alpha 关闭前任务")
        assert first_started.wait(1.0)
        queued = session_service.submit_session_message(beta["id"], "beta 关闭前任务")
        assert queued["currentPhase"] == "queued"

        stopped = runtime_service._stop_active_chat_turns_before_shutdown()
        assert {item["sessionId"] for item in stopped} == {alpha["id"], beta["id"]}
        assert {item["status"] for item in stopped} == {"stopped"}

        release_first.set()
        assert not second_started.wait(0.5), "shutdown-stopped queued turn must not start after active turn releases"
    finally:
        release_first.set()
        release_second.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert prompts == ["alpha 关闭前任务"]
    assert session_service.get_session_detail(alpha["id"])["currentPhase"] == "ready"
    assert session_service.get_session_detail(beta["id"])["currentPhase"] == "ready"


def test_runtime_summary_exposes_parallel_chat_turn_active_items(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_manager_snapshot", lambda: {})
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-active-items")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)

    started_sessions: set[str] = set()
    started_lock = threading.Lock()
    both_started = threading.Event()
    release = threading.Event()

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            session_id = alpha["id"] if "alpha" in prompt else beta["id"]
            with started_lock:
                started_sessions.add(session_id)
                if started_sessions == {alpha["id"], beta["id"]}:
                    both_started.set()
            assert release.wait(2.0)
            return {
                "status": "completed",
                "summary": f"{session_id} done",
                "raw_output": f"{session_id} done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        session_service.submit_session_message(alpha["id"], "alpha 并行任务")
        session_service.submit_session_message(beta["id"], "beta 并行任务")
        assert both_started.wait(1.0), "expected different agents to overlap"

        payload = runtime_service.get_runtime_summary()
        chat_items = payload["workRuns"]["activeItems"]["chat_turn"]
        assert {item["sessionId"] for item in chat_items} == {alpha["id"], beta["id"]}
        assert {item["status"] for item in chat_items} == {"running"}
        assert payload["lifecycleProof"]["activeWorkRuns"]["count"] == 2
        assert payload["lifecycleProof"]["activeWorkRuns"]["kinds"] == ["chat_turn", "chat_turn"]
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_runtime_summary_exposes_queued_chat_turn_active_item(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_manager_snapshot", lambda: {})
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-queued-items")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            if "alpha" in prompt:
                first_started.set()
                assert release_first.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "alpha done",
                    "raw_output": "alpha done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            second_started.set()
            assert release_second.wait(2.0)
            return {
                "status": "completed",
                "summary": "beta done",
                "raw_output": "beta done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        session_service.submit_session_message(alpha["id"], "alpha 串行任务")
        assert first_started.wait(1.0)
        session_service.submit_session_message(beta["id"], "beta 串行任务")

        payload = runtime_service.get_runtime_summary()
        chat_items = sorted(
            payload["workRuns"]["activeItems"]["chat_turn"],
            key=lambda item: item["sessionId"],
        )
        assert {item["sessionId"] for item in chat_items} == {alpha["id"], beta["id"]}
        assert {item["status"] for item in chat_items} == {"queued", "running"}
        assert not second_started.wait(0.2)
    finally:
        release_first.set()
        release_second.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_submit_session_message_records_chat_turn_started_scene_event(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "解释当前状态"},
    )

    assert response.status_code == 202
    started_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn", "conversation.turn.started")
    ]
    assert started_events
    fields = started_events[-1][1]["fields"]
    active_chat = session_service.load_chat_turn_work_run_summary()["active"]
    assert fields["sessionId"] == "session-live"
    assert fields["turnId"] == active_chat["runId"]
    assert fields["leaseCount"] == 1


def test_edit_resubmit_records_chat_turn_started_scene_event(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={"messageId": "session-live-message-1", "content": "编辑后的需求"},
    )

    assert response.status_code == 202
    started_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn", "conversation.turn.started")
    ]
    assert started_events
    fields = started_events[-1][1]["fields"]
    active_chat = session_service.load_chat_turn_work_run_summary()["active"]
    assert fields["sessionId"] == "session-live"
    assert fields["turnId"] == active_chat["runId"]
    assert fields["userMessageChars"] == len("编辑后的需求")


def test_run_session_turn_records_agent_started_scene_event(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class DummyAgent:
        def set_turn_interrupt_checker(self, checker):
            self.checker = checker

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已解释当前状态。",
                "raw_output": "已解释当前状态。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda workspace_path=None: DummyAgent())
    turn_control = session_service._create_session_turn_control("session-live")
    session_service._set_session_running("session-live", True, turn_id=turn_control.turn_id, leases=["readonly_chat"])
    try:
        session_service._run_session_turn(
            {
                "session_id": "session-live",
                "turn_id": turn_control.turn_id,
                "turn_control": turn_control,
                "user_message": "解释当前状态",
                "history_messages": [],
                "mental_model_enabled": False,
            }
        )
    finally:
        session_service._set_session_running("session-live", False, turn_id=turn_control.turn_id)
        session_service._clear_session_turn_control("session-live", turn_id=turn_control.turn_id)

    agent_created_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn_agent_created", "conversation.turn.agent_created")
    ]
    assert agent_created_events
    fields = agent_created_events[-1][1]["fields"]
    assert fields["sessionId"] == "session-live"
    assert fields["turnId"] == turn_control.turn_id
    assert fields["agentType"] == "DummyAgent"


def test_runtime_summary_exposes_work_run_kinds(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    self_evolution_control_service.persist_manager_run_snapshot(
        "self",
        {
            "runId": "self-work-run",
            "status": "running",
            "startedAt": "2026-05-21T00:00:00",
            "updatedAt": "2026-05-21T00:00:00",
        },
        active_run_id="self-work-run",
    )
    supervised_control_service.persist_manager_run_snapshot(
        "supervised",
        {
            "runId": "supervised-work-run",
            "status": "done",
            "startedAt": "2026-05-21T00:00:00",
            "updatedAt": "2026-05-21T00:01:00",
        },
        active_run_id="",
    )
    supervised_worktree_evolution_service._persist_snapshot(
        {
            "runId": "swte-work-run",
            "runKind": "supervised_worktree_evolution_run",
            "status": "running",
            "startedAt": "2026-05-21T00:00:00",
            "updatedAt": "2026-05-21T00:02:00",
        },
        active_run_id="swte-work-run",
    )

    payload = runtime_service.get_runtime_summary()

    assert set(payload["workRuns"]["active"]) == {
        "chat_turn",
        "chat_room_round",
        "self_evolution_run",
        "supervised_evolution_run",
        "supervised_worktree_evolution_run",
    }
    assert payload["workRuns"]["active"]["chat_room_round"] is None
    assert payload["workRuns"]["active"]["self_evolution_run"]["runKind"] == "self_evolution_run"
    assert payload["workRuns"]["active"]["self_evolution_run"]["leases"] == [
        "evolution_transaction",
        "worktree_write",
        "memory_write",
    ]
    assert payload["workRuns"]["latest"]["supervised_evolution_run"]["runKind"] == "supervised_evolution_run"
    assert payload["workRuns"]["latest"]["supervised_evolution_run"]["leases"] == ["evaluation"]
    assert payload["workRuns"]["active"]["supervised_worktree_evolution_run"]["runKind"] == "supervised_worktree_evolution_run"
    assert payload["workRuns"]["active"]["supervised_worktree_evolution_run"]["leases"] == [
        "evaluation",
        "worktree_write",
    ]


def test_submit_session_message_captures_chat_review_candidate(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "结论：已经定位到网页聊天提交流程。下一步我会把采样和审核接上。",
                "raw_output": "结论：已经定位到网页聊天提交流程。下一步我会把采样和审核接上。",
                "tool_call_count": 2,
                "tool_trace": [
                    {"name": "read_file_tool"},
                    {"function": {"name": "apply_patch_tool"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续把网页聊天里的 case 抽出来给监督进化用"},
    )

    assert response.status_code == 202
    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.status_code == 200
    payload = queue_response.json()
    assert payload["pendingCount"] == 1
    assert payload["items"][0]["sessionId"] == "session-live"
    assert payload["items"][0]["qualitySignals"]


def test_session_adds_current_conversation_to_chat_review_queue(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    response = client.post("/api/sessions/session-live/chat-review-candidate")

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["sessionId"] == "session-live"
    assert payload["turnCount"] == 1
    assert payload["candidateId"] == "session-live_t0001_0001"
    assert "监督" in payload["summary"] or "supervised" in payload["summary"].lower()

    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["pendingCount"] == 1
    assert queue_payload["items"][0]["candidateId"] == "session-live_t0001_0001"
    assert queue_payload["items"][0]["status"] == "pending"
    assert recorded_scene_events
    assert recorded_scene_events[-1][0][:3] == (
        "chat_review",
        "session_candidate_created",
        "chat_review.session_candidate.created",
    )


def test_session_add_to_chat_review_rejects_empty_conversation(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"] = [
        {
            "role": "user",
            "content": "只有用户消息",
            "timestamp": "2026-05-18T11:55:00",
        }
    ]
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)

    response = client.post("/api/sessions/session-live/chat-review-candidate")

    assert response.status_code == 422
    assert "完整" in response.json()["detail"] or "complete" in response.json()["detail"].lower()
    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.json()["pendingCount"] == 0


def test_session_add_to_chat_review_rejects_duplicate_snapshot(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)

    first_response = client.post("/api/sessions/session-live/chat-review-candidate")
    second_response = client.post("/api/sessions/session-live/chat-review-candidate")

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert "已经" in second_response.json()["detail"] or "already" in second_response.json()["detail"].lower()
    queue_response = client.get("/api/evolution/chat-review")
    queue_payload = queue_response.json()
    assert queue_payload["pendingCount"] == 1
    assert [item["candidateId"] for item in queue_payload["items"]] == ["session-live_t0001_0001"]


def test_submit_session_message_rejects_busy_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    before_state = load_chat_state(tmp_path)
    before_messages = list(before_state["conversations"][0]["messages"])

    session_service._set_session_running("session-live", True)
    session_service._WORK_RUN_STORE.persist_snapshot(
        "chat_turn",
        {
            "runId": "existing-chat-turn",
            "runKind": "chat_turn",
            "track": "dialogue",
            "sessionId": "session-live",
            "status": "running",
            "currentPhase": "running",
            "leases": ["readonly_chat"],
            "userMessage": "上一轮仍在运行",
            "startedAt": "2026-05-18T11:59:00",
            "updatedAt": "2026-05-18T12:00:00",
            "finishedAt": "",
        },
        active_run_id="existing-chat-turn",
    )
    try:
        response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "继续修复 web/src/routes/ChatCodingRoute.tsx"},
        )
    finally:
        session_service._set_session_running("session-live", False)

    assert response.status_code == 409
    assert "运行" in response.json()["detail"] or "running" in response.json()["detail"].lower()
    after_state = load_chat_state(tmp_path)
    assert after_state["conversations"][0]["messages"] == before_messages
    active_run = session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn")
    assert active_run["runId"] == "existing-chat-turn"
    assert active_run["userMessage"] == "上一轮仍在运行"


def test_submit_session_message_rejects_blank_message_without_mutating_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    before_state = load_chat_state(tmp_path)
    before_messages = list(before_state["conversations"][0]["messages"])
    before_status = before_state["conversations"][0]["last_turn_status"]

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": " \n\t "},
    )

    assert response.status_code == 422
    assert "请输入" in response.json()["detail"] or "enter a message" in response.json()["detail"].lower()
    after_state = load_chat_state(tmp_path)
    assert after_state["conversations"][0]["messages"] == before_messages
    assert after_state["conversations"][0]["last_turn_status"] == before_status
    assert session_service._is_session_running("session-live") is False
    assert session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn") is None


def test_submit_session_message_records_provider_failure_next_state_signal(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class ProviderFailureAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": "litellm.BadGatewayError: BadGatewayError: OpenAIException - {\"error\":{\"message\":\"Upstream request failed\"}}",
                "raw_output": "litellm.BadGatewayError: BadGatewayError: OpenAIException - {\"error\":{\"message\":\"Upstream request failed\"}}",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailureAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续检查上游失败"},
    )

    assert response.status_code == 202
    signals = _read_next_state_signals(tmp_path, session_id="session-live")
    assert any(item["kind"] == "provider_failure" for item in signals)
    assert any(item["relatedEventCode"] == "conversation.turn_error" for item in signals)


def test_capture_session_ui_stream_records_tool_error_next_state_signal(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live", turn_id="turn-tool")
    with session_service._capture_session_ui_stream("session-live", capture):
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_ERROR,
            {"name": "read_file_tool", "error": "permission denied"},
        )

    signals = _read_next_state_signals(tmp_path, session_id="session-live", turn_id="turn-tool")
    assert any(item["kind"] == "tool_error" for item in signals)
    assert any(item["relatedEventCode"] == "conversation.tool_error" for item in signals)
    assert any(item["metadata"]["toolName"] == "read_file_tool" for item in signals)


def test_turn_circuit_breaker_records_next_state_signal_with_turn_id(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )

    session_service._record_session_turn_circuit_breaker_event(
        "session-live",
        {
            "error": "litellm.BadGatewayError: BadGatewayError: OpenAIException - {\"error\":{\"message\":\"Upstream request failed\"}}",
            "llm_failure": {
                "category": "server_error",
                "retryable": True,
                "attempts": 5,
                "max_attempts": 5,
                "consecutive_failures": 5,
                "stop_reason": "retry budget exhausted",
            },
        },
        turn_id="turn-42",
        turn_index=2,
    )

    signals = _read_next_state_signals(tmp_path, session_id="session-live", turn_id="turn-42")
    assert any(item["kind"] == "provider_failure" for item in signals)
    assert any(item["relatedEventCode"] == "conversation.turn_circuit_breaker" for item in signals)
    assert any(item["metadata"]["continuationTurn"] == 2 for item in signals)


def test_submit_session_message_recovers_when_scheduler_fails(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    def fail_schedule(context):
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr(session_service, "_schedule_session_turn", fail_schedule)

    with pytest.raises(RuntimeError, match="scheduler unavailable"):
        session_service.submit_session_message("session-live", "继续检查调度失败恢复")

    payload = session_service.get_session_detail("session-live")
    assert payload["currentPhase"] == "failed"
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "继续检查调度失败恢复"
    assert payload["messages"][-1]["role"] == "assistant"
    assert "scheduler unavailable" in payload["messages"][-1]["content"]
    assert payload["lastTurnError"] is None
    assert session_service._is_session_running("session-live") is False
    assert session_service._get_session_turn_control("session-live") is None
    assert session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn") is None
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run["status"] == "failed"
    assert latest_run["errorType"] == "RuntimeError"
    assert latest_run["userMessage"] == "继续检查调度失败恢复"
    assert "scheduler unavailable" in latest_run["error"]
    event_codes = [args[2] for args, _kwargs in recorded_scene_events if len(args) >= 3]
    assert "conversation.turn.started" in event_codes
    assert "conversation.turn.scheduled" in event_codes
    assert "conversation.turn.failure_persisted" in event_codes


def test_submit_session_message_write_intent_rejects_self_evolution_lease(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    self_snapshot = {
        "runId": "web-self-active-for-chat",
        "runKind": "self_evolution_run",
        "status": "running",
        "leases": ["evolution_transaction", "worktree_write", "memory_write"],
        "startedAt": "2026-05-21T00:00:00",
        "updatedAt": "2026-05-21T00:00:00",
    }
    self_evolution_control_service.persist_manager_run_snapshot("self", self_snapshot, active_run_id=self_snapshot["runId"])

    readonly = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "解释当前状态"},
    )

    assert readonly.status_code == 202
    session_service._set_session_running("session-live", False)
    session_service._clear_session_turn_control("session-live")

    write_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复这个 bug", "writeIntent": True},
    )

    assert write_response.status_code == 409
    assert "resource" in write_response.json()["detail"].lower() or "资源" in write_response.json()["detail"]


def test_request_stop_session_turn_persists_stop_snapshot_and_releases_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        submit_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "先继续分析当前对话提交流程"},
        )

        assert submit_response.status_code == 202
        running_payload = submit_response.json()
        assert running_payload["currentPhase"] == "running"
        assert running_payload["stopRequested"] is False

        stop_response = client.post("/api/sessions/session-live/stop")

        assert stop_response.status_code == 202
        payload = stop_response.json()
        assert payload["currentPhase"] == "ready"
        assert payload["stopRequested"] is False
        assert payload["messages"][-1]["role"] == "assistant"
        assert "本轮已按请求停止" in payload["messages"][-1]["content"]
        stop_signals = _read_next_state_signals(tmp_path, session_id="session-live")
        assert any(item["kind"] == "user_stops" and item["turnId"] for item in stop_signals)

        continue_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "继续"},
        )
        assert continue_response.status_code == 202
        assert continue_response.json()["currentPhase"] == "running"
        continue_signals = _read_next_state_signals(tmp_path, session_id="session-live")
        assert any(item["kind"] == "user_continues" for item in continue_signals)
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")


def test_request_stop_session_turn_reuses_active_work_run_when_controller_is_missing(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    scene_events = []

    def record_scene_event(component, phase, event_code, **kwargs):
        scene_events.append((component, phase, event_code, kwargs))
        return {"accepted": True}

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", record_scene_event)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )
    session_service._set_session_running("session-live", True)
    session_service._clear_session_turn_control("session-live")
    session_service._WORK_RUN_STORE.persist_snapshot(
        "chat_turn",
        {
            "runId": "existing-chat-turn",
            "runKind": "chat_turn",
            "track": "dialogue",
            "sessionId": "session-live",
            "status": "running",
            "currentPhase": "running",
            "leases": ["readonly_chat"],
            "userMessage": "上一轮控制器丢失但 WorkRun 仍活跃",
            "startedAt": "2026-05-18T11:59:00",
            "updatedAt": "2026-05-18T12:00:00",
            "finishedAt": "",
        },
        active_run_id="existing-chat-turn",
    )

    try:
        stop_response = client.post("/api/sessions/session-live/stop")

        assert stop_response.status_code == 202
        payload = stop_response.json()
        assert payload["currentPhase"] == "ready"
        assert payload["stopRequested"] is False
        assert "本轮已按请求停止" in payload["messages"][-1]["content"]
        assert session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn") is None
        latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
        assert latest_run["runId"] == "existing-chat-turn"
        assert latest_run["status"] == "stopped"
        assert latest_run["finishedAt"]
        assert any(
            event[2] == "conversation.turn_control_recovered"
            and event[3]["fields"]["turnId"] == "existing-chat-turn"
            and event[3]["fields"]["reusedActiveRun"] is True
            for event in scene_events
        )
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_stop_requested_turn_persists_visible_stop_message(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    started = threading.Event()
    finished = threading.Event()
    worker_threads = []

    class StoppableAgent:
        def __init__(self):
            self.stop_checker = None

        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def set_turn_interrupt_checker(self, checker):
            self.stop_checker = checker

        def run_single_turn(self, initial_prompt=None):
            started.set()
            for _ in range(200):
                reason = self.stop_checker() if callable(self.stop_checker) else ""
                if reason:
                    return {
                        "status": "stopped",
                        "summary": "",
                        "raw_output": "",
                        "stop_requested": True,
                        "stop_reason": reason,
                        "tool_call_count": 0,
                        "tool_trace": [],
                    }
                time.sleep(0.01)
            return {
                "status": "completed",
                "summary": "不该走到这里。",
                "raw_output": "不该走到这里。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: StoppableAgent())

    def run_async(context):
        def _worker():
            try:
                session_service._run_session_turn(context)
            finally:
                finished.set()

        thread = threading.Thread(target=_worker, daemon=True)
        worker_threads.append(thread)
        thread.start()

    monkeypatch.setattr(session_service, "_schedule_session_turn", run_async)

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续推进当前网页会话的终止能力"},
    )

    assert response.status_code == 202
    assert started.wait(1.0), "expected the background turn to start"

    stop_response = client.post("/api/sessions/session-live/stop")

    assert stop_response.status_code == 202
    assert stop_response.json()["currentPhase"] == "ready"
    assert finished.wait(2.0), "expected the stopped turn to finish"

    for thread in worker_threads:
        thread.join(timeout=0.2)

    detail_response = client.get("/api/sessions/session-live")
    assert detail_response.status_code == 200
    payload = detail_response.json()
    assert payload["currentPhase"] == "ready"
    assert payload["stopRequested"] is False
    assert payload["messages"][-1]["role"] == "assistant"
    assert "本轮已按请求停止" in payload["messages"][-1]["content"]


def test_stop_session_turn_persists_partial_snapshot_and_allows_immediate_continue(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "chat-stop-resume",
            "kind": "coding",
            "status": "reading",
            "title": "修复 Web Chat 停止恢复",
            "goal": "修复 Web Chat 停止恢复",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "已定位停止按钮问题。",
            "updated_at": "2026-05-20T16:24:53",
        },
    )
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    submit_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复停止恢复"},
    )
    assert submit_response.status_code == 202
    old_control = session_service._get_session_turn_control("session-live")
    assert old_control is not None

    session_service._set_session_live_output(
        "session-live",
        thought="我已经定位到 stop checker。",
        content="已完成一部分：停止请求进入后会设置 stop flag。",
        tool_calls=[{"name": "read_file_tool", "status": "done", "summary": "session_service.py"}],
    )

    stop_response = client.post("/api/sessions/session-live/stop")
    assert stop_response.status_code == 202
    stopped_payload = stop_response.json()
    assert stopped_payload["currentPhase"] == "ready"
    assert stopped_payload["stopRequested"] is False
    assert "已完成一部分" in stopped_payload["messages"][-1]["content"]
    assert "本轮已按请求停止" in stopped_payload["messages"][-1]["content"]
    assert stopped_payload["messages"][-1]["thought"] == "我已经定位到 stop checker。"
    assert stopped_payload["messages"][-1]["toolCalls"][0]["name"] == "read_file_tool"

    continue_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )
    assert continue_response.status_code == 202
    new_control = session_service._get_session_turn_control("session-live")
    assert new_control is not None
    assert new_control.turn_id != old_control.turn_id

    session_service._clear_session_turn_control("session-live", turn_id=old_control.turn_id)
    assert session_service._get_session_turn_control("session-live").turn_id == new_control.turn_id

    session_service._set_session_running("session-live", False, turn_id=old_control.turn_id)
    assert session_service._is_session_running("session-live") is True

    session_service._set_session_running("session-live", False, turn_id=new_control.turn_id)
    session_service._clear_session_turn_control("session-live", turn_id=new_control.turn_id)


def test_stale_stopped_turn_does_not_run_after_immediate_continue(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    scheduled_contexts = []
    stale_agent_called = False

    class StaleAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def set_turn_interrupt_checker(self, checker):
            self.stop_checker = checker

        def run_single_turn(self, initial_prompt=None):
            nonlocal stale_agent_called
            stale_agent_called = True
            return {
                "status": "completed",
                "summary": "旧轮结果不应该写入当前会话。",
                "raw_output": "旧轮结果不应该写入当前会话。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: StaleAgent())

    try:
        first_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第一轮需要停止"},
        )
        assert first_response.status_code == 202
        assert len(scheduled_contexts) == 1

        stop_response = client.post("/api/sessions/session-live/stop")
        assert stop_response.status_code == 202

        continue_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第二轮已经开始"},
        )
        assert continue_response.status_code == 202
        assert continue_response.json()["currentPhase"] == "running"
        assert len(scheduled_contexts) == 2

        session_service._run_session_turn(scheduled_contexts[0])

        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert stale_agent_called is False
        assert payload["currentPhase"] == "running"
        assert payload["messages"][-2]["role"] == "user"
        assert payload["messages"][-2]["content"] == "第二轮已经开始"
        assert payload["messages"][-1]["role"] == "assistant"
        assert payload["messages"][-1]["streaming"] is True
        assert payload["messages"][-1]["content"] == "正在准备对话上下文..."
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_stop_during_agent_call_does_not_record_late_completed_result(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    lifecycle_events = []

    def record_lifecycle_event(session_id, phase, **kwargs):
        lifecycle_events.append(
            {
                "session_id": session_id,
                "phase": phase,
                "turn_id": kwargs.get("turn_id", ""),
                "outcome": kwargs.get("outcome", ""),
                "fields": dict(kwargs.get("fields") or {}),
            }
        )

    class LateCompletedAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def set_turn_interrupt_checker(self, checker):
            self.stop_checker = checker

        def run_single_turn(self, initial_prompt=None):
            control = session_service._get_session_turn_control("session-live")
            assert control is not None
            control.request_stop("操作者请求停止当前轮。")
            return {
                "status": "completed",
                "summary": "停止后的迟到完成结果不应该落盘。",
                "raw_output": "停止后的迟到完成结果不应该落盘。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        record_lifecycle_event,
    )
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: LateCompletedAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    try:
        response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "这轮会在模型调用期间被停止"},
        )

        assert response.status_code == 202
        latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert latest_run["status"] == "stopped_by_user"
        assert payload["currentPhase"] == "ready"
        assert "本轮已按请求停止" in payload["messages"][-1]["content"]
        assert "迟到完成结果" not in payload["messages"][-1]["content"]
        assert not any(
            event["phase"] in {"agent_turn_returned", "terminal_result"} and event["outcome"] == "completed"
            for event in lifecycle_events
        )
        assert any(
            event["phase"] == "stop_observed"
            and event["outcome"] == "stopped"
            and event["fields"].get("stage") == "agent_return"
            for event in lifecycle_events
        )
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_stale_turn_live_output_does_not_overwrite_new_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        first_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第一轮需要停止"},
        )
        assert first_response.status_code == 202
        old_control = session_service._get_session_turn_control("session-live")
        assert old_control is not None

        stop_response = client.post("/api/sessions/session-live/stop")
        assert stop_response.status_code == 202

        continue_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第二轮已经开始"},
        )
        assert continue_response.status_code == 202
        new_control = session_service._get_session_turn_control("session-live")
        assert new_control is not None

        session_service._set_session_live_output(
            "session-live",
            turn_id=new_control.turn_id,
            content="新轮正在输出。",
        )
        session_service._set_session_live_output(
            "session-live",
            turn_id=old_control.turn_id,
            content="旧轮迟到输出，不应该可见。",
        )

        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["messages"][-1]["streaming"] is True
        assert payload["messages"][-1]["content"] == "新轮正在输出。"
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_session_detail_includes_live_thought_draft(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        thought="先把这轮的思考过程挂进消息卡片。",
        mental_snapshot={
            "mood": "专注",
            "feeling": "链路已经接近打通。",
            "whisper": "再把默认折叠状态接上。",
            "cognitiveState": "productive",
        },
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["thought"] == "先把这轮的思考过程挂进消息卡片。"
    assert payload["messages"][-1]["mentalSnapshot"]["mood"] == "专注"


def test_session_detail_hides_partial_state_live_answer(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        content="<state",
        tool_calls=[{"name": "read_file_tool", "status": "running"}],
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == ""
    assert payload["messages"][-1]["toolCalls"] == [
        {"name": "read_file_tool", "status": "running"}
    ]


def test_session_detail_hides_dsml_and_lone_angle_live_answer(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        content="<state>\n{}\n</｜｜DSML｜｜parameter>\n</invoke>\n</｜｜DSML｜｜tool_calls>\n<",
        thought="</invoke>\n<",
        tool_calls=[{"name": "spawn_agent_tool", "status": "running"}],
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == ""
    assert "thought" not in payload["messages"][-1]
    assert payload["messages"][-1]["toolCalls"] == [
        {"name": "spawn_agent_tool", "status": "running"}
    ]


def test_session_detail_hides_parameter_live_answer(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        content="连续被拦截。让我尝试拆分写入。\n</parameter>",
        thought="</parameter>\n<parameter",
        tool_calls=[{"name": "cli_tool", "status": "running"}],
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == "连续被拦截。让我尝试拆分写入。"
    assert "thought" not in payload["messages"][-1]
    assert payload["messages"][-1]["toolCalls"] == [
        {"name": "cli_tool", "status": "running"}
    ]


def test_session_detail_sanitizes_persisted_protocol_messages_and_active_task(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "polluted-protocol",
            "kind": "coding",
            "status": "reading",
            "title": "<invoke name=\"read_file_tool\"><parameter name=\"file_path\">secret.py</parameter></invoke>",
            "goal": "<state",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "继续检查。\n</parameter>",
            "next_action": "<parameter name=\"file_path\">secret.py</parameter>",
            "updated_at": "2026-05-20T17:54:06",
        },
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].append(
        {
            "role": "assistant",
            "content": (
                "继续检查。\n"
                '<invoke name="read_file_tool">'
                '<parameter name="file_path">tests/prompt_debugger.py</parameter>'
                "</invoke>\n"
                "<state"
            ),
            "thought": "</parameter>\n<parameter",
            "timestamp": "2026-05-20T17:55:00",
            "tool_calls": [{"name": "read_file_tool"}],
        }
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200, response.json()
    payload = response.json()
    normalized_task = session_service._normalize_session_active_task(
        load_chat_state(tmp_path)["conversations"][0]["active_task"]
    )
    assistant = payload["messages"][-1]
    assert assistant["content"] == "继续检查。"
    assert "thought" not in assistant
    assert payload["taskSummary"] == "继续检查。"
    assert payload["activeTask"]["latestSummary"] == "继续检查。"
    assert payload["activeTask"]["title"] == ""
    assert payload["activeTask"]["goal"] == ""
    assert payload["activeTask"]["nextAction"] == ""
    assert normalized_task["latest_summary"] == "继续检查。"
    assert normalized_task["title"] == ""
    assert normalized_task["goal"] == ""
    assert normalized_task["next_action"] == ""
    assert "<invoke" not in json.dumps(payload, ensure_ascii=False)
    assert "<parameter" not in json.dumps(payload, ensure_ascii=False)
    assert "<state" not in json.dumps(payload, ensure_ascii=False)


def test_session_detail_recovers_stale_running_state(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["last_turn_status"] = "running"
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_service._WORK_RUN_STORE.persist_snapshot(
        "chat_turn",
        {
            "runId": "stale-turn-1",
            "runKind": "chat_turn",
            "track": "dialogue",
            "sessionId": "session-live",
            "status": "running",
            "currentPhase": "running",
            "leases": ["readonly_chat"],
            "userMessage": "继续前端开发",
            "startedAt": "2026-05-18T11:59:00",
            "updatedAt": "2026-05-18T12:00:00",
            "finishedAt": "",
        },
        active_run_id="stale-turn-1",
    )
    session_service._set_session_running("session-live", False)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "ready"
    assert payload["messages"][-1]["role"] == "assistant"
    assert "已被中断" in payload["messages"][-1]["content"]
    persisted = load_chat_state(tmp_path)
    assert persisted["conversations"][0]["last_turn_status"] == "ready"
    assert session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn") is None
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run["runId"] == "stale-turn-1"
    assert latest_run["status"] == "stopped"
    assert latest_run["finishedAt"]


def test_submit_session_message_allows_follow_up_when_previous_turn_finished(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续推进并给出下一步建议。",
                "raw_output": "继续推进并给出下一步建议。",
                "outcome": "done",
                "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
                "tool_call_count": 1,
                "tool_trace": [
                    {"name": "read_file_tool"},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复 web/src/routes/ChatCodingRoute.tsx"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["role"] == "assistant"
    assert payload["messages"][-1]["content"] == "继续推进并给出下一步建议。"
    assert payload["currentPhase"] == "ready"
    assert payload["activeTask"]["goal"] == "继续修复 web/src/routes/ChatCodingRoute.tsx"
    assert payload["activeTask"]["latestSummary"] == "继续推进并给出下一步建议。"


def test_submit_session_message_keeps_streamed_reply_when_final_result_is_control_marker(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class ControlMarkerAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            from core.ui import get_ui

            get_ui().stream_response("项目审查完成：核心问题集中在会话持久化和前端状态冗余。", done=False)
            get_ui().stream_response("[outcome=done]", done=True)
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "read_files": ["README.md"],
                "tool_call_count": 1,
                "tool_trace": [{"name": "read_file_tool", "args": {"file_path": "README.md"}}],
            }

    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ControlMarkerAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "审查整个项目并汇报"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["content"] == "项目审查完成：核心问题集中在会话持久化和前端状态冗余。"
    assert "[outcome=done]" not in json.dumps(payload, ensure_ascii=False)
    assert payload["activeTask"]["latestSummary"] == "项目审查完成：核心问题集中在会话持久化和前端状态冗余。"


def test_submit_session_message_continues_progress_until_done(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    calls = []

    class ContinuingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "completed",
                    "summary": "<state>",
                    "raw_output": "<state>",
                    "outcome": "progress",
                    "next_action": "继续读取测试工具结构并形成规划。",
                    "read_files": ["tests/prompt_debugger.py"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "规划完成：先复用 prompt_debugger，再包装 BDD 调试入口。",
                "raw_output": "规划完成：先复用 prompt_debugger，再包装 BDD 调试入口。",
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ContinuingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert len(calls) == 2
    assert "继续完成同一个用户目标" in calls[1]
    assert payload["messages"][-1]["content"] == "规划完成：先复用 prompt_debugger，再包装 BDD 调试入口。"
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_continues_after_bookkeeping_progress(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    calls = []

    class BookkeepingProgressAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "partial",
                    "summary": "",
                    "raw_output": "",
                    "outcome": "progress",
                    "recommended_next_action": "继续读取证据或直接给出结论。",
                    "tool_call_count": 3,
                    "tool_trace": [
                        {"name": "get_git_status_summary_tool"},
                        {"name": "task_create_tool"},
                        {"name": "task_update_tool"},
                    ],
                }
            return {
                "status": "completed",
                "summary": "已找到优化点：任务管理工具不应算作有效证据推进。",
                "raw_output": "已找到优化点：任务管理工具不应算作有效证据推进。",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: BookkeepingProgressAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "寻找可以优化的地方并汇报"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assert len(calls) == 2
    assert "继续完成同一个用户目标" in calls[1]
    assert "继续读取证据或直接给出结论" in calls[1]
    assert payload["messages"][-1]["content"] == "已找到优化点：任务管理工具不应算作有效证据推进。"
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_keeps_tools_available_after_tool_progress(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=3),
    )
    calls = []

    class ToolProgressAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None, disable_tools=False):
            calls.append({"prompt": initial_prompt, "disable_tools": disable_tools})
            if len(calls) == 1:
                return {
                    "status": "partial",
                    "summary": "已读取 core/web/services/runtime_scene_service.py，下一步继续校准 runtime scene 摘要。",
                    "raw_output": "已读取 core/web/services/runtime_scene_service.py，下一步继续校准 runtime scene 摘要。",
                    "outcome": "progress",
                    "recommended_next_action": "基于已读证据给出可见结论。",
                    "tool_call_count": 3,
                    "tool_trace": [
                        {"name": "code_symbol_tool"},
                        {"name": "read_file_tool"},
                        {"name": "grep_search_tool"},
                    ],
                }
            assert disable_tools is False
            assert "工具循环保护" not in str(initial_prompt)
            return {
                "status": "completed",
                "summary": "已修正工具路径并收束：runtime scene 摘要需要基于返回内容继续推进。",
                "raw_output": "已修正工具路径并收束：runtime scene 摘要需要基于返回内容继续推进。",
                "outcome": "done",
                "tool_call_count": 1,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ToolProgressAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "好的开始修改"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assert len(calls) == 2
    assert calls[0]["disable_tools"] is False
    assert calls[1]["disable_tools"] is False
    assert "继续完成同一个用户目标" in calls[1]["prompt"]
    assert "基于已读证据给出可见结论" in calls[1]["prompt"]
    assert "工具结果是否真正服务于用户目标" not in calls[1]["prompt"]
    assert "禁用工具" not in calls[1]["prompt"]
    assert "工具循环保护" not in calls[1]["prompt"]
    assert payload["messages"][-1]["content"] == "已修正工具路径并收束：runtime scene 摘要需要基于返回内容继续推进。"
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_keeps_previous_continuation_reply_when_done_marker_follows(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    calls = []

    class MarkerAfterReplyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "completed",
                    "summary": "已审查当前项目。以下是汇报结果。\n\n核心问题是回答持久化和 UI 区分度。",
                    "raw_output": "已审查当前项目。以下是汇报结果。\n\n核心问题是回答持久化和 UI 区分度。",
                    "outcome": "progress",
                    "read_files": ["README.md"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "README.md"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: MarkerAfterReplyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你现在审查一下整个项目,并向我汇报结果"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert len(calls) == 2
    assert assistant["content"] == "已审查当前项目。以下是汇报结果。\n\n核心问题是回答持久化和 UI 区分度。"
    assert "[outcome=done]" not in json.dumps(payload, ensure_ascii=False)
    assert payload["activeTask"]["latestSummary"] == "已审查当前项目。以下是汇报结果。\n核心问题是回答持久化和 UI 区分度。"
    assert payload["activeTask"]["readFiles"] == ["README.md"]


def test_submit_session_message_never_persists_empty_assistant_reply(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class EmptyVisibleAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "<state>{}</state>",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: EmptyVisibleAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请审查项目并汇报"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["role"] == "assistant"
    assert assistant["content"].strip()
    assert assistant["content"] == "本轮没有产生可见回复。"

    state = load_chat_state(tmp_path)
    persisted_assistant = state["conversations"][0]["messages"][-1]
    assert persisted_assistant["role"] == "assistant"
    assert persisted_assistant["content"] == "本轮没有产生可见回复。"


def test_submit_session_message_does_not_persist_xml_protocol_as_reply_or_task(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class ProtocolOnlyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": (
                    "继续检查文件。\n"
                    '<invoke name="read_file_tool">'
                    '<parameter name="file_path">tests/prompt_debugger.py</parameter>'
                    "</invoke>\n"
                    "</parameter>"
                ),
                "raw_output": (
                    "继续检查文件。\n"
                    '<invoke name="read_file_tool">'
                    '<parameter name="file_path">tests/prompt_debugger.py</parameter>'
                    "</invoke>\n"
                    "<state"
                ),
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 1,
                "tool_trace": [
                    {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProtocolOnlyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请继续检查 BDD 调试工具规划"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["content"] == "继续检查文件。"
    state = load_chat_state(tmp_path)
    persisted_json = json.dumps(state, ensure_ascii=False)
    assert "<invoke" not in persisted_json
    assert "<parameter" not in persisted_json
    assert "</parameter>" not in persisted_json
    assert "<state" not in persisted_json
    active_task = state["conversations"][0]["active_task"]
    assert active_task["latest_summary"] == "继续检查文件。"
    assert active_task["title"] == "请继续检查 BDD 调试工具规划"
    assert active_task["goal"] == "请继续检查 BDD 调试工具规划"


def test_submit_session_message_ignores_configured_continuation_limit_until_done(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    calls = []

    class ProgressThenDoneAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) < 3:
                return {
                    "status": "completed",
                    "summary": "",
                    "raw_output": "",
                    "outcome": "progress",
                    "next_action": "继续读取测试工具结构并形成规划。",
                    "read_files": ["tests/prompt_debugger.py"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "规划完成：包装 prompt_debugger 的 BDD 场景过滤能力。",
                "raw_output": "规划完成：包装 prompt_debugger 的 BDD 场景过滤能力。",
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProgressThenDoneAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert len(calls) == 3
    assert "任务级持续上限" not in payload["messages"][-1]["content"]
    assert payload["messages"][-1]["content"] == "规划完成：包装 prompt_debugger 的 BDD 场景过滤能力。"
    assert payload["currentPhase"] == "ready"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "completed"
    assert latest_run["finishedAt"]


def test_submit_session_message_preserves_visible_progress_without_limit_prompt(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    calls = []

    class VisibleProgressAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "completed",
                    "summary": "我已经完成第一项优化，并通过基础验证。下一步继续收口剩余日志路径。",
                    "raw_output": "我已经完成第一项优化，并通过基础验证。下一步继续收口剩余日志路径。",
                    "outcome": "progress",
                    "next_action": "继续收口剩余日志路径。",
                    "tool_call_count": 1,
                    "tool_trace": [{"name": "cli_tool", "args": {"command": "python -m py_compile core/logging/__init__.py"}}],
                }
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: VisibleProgressAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续优化日志系统"},
    )

    assert response.status_code == 202
    payload = response.json()
    assistant = payload["messages"][-1]
    assert len(calls) == 2
    assert assistant["content"] == "我已经完成第一项优化，并通过基础验证。下一步继续收口剩余日志路径。"
    assert "任务级持续上限" not in assistant["content"]
    assert payload["currentPhase"] == "ready"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "completed"
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["latest_summary"] == "我已经完成第一项优化，并通过基础验证。下一步继续收口剩余日志路径。"
    assert active_task.get("next_action", "") == ""


def test_submit_session_message_continues_repeated_visible_progress_until_done(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=4),
    )
    calls = []
    repeated_reply = "已完成日志审查：问题集中在 continuation loop 反复发送同一段可见进展。"

    class RepeatingVisibleProgressAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) < 3:
                return {
                    "status": "completed",
                    "summary": repeated_reply,
                    "raw_output": repeated_reply,
                    "outcome": "progress",
                    "next_action": "继续收束同一问题。",
                    "tool_call_count": 1,
                    "tool_trace": [{"name": "read_file_tool", "args": {"file_path": "core/web/services/session_service.py"}}],
                }
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: RepeatingVisibleProgressAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析对话重复输出问题"},
    )

    assert response.status_code == 202
    payload = response.json()
    assistant = payload["messages"][-1]
    assert len(calls) == 3
    assert assistant["content"] == repeated_reply
    assert assistant["content"].count(repeated_reply) == 1
    assert "任务级持续上限" not in assistant["content"]
    assert payload["currentPhase"] == "ready"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "completed"


def test_submit_session_message_stops_on_inferred_progress_visible_conclusion(tmp_path, monkeypatch):
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    calls = []
    conclusion = "根因已经确认：推断出来的 progress 不应该让已完成的可见结论再次进入 continuation。"

    class InferredProgressConclusionAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            return {
                "status": "completed",
                "summary": conclusion,
                "raw_output": conclusion,
                "outcome": "progress",
                "metadata": {"chat_contract_outcome_source": "inferred"},
                "read_files": ["core/web/services/session_service.py"],
                "tool_call_count": 1,
                "tool_trace": [
                    {
                        "name": "read_file_tool",
                        "args": {"file_path": "core/web/services/session_service.py"},
                    }
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: InferredProgressConclusionAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析对话重复输出问题"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert len(calls) == 1
    assert payload["messages"][-1]["content"] == conclusion
    assert payload["currentPhase"] == "ready"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "completed"


def test_submit_session_message_completed_turn_ignores_low_configured_limit(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class DoneAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已经完成优化并验证通过。",
                "raw_output": "已经完成优化并验证通过。",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DoneAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "完成这个优化"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["content"] == "已经完成优化并验证通过。"
    assert "任务级持续上限" not in payload["messages"][-1]["content"]
    assert payload["currentPhase"] == "ready"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "completed"


def test_submit_session_continue_preserves_unfinished_task_goal(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "bdd-tool-plan",
            "kind": "coding",
            "status": "reading",
            "title": "做一个 BDD 调试测试工具规划并汇报",
            "goal": "做一个 BDD 调试测试工具规划并汇报",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "已读取测试工具结构。",
            "updated_at": "2026-05-20T16:24:53",
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    prompts = []

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            prompts.append(initial_prompt)
            return {
                "status": "completed",
                "summary": "继续完成规划：建议包装 prompt_debugger 的 BDD 场景过滤能力。",
                "raw_output": "继续完成规划：建议包装 prompt_debugger 的 BDD 场景过滤能力。",
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert prompts[0] == "做一个 BDD 调试测试工具规划并汇报"
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["goal"] == "做一个 BDD 调试测试工具规划并汇报"
    assert active_task["title"] == "做一个 BDD 调试测试工具规划并汇报"
    assert active_task["last_user_message"] == "继续"


def test_submit_session_continue_clears_stale_next_action_after_visible_reply(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "stale-next-action",
            "kind": "coding",
            "status": "reading",
            "title": "查看系统提示词",
            "goal": "查看系统提示词",
            "latest_summary": "已完成前半段汇报。",
            "next_action": "发送“继续”以恢复停止前的现场。",
            "updated_at": "2026-05-24T20:10:41",
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续上次未完成的汇报，系统提示词已汇总完成。",
                "raw_output": "继续上次未完成的汇报，系统提示词已汇总完成。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["activeTask"]["goal"] == "查看系统提示词"
    assert payload["activeTask"]["latestSummary"] == "继续上次未完成的汇报，系统提示词已汇总完成。"
    assert payload["activeTask"]["nextAction"] == ""

    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["next_action"] == ""


def test_submit_session_continue_recovers_goal_when_active_task_is_continue(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "polluted-continue",
            "kind": "coding",
            "status": "reading",
            "title": "继续",
            "goal": "继续",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "<state",
            "updated_at": "2026-05-20T17:54:06",
        },
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"] = [
        {
            "role": "user",
            "content": "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报",
            "timestamp": "2026-05-20T17:50:00",
        },
        {
            "role": "assistant",
            "content": "已达到 Web Chat 任务级持续上限（1 轮），本次先暂停，避免后台无限运行。",
            "timestamp": "2026-05-20T17:51:00",
        },
        {
            "role": "user",
            "content": "继续",
            "timestamp": "2026-05-20T17:53:05",
        },
    ]
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    prompts = []

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            prompts.append(initial_prompt)
            if len(prompts) == 1:
                return {
                    "status": "completed",
                    "summary": "<state",
                    "raw_output": "<state",
                    "outcome": "progress",
                    "next_action": "继续读取测试工具结构并形成规划。",
                    "read_files": ["tests/prompt_debugger.py"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "规划已恢复：先包装 prompt_debugger 的 BDD 场景过滤能力。",
                "raw_output": "规划已恢复：先包装 prompt_debugger 的 BDD 场景过滤能力。",
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    assert prompts[0] == "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"
    payload = response.json()
    assert len(prompts) == 2
    assert payload["messages"][-1]["content"] == "规划已恢复：先包装 prompt_debugger 的 BDD 场景过滤能力。"
    assert "任务级持续上限" not in payload["messages"][-1]["content"]
    assert "<state" not in payload["messages"][-1]["content"]
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["goal"] == "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"
    assert active_task["title"] == "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"
    assert active_task["latest_summary"] == "规划已恢复：先包装 prompt_debugger 的 BDD 场景过滤能力。"


def test_persist_turn_result_cleans_parameter_and_requires_real_stop(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "bdd-tool-plan",
            "kind": "coding",
            "status": "reading",
            "title": "做一个 BDD 调试测试工具规划并汇报",
            "goal": "做一个 BDD 调试测试工具规划并汇报",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "已读取测试工具结构。",
            "updated_at": "2026-05-20T16:24:53",
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_service._clear_session_turn_control("session-live")

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "stopped",
            "summary": "连续被拦截。让我尝试拆分写入。\n</parameter>",
            "raw_output": "连续被拦截。让我尝试拆分写入。\n</parameter>",
            "stop_requested": True,
            "outcome": "progress",
            "read_files": ["tests/prompt_debugger.py"],
            "tool_call_count": 0,
            "tool_trace": [],
        },
    )

    state = load_chat_state(tmp_path)
    message = state["conversations"][0]["messages"][-1]
    assert message["role"] == "assistant"
    assert message["content"] == "连续被拦截。让我尝试拆分写入。"
    assert message["content"] != "本轮已按请求停止。"
    active_task = state["conversations"][0]["active_task"]
    assert active_task["latest_summary"] == "连续被拦截。让我尝试拆分写入。"
    assert "</parameter>" not in json.dumps(active_task, ensure_ascii=False)


def test_session_detail_uses_ready_phase_for_resting_sessions(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_persists_visible_failure(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class FailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: FailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请修复 web/src/routes/ChatCodingRoute.tsx 的提交流程"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["role"] == "assistant"
    assert "失败" in payload["messages"][-1]["content"] or "failed" in payload["messages"][-1]["content"].lower()
    assert "LLM unavailable" in payload["messages"][-1]["content"]
    assert payload["currentPhase"] == "failed"


def test_submit_session_message_surfaces_failed_result_error(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class FailingResultAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": "",
                "raw_output": "",
                "error": "configuration_error: LiteLLM 未安装，无法执行模型调用；请安装 litellm",
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: FailingResultAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你现在是这个项目的agent，请告诉我目前的感受"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["role"] == "assistant"
    assert "LiteLLM 未安装" in payload["messages"][-1]["content"]
    assert payload["currentPhase"] == "failed"


def test_submit_session_message_surfaces_provider_error_outside_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )

    provider_error = (
        'provider_protocol_error: litellm.BadGatewayError: BadGatewayError: OpenAIException - '
        '{"error":{"message":"Upstream request failed","type":"upstream_error"}}'
    )

    class ProviderFailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": provider_error,
                "raw_output": provider_error,
                "error": provider_error,
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续当前对话"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["role"] == "user"
    assert payload["messages"][-1]["content"] == "继续当前对话"
    assert payload["lastTurnError"]["errorType"] == "provider_upstream_error"
    assert "模型服务上游暂时失败" in payload["lastTurnError"]["message"]
    assert "litellm.BadGatewayError" not in payload["lastTurnError"]["message"]
    assert all("模型服务上游暂时失败" not in item["content"] for item in payload["messages"])
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run["errorType"] == "provider_upstream_error"
    assert "litellm.BadGatewayError" in latest_run["error"]


def test_submit_session_message_omits_mental_snapshot_when_disabled(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "is_mental_model_enabled", lambda: False)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续推进并给出下一步建议。",
                "raw_output": "继续推进并给出下一步建议。",
                "reasoning_content": "先保留思考，再让心智快照按开关退场。",
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "这部分应该被开关挡住。",
                    "whisper": "不要落盘。",
                    "cognitiveState": "productive",
                },
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复 web/src/routes/ChatCodingRoute.tsx"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["thought"] == "先保留思考，再让心智快照按开关退场。"
    assert "mentalSnapshot" not in payload["messages"][-1]


def test_submit_session_message_uses_per_turn_mental_model_override(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "is_mental_model_enabled", lambda: True)

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.override = None
            self.seeded_history = None
            created_agents.append(self)

        def set_mental_model_enabled_override(self, enabled):
            self.override = enabled

        def seed_chat_history(self, messages):
            self.seeded_history = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已按本轮开关处理。",
                "raw_output": "已按本轮开关处理。",
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "如果开关关闭，这里不应该落盘。",
                    "whisper": "per-turn",
                    "cognitiveState": "productive",
                },
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", DummyAgent)
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    disabled_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "这一轮不要打开心智模型", "mentalModelEnabled": False},
    )

    assert disabled_response.status_code == 202, disabled_response.json()
    disabled_payload = disabled_response.json()
    assert created_agents[-1].override is False
    assert "mentalSnapshot" not in disabled_payload["messages"][-1]

    enabled_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "这一轮打开心智模型", "mentalModelEnabled": True},
    )

    assert enabled_response.status_code == 202, enabled_response.json()
    enabled_payload = enabled_response.json()
    assert created_agents[-1].override is True
    assert enabled_payload["messages"][-1]["mentalSnapshot"]["mood"] == "专注"


def test_submit_session_message_includes_stream_friendly_tool_and_mental_payloads(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已完成三段式输出。",
                "raw_output": "最终回答内容。",
                "thought": "这是一段可见思考。",
                "reasoning_content": "这是一段可见思考。",
                "state_info": {
                    "mood": "专注",
                    "feeling": "心智模型已展开。",
                    "whisper": "工具调用继续保持单块。",
                },
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "心智模型已展开。",
                    "whisper": "工具调用继续保持单块。",
                    "cognitiveState": "productive",
                    "confidence": 0.91,
                    "sampleSize": 3,
                    "interventionCount": 1,
                    "updatedAt": "2026-05-18T12:01:00",
                    "source": "diagnosis",
                    "intervention": "继续保持当前路径。",
                    "metrics": {"sample_size": 3, "intervention_count": 1},
                    "historyTail": [
                        {"cognitiveState": "productive", "confidence": 0.91, "timestamp": "2026-05-18T12:01:00"},
                    ],
                },
                "tool_trace": [
                    {"name": "read_file_tool", "result_preview": "read ok", "status": "success"},
                    {"name": "run_test_for_tool", "result_preview": "tests passed", "status": "success"},
                ],
                "tool_call_count": 2,
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续把对话展示改成四段式"},
    )

    assert response.status_code == 202
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["content"] == "最终回答内容。"
    assert assistant["thought"] == "这是一段可见思考。"
    assert assistant["mentalSnapshot"]["cognitiveState"] == "productive"
    assert assistant["mentalSnapshot"]["intervention"] == "继续保持当前路径。"
    assert assistant["mentalSnapshot"]["metrics"]["sample_size"] == 3
    assert assistant["toolCalls"] == [
        {"name": "read_file_tool", "status": "done", "summary": "read ok", "resultPreview": "read ok"},
        {
            "name": "run_test_for_tool",
            "status": "done",
            "summary": "tests passed",
            "resultPreview": "tests passed",
        },
    ]
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_restores_prior_mental_snapshot_for_agent(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-20T14:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-20T14:00:00",
                    "last_turn_status": "ready",
                    "messages": [
                        {
                            "role": "user",
                            "content": "你能感知到你的心智模型吗",
                            "timestamp": "2026-05-20T13:58:00",
                        },
                        {
                            "role": "assistant",
                            "content": "我对自己的心智模型能感知多少？",
                            "timestamp": "2026-05-20T13:59:00",
                            "mental_snapshot": {
                                "mood": "沉思",
                                "feeling": "正在延续心智模型话题。",
                                "whisper": "接住上一段回答。",
                                "sampleSize": 4,
                            },
                        },
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["history"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续补完心智模型回答。",
                "raw_output": "继续补完心智模型回答。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你话还没说完"},
    )

    assert response.status_code == 202
    assert captured["history"][1]["mental_snapshot"]["mood"] == "沉思"
    assert captured["history"][0]["content"] == "你能感知到你的心智模型吗"


def test_runtime_summary_prefers_current_phase_over_stale_task_progress(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "ready",
            "changedFiles": ["web/src/routes/ChatCodingRoute.tsx"],
        },
    )
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    payload = runtime_service.get_runtime_summary()

    assert payload["status"] == "success"
    assert payload["currentPhase"] == "ready"


def test_runtime_summary_exposes_runtime_manager_workbench_state(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 17,
            "workbench": {
                "desiredState": "closed",
                "observedState": "open",
                "phase": "closing",
                "backendPid": 3001,
                "browserWindowPid": 4002,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
                "lastReason": "web_close_button",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["runtimeManager"]["running"] is True
    assert payload["runtimeManager"]["managerPid"] == 9912
    assert payload["workbench"]["desiredState"] == "closed"
    assert payload["workbench"]["observedState"] == "open"
    assert payload["workbench"]["phase"] == "closing"
    assert payload["workbench"]["backendPid"] == 3001


def test_runtime_summary_exposes_orphaned_browser_status(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 18,
            "workbench": {
                "desiredState": "closed",
                "observedState": "open",
                "phase": "failed",
                "backendPid": 0,
                "browserWindowPid": 12132,
                "backendObserved": False,
                "backendPortListening": False,
                "browserWindowAlive": True,
                "browserManaged": True,
                "backendMissing": True,
                "frontendOrphaned": True,
                "lifecycleConsistency": "orphaned_browser",
                "url": "http://127.0.0.1:8000",
                "lastReason": "external_close",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["workbench"]["frontendOrphaned"] is True
    assert payload["workbench"]["backendMissing"] is True
    assert payload["workbench"]["lifecycleConsistency"] == "orphaned_browser"
    assert "后端服务已经离线" in payload["workbench"]["statusLine"]
    assert payload["lifecycleProof"]["overallState"] == "failed"


def test_runtime_lifecycle_proof_marks_ready_when_components_agree(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
            "latest": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 17,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "runtimeManager": {"sourceMatches": True},
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 3001,
                "browserWindowPid": 4002,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
                "lastReason": "start",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    proof = payload["lifecycleProof"]
    assert proof["overallState"] == "ready"
    assert proof["projectRootMatches"] is True
    assert proof["activeWorkRuns"]["count"] == 0
    assert {component["id"] for component in proof["components"]} >= {
        "runtime_manager",
        "backend",
        "workbench_window",
        "project_root",
        "active_work_runs",
    }


def test_runtime_lifecycle_proof_keeps_advisory_source_staleness_non_blocking(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
            "latest": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 18,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "runtimeManager": {"sourceMatches": False},
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 3001,
                "backendAlive": True,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 3001,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "browserWindowPid": 0,
                "browserWindowAlive": False,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
                "lastReason": "start",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    proof = payload["lifecycleProof"]
    source_component = next(component for component in proof["components"] if component["id"] == "source_freshness")
    assert proof["overallState"] == "ready"
    assert source_component["state"] == "failed"
    assert source_component["requiredForOpen"] is False


def test_runtime_lifecycle_proof_does_not_mark_closed_with_active_work_runs(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": {
                    "runId": "turn-live",
                    "runKind": "chat_turn",
                    "status": "running",
                },
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
            "latest": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": False,
            "runtimeState": "idle",
            "managerPid": 0,
            "stateVersion": 17,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "backendPid": 0,
                "browserWindowPid": 0,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
                "lastReason": "web_close_button",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    proof = payload["lifecycleProof"]
    assert proof["overallState"] == "partial"
    assert proof["activeWorkRuns"]["count"] == 1
    assert proof["activeWorkRuns"]["kinds"] == ["chat_turn"]


def test_runtime_lifecycle_proof_does_not_mark_closed_when_backend_port_is_still_owned(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
            "latest": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 18,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "runtimeManager": {"sourceMatches": True},
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "backendPid": 19964,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": True,
                "backendPort": 8766,
                "backendPortListening": True,
                "backendPortOwnerPid": 52396,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": True,
                "browserWindowPid": 0,
                "browserWindowAlive": False,
                "browserManaged": True,
                "url": "http://127.0.0.1:8766",
                "lastReason": "web_close_button",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    proof = payload["lifecycleProof"]
    backend_component = next(component for component in proof["components"] if component["id"] == "backend")
    assert proof["overallState"] == "partial"
    assert backend_component["ok"] is False
    assert backend_component["state"] == "closing"
    assert backend_component["pid"] == 19964
    assert "52396" in backend_component["detail"]


def test_runtime_lifecycle_proof_does_not_mark_closed_with_residual_repo_processes(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
            "latest": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": False,
            "runtimeState": "idle",
            "managerPid": 0,
            "stateVersion": 19,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "runtimeManager": {"sourceMatches": True},
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "backendPid": 0,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8766,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "browserWindowPid": 0,
                "browserWindowAlive": False,
                "browserManaged": True,
                "url": "http://127.0.0.1:8766",
                "lastReason": "web_close_button",
                "failureMessage": "",
            },
            "residualProcesses": {
                "count": 1,
                "items": [
                    {
                        "pid": 49780,
                        "parentPid": 0,
                        "kind": "unmanaged_workbench",
                        "name": "python.exe",
                        "commandLine": "python scripts/web_workbench.py --port 8001 --no-browser",
                        "cwd": str(runtime_service.PROJECT_ROOT),
                        "port": 8001,
                    }
                ],
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    proof = payload["lifecycleProof"]
    residual_component = next(component for component in proof["components"] if component["id"] == "residual_processes")
    assert proof["overallState"] == "partial"
    assert proof["residualProcesses"]["count"] == 1
    assert residual_component["ok"] is False
    assert residual_component["state"] == "running"
    assert residual_component["pid"] == 49780


def test_runtime_lifecycle_proof_detects_unmanaged_frontend_dev_server(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
            "latest": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": False,
            "runtimeState": "idle",
            "managerPid": 0,
            "stateVersion": 19,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "runtimeManager": {"sourceMatches": True},
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "backendPid": 0,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8766,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "browserWindowPid": 0,
                "browserWindowAlive": False,
                "browserManaged": True,
                "url": "http://127.0.0.1:8766",
                "lastReason": "web_close_button",
                "failureMessage": "",
            },
            "residualProcesses": {
                "count": 1,
                "items": [
                    {
                        "pid": 51517,
                        "parentPid": 1,
                        "kind": "unmanaged_frontend_dev_server",
                        "name": "python.exe",
                        "commandLine": "python -m http.server 5173 -d frontend",
                        "cwd": str(runtime_service.PROJECT_ROOT),
                        "port": 5173,
                    }
                ],
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    proof = payload["lifecycleProof"]
    residual_component = next(component for component in proof["components"] if component["id"] == "residual_processes")
    assert proof["overallState"] == "partial"
    assert proof["residualProcesses"]["count"] == 1
    assert proof["residualProcesses"]["items"][0]["kind"] == "unmanaged_frontend_dev_server"
    assert residual_component["ok"] is False
    assert residual_component["pid"] == 51517
    assert "5173" in residual_component["detail"]


def test_runtime_summary_exposes_tool_call_session_state(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "running",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "THINKING",
            "runtime_status": "ACTING",
            "last_tool_name": "read_file_tool",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "tooling"
    assert payload["sessionNeedsResponse"] is False
    assert payload["sessionToolName"] == "read_file_tool"
    assert "tool" in payload["sessionStateLine"].lower() or "工具" in payload["sessionStateLine"]


def test_runtime_summary_exposes_thinking_session_state(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "running",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "THINKING",
            "runtime_status": "WORKING",
            "last_tool_name": "grep_search_tool",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "thinking"
    assert payload["sessionNeedsResponse"] is False
    assert payload["sessionToolName"] == "grep_search_tool"


def test_runtime_summary_exposes_answering_session_state(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "running",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "WORKING",
            "runtime_status": "WORKING",
            "turn_output_tokens": 64,
            "last_tool_name": "",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "answering"
    assert payload["sessionNeedsResponse"] is False


def test_runtime_summary_treats_stopping_session_as_active(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "正在收束当前轮。",
            "currentPhase": "stopping",
        },
    )
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    payload = runtime_service.get_runtime_summary()

    assert payload["status"] == "running"
    assert payload["sessionState"] == "running"
    assert payload["sessionNeedsResponse"] is False


def test_runtime_summary_marks_ready_session_as_needing_response(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "ready",
        },
    )
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "ready"
    assert payload["sessionNeedsResponse"] is True
    assert "继续" in payload["sessionStateLine"] or "ready" in payload["sessionStateLine"].lower()


def test_runtime_summary_marks_failed_session_as_needing_response(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "测试失败，需要你决定先修测试还是先回退。",
            "currentPhase": "failed",
            "updatedAt": "2026-05-18T20:00:00",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "ERROR",
            "runtime_status": "ERROR",
            "updated_at": "2026-05-18T20:00:01",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "failed"
    assert payload["sessionNeedsResponse"] is True
    assert payload["sessionUpdatedAt"] == "2026-05-18T20:00:00"


def test_runtime_summary_ready_session_ignores_stale_runtime_error(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "ready",
            "updatedAt": "2026-05-18T20:30:00",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "ERROR",
            "runtime_status": "IDLE",
            "updated_at": "2026-05-18T20:29:59",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["status"] == "success"
    assert payload["sessionState"] == "ready"
    assert payload["sessionNeedsResponse"] is True


def test_runtime_summary_exposes_latest_mental_state(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    class DummyMentalModel:
        def get_last_state(self):
            return {
                "mood": "专注",
                "feeling": "规则感知: normal",
                "whisper": "继续推进",
                "timestamp": "2026-05-18T20:00:02",
            }

        def diagnose(self):
            return SimpleNamespace(
                state="normal",
                confidence=0.82,
                metrics={"sample_size": 6, "intervention_count": 1},
                timestamp="2026-05-18T20:00:02",
            )

    monkeypatch.setattr(runtime_service, "get_mental_model", lambda *args, **kwargs: DummyMentalModel())

    payload = runtime_service.get_runtime_summary()

    assert payload["mentalState"]["mood"] == "专注"
    assert payload["mentalState"]["feeling"] == "规则感知: normal"
    assert payload["mentalState"]["whisper"] == "继续推进"
    assert payload["mentalState"]["cognitiveState"] == "normal"
    assert payload["mentalState"]["source"] == "state"
    assert payload["mentalState"]["confidence"] == pytest.approx(0.82)
    assert payload["mentalState"]["sampleSize"] == 6
    assert payload["mentalState"]["updatedAt"] == "2026-05-18T20:00:02"


def test_runtime_summary_reports_disabled_mental_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["mental_model"] = {"enabled": False}

    monkeypatch.setattr(runtime_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_manager_snapshot", lambda: {})

    payload = runtime_service.get_runtime_summary()

    assert payload["mentalState"]["source"] == "disabled"
    assert "关闭" in payload["mentalState"]["summary"] or "disabled" in payload["mentalState"]["summary"].lower()


def test_runtime_summary_falls_back_to_mental_diagnosis_when_state_is_empty(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_detail", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    class DummyMentalModel:
        def get_last_state(self):
            return {}

        def diagnose(self):
            return SimpleNamespace(
                state="thrashing",
                confidence=0.71,
                metrics={"sample_size": 8, "intervention_count": 3},
                timestamp="2026-05-18T20:00:03",
            )

    monkeypatch.setattr(runtime_service, "get_mental_model", lambda *args, **kwargs: DummyMentalModel())

    payload = runtime_service.get_runtime_summary()

    assert payload["mentalState"]["mood"] == ""
    assert payload["mentalState"]["cognitiveState"] == "thrashing"
    assert payload["mentalState"]["source"] == "diagnosis"
    assert payload["mentalState"]["confidence"] == pytest.approx(0.71)
    assert payload["mentalState"]["sampleSize"] == 8
    assert payload["mentalState"]["updatedAt"] == "2026-05-18T20:00:03"


def test_config_summary_exposes_language():
    response = client.get("/api/config/public")
    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] in {"zh", "en"}


def test_config_workspace_exposes_unified_config_payload(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("ui", {})["language"] = "en"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] == "en"
    assert payload["publicConfig"]["ui"]["language"] == "en"
    assert "rawToml" in payload
    assert "diagnosis" in payload
    preset_options = {item["preset_id"]: item for item in payload["modelPresetOptions"]}
    relay_preset = preset_options["relay_openai_gpt_5_5"]
    assert relay_preset["category"] == "relay"
    assert relay_preset["provider"]["kind"] == "relay"
    assert relay_preset["provider"]["base_url"] == "https://pixel.try-chatapi.com/v1"
    assert relay_preset["model"]["transport"] == "responses"
    assert relay_preset["model"]["contract"] == "tool_chat"
    image2_preset = preset_options["relay_image2"]
    assert image2_preset["category"] == "relay"
    assert image2_preset["provider"]["kind"] == "relay"
    assert image2_preset["provider"]["base_url"] == "https://ai-pixel.online"
    assert not image2_preset["provider"]["base_url"].endswith("/v1")
    assert image2_preset["model"]["model"] == "image2"
    assert image2_preset["model"]["streaming"] is False
    assert image2_preset["model"]["tool_calling_mode"] == "disabled"
    assert preset_options["custom_openai_compatible_relay"]["category"] == "openai_compatible"
    assert preset_options["custom_openai_compatible_relay"]["provider"]["kind"] == "openai_compatible"
    assert preset_options["custom_relay_responses"]["category"] == "relay"
    assert preset_options["custom_relay_responses"]["model"]["transport"] == "responses"
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["category"] == "official"
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["provider"]["kind"] == "xiaomi"
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["provider"]["base_url"] == (
        "https://token-plan-cn.xiaomimimo.com/v1"
    )
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["model"]["model"] == "mimo-v2.5-pro"
    assert "modelOptions" in payload
    assert "profileCards" in payload
    profile_cards = {item["profileId"]: item for item in payload["profileCards"]}
    assert profile_cards["research_broad"]["label"] == "Research Broad Search"
    assert profile_cards["research_deep"]["label"] == "Research Deep Search"
    assert profile_cards["research_review"]["label"] == "Research Review"
    assert profile_cards["research_themes"]["label"] == "Research Theme Generation"
    assert profile_cards["research_card"]["label"] == "Research Theme Card"


def test_config_workspace_exposes_full_editor_schema(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/workspace")

    assert response.status_code == 200
    payload = response.json()
    editor_sections = {section["id"]: section for section in payload["editorSections"]}
    editor_meta = payload["editorMeta"]

    assert "runtime" in editor_sections
    assert "tools" in editor_sections
    assert "prompt" in editor_sections
    assert "llm-profiles" in editor_sections
    sections_by_id = {section["id"]: section for section in payload["sections"]}
    assert sections_by_id["profiles"]["title"] == "LLM 配置"
    assert "配置档" not in sections_by_id["profiles"]["summary"]
    assert sections_by_id["draft"]["title"] == "高级配置检查"
    assert "JSON" not in sections_by_id["draft"]["title"]
    assert "JSON" not in sections_by_id["draft"]["summary"]
    assert "草稿" not in sections_by_id["draft"]["summary"]
    assert editor_sections["llm-profiles"]["title"] == "模型配置"
    assert editor_sections["prompt"]["title"] == "系统提示词"
    assert "git" not in editor_sections
    assert editor_sections["git-commit-profile"]["path"] == "git.commit_message_profile"
    assert editor_sections["git-commit-profile"]["title"] == "Git 提交模型"
    assert editor_sections["git-commit-profile"]["fieldCount"] == 1
    assert editor_sections["git-commit-prompt"]["path"] == "git.commit_message_prompt"
    assert editor_sections["git-commit-prompt"]["title"] == "Git 提交提示词"
    assert editor_sections["git-commit-prompt"]["fieldCount"] == 1
    assert editor_sections["runtime"]["path"] == "runtime"
    assert "workbench" in editor_sections
    assert editor_sections["workbench"]["path"] == "workbench"
    assert "user-profile" in editor_sections
    assert editor_sections["user-profile"]["path"] == "user_profile"
    assert editor_sections["user-profile"]["title"] == "用户信息"
    assert payload["publicConfig"]["workbench"]["backend_port"] == 8000
    assert payload["publicConfig"]["workbench"]["frontend_port"] == 5173
    assert payload["publicConfig"]["workbench"]["window_mode"] == "windowed"
    assert editor_meta["runtime.profile"]["kind"] == "select"
    assert editor_meta["runtime.profile"]["badge"] == "选项"
    assert editor_meta["workbench.backend_port"]["kind"] == "number"
    assert editor_meta["workbench.backend_port"]["label"] == "后端服务端口"
    assert editor_meta["workbench.frontend_port"]["kind"] == "number"
    assert editor_meta["workbench.frontend_port"]["label"] == "前端页面端口"
    assert editor_meta["workbench.window_mode"]["kind"] == "select"
    assert editor_meta["workbench.window_mode"]["label"] == "窗口模式"
    assert editor_meta["workbench.window_mode"]["options"] == [
        {"value": "windowed", "label": "窗口化"},
        {"value": "fullscreen", "label": "沉浸全屏"},
    ]
    assert "重启工作台" in editor_meta["workbench.window_mode"]["hint"]
    assert editor_meta["user_profile.display_name"]["kind"] == "text"
    assert editor_meta["user_profile.display_name"]["label"] == "用户显示名"
    assert editor_meta["user_profile.bio"]["kind"] == "multiline"
    assert editor_meta["user_profile.preferences"]["kind"] == "string_list"
    assert editor_meta["user_profile.avatar_preset"]["kind"] == "select"
    assert editor_meta["user_profile.avatar_preset"]["options"]
    assert editor_meta["user_profile.avatar_image_path"]["kind"] == "image"
    assert "本地图片" in editor_meta["user_profile.avatar_image_path"]["hint"]
    assert editor_meta["network.proxy_enabled"]["kind"] == "boolean"
    assert editor_meta["network.proxy_enabled"]["label"] == "启用代理"
    assert editor_meta["network.proxy_url"]["kind"] == "url"
    assert editor_meta["network.proxy_url"]["label"] == "代理地址"
    assert "科研调研" in editor_meta["network.proxy_enabled"]["hint"]
    assert editor_meta["tools.file.editable_extensions"]["kind"] == "string_list"
    assert editor_meta["tools.image2.default_model_ref"]["kind"] == "select"
    assert editor_meta["tools.image2.default_model_ref"]["label"] == "默认生图模型"
    assert any(option["value"] == "relay_image2" for option in editor_meta["tools.image2.default_model_ref"]["options"])
    assert editor_meta["prompt.sections"]["kind"] == "object_list"
    assert editor_meta["prompt.sections"]["badge"] == "列表"
    assert editor_meta["llm.profiles.primary.provider.kind"]["label"] == "服务商类型"
    assert editor_meta["llm.profiles.primary.provider.base_url"]["label"] == "服务商基础地址"
    assert payload["publicConfig"]["git"]["commit_message_profile"]
    assert "{diff}" in payload["publicConfig"]["git"]["commit_message_prompt"]
    assert editor_meta["git.commit_message_profile"]["kind"] == "select"
    assert editor_meta["git.commit_message_profile"]["label"] == "Git 提交使用的模型配置"
    assert "profile" not in editor_meta["git.commit_message_profile"]["hint"].lower()
    assert editor_meta["git.commit_message_prompt"]["kind"] == "multiline"
    assert "系统提示词模板" in editor_meta["git.commit_message_prompt"]["hint"]
    assert sections_by_id["health-diagnostics"]["title"] == "健康诊断"
    assert any(section["id"] == "overview" for section in payload["sections"])
    assert any(section["id"] == "shell" for section in payload["sections"])


def test_config_avatar_image_upload_stores_safe_project_file(monkeypatch, tmp_path):
    monkeypatch.setattr(avatar_image_service, "USER_AVATAR_DIR", tmp_path / "user_avatars")
    png_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    response = client.post(
        "/api/config/avatar-image",
        json={
            "filename": "my avatar.png",
            "contentType": "image/png",
            "dataBase64": base64.b64encode(png_payload).decode("ascii"),
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["path"].startswith("workspace/user_avatars/avatar-")
    assert payload["path"].endswith(".png")
    assert payload["url"].startswith("/api/config/avatar-image/avatar-")
    saved_files = list((tmp_path / "user_avatars").glob("*.png"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == png_payload

    image_response = client.get(payload["url"])
    assert image_response.status_code == 200
    assert image_response.headers["content-type"].startswith("image/png")
    assert image_response.content == png_payload


def test_config_avatar_image_upload_rejects_disguised_image(monkeypatch, tmp_path):
    monkeypatch.setattr(avatar_image_service, "USER_AVATAR_DIR", tmp_path / "user_avatars")

    response = client.post(
        "/api/config/avatar-image",
        json={
            "filename": "not-image.png",
            "contentType": "image/png",
            "dataBase64": base64.b64encode(b"not a png").decode("ascii"),
        },
    )

    assert response.status_code == 422
    assert not (tmp_path / "user_avatars").exists()


def test_config_avatar_image_upload_rejects_oversized_image(monkeypatch, tmp_path):
    monkeypatch.setattr(avatar_image_service, "USER_AVATAR_DIR", tmp_path / "user_avatars")
    monkeypatch.setattr(avatar_image_service, "MAX_USER_AVATAR_IMAGE_BYTES", 8)

    response = client.post(
        "/api/config/avatar-image",
        json={
            "filename": "avatar.png",
            "contentType": "image/png",
            "dataBase64": base64.b64encode(b"\x89PNG\r\n\x1a\nextra").decode("ascii"),
        },
    )

    assert response.status_code == 422
    assert not (tmp_path / "user_avatars").exists()


def test_health_diagnostics_endpoint_returns_log_helpers(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    runtime_log = tmp_path / "logs" / "agent_realtime.log"
    runtime_log.parent.mkdir(parents=True, exist_ok=True)
    runtime_log.write_text("runtime line\n", encoding="utf-8")
    conversation_log = tmp_path / "log_info" / "conversation_debug.jsonl"
    conversation_log.parent.mkdir(parents=True, exist_ok=True)
    conversation_log.write_text('{"type":"external_request"}\n', encoding="utf-8")

    _seed_runtime_scene_bundle(tmp_path, scene_id="scene-health", status="failed")
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/diagnostics/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    session_helpers = {item["id"]: item for item in payload["sessionHelpers"]}
    assert session_helpers["chat_sessions"]["sessionCount"] == 1
    assert session_helpers["chat_sessions"]["activeSessionId"] == "session-live"
    assert session_helpers["chat_sessions"]["route"] == "/chat?session=session-live"
    assert session_helpers["chat_sessions"]["protected"] is True
    helpers = {item["id"]: item for item in payload["logHelpers"]}
    assert set(helpers) == {"runtime_scenes", "runtime_logs", "workspace_logs", "conversation_logs"}
    assert helpers["runtime_scenes"]["route"] == "/logs?root=runtime_scenes"
    assert helpers["runtime_scenes"]["resetItemId"] == "stopped_runtime_scenes"
    assert helpers["runtime_scenes"]["protected"] is True
    assert helpers["runtime_logs"]["route"] == "/logs?root=runtime_logs"
    assert helpers["conversation_logs"]["resetItemId"] == "conversation_logs"
    assert helpers["workspace_logs"]["status"] == "warning"
    assert payload["findings"][0]["id"] == "runtime_scene_failed"
    assert payload["findings"][0]["severity"] == "blocked"
    assert payload["findings"][0]["route"] == "/logs?root=runtime_scenes"
    assert helpers["runtime_scenes"]["primaryFindingId"] == "runtime_scene_failed"
    assert any(item["source"] == "reset" and item["protected"] is True for item in payload["findings"])
    assert payload["quickActions"][0]["findingId"] == "runtime_scene_failed"
    assert any(item["resetItemId"] == "stopped_runtime_scenes" for item in payload["quickActions"])


def test_config_workspace_surfaces_llm_security_diagnostics_without_blocking_read(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["profiles"]["primary"]["provider"] = {
        "kind": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "file:///C:/Windows/win.ini",
        "compat_mode": "openai",
        "requires_api_key": True,
        "context_window": 100000,
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["blockingCount"] >= 1
    assert any("LLM security guard" in item for item in payload["diagnosis"]["blocking_issues"])


def test_config_workspace_draft_delete_model_marks_profiles_unconfigured(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "relay_openai_gpt_5_5",
        "overrides": {},
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/delete-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "relay_openai_gpt_5_5",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["publicConfig"]["llm"]["profiles"]["primary"]["model_ref"] == UNCONFIGURED_MODEL_REF
    assert next(item for item in payload["profileCards"] if item["profileId"] == "primary")["requiredModelMissing"] is True


def test_config_open_environment_opens_system_ui_without_returning_keys(monkeypatch):
    launched_commands = []
    focused_windows = []

    def fake_run(command, **kwargs):
        launched_commands.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config_service.os, "name", "nt")
    monkeypatch.setattr(config_service.subprocess, "run", fake_run)
    monkeypatch.setattr(config_service, "_focus_environment_variables_window", lambda: focused_windows.append("focused") or True)
    monkeypatch.setenv("VIBELUTION_SECRET_TEST_KEY", "should-not-leak")

    response = client.post("/api/config/open-environment", json={})

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["opened"] is True
    assert payload["method"] == "interactive-scheduled-task"
    assert payload["focused"] is True
    assert launched_commands
    assert focused_windows == ["focused"]
    assert [command[0][1] for command in launched_commands] == ["/Delete", "/Create", "/Run", "/Delete"]
    create_command = launched_commands[1][0]
    assert "/IT" in create_command
    assert "rundll32.exe sysdm.cpl,EditEnvironmentVariables" in create_command
    assert "should-not-leak" not in response.text
    assert "VIBELUTION_SECRET_TEST_KEY" not in response.text


def test_config_open_environment_reports_unsupported_platform(monkeypatch):
    monkeypatch.setattr(config_service.os, "name", "posix")

    response = client.post("/api/config/open-environment", json={})

    assert response.status_code == 422
    assert "Windows" in response.json()["detail"]


def test_config_open_environment_reports_launch_failure(monkeypatch):
    def fake_run(command, **kwargs):
        if command[1] == "/Create":
            return SimpleNamespace(returncode=1, stdout="", stderr="blocked")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config_service.os, "name", "nt")
    monkeypatch.setattr(config_service.subprocess, "run", fake_run)

    response = client.post("/api/config/open-environment", json={})

    assert response.status_code == 422
    assert "无法打开系统环境变量窗口" in response.json()["detail"]


def test_config_open_environment_focuses_detected_window(monkeypatch):
    focused_handles = []

    monkeypatch.setattr(config_service.os, "name", "nt")
    monkeypatch.setattr(config_service, "_find_environment_variables_window", lambda: 12345)
    monkeypatch.setattr(config_service, "_focus_window", lambda hwnd: focused_handles.append(hwnd) or True)

    assert config_service._focus_environment_variables_window(timeout_seconds=0.01) is True
    assert focused_handles == [12345]


def test_config_open_environment_promotes_window_when_foreground_is_blocked(monkeypatch):
    calls = []

    class FakeUser32:
        def GetForegroundWindow(self):
            return 0

        def GetWindowThreadProcessId(self, hwnd, process_id):
            return 222 if hwnd == 12345 else 0

        def AttachThreadInput(self, current_thread, target_thread, attach):
            calls.append(("AttachThreadInput", current_thread, target_thread, attach))
            return True

        def ShowWindow(self, hwnd, mode):
            calls.append(("ShowWindow", hwnd, mode))
            return True

        def BringWindowToTop(self, hwnd):
            calls.append(("BringWindowToTop", hwnd))
            return True

        def SetActiveWindow(self, hwnd):
            calls.append(("SetActiveWindow", hwnd))
            return hwnd

        def SetFocus(self, hwnd):
            calls.append(("SetFocus", hwnd))
            return hwnd

        def SetForegroundWindow(self, hwnd):
            calls.append(("SetForegroundWindow", hwnd))
            return False

        def SwitchToThisWindow(self, hwnd, alt_tab):
            calls.append(("SwitchToThisWindow", hwnd, alt_tab))
            return None

        def SetWindowPos(self, hwnd, insert_after, x, y, cx, cy, flags):
            calls.append(("SetWindowPos", hwnd, insert_after, flags))
            return True

    class FakeKernel32:
        def GetCurrentThreadId(self):
            return 111

    monkeypatch.setattr(
        config_service.ctypes,
        "windll",
        SimpleNamespace(user32=FakeUser32(), kernel32=FakeKernel32()),
        raising=False,
    )

    assert config_service._focus_window(12345) is False
    assert ("AttachThreadInput", 111, 222, True) in calls
    assert ("AttachThreadInput", 111, 222, False) in calls
    assert ("SetWindowPos", 12345, config_service._HWND_TOPMOST, config_service._SWP_NOMOVE | config_service._SWP_NOSIZE | config_service._SWP_SHOWWINDOW) in calls
    assert ("SetWindowPos", 12345, config_service._HWND_NOTOPMOST, config_service._SWP_NOMOVE | config_service._SWP_NOSIZE | config_service._SWP_SHOWWINDOW) in calls


def test_config_workspace_test_llm_uses_pending_draft_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["profiles"]["subagent_explorer"] = {
        "model_ref": "deepseek_v4_pro",
        "overrides": {},
    }
    monkeypatch.delenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert api_key == "draft-secret"
        return {"ok": True, "message": "ok", "runtime_route": f"{profile.transport}:{profile.model}"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    draft_response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "deepseek_v4_pro",
            "provider": public_config["llm"]["model_library"]["deepseek_v4_pro"]["provider"],
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "details": public_config["llm"]["model_library"]["deepseek_v4_pro"],
            "apiKeyEnv": "VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY",
            "apiKey": "draft-secret",
        },
    )

    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    pending_token = draft_payload["draftMeta"]["pending_api_keys"]["VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY"]
    assert pending_token != "draft-secret"
    assert pending_token.startswith("pending-secret:")

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": draft_payload["publicConfig"],
            "draftMeta": draft_payload["draftMeta"],
            "profileId": "subagent_explorer",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is True
    assert payload["api_key_source"] == "pending-env:VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY"
    assert payload["config_scope"] == "draft"
    assert payload["requires_api_key"] is True
    assert payload["transport"] == "chat_completions"
    assert payload["contract"] == "tool_chat"


def test_config_workspace_test_llm_ignores_forged_pending_draft_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["profiles"]["subagent_explorer"] = {
        "model_ref": "deepseek_v4_pro",
        "overrides": {},
    }
    monkeypatch.delenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert api_key is None
        return {"ok": False, "message": "missing"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {
                "pending_api_keys": {"VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY": "forged-secret"},
                "pending_cleared_api_keys": [],
            },
            "profileId": "subagent_explorer",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["api_key_source"] == "missing"


def test_config_workspace_test_llm_reports_local_draft_route_clearly(monkeypatch):
    saved_config = copy.deepcopy(load_public_config())
    draft_config = copy.deepcopy(saved_config)
    draft_config.setdefault("runtime", {})["profile"] = "safe_local"
    monkeypatch.delenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", raising=False)

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(saved_config))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert provider.kind == "local"
        assert provider.base_url == "http://localhost:11434/v1"
        return {"ok": False, "message": "<urlopen error [WinError 10061] connection refused>"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": draft_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["provider_kind"] == "local"
    assert payload["base_url"] == "http://localhost:11434/v1"
    assert payload["config_scope"] == "draft"
    assert payload["requires_api_key"] is False
    assert payload["api_key_source"] == "not-required"


def test_config_workspace_test_llm_rejects_metadata_service_base_url(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["profiles"]["primary"]
    target["provider"] = {
        "kind": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "http://169.254.169.254/v1",
        "compat_mode": "openai",
        "requires_api_key": True,
        "context_window": 100000,
    }
    target["model"] = "gpt-5.5"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 422
    assert "base_url" in response.json()["detail"]


def test_config_workspace_test_llm_rejects_file_base_url(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["profiles"]["primary"]
    target["provider"] = {
        "kind": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "file:///C:/Windows/win.ini",
        "compat_mode": "openai",
        "requires_api_key": True,
        "context_window": 100000,
    }
    target["model"] = "gpt-5.5"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 422
    assert "http(s)" in response.json()["detail"]


def test_config_workspace_test_llm_allows_localhost_for_local_provider(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["profiles"]["primary"]
    target["provider"] = {
        "kind": "local",
        "api_key_env": "",
        "base_url": "http://127.0.0.1:11434/v1",
        "compat_mode": "openai",
        "requires_api_key": False,
        "context_window": 65536,
    }
    target["model"] = "llama3.2"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert provider.kind == "local"
        assert provider.base_url == "http://127.0.0.1:11434/v1"
        assert api_key is None
        return {"ok": True, "message": "local-ok"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider_kind"] == "local"


def test_config_workspace_test_llm_image_input_reports_unsupported(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["profiles"]["primary"]
    target["provider"] = {
        "kind": "local",
        "api_key_env": "",
        "base_url": "http://127.0.0.1:11434/v1",
        "compat_mode": "openai",
        "requires_api_key": False,
        "context_window": 65536,
    }
    target["model"] = "llama3.2"
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        config_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages, tools=None, metadata=None):
            assert messages[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
            raise RuntimeError("connection refused")

    monkeypatch.setattr("core.llm.LLMClient", FakeClient)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
            "capability": "image_input",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is False
    assert payload["capability"] == "image_input"
    assert payload["capability_status"] == "unknown"
    assert payload["supports_image_input"] is None
    assert payload["api_key_source"] == "not-required"
    assert payload["requires_api_key"] is False
    assert recorded_scene_events
    fields = recorded_scene_events[-1][1]["fields"]
    assert fields["capability"] == "image_input"
    assert fields["supportsImageInput"] is None
    assert "base64" not in str(fields).lower()


def test_config_workspace_test_llm_image_input_maps_provider_unsupported(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages, tools=None, metadata=None):
            assert messages[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
            raise RuntimeError("OpenAIException - No endpoints found that support image input")

    monkeypatch.setattr("core.llm.LLMClient", FakeClient)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
            "capability": "image_input",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is False
    assert payload["capability_status"] == "unsupported"
    assert payload["supports_image_input"] is False
    assert payload["message"] == "image input is not supported by this model route"


def test_config_workspace_draft_model_rejects_path_api_key_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "deepseek_v4_pro",
            "provider": public_config["llm"]["model_library"]["deepseek_v4_pro"]["provider"],
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "details": public_config["llm"]["model_library"]["deepseek_v4_pro"],
            "apiKeyEnv": "PATH",
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 422
    assert "PATH" in response.json()["detail"]


def test_config_workspace_draft_model_allows_approved_ai_pixel_relay_host(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["model_library"]["relay_openai_gpt_5_5"]
    provider = copy.deepcopy(target["provider"])
    provider["base_url"] = "https://ai-pixel.online"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "relay_openai_gpt_5_5",
            "provider": provider,
            "model": "gpt-5.5",
            "label": "GPT-5.5 via relay",
            "details": target,
            "apiKeyEnv": "VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    updated = payload["publicConfig"]["llm"]["model_library"]["relay_openai_gpt_5_5"]
    assert updated["provider"]["base_url"] == "https://ai-pixel.online"


def test_config_workspace_draft_model_allows_custom_openai_compatible_relay(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_openai_compatible_relay",
            "modelId": "custom_relay",
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://relay.example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "model": "custom-gpt",
            "label": "Custom Relay",
            "details": {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_CUSTOM_RELAY_API_KEY",
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    updated = payload["publicConfig"]["llm"]["model_library"]["custom_relay"]
    assert updated["provider"]["kind"] == "openai_compatible"
    assert updated["provider"]["base_url"] == "https://relay.example.com/v1"
    assert updated["api_key_env"] == "VIBELUTION_LLM_CUSTOM_RELAY_API_KEY"
    assert "VIBELUTION_LLM_CUSTOM_RELAY_API_KEY" in payload["draftMeta"]["pending_api_keys"]


def test_config_workspace_draft_model_allows_custom_relay_responses(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_relay_responses",
            "modelId": "custom_relay_responses_model",
            "provider": {
                "kind": "relay",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://ai-pixel.online",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 1000000,
            },
            "model": "gpt-5.5",
            "label": "Custom Relay Responses",
            "details": {
                "transport": "responses",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_CUSTOM_RELAY_RESPONSES_MODEL_API_KEY",
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    updated = payload["publicConfig"]["llm"]["model_library"]["custom_relay_responses_model"]
    assert updated["provider"]["kind"] == "relay"
    assert updated["provider"]["base_url"] == "https://ai-pixel.online"
    assert updated["transport"] == "responses"
    assert updated["api_key_env"] == "VIBELUTION_LLM_CUSTOM_RELAY_RESPONSES_MODEL_API_KEY"


def test_config_workspace_draft_model_rejects_unknown_model_id(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "generated_from_profile",
            "provider": public_config["llm"]["model_library"]["relay_openai_gpt_5_5"]["provider"],
            "model": "gpt-5.5",
            "label": "Generated from profile",
            "details": public_config["llm"]["model_library"]["relay_openai_gpt_5_5"],
            "apiKeyEnv": "VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "unknown LLM model" in response.json()["detail"]


def test_config_workspace_draft_model_auto_generates_custom_relay_model_id(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_openai_compatible_relay",
            "modelId": "",
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "model": "gpt-5.5",
            "label": "GPT-5.5",
            "details": {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    model_library = response.json()["publicConfig"]["llm"]["model_library"]
    assert "gpt_5_5_gpt_5_5" in model_library
    assert "custom_openai_compatible_relay" not in model_library
    assert model_library["gpt_5_5_gpt_5_5"]["api_key_env"] == "VIBELUTION_LLM_GPT_5_5_GPT_5_5_API_KEY"


def test_config_workspace_draft_model_rejects_custom_relay_localhost(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_openai_compatible_relay",
            "modelId": "custom_relay",
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "http://127.0.0.1:11434/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "model": "custom-gpt",
            "label": "Custom Relay",
            "details": {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_CUSTOM_RELAY_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "localhost" in response.json()["detail"] or "https" in response.json()["detail"]


def test_config_workspace_discovers_custom_openai_compatible_models(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_base"] = api_base
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        seen["timeout"] = timeout
        return [
            {"id": "gpt-5.5", "label": "GPT-5.5", "context_window": 1000000},
            {"id": "gpt-5.5-mini", "label": "GPT-5.5 Mini", "context_window": 128000},
        ]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["models"][0]["id"] == "gpt-5.5"
    assert payload["models"][0]["contextWindow"] == 1000000
    assert payload["models"][1]["id"] == "gpt-5.5-mini"
    assert seen == {
        "api_base": "https://example.com/v1",
        "api_key": "draft-secret",
        "api_key_source": "手动输入",
        "timeout": 10,
    }


def test_config_workspace_model_discovery_uses_configured_environment_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setenv("VIBELUTION_LLM_CUSTOM_RELAY_API_KEY", "env-secret")

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_base"] = api_base
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        return [{"id": "relay-model", "label": "Relay Model"}]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "VIBELUTION_LLM_CUSTOM_RELAY_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    assert response.json()["apiKeySource"] == "系统环境变量 VIBELUTION_LLM_CUSTOM_RELAY_API_KEY"
    assert seen == {
        "api_base": "https://example.com/v1",
        "api_key": "env-secret",
        "api_key_source": "系统环境变量 VIBELUTION_LLM_CUSTOM_RELAY_API_KEY",
    }


def test_config_workspace_model_discovery_url_candidates_do_not_duplicate_v1():
    assert config_service._model_discovery_urls("https://ai-pixel.online") == [
        "https://ai-pixel.online/models",
        "https://ai-pixel.online/v1/models",
    ]
    assert config_service._model_discovery_urls("https://ai-pixel.online/v1") == [
        "https://ai-pixel.online/v1/models",
    ]
    assert config_service._model_discovery_urls("https://ai-pixel.online/v1/models") == [
        "https://ai-pixel.online/v1/models",
    ]


def test_config_workspace_model_discovery_rejects_localhost(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "http://127.0.0.1:11434/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "localhost" in response.json()["detail"] or "https" in response.json()["detail"]


def test_config_workspace_apply_rejects_stale_base_hash(monkeypatch):
    original = copy.deepcopy(load_public_config())
    stale_hash = public_config_hash(original)
    external = copy.deepcopy(original)
    external.setdefault("ui", {})["language"] = "en"
    public_config = external

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": original,
            "draftMeta": {},
            "baseHash": stale_hash,
        },
    )

    assert response.status_code == 409
    assert "重新加载" in response.json()["detail"]


def test_config_workspace_apply_persists_changes_and_pending_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    writes = []
    deletes = []
    reloads = []
    scene_events = []

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr(config_service, "_set_user_env_var", lambda name, value: writes.append((name, value)))
    monkeypatch.setattr(config_service, "_delete_user_env_var", lambda name: deletes.append(name))
    monkeypatch.setattr(
        config_service,
        "reload_config",
        lambda config_path=None: reloads.append((config_path, copy.deepcopy(public_config)))
        or config_service.build_effective_config(public_config),
    )
    monkeypatch.setattr(config_service, "_record_config_scene_event", lambda *args, **kwargs: scene_events.append((args, kwargs)))

    payload = copy.deepcopy(public_config)
    payload.setdefault("ui", {})["language"] = "en"

    draft_response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": payload,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "deepseek_v4_pro",
            "provider": payload["llm"]["model_library"]["deepseek_v4_pro"]["provider"],
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "details": payload["llm"]["model_library"]["deepseek_v4_pro"],
            "apiKeyEnv": "VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY",
            "apiKey": "draft-secret",
        },
    )

    assert draft_response.status_code == 200
    draft_payload = draft_response.json()

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": draft_payload["publicConfig"],
            "draftMeta": draft_payload["draftMeta"],
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 200
    persisted = response.json()
    assert public_config["ui"]["language"] == "en"
    assert writes == [("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", "draft-secret")]
    assert deletes == []
    assert persisted["baseHash"] == persisted["hash"]
    assert len(reloads) == 1
    assert reloads[0][0] == str(config_service.CONFIG_PATH)
    assert reloads[0][1]["ui"]["language"] == "en"
    applied_event = scene_events[-1][1]["fields"]
    assert applied_event["runtimeConfigReloaded"] is True
    assert applied_event["primaryProviderKind"]
    assert applied_event["primaryTransport"]
    assert applied_event["primaryModel"] == config_service.build_effective_config(public_config).llm.get_profile(role="primary").model


def test_config_workspace_apply_ignores_forged_pending_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    writes = []

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(config_service, "save_public_config", lambda updated: None)
    monkeypatch.setattr(config_service, "_set_user_env_var", lambda name, value: writes.append((name, value)))

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": public_config,
            "draftMeta": {
                "pending_api_keys": {"VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY": "forged-secret"},
                "pending_cleared_api_keys": [],
            },
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 200
    assert writes == []


def test_config_and_evolution_share_intake_mode(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("evolution", {})["intake_mode"] = "auto"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(workbench_contract_service, "load_public_config", lambda: copy.deepcopy(public_config))

    config_response = client.get("/api/config/public")
    overview_response = client.get("/api/evolution/overview")

    assert config_response.status_code == 200
    assert overview_response.status_code == 200
    assert config_response.json()["intakeMode"] == "auto"
    assert overview_response.json()["intakeMode"] == "auto"


def test_chat_disable_redirects_home_contract_to_evolution(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    agent_cfg = public_config.setdefault("agent", {})
    modes_cfg = agent_cfg.setdefault("modes", {})
    modes_cfg["chat_enabled"] = False
    modes_cfg["self_evolution_enabled"] = True
    modes_cfg["supervised_evolution_enabled"] = True
    modes_cfg["default_shell_mode"] = "chat"
    public_config.setdefault("evolution", {})["enabled"] = True

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(runtime_service, "load_public_config", lambda: copy.deepcopy(public_config))

    config_response = client.get("/api/config/public")
    runtime_response = client.get("/api/runtime/summary")

    assert config_response.status_code == 200
    assert runtime_response.status_code == 200

    config_payload = config_response.json()
    runtime_payload = runtime_response.json()

    assert config_payload["defaultRoute"] == "/self-evolution"
    assert runtime_payload["defaultRoute"] == "/self-evolution"
    assert config_payload["defaultMode"] == "self_evolution"
    assert runtime_payload["mode"] == "self_evolution"
    assert config_payload["domainAvailability"]["chat"] is False
    assert config_payload["domainAvailability"]["evolution"] is True
    assert runtime_payload["domainAvailability"]["chat"] is False
    assert runtime_payload["domainAvailability"]["evolution"] is True


def test_updating_intake_mode_refreshes_config_and_evolution(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr(workbench_contract_service, "load_public_config", fake_load_public_config)

    update_response = client.put("/api/config/intake-mode", json={"intakeMode": "auto"})
    config_response = client.get("/api/config/public")
    overview_response = client.get("/api/evolution/overview")

    assert update_response.status_code == 200
    assert config_response.status_code == 200
    assert overview_response.status_code == 200
    assert update_response.json()["intakeMode"] == "auto"
    assert config_response.json()["intakeMode"] == "auto"
    assert overview_response.json()["intakeMode"] == "auto"


def test_updating_language_refreshes_config_summary(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("ui", {})["language"] = "zh"

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr("core.web.services.i18n.load_public_config", fake_load_public_config)

    update_response = client.put("/api/config/language", json={"language": "en"})
    config_response = client.get("/api/config/public")

    assert update_response.status_code == 200
    assert config_response.status_code == 200
    assert update_response.json()["language"] == "en"
    assert config_response.json()["language"] == "en"


def test_evolution_routes_use_real_supervised_records(tmp_path, monkeypatch):
    pending_result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="web_pending_episode",
    )
    _write_supervised_decision_record(
        tmp_path,
        "web_pending_run",
        {
            "decision": "PROMOTE",
            "reason": "候选方案值得继续进入治理流程。",
            "gates": [
                {
                    "name": "gym_promotion",
                    "status": "pass",
                    "reason": "proposal created",
                    "metrics": {
                        "promotion_proposal_path": pending_result.promotion_proposal_path,
                        "decision_path": pending_result.decision_path,
                    },
                }
            ],
        },
    )

    active_result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="web_active_episode",
    )
    apply_gym_promotion_proposal(active_result.promotion_proposal_path, project_root=tmp_path)
    activation = activate_gym_promotion_proposal(active_result.promotion_proposal_path, project_root=tmp_path)
    _write_supervised_decision_record(
        tmp_path,
        "web_active_run",
        {
            "decision": "PROMOTE",
            "reason": "候选方案已成为当前建议基线。",
            "gates": [
                {
                    "name": "gym_promotion",
                    "status": "pass",
                    "reason": "proposal activated",
                    "metrics": {
                        "promotion_proposal_path": active_result.promotion_proposal_path,
                        "decision_path": active_result.decision_path,
                    },
                }
            ],
            "advisory_context": {
                "active_count": 1,
                "entries": [
                    {
                        "target_key": activation.target_key,
                        "target_label": "local_transaction_closing_v1",
                        "proposal_id": activation.proposal_id,
                        "runtime_effect": "not_applied",
                        "agent_consumption": "advisory",
                    }
                ],
            },
        },
    )
    _write_workbench_state(
        tmp_path,
        {
            "source": "dataset",
            "dataset_name": "custom_prompt_jsonl",
            "dataset_limit": 2,
            "bundle_name": "custom_prompt_jsonl_v1",
            "keep_worktree": True,
        },
    )

    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    overview_response = client.get("/api/evolution/overview")
    runs_response = client.get("/api/evolution/runs")
    library_response = client.get("/api/evolution/library")

    assert overview_response.status_code == 200
    assert runs_response.status_code == 200
    assert library_response.status_code == 200

    overview_payload = overview_response.json()
    runs_payload = runs_response.json()
    library_payload = library_response.json()

    assert overview_payload["currentStatus"]["decision"] == "PROMOTE"
    assert overview_payload["currentStatus"]["proposalStatus"] == "active"
    assert overview_payload["currentStatus"]["runtimeEffect"] == "not_applied"
    assert overview_payload["currentStatus"]["runSemantics"]["runStatus"] == "success"
    assert overview_payload["currentStatus"]["outcomeSemantics"]["proposalStatusLabel"]
    assert overview_payload["currentStatus"]["actionStates"]["delete"]["enabled"] is False
    assert overview_payload["workbench"]["source"] == "dataset"
    assert overview_payload["workbench"]["datasetName"] == "custom_prompt_jsonl"
    assert overview_payload["recentRuns"][0]["id"] == "web_active_run"
    assert runs_payload[0]["proposalStatus"] == "active"
    assert runs_payload[0]["decision"] == "PROMOTE"
    assert runs_payload[0]["runtimeEffect"] == "not_applied"
    assert runs_payload[0]["outcomeSemantics"]["runtimeEffect"] == "not_applied"
    assert runs_payload[0]["actionStates"]["delete"]["enabled"] is False
    _assert_seeded_case_diagnostic(runs_payload[0]["caseDiagnostics"][0])
    assert any(item["sourceRun"] == "web_active_run" for item in library_payload["items"])
    assert any(item["sourceRun"] == "web_pending_run" for item in library_payload["pending"])
    assert library_payload["items"][0]["proposalStatus"] == "active"
    assert library_payload["pending"][0]["proposalStatus"] == "proposed"
    assert library_payload["items"][0]["outcomeSemantics"]["proposalStatus"] == "active"


def test_evolution_runs_route_exposes_case_type_and_expected_outcome(tmp_path, monkeypatch):
    _write_supervised_decision_record(
        tmp_path,
        "web_dynamic_case_schema",
        {
            "case_summaries": [
                {
                    "case_id": "dynamic_calendar_change",
                    "case_type": "dynamic_replanning",
                    "baseline_status": "success",
                    "candidate_status": "success",
                    "decision_signal": "stable_success",
                    "difference_summary": "dynamic case stayed stable",
                    "failure_taxonomy": ["dynamic_replanning_case", "post_adaptation_verification_missing"],
                    "intake_provenance": {
                        "case_type": "dynamic_replanning",
                        "expected_final_state": {"calendar_event": "rescheduled"},
                        "dynamic_events": [{"event": "deadline_changed"}],
                    },
                },
                {
                    "case_id": "impossible_missing_permission",
                    "case_type": "impossible_task",
                    "baseline_status": "success",
                    "candidate_status": "success",
                    "decision_signal": "stable_success",
                    "difference_summary": "impossible case stayed stable",
                    "failure_taxonomy": ["impossible_task_case"],
                    "intake_provenance": {
                        "case_type": "impossible_task",
                        "expected_infeasible_outcome": {"status": "infeasible", "reason": "missing_permission"},
                    },
                },
            ],
        },
    )
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    response = client.get("/api/evolution/runs")

    assert response.status_code == 200
    diagnostics = response.json()[0]["caseDiagnostics"]
    by_case = {item["caseId"]: item for item in diagnostics}
    assert by_case["dynamic_calendar_change"]["caseType"] == "dynamic_replanning"
    assert by_case["dynamic_calendar_change"]["expectedFinalState"]["calendar_event"] == "rescheduled"
    assert by_case["dynamic_calendar_change"]["dynamicEvents"][0]["event"] == "deadline_changed"
    assert by_case["impossible_missing_permission"]["caseType"] == "impossible_task"
    assert by_case["impossible_missing_permission"]["expectedInfeasibleOutcome"]["status"] == "infeasible"


def test_evolution_routes_handle_empty_supervised_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    overview_response = client.get("/api/evolution/overview")
    runs_response = client.get("/api/evolution/runs")
    library_response = client.get("/api/evolution/library")

    assert overview_response.status_code == 200
    assert runs_response.status_code == 200
    assert library_response.status_code == 200
    assert overview_response.json()["currentStatus"]["state"] == "idle"
    assert overview_response.json()["workbench"]["source"] == "unknown"
    assert runs_response.json() == []
    assert library_response.json() == {"items": [], "pending": []}


def test_evolution_library_exposes_self_evolution_candidates_as_pending_review_source(tmp_path, monkeypatch):
    append_candidate_record(
        {
            "candidate_id": "prompt_candidate:web-self-review",
            "candidate_type": "prompt_candidate",
            "source_experience_id": "exp-review",
            "source_reflection_id": "refl-review",
            "source_run_id": "web-self-review",
            "txn_id": "txn-review",
            "provenance": {
                "source_experience_id": "exp-review",
                "source_reflection_id": "refl-review",
                "source_run_id": "web-self-review",
                "txn_id": "txn-review",
                "evidence_refs": ["logs/runtime_scenes/pkg/agent/self_evolution_runs/web-self-review.jsonl"],
            },
            "payload": {
                "suggested_prompt_change": "Ask for the smallest bounded validation before retrying.",
            },
            "risk_level": "medium",
            "allowed_downstream_uses": ["supervised_review", "accepted_baseline", "runtime_prompt_override"],
            "blocked_downstream_uses": [],
        },
        project_root=tmp_path,
    )
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    queue_response = client.get("/api/evolution/self/candidates")
    library_response = client.get("/api/evolution/library")
    detail_response = client.get("/api/evolution/proposals/prompt_candidate:web-self-review")

    assert queue_response.status_code == 200
    assert library_response.status_code == 200
    assert detail_response.status_code == 200
    queue_payload = queue_response.json()
    library_payload = library_response.json()
    detail_payload = detail_response.json()
    item = queue_payload["items"][0]

    assert queue_payload["enabled"] is True
    assert queue_payload["pendingCount"] == 1
    assert queue_payload["counts"]["prompt_candidate"] == 1
    assert item["id"] == "prompt_candidate:web-self-review"
    assert item["sourceRun"] == item["id"]
    assert item["sourceSelfRunId"] == "web-self-review"
    assert item["ingestMode"] == "self_evolution_candidate"
    assert item["candidateType"] == "prompt_candidate"
    assert item["proposalStatus"] == "self_candidate_pending"
    assert item["reviewState"] == "pending"
    assert item["riskLevel"] == "medium"
    assert item["supervisedRequired"] is True
    assert item["candidateOnly"] is True
    assert item["autoApply"] is False
    assert item["canDelete"] is False
    assert item["availableActions"] == []
    assert item["actionStates"]["apply"]["enabled"] is False
    assert item["outcomeSemantics"]["isRuntimeApplied"] is False
    assert item["outcomeSemantics"]["decisionLabel"] == "待监督审阅"
    assert item["outcomeSemantics"]["proposalStatusLabel"] == "自进化候选待审阅"
    assert "accepted_baseline" not in item["allowedDownstreamUses"]
    assert "runtime_prompt_override" not in item["allowedDownstreamUses"]
    assert "accepted_baseline" in item["blockedDownstreamUses"]
    assert "selection_policy" in item["blockedDownstreamUses"]
    assert item["provenance"]["source_run_id"] == "web-self-review"
    assert item["evidenceRefs"] == ["logs/runtime_scenes/pkg/agent/self_evolution_runs/web-self-review.jsonl"]
    assert any(pending["id"] == item["id"] for pending in library_payload["pending"])
    assert next(pending for pending in library_payload["pending"] if pending["id"] == item["id"])["riskLevel"] == "medium"
    assert library_payload["items"] == []
    assert detail_payload["sessionId"] == item["id"]
    assert detail_payload["sourceRun"] == item["id"]
    assert detail_payload["canEdit"] is False
    assert detail_payload["canDelete"] is False
    assert detail_payload["availableActions"] == []
    assert any("web-self-review" in note for note in detail_payload["review"]["whyCreated"])
    assert not any("来源自进化运行：prompt_candidate:web-self-review" in note for note in detail_payload["review"]["whyCreated"])
    assert detail_payload["proposalStatus"] == "self_candidate_pending"
    assert detail_payload["proposal"]["status"] == "self_candidate_pending"
    assert detail_payload["outcomeSemantics"]["isRuntimeApplied"] is False
    assert detail_payload["outcomeSemantics"]["decisionLabel"] == "待监督审阅"
    assert detail_payload["supervised"]["riskLevel"] == "medium"
    assert detail_payload["paths"]["selfEvolutionCandidatePath"].endswith("prompt_candidates.jsonl")
    assert detail_payload["rawProposal"]["candidate_id"] == item["id"]


def test_self_evolution_candidate_review_route_hides_when_self_evolution_disabled(tmp_path, monkeypatch):
    append_candidate_record(
        {
            "candidate_id": "skill_candidate:hidden",
            "candidate_type": "skill_candidate",
            "source_experience_id": "exp-hidden",
            "source_reflection_id": "refl-hidden",
            "source_run_id": "web-self-hidden",
            "provenance": {
                "source_experience_id": "exp-hidden",
                "source_reflection_id": "refl-hidden",
                "source_run_id": "web-self-hidden",
                "evidence_refs": ["reflection:web-self-hidden"],
            },
        },
        project_root=tmp_path,
    )
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "modeAvailability": {
                "chat": True,
                "self_evolution": False,
                "supervised_evolution": True,
            }
        },
    )

    queue_response = client.get("/api/evolution/self/candidates")
    library_response = client.get("/api/evolution/library")

    assert queue_response.status_code == 200
    assert queue_response.json()["enabled"] is False
    assert queue_response.json()["pendingCount"] == 0
    assert queue_response.json()["items"] == []
    assert library_response.json() == {"items": [], "pending": []}


def test_self_evolution_candidate_review_route_normalizes_legacy_risk(tmp_path, monkeypatch):
    append_candidate_record(
        {
            "candidate_id": "proposal_candidate:legacy-risk",
            "candidate_type": "proposal_candidate",
            "source_experience_id": "exp-legacy-risk",
            "source_run_id": "web-self-legacy-risk",
            "risk_level": "accepted",
            "provenance": {
                "source_experience_id": "exp-legacy-risk",
                "source_run_id": "web-self-legacy-risk",
                "evidence_refs": ["reflection:web-self-legacy-risk"],
            },
        },
        project_root=tmp_path,
    )
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            }
        },
    )

    response = client.get("/api/evolution/self/candidates")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["riskLevel"] == "pending_review"


def test_evolution_workbench_route_exposes_dataset_choices_and_saved_state(tmp_path, monkeypatch):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "real_bundle_v1.json").write_text(
        json.dumps(
            {
                "bundle_name": "real_bundle_v1",
                "benchmark": "dry",
                "cases": [{"case_id": "probe", "prompt": "run"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_workbench_state(
        tmp_path,
        {
            "source": "bundle",
            "bundle_name": "saved_bundle_v1",
            "keep_worktree": False,
        },
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/evolution/workbench")

    assert response.status_code == 200
    payload = response.json()
    assert payload["defaultBundleName"]
    assert payload["savedState"]["source"] == "bundle"
    assert payload["savedState"]["bundleName"] == "saved_bundle_v1"
    assert {
        "name": "real_bundle_v1",
        "declaredName": "real_bundle_v1",
        "path": str(bundle_dir / "real_bundle_v1.json"),
        "caseCount": 1,
        "benchmark": "dry",
    } in payload["bundles"]
    dry_run = next(item for item in payload["datasets"] if item["name"] == "supervised_dry_run")
    assert dry_run["effective"] is True
    assert dry_run["caseCount"] >= 1
    assert dry_run["usabilityStatus"] == "ready"
    assert payload["activeRun"] is None


def test_supervised_worktree_run_routes_start_and_list_simulation(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-worktree-start", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-worktree-start",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "closed_loop_v1.json").write_text(
        json.dumps(
            {
                "bundle_name": "closed_loop_v1",
                "benchmark": "unit",
                "cases": [
                    {"case_id": "one", "prompt": "one"},
                    {"case_id": "two", "prompt": "two"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(supervised_worktree_evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(
        supervised_worktree_evolution_service,
        "_raise_if_lease_conflict",
        lambda *, lang: None,
    )

    class ImmediateExecutor:
        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return None

    def fake_worktree_factory(root: Path, run_id: str) -> dict:
        candidate = tmp_path / "candidate"
        candidate.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=str(candidate), check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.local"], cwd=str(candidate), check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(candidate), check=True)
        for source in tmp_path.rglob("*"):
            if not source.is_file():
                continue
            rel = source.relative_to(tmp_path)
            if ".git" in rel.parts or rel.parts[0] == "candidate":
                continue
            target = candidate / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        subprocess.run(["git", "add", "."], cwd=str(candidate), check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=str(candidate), check=True, capture_output=True, text=True)
        (candidate / "agent.py").write_text("print('candidate')\n", encoding="utf-8")
        return {
            "path": str(candidate),
            "baseHead": "base",
            "checkpointCommit": "base",
            "checkpointRef": "",
            "trackedDirty": False,
            "untrackedFiles": [],
        }

    monkeypatch.setattr(supervised_worktree_evolution_service, "_RUN_EXECUTOR", ImmediateExecutor())
    monkeypatch.setattr(supervised_worktree_evolution_service, "_default_worktree_factory", fake_worktree_factory)

    start_response = client.post(
        "/api/evolution/worktree-runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "closed_loop_v1",
            "mode": "auto",
            "uiRoute": "/evolution?view=overview",
            "clientAction": "start_closed_loop_button",
        },
    )

    assert start_response.status_code == 202
    start_payload = start_response.json()
    run_id = start_payload["runId"]
    detail_response = client.get(f"/api/evolution/worktree-runs/{run_id}")
    list_response = client.get("/api/evolution/worktree-runs")

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["status"] == "done"
    assert detail_payload["decision"]["recommendedAction"] == "preserve"
    assert detail_payload["startRequest"] == {
        "requestSource": "api:evolution.worktree-runs",
        "uiRoute": "/evolution?view=overview",
        "initiator": "user",
        "clientAction": "start_closed_loop_button",
    }
    assert list_response.status_code == 200
    assert list_response.json()[0]["runId"] == run_id
    scene_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "supervised_worktree_run.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    started = next(event for event in scene_events if event["event_code"] == "supervised_worktree_run.started")
    assert started["fields"]["runId"] == run_id
    assert started["fields"]["requestSource"] == "api:evolution.worktree-runs"
    assert started["fields"]["uiRoute"] == "/evolution?view=overview"
    assert started["fields"]["clientAction"] == "start_closed_loop_button"
    assert "supervised_worktree_run.started" in (scene_dir / "lifecycle.jsonl").read_text(encoding="utf-8")

    child_log = scene_dir / "agent" / "supervised_worktree_runs" / f"{run_id}.jsonl"
    child_payloads = [
        json.loads(line)
        for line in child_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert child_payloads[0]["startRequest"]["requestSource"] == "api:evolution.worktree-runs"
    assert child_payloads[0]["startRequest"]["uiRoute"] == "/evolution?view=overview"


def test_supervised_worktree_run_route_requires_real_llm_cost_confirmation(tmp_path, monkeypatch):
    bundle_dir = tmp_path / "workspace" / "evaluation" / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "closed_loop_v1.json").write_text(
        json.dumps(
            {
                "bundle_name": "closed_loop_v1",
                "benchmark": "unit",
                "cases": [{"case_id": "one", "prompt": "one"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(supervised_worktree_evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_worktree_evolution_service,
        "_raise_if_lease_conflict",
        lambda *, lang: None,
    )

    response = client.post(
        "/api/evolution/worktree-runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "closed_loop_v1",
            "executionMode": "real",
            "confirmRealLlmCost": False,
        },
    )

    assert response.status_code == 422
    assert "tokens" in response.json()["detail"]


def test_chat_review_routes_list_and_approve_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)

    capture_service = ChatDatasetCaptureService(project_root=tmp_path)
    candidate = capture_service.capture_candidate(
        mode="chat",
        session_id="session-live",
        source_log_path=str(tmp_path / "log_info" / "conversation_session-live.jsonl"),
        turns=[
            ChatTurnRecord(
                turn_number=1,
                user_message="继续排查网页聊天提交链路",
                assistant_message="我先检查 session_service 里的真实提交路径。",
                tool_calls=["read_file_tool"],
                tool_call_count=1,
            ),
            ChatTurnRecord(
                turn_number=2,
                user_message="把根因和下一步说清楚",
                assistant_message="结论：网页聊天每轮都会重建 agent。下一步：把持久化消息重建成 turn 记录并接入审核。",
                tool_calls=["apply_patch_tool"],
                tool_call_count=1,
                had_explicit_conclusion=True,
                had_next_action=True,
            ),
        ],
    )

    assert candidate is not None

    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["pendingCount"] == 1
    assert queue_payload["positiveCount"] == 0
    assert queue_payload["negativeCount"] == 0
    assert queue_payload["discardCount"] == 0
    assert queue_payload["countsByStatus"] == {
        "pending": 1,
        "positive": 0,
        "negative": 0,
        "discard": 0,
    }
    assert queue_payload["lifecycle"]["rawChatDirectTrainingAllowed"] is False
    assert queue_payload["lifecycle"]["candidateStage"] == "pending_review"
    assert queue_payload["lifecycle"]["reviewedCaseStage"] == "reviewed_chat_case"
    assert queue_payload["lifecycle"]["datasetTarget"] == "chat_reviewed_multiturn"
    assert queue_payload["lifecycle"]["negativeTarget"] == "chat_negative_multiturn"
    assert "supervised_evaluation" in queue_payload["lifecycle"]["allowedDownstreamUses"]
    candidate_id = queue_payload["items"][0]["candidateId"]

    decision_response = client.post(
        f"/api/evolution/chat-review/{candidate_id}/decision",
        json={
            "decision": "negative",
            "reviewerNote": "keep as an anti-pattern",
            "reasonCode": "missing_evidence",
            "errorType": "ungrounded_inference",
            "correctPrinciple": "inspect logs before concluding",
        },
    )

    assert decision_response.status_code == 200
    decision_payload = decision_response.json()
    assert decision_payload["status"] == "negative"

    paths = resolve_chat_dataset_paths(project_root=tmp_path)
    assert paths.negative_jsonl_path.exists()

    workbench_response = client.get("/api/evolution/workbench")
    assert workbench_response.status_code == 200
    dataset_entry = next(
        item for item in workbench_response.json()["datasets"] if item["name"] == "chat_reviewed_multiturn"
    )
    assert dataset_entry["available"] is True
    assert dataset_entry["reviewRequired"] is True
    assert dataset_entry["sourceTrack"] == "dialogue"
    assert dataset_entry["holdoutAllowed"] is False
    assert dataset_entry["rawChatDirectTrainingAllowed"] is False
    assert "gym_candidate_case" in dataset_entry["allowedDownstreamUses"]


def test_chat_review_bulk_delete_discards_pending_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        chat_review_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    capture_service = ChatDatasetCaptureService(project_root=tmp_path)
    candidate_a = capture_service.capture_candidate(
        mode="chat",
        session_id="session-bulk-a",
        source_log_path=str(tmp_path / "log_info" / "conversation_session-bulk-a.jsonl"),
        turns=[
            ChatTurnRecord(
                turn_number=1,
                user_message="继续整理监督评审工作区",
                assistant_message="我先读取评审队列和样式文件确认现状。",
                tool_calls=["read_file_tool"],
                tool_call_count=1,
            ),
            ChatTurnRecord(
                turn_number=2,
                user_message="把批量删除做好",
                assistant_message="结论：批量删除应写成软丢弃。下一步我会补接口和测试。",
                tool_calls=["apply_patch_tool"],
                tool_call_count=1,
                had_explicit_conclusion=True,
                had_next_action=True,
            ),
        ],
    )
    candidate_b = capture_service.capture_candidate(
        mode="chat",
        session_id="session-bulk-b",
        source_log_path=str(tmp_path / "log_info" / "conversation_session-bulk-b.jsonl"),
        turns=[
            ChatTurnRecord(
                turn_number=1,
                user_message="复核一个已处理样本",
                assistant_message="我会先查队列状态再操作。",
                tool_calls=["read_file_tool"],
                tool_call_count=1,
            ),
            ChatTurnRecord(
                turn_number=2,
                user_message="这个作为正例",
                assistant_message="结论：这个样本具备稳定推进信号。下一步记录为正例。",
                tool_calls=["apply_patch_tool"],
                tool_call_count=1,
                had_explicit_conclusion=True,
                had_next_action=True,
            ),
        ],
    )
    assert candidate_a is not None
    assert candidate_b is not None

    positive_response = client.post(
        f"/api/evolution/chat-review/{candidate_b.candidate_id}/decision",
        json={"decision": "positive", "reviewerNote": "keep this handled sample"},
    )
    assert positive_response.status_code == 200

    response = client.post(
        "/api/evolution/chat-review/delete",
        json={
            "candidateIds": [
                candidate_a.candidate_id,
                candidate_a.candidate_id,
                candidate_b.candidate_id,
                "missing-candidate",
            ],
            "reviewerNote": "bulk discard from review workspace",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["requestedCount"] == 3
    assert payload["discardedCount"] == 1
    assert payload["skippedCount"] == 2
    assert payload["failedCount"] == 0
    results = {item["candidateId"]: item for item in payload["results"]}
    assert results[candidate_a.candidate_id]["status"] == "discarded"
    assert results[candidate_b.candidate_id]["status"] == "skipped"
    assert results["missing-candidate"]["status"] == "not_found"

    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["pendingCount"] == 0
    assert queue_payload["positiveCount"] == 1
    assert queue_payload["discardCount"] == 1
    statuses = {item["candidateId"]: item["status"] for item in queue_payload["items"]}
    assert statuses[candidate_a.candidate_id] == "discard"
    assert statuses[candidate_b.candidate_id] == "positive"

    paths = resolve_chat_dataset_paths(project_root=tmp_path)
    assert paths.rejected_log_path.exists()
    assert candidate_a.candidate_id in paths.rejected_log_path.read_text(encoding="utf-8")
    assert len(recorded_scene_events) == 1
    event_args, event_kwargs = recorded_scene_events[0]
    assert event_args[:3] == (
        "chat_review",
        "bulk_discard",
        "chat_review.bulk_discard.completed",
    )
    assert event_kwargs["fields"]["candidateIds"] == [
        candidate_a.candidate_id,
        candidate_b.candidate_id,
        "missing-candidate",
    ]
    assert event_kwargs["fields"]["discardedIds"] == [candidate_a.candidate_id]
    assert event_kwargs["fields"]["skippedIds"] == [candidate_b.candidate_id, "missing-candidate"]
    assert event_kwargs["fields"]["failedIds"] == []


def test_workbench_dataset_list_backfills_new_builtin_datasets(tmp_path, monkeypatch):
    registry_path = tmp_path / "workspace" / "evaluation" / "datasets" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "datasets": [
                    {
                        "name": "custom_prompt_jsonl",
                        "kind": "prompt_jsonl",
                        "bundle_name": "custom_prompt_jsonl_v1",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/evolution/workbench")

    assert response.status_code == 200
    rows = response.json()["datasets"]
    assert any(item["name"] == "generated_cases" for item in rows)
    chat_row = next(item for item in rows if item["name"] == "chat_reviewed_multiturn")
    assert chat_row["reviewRequired"] is True
    assert chat_row["sourceTrack"] == "dialogue"
    assert chat_row["holdoutAllowed"] is False
    assert chat_row["effective"] is False
    assert chat_row["caseCount"] == 0
    assert chat_row["usabilityStatus"] == "empty"


def test_start_supervised_run_from_dataset_exposes_active_snapshot_and_sse(tmp_path, monkeypatch):
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "custom_prompt_tasks.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps({"case_id": "case_1", "prompt": "fix bug"}) + "\n",
        encoding="utf-8",
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_agent_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "dataset",
            "datasetName": "custom_prompt_jsonl",
            "datasetLimit": 2,
            "keepWorktree": True,
        },
    )
    active_response = client.get("/api/evolution/active-run")
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["sourceKind"] == "dataset"
    assert payload["datasetName"] == "custom_prompt_jsonl"
    assert payload["bundleName"] == "custom_prompt_jsonl_v1"
    assert payload["keepWorktree"] is True
    assert payload["agentBindings"]["baseline"]["profileId"] == "supervised_baseline"
    assert payload["agentBindings"]["candidate"]["profileId"] == "supervised_candidate"

    assert active_response.status_code == 200
    assert active_response.json()["runId"] == payload["runId"]
    assert active_response.json()["agentBindings"]["baseline"]["agentId"] == payload["agentBindings"]["baseline"]["agentId"]

    stream = supervised_control_service.stream_active_supervised_run_events(
        initial_snapshot=active_response.json()
    )
    raw_event = next(stream)
    stream.close()

    class _SingleEventResponse:
        def iter_lines(self):
            for line in str(raw_event).splitlines():
                yield line
            yield ""

    event = _read_first_sse_event(_SingleEventResponse())
    event_payload = json.loads(event["data"])
    assert event["event"] == "supervised_run"
    assert event_payload["snapshot"]["runId"] == payload["runId"]
    assert event_payload["snapshot"]["status"] == "queued"
    assert event_payload["snapshot"]["agentBindings"]["baseline"]["agentId"] == payload["agentBindings"]["baseline"]["agentId"]

    supervised_control_service._handle_progress_event(
        payload["runId"],
        {
            "event": "role_start",
            "session_id": "supervised-demo",
            "case_index": 1,
            "case_total": 1,
            "case_id": "case_1",
            "role": "baseline",
            "scenario": "transaction",
            "mode": "single_turn",
            "prompt": "fix bug",
            "agent_binding": payload["agentBindings"]["baseline"],
        },
    )
    progress_snapshot = supervised_control_service.get_supervised_run_snapshot(payload["runId"])
    assert progress_snapshot["currentAgentBinding"]["agentId"] == payload["agentBindings"]["baseline"]["agentId"]
    assert progress_snapshot["eventTail"][-1]["agentBinding"]["profileId"] == "supervised_baseline"

    state_path = tmp_path / "workspace" / "supervised_evolution" / "workbench_state.json"
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "custom_prompt_jsonl_v1.json"
    assert state_path.exists()
    assert bundle_path.exists()

    _reset_supervised_live_state()


def test_start_supervised_run_reports_stale_agent_slot_as_validation_error(tmp_path, monkeypatch):
    dataset_path = tmp_path / "workspace" / "evaluation" / "datasets" / "custom_prompt_tasks.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps({"case_id": "case_1", "prompt": "fix bug"}) + "\n",
        encoding="utf-8",
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_agent_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: pytest.fail("stale Agent slot must block before run submission"),
    )
    supervised_agent_service.ensure_supervised_agent_instances()
    replacement = agent_directory_service.create_agent_instance(
        display_name="已归档的基线 Agent",
        profile_id="primary",
        primary_mode="supervised_evolution",
        role_key="baseline",
        prompt_template_id="prompt-supervised-baseline",
    )
    current = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    slots = dict(current["slots"])
    slots["baseline"] = replacement["agentId"]
    agent_mode_binding_service.update_mode_binding("supervised_evolution", slots=slots)
    agent_directory_service.archive_agent_instance(replacement["agentId"])

    response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "dataset",
            "datasetName": "custom_prompt_jsonl",
            "datasetLimit": 1,
            "keepWorktree": True,
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "baseline" in detail
    assert replacement["agentId"] in detail


def test_start_supervised_run_from_web_does_not_write_real_runtime_manager_store(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}),
        encoding="utf-8",
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    assert response.status_code == 202
    run_id = response.json()["runId"]
    run_path, index_path = _real_runtime_manager_evolution_paths("supervised", run_id)
    original_index_text = _read_optional_text(index_path)

    try:
        active_response = client.get("/api/evolution/active-run")

        assert active_response.status_code == 200
        assert active_response.json()["runId"] == run_id
        assert not run_path.exists()
        current_index_text = _read_optional_text(index_path)
        assert current_index_text is None or run_id not in current_index_text
    finally:
        _restore_real_runtime_index_if_touched("supervised", run_id, original_index_text)
        _reset_supervised_live_state()


def test_start_supervised_run_from_bundle_uses_launchable_file_stem(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "launchable_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps({"bundle_name": "declared_inside_json", "cases": [{"case_id": "case_1"}]}),
        encoding="utf-8",
    )
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "launchable_bundle",
            "keepWorktree": False,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["bundleName"] == "launchable_bundle"
    state_path = tmp_path / "workspace" / "supervised_evolution" / "workbench_state.json"
    saved_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved_state["bundle_name"] == "launchable_bundle"

    _reset_supervised_live_state()


def test_start_supervised_run_rejects_second_active_run(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    first = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    second = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )

    assert first.status_code == 202
    assert second.status_code == 409

    _reset_supervised_live_state()


def test_start_supervised_run_rejects_when_self_evolution_lease_active(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    _reset_supervised_live_state()
    _reset_self_evolution_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    self_snapshot = {
        "runId": "web-self-active-lease",
        "runKind": "self_evolution_run",
        "status": "running",
        "leases": ["evolution_transaction", "worktree_write", "memory_write"],
        "startedAt": "2026-05-21T00:00:00",
        "updatedAt": "2026-05-21T00:00:00",
    }
    self_evolution_control_service.persist_manager_run_snapshot("self", self_snapshot, active_run_id=self_snapshot["runId"])

    response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )

    assert response.status_code == 409
    assert "resource" in response.json()["detail"].lower() or "资源" in response.json()["detail"]

    _reset_supervised_live_state()
    _reset_self_evolution_live_state()


def test_supervised_run_control_routes_pause_resume_and_terminate(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    start_response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    run_id = start_response.json()["runId"]

    pause_response = client.post(f"/api/evolution/runs/{run_id}/pause")
    active_after_pause = client.get("/api/evolution/active-run")
    blocked_start = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    resume_response = client.post(f"/api/evolution/runs/{run_id}/resume")
    terminate_response = client.post(f"/api/evolution/runs/{run_id}/terminate")
    active_after_terminate = client.get("/api/evolution/active-run")

    assert start_response.status_code == 202
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"
    assert pause_response.json()["pauseRequested"] is True
    assert active_after_pause.status_code == 200
    assert active_after_pause.json()["status"] == "paused"
    assert blocked_start.status_code == 409
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "queued"
    assert resume_response.json()["pauseRequested"] is False
    assert terminate_response.status_code == 200
    assert terminate_response.json()["status"] == "cancelled"
    assert terminate_response.json()["stopRequested"] is True
    assert active_after_terminate.status_code == 200
    assert active_after_terminate.json() is None

    _reset_supervised_live_state()


def test_supervised_run_delete_route_clears_queued_run_and_unlocks_start(tmp_path, monkeypatch):
    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    _reset_supervised_live_state()
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    start_response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    run_id = start_response.json()["runId"]

    delete_response = client.delete(f"/api/evolution/runs/{run_id}")
    active_after_delete = client.get("/api/evolution/active-run")
    restart_response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )

    assert start_response.status_code == 202
    assert delete_response.status_code == 200, delete_response.json()
    assert delete_response.json()["deleted"] is True
    assert delete_response.json()["clearedActive"] is True
    assert active_after_delete.status_code == 200
    assert active_after_delete.json() is None
    assert restart_response.status_code == 202
    assert restart_response.json()["runId"] != run_id

    _reset_supervised_live_state()


def test_supervised_run_delete_route_rejects_running_run():
    _reset_supervised_live_state()
    context = {
        "runId": "web-supervised-running-delete",
        "lang": "en",
        "sourceKind": "bundle",
        "datasetName": "",
        "datasetLimit": None,
        "bundleName": "manual_bundle",
        "keepWorktree": False,
        "startedAt": "2026-05-18T12:00:00Z",
    }
    state = supervised_control_service._initial_run_state(context)
    state["status"] = "running"
    state["currentPhase"] = "running"
    state["runtimeStatus"] = "running"
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES[context["runId"]] = state
        supervised_control_service._RUN_CONTROLLERS[context["runId"]] = supervised_control_service._SupervisedRunController()
        supervised_control_service._ACTIVE_RUN_ID = context["runId"]
    supervised_control_service.persist_manager_run_snapshot("supervised", state, active_run_id=context["runId"])

    response = client.delete(f"/api/evolution/runs/{context['runId']}")

    assert response.status_code == 409
    assert "Terminate" in response.json()["detail"] or "终止" in response.json()["detail"]

    _reset_supervised_live_state()


def test_supervised_run_action_route_executes_and_respects_active_lock(tmp_path, monkeypatch):
    pending_result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=tmp_path,
        adapter=RunnerFakeAdapter(),
        episode_id="web_action_episode",
    )
    _write_supervised_decision_record(
        tmp_path,
        "web_action_run",
        {
            "decision": "PROMOTE",
            "reason": "候选方案进入 proposal 流程。",
            "gates": [
                {
                    "name": "gym_promotion",
                    "status": "pass",
                    "reason": "proposal created",
                    "metrics": {
                        "promotion_proposal_path": pending_result.promotion_proposal_path,
                        "decision_path": pending_result.decision_path,
                    },
                }
            ],
        },
    )

    _reset_supervised_live_state()
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)

    apply_response = client.post(
        "/api/evolution/runs/web_action_run/actions",
        json={"action": "apply"},
    )

    assert apply_response.status_code == 200
    payload = apply_response.json()
    assert payload["action"] == "apply"
    assert payload["run"]["proposalStatus"] == "applied"
    assert payload["lifecycle"]["status"] == "applied"

    bundle_path = tmp_path / "workspace" / "evaluation" / "bundles" / "manual_bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps({"bundle_name": "manual_bundle", "cases": [{"case_id": "case_1"}]}), encoding="utf-8")
    monkeypatch.setattr(
        supervised_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )
    start_response = client.post(
        "/api/evolution/runs",
        json={
            "sourceKind": "bundle",
            "bundleName": "manual_bundle",
            "keepWorktree": False,
        },
    )
    blocked_response = client.post(
        "/api/evolution/runs/web_action_run/actions",
        json={"action": "activate"},
    )

    assert start_response.status_code == 202
    assert blocked_response.status_code == 409

    _reset_supervised_live_state()


def test_evolution_auto_review_mode_blocks_manual_proposal_governance(tmp_path, monkeypatch):
    seeded = _seed_supervised_proposal_record(tmp_path, "auto_mode_proposal", status="proposed")
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_control_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(evolution_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(supervised_control_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(
        evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/supervised-evolution",
            "intakeMode": "auto",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    _reset_supervised_live_state()

    detail_response = client.get("/api/evolution/proposals/auto_mode_proposal")
    action_response = client.post(
        "/api/evolution/runs/auto_mode_proposal/actions",
        json={"action": "apply"},
    )
    edit_response = client.patch(
        "/api/evolution/proposals/auto_mode_proposal",
        json={"summary": "manual edit should be blocked in auto mode"},
    )
    delete_response = client.delete("/api/evolution/proposals/auto_mode_proposal")
    bulk_delete_response = client.post(
        "/api/evolution/proposals/delete",
        json={"sessionIds": ["auto_mode_proposal"]},
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["availableActions"] == []
    assert detail["canDelete"] is False
    assert "自动审查" in detail["deleteBlockReason"]
    assert detail["canEdit"] is False
    assert "自动审查" in detail["editBlockReason"]
    assert detail["actionStates"]["apply"]["enabled"] is False
    assert detail["actionStates"]["activate"]["enabled"] is False
    assert detail["actionStates"]["rollback"]["enabled"] is False
    assert detail["actionStates"]["delete"]["enabled"] is False
    assert "自动审查" in detail["actionStates"]["apply"]["reason"]
    current_state_text = "\n".join(detail["review"]["currentState"])
    assert "自动审查" in current_state_text
    assert "当前可执行动作" not in current_state_text
    assert "Available actions now" not in current_state_text

    assert action_response.status_code == 409
    assert "自动审查" in action_response.json()["detail"]
    assert edit_response.status_code == 409
    assert "自动审查" in edit_response.json()["detail"]
    assert delete_response.status_code == 409
    assert "自动审查" in delete_response.json()["detail"]

    assert bulk_delete_response.status_code == 200
    bulk_payload = bulk_delete_response.json()
    assert bulk_payload["deletedCount"] == 0
    assert bulk_payload["skippedCount"] == 1
    assert bulk_payload["errorCount"] == 0
    assert bulk_payload["results"][0]["sessionId"] == "auto_mode_proposal"
    assert bulk_payload["results"][0]["status"] == "skipped"
    assert "自动审查" in bulk_payload["results"][0]["summary"]
    assert json.loads(seeded["decision_path"].read_text(encoding="utf-8")).get("hidden_from_workbench") is not True
    assert json.loads(seeded["proposal_path"].read_text(encoding="utf-8")).get("hidden_from_workbench") is not True


def test_evolution_proposal_detail_route_exposes_review_first_payload(tmp_path, monkeypatch):
    seeded = _seed_supervised_proposal_record(tmp_path, "proposal_detail_run", status="proposed")
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/evolution/proposals/proposal_detail_run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sessionId"] == "proposal_detail_run"
    assert payload["proposalStatus"] == "proposed"
    assert payload["canDelete"] is True
    assert payload["review"]["headline"]
    assert payload["review"]["changeSummary"]
    assert payload["review"]["whatChanged"]
    assert payload["review"]["whyCreated"]
    assert payload["proposal"]["proposalId"]
    assert payload["proposal"]["improvementType"]
    assert payload["proposal"]["expectedEffect"]
    assert payload["canEdit"] is True
    assert payload["editBlockReason"] == ""
    _assert_seeded_case_diagnostic(payload["supervised"]["caseDiagnostics"][0])
    assert payload["paths"]["gymProposalPath"] == str(seeded["proposal_path"])
    assert payload["rawProposal"]["status"] == "proposed"
    assert payload["rawGymDecision"]["candidate_improvement"]["improvement_id"]


def test_evolution_update_proposal_persists_manual_draft_edits(tmp_path, monkeypatch):
    seeded = _seed_supervised_proposal_record(tmp_path, "proposal_edit_run", status="proposed")
    events: list[dict] = []

    def fake_record_runtime_scene_event(component, phase, event_code, **kwargs):
        events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **kwargs,
            }
        )

    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event", fake_record_runtime_scene_event)

    response = client.patch(
        "/api/evolution/proposals/proposal_edit_run",
        json={
            "improvementType": "manual prompt patch",
            "expectedEffect": "Make the candidate instruction easier to audit.",
            "summary": "Manual edit from proposal library.",
            "candidatePrompt": "candidate prompt edited by user",
            "baselinePrompt": "baseline prompt retained for comparison",
            "editNote": "tighten candidate wording",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["updated"] is True
    assert set(payload["changedFields"]) == {
        "improvement_type",
        "expected_effect",
        "summary",
        "candidate_prompt",
        "baseline_prompt",
    }
    assert payload["proposal"]["proposal"]["improvementType"] == "manual prompt patch"
    assert payload["proposal"]["proposal"]["expectedEffect"] == "Make the candidate instruction easier to audit."
    assert payload["proposal"]["proposal"]["summary"] == "Manual edit from proposal library."
    assert payload["proposal"]["proposal"]["candidatePrompt"] == "candidate prompt edited by user"
    assert payload["proposal"]["canEdit"] is True

    proposal_payload = json.loads(seeded["proposal_path"].read_text(encoding="utf-8"))
    assert proposal_payload["manual_overrides"]["improvement_type"] == "manual prompt patch"
    assert proposal_payload["manual_overrides"]["candidate_prompt"] == "candidate prompt edited by user"
    assert proposal_payload["manual_edit_history"][-1]["edit_note"] == "tighten candidate wording"
    assert proposal_payload["edited_by"] == "workbench"
    assert any(event["eventCode"] == "evolution.proposal_edit.saved" for event in events)

    partial_response = client.patch(
        "/api/evolution/proposals/proposal_edit_run",
        json={"summary": "Summary-only follow-up edit."},
    )

    assert partial_response.status_code == 200
    partial_payload = partial_response.json()
    assert partial_payload["changedFields"] == ["summary"]
    proposal_payload = json.loads(seeded["proposal_path"].read_text(encoding="utf-8"))
    assert proposal_payload["manual_overrides"]["summary"] == "Summary-only follow-up edit."
    assert proposal_payload["manual_overrides"]["candidate_prompt"] == "candidate prompt edited by user"
    assert proposal_payload["manual_overrides"]["baseline_prompt"] == "baseline prompt retained for comparison"


@pytest.mark.parametrize("status", ["applied", "missing"])
def test_evolution_update_proposal_blocks_non_draft_states(tmp_path, monkeypatch, status):
    seeded = _seed_supervised_proposal_record(tmp_path, f"proposal_edit_blocked_{status}", status=status)
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.patch(
        f"/api/evolution/proposals/proposal_edit_blocked_{status}",
        json={"summary": "should not be saved"},
    )
    detail_response = client.get(f"/api/evolution/proposals/proposal_edit_blocked_{status}")

    assert response.status_code == 409
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["canEdit"] is False
    assert detail["editBlockReason"]
    decision_payload = json.loads(seeded["decision_path"].read_text(encoding="utf-8"))
    assert "manual_overrides" not in decision_payload
    if seeded["proposal_path"].exists():
        proposal_payload = json.loads(seeded["proposal_path"].read_text(encoding="utf-8"))
        assert "manual_overrides" not in proposal_payload


def test_evolution_routes_expose_supervised_policy_observing_proposal(tmp_path, monkeypatch):
    decision_path = _write_supervised_decision_record(
        tmp_path,
        "observing_policy_run",
        {
            "decision": "HOLD",
            "reason": "candidate 持平，进入观察池。",
        },
    )
    proposal_path = tmp_path / "workspace" / "evolution" / "proposals" / "demo__case_1__observing.json"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(
        json.dumps(
            {
                "proposal_id": "demo:case_1:observing",
                "session_id": "observing_policy_run",
                "bundle_name": "demo_bundle",
                "case_id": "case_1",
                "target": {"kind": "bundle_prompt_case", "bundle_name": "demo_bundle", "case_id": "case_1"},
                "candidate_prompt": "candidate prompt",
                "baseline_prompt": "baseline prompt",
                "decision_signal": "stable_success",
                "status": "observing",
                "decision": "HOLD",
                "supervised_decision": "HOLD",
                "policy_action": "HOLD",
                "proposal_status": "observing",
                "runtime_effect": "not_applied",
                "agent_consumption": "advisory",
                "supervision_boundary": {
                    "scope": "supervised_frozen_evaluator",
                    "accepted_baseline_registry_scope": "supervised_policy_artifact",
                    "promote_updates_runtime": False,
                },
                "decision_path": str(decision_path),
                "observation_count": 1,
                "observation_budget": 3,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    payload["policy_action"] = {
        "lineage_index_path": str(tmp_path / "workspace" / "evolution" / "proposals" / "lineage_index.json"),
        "proposal_paths": [str(proposal_path)],
    }
    decision_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    runs_payload = client.get("/api/evolution/runs").json()
    library_payload = client.get("/api/evolution/library").json()
    detail_response = client.get("/api/evolution/proposals/observing_policy_run")

    assert runs_payload[0]["proposalStatus"] == "observing"
    assert runs_payload[0]["runtimeEffect"] == "not_applied"
    assert runs_payload[0]["agentConsumption"] == "advisory"
    assert runs_payload[0]["sourceProposalPath"] == str(proposal_path)
    assert any(item["sourceRun"] == "observing_policy_run" for item in library_payload["pending"])
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["proposalStatus"] == "observing"
    assert detail["runtimeEffect"] == "not_applied"
    assert detail["paths"]["gymProposalPath"] == str(proposal_path)
    assert detail["rawProposal"]["proposal_id"] == "demo:case_1:observing"
    assert detail["rawProposal"]["supervision_boundary"]["scope"] == "supervised_frozen_evaluator"
    assert detail["proposal"]["proposalId"] == "demo:case_1:observing"


def test_evolution_runs_route_exposes_run_delete_state(tmp_path, monkeypatch):
    _seed_supervised_proposal_record(tmp_path, "run_delete_missing", status="missing")
    _seed_supervised_proposal_record(tmp_path, "run_delete_active", status="active")
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/evolution/runs")

    assert response.status_code == 200
    payload = {item["id"]: item for item in response.json()}
    assert payload["run_delete_missing"]["canDelete"] is True
    assert payload["run_delete_missing"]["deleteBlockReason"] == ""
    assert payload["run_delete_active"]["canDelete"] is False
    assert payload["run_delete_active"]["deleteBlockReason"]


@pytest.mark.parametrize("status", ["proposed", "rolled_back", "missing", "superseded"])
def test_evolution_delete_proposal_allows_removable_states(tmp_path, monkeypatch, status):
    session_id = f"delete_{status}"
    seeded = _seed_supervised_proposal_record(tmp_path, session_id, status=status)
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.delete(f"/api/evolution/proposals/{session_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] is True
    assert seeded["decision_path"].exists()
    if status != "missing":
        assert seeded["proposal_path"].exists()
    decision_payload = json.loads(seeded["decision_path"].read_text(encoding="utf-8"))
    assert decision_payload["hidden_from_workbench"] is True
    assert decision_payload["deletion"]["preserved_for_audit"] is True
    if status != "missing":
        proposal_payload = json.loads(seeded["proposal_path"].read_text(encoding="utf-8"))
        assert proposal_payload["hidden_from_workbench"] is True

    runs_payload = client.get("/api/evolution/runs").json()
    library_payload = client.get("/api/evolution/library").json()
    visible_source_runs = {item["sourceRun"] for item in library_payload["items"] + library_payload["pending"]}

    assert all(run["id"] != session_id for run in runs_payload)
    assert session_id not in visible_source_runs


@pytest.mark.parametrize("status", ["applied", "active"])
def test_evolution_delete_proposal_blocks_live_states(tmp_path, monkeypatch, status):
    session_id = f"blocked_{status}"
    seeded = _seed_supervised_proposal_record(tmp_path, session_id, status=status)
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.delete(f"/api/evolution/proposals/{session_id}")
    detail_response = client.get(f"/api/evolution/proposals/{session_id}")

    assert response.status_code == 409
    assert detail_response.status_code == 200
    assert detail_response.json()["canDelete"] is False
    assert seeded["decision_path"].exists()
    assert seeded["proposal_path"].exists()


def test_evolution_bulk_delete_proposals_reports_mixed_results(tmp_path, monkeypatch):
    proposed = _seed_supervised_proposal_record(tmp_path, "bulk_delete_proposed", status="proposed")
    missing = _seed_supervised_proposal_record(tmp_path, "bulk_delete_missing", status="missing")
    active = _seed_supervised_proposal_record(tmp_path, "bulk_delete_active", status="active")
    monkeypatch.setattr(evolution_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/evolution/proposals/delete",
        json={
            "sessionIds": [
                "bulk_delete_proposed",
                "bulk_delete_missing",
                "bulk_delete_active",
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deletedCount"] == 2
    assert payload["skippedCount"] == 1
    assert payload["errorCount"] == 0
    result_status = {item["sessionId"]: item["status"] for item in payload["results"]}
    assert result_status["bulk_delete_proposed"] == "deleted"
    assert result_status["bulk_delete_missing"] == "deleted"
    assert result_status["bulk_delete_active"] == "skipped"
    assert proposed["decision_path"].exists()
    assert missing["decision_path"].exists()
    assert json.loads(proposed["decision_path"].read_text(encoding="utf-8"))["hidden_from_workbench"] is True
    assert json.loads(missing["decision_path"].read_text(encoding="utf-8"))["hidden_from_workbench"] is True
    assert active["decision_path"].exists()
    assert active["proposal_path"].exists()

    runs_payload = client.get("/api/evolution/runs").json()
    run_ids = {item["id"] for item in runs_payload}
    assert "bulk_delete_proposed" not in run_ids
    assert "bulk_delete_missing" not in run_ids
    assert "bulk_delete_active" in run_ids


def test_self_evolution_routes_expose_read_only_evidence(monkeypatch):
    monkeypatch.setattr(self_evolution_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(
        self_evolution_service,
        "build_self_evolution_snapshot",
        lambda project_root=None, transaction_limit=6, recent_limit=4: {
            "goal": "开始自主进化",
            "advisory": {
                "active_count": 1,
                "entries": [
                    {
                        "target_key": "target:a",
                        "target_label": "local_transaction_closing_v1",
                        "proposal_id": "proposal-1",
                        "episode_id": "episode-1",
                        "candidate_improvement_id": "cand-1",
                        "activated_at": "2026-05-18T12:00:00Z",
                        "runtime_effect": "not_applied",
                        "agent_consumption": "advisory",
                        "proposal_path": "workspace/gym/proposal-1.json",
                        "decision_path": "workspace/gym/decision-1.json",
                        "trace_index_path": "workspace/gym/trace-1.json",
                    }
                ],
            },
            "git_status": {
                "summary": json.dumps(
                    {
                        "dirty_summary": "有 unstaged 改动，共 1 个变化文件",
                        "modified_paths": ["core/evaluation/self_evolution_workbench.py"],
                        "modified_entities": [],
                        "last_validation_summary": "ruff lint 通过",
                        "recent_changes": [
                            {
                                "path": "core/evaluation/self_evolution_workbench.py",
                                "change_type": "modified",
                                "subject": "refine self evidence",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "lines": [
                    "{",
                    '  "dirty_summary": "有 unstaged 改动，共 1 个变化文件",',
                    '  "modified_paths": ["core/evaluation/self_evolution_workbench.py"],',
                ],
            },
            "recent_changes": [
                {
                    "path": "core/evaluation/self_evolution_workbench.py",
                    "change_type": "M",
                    "summary": "refine self evidence",
                }
            ],
            "fitness": {
                "transactions": {
                    "opened": 2,
                    "closed": 2,
                    "successful": 1,
                    "failed": 1,
                    "success_rate": 0.5,
                    "recent": [
                        {
                            "txn_id": "txn-1",
                            "status": "failed",
                            "validation_passed": 1,
                            "validation_failed": 1,
                            "mutations_recorded": 2,
                        }
                    ],
                },
                "validation": {"passed": 2, "failed": 1, "pass_rate": 0.66},
                "mutations": {"recorded": 3, "successful": 1, "failed": 1, "blocked": 1},
            },
            "worktree": {
                "available": True,
                "error": "",
                "snapshot_id": "snap-1",
                "created_at": "2026-05-18T12:00:00Z",
                "base_rev": "abcdef1234567890",
                "has_staged": False,
                "has_unstaged": True,
                "has_untracked": False,
                "is_dirty": True,
                "dirty_file_count": 1,
                "files": [
                    {
                        "path": "core/evaluation/self_evolution_workbench.py",
                        "status": "M",
                        "staged": False,
                        "unstaged": True,
                        "untracked": False,
                        "deleted": False,
                    }
                ],
            },
            "recent_transactions": [
                {
                    "txn_id": "txn-1",
                    "opened_at": "2026-05-18T11:55:00Z",
                    "closed_at": "2026-05-18T12:00:00Z",
                    "base_rev": "abcdef1234567890",
                    "base_rev_short": "abcdef123456",
                    "status": "failed",
                    "summary": "touch self loop",
                    "is_open": False,
                }
            ],
        },
    )
    monkeypatch.setattr(
        self_evolution_service,
        "list_recent_self_evolution_transaction_payloads",
        lambda project_root, limit=24: [
            {
                "txn_id": "txn-1",
                "opened_at": "2026-05-18T11:55:00Z",
                "closed_at": "2026-05-18T12:00:00Z",
                "base_rev": "abcdef1234567890",
                "base_rev_short": "abcdef123456",
                "status": "failed",
                "summary": "touch self loop",
                "is_open": False,
            }
        ],
    )
    monkeypatch.setattr(
        self_evolution_service,
        "load_self_evolution_audit_records",
        lambda project_root, limit=6: [
            {
                "timestamp": "2026-05-18T12:00:00Z",
                "event": "validation_completed",
                "txn_id": "txn-1",
                "status": "",
                "kind": "pytest",
                "message": "1 failed",
                "tool_name": "",
                "target_paths": ["tests/test_self_evolution_workbench.py"],
                "passed": False,
                "base_rev": "abcdef1234567890",
                "summary": "2026-05-18T12:00:00Z validation_completed txn-1 kind=pytest passed=False message=1 failed",
            }
        ],
    )

    overview_response = client.get("/api/evolution/self/overview")
    transactions_response = client.get("/api/evolution/self/transactions")
    audit_response = client.get("/api/evolution/self/audit")

    assert overview_response.status_code == 200
    assert transactions_response.status_code == 200
    assert audit_response.status_code == 200

    overview_payload = overview_response.json()
    assert overview_payload["enabled"] is True
    assert overview_payload["readiness"]["state"] == "caution"
    assert overview_payload["advisory"]["activeCount"] == 1
    assert overview_payload["metrics"]["dirtyFiles"] == 1
    assert overview_payload["gitStatus"]["summary"] == "有 unstaged 改动，共 1 个变化文件"
    assert overview_payload["gitStatus"]["lines"][1] == "最近验证: ruff lint 通过"
    assert overview_payload["worktree"]["snapshotId"] == "snap-1"
    assert overview_payload["sceneSemantics"]["sceneState"] == "caution"
    assert overview_payload["runSemantics"]["runStatus"] == "failed"
    assert overview_payload["actionStates"]["start"]["enabled"] is True
    assert overview_payload["recentTransactions"][0]["txnId"] == "txn-1"
    assert overview_payload["auditTail"][0]["event"] == "validation_completed"
    assert transactions_response.json()[0]["baseRevShort"] == "abcdef123456"
    assert audit_response.json()[0]["summary"].startswith("2026-05-18T12:00:00Z")


def test_start_self_evolution_run_from_web_exposes_active_snapshot(monkeypatch):
    _reset_self_evolution_live_state()
    _use_local_self_evolution_start(monkeypatch)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        self_evolution_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    response = client.post("/api/evolution/self/runs", json={"goal": "网页触发一轮自进化"})
    active_response = client.get("/api/evolution/self/active-run")

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["goal"] == "网页触发一轮自进化"
    assert payload["runId"].startswith("web-self-")
    assert payload["runSemantics"]["runStatus"] == "queued"
    assert payload["actionStates"]["pause"]["enabled"] is True

    assert active_response.status_code == 200
    active_payload = active_response.json()
    assert active_payload["runId"] == payload["runId"]
    assert active_payload["status"] == "queued"
    assert active_payload["actionStates"]["resume"]["enabled"] is False

    _reset_self_evolution_live_state()


def test_start_self_evolution_run_from_web_does_not_write_real_runtime_manager_store(monkeypatch):
    _reset_self_evolution_live_state()
    _use_local_self_evolution_start(monkeypatch)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        self_evolution_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    response = client.post("/api/evolution/self/runs", json={"goal": "隔离真实 runtime store"})
    assert response.status_code == 202
    run_id = response.json()["runId"]
    run_path, index_path = _real_runtime_manager_evolution_paths("self", run_id)
    original_index_text = _read_optional_text(index_path)

    try:
        active_response = client.get("/api/evolution/self/active-run")

        assert active_response.status_code == 200
        assert active_response.json()["runId"] == run_id
        assert not run_path.exists()
        current_index_text = _read_optional_text(index_path)
        assert current_index_text is None or run_id not in current_index_text
    finally:
        _restore_real_runtime_index_if_touched("self", run_id, original_index_text)
        _reset_self_evolution_live_state()


def test_start_self_evolution_run_allows_readonly_chat_but_blocks_write_chat(monkeypatch):
    _reset_self_evolution_live_state()
    _use_local_self_evolution_start(monkeypatch)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        self_evolution_control_service._RUN_EXECUTOR,
        "submit",
        lambda fn, *args, **kwargs: object(),
    )

    session_service._set_session_running("session-readonly", True, turn_id="chat-turn-readonly", leases=["readonly_chat"])
    try:
        response = client.post("/api/evolution/self/runs", json={"goal": "允许只读 chat 并行"})
    finally:
        session_service._set_session_running("session-readonly", False, turn_id="chat-turn-readonly")

    assert response.status_code == 202
    _reset_self_evolution_live_state()

    session_service._set_session_running("session-write", True, turn_id="chat-turn-write", leases=["worktree_write"])
    try:
        blocked = client.post("/api/evolution/self/runs", json={"goal": "阻止写入型 chat 并行"})
    finally:
        session_service._set_session_running("session-write", False, turn_id="chat-turn-write")

    assert blocked.status_code == 409
    assert "写入" in blocked.json()["detail"] or "write" in blocked.json()["detail"].lower()

    _reset_self_evolution_live_state()


def test_start_self_evolution_run_rejects_when_supervised_run_active(monkeypatch):
    _reset_self_evolution_live_state()
    _use_local_self_evolution_start(monkeypatch)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_active_supervised_run",
        lambda: {"runId": "supervised-1", "status": "running"},
    )

    response = client.post("/api/evolution/self/runs", json={"goal": "blocked"})

    assert response.status_code == 409
    assert "监督任务" in response.json()["detail"]

    _reset_self_evolution_live_state()


def test_start_self_evolution_run_rejects_when_supervised_run_paused(monkeypatch):
    _reset_self_evolution_live_state()
    _use_local_self_evolution_start(monkeypatch)
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "self_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )
    monkeypatch.setattr(self_evolution_control_service, "has_running_sessions", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "list_active_session_work_runs", lambda: [])
    monkeypatch.setattr(
        self_evolution_control_service,
        "get_active_supervised_run",
        lambda: {"runId": "supervised-paused", "status": "paused"},
    )

    response = client.post("/api/evolution/self/runs", json={"goal": "blocked"})

    assert response.status_code == 409
    assert "监督任务" in response.json()["detail"]

    _reset_self_evolution_live_state()


def test_self_evolution_routes_hide_data_when_mode_disabled(monkeypatch):
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "defaultMode": "supervised_evolution",
            "defaultRoute": "/evolution",
            "intakeMode": "manual_review",
            "modeAvailability": {
                "chat": True,
                "self_evolution": False,
                "supervised_evolution": True,
            },
            "domainAvailability": {
                "chat": True,
                "evolution": True,
                "config": True,
            },
        },
    )

    overview_response = client.get("/api/evolution/self/overview")
    transactions_response = client.get("/api/evolution/self/transactions")
    audit_response = client.get("/api/evolution/self/audit")

    assert overview_response.status_code == 200
    assert transactions_response.status_code == 200
    assert audit_response.status_code == 200
    assert overview_response.json()["enabled"] is False
    assert overview_response.json()["readiness"]["state"] == "disabled"
    assert transactions_response.json() == []
    assert audit_response.json() == []


def _seed_self_evolution_history(project_root: Path) -> Path:
    workspace_dir = project_root / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    db_path = workspace_dir / "agent_brain.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE EvolutionTransaction (
                txn_id TEXT PRIMARY KEY,
                opened_at TEXT,
                closed_at TEXT,
                base_rev TEXT,
                status TEXT,
                summary TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO EvolutionTransaction (txn_id, opened_at, closed_at, base_rev, status, summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("txn-delete-a", "2026-05-18T11:00:00Z", "2026-05-18T11:10:00Z", "aaaabbbbcccc", "done", "delete me"),
                ("txn-keep-b", "2026-05-18T12:00:00Z", "2026-05-18T12:10:00Z", "ddddeeeeffff", "failed", "keep me"),
                ("txn-open-c", "2026-05-18T13:00:00Z", None, "gggghhhhiiii", "running", "still open"),
            ],
        )
        conn.commit()

    audit_dir = workspace_dir / "evolution"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "audit.jsonl"
    audit_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-18T11:05:00Z",
                        "event": "validation_completed",
                        "txn_id": "txn-delete-a",
                        "summary": "delete audit",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-18T12:05:00Z",
                        "event": "validation_completed",
                        "txn_id": "txn-keep-b",
                        "summary": "keep audit",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-18T12:06:00Z",
                        "event": "system_note",
                        "txn_id": "",
                        "summary": "ungrouped audit",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return audit_path


def test_self_evolution_history_delete_removes_transaction_groups_and_linked_audit(tmp_path, monkeypatch):
    audit_path = _seed_self_evolution_history(tmp_path)
    monkeypatch.setattr(self_evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            }
        },
    )
    monkeypatch.setattr(self_evolution_service, "get_web_language", lambda: "zh")

    response = client.post(
        "/api/evolution/self/history/delete",
        json={"txnIds": ["txn-delete-a"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deletedGroupCount"] == 1
    assert payload["deletedAuditCount"] == 1
    assert payload["deletedTxnIds"] == ["txn-delete-a"]

    transactions_response = client.get("/api/evolution/self/transactions")
    remaining_txn_ids = {item["txnId"] for item in transactions_response.json()}
    assert "txn-delete-a" not in remaining_txn_ids
    assert "txn-keep-b" in remaining_txn_ids

    audit_response = client.get("/api/evolution/self/audit")
    audit_txn_ids = [item["txnId"] for item in audit_response.json()]
    assert "txn-delete-a" not in audit_txn_ids
    assert "txn-keep-b" in audit_txn_ids
    assert "" in audit_txn_ids
    assert "txn-delete-a" not in audit_path.read_text(encoding="utf-8")


def test_self_evolution_history_delete_blocks_open_transaction_groups(tmp_path, monkeypatch):
    _seed_self_evolution_history(tmp_path)
    monkeypatch.setattr(self_evolution_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        self_evolution_service,
        "get_workbench_contract",
        lambda: {
            "modeAvailability": {
                "chat": True,
                "self_evolution": True,
                "supervised_evolution": True,
            }
        },
    )
    monkeypatch.setattr(self_evolution_service, "get_web_language", lambda: "zh")

    response = client.post(
        "/api/evolution/self/history/delete",
        json={"txnIds": ["txn-open-c"]},
    )

    assert response.status_code == 422
    assert "当前现场" in response.json()["detail"]


def test_pet_summary_shape():
    response = client.get("/api/pet/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"]
    assert "statusLine" in payload


def test_reset_summary_shape():
    response = client.get("/api/reset/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "custom"
    assert payload["presets"] == []
    assert payload["items"]
    assert payload["categories"]
    item_ids = {item["id"] for item in payload["items"]}
    assert "chat_history" in item_ids
    assert "web_dist" in item_ids
    protected_paths = {path for group in payload["protected"] for path in group["paths"]}
    assert "workspace/agent_brain.db" not in protected_paths
    assert "workspace/memory/" not in protected_paths
    assert "workspace/prompts/" not in protected_paths
    assert "workspace/prompts/DYNAMIC.md" in protected_paths
    assert ".docs/project-memory/" in protected_paths


def _seed_supervised_proposal_record(project_root: Path, session_id: str, *, status: str) -> dict[str, Path]:
    result = run_gym_collection_episode(
        collection_id="foundation_local_stability",
        project_root=project_root,
        adapter=RunnerFakeAdapter(),
        episode_id=f"{session_id}_episode",
    )
    proposal_path = Path(result.promotion_proposal_path)

    activation = None
    if status in {"applied", "active", "rolled_back"}:
        apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=project_root)
    if status == "active":
        activation = activate_gym_promotion_proposal(result.promotion_proposal_path, project_root=project_root)
    elif status == "rolled_back":
        rollback_gym_promotion_proposal(
            result.promotion_proposal_path,
            project_root=project_root,
            reason="manual cleanup for test",
        )
    elif status == "superseded":
        apply_gym_promotion_proposal(result.promotion_proposal_path, project_root=project_root)
        activate_gym_promotion_proposal(result.promotion_proposal_path, project_root=project_root)
        replacement = run_gym_collection_episode(
            collection_id="foundation_local_stability",
            project_root=project_root,
            adapter=RunnerFakeAdapter(),
            episode_id=f"{session_id}_replacement",
        )
        apply_gym_promotion_proposal(replacement.promotion_proposal_path, project_root=project_root)
        activate_gym_promotion_proposal(replacement.promotion_proposal_path, project_root=project_root)
    elif status == "missing":
        proposal_path.unlink()

    advisory_context = None
    if activation is not None:
        advisory_context = {
            "active_count": 1,
            "entries": [
                {
                    "target_key": activation.target_key,
                    "target_label": "local_transaction_closing_v1",
                    "proposal_id": activation.proposal_id,
                    "runtime_effect": activation.runtime_effect,
                    "agent_consumption": activation.agent_consumption,
                }
            ],
        }

    decision_path = _write_supervised_decision_record(
        project_root,
        session_id,
        {
            "decision": "PROMOTE",
            "reason": f"{status} proposal for cleanup review.",
            "gates": [
                {
                    "name": "gym_promotion",
                    "status": "pass",
                    "reason": f"proposal {status}",
                    "metrics": {
                        "promotion_proposal_path": str(proposal_path),
                        "decision_path": result.decision_path,
                    },
                }
            ],
            "advisory_context": advisory_context,
        },
    )
    return {
        "decision_path": decision_path,
        "proposal_path": proposal_path,
    }


def _write_workbench_state(project_root: Path, payload: dict) -> None:
    state_path = project_root / "workspace" / "supervised_evolution" / "workbench_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_supervised_decision_record(project_root: Path, session_id: str, overrides: dict) -> Path:
    decisions_dir = project_root / "workspace" / "supervised_evolution" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    path = decisions_dir / f"{session_id}.json"
    payload = {
        "session_id": session_id,
        "bundle_name": "demo_bundle",
        "decision": "HOLD",
        "reason": "baseline 与 candidate 持平",
        "ended_at": "2026-05-18T12:00:00Z",
        "baseline_success_rate": 1.0,
        "candidate_success_rate": 1.0,
        "score_delta": 0.0,
        "baseline_summary": {"validation_failed": 0, "total_guarded_tools": 2, "avg_wall_clock_seconds": 1.0},
        "candidate_summary": {"validation_failed": 0, "total_guarded_tools": 2, "avg_wall_clock_seconds": 2.0},
        "case_summaries": [
            {
                "case_id": "case_1",
                "baseline_status": "success",
                "candidate_status": "success",
                "decision_signal": "stable_success",
                "difference_summary": "candidate 与 baseline 同为 success，validation 持平，runtime +1.0s。",
                "difference_metrics": {"wall_clock_seconds_delta": 1.0},
                "difference_reasons": ["same_status"],
                "score_breakdown": {
                    "baseline": {"overall_score": 1.0, "final_state_score": 1.0},
                    "candidate": {"overall_score": 0.95, "final_state_score": 1.0},
                    "delta": {"overall_score": -0.05},
                },
                "failure_taxonomy": ["same_status"],
                "evidence_paths": {
                    "baseline_report_path": "workspace/supervised_evolution/sessions/demo/baseline.json",
                    "candidate_report_path": "workspace/supervised_evolution/sessions/demo/candidate.json",
                },
            }
        ],
        "gates": [],
        "decision_path": str(path),
        "policy_action": {"lineage_index_path": str(project_root / "workspace" / "lineage.json")},
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _assert_seeded_case_diagnostic(diagnostic: dict) -> None:
    assert diagnostic == {
        "caseId": "case_1",
        "caseType": "static",
        "baselineStatus": "success",
        "candidateStatus": "success",
        "decisionSignal": "stable_success",
        "summary": "candidate 与 baseline 同为 success，validation 持平，runtime +1.0s。",
        "metrics": {"wall_clock_seconds_delta": 1.0},
        "reasons": ["same_status"],
        "scoreBreakdown": {
            "baseline": {"overall_score": 1.0, "final_state_score": 1.0},
            "candidate": {"overall_score": 0.95, "final_state_score": 1.0},
            "delta": {"overall_score": -0.05},
        },
        "failureTaxonomy": ["same_status"],
        "evidencePaths": {
            "baseline_report_path": "workspace/supervised_evolution/sessions/demo/baseline.json",
            "candidate_report_path": "workspace/supervised_evolution/sessions/demo/candidate.json",
        },
    }


def _reset_supervised_live_state() -> None:
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()


def _reset_self_evolution_live_state() -> None:
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None


def _use_local_self_evolution_start(monkeypatch) -> None:
    monkeypatch.setattr(self_evolution_control_service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "get_active_supervised_worktree_run", lambda: None)
    monkeypatch.setattr(
        self_evolution_control_service,
        "_capture_preflight_state",
        lambda run_id: {
            "runDir": "",
            "backupDir": "",
            "manifestPath": "",
            "baseRev": "",
            "dirtyEntries": {},
        },
    )
    monkeypatch.setattr(
        self_evolution_control_service,
        "self_evolution_agent_bindings",
        lambda: {
            role: {
                "agentId": f"test-self-{role}",
                "displayName": f"Test self {role}",
                "profileId": "primary",
                "promptTemplateId": f"prompt-self-{role}",
                "directSessionId": f"session-self-{role}",
                "workspacePath": f"workspace/agents/test-self-{role}",
                "role": role,
                "roleLabel": role,
            }
            for role in ("executor", "reviewer", "summarizer")
        },
    )
