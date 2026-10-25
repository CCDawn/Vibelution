from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path

import pytest

from core.web.services import runtime_scene_service
from tests.helpers.web_runtime_scene import _seed_runtime_scene_bundle


@pytest.fixture(autouse=True)
def _pin_periodic_package_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the throttled periodic package refresh out of these assertions.

    Ordinary events also ride a deliberately throttled (30s) package refresh that
    keeps summary/package_index fresh for diagnosis; that behavior has its own
    contract in ``test_runtime_scene_summary_refresh.py``.  The clock behind it is
    a lazily created process-global, so on a fresh process it reads as ``0.0`` and
    the refresh fires on the first event -- which made the fastpath assertions
    below depend on how recently some earlier test happened to refresh.  Pinning
    it keeps each test here measuring the per-event fastpath it claims to measure.
    """

    monkeypatch.setattr(
        runtime_scene_service,
        "_last_scene_package_refresh_at",
        float("inf"),
        raising=False,
    )


class _RecordingPipelineMetrics:
    def __init__(self) -> None:
        self.operations: list[tuple[str, str]] = []

    @contextmanager
    def measure(self, operation: str, *, priority: str = "normal"):
        self.operations.append((operation, priority))
        yield


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


def test_ordinary_runtime_event_is_append_only_and_keeps_incremental_sequence(tmp_path, monkeypatch) -> None:
    scene_dir = _point_runtime_scene_at(tmp_path, monkeypatch, scene_id="scene-append-only")
    event_path = scene_dir / "events" / "conversation.jsonl"
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.write_text(json.dumps({"seq": 41, "event_code": "seed"}) + "\n", encoding="utf-8")
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

    first = runtime_scene_service.record_runtime_scene_event(
        "conversation",
        "turn",
        "conversation.turn.started",
        fields={"sessionId": "session-fast", "turnId": "turn-1"},
    )
    second = runtime_scene_service.record_runtime_scene_event(
        "conversation",
        "turn",
        "conversation.turn.scheduled",
        fields={"sessionId": "session-fast", "turnId": "turn-1"},
    )

    assert first["projectionRefresh"] == "deferred"
    assert second["projectionRefresh"] == "deferred"
    assert full_calls == []
    assert lightweight_calls == []
    rows = [
        json.loads(line)
        for line in event_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["seq"] for row in rows[-2:]] == [42, 43]


def test_scene_append_resolves_sequence_key_once_and_checks_both_signatures(tmp_path, monkeypatch) -> None:
    scene_dir = tmp_path / "scene"
    event_path = scene_dir / "events" / "agent.jsonl"
    resolved_paths = []
    signatures = []
    original_resolve = Path.resolve
    original_signature = runtime_scene_service._scene_event_file_signature

    def record_resolve(path, *args, **kwargs):
        resolved_paths.append(path)
        return original_resolve(path, *args, **kwargs)

    def record_signature(path):
        signature = original_signature(path)
        signatures.append(signature)
        return signature

    monkeypatch.setattr(Path, "resolve", record_resolve)
    monkeypatch.setattr(runtime_scene_service, "_scene_event_file_signature", record_signature)
    monkeypatch.setattr(runtime_scene_service, "_should_promote_scene_event_to_timeline", lambda _: False)

    runtime_scene_service._append_scene_event(scene_dir, "agent", {"event_code": "agent.started"})

    assert resolved_paths == [event_path]
    assert signatures == [(0, 0), original_signature(event_path)]
    assert signatures[1][0] > 0


@pytest.mark.parametrize("external_change", ["append", "truncate", "replace"])
def test_scene_append_recovers_sequence_after_external_file_change(tmp_path, monkeypatch, external_change) -> None:
    scene_dir = tmp_path / "scene"
    event_path = scene_dir / "events" / "agent.jsonl"
    monkeypatch.setattr(runtime_scene_service, "_should_promote_scene_event_to_timeline", lambda _: False)
    original_read = runtime_scene_service._read_last_scene_event_seq
    reads = []

    def record_read(path):
        reads.append(path)
        return original_read(path)

    monkeypatch.setattr(runtime_scene_service, "_read_last_scene_event_seq", record_read)
    runtime_scene_service._append_scene_event(scene_dir, "agent", {"event_code": "agent.started"})
    runtime_scene_service._append_scene_event(scene_dir, "agent", {"event_code": "agent.finished"})
    assert reads == [event_path]

    if external_change == "append":
        with event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"seq": 70, "source": "external append"}) + "\n")
        expected_seq = 71
    elif external_change == "truncate":
        event_path.write_text("", encoding="utf-8")
        expected_seq = 1
    else:
        replacement = event_path.with_suffix(".replacement")
        replacement.write_text(json.dumps({"seq": 90}) + "\n", encoding="utf-8")
        replacement.replace(event_path)
        expected_seq = 91

    runtime_scene_service._append_scene_event(scene_dir, "agent", {"event_code": "agent.restarted"})

    rows = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["seq"] == expected_seq
    assert reads == [event_path, event_path]


def test_scene_sequence_helpers_keep_direct_call_compatibility(tmp_path) -> None:
    event_path = tmp_path / "events" / "agent.jsonl"
    assert runtime_scene_service._next_scene_event_seq(tmp_path, "agent") == 1
    event_path.parent.mkdir()
    event_path.write_text(json.dumps({"seq": 8}) + "\n", encoding="utf-8")
    runtime_scene_service._remember_scene_event_seq(event_path, 8)
    assert runtime_scene_service._next_scene_event_seq(tmp_path, "agent") == 9


def test_ordinary_runtime_event_does_not_wait_for_package_projection_lock(tmp_path, monkeypatch) -> None:
    scene_dir = _point_runtime_scene_at(tmp_path, monkeypatch, scene_id="scene-package-lock-isolation")

    class BusyPackageLock:
        def __enter__(self):
            raise AssertionError("ordinary event path must not acquire the package projection lock")

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(runtime_scene_service, "RUNTIME_SCENE_PACKAGE_WRITE_LOCK", BusyPackageLock())

    result = runtime_scene_service.record_runtime_scene_event(
        "agent",
        "prompt",
        "agent.initial_context.completed",
        fields={"gitRefreshMs": 12, "promptBuildMs": 3},
    )

    assert result["projectionRefresh"] == "deferred"
    rows = [
        json.loads(line)
        for line in (scene_dir / "events" / "agent.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[-1]["event_code"] == "agent.initial_context.completed"


def test_ordinary_runtime_event_records_append_pipeline_duration(tmp_path, monkeypatch) -> None:
    _point_runtime_scene_at(tmp_path, monkeypatch, scene_id="scene-append-metrics")
    metrics = _RecordingPipelineMetrics()
    monkeypatch.setattr(runtime_scene_service, "pipeline_metrics", metrics)

    runtime_scene_service.record_runtime_scene_event(
        "conversation",
        "turn",
        "conversation.turn.started",
        fields={"sessionId": "session-fast", "turnId": "turn-metrics"},
    )

    assert metrics.operations == [("append", "normal")]


def test_warning_runtime_event_appends_before_full_projection(tmp_path, monkeypatch) -> None:
    _point_runtime_scene_at(tmp_path, monkeypatch, scene_id="scene-warning-projection")
    monkeypatch.setattr(runtime_scene_service, "_last_scene_package_refresh_at", 0.0)
    projection_calls: list[str] = []

    def record_projection(scene, manifest) -> None:
        rows = [
            json.loads(line)
            for line in (scene / "events" / "agent_directory.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert rows[-1]["event_code"] == "agent_directory.list_agents.slow"
        projection_calls.append(rows[-1]["event_code"])

    monkeypatch.setattr(runtime_scene_service, "_update_runtime_scene_package_manifest", record_projection)

    result = runtime_scene_service.record_runtime_scene_event(
        "agent_directory",
        "agent",
        "agent_directory.list_agents.slow",
        level="warning",
        fields={"elapsedMs": 9000},
    )

    assert result["projectionRefresh"] == "full"
    assert projection_calls == ["agent_directory.list_agents.slow"]


def test_warning_runtime_event_defers_when_projection_already_running(tmp_path, monkeypatch) -> None:
    _point_runtime_scene_at(tmp_path, monkeypatch, scene_id="scene-warning-storm")

    class BusyPackageLock:
        def acquire(self, blocking: bool = True) -> bool:
            return False

        def release(self) -> None:
            raise AssertionError("a skipped warning projection must not release the lock")

        def __enter__(self):
            raise AssertionError("the warning path must not block on the package projection lock")

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(runtime_scene_service, "RUNTIME_SCENE_PACKAGE_WRITE_LOCK", BusyPackageLock())
    monkeypatch.setattr(
        runtime_scene_service,
        "_update_runtime_scene_package_manifest",
        lambda scene, manifest: (_ for _ in ()).throw(
            AssertionError("a queued warning must not rebuild the package projection")
        ),
    )

    result = runtime_scene_service.record_runtime_scene_event(
        "agent_directory",
        "agent",
        "agent_directory.list_agents.slow",
        level="warning",
        fields={"elapsedMs": 9000},
    )

    assert result["projectionRefresh"] == "deferred"


def test_warning_runtime_event_records_append_and_projection_pipeline_durations(tmp_path, monkeypatch) -> None:
    _point_runtime_scene_at(tmp_path, monkeypatch, scene_id="scene-projection-metrics")
    monkeypatch.setattr(runtime_scene_service, "_last_scene_package_refresh_at", 0.0)
    metrics = _RecordingPipelineMetrics()
    monkeypatch.setattr(runtime_scene_service, "pipeline_metrics", metrics)
    monkeypatch.setattr(runtime_scene_service, "_update_runtime_scene_package_manifest", lambda scene, manifest: None)

    runtime_scene_service.record_runtime_scene_event(
        "agent_directory",
        "agent",
        "agent_directory.list_agents.slow",
        level="warning",
        fields={"elapsedMs": 9000},
    )

    assert metrics.operations == [("append", "normal"), ("projection", "high")]


def test_recovered_replay_degradation_warning_is_append_only(tmp_path, monkeypatch) -> None:
    scene_dir = _point_runtime_scene_at(tmp_path, monkeypatch, scene_id="scene-replay-degraded")
    metrics = _RecordingPipelineMetrics()

    class BusyPackageLock:
        def __enter__(self):
            raise AssertionError("recovered replay degradation must not acquire the projection lock")

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(runtime_scene_service, "pipeline_metrics", metrics)
    monkeypatch.setattr(runtime_scene_service, "RUNTIME_SCENE_PACKAGE_WRITE_LOCK", BusyPackageLock())
    monkeypatch.setattr(
        runtime_scene_service,
        "_update_runtime_scene_package_manifest",
        lambda scene, manifest: (_ for _ in ()).throw(
            AssertionError("recovered replay degradation must not rebuild the package projection")
        ),
    )

    result = runtime_scene_service.record_runtime_scene_event(
        "llm",
        "projection",
        "llm.replay_state.degraded",
        level="warning",
        outcome="degraded",
        fields={
            "reason": "missing_assistant_anchor",
            "continuationMode": "unsupported_previous_response_id_replay_dropped",
            "replayItemCount": 1,
            "hasResponseId": True,
            "previousResponseIdUsable": False,
        },
    )

    assert result["projectionRefresh"] == "deferred"
    assert metrics.operations == [("append", "normal")]
    rows = [
        json.loads(line)
        for line in (scene_dir / "events" / "llm.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[-1]["event_code"] == "llm.replay_state.degraded"
    assert rows[-1]["level"] == "warning"
    assert rows[-1]["outcome"] == "degraded"
    assert rows[-1]["fields"]["continuationMode"] == (
        "unsupported_previous_response_id_replay_dropped"
    )
    assert rows[-1]["fields"]["hasResponseId"] is True
    assert rows[-1]["fields"]["previousResponseIdUsable"] is False


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
