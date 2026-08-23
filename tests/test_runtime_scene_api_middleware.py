from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from core.logging import debug as debug_logger
from core.logging.trace_context import (
    bind_trace_context,
    get_current_trace_context,
    new_trace_context,
)
from core.web.middleware.runtime_scene_api import (
    RuntimeSceneApiEventMiddleware,
    api_runtime_record_failure_count,
    record_api_runtime_event,
    reset_api_runtime_record_failure_count_for_tests,
)
from core.web.services.runtime_scene import record as runtime_scene_record


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/sessions",
            "headers": [],
        }
    )


def test_record_api_runtime_event_warns_when_scene_writer_fails(monkeypatch) -> None:
    reset_api_runtime_record_failure_count_for_tests()
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_backend_api_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("scene writer down")),
    )
    monkeypatch.setattr(
        debug_logger,
        "warning",
        lambda message, tag="": warnings.append((str(message), str(tag))),
    )

    record_api_runtime_event(_request(), status_code=500, duration_ms=12.0)

    assert api_runtime_record_failure_count() == 1
    assert warnings
    assert warnings[0][1] == "SCENE"
    assert "count=1" in warnings[0][0]
    assert "RuntimeError" in warnings[0][0]
    assert "scene writer down" not in warnings[0][0]


def test_record_api_runtime_event_rate_limits_repeat_failure_warnings(monkeypatch) -> None:
    reset_api_runtime_record_failure_count_for_tests()
    warnings: list[str] = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_backend_api_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("scene writer down")),
    )
    monkeypatch.setattr(
        debug_logger,
        "warning",
        lambda message, tag="": warnings.append(str(message)),
    )

    for _ in range(4):
        record_api_runtime_event(_request(), status_code=503, duration_ms=8.0)

    assert api_runtime_record_failure_count() == 4
    assert len(warnings) == 3


def test_api_middleware_propagates_trace_context_and_response_headers(monkeypatch) -> None:
    captured_events: list[dict] = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_backend_api_event",
        lambda payload: captured_events.append(dict(payload)),
    )
    app = FastAPI()
    app.add_middleware(RuntimeSceneApiEventMiddleware)

    @app.post("/api/trace-probe")
    def trace_probe() -> dict:
        context = get_current_trace_context()
        assert context is not None
        return context.to_fields()

    trace_id = "1" * 32
    upstream_span_id = "2" * 16
    response = TestClient(app).post(
        "/api/trace-probe",
        headers={
            "traceparent": f"00-{trace_id}-{upstream_span_id}-01",
            "X-Request-ID": "request-123",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["traceId"] == trace_id
    assert body["parentSpanId"] == upstream_span_id
    assert body["requestId"] == "request-123"
    assert response.headers["traceparent"] == f"00-{trace_id}-{body['spanId']}-01"
    assert response.headers["X-Request-ID"] == "request-123"
    assert captured_events[-1]["fields"] == body
    assert get_current_trace_context() is None


def test_runtime_scene_tool_arguments_are_recursively_redacted() -> None:
    secret = "nested-runtime-secret"

    normalized = runtime_scene_record._normalize_telemetry_fields(
        {
            "tool_args": {
                "target": "demo.py",
                "nested": {"auth": {"token": secret}},
            }
        }
    )

    serialized = json.dumps(normalized, ensure_ascii=False)
    assert secret not in serialized
    assert normalized["tool_args"]["nested"]["auth"]["token"] == "[redacted]"


def test_runtime_scene_events_merge_current_trace_with_explicit_fields_winning(monkeypatch) -> None:
    captured: dict = {}

    def capture_impl(*_args, **kwargs):
        captured.update(kwargs)
        return {"accepted": True}

    monkeypatch.setattr(runtime_scene_record, "_record_runtime_scene_event_impl", capture_impl)
    context = new_trace_context(request_id="scoped-request")

    with bind_trace_context(context):
        runtime_scene_record.record_runtime_scene_event(
            "session",
            "turn",
            "conversation.turn.accepted",
            fields={"requestId": "explicit-request", "sessionId": "session-a"},
        )

    assert captured["fields"] == {
        **context.to_fields(),
        "requestId": "explicit-request",
        "sessionId": "session-a",
    }
