import json
from pathlib import Path

from core.web.services import runtime_scene_service


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _seed_scene(tmp_path: Path, scene_id: str, rows: list[dict], *, status: str = "stopped") -> Path:
    scene_dir = tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "raw").mkdir(parents=True, exist_ok=True)
    (scene_dir / "summary.json").write_text("{}", encoding="utf-8")
    (scene_dir / "package_index.json").write_text("{}", encoding="utf-8")
    (scene_dir / "raw" / "desktop-entry-vbs.log").write_text(
        '{"ts":"2026-05-18T12:00:00Z","level":"info","event":"desktop_entry_vbs.started","message":"Launching hidden PowerShell desktop entry.","details":"action=start;run_id=test"}\n',
        encoding="utf-8",
    )
    (scene_dir / "raw" / "desktop-entry.log").write_text(
        '{"message":"Desktop entry started.","level":"info","fields":{"run_id":"run-a"},"event":"desktop_entry.started","ts":"2026-05-18T12:00:01Z"}\n',
        encoding="utf-8",
    )
    (scene_dir / "raw" / "launcher-control.log").write_text(
        '{"ts":"2026-05-18T12:00:02Z","level":"info","event":"launcher.python_runtime.selected","message":"Selected Python runtime for launcher-managed work.","fields":{"path":"python.exe","label":"launcher virtual environment"}}\n',
        encoding="utf-8",
    )
    (scene_dir / "raw" / "backend.stderr.log").write_text("traceback: provider failed\n", encoding="utf-8")
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_scene_id": scene_id,
                "started_at": "2026-05-18T12:00:00Z",
                "ended_at": "" if status == "running" else "2026-05-18T12:02:00Z",
                "status": status,
                "result": "failed" if status == "failed" else "explicit_stop",
                "trigger": "start",
                "session_mode": "managed",
                "project_root": str(tmp_path),
                "backend": {
                    "stderr_path": "raw/backend.stderr.log",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_jsonl(scene_dir / "timeline.jsonl", rows)
    _write_jsonl(
        scene_dir / "lifecycle.jsonl",
        [row for row in rows if row.get("phase") in {"startup", "shutdown", "health"}],
    )
    return scene_dir


def test_runtime_scene_detail_exposes_package_diagnosis_first_signal(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    _seed_scene(
        tmp_path,
        "scene-diagnosis-error",
        [
            {
                "runtime_scene_id": "scene-diagnosis-error",
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "backend",
                "phase": "startup",
                "event_code": "backend.start.failed",
                "level": "error",
                "outcome": "failed",
                "message": "Backend failed to start.",
                "fields": {"errorType": "RuntimeError"},
                "raw_refs": [{"path": "raw/backend.stderr.log", "tail_lines": 80}],
            }
        ],
        status="failed",
    )

    detail = runtime_scene_service.get_runtime_scene_detail("scene-diagnosis-error")

    diagnosis = detail["packageDiagnosis"]
    assert diagnosis["severity"] == "error"
    assert "错误信号" in diagnosis["userSummary"]
    assert diagnosis["firstSignal"]["eventCode"] == "backend.start.failed"
    assert diagnosis["firstSignal"]["rawRefs"] == [{"path": "raw/backend.stderr.log", "tail_lines": 80}]
    assert diagnosis["recommendedOrder"][:5] == [
        "summary.json",
        "package_index.json",
        "raw/desktop-entry-vbs.log",
        "raw/desktop-entry.log",
        "raw/launcher-control.log",
    ]
    assert diagnosis["recommendedOrder"][5:8] == [
        "timeline.jsonl",
        "raw/backend.stderr.log",
        "lifecycle.jsonl",
    ]
    assert diagnosis["startupTrace"]["steps"][0]["id"] == "desktop_entry_vbs"
    assert diagnosis["startupTrace"]["steps"][0]["status"] == "recorded"
    assert any(step["id"] == "backend_start" and step["status"] == "recorded" for step in diagnosis["startupTrace"]["steps"])
    assert diagnosis["keyEntries"][0]["path"] == "summary.json"
    assert diagnosis["keyEntries"][1]["path"] == "package_index.json"
    assert diagnosis["keyEntries"][2]["path"] == "raw/desktop-entry-vbs.log"
    assert any(item["path"] == "raw/backend.stderr.log" for item in diagnosis["keyEntries"])
    assert "logs/runtime_scenes/20260518T120000Z__scene-diagnosis-error/summary.json" in diagnosis["agentNextStep"]


def test_runtime_scene_detail_exposes_clean_package_diagnosis(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    _seed_scene(
        tmp_path,
        "scene-diagnosis-clean",
        [
            {
                "runtime_scene_id": "scene-diagnosis-clean",
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "backend",
                "phase": "health",
                "event_code": "backend.health.succeeded",
                "level": "info",
                "outcome": "succeeded",
                "message": "Backend passed health checks.",
                "fields": {},
            }
        ],
    )

    detail = runtime_scene_service.get_runtime_scene_detail("scene-diagnosis-clean")

    diagnosis = detail["packageDiagnosis"]
    assert diagnosis["severity"] == "info"
    assert "未发现明显错误或警告" in diagnosis["userSummary"]
    assert diagnosis["firstSignal"]["eventCode"] == "backend.health.succeeded"
    assert diagnosis["firstSignal"]["severity"] == "info"
    assert diagnosis["recommendedOrder"][:5] == [
        "summary.json",
        "package_index.json",
        "raw/desktop-entry-vbs.log",
        "raw/desktop-entry.log",
        "raw/launcher-control.log",
    ]
    assert "timeline.jsonl" in diagnosis["recommendedOrder"]
    assert "raw/backend.stderr.log" in diagnosis["recommendedOrder"]
    assert diagnosis["startupTrace"]["missingStepIds"]
    assert "startupTrace.missingStepIds" in diagnosis["agentNextStep"]


def test_runtime_scene_detail_exposes_startup_trace_with_desktop_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_dir = _seed_scene(
        tmp_path,
        "scene-startup-trace",
        [
            {
                "runtime_scene_id": "scene-startup-trace",
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "launcher",
                "phase": "session",
                "event_code": "runtime.scene.created",
                "level": "info",
                "outcome": "started",
                "message": "Created runtime scene bundle.",
                "fields": {},
            },
            {
                "runtime_scene_id": "scene-startup-trace",
                "ts": "2026-05-18T12:00:02Z",
                "seq": 2,
                "component": "backend",
                "phase": "startup",
                "event_code": "backend.start.requested",
                "level": "info",
                "outcome": "started",
                "message": "Starting bundled backend service.",
                "fields": {},
                "raw_refs": [{"path": "raw/backend.stdout.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": "scene-startup-trace",
                "ts": "2026-05-18T12:00:03Z",
                "seq": 3,
                "component": "backend",
                "phase": "health",
                "event_code": "backend.health.succeeded",
                "level": "info",
                "outcome": "succeeded",
                "message": "Backend passed health checks.",
                "fields": {},
            },
        ],
    )
    (scene_dir / "raw" / "desktop-entry.log").write_text(
        '{"event":"desktop_entry.started","fields":{"run_id":"run-a"}}\n',
        encoding="utf-8",
    )
    (scene_dir / "raw" / "backend.stdout.log").write_text("backend starting\n", encoding="utf-8")

    detail = runtime_scene_service.get_runtime_scene_detail("scene-startup-trace")

    diagnosis = detail["packageDiagnosis"]
    startup = diagnosis["startupTrace"]
    desktop_vbs_step = startup["steps"][0]
    desktop_step = startup["steps"][1]
    backend_step = next(step for step in startup["steps"] if step["id"] == "backend_start")
    assert desktop_vbs_step["status"] == "recorded"
    assert desktop_vbs_step["evidencePath"] == "raw/desktop-entry-vbs.log"
    assert desktop_vbs_step["timestamp"] == "2026-05-18T12:00:00Z"
    assert desktop_step["status"] == "recorded"
    assert desktop_step["evidencePath"] == "raw/desktop-entry.log"
    assert backend_step["status"] == "recorded"
    assert backend_step["eventCode"] == "backend.start.requested"
    assert diagnosis["recommendedOrder"][:4] == ["summary.json", "package_index.json", "raw/desktop-entry-vbs.log", "raw/desktop-entry.log"]
    assert any(item["label"].startswith("Startup: 桌面入口 VBS") for item in diagnosis["keyEntries"])


def test_runtime_scene_startup_trace_does_not_reuse_vbs_for_desktop_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_dir = _seed_scene(
        tmp_path,
        "scene-missing-desktop-entry",
        [
            {
                "runtime_scene_id": "scene-missing-desktop-entry",
                "ts": "2026-05-18T12:00:02Z",
                "seq": 1,
                "component": "backend",
                "phase": "health",
                "event_code": "backend.health.succeeded",
                "level": "info",
                "outcome": "succeeded",
                "message": "Backend passed health checks.",
                "fields": {},
            },
        ],
    )
    (scene_dir / "raw" / "desktop-entry.log").unlink()

    detail = runtime_scene_service.get_runtime_scene_detail("scene-missing-desktop-entry")

    startup = detail["packageDiagnosis"]["startupTrace"]
    desktop_vbs_step = startup["steps"][0]
    desktop_step = startup["steps"][1]
    assert desktop_vbs_step["status"] == "recorded"
    assert desktop_vbs_step["timestamp"] == "2026-05-18T12:00:00Z"
    assert desktop_step["status"] == "missing"
    assert desktop_step["evidencePath"] == ""
    assert "desktop_entry" in startup["missingStepIds"]


def test_runtime_scene_startup_trace_reads_vbs_logs_with_control_chars(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_dir = _seed_scene(
        tmp_path,
        "scene-vbs-control-char",
        [
            {
                "runtime_scene_id": "scene-vbs-control-char",
                "ts": "2026-05-18T12:00:02Z",
                "seq": 1,
                "component": "backend",
                "phase": "health",
                "event_code": "backend.health.succeeded",
                "level": "info",
                "outcome": "succeeded",
                "message": "Backend passed health checks.",
                "fields": {},
            },
        ],
    )
    (scene_dir / "raw" / "desktop-entry-vbs.log").write_text(
        '{"ts":"2026-05-18T12:00:00Z","level":"info","event":"desktop_entry_vbs.started","message":"Launching hidden PowerShell desktop entry.","details":"run_id=test\u0000"}\n',
        encoding="utf-8",
    )

    detail = runtime_scene_service.get_runtime_scene_detail("scene-vbs-control-char")

    desktop_vbs_step = detail["packageDiagnosis"]["startupTrace"]["steps"][0]
    assert desktop_vbs_step["status"] == "recorded"
    assert desktop_vbs_step["timestamp"] == "2026-05-18T12:00:00Z"
    assert desktop_vbs_step["eventCode"] == "desktop_entry_vbs.started"
