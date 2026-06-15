import copy
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from config.public_config import load_public_config
from core.launcher import service as standalone_launcher_service
from core.runtime_manager.work_run_store import WorkRunStore
from core.ui.chat_state import save_chat_state
from core.web import app as web_app
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    agent_directory_service,
    agent_mode_binding_service,
    chat_room_service,
    log_service,
    runtime_scene_service,
    runtime_service,
    self_evolution_control_service,
    self_evolution_service,
    session_service,
    supervised_control_service,
)
from tests.helpers.web_runtime_scene import _runtime_scene_local_index_parts, _seed_runtime_scene_bundle

pytestmark = pytest.mark.serial


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.fixture(autouse=True)
def disable_runtime_manager_live_control(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervised_control_service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "_runtime_manager_live_control_enabled", lambda: False)


@pytest.fixture(autouse=True)
def isolate_evolution_live_state():
    self_evolution_service.invalidate_self_evolution_overview_cache()
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_SUBSCRIBERS_LOCK:
        self_evolution_control_service._RUN_SUBSCRIBERS.clear()
    yield
    self_evolution_service.invalidate_self_evolution_overview_cache()
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_SUBSCRIBERS_LOCK:
        self_evolution_control_service._RUN_SUBSCRIBERS.clear()


def _seed_chat_state(project_root, *, task_status="reading", active_task=None, conversations=None):
    seeded_conversations = conversations
    if seeded_conversations is None:
        seeded_conversations = [
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
        ]
    save_chat_state(
        project_root,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": seeded_conversations,
        },
    )
    session_service._invalidate_session_list_cache()


def _reset_self_evolution_live_state() -> None:
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None


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

def test_web_control_guard_rejects_untrusted_host_by_default():
    guarded_client = TestClient(create_app(), base_url="http://192.168.20.30:8000")

    response = guarded_client.get("/api/control-token")

    assert response.status_code == 403
    assert "host" in response.json()["detail"].lower()

def test_web_control_guard_allows_configured_remote_host(monkeypatch):
    monkeypatch.setenv("VIBELUTION_TRUSTED_WEB_HOSTS", "192.168.20.30")
    guarded_client = TestClient(create_app(), base_url="http://192.168.20.30:8000")

    response = guarded_client.get(
        "/api/control-token",
        headers={"Origin": "http://192.168.20.30:8000"},
    )

    assert response.status_code == 200
    assert response.json()["controlToken"]

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

def test_runtime_summary_uses_active_session_agent_dialogue_model(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    cfg = runtime_service.get_config().model_copy(deep=True)
    primary_profile = cfg.llm.get_profile(role="primary")
    provider_id = primary_profile.provider_id
    cfg.llm.model_library["agent-dialogue-runtime-summary-test"] = {
        "provider_id": provider_id,
        "model": "gpt-5.5",
        "label": "Runtime summary Agent dialogue test",
    }
    monkeypatch.setattr(runtime_service, "get_config", lambda: cfg)
    monkeypatch.setattr(session_service, "get_config", lambda: cfg)
    agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="真实会话",
        llm_bindings={"dialogue": {"modelId": "agent-dialogue-runtime-summary-test"}},
        prompt_template_id="prompt-chat-default",
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["model"] == "gpt-5.5"
    assert payload["modelId"] == "agent-dialogue-runtime-summary-test"
    assert payload["modelAgentId"] == agent["agentId"]
    assert payload["modelSource"] == "active_session_agent_dialogue_model"
    assert payload["profile"] == provider_id
    assert payload["profileSource"] == "active_session_agent_dialogue_provider"

def test_runtime_summary_uses_light_active_session_summary(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_summary",
        lambda: {
            "id": "session-light",
            "title": "Light session",
            "agentId": "",
            "currentPhase": "running",
            "taskSummary": "light task",
            "updatedAt": "2026-06-07T09:30:00+00:00",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_detail",
        lambda: (_ for _ in ()).throw(AssertionError("runtime summary must not hydrate full session detail")),
        raising=False,
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionTitle"] == "Light session"
    assert payload["taskSummary"] == "light task"
    assert payload["currentPhase"] == "running"

def test_runtime_summary_falls_back_when_agent_model_identity_fails(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    expected_profile = str(public_config["runtime"]["profile"])
    public_config["llm"]["model_library"]["public-fallback-model"] = {
        "provider_id": "primary",
        "model": "public-fallback-model",
        "label": "Public fallback model",
    }
    public_config["llm"]["profiles"]["primary"]["model_ref"] = "public-fallback-model"
    scene_events: list[tuple[str, str, str, dict]] = []

    monkeypatch.setattr(runtime_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_summary",
        lambda: {"agentId": "agent-model-broken", "currentPhase": "ready"},
    )
    monkeypatch.setattr(
        runtime_service,
        "_active_session_model_identity",
        lambda active_session: (_ for _ in ()).throw(NameError("missing model identity helper")),
    )
    monkeypatch.setattr(
        runtime_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: scene_events.append(
            (component, phase, event_code, kwargs)
        ),
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["model"] == "public-fallback-model"
    assert payload["profile"] == expected_profile
    assert payload["modelSource"] == "public_config_primary"
    assert payload["modelId"] == ""
    assert scene_events
    assert scene_events[-1][0:3] == (
        "runtime",
        "summary",
        "runtime.summary.model_identity_failed",
    )
    assert scene_events[-1][3]["outcome"] == "fallback"
    assert scene_events[-1][3]["level"] == "warning"
    assert scene_events[-1][3]["fields"]["exceptionType"] == "NameError"

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
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
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
                    "triggerSource": "manual",
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

    assert compression["source"] == "runtime_state"
    assert compression["scope"] == "runtime_prompt_estimate"
    assert compression["tokenBasis"] == "current_context_tokens"
    assert compression["limitBasis"] == "effective_token_limit"
    assert compression["currentTokens"] == 7000
    assert compression["effectiveTokenLimit"] == 12000
    assert compression["contextWindowLimit"] == 24000
    assert compression["usageRatio"] == pytest.approx(0.5833)
    assert compression["compressionCount"] == 2
    assert compression["lastCompression"]["level"] == "standard"
    assert compression["lastCompression"]["triggerSource"] == "manual"
    assert compression["lastCompression"]["summaryWritten"] is True
    assert compression["strategy"]["levels"][0]["thresholdTokens"] == 7200


def test_runtime_summary_prefers_current_phase_over_stale_task_progress(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_summary",
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
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
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


def test_runtime_summary_uses_light_runtime_manager_snapshot(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "load_runtime_manager_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 17,
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 3001,
                "browserWindowPid": 4002,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
            },
        },
    )
    monkeypatch.setattr(runtime_service, "current_runtime_manager_pid", lambda project_root: 9912)
    monkeypatch.setattr(
        runtime_service,
        "load_runtime_snapshot",
        lambda: (_ for _ in ()).throw(AssertionError("runtime summary must not perform full runtime snapshot observation")),
        raising=False,
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["runtimeManager"]["running"] is True
    assert payload["runtimeManager"]["managerPid"] == 9912
    assert payload["workbench"]["observedState"] == "open"
    assert payload["lifecycleProof"]["projectRootMatches"] is True


def test_runtime_summary_labels_launcher_control_surface_separately(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 19,
            "workbench": {
                "sessionRole": "launcher_control_surface",
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "backendPid": 3001,
                "backendAlive": True,
                "backendHealthy": True,
                "backendObserved": True,
                "browserWindowPid": 4002,
                "browserWindowAlive": True,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["workbench"]["sessionRole"] == "launcher_control_surface"
    assert payload["workbench"]["observedState"] == "closed"
    assert "Launcher 控制台正在运行" in payload["workbench"]["statusLine"]
    assert payload["lifecycleProof"]["overallState"] == "partial"


def test_runtime_summary_exposes_orphaned_browser_status(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
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


def test_runtime_summary_marks_missing_managed_window_as_partial(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
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
                "desiredState": "open",
                "observedState": "partial",
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
                "browserWindowPid": 4002,
                "browserWindowAlive": False,
                "browserManaged": True,
                "lifecycleConsistency": "browser_missing",
                "url": "http://127.0.0.1:8000",
                "lastReason": "start",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["workbench"]["observedState"] == "partial"
    assert payload["workbench"]["lifecycleConsistency"] == "browser_missing"
    assert payload["workbench"]["statusLine"] == "工作台窗口已关闭，后端仍在运行。"
    proof = payload["lifecycleProof"]
    assert proof["overallState"] == "partial"
    backend = next(component for component in proof["components"] if component["id"] == "backend")
    window = next(component for component in proof["components"] if component["id"] == "workbench_window")
    assert backend["ok"] is True
    assert window["state"] == "missing"


def test_runtime_lifecycle_proof_marks_ready_when_components_agree(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
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
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
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
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
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


def test_runtime_lifecycle_proof_ignores_finished_needs_continue_work_run(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(runtime_service, "list_active_session_work_runs", lambda: [])
    finished_run = {
        "runId": "turn-needs-continue",
        "runKind": "chat_turn",
        "sessionId": "session-a",
        "status": "needs_continue",
        "currentPhase": "needs_continue",
        "updatedAt": "2026-06-05T11:30:33Z",
        "finishedAt": "2026-06-05T11:30:33Z",
    }
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": finished_run,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
                "supervised_worktree_evolution_run": None,
            },
            "latest": {
                "chat_turn": finished_run,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
                "supervised_worktree_evolution_run": None,
            },
            "activeItems": {
                "chat_turn": [finished_run],
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
    assert proof["overallState"] == "closed"
    assert proof["activeWorkRuns"]["count"] == 0
    assert runtime_service._restart_guard_active_work_runs() == []


def test_runtime_lifecycle_proof_does_not_mark_closed_when_backend_port_is_still_owned(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
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
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
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
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
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
        "get_active_session_summary",
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
        "get_active_session_summary",
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
        "get_active_session_summary",
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
        "get_active_session_summary",
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
        "get_active_session_summary",
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
        "get_active_session_summary",
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
        "get_active_session_summary",
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
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
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
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_manager_snapshot", lambda: {})

    payload = runtime_service.get_runtime_summary()

    assert payload["mentalState"]["source"] == "disabled"
    assert "关闭" in payload["mentalState"]["summary"] or "disabled" in payload["mentalState"]["summary"].lower()


def test_runtime_summary_falls_back_to_mental_diagnosis_when_state_is_empty(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
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
    monkeypatch.setattr(runtime_service, "_work_run_summary", lambda: {"active": {}, "activeItems": {}})
    monkeypatch.setattr(runtime_service, "_work_run_summary", lambda: {"active": {}, "activeItems": {}})
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
        {"reason": "web_close_button", "source": "web_ui", "stopManager": False},
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
    monkeypatch.setattr(runtime_service, "_work_run_summary", lambda: {"active": {}, "activeItems": {}})
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

def test_launcher_status_exposes_project_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(standalone_launcher_service, "LAUNCHER_STATE_PATH", tmp_path / "missing-launcher-state.json")
    monkeypatch.setattr(
        standalone_launcher_service,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 2001,
            "stateVersion": 2,
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "url": "http://127.0.0.1:8000",
                "lastReason": "launcher_start_button",
                "lastSource": "launcher_api",
                "lastTransitionAt": "2026-06-02T12:00:00Z",
            },
        },
    )
    monkeypatch.setattr(standalone_launcher_service, "load_pid", lambda: 2001)
    monkeypatch.setattr(standalone_launcher_service, "_is_process_alive", lambda pid: int(pid) == 2001)
    monkeypatch.setattr(
        standalone_launcher_service,
        "observe_workbench",
        lambda: {
            "observedState": "open",
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

    response = client.get("/api/launcher/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["launcher"]["mode"] == "standalone_control_plane"
    assert payload["launcher"]["phase"] == "phase_2a"
    assert payload["launcher"]["controlPlane"]["adapter"] == "runtime_manager"
    assert payload["launcher"]["controlPlane"]["independent"] is True
    assert payload["projectBundle"]["schemaVersion"] == 1
    assert payload["projectBundle"]["mode"] == "bundled"
    assert payload["projectBundle"]["observedState"] == "open"
    assert payload["projectBundle"]["lastOperation"]["source"] == "launcher_api"
    assert payload["projectBundle"]["backend"]["pid"] == 3001
    assert payload["projectBundle"]["frontend"]["mode"] == "bundled_static_dist"
    assert payload["projectBundle"]["browser"]["windowPid"] == 4001
    assert [component["id"] for component in payload["projectBundle"]["components"]] == ["backend", "frontend", "browser"]
    assert payload["projectBundle"]["components"][0]["requiredForRunning"] is True

def test_launcher_start_queues_open_workbench_and_records_lifecycle(monkeypatch):
    calls: list[object] = []
    scene_events: list[tuple[str, dict]] = []

    monkeypatch.setattr(standalone_launcher_service, "append_runtime_manager_file_event", lambda event_code, payload, **kwargs: scene_events.append((event_code, payload)))
    monkeypatch.setattr(standalone_launcher_service, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        standalone_launcher_service,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by))
        or {"commandId": "cmd-launcher-start"},
    )

    response = client.post("/api/launcher/start")

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["commandId"] == "cmd-launcher-start"
    assert calls == [
        "ensure",
        (
            "open_workbench",
            {"reason": "launcher_start_button", "source": "launcher_api", "noBrowser": False},
            "launcher_api",
        ),
    ]
    event_codes = [item[0] for item in scene_events]
    assert "launcher.bundle.start.requested" in event_codes
    assert "launcher.bundle.start.accepted" in event_codes
    accepted_event = next(item for item in scene_events if item[0] == "launcher.bundle.start.accepted")
    assert accepted_event[1]["fields"]["commandId"] == "cmd-launcher-start"

def test_launcher_restart_blocks_active_work(monkeypatch):
    scene_events: list[tuple[str, dict]] = []
    active_work_runs = [{"kind": "chat_turn", "runId": "chat-turn-live", "status": "running"}]

    def block_restart():
        raise standalone_launcher_service.LauncherActiveWorkBlocked(
            "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。",
            active_work_runs,
        )

    monkeypatch.setattr(standalone_launcher_service, "append_runtime_manager_file_event", lambda event_code, payload, **kwargs: scene_events.append((event_code, payload)))
    monkeypatch.setattr(standalone_launcher_service, "request_launcher_restart", block_restart)

    response = client.post("/api/launcher/restart")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "active_work_restart_blocked"
    assert detail["message"] == "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。"
    assert detail["activeWorkRuns"][0]["runId"] == "chat-turn-live"
    event_codes = [item[0] for item in scene_events]
    assert "launcher.bundle.restart.accepted" not in event_codes

def test_launcher_stop_blocks_active_work(monkeypatch):
    active_work_runs = [{"kind": "chat_turn", "runId": "chat-turn-live", "status": "running"}]

    def block_stop():
        raise standalone_launcher_service.LauncherActiveWorkBlocked(
            "有进行中的任务，无法停止 Vibelution。请等待任务完成或先停止任务。",
            active_work_runs,
        )

    monkeypatch.setattr(standalone_launcher_service, "request_launcher_stop", block_stop)

    response = client.post("/api/launcher/stop")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "active_work_stop_blocked"
    assert detail["message"] == "有进行中的任务，无法停止 Vibelution。请等待任务完成或先停止任务。"
    assert detail["activeWorkRuns"][0]["runId"] == "chat-turn-live"

def test_launcher_stop_delegates_runtime_shutdown_and_normalizes_response(monkeypatch):
    monkeypatch.setattr(
        standalone_launcher_service,
        "request_launcher_stop",
        lambda: {
            "accepted": True,
            "mode": "runtime_manager",
            "launcherMode": "standalone_control_plane",
            "operation": "stop",
            "commandId": "cmd-launcher-stop",
            "message": "closing",
        },
    )

    response = client.post("/api/launcher/stop")

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["operation"] == "stop"
    assert payload["launcherMode"] == "standalone_control_plane"
    assert payload["mode"] == "runtime_manager"

def test_launcher_restart_delegates_runtime_restart_and_normalizes_response(monkeypatch):
    monkeypatch.setattr(
        standalone_launcher_service,
        "request_launcher_restart",
        lambda: {
            "accepted": True,
            "mode": "runtime_manager",
            "launcherMode": "standalone_control_plane",
            "operation": "restart",
            "commandId": "cmd-launcher-restart",
            "message": "restarting",
        },
    )

    response = client.post("/api/launcher/restart")

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["operation"] == "restart"
    assert payload["commandId"] == "cmd-launcher-restart"
    assert payload["launcherMode"] == "standalone_control_plane"

def test_runtime_restart_blocks_active_work(monkeypatch):
    calls: list[object] = []
    scene_events: list[tuple[str, str, str, dict]] = []

    def record_scene_event(component, phase, event_code, **kwargs):
        scene_events.append((component, phase, event_code, kwargs))
        return {"accepted": True}

    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {},
            "activeItems": {
                "chat_turn": [
                    {
                        "sessionId": "session-live",
                        "runId": "chat-turn-live",
                        "status": "running",
                    }
                ]
            },
        },
    )
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

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "active_work_restart_blocked"
    assert detail["message"] == "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。"
    assert detail["activeWorkRuns"] == [
        {
            "kind": "chat_turn",
            "runId": "chat-turn-live",
            "status": "running",
            "sessionId": "session-live",
        }
    ]
    assert calls == []
    event_codes = [item[2] for item in scene_events]
    assert "runtime.restart.requested" in event_codes
    assert "runtime.restart.blocked_active_work" in event_codes
    assert "runtime.restart.accepted" not in event_codes
    blocked_event = next(item for item in scene_events if item[2] == "runtime.restart.blocked_active_work")
    assert blocked_event[3]["outcome"] == "blocked"
    assert blocked_event[3]["fields"]["activeWorkCount"] == 1

def test_runtime_restart_blocks_confirmed_active_work_without_releasing_tasks(monkeypatch):
    calls: list[object] = []
    self_calls: list[str] = []
    supervised_calls: list[str] = []
    worktree_calls: list[str] = []
    stop_calls: list[str] = []

    def fail_stop(session_id):
        stop_calls.append(session_id)
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

    response = client.post("/api/runtime/restart?confirmedActiveWork=true")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "active_work_restart_blocked"
    assert detail["activeWorkRuns"][0]["runId"] == "chat-turn-live"
    assert stop_calls == []
    assert self_calls == []
    assert supervised_calls == []
    assert worktree_calls == []
    assert calls == []

def test_runtime_shutdown_blocks_active_chat_turn_before_manager_close(tmp_path, monkeypatch):
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

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "active_work_stop_blocked"
        assert detail["message"] == "有进行中的任务，无法停止 Vibelution。请等待任务完成或先停止任务。"
        assert detail["activeWorkRuns"][0]["runId"] == turn_control.turn_id
        assert calls == []
        active = session_service.load_chat_turn_work_run_summary()["active"]
        assert active["runId"] == turn_control.turn_id
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")

@pytest.mark.slow
def test_runtime_shutdown_blocks_active_chat_room_round_before_manager_close(tmp_path, monkeypatch):
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

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "active_work_stop_blocked"
        assert detail["message"] == "有进行中的任务，无法停止 Vibelution。请等待任务完成或先停止任务。"
        assert detail["activeWorkRuns"][0]["kind"] == "chat_room_round"
        assert detail["activeWorkRuns"][0]["runId"] == round_id
        final_detail = chat_room_service.get_chat_room_detail(room["roomId"])
        assert final_detail["status"] == "running"
        assert final_detail["activeRoundId"] == round_id
        assert final_detail["rounds"][-1]["status"] == "running"
        assert chat_room_service.load_chat_room_work_run_summary()["active"]["runId"] == round_id
        assert calls == []
    finally:
        release_room.set()
        room_executor.shutdown(wait=True, cancel_futures=True)

def test_runtime_shutdown_blocks_active_evolution_runs_before_manager_close(tmp_path, monkeypatch):
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
        "_work_run_summary",
        lambda: {
            "active": {
                "self_evolution_run": {"runId": "web-self-active", "status": "running"},
                "supervised_evolution_run": {"runId": "web-supervised-active", "status": "running"},
                "supervised_worktree_evolution_run": {"runId": "web-worktree-active", "status": "running"},
            },
            "activeItems": {},
        },
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

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "active_work_stop_blocked"
    assert detail["message"] == "有进行中的任务，无法停止 Vibelution。请等待任务完成或先停止任务。"
    assert {item["runId"] for item in detail["activeWorkRuns"]} == {
        "web-self-active",
        "web-supervised-active",
        "web-worktree-active",
    }
    assert self_calls == []
    assert supervised_calls == []
    assert worktree_calls == []
    assert calls == []

def test_runtime_shutdown_blocks_active_chat_turn_without_trying_stop(tmp_path, monkeypatch):
    script_path = tmp_path / "vibelution_launcher.ps1"
    script_path.write_text("Write-Host managed\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    calls: list[object] = []
    stop_calls: list[str] = []

    def fail_stop(session_id):
        stop_calls.append(session_id)
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

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "active_work_stop_blocked"
    assert detail["activeWorkRuns"][0]["sessionId"] == "session-live"
    assert detail["activeWorkRuns"][0]["runId"] == "chat-turn-live"
    assert stop_calls == []
    assert calls == []

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
    monkeypatch.setattr(runtime_service, "_work_run_summary", lambda: {"active": {}, "activeItems": {}})
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
    monkeypatch.setattr(runtime_service, "_work_run_summary", lambda: {"active": {}, "activeItems": {}})
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
    assert scene_a["eventCount"] >= 3
    assert scene_a["rawLogCount"] >= 5
    assert scene_a["eventLogCount"] == 3
    assert scene_a["warningCount"] == 1
    assert scene_a["errorCount"] == 1

    detail_response = client.get("/api/logs/runtime-scenes/scene-a")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["runtimeSceneId"] == "scene-a"
    assert detail["displayName"] == scene_a["displayName"]
    for key in [
        "schemaVersion",
        "packageId",
        "displayName",
        "indexKey",
        "startedAt",
        "startedDate",
        "startedTime",
        "durationSeconds",
    ]:
        assert detail["packageIndex"][key] == scene_a["packageIndex"][key]
    assert "diagnosis-active-issue" in detail["packageIndex"]["tags"]
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

def test_runtime_scene_event_keeps_safe_token_usage_counters(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-token-counters", status="running")
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-token-counters",
                "runtimeSceneDir": str(scene_dir),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    result = runtime_scene_service.record_runtime_scene_event(
        "llm",
        "stream",
        "llm.stream.succeeded",
        fields={
            "inputTokens": 100,
            "outputTokens": 20,
            "cachedInputTokens": 64,
            "accessToken": "secret-token",
        },
    )

    assert result["accepted"] is True
    llm_events = (scene_dir / "events" / "llm.jsonl").read_text(encoding="utf-8").splitlines()
    event = json.loads(llm_events[-1])
    assert event["fields"]["inputTokens"] == 100
    assert event["fields"]["outputTokens"] == 20
    assert event["fields"]["cachedInputTokens"] == 64
    assert event["fields"]["accessToken"] == runtime_scene_service.REDACTED_FIELD_VALUE

def test_runtime_scene_child_log_preserves_agent_llm_binding_shape(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-agent-binding", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-agent-binding",
                "runtimeSceneDir": str(scene_dir),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    result = runtime_scene_service.record_runtime_scene_event(
        "supervision",
        "progress",
        "supervised.role_finish",
        child_log_path="agent/supervised_runs/web-supervised-binding.jsonl",
        child_log_payload={
            "agentBinding": {
                "agentId": "agent-a",
                "llmBindings": {
                    "dialogue": {
                        "modelId": "model-a",
                    },
                },
            },
        },
    )

    assert result["accepted"] is True
    child_log = scene_dir / "agent" / "supervised_runs" / "web-supervised-binding.jsonl"
    child_event = json.loads(child_log.read_text(encoding="utf-8").splitlines()[-1])
    assert child_event["agentBinding"]["llmBindings"]["dialogue"]["modelId"] == "model-a"

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

def test_runtime_scene_event_helper_keeps_noisy_observations_out_of_timeline(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-event-noise", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-event-noise",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    runtime_scene_service.record_runtime_scene_event(
        "conversation",
        "session_list",
        "session.list.loaded",
        message="Session list loaded through read-only lightweight indexes.",
        fields={"sessionCount": 3, "readOnly": True},
    )
    runtime_scene_service.record_runtime_scene_event(
        "image2",
        "generate",
        "image2.generate.failed",
        message="image2.generate.failed",
        level="error",
        outcome="failed",
        fields={"errorType": "RuntimeError"},
    )

    conversation_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "conversation.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert conversation_events[-1]["event_code"] == "session.list.loaded"

    timeline_events = [
        json.loads(line)
        for line in (scene_dir / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "session.list.loaded" not in {event["event_code"] for event in timeline_events}
    assert "image2.generate.failed" in {event["event_code"] for event in timeline_events}

def test_session_list_loaded_event_marks_stale_matching_signature(monkeypatch):
    events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    session_service._record_session_list_loaded_event(
        session_count=3,
        conversation_count=4,
        agent_count=2,
        elapsed_ms=5,
        cache_hit=True,
        cache_age_ms=5000,
        cache_ttl_ms=4000,
        waited_for_inflight=False,
    )

    fields = events[-1][1]["fields"]
    assert fields["cacheExpired"] is True
    assert fields["servedStaleMatchingSignature"] is True

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

def test_work_run_store_clears_finished_needs_continue_active_index(tmp_path):
    store = WorkRunStore(root=tmp_path / ".runtime" / "runtime-manager" / "work_runs")

    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "turn-needs-continue",
            "runKind": "chat_turn",
            "status": "needs_continue",
            "currentPhase": "needs_continue",
            "updatedAt": "2026-06-05T11:30:33Z",
            "finishedAt": "2026-06-05T11:30:33Z",
        },
        active_run_id="turn-needs-continue",
    )

    assert store.load_active_snapshot("chat_turn") is None
    assert store.load_latest_snapshot("chat_turn")["runId"] == "turn-needs-continue"
    assert store.load_run_index("chat_turn")["activeRunId"] == ""

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

def test_supervised_failed_case_progress_is_evidence_not_lifecycle_error(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-supervised-failed-case", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-supervised-failed-case",
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
            "timestamp": "2026-06-01T12:17:19",
            "event": "role_finish",
            "title": "Case 完成",
            "summary": "case-1 candidate status=failed reason=事务探针未关账",
            "status": "failed",
            "caseId": "case-1",
            "caseIndex": 1,
            "caseTotal": 1,
            "role": "candidate",
            "scenario": "transaction",
            "mode": "multi_step_react",
            "bundleName": "terminal_bench_core_v1",
            "sessionId": "session-1",
            "reason": "事务探针未关账",
            "elapsedSeconds": 150.0,
            "resultStatus": "failed",
        },
    )

    event_rows = [
        json.loads(line)
        for line in (scene_dir / "events" / "supervised_run.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event = event_rows[-1]
    assert event["event_code"] == "supervised_run.progress.role_finish"
    assert event["level"] == "info"
    assert event["outcome"] == "failed"
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

def test_backend_api_runtime_event_records_request_source_summary(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-api-source", status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": "scene-api-source",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = client.get(
        "/api/source-probe-missing?tab=runs&secret=hidden&token=abc123",
        headers={
            "referer": "http://testserver/supervised-evolution?tab=runs&secret=hidden#detail",
            "origin": "http://testserver",
            "user-agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/125.0 Safari/537.36 Edg/125.0",
        },
    )

    assert response.status_code == 404
    backend_raw = (scene_dir / "raw" / "backend.api.log").read_text(encoding="utf-8")
    assert "/api/source-probe-missing" in backend_raw
    assert "/supervised-evolution" in backend_raw
    assert "tab=runs" not in backend_raw
    assert "secret=hidden" not in backend_raw
    assert "token=abc123" not in backend_raw
    assert "Mozilla/5.0" not in backend_raw
    assert "Chrome/125.0" not in backend_raw

    backend_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "backend.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    api_event = backend_events[-1]
    assert api_event["event_code"] == "backend.api.request"
    assert api_event["fields"]["path"] == "/api/source-probe-missing"
    assert api_event["fields"]["statusCode"] == 404
    assert api_event["fields"]["query"] == "params=3;length=35;keys=tab;sensitiveKeys=2"
    assert api_event["fields"]["queryParamCount"] == 3
    assert api_event["fields"]["queryKeys"] == ["tab"]
    assert api_event["fields"]["queryLength"] == 35
    assert api_event["fields"]["sensitiveQueryKeyCount"] == 2
    assert api_event["fields"]["refererPath"] == "/supervised-evolution"
    assert api_event["fields"]["requestOrigin"] == "http://testserver"
    assert api_event["fields"]["userAgentFamily"] == "edge"

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
