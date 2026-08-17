from __future__ import annotations

from starlette.requests import Request

from core.logging import debug as debug_logger
from core.web.middleware.runtime_scene_api import (
    api_runtime_record_failure_count,
    record_api_runtime_event,
    reset_api_runtime_record_failure_count_for_tests,
)


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
