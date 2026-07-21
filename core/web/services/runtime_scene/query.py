"""Runtime scene list/get/detail/query helpers.

Claim scope: list/get detail, read scene files, evidence listing,
prompt index, retention prune, and query-side package sidecar sync.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any

# Local default for signature evaluation (facade remains SSOT).
RUNTIME_SCENE_RETENTION_LIMIT = 30


def _service():
    from core.web.services import runtime_scene_service

    return runtime_scene_service


def _analyze_runtime_scene_content(scene_id: str, relative_path: str, content: str) -> dict[str, Any]:
    s = _service()
    return s.analyze_log_content(
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


def _can_delete_runtime_scene_for_retention(scene_dir: Path) -> bool:
    s = _service()
    try:
        resolved = scene_dir.resolve()
        resolved.relative_to(s._runtime_scene_root())
    except (OSError, ValueError):
        return False
    if not resolved.exists() or not resolved.is_dir():
        return False
    return not s._is_runtime_scene_retention_protected(
        resolved,
        s._safe_current_runtime_scene_dir_for_retention(),
    )


def _closed_reconciliation_fields(fields: dict[str, Any]) -> bool:
    s = _service()
    observed_state = str(fields.get("observedState") or "").strip().lower()
    desired_state = str(fields.get("desiredState") or "").strip().lower()
    manager_running = bool(fields.get("managerRunning"))
    backend_pid = s._coerce_int(fields.get("backendPid"), default=0)
    browser_pid = s._coerce_int(fields.get("browserWindowPid"), default=0)
    return observed_state == "closed" and desired_state == "closed" and not manager_running and backend_pid == 0 and browser_pid == 0


def _enforce_runtime_scene_retention(max_packages: int = RUNTIME_SCENE_RETENTION_LIMIT) -> dict[str, Any]:
    """Keep runtime scene packages bounded while preserving active evidence."""
    s = _service()

    try:
        retention_limit = max(1, int(max_packages or s.RUNTIME_SCENE_RETENTION_LIMIT))
    except (TypeError, ValueError):
        retention_limit = s.RUNTIME_SCENE_RETENTION_LIMIT
    scene_dirs = s._scene_dirs()
    if len(scene_dirs) <= retention_limit:
        return {
            "retentionLimit": retention_limit,
            "deletedCount": 0,
            "keptCount": len(scene_dirs),
            "protectedCount": 0,
            "deletedSceneIds": [],
        }

    current_scene_dir = s._safe_current_runtime_scene_dir_for_retention()
    items: list[dict[str, Any]] = []
    for scene_dir in scene_dirs:
        manifest = s._load_scene_manifest(scene_dir)
        items.append(
            {
                "path": scene_dir,
                "manifest": manifest,
                "sceneId": s._scene_id(scene_dir, manifest),
                "sortKey": s._runtime_scene_retention_sort_key(scene_dir, manifest),
                "protected": s._is_runtime_scene_retention_protected(scene_dir, current_scene_dir),
            }
        )

    items.sort(key=lambda item: item["sortKey"], reverse=True)
    protected_items = [item for item in items if item["protected"]]
    ordinary_items = [item for item in items if not item["protected"]]
    keep_paths: set[Path] = {item["path"].resolve() for item in protected_items}
    ordinary_slots = max(0, retention_limit - len(keep_paths))
    keep_paths.update(item["path"].resolve() for item in ordinary_items[:ordinary_slots])
    delete_items = [item for item in ordinary_items if item["path"].resolve() not in keep_paths]

    deleted_scene_ids: list[str] = []
    for item in delete_items:
        scene_dir = item["path"]
        if not s._can_delete_runtime_scene_for_retention(scene_dir):
            continue
        shutil.rmtree(scene_dir)
        deleted_scene_ids.append(str(item["sceneId"] or scene_dir.name))

    if deleted_scene_ids:
        s._record_runtime_scene_retention_pruned(
            retention_limit=retention_limit,
            kept_count=len(items) - len(deleted_scene_ids),
            protected_count=len(protected_items),
            deleted_scene_ids=deleted_scene_ids,
        )

    return {
        "retentionLimit": retention_limit,
        "deletedCount": len(deleted_scene_ids),
        "keptCount": len(items) - len(deleted_scene_ids),
        "protectedCount": len(protected_items),
        "deletedSceneIds": deleted_scene_ids,
    }


def _get_runtime_scene_prompt_index_cache(
    limit: int,
    signature: tuple[tuple[str, str, str, str], ...],
) -> str | None:
    s = _service()
    cache_key = (limit, signature)
    now = monotonic()
    with s._RUNTIME_SCENE_PROMPT_INDEX_CACHE_LOCK:
        cached = s._RUNTIME_SCENE_PROMPT_INDEX_CACHE.get(cache_key)
        if cached is None:
            return None
        cached_at, rendered = cached
        if now - cached_at > s.RUNTIME_SCENE_PROMPT_INDEX_CACHE_TTL_SECONDS:
            s._RUNTIME_SCENE_PROMPT_INDEX_CACHE.pop(cache_key, None)
            return None
        return rendered


def _is_runtime_scene_reopen_event(event_name: str) -> bool:
    s = _service()
    return str(event_name or "").strip() in {
        "runtime.scene.ready",
        "backend.health.succeeded",
        "browser.window.opened",
        "workbench.open.already_satisfied",
        "workbench.open.verification_succeeded",
    }


def _is_runtime_scene_retention_protected(
    scene_dir: Path,
    current_scene_dir: Path | None,
) -> bool:
    s = _service()
    return current_scene_dir is not None and s._same_path(scene_dir, current_scene_dir)


def _latest_closed_reconciliation_event(scene_dir: Path) -> dict[str, Any] | None:
    s = _service()
    latest: dict[str, Any] | None = None
    latest_timestamp = ""
    for row in s._runtime_scene_reconciliation_history_events(scene_dir):
        event_name = str(row.get("event_code") or "").strip()
        timestamp = str(row.get("ts") or "").strip()
        if not timestamp:
            continue
        if s._is_runtime_scene_reopen_event(event_name) and latest_timestamp and timestamp > latest_timestamp:
            latest = None
            latest_timestamp = ""
            continue
        if event_name != "runtime.snapshot.reconciled":
            continue
        fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
        if not s._closed_reconciliation_fields(fields):
            continue
        latest = {"timestamp": s._normalize_event_timestamp(timestamp) or timestamp, "fields": fields}
        latest_timestamp = timestamp
    return latest


def _record_runtime_scene_retention_pruned(
    *,
    retention_limit: int,
    kept_count: int,
    protected_count: int,
    deleted_scene_ids: list[str],
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "runtime_manager",
            "retention",
            "runtime_scene.retention.pruned",
            message="Runtime scene retention pruned old packages",
            level="info",
            outcome="succeeded",
            fields={
                "retentionLimit": retention_limit,
                "keptCount": kept_count,
                "protectedCount": protected_count,
                "deletedCount": len(deleted_scene_ids),
                "deletedSceneIds": deleted_scene_ids[:20],
            },
            lifecycle=True,
            allow_recent_completed=False,
        )
    except Exception:
        pass


def _remember_runtime_scene_prompt_index_cache(
    limit: int,
    signature: tuple[tuple[str, str, str, str], ...],
    rendered: str,
) -> None:
    s = _service()
    cache_key = (limit, signature)
    with s._RUNTIME_SCENE_PROMPT_INDEX_CACHE_LOCK:
        s._RUNTIME_SCENE_PROMPT_INDEX_CACHE[cache_key] = (monotonic(), rendered)
        if len(s._RUNTIME_SCENE_PROMPT_INDEX_CACHE) > 8:
            oldest_key = min(
                s._RUNTIME_SCENE_PROMPT_INDEX_CACHE,
                key=lambda item: s._RUNTIME_SCENE_PROMPT_INDEX_CACHE[item][0],
            )
            s._RUNTIME_SCENE_PROMPT_INDEX_CACHE.pop(oldest_key, None)


def _repair_runtime_scene_from_reconciliation_history(scene_dir: Path, manifest: dict[str, Any]) -> bool:
    s = _service()
    if str(manifest.get("status") or "").strip().lower() not in {"", "running", "starting", "queued", "opening", "stopping", "closing"}:
        return False
    reconciliation = s._latest_closed_reconciliation_event(scene_dir)
    if reconciliation is None:
        return False
    changed = s._maybe_close_runtime_scene_from_reconciliation(
        scene_dir,
        manifest,
        "runtime.snapshot.reconciled",
        reconciliation["fields"],
        reconciliation["timestamp"],
    )
    if changed:
        s._update_runtime_scene_package_manifest(scene_dir, manifest)
    return changed


def _runtime_scene_component_evidence_path(component: str) -> str:
    s = _service()
    normalized = str(component or "").strip().lower()
    if normalized == "backend":
        return s.BACKEND_API_RAW_PATH
    if normalized == "browser":
        return "raw/browser.log"
    if normalized == "browser_page":
        return s.BROWSER_TELEMETRY_RAW_PATH
    if normalized == "frontend":
        return "raw/frontend.build.log"
    if normalized == "launcher":
        return "raw/launcher-control.log"
    if normalized == "supervisor":
        return "raw/supervisor.log"
    if normalized == "conversation":
        return f"{s.EVENTS_DIR}/conversation.jsonl"
    if normalized in {"agent", "llm", "runtime_manager", "tool_executor", "work_run"}:
        return f"{s.EVENTS_DIR}/{normalized}.jsonl"
    if normalized:
        return f"{s.EVENTS_DIR}/{s._runtime_scene_event_component_filename(normalized)}"
    return s.TIMELINE_PATH


def _runtime_scene_diagnosis_status(issue_state: dict[str, Any]) -> str:
    s = _service()
    if int(issue_state.get("activeClusterCount") or 0):
        return "active_issue"
    if int(issue_state.get("policyClusterCount") or 0) or int(issue_state.get("policySignalCount") or 0):
        return "policy_signal"
    if int(issue_state.get("historicalClusterCount") or 0):
        return "recovered_issue"
    if int(issue_state.get("controlSignalCount") or 0):
        return "control_only"
    return "clear"


def _runtime_scene_event_component_filename(component: str) -> str:
    s = _service()
    token = str(component or "").strip().lower()
    token = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in token)
    token = "_".join(part for part in token.split("_") if part)
    token = token.strip("-_.")
    return f"{token or 'component'}.jsonl"


def _runtime_scene_event_datetime(event: dict[str, Any]) -> datetime | None:
    s = _service()
    return s._parse_datetime(str(event.get("timestamp") or event.get("ts") or ""))


def _runtime_scene_event_endpoint(event: dict[str, Any]) -> str:
    s = _service()
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    for key in ("endpoint", "pathTemplate", "path"):
        endpoint = s._normalize_endpoint_path(fields.get(key))
        if endpoint:
            return endpoint
    message = str(event.get("message") or "")
    if s.CONFIG_MODEL_DISCOVERY_ENDPOINT in message:
        return s.CONFIG_MODEL_DISCOVERY_ENDPOINT
    return ""


def _runtime_scene_event_matches_agent(
    event: dict[str, Any],
    *,
    agent_id: str,
    session_id: str,
    run_id: str,
) -> bool:
    s = _service()
    return bool(
        s._runtime_scene_matched_fields(
            event,
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
        )
    )


def _runtime_scene_event_severity(event: dict) -> str:
    s = _service()
    level = str(event.get("level") or "").strip().lower()
    outcome = str(event.get("outcome") or "").strip().lower()
    status = str(event.get("status") or "").strip().lower()
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    if s._runtime_scene_is_supervisor_clean_exit_adopted_event(event):
        return "info"
    if s._runtime_scene_is_operational_client_error_event(event):
        return "info"
    if s._runtime_scene_is_diagnostic_mirror_event(event):
        if level in {"error", "fatal", "critical"}:
            return "error"
        if level in {"warning", "warn"}:
            return "warning"
        return "info"
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


def _runtime_scene_event_status_code(event: dict[str, Any]) -> int:
    s = _service()
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    for key in ("status", "statusCode", "httpStatus"):
        value = s._coerce_int(fields.get(key), default=0)
        if value:
            return value
    message = str(event.get("message") or "")
    for marker in ("HTTP ", "failed (", "-> "):
        if marker not in message:
            continue
        after = message.split(marker, 1)[1]
        digits = "".join(char for char in after[:4] if char.isdigit())
        if digits:
            return s._coerce_int(digits, default=0)
    return 0


def _runtime_scene_is_diagnostic_mirror_event(event: dict) -> bool:
    """Events that persisted an observation should not become a second root cause."""
    s = _service()

    event_code = str(event.get("eventCode") or event.get("event_code") or "").strip()
    if event_code != "memory.event_written":
        return False
    component = str(event.get("component") or "").strip()
    if component not in {"agent_memory", "agent_directory", "memory"}:
        return False
    outcome = str(event.get("outcome") or "").strip().lower()
    level = str(event.get("level") or "").strip().lower()
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    has_persistence_error = any(
        str(fields.get(key) or "").strip()
        for key in ("writeError", "persistenceError", "storageError", "exceptionType", "exceptionMessage")
    )
    if has_persistence_error:
        return False
    return level in {"", "debug", "info"} and outcome in {"", "observed", "written", "succeeded", "success"}


def _runtime_scene_is_operational_client_error_event(event: dict) -> bool:
    s = _service()
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    if fields.get("operationalClientError") is True:
        return True
    if str(event.get("component") or "").strip() != s.BACKEND_COMPONENT:
        return False
    if str(event.get("phase") or "").strip() != "api":
        return False
    endpoint = s._runtime_scene_event_endpoint(event)
    if endpoint not in s.OPERATIONAL_CLIENT_ERROR_PATHS:
        method = str(fields.get("method") or "").strip().upper()
        path = str(fields.get("path") or "").strip()
        path_template = str(fields.get("pathTemplate") or endpoint).strip()
        status_code = s._runtime_scene_event_status_code(event)
        client = str(fields.get("client") or "").strip()
        if s._is_test_client_client_error(client=client, status_code=status_code):
            return True
        return s._is_diagnostic_probe_404(
            method=method,
            path=path,
            path_template=path_template,
            status_code=status_code,
        )
    status_code = s._runtime_scene_event_status_code(event)
    return 400 <= status_code < 500


def _runtime_scene_is_supervisor_clean_exit_adopted_event(event: dict) -> bool:
    s = _service()
    event_code = str(event.get("eventCode") or event.get("event_code") or "").strip()
    if event_code != "supervisor.clean_exit_adopted":
        return False
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    return (
        str(event.get("component") or "").strip() == "supervisor"
        and bool(fields.get("backend_alive"))
        and bool(fields.get("backend_healthy"))
        and int(fields.get("browser_window_count") or 0) > 0
    )


def _runtime_scene_list_diagnosis_summary(summary_payload: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    diagnosis = summary_payload.get("diagnosis") if isinstance(summary_payload.get("diagnosis"), dict) else {}
    issue_state = diagnosis.get("issueState") if isinstance(diagnosis.get("issueState"), dict) else {}
    agent_brief = summary_payload.get("agent_brief") if isinstance(summary_payload.get("agent_brief"), dict) else {}
    active_cluster_count = s._coerce_int(
        issue_state.get("activeClusterCount", agent_brief.get("active_cluster_count")),
        default=s._coerce_int(agent_brief.get("active_cluster_count"), default=0),
    )
    policy_cluster_count = s._coerce_int(
        issue_state.get("policyClusterCount", agent_brief.get("policy_cluster_count")),
        default=s._coerce_int(agent_brief.get("policy_cluster_count"), default=0),
    )
    historical_cluster_count = s._coerce_int(
        issue_state.get("historicalClusterCount", agent_brief.get("historical_cluster_count")),
        default=s._coerce_int(agent_brief.get("historical_cluster_count"), default=0),
    )
    active_error_count = s._coerce_int(issue_state.get("activeErrorCount"), default=0)
    active_warning_count = s._coerce_int(issue_state.get("activeWarningCount"), default=0)
    severity = str(agent_brief.get("severity") or diagnosis.get("severity") or issue_state.get("severity") or "info")
    status = str(agent_brief.get("diagnosis_status") or s._runtime_scene_diagnosis_status(issue_state))
    return {
        "status": status,
        "severity": severity,
        "primaryIssue": str(agent_brief.get("primary_issue") or "none"),
        "needsAction": bool(agent_brief.get("needs_action")) or active_cluster_count > 0,
        "activeClusterCount": active_cluster_count,
        "activeErrorCount": active_error_count,
        "activeWarningCount": active_warning_count,
        "policyClusterCount": policy_cluster_count,
        "policySignalCount": s._coerce_int(issue_state.get("policySignalCount"), default=0),
        "historicalClusterCount": historical_cluster_count,
        "historicalErrorCount": s._coerce_int(issue_state.get("historicalErrorCount"), default=0),
        "historicalWarningCount": s._coerce_int(issue_state.get("historicalWarningCount"), default=0),
        "controlSignalCount": s._coerce_int(issue_state.get("controlSignalCount"), default=0),
    }


def _runtime_scene_matched_fields(
    event: dict[str, Any],
    *,
    agent_id: str,
    session_id: str,
    run_id: str,
) -> dict[str, str]:
    s = _service()
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    matches: dict[str, str] = {}
    if agent_id:
        for key in ("agentId", "agent_id", "targetAgentId", "sourceAgentId", "parentAgentId"):
            if str(fields.get(key) or "").strip() == agent_id:
                matches[key] = agent_id
    if session_id:
        for key in ("sessionId", "session_id", "targetSessionId", "sourceSessionId", "parentSessionId"):
            if str(fields.get(key) or "").strip() == session_id:
                matches[key] = session_id
    if run_id:
        for key in ("runId", "turnId", "sourceRunId", "parentRunId", "activeRunId", "subRunId"):
            if str(fields.get(key) or "").strip() == run_id:
                matches[key] = run_id
    return matches


def _runtime_scene_open_operation_payload(event: dict[str, Any], operation_code: str) -> dict[str, str]:
    s = _service()
    return {
        "operationCode": operation_code,
        "component": str(event.get("component") or ""),
        "phase": str(event.get("phase") or ""),
        "startedAt": str(event.get("timestamp") or ""),
        "startEventCode": str(event.get("eventCode") or ""),
    }


def _runtime_scene_operation_timing_key(event: dict[str, Any]) -> tuple[tuple[str, str, str], str, str] | None:
    s = _service()
    event_code = str(event.get("eventCode") or event.get("event_code") or "").strip()
    parts = [part for part in event_code.split(".") if part]
    if len(parts) < 2:
        return None
    outcome = parts[-1]
    if outcome != s.OPERATION_TIMING_START_OUTCOME and outcome not in s.OPERATION_TIMING_TERMINAL_OUTCOMES:
        return None
    operation_code = ".".join(parts[:-1])
    if not operation_code:
        return None
    component = str(event.get("component") or "").strip()
    phase = str(event.get("phase") or "").strip()
    return (component, phase, operation_code), operation_code, outcome


def _runtime_scene_operation_timing_summary(events: list[dict]) -> dict[str, Any]:
    s = _service()
    pending: dict[tuple[str, str, str], dict[str, Any]] = {}
    completed: list[dict[str, Any]] = []

    for event in sorted(events, key=lambda item: str(item.get("timestamp") or item.get("ts") or "")):
        operation = s._runtime_scene_operation_timing_key(event)
        if operation is None:
            continue
        key, operation_code, outcome = operation
        if outcome == s.OPERATION_TIMING_START_OUTCOME:
            pending[key] = event
            continue
        started = pending.pop(key, None)
        if started is None:
            continue
        started_at = s._runtime_scene_event_datetime(started)
        ended_at = s._runtime_scene_event_datetime(event)
        if started_at is None or ended_at is None:
            continue
        elapsed_ms = max(0.0, round((ended_at - started_at).total_seconds() * 1000, 1))
        completed.append(
            {
                "operationCode": operation_code,
                "component": str(event.get("component") or started.get("component") or ""),
                "phase": str(event.get("phase") or started.get("phase") or ""),
                "outcome": outcome,
                "startedAt": str(started.get("timestamp") or ""),
                "endedAt": str(event.get("timestamp") or ""),
                "elapsedMs": elapsed_ms,
                "startEventCode": str(started.get("eventCode") or ""),
                "endEventCode": str(event.get("eventCode") or ""),
            }
        )

    open_operations = [
        s._runtime_scene_open_operation_payload(event, operation_code)
        for (_component, _phase, operation_code), event in pending.items()
    ]
    open_operations.sort(key=lambda item: str(item.get("startedAt") or ""), reverse=True)
    completed_recent = sorted(completed, key=lambda item: str(item.get("endedAt") or ""), reverse=True)
    completed_slowest = sorted(completed, key=lambda item: float(item.get("elapsedMs") or 0.0), reverse=True)
    return {
        "completedCount": len(completed),
        "openCount": len(open_operations),
        "recentCompleted": completed_recent[:s.OPERATION_TIMING_RECENT_LIMIT],
        "slowestCompleted": completed_slowest[:s.OPERATION_TIMING_SLOWEST_LIMIT],
        "openOperations": open_operations[:s.OPERATION_TIMING_OPEN_LIMIT],
    }


def _runtime_scene_package_sidecars_are_stale(
    scene_dir: Path,
    manifest: dict[str, Any],
    package_index: dict[str, Any],
) -> bool:
    s = _service()
    expected_index = s._runtime_scene_sidecar_compare_payload(
        s._runtime_scene_package_index_payload(scene_dir, package_index)
    )
    actual_index = s._runtime_scene_sidecar_compare_payload(
        s._load_scene_json(scene_dir / s.PACKAGE_INDEX_PATH)
    )
    if set(actual_index) != set(expected_index):
        return True
    for key, expected_value in expected_index.items():
        if actual_index.get(key) != expected_value:
            return True

    expected_summary = s._runtime_scene_sidecar_compare_payload(
        s._runtime_scene_summary_payload(scene_dir, manifest, package_index)
    )
    actual_summary = s._runtime_scene_sidecar_compare_payload(
        s._load_scene_json(scene_dir / s.SUMMARY_PATH)
    )
    if set(actual_summary) - {"generated_at"} != set(expected_summary) - {"generated_at"}:
        return True
    for key, expected_value in expected_summary.items():
        if key == "generated_at":
            continue
        if actual_summary.get(key) != expected_value:
            return True

    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    expected_package_values = s._runtime_scene_manifest_package_index_values(package_index)
    return any(package.get(key) != expected_value for key, expected_value in expected_package_values.items())


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
    s = _service()
    research_logs = research_logs if isinstance(research_logs, list) else []
    severity_summary = s._runtime_scene_severity_summary(timeline)
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
        "operationTimings": s._runtime_scene_operation_timing_summary(timeline),
    }


def _runtime_scene_prompt_index_signature(scene_summaries: list[dict[str, Any]]) -> tuple[tuple[str, str, str, str], ...]:
    s = _service()
    items: list[tuple[str, str, str, str]] = []
    for summary in scene_summaries:
        if not isinstance(summary, dict):
            continue
        scene_id = str(summary.get("runtimeSceneId") or "").strip()
        directory_name = str(summary.get("directoryName") or scene_id).strip()
        package_dir = s.PROJECT_ROOT / "logs" / "runtime_scenes" / directory_name
        package_index_path = package_dir / s.PACKAGE_INDEX_PATH
        summary_path = package_dir / s.SUMMARY_PATH
        try:
            package_index_mtime = str(package_index_path.stat().st_mtime_ns) if package_index_path.exists() else "0"
        except OSError:
            package_index_mtime = "0"
        try:
            summary_mtime = str(summary_path.stat().st_mtime_ns) if summary_path.exists() else "0"
        except OSError:
            summary_mtime = "0"
        items.append((scene_id, directory_name, package_index_mtime, summary_mtime))
    return tuple(items)


def _runtime_scene_reconciliation_history_events(scene_dir: Path) -> list[dict[str, Any]]:
    s = _service()
    events = [
        *s._read_jsonl_file(scene_dir / s.EVENTS_DIR / "runtime_manager.jsonl"),
        *s._read_jsonl_file(scene_dir / s.TIMELINE_PATH),
    ]
    return sorted(
        events,
        key=lambda item: (
            str(item.get("ts") or ""),
            s._coerce_int(item.get("seq"), default=0),
        ),
    )


def _runtime_scene_retention_sort_key(scene_dir: Path, manifest: dict[str, Any]) -> tuple[str, str]:
    s = _service()
    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    started = s._resolve_scene_started_at(str(manifest.get("started_at") or package.get("started_at") or ""), scene_dir)
    if started is not None:
        return (started.isoformat(), scene_dir.name)
    return ("", scene_dir.name)


def _runtime_scene_severity_summary(events: list[dict]) -> dict[str, int]:
    s = _service()
    error_count = 0
    warning_count = 0
    for event in events:
        severity = s._runtime_scene_event_severity(event)
        if severity == "error":
            error_count += 1
        elif severity == "warning":
            warning_count += 1
    return {
        "errorCount": error_count,
        "warningCount": warning_count,
    }


def _runtime_scene_sidecar_compare_payload(payload: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    normalized = dict(payload) if isinstance(payload, dict) else {}
    snapshot_metadata = normalized.get("snapshot_metadata")
    if isinstance(snapshot_metadata, dict):
        stable_snapshot = dict(snapshot_metadata)
        stable_snapshot.pop("generated_at", None)
        normalized["snapshot_metadata"] = stable_snapshot
    return normalized


def _runtime_scene_signal_raw_refs(event: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
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
    fallback_path = s._runtime_scene_component_evidence_path(component)
    if fallback_path:
        return [{"path": fallback_path, "tail_lines": 80}]
    return []


def _safe_current_runtime_scene_dir_for_retention() -> Path | None:
    s = _service()
    try:
        return s._resolve_current_runtime_scene_dir()
    except Exception:
        return None


def _sync_runtime_scene_package_sidecars_if_stale(
    scene_dir: Path,
    manifest: dict[str, Any],
    package_index: dict[str, Any],
) -> None:
    s = _service()
    if not s._runtime_scene_package_sidecars_are_stale(scene_dir, manifest, package_index):
        return
    try:
        s._update_runtime_scene_package_manifest(scene_dir, manifest)
    except OSError:
        return


def _truncate_prompt_index_text(value: str, limit: int) -> str:
    s = _service()
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: max(0, limit - 3)]}..."


def build_runtime_scene_prompt_index(limit: int = 3) -> str:
    """Return a compact prompt-facing index for the newest runtime scene packages."""
    s = _service()

    bounded_limit = max(1, min(int(limit or 3), 10))
    try:
        scene_summaries = s.list_runtime_scenes(limit=bounded_limit)
    except Exception:
        return ""

    if not scene_summaries:
        return ""

    signature = s._runtime_scene_prompt_index_signature(scene_summaries[:bounded_limit])
    cached = s._get_runtime_scene_prompt_index_cache(bounded_limit, signature)
    if cached is not None:
        return cached

    lines = [
        "## RUNTIME_LOG_INDEX",
        "- 最近运行现场索引；用于先定位日志包，再按需读取 detail/raw 子日志。",
        "- 只注入结构化摘要和路径，不注入 raw 日志全文、完整对话或完整工具输出。",
    ]
    for index, summary in enumerate(scene_summaries[:bounded_limit], start=1):
        scene_id = str(summary.get("runtimeSceneId") or "").strip()
        detail: dict[str, Any] = {}
        if scene_id:
            try:
                detail = s.get_runtime_scene_detail(scene_id)
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
        next_step = s._truncate_prompt_index_text(str(package_diagnosis.get("agentNextStep") or ""), 360)
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

    rendered = "\n".join(lines).strip()
    s._remember_runtime_scene_prompt_index_cache(bounded_limit, signature, rendered)
    return rendered


def get_runtime_scene_detail(scene_id: str) -> dict:
    """Return one runtime scene bundle with manifest, merged timeline, and raw file metadata."""
    s = _service()

    scene_dir = s._resolve_scene_dir(scene_id)
    manifest = s._load_scene_manifest(scene_dir)
    s._repair_runtime_scene_from_reconciliation_history(scene_dir, manifest)
    detail_scene_id = s._scene_id(scene_dir, manifest)
    timeline = s._read_scene_timeline(scene_dir)
    raw_files = s._list_raw_files(scene_dir)
    lifecycle_events = s._read_scene_lifecycle(scene_dir, timeline)
    conversation_logs = s._list_conversation_logs(scene_dir)
    agent_logs = s._list_agent_logs(scene_dir)
    artifacts = s._list_artifacts(scene_dir)
    event_logs = s._list_event_logs(scene_dir)
    research_logs = s._list_research_logs(scene_dir)
    package_index = s._runtime_scene_package_index(scene_dir, manifest, detail_scene_id)
    s._sync_runtime_scene_package_sidecars_if_stale(scene_dir, manifest, package_index)
    summary_payload = s._load_scene_json(scene_dir / s.SUMMARY_PATH)
    package_diagnosis = summary_payload.get("diagnosis") if isinstance(summary_payload.get("diagnosis"), dict) else {}
    return {
        "runtimeSceneId": detail_scene_id,
        "directoryName": scene_dir.name,
        "displayName": package_index["displayName"],
        "packageIndex": package_index,
        "manifestPath": str((scene_dir / "manifest.json").relative_to(s.PROJECT_ROOT).as_posix()),
        "manifest": manifest,
        "startedAt": package_index["startedAt"],
        "endedAt": str(manifest.get("ended_at") or ""),
        "status": s._runtime_scene_status(manifest),
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
        "packageSummary": s._runtime_scene_package_summary(
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
        "diagnosisSummary": s._runtime_scene_list_diagnosis_summary(summary_payload),
    }


def list_runtime_scene_evidence_for_agent(
    agent_id: str,
    *,
    session_id: str = "",
    run_id: str = "",
    limit: int = 5,
    scene_limit: int = 12,
) -> dict[str, Any]:
    """Return recent runtime scene events that mention one Agent/session/run."""
    s = _service()

    normalized_agent_id = str(agent_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_run_id = str(run_id or "").strip()
    if not any([normalized_agent_id, normalized_session_id, normalized_run_id]):
        return {"agentId": normalized_agent_id, "sessionId": normalized_session_id, "runId": normalized_run_id, "matches": []}

    bounded_limit = max(1, min(int(limit or 5), 20))
    bounded_scene_limit = max(1, min(int(scene_limit or 12), 30))
    matches: list[dict[str, Any]] = []
    for scene_dir in s._scene_dirs()[:bounded_scene_limit]:
        manifest = s._load_scene_manifest(scene_dir)
        scene_id = s._scene_id(scene_dir, manifest)
        if not scene_id:
            continue
        package_index = s._runtime_scene_lightweight_package_index(scene_dir, manifest, scene_id)
        for event in reversed(s._read_scene_timeline(scene_dir)):
            if not s._runtime_scene_event_matches_agent(
                event,
                agent_id=normalized_agent_id,
                session_id=normalized_session_id,
                run_id=normalized_run_id,
            ):
                continue
            matches.append(
                {
                    "runtimeSceneId": scene_id,
                    "directoryName": scene_dir.name,
                    "displayName": package_index["displayName"],
                    "startedAt": package_index["startedAt"],
                    "status": s._runtime_scene_status(manifest),
                    "eventCode": str(event.get("eventCode") or ""),
                    "component": str(event.get("component") or ""),
                    "phase": str(event.get("phase") or ""),
                    "level": str(event.get("level") or ""),
                    "outcome": str(event.get("outcome") or ""),
                    "message": str(event.get("message") or ""),
                    "timestamp": str(event.get("timestamp") or ""),
                    "rawRefs": s._runtime_scene_signal_raw_refs(event),
                    "matchedFields": s._runtime_scene_matched_fields(
                        event,
                        agent_id=normalized_agent_id,
                        session_id=normalized_session_id,
                        run_id=normalized_run_id,
                    ),
                }
            )
            if len(matches) >= bounded_limit:
                return {
                    "agentId": normalized_agent_id,
                    "sessionId": normalized_session_id,
                    "runId": normalized_run_id,
                    "matches": matches,
                }
    return {
        "agentId": normalized_agent_id,
        "sessionId": normalized_session_id,
        "runId": normalized_run_id,
        "matches": matches,
    }


def list_runtime_scenes(limit: int = 80) -> list[dict]:
    """Return runtime scene summaries sorted by most recent first."""
    s = _service()

    s._enforce_runtime_scene_retention()
    scenes: list[dict] = []
    for scene_dir in s._scene_dirs():
        manifest = s._load_scene_manifest(scene_dir)
        scene_id = s._scene_id(scene_dir, manifest)
        if not scene_id:
            continue
        summary_payload = s._load_scene_json(scene_dir / s.SUMMARY_PATH)
        event_counts = summary_payload.get("event_counts") if isinstance(summary_payload.get("event_counts"), dict) else {}
        package_index = s._runtime_scene_lightweight_package_index(scene_dir, manifest, scene_id, summary_payload)
        scenes.append(
            {
                "runtimeSceneId": scene_id,
                "directoryName": scene_dir.name,
                "title": str(manifest.get("title") or scene_dir.name),
                "displayName": package_index["displayName"],
                "packageIndex": package_index,
                "startedAt": package_index["startedAt"],
                "endedAt": str(manifest.get("ended_at") or ""),
                "status": s._runtime_scene_status(manifest),
                "result": str(manifest.get("result") or ""),
                "stopReason": str(manifest.get("stop_reason") or ""),
                "trigger": str(manifest.get("trigger") or ""),
                "sessionMode": str(manifest.get("session_mode") or ""),
                "backendStatus": str(((manifest.get("backend") or {}) if isinstance(manifest.get("backend"), dict) else {}).get("health_status") or ""),
                "frontendStatus": str(((manifest.get("frontend") or {}) if isinstance(manifest.get("frontend"), dict) else {}).get("build_status") or ""),
                "browserStatus": str(((manifest.get("browser") or {}) if isinstance(manifest.get("browser"), dict) else {}).get("status") or ""),
                "eventCount": s._coerce_int(event_counts.get("timeline_events"), default=0),
                "rawLogCount": s._coerce_int(event_counts.get("raw_logs"), default=0),
                "conversationCount": s._coerce_int(event_counts.get("conversation_logs"), default=0),
                "agentLogCount": s._coerce_int(event_counts.get("agent_logs"), default=0),
                "artifactCount": s._coerce_int(event_counts.get("artifacts"), default=0),
                "eventLogCount": s._coerce_int(event_counts.get("event_logs"), default=0),
                "researchLogCount": s._coerce_int(event_counts.get("research_files"), default=0),
                "errorCount": s._coerce_int(event_counts.get("errors"), default=0),
                "warningCount": s._coerce_int(event_counts.get("warnings"), default=0),
                "diagnosisSummary": s._runtime_scene_list_diagnosis_summary(summary_payload),
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


def read_runtime_scene_file(scene_id: str, relative_path: str) -> dict:
    """Read a raw or structured file from one runtime scene bundle."""
    s = _service()

    scene_dir = s._resolve_scene_dir(scene_id)
    relative = s._normalize_relative_path(relative_path)
    file_path = s._resolve_scene_child(scene_dir, relative)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Runtime scene file not found: {relative}")
    raw = file_path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("Binary runtime scene files are not supported in the preview yet")
    content = raw.decode("utf-8-sig", errors="replace")
    truncated = len(content) > s.MAX_TEXT_CHARS
    if truncated:
        content = content[:s.MAX_TEXT_CHARS] + "\n\n... preview truncated ..."
    scene_root_path = scene_dir.relative_to(s.PROJECT_ROOT).as_posix()
    return {
        "rootId": "runtime_scenes",
        "rootPath": scene_root_path,
        "relativePath": relative,
        "path": f"{scene_root_path}/{relative}".replace("//", "/"),
        "language": s.LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text"),
        "content": content,
        "truncated": truncated,
        "diagnostics": s._analyze_runtime_scene_content(scene_id, relative, content),
    }
