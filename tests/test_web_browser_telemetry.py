import json

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import runtime_scene_service


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _activate_runtime_scene(tmp_path, monkeypatch, scene_id: str):
    scene_dir = tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}"
    (scene_dir / "events").mkdir(parents=True, exist_ok=True)
    (scene_dir / "raw").mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime_scene_id": scene_id,
                "title": f"Managed workbench run {scene_id}",
                "started_at": "2026-05-18T12:00:00Z",
                "ended_at": "",
                "status": "running",
                "trigger": "start",
                "session_mode": "managed",
                "project_root": str(tmp_path),
                "browser": {"managed": True, "status": "running"},
                "package": {
                    "schema_version": 2,
                    "timeline_path": "timeline.jsonl",
                    "lifecycle_path": "lifecycle.jsonl",
                    "raw_dir": "raw",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (scene_dir / "timeline.jsonl").write_text("", encoding="utf-8")
    (scene_dir / "lifecycle.jsonl").write_text("", encoding="utf-8")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps({"runtimeSceneId": scene_id, "runtimeSceneDir": str(scene_dir)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    return scene_dir


def _post_browser_telemetry(payload: dict):
    return client.post("/api/runtime/browser-telemetry", json=payload)


def test_runtime_browser_telemetry_records_into_active_scene(tmp_path, monkeypatch):
    scene_dir = _activate_runtime_scene(tmp_path, monkeypatch, "scene-live")

    response = _post_browser_telemetry(
        {
            "phase": "navigation",
            "eventCode": "browser.route.changed",
            "message": "React route changed to /chat",
            "level": "info",
            "fields": {
                "pathname": "/chat",
                "href": "http://127.0.0.1:8000/chat",
                "title": "Chat",
                "browserRole": "workbench",
                "activeNavHref": "/self-evolution",
                "heading": "Self evolution",
            },
        }
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
    assert manifest["browser"]["browser_role"] == "workbench"
    assert manifest["workbenchBrowser"]["current_pathname"] == "/chat"
    assert manifest["workbenchBrowser"]["browser_role"] == "workbench"


def test_runtime_browser_telemetry_keeps_launcher_and_workbench_manifest_slots_separate(tmp_path, monkeypatch):
    scene_dir = _activate_runtime_scene(tmp_path, monkeypatch, "scene-dual-browser")

    launcher_response = _post_browser_telemetry(
        {
            "phase": "page",
            "eventCode": "browser.page.snapshot",
            "message": "Launcher snapshot",
            "level": "info",
            "fields": {
                "pathname": "/launcher",
                "href": "http://127.0.0.1:8000/launcher",
                "title": "Launcher",
                "browserRole": "launcher_control_surface",
                "telemetrySurface": "managed_launcher",
                "pageInstanceId": "page-launcher",
            },
        }
    )
    workbench_response = _post_browser_telemetry(
        {
            "phase": "navigation",
            "eventCode": "browser.route.changed",
            "message": "Workbench route changed",
            "level": "info",
            "fields": {
                "pathname": "/chat",
                "href": "http://127.0.0.1:8000/chat",
                "title": "Vibelution 工作台",
                "browserRole": "workbench",
                "telemetrySurface": "managed_workbench",
                "pageInstanceId": "page-workbench",
            },
        }
    )

    assert launcher_response.status_code == 202
    assert workbench_response.status_code == 202
    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["launcherBrowser"]["current_pathname"] == "/launcher"
    assert manifest["launcherBrowser"]["browser_role"] == "launcher_control_surface"
    assert manifest["launcherBrowser"]["telemetry_surface"] == "managed_launcher"
    assert manifest["launcherBrowser"]["page_instance_id"] == "page-launcher"
    assert manifest["workbenchBrowser"]["current_pathname"] == "/chat"
    assert manifest["workbenchBrowser"]["browser_role"] == "workbench"
    assert manifest["workbenchBrowser"]["telemetry_surface"] == "managed_workbench"
    assert manifest["workbenchBrowser"]["page_instance_id"] == "page-workbench"
    assert manifest["browser"]["current_pathname"] == "/chat"


def test_runtime_browser_memory_telemetry_updates_manifest_summary(tmp_path, monkeypatch):
    scene_dir = _activate_runtime_scene(tmp_path, monkeypatch, "scene-memory")

    response = _post_browser_telemetry(
        {
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
        }
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
    timeline_events = [
        json.loads(line)
        for line in (scene_dir / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "browser.memory.sampled" not in {event["event_code"] for event in timeline_events}


def test_runtime_browser_memory_telemetry_suppresses_repetitive_component_events(tmp_path, monkeypatch):
    scene_dir = _activate_runtime_scene(tmp_path, monkeypatch, "scene-memory-suppressed")

    base_payload = {
        "phase": "memory",
        "eventCode": "browser.memory.sampled",
        "message": "Browser memory sampled: periodic",
        "level": "info",
        "fields": {
            "pathname": "/config",
            "reason": "periodic",
            "available": True,
            "usedJSHeapMB": 512.5,
            "totalJSHeapMB": 640.0,
            "jsHeapLimitMB": 4096.0,
            "queryCount": 17,
        },
    }

    assert _post_browser_telemetry(base_payload).json()["indexed"] is True
    repeated_payload = {
        **base_payload,
        "fields": {
            **base_payload["fields"],
            "usedJSHeapMB": 520.0,
            "queryCount": 19,
        },
    }
    assert _post_browser_telemetry(repeated_payload).json()["indexed"] is False

    telemetry_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "browser_page.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["event_code"] for event in telemetry_events] == ["browser.memory.sampled"]
    raw_lines = (scene_dir / "raw" / "browser.telemetry.log").read_text(encoding="utf-8").splitlines()
    assert sum("browser.memory.sampled" in line for line in raw_lines) == 2
    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["browser"]["last_memory_query_count"] == 19
    assert manifest["browser"]["memory_sample_count"] == 2
    assert manifest["browser"]["memory_sample_suppressed_count"] == 1


def test_runtime_browser_benign_resize_observer_error_stays_out_of_timeline(tmp_path, monkeypatch):
    scene_dir = _activate_runtime_scene(tmp_path, monkeypatch, "scene-resize-observer-noise")

    response = _post_browser_telemetry(
        {
            "phase": "error",
            "eventCode": "browser.page.error",
            "message": "ResizeObserver loop completed with undelivered notifications.",
            "level": "error",
            "fields": {
                "pathname": "/chat",
                "filename": "http://127.0.0.1:8000/chat",
                "stack": "null",
            },
        }
    )

    assert response.status_code == 202
    telemetry_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "browser_page.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert telemetry_events[-1]["event_code"] == "browser.page.error"
    timeline_events = [
        json.loads(line)
        for line in (scene_dir / "timeline.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "browser.page.error" not in {event["event_code"] for event in timeline_events}


def test_runtime_browser_telemetry_from_vite_dev_stays_out_of_index(tmp_path, monkeypatch):
    scene_dir = _activate_runtime_scene(tmp_path, monkeypatch, "scene-dev-telemetry")

    response = _post_browser_telemetry(
        {
            "phase": "memory",
            "eventCode": "browser.memory.sampled",
            "message": "Browser memory sampled: periodic",
            "level": "error",
            "fields": {
                "href": "http://127.0.0.1:5173/chat",
                "port": "5173",
                "telemetrySurface": "vite_dev",
                "browserRole": "workbench",
                "pathname": "/chat",
                "usedJSHeapMB": 166.2,
                "queryCount": 17,
            },
        }
    )

    assert response.status_code == 202
    assert response.json()["indexed"] is False
    raw = (scene_dir / "raw" / "browser.telemetry.log").read_text(encoding="utf-8")
    assert "browser.memory.sampled" in raw
    assert not (scene_dir / "events" / "browser_page.jsonl").exists()
    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["browser"]["last_ignored_telemetry_reason"] == "vite_dev_surface"
    assert manifest["browser"]["last_ignored_telemetry_surface"] == "vite_dev"
    assert manifest["workbenchBrowser"]["last_ignored_telemetry_reason"] == "vite_dev_surface"
    assert "current_pathname" not in manifest["browser"]
    assert "last_memory_used_js_heap_mb" not in manifest["browser"]


def test_runtime_browser_stream_lifecycle_telemetry_updates_manifest(tmp_path, monkeypatch):
    scene_dir = _activate_runtime_scene(tmp_path, monkeypatch, "scene-stream")

    response = _post_browser_telemetry(
        {
            "phase": "session_stream",
            "eventCode": "browser.session_stream.closed",
            "message": "Session detail stream closed.",
            "level": "info",
            "fields": {
                "sessionId": "session-1",
                "readyState": 1,
            },
        }
    )

    assert response.status_code == 202
    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["browser"]["last_session_stream_event_code"] == "browser.session_stream.closed"
    assert manifest["browser"]["last_session_stream_session_id"] == "session-1"


def test_runtime_browser_visibility_noise_stays_in_raw_log(tmp_path, monkeypatch):
    scene_dir = _activate_runtime_scene(tmp_path, monkeypatch, "scene-browser-noise")

    def post_visibility(value: str):
        return _post_browser_telemetry(
            {
                "phase": "lifecycle",
                "eventCode": "browser.visibility.changed",
                "message": f"Visibility changed to {value}",
                "level": "info",
                "fields": {
                    "pathname": "/supervised-evolution/runs",
                    "visibilityState": value,
                },
            }
        )

    assert post_visibility("visible").status_code == 202
    assert post_visibility("hidden").status_code == 202
    route_response = _post_browser_telemetry(
        {
            "phase": "navigation",
            "eventCode": "browser.route.changed",
            "message": "React route changed to /chat",
            "level": "info",
            "fields": {
                "pathname": "/chat",
                "visibilityState": "hidden",
            },
        }
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
