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
    assert diagnosis["evidencePaths"][0] == "raw/backend.stderr.log"
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
    assert "启动流程 6/10" in diagnosis["startupTrace"]["summary"]
    assert "缺少：前端依赖与构建、后端依赖、浏览器窗口、监督器" in diagnosis["startupTrace"]["summary"]
    assert diagnosis["keyEntries"][0]["path"] == "summary.json"
    assert diagnosis["keyEntries"][1]["path"] == "package_index.json"
    assert diagnosis["keyEntries"][2]["path"] == "raw/desktop-entry-vbs.log"
    assert any(item["path"] == "raw/backend.stderr.log" for item in diagnosis["keyEntries"])
    assert "logs/runtime_scenes/20260518T120000Z__scene-diagnosis-error/summary.json" in diagnosis["agentNextStep"]
    assert "issueState.activeClusterCount" in diagnosis["agentNextStep"]
    assert "evidence_paths" in diagnosis["agentNextStep"]
    assert "rawRefs" not in diagnosis["agentNextStep"]


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


def test_runtime_scene_diagnosis_names_legacy_model_discovery_auth_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-model-discovery-auth"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "backend",
                "phase": "api",
                "event_code": "backend.api.request",
                "level": "warning",
                "outcome": "client_error",
                "message": "POST /api/config/discover-models -> 422",
                "fields": {
                    "method": "POST",
                    "path": "/api/config/discover-models",
                    "pathTemplate": "/api/config/discover-models",
                    "statusCode": 422,
                },
                "raw_refs": [{"path": "raw/backend.api.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:02Z",
                "seq": 2,
                "component": "browser_page",
                "phase": "api",
                "event_code": "browser.api.request_failed",
                "level": "error",
                "outcome": "observed",
                "message": "POST /api/config/discover-models failed (422)",
                "fields": {
                    "pageInstanceId": "page-a",
                    "endpoint": "/api/config/discover-models",
                    "method": "POST",
                    "status": 422,
                    "failureKind": "http",
                    "failureMessage": "认证失败（HTTP 401），请检查 API Key。密钥来源：未找到环境变量 OPENAI_API_KEY。",
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
        ],
        status="stopped",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    issue_state = diagnosis["issueState"]
    active_cluster = issue_state["firstActiveCluster"]
    assert diagnosis["severity"] == "error"
    assert issue_state["historicalClusterCount"] == 0
    assert issue_state["historicalClusters"] == []
    assert issue_state["controlSignalCount"] == 0
    assert diagnosis["firstSignal"]["eventCode"] == "config.model_discovery.failed"
    assert diagnosis["firstSignal"]["sourceEventCode"] == "browser.api.request_failed"
    assert diagnosis["firstSignal"]["diagnosisReason"] == "missing_openai_api_key"
    assert diagnosis["firstSignal"]["diagnosisLabel"] == "配置模型发现失败：缺少 OPENAI_API_KEY"
    assert active_cluster["eventCode"] == "config.model_discovery.failed"
    assert active_cluster["label"] == "配置模型发现失败：缺少 OPENAI_API_KEY"
    assert active_cluster["representativeSignal"]["fields"]["sourceEventCode"] == "browser.api.request_failed"
    assert "配置模型发现失败：缺少 OPENAI_API_KEY" in diagnosis["userSummary"]
    assert "先配置 OPENAI_API_KEY" in diagnosis["agentNextStep"]
    assert diagnosis["evidencePaths"][0] == "raw/browser.telemetry.log"
    assert "请求返回 422" not in diagnosis["userSummary"]

    summary = json.loads((tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}" / "summary.json").read_text(encoding="utf-8"))
    package_index = json.loads((tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}" / "package_index.json").read_text(encoding="utf-8"))
    assert summary["agent_brief"]["primary_issue"] == "config.model_discovery.failed"
    assert "config-model-discovery-failed" in package_index["tags"]
    assert "缺少 OPENAI_API_KEY" in package_index["search_text"]


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


def test_runtime_scene_issue_state_treats_pagehide_get_network_failures_as_control(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-diagnosis-pagehide-fetch"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.100Z",
                "seq": 1,
                "component": "browser_page",
                "phase": "lifecycle",
                "event_code": "browser.page.hide",
                "level": "info",
                "outcome": "observed",
                "message": "Page hide at /supervised-evolution",
                "fields": {
                    "pageInstanceId": "page-a",
                    "pathname": "/supervised-evolution",
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.150Z",
                "seq": 2,
                "component": "browser_page",
                "phase": "api",
                "event_code": "browser.api.network_error",
                "level": "error",
                "outcome": "observed",
                "message": "GET /api/runtime/summary failed",
                "fields": {
                    "pageInstanceId": "page-a",
                    "endpoint": "/api/runtime/summary",
                    "method": "GET",
                    "failureKind": "network",
                    "failureMessage": "Failed to fetch",
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.150Z",
                "seq": 3,
                "component": "browser_page",
                "phase": "api",
                "event_code": "browser.api.network_error",
                "level": "error",
                "outcome": "observed",
                "message": "GET /api/evolution/workspace-snapshot failed",
                "fields": {
                    "pageInstanceId": "page-a",
                    "endpoint": "/api/evolution/workspace-snapshot",
                    "method": "GET",
                    "failureKind": "network",
                    "failureMessage": "Failed to fetch",
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:02.200Z",
                "seq": 4,
                "component": "browser_page",
                "phase": "page",
                "event_code": "browser.page.snapshot",
                "level": "info",
                "outcome": "observed",
                "message": "Page snapshot for /supervised-evolution",
                "fields": {
                    "pageInstanceId": "page-b",
                    "pathname": "/supervised-evolution",
                    "readyState": "complete",
                    "mainTextLength": 4551,
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    issue_state = diagnosis["issueState"]
    assert diagnosis["severity"] == "info"
    assert issue_state["activeErrorCount"] == 0
    assert issue_state["activeClusterCount"] == 0
    assert issue_state["controlSignalCount"] == 2
    assert issue_state["activeClusters"] == []
    assert "控制类信号" in diagnosis["userSummary"]
    assert "browser.api.network_error" not in diagnosis["agentNextStep"]


def test_runtime_scene_issue_state_treats_recovered_route_chunk_errors_as_historical(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-diagnosis-route-chunk-recovered"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.000Z",
                "seq": 1,
                "component": "browser_page",
                "phase": "recovery",
                "event_code": "browser.route_chunk_recovery.reload_requested",
                "level": "warning",
                "outcome": "observed",
                "message": "Stale route chunk detected; requesting a page reload.",
                "fields": {
                    "pageInstanceId": "page-old",
                    "pathname": "/chat",
                    "routeTarget": "/chat",
                    "reason": "built_asset_resource_error",
                    "resourceUrl": "http://127.0.0.1:8000/assets/old-route.js",
                    "reloadRequested": True,
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.010Z",
                "seq": 2,
                "component": "browser_page",
                "phase": "error",
                "event_code": "browser.resource.error",
                "level": "error",
                "outcome": "observed",
                "message": "Resource failed to load: http://127.0.0.1:8000/assets/old-route.js",
                "fields": {
                    "pageInstanceId": "page-old",
                    "pathname": "/chat",
                    "resourceUrl": "http://127.0.0.1:8000/assets/old-route.js",
                    "tagName": "link",
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.030Z",
                "seq": 3,
                "component": "browser_page",
                "phase": "error",
                "event_code": "browser.resource.error",
                "level": "error",
                "outcome": "observed",
                "message": "Resource failed to load: http://127.0.0.1:8000/assets/old-panel.js",
                "fields": {
                    "pageInstanceId": "page-old",
                    "pathname": "/chat",
                    "resourceUrl": "http://127.0.0.1:8000/assets/old-panel.js",
                    "tagName": "script",
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.100Z",
                "seq": 4,
                "component": "browser_page",
                "phase": "console",
                "event_code": "browser.console.error",
                "level": "error",
                "outcome": "observed",
                "message": "Error handled by React Router default ErrorBoundary: | TypeError: Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/old-route.js",
                "fields": {
                    "pageInstanceId": "page-old",
                    "pathname": "/chat",
                    "argsPreview": "TypeError: Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/old-route.js",
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.200Z",
                "seq": 5,
                "component": "browser_page",
                "phase": "lifecycle",
                "event_code": "browser.page.hide",
                "level": "info",
                "outcome": "observed",
                "message": "Page hide at /chat",
                "fields": {"pageInstanceId": "page-old", "pathname": "/chat"},
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.800Z",
                "seq": 6,
                "component": "browser_page",
                "phase": "navigation",
                "event_code": "browser.route.changed",
                "level": "info",
                "outcome": "observed",
                "message": "React route changed to /chat",
                "fields": {
                    "pageInstanceId": "page-new",
                    "pathname": "/chat",
                    "readyState": "complete",
                    "mainTextLength": 900,
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:02.300Z",
                "seq": 7,
                "component": "browser_page",
                "phase": "page",
                "event_code": "browser.page.snapshot",
                "level": "info",
                "outcome": "observed",
                "message": "Page snapshot for /chat",
                "fields": {
                    "pageInstanceId": "page-new",
                    "pathname": "/chat",
                    "readyState": "complete",
                    "mainTextLength": 1200,
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    issue_state = diagnosis["issueState"]
    assert diagnosis["severity"] == "info"
    assert issue_state["activeErrorCount"] == 0
    assert issue_state["activeWarningCount"] == 0
    assert issue_state["activeClusterCount"] == 0
    assert issue_state["historicalErrorCount"] == 3
    assert issue_state["historicalWarningCount"] == 1
    assert issue_state["historicalClusterCount"] == 3
    assert issue_state["historicalClusters"][0]["eventCode"] == "browser.resource.error"
    assert issue_state["historicalClusters"][0]["repeatCount"] == 2
    assert {cluster["eventCode"] for cluster in issue_state["historicalClusters"]} >= {
        "browser.console.error",
        "browser.resource.error",
        "browser.route_chunk_recovery.reload_requested",
    }

    summary = json.loads((tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}" / "summary.json").read_text(encoding="utf-8"))
    assert summary["agent_brief"]["diagnosis_status"] == "resolved"
    assert summary["agent_brief"]["primary_issue"] == "none"


def test_runtime_scene_issue_state_treats_reopened_session_stream_error_as_historical(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-diagnosis-session-stream-recovered"
    scene_dir = _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.000Z",
                "seq": 1,
                "component": "browser_page",
                "phase": "session_stream",
                "event_code": "browser.session_stream.error",
                "level": "warning",
                "outcome": "observed",
                "message": "Session detail stream reported an error.",
                "fields": {"sessionId": "session-a", "readyState": 2},
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            }
        ],
        status="running",
    )
    _write_jsonl(
        scene_dir / "events" / "browser_page.jsonl",
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.000Z",
                "seq": 1,
                "component": "browser_page",
                "phase": "session_stream",
                "event_code": "browser.session_stream.error",
                "level": "warning",
                "outcome": "observed",
                "message": "Session detail stream reported an error.",
                "fields": {"sessionId": "session-a", "readyState": 2},
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:02.000Z",
                "seq": 2,
                "component": "browser_page",
                "phase": "session_stream",
                "event_code": "browser.session_stream.opened",
                "level": "info",
                "outcome": "observed",
                "message": "Session detail stream opened.",
                "fields": {"sessionId": "session-a"},
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:02.200Z",
                "seq": 3,
                "component": "browser_page",
                "phase": "session_stream",
                "event_code": "browser.session_stream.snapshot_applied",
                "level": "info",
                "outcome": "observed",
                "message": "Session detail stream snapshot was applied to the UI cache.",
                "fields": {"sessionId": "session-a", "reason": "final", "appliedCount": 1},
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
        ],
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    issue_state = detail["packageDiagnosis"]["issueState"]
    assert detail["packageDiagnosis"]["severity"] == "info"
    assert issue_state["activeWarningCount"] == 0
    assert issue_state["activeClusterCount"] == 0
    assert issue_state["historicalWarningCount"] == 1
    assert issue_state["historicalClusterCount"] == 1
    assert issue_state["historicalClusters"][0]["eventCode"] == "browser.session_stream.error"


def test_runtime_scene_issue_state_keeps_foreground_post_network_failures_active(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-diagnosis-post-network"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.100Z",
                "seq": 1,
                "component": "browser_page",
                "phase": "lifecycle",
                "event_code": "browser.page.hide",
                "level": "info",
                "outcome": "observed",
                "message": "Page hide at /supervised-evolution",
                "fields": {"pageInstanceId": "page-a"},
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.150Z",
                "seq": 2,
                "component": "browser_page",
                "phase": "api",
                "event_code": "browser.api.network_error",
                "level": "error",
                "outcome": "observed",
                "message": "POST /api/evolution/runs failed",
                "fields": {
                    "pageInstanceId": "page-a",
                    "endpoint": "/api/evolution/runs",
                    "method": "POST",
                    "failureKind": "network",
                    "failureMessage": "Failed to fetch",
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    issue_state = detail["packageDiagnosis"]["issueState"]
    assert issue_state["activeErrorCount"] == 1
    assert issue_state["activeClusterCount"] == 1
    assert issue_state["controlSignalCount"] == 0
    assert issue_state["firstActiveCluster"]["eventCode"] == "browser.api.network_error"


def test_runtime_scene_issue_state_tracks_tool_registry_policy_signals(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    _seed_scene(
        tmp_path,
        "scene-diagnosis-policy-block",
        [
            {
                "runtime_scene_id": "scene-diagnosis-policy-block",
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "tool_registry",
                "phase": "registry",
                "event_code": "tool_registry.test.blocked",
                "level": "warning",
                "outcome": "blocked",
                "message": "Built-in tool test was blocked by safe test policy.",
                "fields": {
                    "source": "built_in",
                    "status": "blocked",
                    "testPolicy": "blocked",
                    "toolId": "shell_exec",
                },
            }
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail("scene-diagnosis-policy-block")

    diagnosis = detail["packageDiagnosis"]
    issue_state = diagnosis["issueState"]
    assert diagnosis["severity"] == "warning"
    assert issue_state["policySignalCount"] == 1
    assert issue_state["policyClusterCount"] == 1
    assert issue_state["activeClusterCount"] == 0
    assert issue_state["firstPolicyCluster"]["eventCode"] == "tool_registry.test.blocked"
    assert diagnosis["firstSignal"]["eventCode"] == "tool_registry.test.blocked"
    assert "控制/策略问题簇" in diagnosis["userSummary"]
    assert "原始记录包含 1 个控制/策略信号" in diagnosis["userSummary"]
    assert "issueState.policyClusterCount" in diagnosis["agentNextStep"]
    assert "testPolicy" in diagnosis["agentNextStep"]
    assert "不要按业务故障继续追恢复链" in diagnosis["agentNextStep"]
    assert "issueState.activeClusterCount" not in diagnosis["agentNextStep"]


def test_runtime_scene_issue_state_treats_resource_lease_conflict_as_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-diagnosis-lease-conflict"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.000Z",
                "seq": 1,
                "component": "backend",
                "phase": "api",
                "event_code": "backend.api.request",
                "level": "warning",
                "outcome": "client_error",
                "message": "POST /api/sessions/{session_id}/messages -> 409",
                "fields": {
                    "method": "POST",
                    "path": "/api/sessions/session-a/messages",
                    "pathTemplate": "/api/sessions/{session_id}/messages",
                    "statusCode": 409,
                },
                "raw_refs": [{"path": "raw/backend.api.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.500Z",
                "seq": 2,
                "component": "browser_page",
                "phase": "api",
                "event_code": "browser.api.request_failed",
                "level": "error",
                "outcome": "observed",
                "message": "POST /api/sessions/session-a/messages failed (409)",
                "fields": {
                    "endpoint": "/api/sessions/session-a/messages",
                    "method": "POST",
                    "status": 409,
                    "failureKind": "http",
                    "failureMessage": (
                        "当前资源正在被另一条运行占用，请等待它收束后再继续。"
                        "Resource lease conflict on worktree_write with web-supervised-run-1."
                    ),
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01.700Z",
                "seq": 3,
                "component": "browser_page",
                "phase": "chat_submit",
                "event_code": "browser.chat_submit.request_failed",
                "level": "error",
                "outcome": "observed",
                "message": "Direct chat submit request failed before the backend accepted the turn.",
                "fields": {
                    "sessionId": "session-a",
                    "errorMessage": "Resource lease conflict on worktree_write with web-supervised-run-1.",
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    issue_state = diagnosis["issueState"]
    assert diagnosis["severity"] == "warning"
    assert issue_state["activeClusterCount"] == 0
    assert issue_state["policySignalCount"] == 3
    assert issue_state["policyClusterCount"] == 3
    assert diagnosis["firstSignal"]["eventCode"] in {"backend.api.request", "browser.api.request_failed"}
    assert issue_state["firstPolicyCluster"]["eventCode"] in {"backend.api.request", "browser.api.request_failed"}
    assert "控制/策略问题簇" in diagnosis["userSummary"]
    assert "issueState.policyClusterCount" in diagnosis["agentNextStep"]


def test_runtime_scene_treats_transient_agent_directory_slow_as_policy_observation(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-agent-directory-transient-slow"
    slow_event = {
        "runtime_scene_id": scene_id,
        "component": "agent_directory",
        "phase": "list_agents",
        "event_code": "agent_directory.list_agents.slow",
        "level": "warning",
        "outcome": "observed",
        "message": "Agent directory list_agents was slow.",
        "fields": {
            "rawAgentCount": 32,
            "returnedAgentCount": 32,
            "timingsMs": {"hydrate": 4917.4, "total": 5104.7},
            "hydrationTimingsMs": {"group_context_events": 3233.7},
            "slowestStage": "hydrate",
            "slowestHydrationStage": "group_context_events",
        },
        "raw_refs": [{"path": "events/agent_directory.jsonl", "tail_lines": 80}],
    }
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {**slow_event, "ts": "2026-05-18T12:00:01Z", "seq": 1},
            {**slow_event, "ts": "2026-05-18T12:00:02Z", "seq": 2},
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    issue_state = diagnosis["issueState"]
    assert diagnosis["severity"] == "warning"
    assert issue_state["activeClusterCount"] == 0
    assert issue_state["policyClusterCount"] == 1
    assert issue_state["firstPolicyCluster"]["eventCode"] == "agent_directory.list_agents.slow"
    assert "issueState.policyClusterCount" in diagnosis["agentNextStep"]
    summary = json.loads(
        (
            tmp_path
            / "logs"
            / "runtime_scenes"
            / f"20260518T120000Z__{scene_id}"
            / "summary.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["agent_brief"]["diagnosis_status"] == "policy_only"
    assert summary["agent_brief"]["needs_action"] is False


def test_runtime_scene_keeps_repeated_agent_directory_slow_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-agent-directory-repeated-slow"
    rows = []
    for index in range(3):
        rows.append(
            {
                "runtime_scene_id": scene_id,
                "ts": f"2026-05-18T12:00:0{index + 1}Z",
                "seq": index + 1,
                "component": "agent_directory",
                "phase": "list_agents",
                "event_code": "agent_directory.list_agents.slow",
                "level": "warning",
                "outcome": "observed",
                "message": "Agent directory list_agents was slow.",
                "fields": {
                    "rawAgentCount": 32,
                    "returnedAgentCount": 32,
                    "timingsMs": {"hydrate": 4100.0, "total": 4300.0},
                    "hydrationTimingsMs": {"group_context_events": 3000.0},
                },
                "raw_refs": [{"path": "events/agent_directory.jsonl", "tail_lines": 80}],
            }
        )
    _seed_scene(tmp_path, scene_id, rows, status="running")

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    issue_state = detail["packageDiagnosis"]["issueState"]
    assert issue_state["activeClusterCount"] == 1
    assert issue_state["policyClusterCount"] == 0
    assert issue_state["activeClusters"][0]["eventCode"] == "agent_directory.list_agents.slow"
    assert issue_state["activeClusters"][0]["repeatCount"] == 3


def test_runtime_scene_treats_runtime_status_probe_404_as_operational_noise(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-runtime-status-probe"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "backend",
                "phase": "api",
                "event_code": "backend.api.request",
                "level": "warning",
                "outcome": "client_error",
                "message": "GET /{full_path:path} -> 404",
                "fields": {
                    "method": "GET",
                    "path": "/api/runtime/status",
                    "pathTemplate": "/{full_path:path}",
                    "statusCode": 404,
                },
                "raw_refs": [{"path": "raw/backend.api.log", "tail_lines": 80}],
            }
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    assert diagnosis["severity"] == "info"
    assert diagnosis["issueState"]["activeClusterCount"] == 0
    assert diagnosis["issueState"]["policyClusterCount"] == 0


def test_runtime_scene_treats_testclient_404_as_operational_noise(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-testclient-404"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "backend",
                "phase": "api",
                "event_code": "backend.api.request",
                "level": "warning",
                "outcome": "client_error",
                "message": "GET /api/memory/knowledge-graph/node-detail -> 404",
                "fields": {
                    "method": "GET",
                    "path": "/api/memory/knowledge-graph/node-detail",
                    "pathTemplate": "/api/memory/knowledge-graph/node-detail",
                    "statusCode": 404,
                    "client": "testclient",
                },
                "raw_refs": [{"path": "raw/backend.api.log", "tail_lines": 80}],
            }
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    assert diagnosis["severity"] == "info"
    assert diagnosis["issueState"]["activeClusterCount"] == 0
    assert diagnosis["issueState"]["policyClusterCount"] == 0


def test_runtime_scene_keeps_testclient_500_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-testclient-500"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "backend",
                "phase": "api",
                "event_code": "backend.api.request",
                "level": "error",
                "outcome": "failed",
                "message": "GET /api/memory/knowledge-graph/node-detail -> 500",
                "fields": {
                    "method": "GET",
                    "path": "/api/memory/knowledge-graph/node-detail",
                    "pathTemplate": "/api/memory/knowledge-graph/node-detail",
                    "statusCode": 500,
                    "client": "testclient",
                },
                "raw_refs": [{"path": "raw/backend.api.log", "tail_lines": 80}],
            }
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    assert diagnosis["severity"] == "error"
    assert diagnosis["issueState"]["activeClusterCount"] == 1
    assert diagnosis["issueState"]["activeClusters"][0]["eventCode"] == "backend.api.request"


def test_runtime_scene_component_fallback_evidence_path_matches_event_file_name(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-component-fallback-path"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "evolution_service",
                "phase": "workspace_snapshot",
                "event_code": "evolution.workspace_snapshot.slow",
                "level": "warning",
                "outcome": "observed",
                "message": "Evolution workspace snapshot was slow.",
                "fields": {"timingsMs": {"total": 2000.0}},
                "raw_refs": [],
            }
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    assert diagnosis["firstSignal"]["rawRefs"] == [
        {"path": "events/evolution_service.jsonl", "tail_lines": 80}
    ]
    assert diagnosis["evidencePaths"][0] == "events/evolution_service.jsonl"


def test_runtime_scene_resolved_agent_model_references_clear_active_unresolved_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-agent-model-reference-recovered"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "agent_config",
                "phase": "model_binding",
                "event_code": "agent_config.unresolved_model_reference",
                "level": "warning",
                "outcome": "observed",
                "message": "Agent LLM binding references a model id that is not present in the model library.",
                "fields": {
                    "agentId": "agent-knowledge-steward",
                    "slot": "dialogue",
                    "modelId": "generated_xiaomi_mimo_v2_5_cdff497b2d9b",
                },
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:02Z",
                "seq": 2,
                "component": "agent_config",
                "phase": "model_binding",
                "event_code": "agent_config.model_references.resolved",
                "level": "info",
                "outcome": "resolved",
                "message": "Agent LLM binding model references are resolved.",
                "fields": {"unresolvedCount": 0},
            },
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    issue_state = diagnosis["issueState"]
    assert diagnosis["severity"] == "info"
    assert issue_state["activeClusterCount"] == 0
    assert issue_state["historicalClusterCount"] == 1
    assert issue_state["historicalClusters"][0]["eventCode"] == "agent_config.unresolved_model_reference"


def test_runtime_scene_issue_state_keeps_unknown_http_409_active(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-diagnosis-unknown-409"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "browser_page",
                "phase": "api",
                "event_code": "browser.api.request_failed",
                "level": "error",
                "outcome": "observed",
                "message": "POST /api/sessions/session-a/messages failed (409)",
                "fields": {
                    "endpoint": "/api/sessions/session-a/messages",
                    "method": "POST",
                    "status": 409,
                    "failureKind": "http",
                    "failureMessage": "Unknown conflict while saving the turn.",
                },
                "raw_refs": [{"path": "raw/browser.telemetry.log", "tail_lines": 80}],
            },
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    issue_state = detail["packageDiagnosis"]["issueState"]
    assert issue_state["activeErrorCount"] == 1
    assert issue_state["activeClusterCount"] == 1
    assert issue_state["policySignalCount"] == 0
    assert issue_state["firstActiveCluster"]["eventCode"] == "browser.api.request_failed"


def test_runtime_scene_diagnosis_keeps_memory_status_mirror_out_of_active_clusters(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-diagnosis-memory-mirror"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "tool_executor",
                "phase": "execute",
                "event_code": "tool.execute.degraded",
                "level": "warning",
                "outcome": "degraded",
                "message": "Tool execution degraded.",
                "fields": {"toolName": "shell", "status": "degraded", "runId": "run-tool-1"},
                "raw_refs": [{"path": "events/tool_executor.jsonl", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:02Z",
                "seq": 2,
                "component": "agent_memory",
                "phase": "memory",
                "event_code": "memory.event_written",
                "level": "info",
                "outcome": "written",
                "message": "Agent memory event was written.",
                "fields": {
                    "sourceEventCode": "tool.execute.degraded",
                    "status": "degraded",
                    "runId": "run-tool-1",
                },
                "raw_refs": [{"path": "events/agent_memory.jsonl", "tail_lines": 80}],
            },
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    issue_state = diagnosis["issueState"]
    assert diagnosis["severity"] == "warning"
    assert issue_state["activeClusterCount"] == 1
    assert issue_state["activeWarningCount"] == 1
    assert issue_state["activeClusters"][0]["eventCode"] == "tool.execute.degraded"
    active_codes = {cluster["eventCode"] for cluster in issue_state["activeClusters"]}
    assert "memory.event_written" not in active_codes
    assert diagnosis["firstSignal"]["eventCode"] == "tool.execute.degraded"

    summary = json.loads((tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}" / "summary.json").read_text(encoding="utf-8"))
    assert summary["event_counts"]["warnings"] == 1
    assert summary["agent_brief"]["diagnosis_status"] == "active_issue"
    assert summary["agent_brief"]["primary_issue"] == "tool.execute.degraded"


def test_runtime_scene_busy_command_is_actionable_policy_not_active_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-diagnosis-busy-command"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "runtime_manager",
                "phase": "command",
                "event_code": "command.failed",
                "level": "error",
                "outcome": "failed",
                "message": "Runtime manager command event: command.failed",
                "fields": {
                    "commandId": "cmd-self-1",
                    "type": "start_self_evolution_run",
                    "message": "当前已经有一轮网页自进化在运行或暂停中，请先继续或终止这一轮。",
                },
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:02Z",
                "seq": 2,
                "component": "runtime_manager",
                "phase": "queue",
                "event_code": "command_queue.command_result_written",
                "level": "error",
                "outcome": "failed",
                "message": "Runtime manager queue event: command_queue.command_result_written",
                "fields": {
                    "commandId": "cmd-self-1",
                    "ok": False,
                    "completed": True,
                    "errorType": "SelfEvolutionRunBusyError",
                    "message": "当前已经有一轮网页自进化在运行或暂停中，请先继续或终止这一轮。",
                },
            },
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    issue_state = diagnosis["issueState"]
    assert diagnosis["severity"] == "warning"
    assert issue_state["activeClusterCount"] == 0
    assert issue_state["policySignalCount"] == 2
    assert issue_state["policyClusterCount"] == 2
    assert diagnosis["firstSignal"]["eventCode"] == "command.failed"
    assert "控制/策略问题簇" in diagnosis["userSummary"]
    assert "issueState.policyClusterCount" in diagnosis["agentNextStep"]
    assert "issueState.activeClusterCount" not in diagnosis["agentNextStep"]

    summary = json.loads((tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}" / "summary.json").read_text(encoding="utf-8"))
    assert summary["agent_brief"]["diagnosis_status"] == "policy_only"
    assert summary["agent_brief"]["actionability"] == "policy_acknowledge_only"
    assert summary["agent_brief"]["needs_action"] is False


def test_runtime_scene_self_evolution_busy_manager_event_is_policy_not_active_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-diagnosis-self-evolution-busy-manager"
    command_id = "cmd-self-2"
    busy_message = "当前已经有一轮网页自进化在运行或暂停中，请先继续或终止这一轮。"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "runtime_manager",
                "phase": "command",
                "event_code": "command.failed",
                "level": "error",
                "outcome": "failed",
                "message": "Runtime manager command event: command.failed",
                "fields": {
                    "commandId": command_id,
                    "type": "start_self_evolution_run",
                    "message": busy_message,
                },
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:02Z",
                "seq": 2,
                "component": "self_evolution_run",
                "phase": "runtime_manager",
                "event_code": "self_evolution_run.manager.start_self_evolution_run.failed",
                "level": "error",
                "outcome": "failed",
                "message": busy_message,
                "fields": {
                    "commandId": command_id,
                    "commandType": "start_self_evolution_run",
                    "errorType": "SelfEvolutionRunBusyError",
                },
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:03Z",
                "seq": 3,
                "component": "runtime_manager",
                "phase": "queue",
                "event_code": "command_queue.command_result_written",
                "level": "error",
                "outcome": "failed",
                "message": "Runtime manager queue event: command_queue.command_result_written",
                "fields": {
                    "commandId": command_id,
                    "ok": False,
                    "completed": True,
                    "errorType": "SelfEvolutionRunBusyError",
                    "message": busy_message,
                },
            },
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    issue_state = diagnosis["issueState"]
    assert diagnosis["severity"] == "warning"
    assert issue_state["activeClusterCount"] == 0
    assert issue_state["policySignalCount"] == 3
    assert issue_state["policyClusterCount"] == 3
    assert issue_state["firstPolicyCluster"]["eventCode"] == "command.failed"
    assert diagnosis["firstSignal"]["eventCode"] == "command.failed"

    summary = json.loads((tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}" / "summary.json").read_text(encoding="utf-8"))
    assert summary["agent_brief"]["diagnosis_status"] == "policy_only"
    assert summary["agent_brief"]["needs_action"] is False


def test_runtime_scene_conversation_artifact_failure_wraps_image2_root_cause(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-diagnosis-image2-wrapper"
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "image2",
                "phase": "generate",
                "event_code": "image2.generate.started",
                "level": "info",
                "outcome": "running",
                "message": "image2.generate.started",
                "fields": {"sessionId": "session-image2", "model": "gpt-image-1.5"},
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:02Z",
                "seq": 2,
                "component": "conversation",
                "phase": "assistant_artifact",
                "event_code": "conversation.assistant_artifact",
                "level": "error",
                "outcome": "failed",
                "message": "assistant: 图片生成失败：image2 provider returned 404: <html>",
                "fields": {
                    "sessionId": "session-image2",
                    "role": "assistant",
                    "status": "failed",
                    "contentPreview": "图片生成失败：image2 provider returned 404: <html>",
                },
                "raw_refs": [{"path": "conversations/session-image2.jsonl", "tail_lines": 80}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:03Z",
                "seq": 3,
                "component": "image2",
                "phase": "generate",
                "event_code": "image2.generate.failed",
                "level": "error",
                "outcome": "failed",
                "message": "image2.generate.failed",
                "fields": {
                    "errorType": "RuntimeError",
                    "errorPreview": "image2 provider returned 404: <html>",
                    "durationMs": 391,
                },
                "raw_refs": [{"path": "artifacts/session-image2-image2.jsonl", "tail_lines": 80}],
            },
        ],
        status="running",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    issue_state = diagnosis["issueState"]
    assert diagnosis["severity"] == "error"
    assert issue_state["activeClusterCount"] == 1
    assert issue_state["activeErrorCount"] == 1
    assert issue_state["controlSignalCount"] == 1
    assert issue_state["firstActiveCluster"]["eventCode"] == "image2.generate.failed"
    assert diagnosis["firstSignal"]["eventCode"] == "image2.generate.failed"
    assert diagnosis["evidencePaths"][0] == "artifacts/session-image2-image2.jsonl"

    summary = json.loads((tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}" / "summary.json").read_text(encoding="utf-8"))
    assert summary["agent_brief"]["diagnosis_status"] == "active_issue"
    assert summary["agent_brief"]["primary_issue"] == "image2.generate.failed"


def test_runtime_scene_startup_wrappers_do_not_duplicate_specific_frontend_root_cause(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-startup-wrapper-frontend-root"
    command_id = "cmd-open-workbench-1"
    frontend_error = (
        "npm run build failed with exit code 1.\n"
        "frontend.build.failed\n"
        "src/routes/ResearchFlowCanvasRoute.tsx(1475,45): error TS2552: "
        "Cannot find name 'ORGANIZATION_CANVAS_KIND'."
    )
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "frontend",
                "phase": "build",
                "event_code": "frontend.build.failed",
                "level": "error",
                "outcome": "failed",
                "message": "Frontend build failed.",
                "fields": {"exitCode": 1, "reason": "frontend sources changed"},
                "raw_refs": [{"path": "raw/frontend.build.log", "tail_lines": 120}],
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:02Z",
                "seq": 2,
                "component": "launcher",
                "phase": "session",
                "event_code": "runtime.scene.startup.failed",
                "level": "error",
                "outcome": "failed",
                "message": "Managed runtime scene startup failed.",
                "fields": {"reason": frontend_error},
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:03Z",
                "seq": 3,
                "component": "runtime_manager",
                "phase": "command",
                "event_code": "command.failed",
                "level": "error",
                "outcome": "failed",
                "message": "Runtime manager command event: command.failed",
                "fields": {
                    "commandId": command_id,
                    "type": "open_workbench",
                    "message": f"{frontend_error}\nLauncher exit code: 1",
                },
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:04Z",
                "seq": 4,
                "component": "runtime_manager",
                "phase": "queue",
                "event_code": "command_queue.command_result_written",
                "level": "error",
                "outcome": "failed",
                "message": "Runtime manager queue event: command_queue.command_result_written",
                "fields": {
                    "commandId": command_id,
                    "ok": False,
                    "completed": True,
                    "errorType": "RuntimeError",
                    "message": frontend_error,
                },
            },
        ],
        status="failed",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    issue_state = diagnosis["issueState"]
    assert diagnosis["severity"] == "error"
    assert issue_state["activeClusterCount"] == 1
    assert issue_state["activeErrorCount"] == 1
    assert issue_state["controlSignalCount"] == 3
    assert issue_state["policySignalCount"] == 0
    assert issue_state["firstActiveCluster"]["eventCode"] == "frontend.build.failed"
    assert diagnosis["firstSignal"]["eventCode"] == "frontend.build.failed"
    active_codes = {cluster["eventCode"] for cluster in issue_state["activeClusters"]}
    assert "runtime.scene.startup.failed" not in active_codes
    assert "command.failed" not in active_codes
    assert "command_queue.command_result_written" not in active_codes

    summary = json.loads((tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}" / "summary.json").read_text(encoding="utf-8"))
    assert summary["agent_brief"]["diagnosis_status"] == "active_issue"
    assert summary["agent_brief"]["primary_issue"] == "frontend.build.failed"


def test_runtime_scene_startup_failure_keeps_launcher_root_when_no_specific_event_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-startup-launcher-root"
    command_id = "cmd-open-workbench-2"
    reason = (
        "The term 'Get-InventoryPythonPath' is not recognized as the name of a cmdlet, "
        "function, script file, or operable program."
    )
    _seed_scene(
        tmp_path,
        scene_id,
        [
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:01Z",
                "seq": 1,
                "component": "launcher",
                "phase": "session",
                "event_code": "runtime.scene.startup.failed",
                "level": "error",
                "outcome": "failed",
                "message": "Managed runtime scene startup failed.",
                "fields": {"reason": reason},
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:02Z",
                "seq": 2,
                "component": "runtime_manager",
                "phase": "command",
                "event_code": "command.failed",
                "level": "error",
                "outcome": "failed",
                "message": "Runtime manager command event: command.failed",
                "fields": {
                    "commandId": command_id,
                    "type": "open_workbench",
                    "message": f"Get-InventoryPythonPath : {reason}\nLauncher exit code: 1",
                },
            },
            {
                "runtime_scene_id": scene_id,
                "ts": "2026-05-18T12:00:03Z",
                "seq": 3,
                "component": "runtime_manager",
                "phase": "queue",
                "event_code": "command_queue.command_result_written",
                "level": "error",
                "outcome": "failed",
                "message": "Runtime manager queue event: command_queue.command_result_written",
                "fields": {
                    "commandId": command_id,
                    "ok": False,
                    "completed": True,
                    "errorType": "RuntimeError",
                    "message": f"Get-InventoryPythonPath : {reason}",
                },
            },
        ],
        status="failed",
    )

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    diagnosis = detail["packageDiagnosis"]
    issue_state = diagnosis["issueState"]
    assert diagnosis["severity"] == "error"
    assert issue_state["activeClusterCount"] == 1
    assert issue_state["activeErrorCount"] == 1
    assert issue_state["controlSignalCount"] == 2
    assert issue_state["policySignalCount"] == 0
    assert issue_state["firstActiveCluster"]["eventCode"] == "startup.launcher.command_missing"
    assert issue_state["firstActiveCluster"]["label"] == "启动失败：PowerShell 函数缺失 Get-InventoryPythonPath"
    assert diagnosis["firstSignal"]["eventCode"] == "startup.launcher.command_missing"
    assert diagnosis["firstSignal"]["sourceEventCode"] == "runtime.scene.startup.failed"
    assert diagnosis["firstSignal"]["diagnosisReason"] == "powershell_command_missing"
    assert "Get-InventoryPythonPath" in diagnosis["agentNextStep"]

    summary = json.loads((tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}" / "summary.json").read_text(encoding="utf-8"))
    assert summary["agent_brief"]["diagnosis_status"] == "active_issue"
    assert summary["agent_brief"]["primary_issue"] == "startup.launcher.command_missing"


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
    summary = json.loads((tmp_path / "logs" / "runtime_scenes" / "20260518T120000Z__scene-diagnosis-historical-cluster" / "summary.json").read_text(encoding="utf-8"))
    assert summary["agent_brief"]["diagnosis_status"] == "resolved"
    assert summary["agent_brief"]["primary_issue"] == "none"


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
    summary = json.loads((tmp_path / "logs" / "runtime_scenes" / "20260518T120000Z__scene-diagnosis-clean" / "summary.json").read_text(encoding="utf-8"))
    assert summary["agent_brief"]["diagnosis_status"] == "healthy"
    assert summary["agent_brief"]["primary_issue"] == "none"


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
    assert diagnosis["startupTrace"]["summary"] == "启动流程 10/10，状态 running。"
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


def test_runtime_scene_diagnosis_exposes_compact_work_run_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    scene_id = "scene-work-run-summary"
    rows: list[dict] = []
    for index in range(7):
        rows.append(
            {
                "runtime_scene_id": scene_id,
                "ts": f"2026-05-18T12:00:0{index}Z",
                "seq": index + 1,
                "component": "work_run",
                "phase": "state",
                "event_code": "work_run.snapshot.persisted",
                "level": "info",
                "outcome": "succeeded",
                "message": "Work run snapshot persisted: self/run-busy running",
                "fields": {
                    "runKind": "self",
                    "runId": "run-busy",
                    "status": "running",
                    "phase": "reading",
                    "activeRunId": "run-busy",
                    "runtimeStatus": "error",
                    "snapshotPath": "C:\\workspace\\.runtime\\run-busy.json",
                },
            }
        )
    rows.append(
        {
            "runtime_scene_id": scene_id,
            "ts": "2026-05-18T12:00:08Z",
            "seq": 8,
            "component": "work_run",
            "phase": "state",
            "event_code": "work_run.snapshot.persisted",
            "level": "info",
            "outcome": "succeeded",
            "message": "Work run snapshot persisted: chat_turn/run-done completed",
            "fields": {
                "runKind": "chat_turn",
                "runId": "run-done",
                "status": "completed",
                "phase": "done",
            },
        }
    )
    _seed_scene(tmp_path, scene_id, rows, status="running")

    detail = runtime_scene_service.get_runtime_scene_detail(scene_id)

    work_runs = detail["packageDiagnosis"]["workRunSummary"]
    assert work_runs["eventsPath"] == "timeline.jsonl"
    assert work_runs["snapshotEventCount"] == 8
    assert work_runs["runCount"] == 2
    assert work_runs["activeRunCount"] == 1
    assert work_runs["highFrequencyRunCount"] == 1
    assert work_runs["activeRuns"][0]["runId"] == "run-busy"
    assert work_runs["highFrequencyRuns"][0]["snapshotCount"] == 7

    summary = json.loads((tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}" / "summary.json").read_text(encoding="utf-8"))
    assert summary["agent_brief"]["work_run_focus"]["active_run_count"] == 1
    assert summary["agent_brief"]["work_run_focus"]["high_frequency_run_count"] == 1
    assert summary["agent_brief"]["work_run_focus"]["first_active_run"]["runId"] == "run-busy"


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
