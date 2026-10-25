from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.background import BackgroundTasks
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

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


def _observe_response_body(app, events: list[str]):
    async def observed_app(scope, receive, send):
        async def observed_send(message):
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                events.append("body-sent")

        await app(scope, receive, observed_send)

    return observed_app


def test_slow_json_get_records_after_body_with_trace_and_existing_background_tasks(monkeypatch) -> None:
    events: list[str] = []
    payloads: list[dict] = []

    def record(payload):
        events.append("diagnostic")
        payloads.append(payload)

    monkeypatch.setattr("core.web.services.runtime_scene_service.record_backend_api_event", record)
    clock = iter([0.0, 1.0])
    monkeypatch.setattr("core.web.middleware.runtime_scene_api._api_runtime_perf_counter", lambda: next(clock))
    app = FastAPI()
    app.add_middleware(RuntimeSceneApiEventMiddleware)

    @app.get("/api/slow-json")
    async def slow_json():
        background = BackgroundTasks()
        background.add_task(events.append, "existing-first")
        background.add_task(events.append, "existing-second")
        return JSONResponse(get_current_trace_context().to_fields(), background=background)

    response = TestClient(_observe_response_body(app, events)).get(
        "/api/slow-json?token=do-not-record&page=1",
        headers={"X-Request-ID": "deferred-request", "traceparent": f"00-{'1' * 32}-{'2' * 16}-01"},
    )

    assert response.status_code == 200
    assert events.index("body-sent") < events.index("diagnostic")
    assert events.count("diagnostic") == 1
    assert events.count("existing-first") == events.count("existing-second") == 1
    assert events.index("existing-first") < events.index("existing-second")
    assert payloads[0]["fields"] == response.json()
    assert payloads[0]["duration_ms"] == 1000.0
    assert payloads[0]["path_template"] == "/api/slow-json"
    assert "do-not-record" not in json.dumps(payloads)
    assert response.headers["X-Request-ID"] == "deferred-request"
    assert get_current_trace_context() is None


def test_deferred_diagnostic_keeps_background_attached_to_dispatch_response(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        "core.web.middleware.runtime_scene_api.record_api_runtime_event",
        lambda *_args, **_kwargs: events.append("diagnostic"),
    )
    clock = iter([0.0, 1.0])
    monkeypatch.setattr("core.web.middleware.runtime_scene_api._api_runtime_perf_counter", lambda: next(clock))
    response = JSONResponse({"ok": True}, background=BackgroundTasks())
    response.background.add_task(events.append, "existing")
    request = Request({"type": "http", "method": "GET", "path": "/api/slow-json", "headers": []})

    async def run():
        async def call_next(_request):
            return response

        result = await RuntimeSceneApiEventMiddleware(None).dispatch(request, call_next)
        assert events == []
        await result.background()

    asyncio.run(run())
    assert events == ["diagnostic", "existing"]


@pytest.mark.parametrize(
    ("method", "status_code", "referer", "streaming", "media_type"),
    [
        ("POST", 200, "", False, "application/json"),
        ("GET", 500, "", False, "application/json"),
        ("GET", 200, "/teams", False, "application/json"),
        ("GET", 200, "", True, "text/event-stream"),
        ("GET", 200, "", True, "application/json"),
    ],
)
def test_mutation_error_referer_and_stream_diagnostics_stay_before_body(
    monkeypatch, method, status_code, referer, streaming, media_type
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        "core.web.middleware.runtime_scene_api.record_api_runtime_event",
        lambda *_args, **_kwargs: events.append("diagnostic"),
    )
    clock = iter([0.0, 1.0])
    monkeypatch.setattr("core.web.middleware.runtime_scene_api._api_runtime_perf_counter", lambda: next(clock))
    app = FastAPI()
    app.add_middleware(RuntimeSceneApiEventMiddleware)

    @app.api_route("/api/probe", methods=[method])
    async def probe():
        if streaming:
            return StreamingResponse(iter([b"data: {}\n\n"]), media_type=media_type)
        return JSONResponse({"ok": True}, status_code=status_code)

    response = TestClient(_observe_response_body(app, events)).request(
        method, "/api/probe", headers={"referer": referer}
    )

    assert response.status_code == status_code
    assert events == ["diagnostic", "body-sent"]


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
