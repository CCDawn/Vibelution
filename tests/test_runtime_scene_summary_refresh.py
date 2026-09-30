#!/usr/bin/env python3
import json
import threading
import time
from pathlib import Path

from core.web.services import runtime_scene_service
from core.web.services.runtime_scene import record as runtime_scene_record


def _seed_active_scene(tmp_path: Path) -> Path:
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260812T000000Z__summary-refresh-test"
    scene_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_scene_id": "summary-refresh-test",
                "started_at": "2026-08-12T00:00:00Z",
                "ended_at": "",
                "status": "running",
                "result": "explicit_stop",
                "trigger": "start",
                "session_mode": "managed",
                "project_root": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    launcher_dir = tmp_path / ".runtime" / "launcher"
    launcher_dir.mkdir(parents=True, exist_ok=True)
    (launcher_dir / "active-runtime-scene.json").write_text(
        json.dumps(
            {
                "runtimeSceneDir": str(scene_dir),
                "runtimeSceneId": "summary-refresh-test",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return scene_dir


def test_active_scene_summary_refreshed_when_due(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    runtime_scene_service._last_scene_package_refresh_at = 0.0
    scene_dir = _seed_active_scene(tmp_path)

    refreshed = runtime_scene_record._refresh_active_scene_package_if_due(scene_dir)

    assert refreshed is True
    assert (scene_dir / "summary.json").exists()
    assert (scene_dir / "package_index.json").exists()
    summary = json.loads((scene_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary.get("package_id") == "summary-refresh-test"


def test_active_scene_summary_throttled_within_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    runtime_scene_service._last_scene_package_refresh_at = 1e18
    scene_dir = _seed_active_scene(tmp_path)

    refreshed = runtime_scene_record._refresh_active_scene_package_if_due(scene_dir)

    assert refreshed is False
    assert not (scene_dir / "summary.json").exists()


def _wait_for_file(path: Path, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return path.exists()


def test_scene_event_write_refreshes_summary_in_background(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    runtime_scene_service._last_scene_package_refresh_at = 0.0
    scene_dir = _seed_active_scene(tmp_path)

    result = runtime_scene_service.record_runtime_scene_event(
        "backend",
        "startup",
        "backend.api.ready",
        message="backend ready",
        level="info",
        outcome="succeeded",
    )

    assert result.get("accepted") is True
    # 刷新已移交后台线程，由轮询确认最终落地。
    assert _wait_for_file(scene_dir / "summary.json")
    assert runtime_scene_record._wait_for_background_scene_refresh(scene_dir, timeout=10)
    summary = json.loads((scene_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary.get("package_id") == "summary-refresh-test"


def test_periodic_refresh_runs_off_request_path(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    runtime_scene_service._last_scene_package_refresh_at = 0.0
    monkeypatch.setattr(
        runtime_scene_service, "_last_scene_package_refresh_duration_s", 0.0, raising=False
    )
    scene_dir = _seed_active_scene(tmp_path)
    release = threading.Event()

    def slow_update(scene: Path, manifest: dict) -> None:
        release.wait(timeout=10)

    monkeypatch.setattr(
        runtime_scene_service, "_update_runtime_scene_package_manifest", slow_update
    )

    started_at = time.monotonic()
    result = runtime_scene_service.record_runtime_scene_event(
        "backend",
        "startup",
        "backend.api.ready",
        message="backend ready",
        level="info",
        outcome="succeeded",
    )
    elapsed = time.monotonic() - started_at

    # 全量刷新被慢速 monkeypatch 卡住时，事件记录本身必须毫秒级返回。
    assert result.get("accepted") is True
    assert elapsed < 1.0
    assert not (scene_dir / "summary.json").exists()

    release.set()
    assert runtime_scene_record._wait_for_background_scene_refresh(scene_dir, timeout=10)
    assert runtime_scene_service._last_scene_package_refresh_at > 0.0


def test_background_refresh_does_not_pile_up(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    runtime_scene_service._last_scene_package_refresh_at = 0.0
    scene_dir = _seed_active_scene(tmp_path)
    calls: list[Path] = []
    started = threading.Event()
    release = threading.Event()

    def blocking_update(scene: Path, manifest: dict) -> None:
        calls.append(scene)
        started.set()
        release.wait(timeout=10)

    monkeypatch.setattr(
        runtime_scene_service, "_update_runtime_scene_package_manifest", blocking_update
    )

    first = runtime_scene_service.record_runtime_scene_event(
        "backend",
        "startup",
        "backend.api.ready",
        message="backend ready",
        level="info",
        outcome="succeeded",
    )
    assert first.get("accepted") is True
    assert started.wait(timeout=10)

    # 后台刷新在跑时，后续常规事件只登记不排队：同一场景不叠加第二个全量刷新。
    burst_started_at = time.monotonic()
    second = runtime_scene_service.record_runtime_scene_event(
        "backend", "startup", "backend.api.ready", message="second", level="info", outcome="succeeded"
    )
    third = runtime_scene_service.record_runtime_scene_event(
        "backend", "startup", "backend.api.ready", message="third", level="info", outcome="succeeded"
    )
    burst_elapsed = time.monotonic() - burst_started_at

    release.set()
    assert runtime_scene_record._wait_for_background_scene_refresh(scene_dir, timeout=10)

    assert second.get("accepted") is True
    assert third.get("accepted") is True
    assert burst_elapsed < 1.0
    assert calls == [scene_dir]


def test_scene_event_can_defer_periodic_summary_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "_last_scene_package_refresh_at", 0.0)
    scene_dir = _seed_active_scene(tmp_path)

    result = runtime_scene_service.record_runtime_scene_event(
        "runtime_manager",
        "queue",
        "command_queue.command_claimed",
        message="runtime manager claimed lifecycle command",
        level="info",
        outcome="started",
        lifecycle=True,
        refresh_package_if_due=False,
    )

    assert result.get("accepted") is True
    assert result.get("projectionRefresh") == "deferred"
    assert not (scene_dir / "summary.json").exists()
    assert not (scene_dir / "package_index.json").exists()
    rows = [
        json.loads(line)
        for line in (scene_dir / "events" / "runtime_manager.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[-1]["event_code"] == "command_queue.command_claimed"


def test_active_scene_refresh_is_single_flight(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "_last_scene_package_refresh_at", 0.0)
    scene_dir = _seed_active_scene(tmp_path)
    calls: list[Path] = []
    started = threading.Event()
    release = threading.Event()

    def blocking_update(scene: Path, manifest: dict) -> None:
        calls.append(scene)
        started.set()
        release.wait(timeout=10)

    monkeypatch.setattr(
        runtime_scene_service, "_update_runtime_scene_package_manifest", blocking_update
    )
    results: dict[str, bool] = {}

    def first_refresh() -> None:
        results["first"] = runtime_scene_record._refresh_active_scene_package_if_due(scene_dir)

    worker = threading.Thread(target=first_refresh)
    worker.start()
    assert started.wait(timeout=10)

    # A concurrent recorder that missed the claim (stale timestamp) must skip
    # on the non-blocking package lock instead of queueing a second full
    # refresh behind the in-flight one.
    monkeypatch.setattr(runtime_scene_service, "_last_scene_package_refresh_at", 0.0)
    started_at = time.monotonic()
    second = runtime_scene_record._refresh_active_scene_package_if_due(scene_dir)
    elapsed = time.monotonic() - started_at

    release.set()
    worker.join(timeout=10)

    assert second is False
    assert elapsed < 1.0
    assert results.get("first") is True
    assert calls == [scene_dir]


def test_active_scene_refresh_computes_diagnosis_once(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "_last_scene_package_refresh_at", 0.0)
    scene_dir = _seed_active_scene(tmp_path)
    calls: list[str] = []
    original = runtime_scene_service._runtime_scene_package_diagnosis_for_scene

    def counting_diagnosis(*args, **kwargs):
        calls.append(str(args[2]))
        return original(*args, **kwargs)

    monkeypatch.setattr(
        runtime_scene_service,
        "_runtime_scene_package_diagnosis_for_scene",
        counting_diagnosis,
    )

    refreshed = runtime_scene_record._refresh_active_scene_package_if_due(scene_dir)

    assert refreshed is True
    assert len(calls) == 1
    summary = json.loads((scene_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["diagnosis"]["issueState"] is not None


def test_deferred_periodic_refresh_keeps_warning_projection_immediate(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "_last_scene_package_refresh_at", 0.0)
    scene_dir = _seed_active_scene(tmp_path)
    full_projection_calls: list[Path] = []
    monkeypatch.setattr(
        runtime_scene_service,
        "_update_runtime_scene_package_manifest",
        lambda scene, manifest: full_projection_calls.append(scene),
    )

    result = runtime_scene_service.record_runtime_scene_event(
        "runtime_manager",
        "consistency",
        "workbench.consistency.orphaned_browser_detected",
        message="orphaned browser detected",
        level="warning",
        outcome="observed",
        lifecycle=True,
        refresh_package_if_due=False,
    )

    assert result.get("accepted") is True
    assert result.get("projectionRefresh") == "full"
    assert full_projection_calls == [scene_dir]


def test_warning_storm_uses_single_full_refresh_window(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "_last_scene_package_refresh_at", 0.0)
    monkeypatch.setattr(runtime_scene_service, "_last_scene_package_refresh_duration_s", 0.0, raising=False)
    scene_dir = _seed_active_scene(tmp_path)
    full_projection_calls: list[Path] = []
    monkeypatch.setattr(
        runtime_scene_service,
        "_update_runtime_scene_package_manifest",
        lambda scene, manifest: full_projection_calls.append(scene),
    )

    first = runtime_scene_service.record_runtime_scene_event(
        "runtime_manager",
        "consistency",
        "workbench.consistency.orphaned_browser_detected",
        message="orphaned browser detected",
        level="warning",
        outcome="observed",
        lifecycle=True,
        refresh_package_if_due=False,
    )
    second = runtime_scene_service.record_runtime_scene_event(
        "runtime_manager",
        "consistency",
        "workbench.consistency.orphaned_browser_detected",
        message="orphaned browser detected",
        level="warning",
        outcome="observed",
        lifecycle=True,
        refresh_package_if_due=False,
    )

    # 同一窗口内的第二次 warning 不再重复全量诊断。
    assert first.get("projectionRefresh") == "full"
    assert second.get("projectionRefresh") == "deferred"
    assert full_projection_calls == [scene_dir]


def test_package_refresh_window_scales_with_last_refresh_duration(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        runtime_scene_service, "_last_scene_package_refresh_duration_s", 12.0, raising=False
    )
    monkeypatch.setattr(
        runtime_scene_service, "_last_scene_package_refresh_at", time.monotonic() - 34.0
    )
    scene_dir = _seed_active_scene(tmp_path)

    # 34s 超过基础 30s，但 12s * 4 = 48s 的自适应窗口还没到。
    refreshed = runtime_scene_record._refresh_active_scene_package_if_due(scene_dir)

    assert runtime_scene_record._scene_package_refresh_min_interval_seconds() == 48.0
    assert refreshed is False
    assert not (scene_dir / "summary.json").exists()
