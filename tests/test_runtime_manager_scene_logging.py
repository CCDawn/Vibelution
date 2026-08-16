from __future__ import annotations

from pathlib import Path

from core.launcher import service as launcher_service
from core.runtime_manager import scene_logging
from core.web.services import runtime_scene_service as runtime_scene_facade
from core.web.services.runtime_scene import record as runtime_scene_record


def test_facade_exports_quiet_scene_record_helper() -> None:
    assert (
        runtime_scene_facade.record_runtime_scene_event_quietly
        is runtime_scene_record.record_runtime_scene_event_quietly
    )


def test_record_runtime_scene_event_quietly_swallows_record_errors(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("scene write failed")

    monkeypatch.setattr(runtime_scene_record, "record_runtime_scene_event", boom)

    result = runtime_scene_record.record_runtime_scene_event_quietly(
        "git_process",
        "command",
        "git_process.command.failed",
        message="Git command failed.",
        level="error",
        outcome="failed",
    )

    assert result is None


def test_runtime_manager_scene_bridge_logs_failure_without_raising(monkeypatch, tmp_path: Path) -> None:
    warnings: list[str] = []
    file_events: list[tuple[object, ...]] = []

    class _Logger:
        def warning(self, message: str, tag: str = "") -> None:
            warnings.append(message)

    monkeypatch.setattr(scene_logging, "_debug_logger", _Logger())
    monkeypatch.setattr(
        scene_logging,
        "_runtime_scene_service",
        lambda: (_ for _ in ()).throw(RuntimeError("scene service unavailable")),
    )
    monkeypatch.setattr(
        scene_logging,
        "append_runtime_manager_file_event",
        lambda event_type, payload, **_kwargs: file_events.append((event_type, payload)) or "",
    )

    accepted = scene_logging.record_runtime_manager_scene_event(
        "command.failed",
        {"commandId": "cmd-1", "ok": False},
        phase="command",
    )

    assert accepted is False
    assert warnings
    assert "command.failed" in warnings[0]
    assert "RuntimeError" in warnings[0]
    assert file_events[0][0] == "runtime_scene.bridge_failed"
    assert file_events[0][1]["eventType"] == "command.failed"
    assert file_events[0][1]["exceptionType"] == "RuntimeError"


def test_load_launcher_public_config_records_load_failure(monkeypatch) -> None:
    file_events: list[tuple[object, ...]] = []
    scene_events: list[tuple[object, ...]] = []

    def boom(_path):
        raise ValueError("bad toml")

    monkeypatch.setattr(launcher_service, "load_public_config", boom)
    monkeypatch.setattr(
        launcher_service,
        "append_runtime_manager_file_event",
        lambda event_type, payload, **_kwargs: file_events.append((event_type, payload)) or "2026-08-16T00:00:00+00:00",
    )
    monkeypatch.setattr(
        launcher_service,
        "record_runtime_manager_scene_event",
        lambda event_type, payload, **kwargs: scene_events.append((event_type, payload, kwargs)),
    )

    result = launcher_service._load_launcher_public_config()

    assert result == {}
    assert file_events[0][0] == "launcher.config.load_failed"
    assert file_events[0][1]["exceptionType"] == "ValueError"
    assert "bad toml" in str(file_events[0][1]["exceptionMessage"])
    assert scene_events[0][0] == "launcher.config.load_failed"
