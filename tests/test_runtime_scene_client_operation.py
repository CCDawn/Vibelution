from __future__ import annotations

import json

from starlette.requests import Request

from tests.test_runtime_scene_projection_fastpath import _point_runtime_scene_at

from core.web.middleware.runtime_scene_api import (
    CLIENT_OPERATION_ID_HEADER,
    _client_operation_id,
    record_api_runtime_event,
)
from core.web.services import runtime_scene_service


def test_client_operation_id_header_is_truncated() -> None:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/sessions",
        "headers": [(CLIENT_OPERATION_ID_HEADER.lower().encode(), b"x" * 200)],
    }
    request = Request(scope)
    assert len(_client_operation_id(request)) == 120


def test_record_backend_api_event_persists_client_operation_id(
    tmp_path,
    monkeypatch,
) -> None:
    scene_dir = _point_runtime_scene_at(tmp_path, monkeypatch, scene_id="scene-client-op")

    runtime_scene_service.record_backend_api_event(
        {
            "method": "DELETE",
            "path": "/api/sessions/session-a",
            "path_template": "/api/sessions/{session_id}",
            "status_code": 200,
            "duration_ms": 12.5,
            "client_operation_id": "session_delete-123-1",
        }
    )

    backend_events = [
        json.loads(line)
        for line in (scene_dir / "events" / "backend.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert backend_events[-1]["fields"]["clientOperationId"] == "session_delete-123-1"


def test_record_api_runtime_event_forwards_client_operation_id(monkeypatch) -> None:
    captured: list[dict] = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_backend_api_event",
        lambda payload: captured.append(payload) or {"accepted": True},
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/sessions",
        "headers": [(CLIENT_OPERATION_ID_HEADER.lower().encode(), b"session_create-999-1")],
    }
    request = Request(scope)
    record_api_runtime_event(request, status_code=200, duration_ms=3.2)
    assert captured
    assert captured[0]["client_operation_id"] == "session_create-999-1"
