"""Structured runtime scene bundles for frontend inspection and agent diagnosis."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from core.web.services.log_diagnostics import analyze_log_content


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_STATE_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "state.json"
MAX_TEXT_CHARS = 200_000
BROWSER_TELEMETRY_RAW_PATH = "raw/browser.telemetry.log"
BROWSER_TELEMETRY_COMPONENT = "browser_page"
BACKEND_API_RAW_PATH = "raw/backend.api.log"
BACKEND_COMPONENT = "backend"
TIMELINE_PATH = "timeline.jsonl"
LIFECYCLE_PATH = "lifecycle.jsonl"
PACKAGE_INDEX_PATH = "package_index.json"
SUMMARY_PATH = "summary.json"
CONVERSATIONS_DIR = "conversations"
AGENT_DIR = "agent"
ARTIFACTS_DIR = "artifacts"
EVENTS_DIR = "events"
RESEARCH_DIR = "research"
RESEARCH_EVENTS_PATH = f"{RESEARCH_DIR}/events.jsonl"
RESEARCH_SUMMARY_PATH = f"{RESEARCH_DIR}/summary.json"
MAX_TELEMETRY_TEXT_CHARS = 4_000
MAX_TELEMETRY_FIELD_TEXT_CHARS = 1_200
MAX_TELEMETRY_FIELD_ITEMS = 24
BROWSER_VISIBILITY_TIMELINE_MIN_SECONDS = 60.0
WORK_RUN_SNAPSHOT_EVENT_CODE = "work_run.snapshot.persisted"
WORK_RUN_SNAPSHOT_SUMMARY_EVENT_CODE = "work_run.snapshot.summary"
MAX_CONVERSATION_TEXT_CHARS = 20_000
REDACTED_FIELD_VALUE = "[redacted]"
LIFECYCLE_INDEX_PHASES = {
    "session",
    "startup",
    "shutdown",
    "build",
    "health",
    "supervision",
    "dependencies",
    "python_dependencies",
    "window",
    "api",
    "desktop_monitor",
    "lifecycle",
    "navigation",
}
SENSITIVE_FIELD_KEYWORDS = (
    "authorization",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "bearer",
)
NON_PROBLEM_NEXT_STATE_KINDS = {
    "assistant_output_edited",
    "user_continues",
    "user_stops",
}
ISSUE_RESOLUTION_OUTCOMES = {
    "fallback",
    "fallback_activated",
    "recovered",
    "resolved",
    "skipped",
    "success",
    "succeeded",
}
ISSUE_IDENTITY_FIELD_KEYS = (
    "activeRunId",
    "commandId",
    "pageInstanceId",
    "runId",
    "sessionId",
    "turnId",
)
BROWSER_TELEMETRY_WRITE_LOCK = Lock()
BACKEND_API_WRITE_LOCK = Lock()
RUNTIME_SCENE_PACKAGE_WRITE_LOCK = Lock()
RAW_LABELS = {
    "raw/desktop-entry.log": "Desktop entry log",
    "raw/desktop-entry-vbs.log": "Desktop entry VBS log",
    "raw/launcher-control.log": "Launcher control log",
    "raw/frontend.build.log": "Frontend build log",
    "raw/backend.stdout.log": "Backend stdout",
    "raw/backend.stderr.log": "Backend stderr",
    BACKEND_API_RAW_PATH: "Backend API events",
    "raw/supervisor.log": "Supervisor log",
    "raw/supervisor.stderr.log": "Supervisor stderr",
    "raw/browser.log": "Browser log",
    BROWSER_TELEMETRY_RAW_PATH: "Browser telemetry",
    TIMELINE_PATH: "Unified timeline",
    LIFECYCLE_PATH: "Lifecycle events",
}
LANGUAGE_BY_SUFFIX = {
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".json": "json",
    ".jsonl": "json",
    ".log": "text",
    ".md": "markdown",
    ".ps1": "powershell",
    ".py": "python",
    ".text": "text",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
}
DISPLAY_NAME_TRIGGER_LABELS = {
    "start": "工作台启动",
    "internal-start": "工作台启动",
    "internal-restart": "工作台重启",
    "restart": "工作台重启",
    "open": "打开工作台",
    "stop": "关闭工作台",
    "shutdown": "关闭工作台",
}
DISPLAY_NAME_STATUS_LABELS = {
    "running": "运行中",
    "starting": "启动中",
    "queued": "等待中",
    "stopping": "停止中",
    "stopped": "已停止",
    "failed": "失败",
    "success": "成功",
    "succeeded": "成功",
}
DISPLAY_NAME_RESULT_LABELS = {
    "explicit_stop": "手动停止",
    "explicit stop": "手动停止",
    "browser_window_closed": "窗口关闭",
    "app window closed": "窗口关闭",
    "startup_failed": "启动失败",
    "backend_exited": "后端退出",
    "state_reconciled": "状态校准",
    "success": "成功",
    "succeeded": "成功",
    "failed": "失败",
}
PACKAGE_INDEX_TRIGGER_TOKENS = {
    "start": "workbench-start",
    "internal-start": "workbench-start",
    "internal-restart": "workbench-restart",
    "restart": "workbench-restart",
    "open": "workbench-open",
    "stop": "workbench-stop",
    "shutdown": "workbench-shutdown",
}
PACKAGE_INDEX_STATUS_TOKENS = {
    "running": "running",
    "starting": "starting",
    "queued": "queued",
    "stopping": "stopping",
    "stopped": "stopped",
    "failed": "failed",
    "success": "success",
    "succeeded": "success",
}
PACKAGE_INDEX_RESULT_TOKENS = {
    "explicit_stop": "manual-stop",
    "explicit stop": "manual-stop",
    "browser_window_closed": "window-closed",
    "app window closed": "window-closed",
    "startup_failed": "startup-failed",
    "backend_exited": "backend-exited",
    "state_reconciled": "state-reconciled",
    "success": "success",
    "succeeded": "success",
    "failed": "failed",
}


def list_runtime_scenes(limit: int = 80) -> list[dict]:
    """Return runtime scene summaries sorted by most recent first."""

    scenes: list[dict] = []
    for scene_dir in _scene_dirs():
        manifest = _load_scene_manifest(scene_dir)
        _repair_runtime_scene_from_reconciliation_history(scene_dir, manifest)
        scene_id = _scene_id(scene_dir, manifest)
        if not scene_id:
            continue
        timeline = _read_scene_timeline(scene_dir)
        raw_files = _list_raw_files(scene_dir)
        conversations = _list_conversation_logs(scene_dir)
        agent_logs = _list_agent_logs(scene_dir)
        artifacts = _list_artifacts(scene_dir)
        event_logs = _list_event_logs(scene_dir)
        research_logs = _list_research_logs(scene_dir)
        package_index = _runtime_scene_package_index(scene_dir, manifest, scene_id)
        _sync_runtime_scene_package_sidecars_if_stale(scene_dir, manifest, package_index)
        severity_summary = _runtime_scene_severity_summary(timeline)
        scenes.append(
            {
                "runtimeSceneId": scene_id,
                "directoryName": scene_dir.name,
                "title": str(manifest.get("title") or scene_dir.name),
                "displayName": package_index["displayName"],
                "packageIndex": package_index,
                "startedAt": package_index["startedAt"],
                "endedAt": str(manifest.get("ended_at") or ""),
                "status": _runtime_scene_status(manifest),
                "result": str(manifest.get("result") or ""),
                "stopReason": str(manifest.get("stop_reason") or ""),
                "trigger": str(manifest.get("trigger") or ""),
                "sessionMode": str(manifest.get("session_mode") or ""),
                "backendStatus": str(((manifest.get("backend") or {}) if isinstance(manifest.get("backend"), dict) else {}).get("health_status") or ""),
                "frontendStatus": str(((manifest.get("frontend") or {}) if isinstance(manifest.get("frontend"), dict) else {}).get("build_status") or ""),
                "browserStatus": str(((manifest.get("browser") or {}) if isinstance(manifest.get("browser"), dict) else {}).get("status") or ""),
                "eventCount": len(timeline),
                "rawLogCount": len(raw_files),
                "conversationCount": len(conversations),
                "agentLogCount": len(agent_logs),
                "artifactCount": len(artifacts),
                "eventLogCount": len(event_logs),
                "researchLogCount": len(research_logs),
                "errorCount": severity_summary["errorCount"],
                "warningCount": severity_summary["warningCount"],
            }
        )
    scenes.sort(
        key=lambda item: (
            str((item.get("packageIndex") or {}).get("sortableTimestamp") or item.get("startedAt") or ""),
            item["directoryName"],
        ),
        reverse=True,
    )
    return scenes[: max(1, int(limit or 80))]


def get_runtime_scene_detail(scene_id: str) -> dict:
    """Return one runtime scene bundle with manifest, merged timeline, and raw file metadata."""

    scene_dir = _resolve_scene_dir(scene_id)
    manifest = _load_scene_manifest(scene_dir)
    _repair_runtime_scene_from_reconciliation_history(scene_dir, manifest)
    detail_scene_id = _scene_id(scene_dir, manifest)
    timeline = _read_scene_timeline(scene_dir)
    raw_files = _list_raw_files(scene_dir)
    lifecycle_events = _read_scene_lifecycle(scene_dir, timeline)
    conversation_logs = _list_conversation_logs(scene_dir)
    agent_logs = _list_agent_logs(scene_dir)
    artifacts = _list_artifacts(scene_dir)
    event_logs = _list_event_logs(scene_dir)
    research_logs = _list_research_logs(scene_dir)
    package_index = _runtime_scene_package_index(scene_dir, manifest, detail_scene_id)
    _sync_runtime_scene_package_sidecars_if_stale(scene_dir, manifest, package_index)
    summary_payload = _load_scene_json(scene_dir / SUMMARY_PATH)
    package_diagnosis = summary_payload.get("diagnosis") if isinstance(summary_payload.get("diagnosis"), dict) else {}
    return {
        "runtimeSceneId": detail_scene_id,
        "directoryName": scene_dir.name,
        "displayName": package_index["displayName"],
        "packageIndex": package_index,
        "manifestPath": str((scene_dir / "manifest.json").relative_to(PROJECT_ROOT).as_posix()),
        "manifest": manifest,
        "startedAt": package_index["startedAt"],
        "endedAt": str(manifest.get("ended_at") or ""),
        "status": _runtime_scene_status(manifest),
        "result": str(manifest.get("result") or ""),
        "stopReason": str(manifest.get("stop_reason") or ""),
        "trigger": str(manifest.get("trigger") or ""),
        "sessionMode": str(manifest.get("session_mode") or ""),
        "host": str(manifest.get("host") or ""),
        "port": int(manifest.get("port") or 0) if str(manifest.get("port") or "").strip() else 0,
        "url": str(manifest.get("url") or ""),
        "frontend": manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {},
        "backend": manifest.get("backend") if isinstance(manifest.get("backend"), dict) else {},
        "browser": manifest.get("browser") if isinstance(manifest.get("browser"), dict) else {},
        "supervisor": manifest.get("supervisor") if isinstance(manifest.get("supervisor"), dict) else {},
        "timeline": timeline,
        "lifecycle": lifecycle_events,
        "rawFiles": raw_files,
        "conversationLogs": conversation_logs,
        "agentLogs": agent_logs,
        "artifacts": artifacts,
        "eventLogs": event_logs,
        "researchLogs": research_logs,
        "packageSummary": _runtime_scene_package_summary(
            timeline=timeline,
            lifecycle=lifecycle_events,
            raw_files=raw_files,
            conversation_logs=conversation_logs,
            agent_logs=agent_logs,
            artifacts=artifacts,
            event_logs=event_logs,
            research_logs=research_logs,
        ),
        "packageDiagnosis": package_diagnosis,
    }


def build_runtime_scene_prompt_index(limit: int = 3) -> str:
    """Return a compact prompt-facing index for the newest runtime scene packages."""

    try:
        scene_summaries = list_runtime_scenes(limit=max(1, min(int(limit or 3), 10)))
    except Exception:
        return ""

    if not scene_summaries:
        return ""

    lines = [
        "## RUNTIME_LOG_INDEX",
        "- 最近运行现场索引；用于先定位日志包，再按需读取 detail/raw 子日志。",
        "- 只注入结构化摘要和路径，不注入 raw 日志全文、完整对话或完整工具输出。",
    ]
    for index, summary in enumerate(scene_summaries[: max(1, min(int(limit or 3), 10))], start=1):
        scene_id = str(summary.get("runtimeSceneId") or "").strip()
        detail: dict[str, Any] = {}
        if scene_id:
            try:
                detail = get_runtime_scene_detail(scene_id)
            except Exception:
                detail = {}

        source = detail or summary
        package_index = source.get("packageIndex") if isinstance(source.get("packageIndex"), dict) else {}
        package_summary = source.get("packageSummary") if isinstance(source.get("packageSummary"), dict) else {}
        package_diagnosis = source.get("packageDiagnosis") if isinstance(source.get("packageDiagnosis"), dict) else {}
        issue_state = package_diagnosis.get("issueState") if isinstance(package_diagnosis.get("issueState"), dict) else {}
        first_signal = package_diagnosis.get("firstSignal") if isinstance(package_diagnosis.get("firstSignal"), dict) else {}

        directory_name = str(source.get("directoryName") or summary.get("directoryName") or scene_id).strip()
        display_name = str(
            source.get("displayName")
            or package_index.get("displayName")
            or source.get("title")
            or scene_id
            or directory_name
        ).strip()
        status = str(source.get("status") or summary.get("status") or "unknown").strip()
        result = str(source.get("result") or summary.get("result") or "").strip()
        event_count = int(package_summary.get("eventCount") or source.get("eventCount") or summary.get("eventCount") or 0)
        error_count = int(package_summary.get("errorCount") or source.get("errorCount") or summary.get("errorCount") or 0)
        warning_count = int(package_summary.get("warningCount") or source.get("warningCount") or summary.get("warningCount") or 0)
        active_cluster_count = int(issue_state.get("activeClusterCount") or 0)
        policy_cluster_count = int(issue_state.get("policyClusterCount") or 0)
        historical_cluster_count = int(issue_state.get("historicalClusterCount") or 0)
        next_step = _truncate_prompt_index_text(str(package_diagnosis.get("agentNextStep") or ""), 360)
        first_signal_code = str(first_signal.get("eventCode") or "").strip()
        severity = str(package_diagnosis.get("severity") or issue_state.get("severity") or "").strip()

        lines.append(f"### {index}. {display_name or 'runtime scene'}")
        lines.append(f"- 包路径: `logs/runtime_scenes/{directory_name}`")
        lines.append(f"- 状态: {status}{f' / {result}' if result else ''} | severity={severity or 'info'} | events={event_count} | errors={error_count} | warnings={warning_count}")
        if active_cluster_count or policy_cluster_count or historical_cluster_count:
            lines.append(
                f"- 问题簇: active={active_cluster_count} | policy={policy_cluster_count} | historical={historical_cluster_count}"
            )
        if first_signal_code:
            lines.append(f"- 首个信号: `{first_signal_code}`")
        if next_step:
            lines.append(f"- agent 下一步: {next_step}")

    return "\n".join(lines).strip()


def read_runtime_scene_file(scene_id: str, relative_path: str) -> dict:
    """Read a raw or structured file from one runtime scene bundle."""

    scene_dir = _resolve_scene_dir(scene_id)
    relative = _normalize_relative_path(relative_path)
    file_path = _resolve_scene_child(scene_dir, relative)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Runtime scene file not found: {relative}")
    raw = file_path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("Binary runtime scene files are not supported in the preview yet")
    content = raw.decode("utf-8-sig", errors="replace")
    truncated = len(content) > MAX_TEXT_CHARS
    if truncated:
        content = content[:MAX_TEXT_CHARS] + "\n\n... preview truncated ..."
    scene_root_path = scene_dir.relative_to(PROJECT_ROOT).as_posix()
    return {
        "rootId": "runtime_scenes",
        "rootPath": scene_root_path,
        "relativePath": relative,
        "path": f"{scene_root_path}/{relative}".replace("//", "/"),
        "language": LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text"),
        "content": content,
        "truncated": truncated,
        "diagnostics": _analyze_runtime_scene_content(scene_id, relative, content),
    }


def record_browser_telemetry(payload: dict[str, Any]) -> dict[str, Any]:
    """Append one browser-side telemetry event into the active runtime scene bundle."""

    scene_dir = _resolve_current_runtime_scene_dir()
    if scene_dir is None:
        return {
            "accepted": False,
            "reason": "no_runtime_scene",
        }

    timestamp = datetime.now(UTC).isoformat()
    phase = _sanitize_token(payload.get("phase"), default="page")
    event_code = _sanitize_token(payload.get("eventCode"), default="browser.telemetry")
    level = _sanitize_token(payload.get("level"), default="info")
    message = _truncate_text(str(payload.get("message") or event_code), 320)
    fields = _normalize_telemetry_fields(payload.get("fields"))

    raw_line = f"[{timestamp}] {event_code} [{level}] {message}"
    if fields:
        raw_line = f"{raw_line} :: {json.dumps(fields, ensure_ascii=False, separators=(',', ':'))}"
    with BROWSER_TELEMETRY_WRITE_LOCK:
        manifest = _load_scene_manifest(scene_dir)
        scene_id = _scene_id(scene_dir, manifest)
        _append_scene_log_line(scene_dir, BROWSER_TELEMETRY_RAW_PATH, _truncate_text(raw_line, MAX_TELEMETRY_TEXT_CHARS))

        raw_refs = [
            {
                "path": BROWSER_TELEMETRY_RAW_PATH,
                "tail_lines": 80,
            },
        ]
        indexed = _should_index_browser_telemetry_event(manifest, timestamp, event_code, level, fields)
        event_payload = {
            "schema_version": 1,
            "runtime_scene_id": scene_id,
            "ts": timestamp,
            "seq": _next_scene_event_seq(scene_dir, BROWSER_TELEMETRY_COMPONENT),
            "component": BROWSER_TELEMETRY_COMPONENT,
            "phase": phase,
            "event_code": event_code,
            "level": level,
            "outcome": "observed",
            "message": message,
            "fields": fields,
            "raw_refs": raw_refs,
        }
        if indexed:
            _append_scene_event(scene_dir, BROWSER_TELEMETRY_COMPONENT, event_payload)
        _update_runtime_scene_package_manifest(scene_dir, manifest)
        _update_browser_manifest(scene_dir, manifest, timestamp, event_code, level, message, fields, indexed=indexed)

    return {
        "accepted": True,
        "runtimeSceneId": scene_id,
        "recordedAt": timestamp,
    }


def record_backend_api_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Append one backend API request event into the active runtime scene bundle."""

    scene_dir = _resolve_current_runtime_scene_dir()
    if scene_dir is None:
        return {
            "accepted": False,
            "reason": "no_runtime_scene",
        }

    timestamp = datetime.now(UTC).isoformat()
    method = _truncate_text(str(payload.get("method") or "").upper(), 16)
    path = _truncate_text(str(payload.get("path") or ""), 240)
    status_code = _coerce_int(payload.get("status_code"), default=0)
    duration_ms = _coerce_float(payload.get("duration_ms"), default=0.0)
    path_template = _truncate_text(str(payload.get("path_template") or path), 240)
    level = "error" if status_code >= 500 else "warning" if status_code >= 400 else "info"
    outcome = "failed" if status_code >= 500 else "client_error" if status_code >= 400 else "succeeded"
    event_code = _sanitize_token(payload.get("event_code"), default="backend.api.request")
    message = _truncate_text(
        str(payload.get("message") or f"{method or 'API'} {path_template or path} -> {status_code or '?'}"),
        320,
    )
    fields = _normalize_telemetry_fields(
        {
            "method": method,
            "path": path,
            "pathTemplate": path_template,
            "statusCode": status_code,
            "durationMs": round(duration_ms, 2),
            "query": _truncate_text(str(payload.get("query") or ""), 240),
            "client": _truncate_text(str(payload.get("client") or ""), 160),
            "exceptionType": _truncate_text(str(payload.get("exception_type") or ""), 120),
            "exceptionMessage": _truncate_text(str(payload.get("exception_message") or ""), 320),
        }
    )

    raw_line = f"[{timestamp}] {event_code} [{level}] {message}"
    if fields:
        raw_line = f"{raw_line} :: {json.dumps(fields, ensure_ascii=False, separators=(',', ':'))}"

    with BACKEND_API_WRITE_LOCK:
        manifest = _load_scene_manifest(scene_dir)
        scene_id = _scene_id(scene_dir, manifest)
        _append_scene_log_line(scene_dir, BACKEND_API_RAW_PATH, _truncate_text(raw_line, MAX_TELEMETRY_TEXT_CHARS))
        event_payload = {
            "schema_version": 1,
            "runtime_scene_id": scene_id,
            "ts": timestamp,
            "seq": _next_scene_event_seq(scene_dir, BACKEND_COMPONENT),
            "component": BACKEND_COMPONENT,
            "phase": "api",
            "event_code": event_code,
            "level": level,
            "outcome": outcome,
            "message": message,
            "fields": fields,
            "raw_refs": [
                {
                    "path": BACKEND_API_RAW_PATH,
                    "tail_lines": 80,
                },
            ],
        }
        _append_scene_event(scene_dir, BACKEND_COMPONENT, event_payload)
        _update_runtime_scene_package_manifest(scene_dir, manifest)
        _update_backend_api_manifest(scene_dir, manifest, timestamp, level, fields)

    return {
        "accepted": True,
        "runtimeSceneId": scene_id,
        "recordedAt": timestamp,
    }


def record_runtime_scene_event(
    component: str,
    phase: str,
    event_code: str,
    *,
    message: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
    raw_refs: list[dict[str, Any]] | None = None,
    child_log_path: str = "",
    child_log_payload: dict[str, Any] | None = None,
    lifecycle: bool = False,
    occurred_at: str = "",
    allow_recent_completed: bool = False,
) -> dict[str, Any]:
    """Append one structured service/runtime event into the active runtime scene package."""

    scene_dir = _resolve_current_runtime_scene_dir()
    if scene_dir is None and allow_recent_completed:
        scene_dir = _resolve_recent_completed_runtime_scene_dir()
    if scene_dir is None:
        return {
            "accepted": False,
            "reason": "no_runtime_scene",
        }

    timestamp = _normalize_event_timestamp(occurred_at) or _now_utc()
    component_name = _sanitize_path_token(component, default="runtime")
    phase_name = _sanitize_token(phase, default="runtime")
    event_name = _sanitize_token(event_code, default=f"{component_name}.event")
    level_name = _sanitize_token(level, default="info")
    outcome_name = _sanitize_token(outcome, default="observed")
    message_text = _truncate_text(str(message or event_name), 320)
    normalized_fields = _normalize_telemetry_fields(fields)
    normalized_raw_refs = _normalize_raw_refs(raw_refs)
    normalized_child_path = _safe_optional_relative_path(child_log_path)
    if normalized_child_path:
        normalized_raw_refs = [
            *normalized_raw_refs,
            {
                "path": normalized_child_path,
                "tail_lines": 80,
            },
        ]

    with RUNTIME_SCENE_PACKAGE_WRITE_LOCK:
        manifest = _load_scene_manifest(scene_dir)
        scene_id = _scene_id(scene_dir, manifest)
        if normalized_child_path:
            child_payload = _normalize_telemetry_fields(child_log_payload or {})
            child_payload.update(
                {
                    "schema_version": 1,
                    "runtime_scene_id": scene_id,
                    "ts": timestamp,
                    "component": component_name,
                    "phase": phase_name,
                    "event_code": event_name,
                    "level": level_name,
                    "outcome": outcome_name,
                    "message": message_text,
                }
            )
            _append_scene_jsonl(scene_dir, normalized_child_path, child_payload)
        event_payload = {
            "schema_version": 1,
            "runtime_scene_id": scene_id,
            "ts": timestamp,
            "seq": _next_scene_event_seq(scene_dir, component_name),
            "component": component_name,
            "phase": phase_name,
            "event_code": event_name,
            "level": level_name,
            "outcome": outcome_name,
            "message": message_text,
            "fields": normalized_fields,
            "raw_refs": normalized_raw_refs,
        }
        if lifecycle:
            event_payload["lifecycle"] = True
        _append_scene_event(scene_dir, component_name, event_payload)
        _maybe_close_runtime_scene_from_reconciliation(scene_dir, manifest, event_name, normalized_fields, timestamp)
        _update_runtime_scene_package_manifest(scene_dir, manifest)

    return {
        "accepted": True,
        "runtimeSceneId": scene_id,
        "recordedAt": timestamp,
        "path": normalized_child_path,
    }


def record_research_scene_event(
    event_code: str,
    *,
    message: str = "",
    level: str = "info",
    outcome: str = "observed",
    phase: str = "theme_discovery",
    fields: dict[str, Any] | None = None,
    session_id: str = "",
    agent_key: str = "",
    occurred_at: str = "",
    allow_recent_completed: bool = True,
) -> dict[str, Any]:
    """Record research workflow activity in a dedicated runtime-scene subpackage."""

    scene_dir = _resolve_current_runtime_scene_dir()
    if scene_dir is None and allow_recent_completed:
        scene_dir = _resolve_recent_completed_runtime_scene_dir()
    if scene_dir is None:
        return {
            "accepted": False,
            "reason": "no_runtime_scene",
        }

    timestamp = _normalize_event_timestamp(occurred_at) or _now_utc()
    event_name = _sanitize_token(event_code, default="research.event")
    phase_name = _sanitize_token(phase, default="theme_discovery")
    level_name = _sanitize_token(level, default="info")
    outcome_name = _sanitize_token(outcome, default="observed")
    normalized_fields = _normalize_telemetry_fields(fields)
    normalized_session_id = str(session_id or normalized_fields.get("sessionId") or "").strip()
    normalized_agent_key = str(agent_key or normalized_fields.get("agentKey") or "").strip()
    if normalized_session_id:
        normalized_fields["sessionId"] = normalized_session_id
    if normalized_agent_key:
        normalized_fields["agentKey"] = normalized_agent_key
    message_text = _truncate_text(str(message or event_name), 320)

    with RUNTIME_SCENE_PACKAGE_WRITE_LOCK:
        manifest = _load_scene_manifest(scene_dir)
        scene_id = _scene_id(scene_dir, manifest)
        research_payload = {
            "schema_version": 1,
            "runtime_scene_id": scene_id,
            "ts": timestamp,
            "seq": _next_research_event_seq(scene_dir),
            "component": "research",
            "phase": phase_name,
            "event_code": event_name,
            "level": level_name,
            "outcome": outcome_name,
            "message": message_text,
            "session_id": normalized_session_id,
            "agent_key": normalized_agent_key,
            "fields": normalized_fields,
        }
        _append_scene_jsonl(scene_dir, RESEARCH_EVENTS_PATH, research_payload)
        _append_scene_event(
            scene_dir,
            "research",
            {
                "schema_version": 1,
                "runtime_scene_id": scene_id,
                "ts": timestamp,
                "seq": _next_scene_event_seq(scene_dir, "research"),
                "component": "research",
                "phase": phase_name,
                "event_code": event_name,
                "level": level_name,
                "outcome": outcome_name,
                "message": message_text,
                "fields": normalized_fields,
                "raw_refs": [
                    {
                        "path": RESEARCH_EVENTS_PATH,
                        "tail_lines": 80,
                    },
                ],
            },
        )
        _save_runtime_scene_research_summary(scene_dir)
        _update_runtime_scene_package_manifest(scene_dir, manifest)

    return {
        "accepted": True,
        "runtimeSceneId": scene_id,
        "recordedAt": timestamp,
        "path": RESEARCH_EVENTS_PATH,
        "summaryPath": RESEARCH_SUMMARY_PATH,
    }


def _maybe_close_runtime_scene_from_reconciliation(
    scene_dir: Path,
    manifest: dict[str, Any],
    event_name: str,
    fields: dict[str, Any],
    timestamp: str,
) -> bool:
    if event_name != "runtime.snapshot.reconciled":
        return False
    if str(manifest.get("status") or "").strip().lower() not in {"", "running", "starting", "queued", "opening", "stopping", "closing"}:
        return False
    observed_state = str(fields.get("observedState") or "").strip().lower()
    desired_state = str(fields.get("desiredState") or "").strip().lower()
    manager_running = bool(fields.get("managerRunning"))
    backend_pid = _coerce_int(fields.get("backendPid"), default=0)
    browser_pid = _coerce_int(fields.get("browserWindowPid"), default=0)
    if observed_state != "closed" or desired_state != "closed" or manager_running or backend_pid or browser_pid:
        return False

    manifest["status"] = "stopped"
    manifest["result"] = str(manifest.get("result") or "state_reconciled")
    manifest["stop_reason"] = str(manifest.get("stop_reason") or "runtime manager observed all workbench processes closed")
    manifest["ended_at"] = str(manifest.get("ended_at") or timestamp or _now_utc())

    backend = manifest.get("backend") if isinstance(manifest.get("backend"), dict) else {}
    backend.update({"health_status": "stopped", "pid": 0})
    manifest["backend"] = backend

    browser = manifest.get("browser") if isinstance(manifest.get("browser"), dict) else {}
    browser.update({"status": "stopped", "window_pid": 0, "launch_pid": 0})
    manifest["browser"] = browser

    supervisor = manifest.get("supervisor") if isinstance(manifest.get("supervisor"), dict) else {}
    if supervisor:
        supervisor.update({"status": "stopped", "pid": 0})
        manifest["supervisor"] = supervisor

    runtime_manager = manifest.get("runtime_manager") if isinstance(manifest.get("runtime_manager"), dict) else {}
    runtime_manager.update(
        {
            "desired_state": "closed",
            "observed_state": "closed",
            "phase": "steady",
            "failure_message": "",
            "reconciled_at": timestamp,
        }
    )
    manifest["runtime_manager"] = runtime_manager
    return True


def _repair_runtime_scene_from_reconciliation_history(scene_dir: Path, manifest: dict[str, Any]) -> bool:
    if str(manifest.get("status") or "").strip().lower() not in {"", "running", "starting", "queued", "opening", "stopping", "closing"}:
        return False
    reconciliation = _latest_closed_reconciliation_event(scene_dir)
    if reconciliation is None:
        return False
    changed = _maybe_close_runtime_scene_from_reconciliation(
        scene_dir,
        manifest,
        "runtime.snapshot.reconciled",
        reconciliation["fields"],
        reconciliation["timestamp"],
    )
    if changed:
        _update_runtime_scene_package_manifest(scene_dir, manifest)
    return changed


def _latest_closed_reconciliation_event(scene_dir: Path) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    latest_timestamp = ""
    for row in _read_jsonl_file(scene_dir / TIMELINE_PATH):
        event_name = str(row.get("event_code") or "").strip()
        timestamp = str(row.get("ts") or "").strip()
        if not timestamp:
            continue
        if _is_runtime_scene_reopen_event(event_name) and latest_timestamp and timestamp > latest_timestamp:
            latest = None
            latest_timestamp = ""
            continue
        if event_name != "runtime.snapshot.reconciled":
            continue
        fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
        if not _closed_reconciliation_fields(fields):
            continue
        latest = {"timestamp": _normalize_event_timestamp(timestamp) or timestamp, "fields": fields}
        latest_timestamp = timestamp
    return latest


def _closed_reconciliation_fields(fields: dict[str, Any]) -> bool:
    observed_state = str(fields.get("observedState") or "").strip().lower()
    desired_state = str(fields.get("desiredState") or "").strip().lower()
    manager_running = bool(fields.get("managerRunning"))
    backend_pid = _coerce_int(fields.get("backendPid"), default=0)
    browser_pid = _coerce_int(fields.get("browserWindowPid"), default=0)
    return observed_state == "closed" and desired_state == "closed" and not manager_running and backend_pid == 0 and browser_pid == 0


def _is_runtime_scene_reopen_event(event_name: str) -> bool:
    return str(event_name or "").strip() in {
        "runtime.scene.ready",
        "backend.health.succeeded",
        "browser.window.opened",
        "workbench.open.already_satisfied",
        "workbench.open.verification_succeeded",
    }


def record_runtime_scene_conversation_event(
    session_id: str,
    role: str,
    content: str,
    *,
    message: dict[str, Any] | None = None,
    event: str = "message",
    status: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    active_task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one web-chat conversation breadcrumb into the active runtime scene package."""

    scene_dir = _resolve_current_runtime_scene_dir()
    if scene_dir is None:
        return {
            "accepted": False,
            "reason": "no_runtime_scene",
        }

    timestamp = _now_utc()
    manifest = _load_scene_manifest(scene_dir)
    scene_id = _scene_id(scene_dir, manifest)
    normalized_session_id = _sanitize_path_token(session_id, default="session")
    role_label = _sanitize_token(role, default="message")
    event_code = f"conversation.{_sanitize_path_token(event, default='message')}"
    relative_path = f"{CONVERSATIONS_DIR}/{normalized_session_id}.jsonl"
    text = _truncate_text(str(content or ""), MAX_CONVERSATION_TEXT_CHARS)
    payload = {
        "schema_version": 1,
        "runtime_scene_id": scene_id,
        "ts": timestamp,
        "session_id": str(session_id or "").strip(),
        "event": str(event or "message").strip() or "message",
        "role": role_label,
        "status": str(status or "").strip(),
        "content": text,
        "message": message if isinstance(message, dict) else {},
        "tool_calls": tool_calls if isinstance(tool_calls, list) else [],
        "active_task": active_task if isinstance(active_task, dict) else {},
    }
    with RUNTIME_SCENE_PACKAGE_WRITE_LOCK:
        _append_scene_jsonl(scene_dir, relative_path, payload)
        _append_agent_turn_log(scene_dir, payload)
        _append_agent_tool_call_logs(scene_dir, payload)
        _append_scene_event(
            scene_dir,
            "conversation",
            {
                "schema_version": 1,
                "runtime_scene_id": scene_id,
                "ts": timestamp,
                "seq": _next_scene_event_seq(scene_dir, "conversation"),
                "component": "conversation",
                "phase": str(event or "message").strip() or "message",
                "event_code": event_code,
                "level": "info" if str(status or "").strip().lower() != "failed" else "error",
                "outcome": str(status or "observed").strip() or "observed",
                "message": _truncate_text(f"{role_label}: {text}", 320),
                "fields": {
                    "sessionId": str(session_id or "").strip(),
                    "role": role_label,
                    "status": str(status or "").strip(),
                    "contentPreview": _truncate_text(text, 240),
                },
                "raw_refs": [
                    {
                        "path": relative_path,
                        "tail_lines": 80,
                    },
                ],
            },
        )
        _update_runtime_scene_package_manifest(scene_dir, manifest)

    return {
        "accepted": True,
        "runtimeSceneId": scene_id,
        "recordedAt": timestamp,
        "path": relative_path,
    }


def _append_agent_turn_log(scene_dir: Path, conversation_payload: dict[str, Any]) -> None:
    content = _truncate_text(str(conversation_payload.get("content") or ""), 800)
    active_task = conversation_payload.get("active_task")
    _append_scene_jsonl(
        scene_dir,
        f"{AGENT_DIR}/turns.jsonl",
        {
            "schema_version": 1,
            "runtime_scene_id": conversation_payload.get("runtime_scene_id") or "",
            "ts": conversation_payload.get("ts") or "",
            "session_id": conversation_payload.get("session_id") or "",
            "event": conversation_payload.get("event") or "",
            "role": conversation_payload.get("role") or "",
            "status": conversation_payload.get("status") or "",
            "content_preview": content,
            "active_task": active_task if isinstance(active_task, dict) else {},
        },
    )


def _append_agent_tool_call_logs(scene_dir: Path, conversation_payload: dict[str, Any]) -> None:
    tool_calls = conversation_payload.get("tool_calls")
    if not isinstance(tool_calls, list):
        return
    for index, item in enumerate(tool_calls):
        if not isinstance(item, dict):
            continue
        _append_scene_jsonl(
            scene_dir,
            f"{AGENT_DIR}/tool_calls.jsonl",
            {
                "schema_version": 1,
                "runtime_scene_id": conversation_payload.get("runtime_scene_id") or "",
                "ts": conversation_payload.get("ts") or "",
                "session_id": conversation_payload.get("session_id") or "",
                "event": conversation_payload.get("event") or "",
                "role": conversation_payload.get("role") or "",
                "index": index,
                "name": str(item.get("name") or "").strip(),
                "status": str(item.get("status") or "").strip(),
                "summary": _truncate_text(str(item.get("summary") or ""), 800),
            },
        )


def delete_runtime_scenes(scene_ids: list[str] | tuple[str, ...]) -> dict:
    """Delete one or more runtime scene bundles as a unit."""

    normalized_ids = _normalize_scene_ids(scene_ids)
    if not normalized_ids:
        raise ValueError("Select at least one runtime scene to delete")

    deleted_ids: list[str] = []
    missing_ids: list[str] = []
    for scene_id in normalized_ids:
        try:
            scene_dir = _resolve_scene_dir(scene_id)
        except FileNotFoundError:
            missing_ids.append(scene_id)
            continue
        manifest = _load_scene_manifest(scene_dir)
        if str(manifest.get("status", "") or "").strip().lower() == "running":
            raise ValueError(f"Runtime scene is still running: {scene_id}")
        shutil.rmtree(scene_dir)
        deleted_ids.append(scene_id)

    return {
        "requestedCount": len(normalized_ids),
        "deletedCount": len(deleted_ids),
        "missingCount": len(missing_ids),
        "deletedSceneIds": deleted_ids,
        "missingSceneIds": missing_ids,
        "summary": (
            f"Deleted {len(deleted_ids)} runtime scene bundle"
            f"{'' if len(deleted_ids) == 1 else 's'}."
        ),
    }


def _scene_dirs() -> list[Path]:
    runtime_scene_root = _runtime_scene_root()
    if not runtime_scene_root.exists() or not runtime_scene_root.is_dir():
        return []
    return sorted([path for path in runtime_scene_root.iterdir() if path.is_dir()], reverse=True)


def _analyze_runtime_scene_content(scene_id: str, relative_path: str, content: str) -> dict[str, Any]:
    return analyze_log_content(
        anchor=f"runtime_scenes/{scene_id}/{relative_path}",
        content=content,
        normal_summary="这份原始日志未发现明显错误或警告，可作为运行现场的补充证据。",
        empty_summary="这份原始日志为空，暂时不能作为诊断证据。",
        error_summary_prefix="这份原始日志发现 ",
        warning_summary_prefix="这份原始日志发现 ",
        error_next_step="打开错误筛选，围绕第 {line} 行对照左侧统一时间线和证据路径。",
        warning_next_step="打开警告筛选，把第 {line} 行附近的重试/超时与 timeline 事件对齐。",
        structured_next_step="按结构化事件类型回到统一时间线，确认这份原始日志对应的组件阶段。",
        fallback_next_step="如当前问题仍未解释，继续查看同一运行现场的其它 raw 日志。",
    )


def _load_scene_manifest(scene_dir: Path) -> dict:
    manifest_path = scene_dir / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _save_scene_manifest(scene_dir: Path, manifest: dict[str, Any]) -> None:
    manifest_path = scene_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_runtime_scene_package_index(scene_dir: Path, package_index: dict[str, Any]) -> None:
    index_path = scene_dir / PACKAGE_INDEX_PATH
    payload = _runtime_scene_package_index_payload(scene_dir, package_index)
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _runtime_scene_package_index_payload(scene_dir: Path, package_index: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "package_id": package_index["packageId"],
        "display_name": package_index["displayName"],
        "index_key": package_index["indexKey"],
        "sortable_timestamp": package_index["sortableTimestamp"],
        "started_at": package_index["startedAt"],
        "started_at_local": package_index["startedAtLocal"],
        "started_date": package_index["startedDate"],
        "started_time": package_index["startedTime"],
        "ended_at": package_index["endedAt"],
        "duration_seconds": package_index["durationSeconds"],
        "search_text": package_index["searchText"],
        "tags": package_index["tags"],
        "summary_ref": SUMMARY_PATH,
        "timeline_path": TIMELINE_PATH,
        "lifecycle_path": LIFECYCLE_PATH,
        "raw_dir": "raw",
        "conversations_dir": CONVERSATIONS_DIR,
        "agent_dir": AGENT_DIR,
        "artifacts_dir": ARTIFACTS_DIR,
        "research_dir": RESEARCH_DIR,
        "snapshot_metadata": _runtime_scene_snapshot_metadata(scene_dir),
    }


def _save_runtime_scene_summary(scene_dir: Path, manifest: dict[str, Any], package_index: dict[str, Any]) -> None:
    summary_path = scene_dir / SUMMARY_PATH
    payload = _runtime_scene_summary_payload(scene_dir, manifest, package_index)
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _runtime_scene_summary_payload(
    scene_dir: Path,
    manifest: dict[str, Any],
    package_index: dict[str, Any],
) -> dict[str, Any]:
    diagnosis = _runtime_scene_package_diagnosis_for_scene(scene_dir, manifest, package_index["packageId"])
    return {
        "schema_version": 2,
        "package_id": package_index["packageId"],
        "display_name": package_index["displayName"],
        "index_key": package_index["indexKey"],
        "status": _runtime_scene_status(manifest),
        "result": str(manifest.get("result") or ""),
        "stop_reason": str(manifest.get("stop_reason") or ""),
        "trigger": str(manifest.get("trigger") or ""),
        "started_at": package_index["startedAt"],
        "started_at_local": package_index["startedAtLocal"],
        "started_date": package_index["startedDate"],
        "started_time": package_index["startedTime"],
        "ended_at": package_index["endedAt"],
        "duration_seconds": package_index["durationSeconds"],
        "event_counts": _runtime_scene_summary_counts(scene_dir),
        "snapshot_metadata": _runtime_scene_snapshot_metadata(scene_dir),
        "agent_brief": _runtime_scene_agent_brief(diagnosis),
        "diagnosis": diagnosis,
        "primary_files": {
            "summary": SUMMARY_PATH,
            "package_index": PACKAGE_INDEX_PATH,
            "manifest": "manifest.json",
            "timeline": TIMELINE_PATH,
            "lifecycle": LIFECYCLE_PATH,
            "startup": "raw/desktop-entry.log",
            "research": RESEARCH_SUMMARY_PATH,
        },
        "sections": _runtime_scene_summary_sections(),
        "diagnostic_entrypoint": {
            "first_read": SUMMARY_PATH,
            "purpose": "Agent first-read summary for reconstructing this lifecycle package before opening child logs.",
            "package_root": f"logs/runtime_scenes/{scene_dir.name}",
            "path_mode": "package_relative",
            "evidence_paths": diagnosis.get("evidencePaths", []),
            "recommended_order": [
                SUMMARY_PATH,
                PACKAGE_INDEX_PATH,
                "raw/desktop-entry-vbs.log",
                "raw/desktop-entry.log",
                "raw/launcher-control.log",
                TIMELINE_PATH,
                LIFECYCLE_PATH,
                "conversations/",
                "agent/turns.jsonl",
                "agent/tool_calls.jsonl",
                "agent/supervised_runs/",
                "agent/supervised_worktree_runs/",
                "agent/self_evolution_runs/",
                RESEARCH_SUMMARY_PATH,
                RESEARCH_EVENTS_PATH,
                "raw/",
                "artifacts/",
            ],
        },
        "generated_at": _now_utc(),
    }


def _runtime_scene_agent_brief(diagnosis: dict[str, Any]) -> dict[str, Any]:
    """Build a compact agent-facing diagnosis view for one runtime scene.

    The full ``diagnosis`` object is intentionally rich, but most agent-side
    triage only needs to know whether action is required, what the primary
    issue is, and which evidence paths should be opened first.  Keeping this
    brief in ``summary.json`` reduces repeated reads of timeline/raw logs.
    """
    issue_state = diagnosis.get("issueState") if isinstance(diagnosis.get("issueState"), dict) else {}
    evidence_paths = diagnosis.get("evidencePaths") if isinstance(diagnosis.get("evidencePaths"), list) else []
    severity = str(diagnosis.get("severity") or issue_state.get("severity") or "info")
    active_clusters = issue_state.get("activeClusters") if isinstance(issue_state.get("activeClusters"), list) else []
    active_count = int(issue_state.get("activeClusterCount") or 0)
    if severity in {"error", "warning"} and active_clusters:
        active_count = len(
            [
                cluster
                for cluster in active_clusters
                if isinstance(cluster, dict) and str(cluster.get("severity") or "") == severity
            ]
        )
    policy_count = int(issue_state.get("policyClusterCount") or 0)
    historical_count = int(issue_state.get("historicalClusterCount") or 0)
    first_signal = diagnosis.get("firstSignal") if isinstance(diagnosis.get("firstSignal"), dict) else {}
    primary_issue = str(
        first_signal.get("event")
        or first_signal.get("type")
        or first_signal.get("eventCode")
        or first_signal.get("component")
        or _runtime_scene_diagnosis_status(issue_state)
        or "none"
    )

    if active_count > 0 or severity in {"error", "critical"}:
        diagnosis_status = "active_issue"
        needs_action = True
        actionability = "fix_required"
        do_not_do = ["do not ignore active clusters without checking their evidence paths"]
    elif policy_count > 0:
        diagnosis_status = "policy_only"
        needs_action = False
        actionability = "policy_acknowledge_only"
        do_not_do = ["do not treat expected policy blocks as product/runtime bugs"]
    elif historical_count > 0:
        diagnosis_status = "resolved"
        needs_action = False
        actionability = "no_action_needed"
        do_not_do = ["do not keep chasing historical recovered errors as active blockers"]
    else:
        diagnosis_status = "healthy"
        needs_action = False
        actionability = "no_action_needed"
        do_not_do = ["do not open raw logs unless a new signal appears"]

    return {
        "diagnosis_status": diagnosis_status,
        "needs_action": needs_action,
        "actionability": actionability,
        "primary_issue": primary_issue,
        "severity": severity,
        "active_cluster_count": active_count,
        "policy_cluster_count": policy_count,
        "historical_cluster_count": historical_count,
        "next_minimal_action": str(diagnosis.get("agentNextStep") or "read summary.json first"),
        "evidence_refs": evidence_paths[:5],
        "do_not_do": do_not_do,
    }


def _runtime_scene_snapshot_metadata(scene_dir: Path) -> dict[str, Any]:
    timeline = _read_scene_timeline(scene_dir)
    lifecycle = _read_scene_lifecycle(scene_dir, timeline)
    last_event_timestamp = ""
    for event in [*timeline, *lifecycle]:
        ts = str(event.get("ts") or event.get("timestamp") or event.get("recordedAt") or "")
        if ts and (not last_event_timestamp or ts > last_event_timestamp):
            last_event_timestamp = ts
    return {
        "generated_at": _now_utc(),
        "source_event_count": len(timeline) + len(lifecycle),
        "timeline_event_count": len(timeline),
        "lifecycle_event_count": len(lifecycle),
        "last_event_timestamp": last_event_timestamp,
        "is_live_snapshot": not _runtime_scene_has_completed(_load_scene_manifest(scene_dir)),
    }


def _sync_runtime_scene_package_sidecars_if_stale(
    scene_dir: Path,
    manifest: dict[str, Any],
    package_index: dict[str, Any],
) -> None:
    if not _runtime_scene_package_sidecars_are_stale(scene_dir, manifest, package_index):
        return
    try:
        _update_runtime_scene_package_manifest(scene_dir, manifest)
    except OSError:
        return


def _runtime_scene_package_sidecars_are_stale(
    scene_dir: Path,
    manifest: dict[str, Any],
    package_index: dict[str, Any],
) -> bool:
    expected_index = _runtime_scene_sidecar_compare_payload(
        _runtime_scene_package_index_payload(scene_dir, package_index)
    )
    actual_index = _runtime_scene_sidecar_compare_payload(
        _load_scene_json(scene_dir / PACKAGE_INDEX_PATH)
    )
    if set(actual_index) != set(expected_index):
        return True
    for key, expected_value in expected_index.items():
        if actual_index.get(key) != expected_value:
            return True

    expected_summary = _runtime_scene_sidecar_compare_payload(
        _runtime_scene_summary_payload(scene_dir, manifest, package_index)
    )
    actual_summary = _runtime_scene_sidecar_compare_payload(
        _load_scene_json(scene_dir / SUMMARY_PATH)
    )
    if set(actual_summary) - {"generated_at"} != set(expected_summary) - {"generated_at"}:
        return True
    for key, expected_value in expected_summary.items():
        if key == "generated_at":
            continue
        if actual_summary.get(key) != expected_value:
            return True

    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    expected_package_values = {
        "index_schema_version": package_index["schemaVersion"],
        "package_id": package_index["packageId"],
        "display_name": package_index["displayName"],
        "index_key": package_index["indexKey"],
        "summary_path": SUMMARY_PATH,
        "package_index_path": PACKAGE_INDEX_PATH,
        "research_dir": RESEARCH_DIR,
    }
    return any(package.get(key) != expected_value for key, expected_value in expected_package_values.items())


def _runtime_scene_sidecar_compare_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload) if isinstance(payload, dict) else {}
    snapshot_metadata = normalized.get("snapshot_metadata")
    if isinstance(snapshot_metadata, dict):
        stable_snapshot = dict(snapshot_metadata)
        stable_snapshot.pop("generated_at", None)
        normalized["snapshot_metadata"] = stable_snapshot
    return normalized


def _load_scene_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _runtime_scene_summary_counts(scene_dir: Path) -> dict[str, int]:
    timeline = _read_scene_timeline(scene_dir)
    lifecycle = _read_scene_lifecycle(scene_dir, timeline)
    raw_files = _list_raw_files(scene_dir)
    conversation_logs = _list_conversation_logs(scene_dir)
    agent_logs = _list_agent_logs(scene_dir)
    artifacts = _list_artifacts(scene_dir)
    event_logs = _list_event_logs(scene_dir)
    research_logs = _list_research_logs(scene_dir)
    research_events = _read_jsonl_file(scene_dir / RESEARCH_EVENTS_PATH)
    severity = _runtime_scene_severity_summary(timeline)
    return {
        "timeline_events": len(timeline),
        "lifecycle_events": len(lifecycle),
        "raw_logs": len(raw_files),
        "conversation_logs": len(conversation_logs),
        "agent_logs": len(agent_logs),
        "artifacts": len(artifacts),
        "event_logs": len(event_logs),
        "research_files": len(research_logs),
        "research_events": len(research_events),
        "supervised_evolution_logs": _count_runtime_scene_files(scene_dir, f"{AGENT_DIR}/supervised_runs")
        + _count_runtime_scene_files(scene_dir, f"{AGENT_DIR}/supervised_worktree_runs"),
        "self_evolution_logs": _count_runtime_scene_files(scene_dir, f"{AGENT_DIR}/self_evolution_runs"),
        "errors": severity["errorCount"],
        "warnings": severity["warningCount"],
    }


def _count_runtime_scene_files(scene_dir: Path, relative_path: str) -> int:
    target = scene_dir / relative_path
    if target.is_file():
        return 1
    if not target.is_dir():
        return 0
    return sum(1 for item in target.rglob("*") if item.is_file())


def _runtime_scene_summary_sections() -> dict[str, dict[str, str]]:
    return {
        "startup": {
            "path": "raw/desktop-entry.log",
            "vbs_path": "raw/desktop-entry-vbs.log",
            "launcher_path": "raw/launcher-control.log",
            "purpose": "Desktop entry, launcher handoff, runtime manager, backend, browser, and supervisor startup breadcrumbs.",
        },
        "lifecycle": {
            "path": LIFECYCLE_PATH,
            "purpose": "Workbench startup, shutdown, recovery, supervision, and lifecycle state changes.",
        },
        "timeline": {
            "path": TIMELINE_PATH,
            "purpose": "Merged chronological event stream for the whole runtime scene package.",
        },
        "raw": {
            "path": "raw",
            "purpose": "Raw launcher, backend, frontend, browser, supervisor, and API output.",
        },
        "conversations": {
            "path": CONVERSATIONS_DIR,
            "purpose": "Per-session user, assistant, tool-call, and chat-review conversation breadcrumbs.",
        },
        "agent": {
            "path": AGENT_DIR,
            "purpose": "Agent turn and tool-call child logs used to diagnose reasoning and execution flow.",
        },
        "supervised_evolution": {
            "path": f"{AGENT_DIR}/supervised_runs",
            "worktree_path": f"{AGENT_DIR}/supervised_worktree_runs",
            "purpose": "Supervised evolution run, candidate, review, selection, promotion, and rollback breadcrumbs when present.",
        },
        "self_evolution": {
            "path": f"{AGENT_DIR}/self_evolution_runs",
            "purpose": "Unsupervised self-evolution run, checkpoint, reflection, guard, and validation breadcrumbs when present.",
        },
        "research": {
            "path": RESEARCH_DIR,
            "events_path": RESEARCH_EVENTS_PATH,
            "summary_path": RESEARCH_SUMMARY_PATH,
            "purpose": "Research theme discovery sessions, prompt and agent-template edits, searches, evidence extraction, theme selection, and theme-card operations.",
        },
        "artifacts": {
            "path": ARTIFACTS_DIR,
            "purpose": "Reports, generated files, snapshots, and other run artifacts referenced by events.",
        },
        "events": {
            "path": EVENTS_DIR,
            "purpose": "Component-specific structured event streams backing the merged timeline.",
        },
    }


def _scene_id(scene_dir: Path, manifest: dict) -> str:
    value = str(manifest.get("runtime_scene_id") or "").strip()
    if value:
        return value
    marker = "__"
    if marker in scene_dir.name:
        return scene_dir.name.split(marker, 1)[1].strip()
    return scene_dir.name


def _runtime_scene_display_name(scene_dir: Path, manifest: dict, scene_id: str) -> str:
    label = _display_name_time_label(str(manifest.get("started_at") or ""), scene_dir)
    trigger_label = _display_name_trigger_label(str(manifest.get("trigger") or ""))
    status_label = _display_name_status_label(manifest)
    parts = [item for item in [label, trigger_label, status_label] if item]
    if parts:
        return " · ".join(parts)
    return str(manifest.get("title") or scene_dir.name or scene_id).strip()


def _runtime_scene_package_index(scene_dir: Path, manifest: dict, scene_id: str) -> dict[str, Any]:
    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    raw_started_at = str(manifest.get("started_at") or package.get("started_at") or "").strip()
    started = _resolve_scene_started_at(raw_started_at, scene_dir)
    started_at = raw_started_at or (started.isoformat() if started else "")
    ended_at = str(manifest.get("ended_at") or "").strip() if _runtime_scene_has_completed(manifest) else ""
    ended = _parse_datetime(ended_at)
    display_name = _runtime_scene_display_name(scene_dir, manifest, scene_id)
    if not display_name:
        display_name = str(package.get("display_name") or scene_dir.name or scene_id).strip()
    started_local = started.astimezone() if started else None
    started_date = str(package.get("started_date") or "").strip()
    if not started_date and started_local:
        started_date = started_local.strftime("%Y-%m-%d")
    started_time = str(package.get("started_time") or "").strip()
    if not started_time and started_local:
        started_time = started_local.strftime("%H:%M:%S")
    started_at_local = str(package.get("started_at_local") or "").strip()
    if not started_at_local and started_local:
        started_at_local = started_local.isoformat()
    trigger_token = _package_index_trigger_token(str(manifest.get("trigger") or ""))
    status_token = _package_index_status_token(manifest)
    index_key = _join_index_key_parts([started_date, started_time.replace(":", "-"), trigger_token, status_token])
    duration_seconds = _scene_duration_seconds(started, ended)
    tags = _runtime_scene_index_tags(manifest, trigger_token, status_token)
    diagnosis = _runtime_scene_package_diagnosis_for_scene(scene_dir, manifest, scene_id)
    diagnosis_tags = _runtime_scene_diagnosis_tags(diagnosis)
    tags = [*tags, *[tag for tag in diagnosis_tags if tag not in tags]]
    search_text = _join_search_text(
        [
            display_name,
            index_key,
            started_at,
            started_at_local,
            started_date,
            started_time,
            scene_id,
            scene_dir.name,
            str(manifest.get("title") or ""),
            str(manifest.get("trigger") or ""),
            str(manifest.get("status") or ""),
            str(manifest.get("result") or ""),
            str(manifest.get("stop_reason") or ""),
            _runtime_scene_diagnosis_status(diagnosis.get("issueState") if isinstance(diagnosis.get("issueState"), dict) else {}),
            _runtime_scene_primary_cause_token(
                diagnosis,
                _runtime_scene_primary_issue_cluster(diagnosis.get("issueState") if isinstance(diagnosis.get("issueState"), dict) else {}),
                diagnosis.get("firstSignal") if isinstance(diagnosis.get("firstSignal"), dict) else None,
            ),
            _runtime_scene_primary_cause_label(
                _runtime_scene_primary_issue_cluster(diagnosis.get("issueState") if isinstance(diagnosis.get("issueState"), dict) else {}),
                diagnosis.get("firstSignal") if isinstance(diagnosis.get("firstSignal"), dict) else None,
            ),
            diagnosis.get("severity"),
            diagnosis.get("userSummary"),
            diagnosis.get("agentNextStep"),
            *tags,
        ]
    )
    return {
        "schemaVersion": 2,
        "packageId": scene_id,
        "displayName": display_name,
        "indexKey": index_key,
        "sortableTimestamp": started.isoformat() if started else started_at,
        "startedAt": started_at,
        "startedAtLocal": started_at_local,
        "startedDate": started_date,
        "startedTime": started_time,
        "endedAt": ended_at,
        "durationSeconds": duration_seconds,
        "searchText": search_text,
        "tags": tags,
        "summaryRef": SUMMARY_PATH,
    }


def _resolve_scene_started_at(started_at: str, scene_dir: Path) -> datetime | None:
    parsed = _parse_datetime(started_at)
    if parsed is not None:
        return parsed
    marker = "__"
    token = scene_dir.name.split(marker, 1)[0] if marker in scene_dir.name else scene_dir.name
    return _parse_directory_timestamp_token(token)


def _display_name_time_label(started_at: str, scene_dir: Path) -> str:
    parsed = _resolve_scene_started_at(started_at, scene_dir)
    if parsed is None:
        return ""
    local_value = parsed.astimezone()
    return local_value.strftime("%Y-%m-%d %H:%M")


def _display_name_trigger_label(trigger: str) -> str:
    normalized = str(trigger or "").strip().lower()
    if not normalized:
        return "工作台运行"
    return DISPLAY_NAME_TRIGGER_LABELS.get(normalized, _humanize_runtime_token(normalized))


def _display_name_status_label(manifest: dict) -> str:
    status = _runtime_scene_status(manifest)
    result = str(manifest.get("result") or "").strip().lower()
    stop_reason = str(manifest.get("stop_reason") or "").strip().lower()
    if status == "stopped" and (result or stop_reason):
        return DISPLAY_NAME_RESULT_LABELS.get(result) or _humanize_runtime_token(stop_reason or result)
    return DISPLAY_NAME_STATUS_LABELS.get(status, _humanize_runtime_token(status))


def _package_index_trigger_token(trigger: str) -> str:
    normalized = str(trigger or "").strip().lower()
    if not normalized:
        return "workbench-run"
    return PACKAGE_INDEX_TRIGGER_TOKENS.get(normalized, _slugify_index_token(normalized, default="workbench-run"))


def _package_index_status_token(manifest: dict) -> str:
    status = _runtime_scene_status(manifest)
    result = str(manifest.get("result") or "").strip().lower()
    stop_reason = str(manifest.get("stop_reason") or "").strip().lower()
    if status == "stopped" and (result or stop_reason):
        return PACKAGE_INDEX_RESULT_TOKENS.get(result) or _slugify_index_token(stop_reason or result, default="stopped")
    return PACKAGE_INDEX_STATUS_TOKENS.get(status, _slugify_index_token(status, default="unknown"))


def _runtime_scene_has_completed(manifest: dict) -> bool:
    status = _runtime_scene_status(manifest)
    return status not in {"running", "starting", "queued", "stopping"}


def _runtime_scene_status(manifest: dict) -> str:
    status = str(manifest.get("status") or "").strip().lower()
    if status and status != "unknown":
        return status
    if str(manifest.get("ended_at") or "").strip():
        return status or "unknown"
    return "running"


def _runtime_scene_index_tags(manifest: dict, trigger_token: str, status_token: str) -> list[str]:
    values = [
        "runtime-scene",
        "workbench-lifecycle",
        trigger_token,
        status_token,
        str(manifest.get("status") or ""),
        str(manifest.get("result") or ""),
        str(manifest.get("trigger") or ""),
        str(manifest.get("session_mode") or ""),
    ]
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = _slugify_index_token(value, default="")
        if not token or token in seen:
            continue
        seen.add(token)
        tags.append(token)
    return tags


def _scene_duration_seconds(started: datetime | None, ended: datetime | None) -> float | None:
    if started is None or ended is None:
        return None
    return max(0.0, round((ended - started).total_seconds(), 3))


def _join_index_key_parts(parts: list[str]) -> str:
    return "_".join(_slugify_index_token(part, default="") for part in parts if _slugify_index_token(part, default=""))


def _join_search_text(parts: list[str]) -> str:
    return " ".join(str(part or "").strip() for part in parts if str(part or "").strip())


def _slugify_index_token(value: str, *, default: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default
    chars: list[str] = []
    previous_dash = False
    for char in text:
        if char.isalnum():
            chars.append(char)
            previous_dash = False
            continue
        if char in {"-", "_", " ", ".", ":", "/"} and not previous_dash:
            chars.append("-")
            previous_dash = True
    token = "".join(chars).strip("-")
    return token or default


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_directory_timestamp_token(value: str) -> datetime | None:
    text = str(value or "").strip()
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S"):
        try:
            parsed = datetime.strptime(text, pattern)
        except ValueError:
            continue
        return parsed.replace(tzinfo=UTC)
    return None


def _humanize_runtime_token(value: str) -> str:
    token = str(value or "").strip(" ._-")
    if not token:
        return ""
    return token.replace("_", " ").replace("-", " ")


def _read_scene_timeline(scene_dir: Path) -> list[dict]:
    timeline_rows = _read_jsonl_file(scene_dir / TIMELINE_PATH)
    if timeline_rows:
        timeline = [
            _event_payload_to_client_item(entry, scene_dir, "timeline")
            for entry in timeline_rows
        ]
        timeline.sort(key=lambda item: (item["timestamp"], item["component"], item["seq"]))
        return _fold_repeated_work_run_snapshots(timeline)

    events_dir = scene_dir / "events"
    timeline: list[dict] = []
    if not events_dir.exists() or not events_dir.is_dir():
        return timeline

    for file_path in sorted(events_dir.glob("*.jsonl")):
        component = file_path.stem
        for entry in _read_jsonl_file(file_path):
            timeline.append(_event_payload_to_client_item(entry, scene_dir, component))

    timeline.sort(key=lambda item: (item["timestamp"], item["component"], item["seq"]))
    return _fold_repeated_work_run_snapshots(timeline)


def _fold_repeated_work_run_snapshots(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    folded: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    repeat_count = 0
    last_timestamp = ""

    def flush_pending() -> None:
        nonlocal pending, repeat_count, last_timestamp
        if pending is None:
            return
        if repeat_count <= 1:
            folded.append(pending)
        else:
            folded.append(_work_run_snapshot_summary_event(pending, repeat_count, last_timestamp))
        pending = None
        repeat_count = 0
        last_timestamp = ""

    for event in events:
        if str(event.get("eventCode") or "") != WORK_RUN_SNAPSHOT_EVENT_CODE:
            flush_pending()
            folded.append(event)
            continue
        if pending is None:
            pending = event
            repeat_count = 1
            last_timestamp = str(event.get("timestamp") or "")
            continue
        if _work_run_snapshot_fold_key(event) == _work_run_snapshot_fold_key(pending):
            repeat_count += 1
            last_timestamp = str(event.get("timestamp") or last_timestamp)
            continue
        flush_pending()
        pending = event
        repeat_count = 1
        last_timestamp = str(event.get("timestamp") or "")
    flush_pending()
    return folded


def _work_run_snapshot_fold_key(event: dict[str, Any]) -> tuple[str, str, str, str]:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    return (
        str(fields.get("runKind") or ""),
        str(fields.get("runId") or ""),
        str(fields.get("status") or ""),
        str(fields.get("phase") or ""),
    )


def _work_run_snapshot_summary_event(event: dict[str, Any], repeat_count: int, last_timestamp: str) -> dict[str, Any]:
    fields = dict(event.get("fields") if isinstance(event.get("fields"), dict) else {})
    first_timestamp = str(event.get("timestamp") or "")
    fields.update(
        {
            "repeatCount": repeat_count,
            "foldedEvent": True,
            "originalEventCode": WORK_RUN_SNAPSHOT_EVENT_CODE,
            "firstTimestamp": first_timestamp,
            "lastTimestamp": last_timestamp or first_timestamp,
        }
    )
    run_kind = str(fields.get("runKind") or "work_run")
    run_id = str(fields.get("runId") or "")
    status = str(fields.get("status") or "")
    phase = str(fields.get("phase") or "")
    return {
        **event,
        "eventCode": WORK_RUN_SNAPSHOT_SUMMARY_EVENT_CODE,
        "message": (
            f"Folded {repeat_count} repeated work run snapshots: "
            f"{run_kind}/{run_id} {status} {phase}".strip()
        ),
        "fields": fields,
    }


def _read_scene_lifecycle(scene_dir: Path, fallback_timeline: list[dict] | None = None) -> list[dict]:
    lifecycle_path = scene_dir / LIFECYCLE_PATH
    events = [
        _event_payload_to_client_item(row, scene_dir, "lifecycle")
        for row in _read_jsonl_file(lifecycle_path)
    ]
    if events:
        events.sort(key=lambda item: (item["timestamp"], item["component"], item["seq"]))
        return events
    return [
        item
        for item in list(fallback_timeline or [])
        if str(item.get("phase") or "").strip().lower() in LIFECYCLE_INDEX_PHASES
        or str(item.get("eventCode") or "").startswith("runtime.scene.")
    ]


def _event_payload_to_client_item(entry: dict[str, Any], scene_dir: Path, component: str) -> dict[str, Any]:
    return {
        "runtimeSceneId": str(entry.get("runtime_scene_id") or _scene_id(scene_dir, {})),
        "component": str(entry.get("component") or component),
        "phase": str(entry.get("phase") or ""),
        "eventCode": str(entry.get("event_code") or ""),
        "level": str(entry.get("level") or "info"),
        "message": str(entry.get("message") or ""),
        "timestamp": str(entry.get("ts") or ""),
        "seq": int(entry.get("seq") or 0),
        "outcome": str(entry.get("outcome") or ""),
        "fields": entry.get("fields") if isinstance(entry.get("fields"), dict) else {},
        "rawRefs": entry.get("raw_refs") if isinstance(entry.get("raw_refs"), list) else [],
    }


def _read_jsonl_file(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return rows
    for line in lines:
        text = str(line or "").strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _load_launcher_state() -> dict[str, Any]:
    try:
        payload = json.loads(LAUNCHER_STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _list_raw_files(scene_dir: Path) -> list[dict]:
    raw_dir = scene_dir / "raw"
    items: list[dict] = []
    if not raw_dir.exists() or not raw_dir.is_dir():
        return items
    for file_path in sorted(raw_dir.rglob("*")):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(scene_dir).as_posix()
        items.append(
            {
                "path": relative,
                "label": RAW_LABELS.get(relative, file_path.name),
                "size": file_path.stat().st_size,
                "language": LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text"),
            }
        )
    return items


def _list_conversation_logs(scene_dir: Path) -> list[dict[str, Any]]:
    return _list_package_files(scene_dir, CONVERSATIONS_DIR, label_prefix="Conversation")


def _list_agent_logs(scene_dir: Path) -> list[dict[str, Any]]:
    return _list_package_files(scene_dir, AGENT_DIR, label_prefix="Agent")


def _list_artifacts(scene_dir: Path) -> list[dict[str, Any]]:
    return _list_package_files(scene_dir, ARTIFACTS_DIR, label_prefix="Artifact")


def _list_event_logs(scene_dir: Path) -> list[dict[str, Any]]:
    return _list_package_files(scene_dir, EVENTS_DIR, label_prefix="Event stream")


def _list_research_logs(scene_dir: Path) -> list[dict[str, Any]]:
    return _list_package_files(scene_dir, RESEARCH_DIR, label_prefix="Research")


def _next_research_event_seq(scene_dir: Path) -> int:
    last_seq = 0
    for row in _read_jsonl_file(scene_dir / RESEARCH_EVENTS_PATH):
        try:
            last_seq = max(last_seq, int(row.get("seq") or 0))
        except (TypeError, ValueError):
            continue
    return last_seq + 1


def _save_runtime_scene_research_summary(scene_dir: Path) -> None:
    events = _read_jsonl_file(scene_dir / RESEARCH_EVENTS_PATH)
    if not events:
        return
    summary_path = _resolve_scene_child(scene_dir, RESEARCH_SUMMARY_PATH)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(_runtime_scene_research_summary_payload(events), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _runtime_scene_research_summary_payload(events: list[dict[str, Any]]) -> dict[str, Any]:
    event_codes: dict[str, int] = {}
    phases: dict[str, int] = {}
    agents: dict[str, int] = {}
    sessions: dict[str, dict[str, Any]] = {}
    latest_event: dict[str, Any] | None = None
    for event in events:
        event_code = str(event.get("event_code") or "research.event").strip()
        phase = str(event.get("phase") or "theme_discovery").strip()
        agent_key = str(event.get("agent_key") or "").strip()
        session_id = str(event.get("session_id") or "").strip()
        timestamp = str(event.get("ts") or "").strip()
        event_codes[event_code] = event_codes.get(event_code, 0) + 1
        phases[phase] = phases.get(phase, 0) + 1
        if agent_key:
            agents[agent_key] = agents.get(agent_key, 0) + 1
        if session_id:
            session = sessions.setdefault(
                session_id,
                {
                    "sessionId": session_id,
                    "eventCount": 0,
                    "latestEventAt": "",
                    "latestEventCode": "",
                },
            )
            session["eventCount"] = int(session.get("eventCount") or 0) + 1
            if timestamp >= str(session.get("latestEventAt") or ""):
                session["latestEventAt"] = timestamp
                session["latestEventCode"] = event_code
        if latest_event is None or timestamp >= str(latest_event.get("ts") or ""):
            latest_event = event
    return {
        "schema_version": 1,
        "event_count": len(events),
        "session_count": len(sessions),
        "agent_count": len(agents),
        "event_codes": event_codes,
        "phases": phases,
        "agents": agents,
        "sessions": sorted(sessions.values(), key=lambda item: str(item.get("latestEventAt") or ""), reverse=True),
        "latest_event": _runtime_scene_research_summary_event(latest_event),
        "events_path": RESEARCH_EVENTS_PATH,
        "generated_at": _now_utc(),
    }


def _runtime_scene_research_summary_event(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    return {
        "timestamp": str(event.get("ts") or ""),
        "eventCode": str(event.get("event_code") or ""),
        "phase": str(event.get("phase") or ""),
        "level": str(event.get("level") or ""),
        "outcome": str(event.get("outcome") or ""),
        "message": str(event.get("message") or ""),
        "sessionId": str(event.get("session_id") or ""),
        "agentKey": str(event.get("agent_key") or ""),
    }


def _list_package_files(scene_dir: Path, relative_dir: str, *, label_prefix: str) -> list[dict[str, Any]]:
    root = scene_dir / relative_dir
    items: list[dict[str, Any]] = []
    if not root.exists() or not root.is_dir():
        return items
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(scene_dir).as_posix()
        items.append(
            {
                "path": relative,
                "label": f"{label_prefix}: {file_path.stem}",
                "size": file_path.stat().st_size,
                "language": LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text"),
                "updatedAt": _file_timestamp(file_path),
            }
        )
    return items


def _runtime_scene_package_summary(
    *,
    timeline: list[dict],
    lifecycle: list[dict],
    raw_files: list[dict],
    conversation_logs: list[dict],
    agent_logs: list[dict],
    artifacts: list[dict],
    event_logs: list[dict],
    research_logs: list[dict] | None = None,
) -> dict[str, Any]:
    research_logs = research_logs if isinstance(research_logs, list) else []
    severity_summary = _runtime_scene_severity_summary(timeline)
    return {
        "schemaVersion": 2,
        "eventCount": len(timeline),
        "lifecycleEventCount": len(lifecycle),
        "rawLogCount": len(raw_files),
        "conversationLogCount": len(conversation_logs),
        "agentLogCount": len(agent_logs),
        "artifactCount": len(artifacts),
        "eventLogCount": len(event_logs),
        "researchLogCount": len(research_logs),
        "errorCount": severity_summary["errorCount"],
        "warningCount": severity_summary["warningCount"],
    }


def _runtime_scene_package_diagnosis_for_scene(
    scene_dir: Path,
    manifest: dict[str, Any],
    scene_id: str,
) -> dict[str, Any]:
    timeline = _read_scene_timeline(scene_dir)
    lifecycle = _read_scene_lifecycle(scene_dir, timeline)
    diagnosis = _runtime_scene_package_diagnosis(
        scene_dir=scene_dir,
        scene_id=scene_id,
        manifest=manifest,
        timeline=timeline,
        lifecycle=lifecycle,
        raw_files=_list_raw_files(scene_dir),
        conversation_logs=_list_conversation_logs(scene_dir),
        agent_logs=_list_agent_logs(scene_dir),
        artifacts=_list_artifacts(scene_dir),
        event_logs=_list_event_logs(scene_dir),
    )
    return diagnosis


def _runtime_scene_primary_issue_cluster(issue_state: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("firstActiveCluster", "firstPolicyCluster", "firstHistoricalCluster"):
        value = issue_state.get(key)
        if isinstance(value, dict):
            return value
    for key in ("activeClusters", "policyClusters", "historicalClusters"):
        value = issue_state.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    return item
    return None


def _runtime_scene_diagnosis_status(issue_state: dict[str, Any]) -> str:
    if int(issue_state.get("activeClusterCount") or 0):
        return "active_issue"
    if int(issue_state.get("policyClusterCount") or 0) or int(issue_state.get("policySignalCount") or 0):
        return "policy_signal"
    if int(issue_state.get("historicalClusterCount") or 0):
        return "recovered_issue"
    if int(issue_state.get("controlSignalCount") or 0):
        return "control_only"
    return "clear"


def _runtime_scene_primary_cause_token(
    diagnosis: dict[str, Any],
    primary_cluster: dict[str, Any] | None,
    first_signal: dict[str, Any] | None,
) -> str:
    source = primary_cluster if isinstance(primary_cluster, dict) else first_signal if isinstance(first_signal, dict) else {}
    component = str(source.get("component") or "").strip()
    event_code = str(source.get("eventCode") or "").strip()
    if component or event_code:
        return _slugify_index_token("_".join(part for part in (component, event_code) if part), default="runtime-signal")
    severity = str(diagnosis.get("severity") or "info").strip()
    return _slugify_index_token(f"runtime-{severity}", default="runtime-clear")


def _runtime_scene_primary_cause_label(
    primary_cluster: dict[str, Any] | None,
    first_signal: dict[str, Any] | None,
) -> str:
    if isinstance(primary_cluster, dict):
        return _runtime_scene_issue_cluster_display(primary_cluster)
    if isinstance(first_signal, dict):
        return " / ".join(
            part
            for part in (
                str(first_signal.get("component") or "").strip(),
                str(first_signal.get("eventCode") or "").strip(),
            )
            if part
        )
    return ""


def _runtime_scene_diagnosis_evidence_paths(
    diagnosis: dict[str, Any],
    primary_cluster: dict[str, Any] | None,
    first_signal: dict[str, Any] | None,
) -> list[str]:
    paths: list[str] = []
    for source in (primary_cluster, first_signal):
        if not isinstance(source, dict):
            continue
        for item in source.get("rawRefs") if isinstance(source.get("rawRefs"), list) else []:
            if isinstance(item, dict):
                _append_unique_path(paths, str(item.get("path") or ""))
    for item in diagnosis.get("keyEntries") if isinstance(diagnosis.get("keyEntries"), list) else []:
        if isinstance(item, dict):
            _append_unique_path(paths, str(item.get("path") or ""))
    for path in diagnosis.get("recommendedOrder") if isinstance(diagnosis.get("recommendedOrder"), list) else []:
        _append_unique_path(paths, str(path or ""))
    return paths[:6]


def _runtime_scene_diagnosis_tags(diagnosis: dict[str, Any]) -> list[str]:
    issue_state = diagnosis.get("issueState") if isinstance(diagnosis.get("issueState"), dict) else {}
    primary_cluster = _runtime_scene_primary_issue_cluster(issue_state)
    first_signal = diagnosis.get("firstSignal") if isinstance(diagnosis.get("firstSignal"), dict) else None
    tags = [
        f"diagnosis-{_runtime_scene_diagnosis_status(issue_state)}",
        f"severity-{diagnosis.get('severity') or 'info'}",
        _runtime_scene_primary_cause_token(diagnosis, primary_cluster, first_signal),
    ]
    return [_slugify_index_token(tag, default="") for tag in tags if _slugify_index_token(tag, default="")]


def _runtime_scene_package_diagnosis(
    *,
    scene_dir: Path,
    scene_id: str,
    manifest: dict[str, Any],
    timeline: list[dict],
    lifecycle: list[dict],
    raw_files: list[dict],
    conversation_logs: list[dict],
    agent_logs: list[dict],
    artifacts: list[dict],
    event_logs: list[dict],
) -> dict[str, Any]:
    severity_summary = _runtime_scene_severity_summary(timeline)
    issue_state = _runtime_scene_issue_state(timeline)
    severity = str(issue_state.get("severity") or "info")
    first_signal = _runtime_scene_first_signal(timeline, issue_state=issue_state)
    if first_signal is None:
        first_signal = _runtime_scene_first_key_event(lifecycle, timeline)
    startup_trace = _runtime_scene_startup_trace(scene_dir=scene_dir, manifest=manifest, timeline=timeline)
    recommended_order = _runtime_scene_recommended_reading_order(
        startup_trace=startup_trace,
        raw_files=raw_files,
        conversation_logs=conversation_logs,
        agent_logs=agent_logs,
        artifacts=artifacts,
        event_logs=event_logs,
        first_signal=first_signal,
    )
    key_entries = _runtime_scene_key_entries(
        scene_dir=scene_dir,
        manifest=manifest,
        startup_trace=startup_trace,
        raw_files=raw_files,
        conversation_logs=conversation_logs,
        agent_logs=agent_logs,
        artifacts=artifacts,
        event_logs=event_logs,
        first_signal=first_signal,
    )
    evidence_paths = _runtime_scene_diagnosis_evidence_paths(
        {"keyEntries": key_entries, "recommendedOrder": recommended_order},
        _runtime_scene_primary_issue_cluster(issue_state),
        _runtime_scene_diagnosis_signal_payload(first_signal),
    )
    return {
        "schemaVersion": 1,
        "severity": severity,
        "userSummary": _runtime_scene_diagnosis_user_summary(
            severity=severity,
            manifest=manifest,
            timeline=timeline,
            lifecycle=lifecycle,
            severity_summary=severity_summary,
            issue_state=issue_state,
            first_signal=first_signal,
            child_log_count=len(raw_files) + len(conversation_logs) + len(agent_logs) + len(artifacts) + len(event_logs),
            startup_trace=startup_trace,
        ),
        "agentNextStep": _runtime_scene_diagnosis_next_step(
            scene_dir_name=scene_dir.name,
            scene_id=scene_id,
            severity=severity,
            issue_state=issue_state,
            first_signal=first_signal,
            recommended_order=recommended_order,
            key_entries=key_entries,
            startup_trace=startup_trace,
        ),
        "issueState": issue_state,
        "firstSignal": _runtime_scene_diagnosis_signal_payload(first_signal),
        "startupTrace": startup_trace,
        "recommendedOrder": recommended_order,
        "keyEntries": key_entries,
        "evidencePaths": evidence_paths,
    }


def _runtime_scene_first_signal(events: list[dict], *, issue_state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    active = issue_state.get("firstActiveSignal") if isinstance(issue_state, dict) else None
    if isinstance(active, dict):
        return active
    policy = issue_state.get("firstPolicySignal") if isinstance(issue_state, dict) else None
    if isinstance(policy, dict):
        return policy
    historical = issue_state.get("firstHistoricalSignal") if isinstance(issue_state, dict) else None
    if isinstance(historical, dict):
        return historical
    for target_severity in ("error", "warning"):
        for event in events:
            severity = _runtime_scene_event_severity(event)
            if severity == target_severity:
                return {**event, "diagnosisSeverity": severity}
    return None


def _runtime_scene_first_key_event(lifecycle: list[dict], timeline: list[dict]) -> dict[str, Any] | None:
    for event in lifecycle:
        if str(event.get("eventCode") or "").strip():
            return {**event, "diagnosisSeverity": _runtime_scene_event_severity(event)}
    for event in timeline:
        if str(event.get("eventCode") or "").strip():
            return {**event, "diagnosisSeverity": _runtime_scene_event_severity(event)}
    return None


def _runtime_scene_issue_state(events: list[dict]) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        severity = _runtime_scene_event_severity(event)
        if severity not in {"error", "warning"}:
            continue
        problem = _runtime_scene_signal_kind(event)
        signals.append(
            {
                "index": index,
                "severity": severity,
                "problem": problem,
                "event": {**event, "diagnosisSeverity": severity},
            }
        )

    active: list[dict[str, Any]] = []
    policy: list[dict[str, Any]] = []
    historical: list[dict[str, Any]] = []
    control: list[dict[str, Any]] = []
    for signal in signals:
        problem = str(signal.get("problem") or "")
        event = signal.get("event")
        if not isinstance(event, dict):
            continue
        if problem == "control":
            control.append(signal)
            continue
        if problem == "policy":
            policy.append(signal)
            continue
        if _runtime_scene_signal_has_later_resolution(events, signal):
            historical.append(signal)
            continue
        active.append(signal)

    active_clusters = _runtime_scene_issue_clusters(active)
    policy_clusters = _runtime_scene_issue_clusters(policy)
    historical_clusters = _runtime_scene_issue_clusters(historical)
    first_active_cluster = active_clusters[0] if active_clusters else None
    first_policy_cluster = policy_clusters[0] if policy_clusters else None
    first_historical_cluster = historical_clusters[0] if historical_clusters else None
    first_active = _runtime_scene_first_ranked_signal(active)
    first_policy = _runtime_scene_first_ranked_signal(policy)
    first_historical = _runtime_scene_first_ranked_signal(historical)
    return {
        "schemaVersion": 1,
        "severity": _runtime_scene_issue_state_severity(active, policy),
        "activeErrorCount": _count_issue_signals(active, "error"),
        "activeWarningCount": _count_issue_signals(active, "warning"),
        "policySignalCount": len(policy),
        "historicalErrorCount": _count_issue_signals(historical, "error"),
        "historicalWarningCount": _count_issue_signals(historical, "warning"),
        "activeClusterCount": len(active_clusters),
        "policyClusterCount": len(policy_clusters),
        "historicalClusterCount": len(historical_clusters),
        "controlSignalCount": len(control),
        "activeClusters": active_clusters,
        "policyClusters": policy_clusters,
        "historicalClusters": historical_clusters,
        "firstActiveCluster": first_active_cluster,
        "firstPolicyCluster": first_policy_cluster,
        "firstHistoricalCluster": first_historical_cluster,
        "firstActiveSignal": first_active,
        "firstPolicySignal": first_policy,
        "firstHistoricalSignal": first_historical,
    }


def _runtime_scene_issue_clusters(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    cluster_order: list[tuple[str, ...]] = []
    for signal in signals:
        event = signal.get("event")
        if not isinstance(event, dict):
            continue
        key = _runtime_scene_issue_cluster_key(event)
        cluster = clusters_by_key.get(key)
        timestamp = str(event.get("timestamp") or "")
        representative = {**event, "diagnosisSeverity": str(signal.get("severity") or _runtime_scene_event_severity(event))}
        if cluster is None:
            raw_refs = _runtime_scene_signal_raw_refs(representative)
            cluster = {
                "schemaVersion": 1,
                "severity": str(signal.get("severity") or "info"),
                "component": str(event.get("component") or ""),
                "phase": str(event.get("phase") or ""),
                "eventCode": str(event.get("eventCode") or ""),
                "label": _runtime_scene_issue_cluster_label(event),
                "repeatCount": 1,
                "firstTimestamp": timestamp,
                "lastTimestamp": timestamp,
                "representativeSignal": representative,
                "rawRefs": raw_refs,
                "identity": _runtime_scene_event_identity(event),
            }
            representative["rawRefs"] = raw_refs
            clusters_by_key[key] = cluster
            cluster_order.append(key)
            continue
        cluster["repeatCount"] = int(cluster.get("repeatCount") or 0) + 1
        if timestamp:
            cluster["lastTimestamp"] = timestamp
        if not str(cluster.get("firstTimestamp") or "") and timestamp:
            cluster["firstTimestamp"] = timestamp
    clusters = [clusters_by_key[key] for key in cluster_order]
    clusters.sort(key=_runtime_scene_issue_cluster_sort_key)
    return clusters


def _runtime_scene_issue_cluster_key(event: dict[str, Any]) -> tuple[str, ...]:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    parts = [
        str(event.get("component") or ""),
        str(event.get("eventCode") or ""),
        str(event.get("phase") or ""),
    ]
    identity_parts: list[str] = []
    for key in ISSUE_IDENTITY_FIELD_KEYS:
        value = str(fields.get(key) or "").strip()
        if value:
            identity_parts.append(f"{key}={value}")
    if identity_parts:
        parts.extend(identity_parts)
    else:
        message_signature = _runtime_scene_signal_message_signature(str(event.get("message") or ""))
        if message_signature:
            parts.append(f"message={message_signature}")
    return tuple(parts)


def _runtime_scene_issue_cluster_sort_key(cluster: dict[str, Any]) -> tuple[int, int, str, str]:
    severity = str(cluster.get("severity") or "")
    severity_rank = 0 if severity == "error" else 1 if severity == "warning" else 2
    repeat_count = int(cluster.get("repeatCount") or 0)
    return (severity_rank, -repeat_count, str(cluster.get("firstTimestamp") or ""), str(cluster.get("label") or ""))


def _runtime_scene_issue_cluster_label(event: dict[str, Any] | None) -> str:
    if not isinstance(event, dict):
        return "未命名问题簇"
    parts = [
        str(event.get("component") or "").strip(),
        str(event.get("eventCode") or "").strip(),
    ]
    return " / ".join(part for part in parts if part) or _runtime_scene_signal_label(event)


def _runtime_scene_issue_cluster_display(cluster: dict[str, Any] | None) -> str:
    if not isinstance(cluster, dict):
        return "未命名问题簇"
    label = str(cluster.get("label") or "").strip() or _runtime_scene_issue_cluster_label(cluster.get("representativeSignal") if isinstance(cluster.get("representativeSignal"), dict) else None)
    repeat_count = int(cluster.get("repeatCount") or 0)
    if repeat_count > 1:
        return f"{label} ×{repeat_count}"
    return label


def _runtime_scene_signal_message_signature(message: str) -> str:
    text = " ".join(str(message or "").split())
    if not text:
        return ""
    first_line = text.split(" | ", 1)[0].splitlines()[0]
    return _truncate_text(first_line, 160)


def _runtime_scene_signal_kind(event: dict[str, Any]) -> str:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    if str(event.get("eventCode") or "") == "conversation.next_state_signal.recorded":
        kind = str(fields.get("kind") or event.get("outcome") or "").strip().lower()
        if kind in NON_PROBLEM_NEXT_STATE_KINDS:
            return "control"
    if str(event.get("component") or "") == "tool_registry":
        if str(event.get("outcome") or "").strip().lower() == "blocked":
            return "policy"
        if str(fields.get("testPolicy") or "").strip().lower() == "blocked":
            return "policy"
    if str(event.get("eventCode") or "").endswith(".blocked"):
        if str(fields.get("source") or "").strip().lower() == "built_in":
            return "policy"
    return "problem"


def _runtime_scene_signal_raw_refs(event: dict[str, Any]) -> list[dict[str, Any]]:
    raw_refs = event.get("rawRefs") if isinstance(event.get("rawRefs"), list) else []
    normalized: list[dict[str, Any]] = []
    for item in raw_refs:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip().replace("\\", "/")
        if not path:
            continue
        ref: dict[str, Any] = {"path": path}
        if item.get("tail_lines") is not None:
            ref["tail_lines"] = item.get("tail_lines")
        elif item.get("tailLines") is not None:
            ref["tail_lines"] = item.get("tailLines")
        else:
            ref["tail_lines"] = 80
        normalized.append(ref)
    if normalized:
        return normalized

    component = str(event.get("component") or "").strip()
    fallback_path = _runtime_scene_component_evidence_path(component)
    if fallback_path:
        return [{"path": fallback_path, "tail_lines": 80}]
    return []


def _runtime_scene_component_evidence_path(component: str) -> str:
    normalized = str(component or "").strip().lower()
    if normalized == "backend":
        return BACKEND_API_RAW_PATH
    if normalized == "browser":
        return "raw/browser.log"
    if normalized == "browser_page":
        return BROWSER_TELEMETRY_RAW_PATH
    if normalized == "frontend":
        return "raw/frontend.build.log"
    if normalized == "launcher":
        return "raw/launcher-control.log"
    if normalized == "supervisor":
        return "raw/supervisor.log"
    if normalized == "conversation":
        return f"{EVENTS_DIR}/conversation.jsonl"
    if normalized in {"agent", "llm", "runtime_manager", "tool_executor", "work_run"}:
        return f"{EVENTS_DIR}/{normalized}.jsonl"
    if normalized:
        return f"{EVENTS_DIR}/{_slugify_index_token(normalized, default='component')}.jsonl"
    return TIMELINE_PATH


def _runtime_scene_signal_has_later_resolution(events: list[dict], signal: dict[str, Any]) -> bool:
    event = signal.get("event")
    index = int(signal.get("index") or 0)
    if not isinstance(event, dict):
        return False
    identity = _runtime_scene_event_identity(event)
    for later in events[index + 1 :]:
        if not _runtime_scene_resolution_event_matches(later, event, identity):
            continue
        return True
    return False


def _runtime_scene_event_identity(event: dict[str, Any]) -> dict[str, str]:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    identity: dict[str, str] = {}
    for key in ISSUE_IDENTITY_FIELD_KEYS:
        value = str(fields.get(key) or "").strip()
        if value:
            identity[key] = value
    return identity


def _runtime_scene_resolution_event_matches(
    candidate: dict[str, Any],
    source: dict[str, Any],
    identity: dict[str, str],
) -> bool:
    if _runtime_scene_event_severity(candidate) in {"error", "warning"}:
        return False
    outcome = str(candidate.get("outcome") or "").strip().lower()
    status = str(candidate.get("status") or "").strip().lower()
    fields = candidate.get("fields") if isinstance(candidate.get("fields"), dict) else {}
    field_outcome = str(fields.get("outcome") or "").strip().lower()
    field_status = str(fields.get("status") or fields.get("resultStatus") or "").strip().lower()
    event_code = str(candidate.get("eventCode") or "").strip().lower()
    if (
        outcome not in ISSUE_RESOLUTION_OUTCOMES
        and status not in ISSUE_RESOLUTION_OUTCOMES
        and field_outcome not in ISSUE_RESOLUTION_OUTCOMES
        and field_status not in ISSUE_RESOLUTION_OUTCOMES
        and not event_code.endswith((".recovered", ".resolved", ".fallback", ".fallback_activated"))
    ):
        return False
    if str(candidate.get("component") or "") != str(source.get("component") or ""):
        return False
    if identity:
        candidate_identity = _runtime_scene_event_identity(candidate)
        return any(candidate_identity.get(key) == value for key, value in identity.items())
    return str(candidate.get("phase") or "") == str(source.get("phase") or "")


def _runtime_scene_first_ranked_signal(signals: list[dict[str, Any]]) -> dict[str, Any] | None:
    for target_severity in ("error", "warning"):
        for signal in signals:
            if str(signal.get("severity") or "") == target_severity and isinstance(signal.get("event"), dict):
                return signal["event"]
    return None


def _runtime_scene_issue_state_severity(
    active_signals: list[dict[str, Any]],
    policy_signals: list[dict[str, Any]] | None = None,
) -> str:
    combined_signals = [*active_signals, *(policy_signals or [])]
    if any(str(signal.get("severity") or "") == "error" for signal in combined_signals):
        return "error"
    if any(str(signal.get("severity") or "") == "warning" for signal in combined_signals):
        return "warning"
    return "info"


def _count_issue_signals(signals: list[dict[str, Any]], severity: str) -> int:
    return len([signal for signal in signals if str(signal.get("severity") or "") == severity])


STARTUP_TRACE_STEPS = [
    {
        "id": "desktop_entry_vbs",
        "label": "桌面入口 VBS",
        "eventCodes": {
            "desktop_entry_vbs.python_runtime.selected",
            "desktop_entry_vbs.started",
            "desktop_entry_vbs.launched",
        },
        "fallbackPaths": ("raw/desktop-entry-vbs.log",),
    },
    {
        "id": "desktop_entry",
        "label": "桌面入口",
        "eventCodes": {
            "desktop_entry.python_runtime.selected",
            "desktop_entry.started",
            "desktop_entry.launcher_action.started",
        },
        "fallbackPaths": ("raw/desktop-entry.log",),
    },
    {
        "id": "launcher_control",
        "label": "启动控制",
        "eventCodes": {
            "launcher.python_runtime.selected",
            "launcher.browser.focus.succeeded",
        },
        "fallbackPaths": ("raw/launcher-control.log",),
    },
    {
        "id": "runtime_scene",
        "label": "日志包创建",
        "eventCodes": {"runtime.scene.created"},
        "fallbackPaths": (TIMELINE_PATH,),
    },
    {
        "id": "frontend",
        "label": "前端依赖与构建",
        "eventCodes": {
            "frontend.dependencies.current",
            "frontend.dependencies.install.started",
            "frontend.dependencies.install.failed",
            "frontend.build.current",
            "frontend.build.started",
            "frontend.build.succeeded",
            "frontend.build.failed",
        },
        "fallbackPaths": ("raw/frontend.build.log",),
    },
    {
        "id": "backend_dependencies",
        "label": "后端依赖",
        "eventCodes": {
            "backend.dependencies.current",
            "backend.dependencies.install.started",
            "backend.dependencies.install.failed",
        },
        "fallbackPaths": ("events/launcher.jsonl",),
    },
    {
        "id": "backend_start",
        "label": "后端启动与健康检查",
        "eventCodes": {
            "backend.start.requested",
            "backend.process.started",
            "backend.health.succeeded",
            "backend.health.failed",
            "runtime.scene.backend_live",
        },
        "fallbackPaths": ("raw/backend.stdout.log", "raw/backend.stderr.log", "events/backend.jsonl"),
    },
    {
        "id": "browser",
        "label": "浏览器窗口",
        "eventCodes": {
            "runtime.scene.headless_upgrade.started",
            "runtime.scene.headless_upgrade.succeeded",
            "browser.window.launch.requested",
            "browser.window.opened",
            "browser.window.launch.failed",
        },
        "fallbackPaths": ("raw/browser.log", "events/browser.jsonl"),
    },
    {
        "id": "supervisor",
        "label": "监督器",
        "eventCodes": {"supervisor.started", "launcher.monitor.started", "launcher.monitor.workbench_open"},
        "fallbackPaths": ("events/supervisor.jsonl", "raw/supervisor.log", "raw/supervisor.stderr.log"),
    },
    {
        "id": "ready",
        "label": "工作台就绪",
        "eventCodes": {"runtime.scene.ready", "runtime.scene.backend_live"},
        "fallbackPaths": (LIFECYCLE_PATH,),
    },
]


def _runtime_scene_startup_trace(
    *,
    scene_dir: Path,
    manifest: dict[str, Any],
    timeline: list[dict],
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    missing: list[str] = []
    for spec in STARTUP_TRACE_STEPS:
        event = _first_event_by_code(timeline, spec["eventCodes"])
        evidence_path = _startup_step_evidence_path(scene_dir, event, spec["fallbackPaths"])
        raw_event = event or _startup_step_raw_event(scene_dir, evidence_path, spec["eventCodes"])
        timestamp = _startup_step_timestamp(raw_event)
        event_code = str(
            (raw_event or {}).get("eventCode")
            or (raw_event or {}).get("event_code")
            or (raw_event or {}).get("event")
            or ""
        )
        message = _truncate_text(str((raw_event or {}).get("message") or (raw_event or {}).get("details") or ""), 240)
        status = "recorded" if event or evidence_path else "missing"
        if status == "missing":
            missing.append(str(spec["id"]))
        steps.append(
            {
                "id": str(spec["id"]),
                "label": str(spec["label"]),
                "status": status,
                "timestamp": timestamp,
                "eventCode": event_code,
                "message": message,
                "evidencePath": evidence_path,
            }
        )

    return {
        "schemaVersion": 1,
        "summary": _runtime_scene_startup_trace_summary(manifest, steps, missing),
        "missingStepIds": missing,
        "steps": steps,
    }


def _first_event_by_code(events: list[dict], event_codes: set[str]) -> dict[str, Any] | None:
    for event in events:
        if str(event.get("eventCode") or "").strip() in event_codes:
            return event
    return None


def _startup_step_evidence_path(scene_dir: Path, event: dict[str, Any] | None, fallback_paths: tuple[str, ...]) -> str:
    raw_refs = event.get("rawRefs") if isinstance(event, dict) else []
    for item in raw_refs if isinstance(raw_refs, list) else []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip().replace("\\", "/")
        if path and _scene_child_has_content(scene_dir, path):
            return path
    for path in fallback_paths:
        if _scene_child_has_content(scene_dir, path):
            return path
    return ""


def _startup_step_raw_event(
    scene_dir: Path,
    evidence_path: str,
    event_codes: set[str],
) -> dict[str, Any] | None:
    if not evidence_path.startswith("raw/"):
        return None
    try:
        lines = _resolve_scene_child(scene_dir, evidence_path).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return None
    fallback: dict[str, Any] | None = None
    for line in lines:
        text = str(line or "").strip()
        if not text:
            continue
        payload = _parse_startup_raw_json_line(text)
        if not isinstance(payload, dict):
            continue
        if fallback is None:
            fallback = payload
        candidate_code = str(payload.get("event") or payload.get("event_code") or payload.get("eventCode") or "").strip()
        if candidate_code and candidate_code in event_codes:
            return payload
    return fallback


def _parse_startup_raw_json_line(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        sanitized = "".join(char for char in text if char >= " " or char in "\t\r\n")
        if sanitized == text:
            return None
        try:
            payload = json.loads(sanitized)
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _startup_step_timestamp(event: dict[str, Any] | None) -> str:
    if not isinstance(event, dict):
        return ""
    return str(event.get("timestamp") or event.get("ts") or "").strip()


def _runtime_scene_startup_trace_summary(
    manifest: dict[str, Any],
    steps: list[dict[str, Any]],
    missing: list[str],
) -> str:
    recorded = len([step for step in steps if step.get("status") == "recorded"])
    total = len(steps)
    status = _runtime_scene_status(manifest)
    if not missing:
        return f"启动流程 {recorded}/{total}，状态 {status}。"
    labels = [
        str(step.get("label") or step.get("id") or "")
        for step in steps
        if step.get("id") in missing
    ]
    return f"启动流程 {recorded}/{total}，缺少：{'、'.join(labels)}。"


def _scene_child_has_content(scene_dir: Path, relative_path: str) -> bool:
    if not _scene_child_exists(scene_dir, relative_path):
        return False
    try:
        return (_resolve_scene_child(scene_dir, relative_path).stat().st_size or 0) > 0
    except OSError:
        return False


def _runtime_scene_recommended_reading_order(
    *,
    startup_trace: dict[str, Any],
    raw_files: list[dict],
    conversation_logs: list[dict],
    agent_logs: list[dict],
    artifacts: list[dict],
    event_logs: list[dict],
    first_signal: dict[str, Any] | None,
) -> list[str]:
    order = [SUMMARY_PATH, PACKAGE_INDEX_PATH]
    for step in startup_trace.get("steps", []) if isinstance(startup_trace, dict) else []:
        if isinstance(step, dict):
            _append_unique_path(order, str(step.get("evidencePath") or "").strip())
    _append_unique_path(order, TIMELINE_PATH)
    _append_unique_path(order, LIFECYCLE_PATH)
    raw_refs = first_signal.get("rawRefs") if isinstance(first_signal, dict) else []
    for item in raw_refs if isinstance(raw_refs, list) else []:
        if isinstance(item, dict):
            _append_unique_path(order, str(item.get("path") or "").strip())
    for group in (conversation_logs, agent_logs, event_logs, raw_files, artifacts):
        for item in group:
            _append_unique_path(order, str(item.get("path") or "").strip())
            if len(order) >= 12:
                return order
    return order


def _runtime_scene_key_entries(
    *,
    scene_dir: Path,
    manifest: dict[str, Any],
    startup_trace: dict[str, Any],
    raw_files: list[dict],
    conversation_logs: list[dict],
    agent_logs: list[dict],
    artifacts: list[dict],
    event_logs: list[dict],
    first_signal: dict[str, Any] | None,
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path, label, reason in (
        (SUMMARY_PATH, "Lifecycle package summary", "Start here for package counts, sections, and diagnostic entrypoint."),
        (PACKAGE_INDEX_PATH, "Package index", "Use this for stable date-based lookup and package identity."),
        ("raw/desktop-entry-vbs.log", "Startup: 桌面入口 VBS", "Use this to reconstruct the Windows Script Host entry that hands off into PowerShell."),
        ("raw/desktop-entry.log", "Startup: 桌面入口", "Use this to reconstruct the PowerShell desktop entry handoff."),
        ("raw/launcher-control.log", "Startup: 启动控制", "Use this to reconstruct launcher handoff, backend, browser, and supervisor startup."),
    ):
        if _scene_child_exists(scene_dir, path):
            _append_key_entry(
                entries,
                path=path,
                label=label,
                reason=reason,
            )
    for path, label in ((TIMELINE_PATH, "Unified timeline"), (LIFECYCLE_PATH, "Lifecycle events")):
        if _scene_child_exists(scene_dir, path):
            _append_key_entry(
                entries,
                path=path,
                label=label,
                reason="Read chronological events across the full lifecycle." if path == TIMELINE_PATH else "Check startup, shutdown, supervision, and recovery phases.",
            )
    for step in startup_trace.get("steps", []) if isinstance(startup_trace, dict) else []:
        if not isinstance(step, dict):
            continue
        path = str(step.get("evidencePath") or "").strip()
        if path and _scene_child_exists(scene_dir, path):
            label = str(step.get("label") or step.get("id") or "startup").strip()
            _append_key_entry(
                entries,
                path=path,
                label=f"Startup: {label}",
                reason="Use this startup breadcrumb to reconstruct the launcher-to-workbench boot chain.",
            )
    for path in ("raw/desktop-entry-vbs.log", "raw/desktop-entry.log", "raw/launcher-control.log"):
        _append_key_entry(
            entries,
            path=path,
            label=f"Startup: {Path(path).name}",
            reason="Use this startup breadcrumb to reconstruct the launcher-to-workbench boot chain.",
        )
    if not entries and event_logs:
        _append_key_entry(
            entries,
            path=str(event_logs[0].get("path") or ""),
            label="Component event stream",
            reason="This legacy package has no merged timeline file; start from component events.",
        )
    raw_refs = first_signal.get("rawRefs") if isinstance(first_signal, dict) else []
    for item in raw_refs if isinstance(raw_refs, list) else []:
        if isinstance(item, dict):
            path = str(item.get("path") or "").strip()
            if not _scene_child_exists(scene_dir, path):
                continue
            _append_key_entry(
                entries,
                path=path,
                label="First signal evidence",
                reason="Open the raw reference attached to the first error or warning event.",
            )
    for key, label, reason in (
        ("frontend.log_path", "Frontend build log", "Confirm frontend build output for this lifecycle."),
        ("backend.stdout_path", "Backend stdout", "Inspect backend startup and runtime output."),
        ("backend.stderr_path", "Backend stderr", "Inspect backend errors and tracebacks when present."),
        ("browser.log_path", "Browser log", "Inspect managed browser launch and close behavior."),
        ("supervisor.log_path", "Supervisor log", "Inspect supervisor process behavior."),
        ("supervisor.stderr_path", "Supervisor stderr", "Inspect supervisor errors when present."),
    ):
        path = _manifest_nested_string(manifest, key)
        if path and _scene_child_exists(scene_dir, path):
            _append_key_entry(entries, path=path, label=label, reason=reason)
    for group, label, reason in (
        (conversation_logs, "Conversation child log", "Review user, assistant, and tool-call conversation breadcrumbs."),
        (agent_logs, "Agent child log", "Review agent turn, tool-call, supervision, or self-evolution breadcrumbs."),
        (event_logs, "Component event stream", "Inspect component-specific structured events backing the timeline."),
        (raw_files, "Raw log", "Use as supporting low-level process evidence."),
        (artifacts, "Artifact", "Inspect generated reports, snapshots, or referenced run outputs."),
    ):
        if group:
            _append_key_entry(entries, path=str(group[0].get("path") or ""), label=label, reason=reason)
    return entries[:10]


def _runtime_scene_diagnosis_user_summary(
    *,
    severity: str,
    manifest: dict[str, Any],
    timeline: list[dict],
    lifecycle: list[dict],
    severity_summary: dict[str, int],
    issue_state: dict[str, Any],
    first_signal: dict[str, Any] | None,
    child_log_count: int,
    startup_trace: dict[str, Any],
) -> str:
    status = _runtime_scene_status(manifest)
    result = str(manifest.get("result") or manifest.get("stop_reason") or "").strip()
    event_count = len(timeline)
    lifecycle_count = len(lifecycle)
    base = f"本周期状态为 {status}"
    if result:
        base = f"{base}，结果为 {result}"
    base = f"{base}；记录了 {event_count} 个时间线事件、{lifecycle_count} 个生命周期事件、{child_log_count} 个子日志入口。"
    issue_phrase = _runtime_scene_issue_state_summary(issue_state)
    active_signal_count = int(issue_state.get("activeErrorCount") or 0) + int(issue_state.get("activeWarningCount") or 0)
    policy_signal_count = int(issue_state.get("policySignalCount") or 0)
    if policy_signal_count and not active_signal_count:
        signal = _runtime_scene_signal_label(first_signal)
        return f"{base}{issue_phrase}原始记录包含 {policy_signal_count} 个控制/策略信号，优先确认策略语义是 {signal}。"
    if severity == "error" and active_signal_count:
        signal = _runtime_scene_signal_label(first_signal)
        return f"{base}{issue_phrase}原始记录包含 {severity_summary['errorCount']} 个错误信号，优先排查的活跃信号是 {signal}。"
    if severity == "warning" and active_signal_count:
        signal = _runtime_scene_signal_label(first_signal)
        return f"{base}{issue_phrase}原始记录包含 {severity_summary['warningCount']} 个警告信号，优先排查的活跃信号是 {signal}。"
    if issue_phrase:
        base = f"{base}{issue_phrase}"
    startup_summary = str((startup_trace or {}).get("summary") or "").strip()
    if startup_summary:
        base = f"{base}{startup_summary}"
    if event_count == 0 and child_log_count == 0:
        return f"{base}当前包缺少可分析事件和子日志，应把缺失日志视为日志系统问题。"
    if issue_phrase:
        return f"{base}当前未发现活跃错误或警告，可按推荐顺序抽查关键入口。"
    return f"{base}未发现明显错误或警告，可按推荐顺序抽查关键入口。"


def _runtime_scene_issue_state_summary(issue_state: dict[str, Any]) -> str:
    active_errors = int(issue_state.get("activeErrorCount") or 0)
    active_warnings = int(issue_state.get("activeWarningCount") or 0)
    policy_signals = int(issue_state.get("policySignalCount") or 0)
    historical_errors = int(issue_state.get("historicalErrorCount") or 0)
    historical_warnings = int(issue_state.get("historicalWarningCount") or 0)
    active_cluster_count = int(issue_state.get("activeClusterCount") or 0)
    policy_cluster_count = int(issue_state.get("policyClusterCount") or 0)
    historical_cluster_count = int(issue_state.get("historicalClusterCount") or 0)
    control_count = int(issue_state.get("controlSignalCount") or 0)
    if active_errors or active_warnings:
        cluster = _runtime_scene_issue_cluster_display(issue_state.get("firstActiveCluster"))
        return (
            f"当前仍有 {active_cluster_count} 个活跃问题簇，其中主簇是 {cluster}；"
            if active_cluster_count
            else f"当前仍有 {active_errors} 个活跃错误、{active_warnings} 个活跃警告；"
        )
    if policy_signals:
        cluster = _runtime_scene_issue_cluster_display(issue_state.get("firstPolicyCluster"))
        return (
            f"当前记录到 {policy_cluster_count} 个控制/策略问题簇，其中主簇是 {cluster}；"
            if policy_cluster_count
            else f"当前记录到 {policy_signals} 个控制/策略信号；"
        )
    if historical_errors or historical_warnings:
        cluster = _runtime_scene_issue_cluster_display(issue_state.get("firstHistoricalCluster"))
        return (
            f"错误/警告均有后续恢复证据，当前记录到 {historical_cluster_count} 个历史/已恢复问题簇，主簇是 {cluster}；"
            if historical_cluster_count
            else f"错误/警告均有后续恢复证据，历史错误 {historical_errors} 个、历史警告 {historical_warnings} 个；"
        )
    if control_count:
        return f"另有 {control_count} 个控制类信号，不作为当前问题；"
    return ""


def _runtime_scene_diagnosis_next_step(
    *,
    scene_dir_name: str,
    scene_id: str,
    severity: str,
    issue_state: dict[str, Any],
    first_signal: dict[str, Any] | None,
    recommended_order: list[str],
    key_entries: list[dict[str, str]],
    startup_trace: dict[str, Any],
) -> str:
    first_path = recommended_order[0] if recommended_order else key_entries[0]["path"] if key_entries else SUMMARY_PATH
    package_anchor = str(scene_dir_name or scene_id).strip() or scene_id
    historical_errors = int(issue_state.get("historicalErrorCount") or 0)
    historical_warnings = int(issue_state.get("historicalWarningCount") or 0)
    active_cluster_count = int(issue_state.get("activeClusterCount") or 0)
    policy_cluster_count = int(issue_state.get("policyClusterCount") or 0)
    policy_signal_count = int(issue_state.get("policySignalCount") or 0)
    historical_cluster_count = int(issue_state.get("historicalClusterCount") or 0)
    control_count = int(issue_state.get("controlSignalCount") or 0)
    if policy_signal_count and not active_cluster_count and first_signal:
        cluster = _runtime_scene_issue_cluster_display(issue_state.get("firstPolicyCluster"))
        return (
            f"先读 logs/runtime_scenes/{package_anchor}/{first_path}，确认 issueState.policyClusterCount；"
            f"再定位主控制/策略簇 {cluster}，优先检查 testPolicy、mode、source 或 guard 语义，不要按业务故障继续追恢复链。"
        )
    if severity == "error" and active_cluster_count and first_signal:
        cluster = _runtime_scene_issue_cluster_display(issue_state.get("firstActiveCluster"))
        return (
            f"先读 logs/runtime_scenes/{package_anchor}/{first_path}，确认 issueState.activeClusterCount；"
            f"再定位主问题簇 {cluster}，优先打开 summary/package_index 里的 evidence_paths 对应文件，"
            "并沿同一 component/runId/pageInstanceId 向后找恢复或重复崩溃。"
        )
    if severity == "warning" and active_cluster_count and first_signal:
        cluster = _runtime_scene_issue_cluster_display(issue_state.get("firstActiveCluster"))
        return (
            f"先读 logs/runtime_scenes/{package_anchor}/{first_path}，确认 issueState.activeClusterCount；"
            f"再定位主问题簇 {cluster}，判断它是退化、重试还是用户控制信号，必要时打开 evidence_paths 对应文件。"
        )
    if policy_signal_count and first_signal:
        cluster = _runtime_scene_issue_cluster_display(issue_state.get("firstPolicyCluster"))
        return (
            f"先读 logs/runtime_scenes/{package_anchor}/{first_path}，确认 issueState.policyClusterCount；"
            f"再定位主控制/策略簇 {cluster}，优先检查 testPolicy、mode、source 或 guard 语义，不要按业务故障继续追恢复链。"
        )
    if historical_cluster_count or historical_errors or historical_warnings:
        cluster = _runtime_scene_issue_cluster_display(issue_state.get("firstHistoricalCluster"))
        return (
            f"先读 logs/runtime_scenes/{package_anchor}/{first_path}，确认 issueState 中历史/已恢复簇计数；"
            f"再对照主历史簇 {cluster} 与后续恢复事件，避免把已恢复错误当成当前阻塞。"
        )
    missing = startup_trace.get("missingStepIds", []) if isinstance(startup_trace, dict) else []
    if missing:
        return (
            f"先读 logs/runtime_scenes/{package_anchor}/{first_path}，再对照 startupTrace.missingStepIds "
            "确认启动链路缺口是否属于日志系统问题。"
        )
    if control_count:
        return (
            f"先读 logs/runtime_scenes/{package_anchor}/{first_path}，确认控制类信号只代表用户意图或编辑行为；"
            "再按推荐阅读顺序抽查 timeline、conversation 和 agent 子日志。"
        )
    if active_cluster_count:
        cluster = _runtime_scene_issue_cluster_display(issue_state.get("firstActiveCluster"))
        return (
            f"先读 logs/runtime_scenes/{package_anchor}/{first_path}，确认 issueState.activeClusterCount；"
            f"再追踪主问题簇 {cluster}，把它和首个信号、证据路径、timeline 顺序对齐。"
        )
    return (
        f"先读 logs/runtime_scenes/{package_anchor}/{first_path}，再按推荐阅读顺序对照 timeline、lifecycle 和子日志确认周期完整性。"
    )


def _runtime_scene_diagnosis_signal_payload(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not event:
        return None
    return {
        "severity": str(event.get("diagnosisSeverity") or _runtime_scene_event_severity(event)),
        "timestamp": str(event.get("timestamp") or ""),
        "component": str(event.get("component") or ""),
        "phase": str(event.get("phase") or ""),
        "eventCode": str(event.get("eventCode") or ""),
        "message": _truncate_text(str(event.get("message") or ""), 320),
        "rawRefs": _runtime_scene_signal_raw_refs(event),
    }


def _runtime_scene_signal_label(event: dict[str, Any] | None) -> str:
    if not event:
        return "未记录"
    parts = [
        str(event.get("timestamp") or "").strip(),
        str(event.get("component") or "").strip(),
        str(event.get("eventCode") or "").strip(),
    ]
    return " / ".join(part for part in parts if part) or "未命名事件"


def _append_unique_path(items: list[str], path: str) -> None:
    normalized = str(path or "").strip().replace("\\", "/")
    if normalized and normalized not in items:
        items.append(normalized)


def _append_key_entry(entries: list[dict[str, str]], *, path: str, label: str, reason: str) -> None:
    normalized = str(path or "").strip().replace("\\", "/")
    if not normalized or any(item["path"] == normalized for item in entries):
        return
    entries.append({"path": normalized, "label": label, "reason": reason})


def _manifest_nested_string(manifest: dict[str, Any], key: str) -> str:
    current: Any = manifest
    for part in key.split("."):
        if not isinstance(current, dict):
            return ""
        current = current.get(part)
    return str(current or "").strip().replace("\\", "/")


def _scene_child_exists(scene_dir: Path, relative_path: str) -> bool:
    try:
        return _resolve_scene_child(scene_dir, relative_path).exists()
    except ValueError:
        return False


def _runtime_scene_severity_summary(events: list[dict]) -> dict[str, int]:
    error_count = 0
    warning_count = 0
    for event in events:
        severity = _runtime_scene_event_severity(event)
        if severity == "error":
            error_count += 1
        elif severity == "warning":
            warning_count += 1
    return {
        "errorCount": error_count,
        "warningCount": warning_count,
    }


def _runtime_scene_event_severity(event: dict) -> str:
    level = str(event.get("level") or "").strip().lower()
    outcome = str(event.get("outcome") or "").strip().lower()
    status = str(event.get("status") or "").strip().lower()
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    field_status = str(fields.get("status") or fields.get("resultStatus") or "").strip().lower()
    field_outcome = str(fields.get("outcome") or "").strip().lower()
    error_markers = (
        fields.get("error"),
        fields.get("errorType"),
        fields.get("exceptionType"),
        fields.get("exceptionMessage"),
        fields.get("failureMessage"),
    )
    has_error_marker = any(str(value or "").strip() for value in error_markers)

    if level in {"error", "fatal", "critical"}:
        return "error"
    if outcome in {"error", "failed", "failure"} or field_outcome in {"error", "failed", "failure"}:
        return "error"
    if status in {"error", "failed"} or field_status in {"error", "failed"}:
        return "error"
    if has_error_marker:
        return "error"
    if level in {"warning", "warn"}:
        return "warning"
    if outcome in {"warning", "warn", "partial", "client_error", "degraded"} or field_outcome in {
        "warning",
        "warn",
        "partial",
        "client_error",
        "degraded",
    }:
        return "warning"
    if status in {"warning", "warn", "partial", "degraded"} or field_status in {
        "warning",
        "warn",
        "partial",
        "degraded",
    }:
        return "warning"
    return "info"


def _file_timestamp(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
    except OSError:
        return ""


def _resolve_current_runtime_scene_dir() -> Path | None:
    launcher_state = _load_launcher_state()
    raw_dir = str(launcher_state.get("runtimeSceneDir") or "").strip()
    if not raw_dir:
        return None

    scene_dir = Path(raw_dir).resolve()
    try:
        scene_dir.relative_to(_runtime_scene_root())
    except ValueError:
        return None

    if not scene_dir.exists() or not scene_dir.is_dir():
        return None
    manifest = _load_scene_manifest(scene_dir)
    if not _is_current_runtime_scene_manifest(scene_dir, manifest, launcher_state):
        return None
    return scene_dir


def _resolve_recent_completed_runtime_scene_dir(*, max_age_seconds: float = 180.0) -> Path | None:
    now = datetime.now(UTC)
    for scene_dir in _scene_dirs():
        manifest = _load_scene_manifest(scene_dir)
        if not _runtime_scene_project_matches(manifest):
            continue
        status = str(manifest.get("status") or "").strip().lower()
        if status not in {"failed", "stopped"}:
            continue
        ended_at = _parse_datetime(str(manifest.get("ended_at") or ""))
        if ended_at is None:
            continue
        age = max(0.0, (now - ended_at.astimezone(UTC)).total_seconds())
        if age <= max_age_seconds:
            return scene_dir
    return None


def _is_current_runtime_scene_manifest(scene_dir: Path, manifest: dict[str, Any], launcher_state: dict[str, Any]) -> bool:
    status = str(manifest.get("status") or "").strip().lower()
    if status and status not in {"running", "starting", "queued", "opening", "stopping", "closing"}:
        return False

    target_scene_id = str(launcher_state.get("runtimeSceneId") or "").strip()
    if target_scene_id and _scene_id(scene_dir, manifest) != target_scene_id:
        return False

    if not _runtime_scene_project_matches(manifest):
        return False
    return True


def _runtime_scene_project_matches(manifest: dict[str, Any]) -> bool:
    manifest_project_root = str(
        manifest.get("project_root")
        or manifest.get("projectRoot")
        or ((manifest.get("project") or {}) if isinstance(manifest.get("project"), dict) else {}).get("root")
        or ""
    ).strip()
    if manifest_project_root and not _same_path(manifest_project_root, PROJECT_ROOT):
        return False
    return True


def _same_path(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return str(left).strip().replace("\\", "/").rstrip("/").lower() == str(right).strip().replace("\\", "/").rstrip("/").lower()


def _resolve_scene_dir(scene_id: str) -> Path:
    target = str(scene_id or "").strip()
    if not target:
        raise FileNotFoundError("Runtime scene id is required")
    for scene_dir in _scene_dirs():
        manifest = _load_scene_manifest(scene_dir)
        if _scene_id(scene_dir, manifest) == target:
            return scene_dir
    raise FileNotFoundError(f"Runtime scene not found: {target}")


def _normalize_relative_path(value: str) -> str:
    relative = str(value or "").strip().replace("\\", "/")
    if not relative:
        raise ValueError("Runtime scene path is required")
    return relative


def _resolve_scene_child(scene_dir: Path, relative_path: str) -> Path:
    candidate = (scene_dir / relative_path).resolve()
    try:
        candidate.relative_to(scene_dir.resolve())
    except ValueError as exc:
        raise ValueError("Runtime scene path must stay inside the selected scene") from exc
    return candidate


def _append_scene_log_line(scene_dir: Path, relative_path: str, message: str) -> None:
    target = _resolve_scene_child(scene_dir, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


def _append_scene_jsonl(scene_dir: Path, relative_path: str, payload: dict[str, Any]) -> None:
    target = _resolve_scene_child(scene_dir, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")


def _append_scene_event(scene_dir: Path, component: str, payload: dict[str, Any]) -> None:
    events_dir = scene_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    event_path = events_dir / f"{component}.jsonl"
    with event_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")
    _append_scene_jsonl(scene_dir, TIMELINE_PATH, payload)
    if _is_lifecycle_event(payload):
        _append_scene_jsonl(scene_dir, LIFECYCLE_PATH, payload)


def _is_lifecycle_event(payload: dict[str, Any]) -> bool:
    if bool(payload.get("lifecycle")):
        return True
    phase = str(payload.get("phase") or "").strip().lower()
    event_code = str(payload.get("event_code") or "").strip()
    component = str(payload.get("component") or "").strip().lower()
    if event_code.startswith("runtime.scene."):
        return True
    if phase in LIFECYCLE_INDEX_PHASES:
        return True
    return component in {"launcher", "supervisor"} and phase in {"session", "shutdown"}


def _should_index_browser_telemetry_event(
    manifest: dict[str, Any],
    timestamp: str,
    event_code: str,
    level: str,
    fields: dict[str, Any],
) -> bool:
    """Keep noisy browser focus changes in raw logs unless they add timeline signal."""

    if level in {"warning", "error"}:
        return True
    if event_code != "browser.visibility.changed":
        return True

    browser = manifest.get("browser") if isinstance(manifest.get("browser"), dict) else {}
    previous_visibility = str(browser.get("visibility_state") or "").strip()
    next_visibility = str(fields.get("visibilityState") or "").strip()
    if not previous_visibility:
        return True
    if next_visibility and previous_visibility == next_visibility:
        return False

    last_indexed_at = str(browser.get("last_indexed_visibility_event_at") or "").strip()
    if not last_indexed_at:
        return True
    return _seconds_between_iso(last_indexed_at, timestamp) >= BROWSER_VISIBILITY_TIMELINE_MIN_SECONDS


def _update_runtime_scene_package_manifest(scene_dir: Path, manifest: dict[str, Any]) -> None:
    package = manifest.get("package")
    if not isinstance(package, dict):
        package = {}
    scene_id = _scene_id(scene_dir, manifest)
    package_index = _runtime_scene_package_index(scene_dir, manifest, scene_id)
    package.update(
        {
            "schema_version": 2,
            "index_schema_version": package_index["schemaVersion"],
            "package_id": package_index["packageId"],
            "display_name": package_index["displayName"],
            "index_key": package_index["indexKey"],
            "sortable_timestamp": package_index["sortableTimestamp"],
            "started_at": package_index["startedAt"],
            "started_at_local": package_index["startedAtLocal"],
            "started_date": package_index["startedDate"],
            "started_time": package_index["startedTime"],
            "ended_at": package_index["endedAt"],
            "duration_seconds": package_index["durationSeconds"],
            "search_text": package_index["searchText"],
            "tags": package_index["tags"],
            "package_index_path": PACKAGE_INDEX_PATH,
            "summary_path": SUMMARY_PATH,
            "timeline_path": TIMELINE_PATH,
            "lifecycle_path": LIFECYCLE_PATH,
            "raw_dir": "raw",
            "conversations_dir": CONVERSATIONS_DIR,
            "agent_dir": AGENT_DIR,
            "artifacts_dir": ARTIFACTS_DIR,
            "research_dir": RESEARCH_DIR,
            "updated_at": _now_utc(),
        }
    )
    manifest["package"] = package
    _save_runtime_scene_research_summary(scene_dir)
    _save_runtime_scene_package_index(scene_dir, package_index)
    _save_runtime_scene_summary(scene_dir, manifest, package_index)
    _save_scene_manifest(scene_dir, manifest)


def _next_scene_event_seq(scene_dir: Path, component: str) -> int:
    event_path = scene_dir / "events" / f"{component}.jsonl"
    last_seq = 0
    for row in _read_jsonl_file(event_path):
        try:
            last_seq = max(last_seq, int(row.get("seq") or 0))
        except (TypeError, ValueError):
            continue
    return last_seq + 1


def _update_browser_manifest(
    scene_dir: Path,
    manifest: dict[str, Any],
    timestamp: str,
    event_code: str,
    level: str,
    message: str,
    fields: dict[str, Any],
    *,
    indexed: bool = True,
) -> None:
    browser = manifest.get("browser")
    if not isinstance(browser, dict):
        browser = {}

    browser["telemetry_path"] = BROWSER_TELEMETRY_RAW_PATH
    browser["last_event_at"] = timestamp
    browser["last_event_indexed"] = bool(indexed)

    field_to_manifest_key = {
        "href": "current_href",
        "pathname": "current_pathname",
        "title": "current_title",
        "activeNavHref": "active_nav_href",
        "activeNavText": "active_nav_text",
        "heading": "current_heading",
        "visibilityState": "visibility_state",
    }
    for field_name, manifest_key in field_to_manifest_key.items():
        value = fields.get(field_name)
        if isinstance(value, str) and value.strip():
            browser[manifest_key] = _truncate_text(value.strip(), MAX_TELEMETRY_FIELD_TEXT_CHARS)

    if "online" in fields:
        browser["online"] = bool(fields.get("online"))

    if event_code.startswith("browser.console."):
        browser["last_console_at"] = timestamp
        browser["last_console_level"] = level
        browser["last_console_message"] = message

    if event_code in {"browser.page.error", "browser.promise.rejected", "browser.resource.error"}:
        browser["last_page_error_at"] = timestamp
        browser["last_page_error_message"] = message

    if event_code == "browser.visibility.changed":
        browser["last_visibility_event_at"] = timestamp
        if indexed:
            browser["last_indexed_visibility_event_at"] = timestamp

    manifest["browser"] = browser
    _save_scene_manifest(scene_dir, manifest)


def _update_backend_api_manifest(
    scene_dir: Path,
    manifest: dict[str, Any],
    timestamp: str,
    level: str,
    fields: dict[str, Any],
) -> None:
    backend = manifest.get("backend")
    if not isinstance(backend, dict):
        backend = {}

    backend["api_log_path"] = BACKEND_API_RAW_PATH
    backend["last_api_event_at"] = timestamp
    backend["last_api_event_level"] = level

    status_code = fields.get("statusCode")
    if isinstance(status_code, int):
        backend["last_api_status_code"] = status_code
    path_template = fields.get("pathTemplate")
    if isinstance(path_template, str) and path_template.strip():
        backend["last_api_path"] = _truncate_text(path_template.strip(), MAX_TELEMETRY_FIELD_TEXT_CHARS)
    method = fields.get("method")
    if isinstance(method, str) and method.strip():
        backend["last_api_method"] = method.strip()

    manifest["backend"] = backend
    _save_scene_manifest(scene_dir, manifest)


def _sanitize_token(value: object, *, default: str) -> str:
    token = str(value or "").strip()
    if not token:
        return default
    return _truncate_text(token, 120)


def _sanitize_path_token(value: object, *, default: str) -> str:
    token = str(value or "").strip()
    if not token:
        token = default
    normalized = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in token)
    normalized = normalized.strip("._-")
    return _truncate_text(normalized or default, 120)


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_event_timestamp(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _truncate_text(value: str, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[: max(0, limit - 3)]}..."


def _truncate_prompt_index_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: max(0, limit - 3)]}..."


def _seconds_between_iso(start: str, end: str) -> float:
    try:
        start_at = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        end_at = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return BROWSER_VISIBILITY_TIMELINE_MIN_SECONDS
    return max(0.0, (end_at - start_at).total_seconds())


def _coerce_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: object, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_telemetry_fields(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_TELEMETRY_FIELD_ITEMS:
                break
            key_text = str(key)
            normalized[key_text] = (
                REDACTED_FIELD_VALUE
                if _is_sensitive_telemetry_key(key_text)
                else _normalize_telemetry_value(item, depth=0)
            )
        return normalized
    if value is None:
        return {}
    return {"value": _normalize_telemetry_value(value, depth=0)}


def _normalize_telemetry_value(value: object, *, depth: int) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_text(value, MAX_TELEMETRY_FIELD_TEXT_CHARS)
    if depth >= 2:
        return _truncate_text(str(value), MAX_TELEMETRY_FIELD_TEXT_CHARS)
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_TELEMETRY_FIELD_ITEMS:
                break
            key_text = str(key)
            normalized[key_text] = (
                REDACTED_FIELD_VALUE
                if _is_sensitive_telemetry_key(key_text)
                else _normalize_telemetry_value(item, depth=depth + 1)
            )
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _normalize_telemetry_value(item, depth=depth + 1)
            for item in list(value)[:MAX_TELEMETRY_FIELD_ITEMS]
        ]
    return _truncate_text(str(value), MAX_TELEMETRY_FIELD_TEXT_CHARS)


def _is_sensitive_telemetry_key(key: str) -> bool:
    normalized = str(key or "").strip().lower().replace("-", "_")
    return any(keyword in normalized for keyword in SENSITIVE_FIELD_KEYWORDS)


def _normalize_raw_refs(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    refs: list[dict[str, Any]] = []
    for item in value[:MAX_TELEMETRY_FIELD_ITEMS]:
        if not isinstance(item, dict):
            continue
        path = _truncate_text(str(item.get("path") or "").strip().replace("\\", "/"), 240)
        if not path:
            continue
        ref: dict[str, Any] = {"path": path}
        tail_lines = _coerce_int(item.get("tail_lines"), default=0)
        if tail_lines > 0:
            ref["tail_lines"] = min(tail_lines, 1_000)
        refs.append(ref)
    return refs


def _safe_optional_relative_path(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    try:
        relative = _normalize_relative_path(text)
    except ValueError:
        return ""
    if (
        relative.startswith("/")
        or relative.startswith("//")
        or relative.startswith("../")
        or "/../" in relative
        or relative == ".."
        or _looks_like_windows_absolute_path(relative)
    ):
        return ""
    return _truncate_text(relative, 240)


def _looks_like_windows_absolute_path(value: str) -> bool:
    return len(value) >= 3 and value[1] == ":" and value[0].isalpha() and value[2] == "/"


def _normalize_scene_ids(scene_ids: list[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    for item in scene_ids:
        value = str(item or "").strip()
        if not value or value in normalized:
            continue
        normalized.append(value)
    return normalized


def _runtime_scene_root() -> Path:
    return (PROJECT_ROOT / "logs" / "runtime_scenes").resolve()
