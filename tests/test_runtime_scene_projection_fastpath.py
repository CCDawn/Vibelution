from __future__ import annotations

import json

import pytest

from core.web.services import runtime_scene_service
from tests.helpers.web_runtime_scene import _seed_runtime_scene_bundle


@pytest.mark.parametrize(
    ("level", "reconciliation_closed", "expected"),
    [
        ("info", False, False),
        ("info", True, True),
        ("warning", False, True),
        ("error", False, True),
        ("critical", False, True),
        ("fatal", False, True),
    ],
)
def test_runtime_scene_event_projection_refresh_policy(
    level: str,
    reconciliation_closed: bool,
    expected: bool,
) -> None:
    assert (
        runtime_scene_service._runtime_scene_event_requires_full_projection_refresh(
            level=level,
            reconciliation_closed=reconciliation_closed,
        )
        is expected
    )


def _point_runtime_scene_at(tmp_path, monkeypatch, *, scene_id: str):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id=scene_id, status="running")
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps({"runtimeSceneId": scene_id, "runtimeSceneDir": str(scene_dir)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    return scene_dir


@pytest.mark.parametrize(
    ("status_code", "exception_type", "expected_level"),
    [
        (200, "", "info"),
        (404, "", "warning"),
        (500, "RuntimeError", "error"),
    ],
)
def test_backend_api_telemetry_never_rebuilds_full_projection_on_request_path(
    tmp_path,
    monkeypatch,
    status_code: int,
    exception_type: str,
    expected_level: str,
) -> None:
    scene_dir = _point_runtime_scene_at(tmp_path, monkeypatch, scene_id=f"scene-api-{status_code}")
    full_calls: list[tuple] = []
    lightweight_calls: list[tuple] = []
    monkeypatch.setattr(
        runtime_scene_service,
        "_update_runtime_scene_package_manifest",
        lambda scene, manifest: full_calls.append((scene, manifest)),
    )
    monkeypatch.setattr(
        runtime_scene_service,
        "_update_runtime_scene_package_manifest_lightweight",
        lambda scene, manifest: lightweight_calls.append((scene, manifest)),
    )

    result = runtime_scene_service.record_backend_api_event(
        {
            "method": "GET",
            "path": "/api/runtime/summary",
            "path_template": "/api/runtime/summary",
            "status_code": status_code,
            "duration_ms": 1250.5,
            "client": "127.0.0.1",
            "exception_type": exception_type,
            "exception_message": "bounded failure" if exception_type else "",
        }
    )

    assert result["projectionRefresh"] == "lightweight"
    assert len(lightweight_calls) == 1
    assert lightweight_calls[0][0] == scene_dir
    assert full_calls == []
    backend_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "backend.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert backend_events[-1]["level"] == expected_level
    assert backend_events[-1]["fields"]["statusCode"] == status_code


@pytest.mark.parametrize(
    ("status", "expected_level"),
    [
        ("running", "info"),
        ("failed", "error"),
    ],
)
def test_conversation_telemetry_never_rebuilds_full_projection_on_turn_path(
    tmp_path,
    monkeypatch,
    status: str,
    expected_level: str,
) -> None:
    scene_dir = _point_runtime_scene_at(tmp_path, monkeypatch, scene_id=f"scene-conversation-{status}")
    full_calls: list[tuple] = []
    lightweight_calls: list[tuple] = []
    monkeypatch.setattr(
        runtime_scene_service,
        "_update_runtime_scene_package_manifest",
        lambda scene, manifest: full_calls.append((scene, manifest)),
    )
    monkeypatch.setattr(
        runtime_scene_service,
        "_update_runtime_scene_package_manifest_lightweight",
        lambda scene, manifest: lightweight_calls.append((scene, manifest)),
    )

    result = runtime_scene_service.record_runtime_scene_conversation_event(
        "session-hotpath",
        "user",
        "redacted by the telemetry writer",
        message={
            "id": "message-hotpath",
            "role": "user",
            "metadata": {"turnId": "turn-hotpath"},
        },
        event="user_message",
        status=status,
    )

    assert result["projectionRefresh"] == "lightweight"
    assert len(lightweight_calls) == 1
    assert lightweight_calls[0][0] == scene_dir
    assert full_calls == []
    conversation_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "conversation.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert conversation_events[-1]["level"] == expected_level
    assert conversation_events[-1]["fields"]["contentRedacted"] is True
    assert conversation_events[-1]["fields"]["turnId"] == "turn-hotpath"
