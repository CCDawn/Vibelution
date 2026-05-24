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
    assert "issueState.activeClusterCount" in diagnosis["agentNextStep"]
    assert "rawRefs" in diagnosis["agentNextStep"]


def test_runtime_scene_first_signal_prefers_errors_over_earlier_user_stop_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    _seed_scene(
        tmp_path,
        "scene-diagnosis-error-priority",
        [
            {
                "runtime_scene_id": "scene-diagnosis-error-priority",
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "conversation",
                "phase": "next_state_signal",
                "event_code": "conversation.next_state_signal.recorded",
                "level": "warning",
                "outcome": "user_stops",
                "message": "用户请求停止当前对话轮次。",
                "fields": {"kind": "user_stops"},
                "raw_refs": [{"path": "conversations/chat-next-state-signals.jsonl", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": "scene-diagnosis-error-priority",
                "ts": "2026-05-18T12:00:02Z",
                "seq": 2,
                "component": "backend",
                "phase": "startup",
                "event_code": "backend.start.failed",
                "level": "error",
                "outcome": "failed",
                "message": "Backend failed to start.",
                "fields": {"errorType": "RuntimeError"},
                "raw_refs": [{"path": "raw/backend.stderr.log", "tail_lines": 80}],
            },
        ],
        status="failed",
    )

    detail = runtime_scene_service.get_runtime_scene_detail("scene-diagnosis-error-priority")

    diagnosis = detail["packageDiagnosis"]
    assert diagnosis["severity"] == "error"
    assert diagnosis["firstSignal"]["severity"] == "error"
    assert diagnosis["firstSignal"]["eventCode"] == "backend.start.failed"
    assert diagnosis["firstSignal"]["rawRefs"] == [{"path": "raw/backend.stderr.log", "tail_lines": 80}]
    assert "backend.start.failed" in diagnosis["userSummary"]
    assert "backend.start.failed" in diagnosis["agentNextStep"]
    assert "主问题簇" in diagnosis["agentNextStep"]
    assert "conversation.next_state_signal.recorded" not in diagnosis["agentNextStep"]


def test_runtime_scene_diagnosis_separates_recovered_errors_from_active_issues(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    _seed_scene(
        tmp_path,
        "scene-diagnosis-recovered-error",
        [
            {
                "runtime_scene_id": "scene-diagnosis-recovered-error",
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "frontend",
                "phase": "build",
                "event_code": "frontend.build.failed",
                "level": "error",
                "outcome": "failed",
                "message": "Frontend build failed.",
                "fields": {"runId": "build-1", "errorType": "BuildError"},
                "raw_refs": [{"path": "raw/frontend.build.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": "scene-diagnosis-recovered-error",
                "ts": "2026-05-18T12:00:02Z",
                "seq": 2,
                "component": "frontend",
                "phase": "build",
                "event_code": "frontend.build.succeeded",
                "level": "info",
                "outcome": "succeeded",
                "message": "Frontend build recovered.",
                "fields": {"runId": "build-1"},
            },
            {
                "runtime_scene_id": "scene-diagnosis-recovered-error",
                "ts": "2026-05-18T12:00:03Z",
                "seq": 3,
                "component": "conversation",
                "phase": "next_state_signal",
                "event_code": "conversation.next_state_signal.recorded",
                "level": "warning",
                "outcome": "user_stops",
                "message": "用户请求停止当前对话轮次。",
                "fields": {"kind": "user_stops"},
            },
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail("scene-diagnosis-recovered-error")

    diagnosis = detail["packageDiagnosis"]
    assert diagnosis["severity"] == "info"
    assert diagnosis["issueState"]["activeErrorCount"] == 0
    assert diagnosis["issueState"]["activeWarningCount"] == 0
    assert diagnosis["issueState"]["historicalErrorCount"] == 1
    assert diagnosis["issueState"]["controlSignalCount"] == 1
    assert diagnosis["firstSignal"]["eventCode"] == "frontend.build.failed"
    assert "历史/已恢复问题簇" in diagnosis["userSummary"]
    assert "当前未发现活跃错误或警告" in diagnosis["userSummary"]
    assert "历史/已恢复簇计数" in diagnosis["agentNextStep"]
    assert "避免把已恢复错误当成当前阻塞" in diagnosis["agentNextStep"]


def test_runtime_scene_issue_state_clusters_repeated_active_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    _seed_scene(
        tmp_path,
        "scene-diagnosis-repeated-browser-error",
        [
            {
                "runtime_scene_id": "scene-diagnosis-repeated-browser-error",
                "ts": f"2026-05-18T12:00:0{seq}Z",
                "seq": seq,
                "component": "browser",
                "phase": "console",
                "event_code": "browser.console.error",
                "level": "error",
                "outcome": "failed",
                "message": "Uncaught TypeError: Cannot read properties of undefined.",
                "fields": {"pageInstanceId": "page-a"},
                "raw_refs": [{"path": "raw/browser.log", "tail_lines": 80}],
            }
            for seq in (1, 2, 3)
        ],
        status="failed",
    )

    detail = runtime_scene_service.get_runtime_scene_detail("scene-diagnosis-repeated-browser-error")

    issue_state = detail["packageDiagnosis"]["issueState"]
    assert issue_state["activeErrorCount"] == 3
    assert issue_state["activeClusterCount"] == 1
    assert issue_state["activeClusters"][0]["eventCode"] == "browser.console.error"
    assert issue_state["activeClusters"][0]["repeatCount"] == 3
    assert issue_state["activeClusters"][0]["identity"] == {"pageInstanceId": "page-a"}
    assert issue_state["firstActiveCluster"]["repeatCount"] == 3
    assert "browser.console.error ×3" in detail["packageDiagnosis"]["userSummary"]
    assert "browser.console.error ×3" in detail["packageDiagnosis"]["agentNextStep"]


def test_runtime_scene_issue_state_excludes_control_signals_from_clusters(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    _seed_scene(
        tmp_path,
        "scene-diagnosis-control-only",
        [
            {
                "runtime_scene_id": "scene-diagnosis-control-only",
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "conversation",
                "phase": "next_state_signal",
                "event_code": "conversation.next_state_signal.recorded",
                "level": "warning",
                "outcome": "user_stops",
                "message": "用户请求停止当前对话轮次。",
                "fields": {"kind": "user_stops"},
            }
        ],
        status="stopped",
    )

    detail = runtime_scene_service.get_runtime_scene_detail("scene-diagnosis-control-only")

    issue_state = detail["packageDiagnosis"]["issueState"]
    assert issue_state["severity"] == "info"
    assert issue_state["controlSignalCount"] == 1
    assert issue_state["activeClusterCount"] == 0
    assert issue_state["historicalClusterCount"] == 0
    assert issue_state["activeClusters"] == []
    assert issue_state["historicalClusters"] == []
    assert "控制类信号" in detail["packageDiagnosis"]["userSummary"]
    assert "主问题簇" not in detail["packageDiagnosis"]["agentNextStep"]


def test_runtime_scene_issue_state_clusters_recovered_historical_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    _seed_scene(
        tmp_path,
        "scene-diagnosis-historical-cluster",
        [
            {
                "runtime_scene_id": "scene-diagnosis-historical-cluster",
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "frontend",
                "phase": "build",
                "event_code": "frontend.build.failed",
                "level": "error",
                "outcome": "failed",
                "message": "Frontend build failed.",
                "fields": {"runId": "build-1", "errorType": "BuildError"},
                "raw_refs": [{"path": "raw/frontend.build.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": "scene-diagnosis-historical-cluster",
                "ts": "2026-05-18T12:00:02Z",
                "seq": 2,
                "component": "frontend",
                "phase": "build",
                "event_code": "frontend.build.failed",
                "level": "error",
                "outcome": "failed",
                "message": "Frontend build failed again.",
                "fields": {"runId": "build-1", "errorType": "BuildError"},
                "raw_refs": [{"path": "raw/frontend.build.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": "scene-diagnosis-historical-cluster",
                "ts": "2026-05-18T12:00:03Z",
                "seq": 3,
                "component": "frontend",
                "phase": "build",
                "event_code": "frontend.build.succeeded",
                "level": "info",
                "outcome": "succeeded",
                "message": "Frontend build recovered.",
                "fields": {"runId": "build-1"},
            },
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail("scene-diagnosis-historical-cluster")

    issue_state = detail["packageDiagnosis"]["issueState"]
    assert issue_state["severity"] == "info"
    assert issue_state["historicalErrorCount"] == 2
    assert issue_state["historicalClusterCount"] == 1
    assert issue_state["historicalClusters"][0]["eventCode"] == "frontend.build.failed"
    assert issue_state["historicalClusters"][0]["repeatCount"] == 2
    assert issue_state["firstHistoricalCluster"]["identity"] == {"runId": "build-1"}
    assert "frontend.build.failed ×2" in detail["packageDiagnosis"]["userSummary"]
    assert "frontend.build.failed ×2" in detail["packageDiagnosis"]["agentNextStep"]


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


def test_runtime_scene_package_diagnosis_uses_effective_running_status(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_dir = _seed_scene(
        tmp_path,
        "scene-diagnosis-effective-running",
        [
            {
                "runtime_scene_id": "scene-diagnosis-effective-running",
                "ts": "2026-05-18T12:00:01Z",
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
        status="running",
    )
    (scene_dir / "raw" / "frontend.build.log").write_text("frontend current\n", encoding="utf-8")
    (scene_dir / "events").mkdir(parents=True, exist_ok=True)
    (scene_dir / "events" / "launcher.jsonl").write_text(
        '{"event_code":"backend.dependencies.current","ts":"2026-05-18T12:00:01Z"}\n',
        encoding="utf-8",
    )
    (scene_dir / "raw" / "browser.log").write_text("browser opened\n", encoding="utf-8")
    (scene_dir / "raw" / "supervisor.log").write_text("supervisor started\n", encoding="utf-8")
    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["status"] = "unknown"
    manifest["ended_at"] = ""
    (scene_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    detail = runtime_scene_service.get_runtime_scene_detail("scene-diagnosis-effective-running")

    diagnosis = detail["packageDiagnosis"]
    assert detail["status"] == "running"
    assert "本周期状态为 running" in diagnosis["userSummary"]
    assert "当前周期状态为 running" in diagnosis["startupTrace"]["summary"]
    assert "unknown" not in diagnosis["userSummary"]
    assert "unknown" not in diagnosis["startupTrace"]["summary"]


def test_runtime_scene_timeline_folds_repeated_work_run_snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    _seed_scene(
        tmp_path,
        "scene-fold-work-run-snapshots",
        [
            {
                "runtime_scene_id": "scene-fold-work-run-snapshots",
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "work_run",
                "phase": "state",
                "event_code": "work_run.snapshot.persisted",
                "level": "info",
                "outcome": "succeeded",
                "message": "Work run snapshot persisted: supervised/run-1 running",
                "fields": {"runKind": "supervised", "runId": "run-1", "status": "running", "phase": "running"},
            },
            {
                "runtime_scene_id": "scene-fold-work-run-snapshots",
                "ts": "2026-05-18T12:00:02Z",
                "seq": 2,
                "component": "work_run",
                "phase": "state",
                "event_code": "work_run.snapshot.persisted",
                "level": "info",
                "outcome": "succeeded",
                "message": "Work run snapshot persisted: supervised/run-1 running",
                "fields": {"runKind": "supervised", "runId": "run-1", "status": "running", "phase": "running"},
            },
            {
                "runtime_scene_id": "scene-fold-work-run-snapshots",
                "ts": "2026-05-18T12:00:03Z",
                "seq": 3,
                "component": "work_run",
                "phase": "state",
                "event_code": "work_run.snapshot.persisted",
                "level": "info",
                "outcome": "succeeded",
                "message": "Work run snapshot persisted: supervised/run-1 done",
                "fields": {"runKind": "supervised", "runId": "run-1", "status": "done", "phase": "done"},
            },
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail("scene-fold-work-run-snapshots")

    assert [event["eventCode"] for event in detail["timeline"]].count("work_run.snapshot.persisted") == 1
    summary = next(event for event in detail["timeline"] if event["eventCode"] == "work_run.snapshot.summary")
    assert summary["fields"]["repeatCount"] == 2
    assert summary["fields"]["foldedEvent"] is True
    assert summary["fields"]["originalEventCode"] == "work_run.snapshot.persisted"
    assert summary["fields"]["firstTimestamp"] == "2026-05-18T12:00:01Z"
    assert summary["fields"]["lastTimestamp"] == "2026-05-18T12:00:02Z"
    assert "Folded 2 repeated work run snapshots" in summary["message"]


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
