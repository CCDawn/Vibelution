"""Structured runtime scene bundles for frontend inspection and agent diagnosis."""

from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any

from core.infrastructure import developer_sandbox
from core.web.services.log_diagnostics import analyze_log_content
from .runtime_scene.record import (
    _append_agent_tool_call_logs,
    _append_agent_turn_log,
    _append_scene_event,
    _append_scene_jsonl,
    _append_scene_log_line,
    _browser_manifest_for_role,
    _browser_manifest_key_for_existing_browser,
    _browser_manifest_key_for_telemetry,
    _camel_to_snake,
    _coerce_float,
    _coerce_int,
    _copy_jsonl_rows,
    _count_runtime_scene_files,
    _display_name_status_label,
    _display_name_time_label,
    _display_name_trigger_label,
    _event_payload_to_client_item,
    _file_timestamp,
    _get_jsonl_file_cache,
    _humanize_runtime_token,
    _is_current_runtime_scene_manifest,
    _is_dev_browser_telemetry_surface,
    _is_diagnostic_probe_404,
    _is_known_benign_browser_event,
    _is_lifecycle_event,
    _is_readable_file,
    _is_safe_usage_counter_key,
    _is_sensitive_telemetry_key,
    _is_structured_telemetry_key,
    _is_test_client_client_error,
    _iter_runtime_scene_descendants,
    _join_index_key_parts,
    _join_search_text,
    _jsonl_file_signature,
    _list_agent_logs,
    _list_artifacts,
    _list_conversation_logs,
    _list_event_logs,
    _list_package_files,
    _list_raw_files,
    _list_research_logs,
    _load_active_runtime_scene_reference,
    _load_launcher_state,
    _load_scene_json,
    _load_scene_manifest,
    _looks_like_windows_absolute_path,
    _maybe_close_runtime_scene_from_reconciliation,
    _next_research_event_seq,
    _next_scene_event_seq,
    _normalize_endpoint_path,
    _normalize_event_timestamp,
    _normalize_raw_refs,
    _normalize_relative_path,
    _normalize_scene_ids,
    _normalize_structured_telemetry_value,
    _normalize_telemetry_fields,
    _normalize_telemetry_value,
    _now_utc,
    _package_index_status_token,
    _package_index_trigger_token,
    _parse_datetime,
    _parse_directory_timestamp_token,
    _read_jsonl_file,
    _read_last_scene_event_seq,
    _read_scene_lifecycle,
    _read_scene_timeline,
    _remember_jsonl_file_cache,
    _remember_scene_event_seq,
    _resolve_current_runtime_scene_dir,
    _resolve_recent_completed_runtime_scene_dir,
    _resolve_scene_child,
    _resolve_scene_dir,
    _resolve_scene_started_at,
    _runtime_scene_base_package_index,
    _runtime_scene_conversation_correlation_ids,
    _runtime_scene_conversation_message_summary,
    _runtime_scene_display_name,
    _runtime_scene_event_requires_full_projection_refresh,
    _runtime_scene_event_requires_immediate_projection,
    _runtime_scene_file_size,
    _runtime_scene_first_safe_id,
    _runtime_scene_has_completed,
    _runtime_scene_index_tags,
    _runtime_scene_is_diagnostic_only_observation,
    _runtime_scene_lightweight_package_index,
    _runtime_scene_lightweight_package_index_payload,
    _runtime_scene_manifest_package_index_values,
    _runtime_scene_package_index,
    _runtime_scene_package_index_payload,
    _runtime_scene_payload_has_diagnostic_signal,
    _runtime_scene_project_matches,
    _runtime_scene_research_summary_event,
    _runtime_scene_research_summary_payload,
    _runtime_scene_root,
    _runtime_scene_safe_id,
    _runtime_scene_safe_tool_calls,
    _runtime_scene_snapshot_metadata,
    _runtime_scene_status,
    _runtime_scene_summary_counts,
    _runtime_scene_summary_payload,
    _runtime_scene_summary_sections,
    _safe_optional_relative_path,
    _same_path,
    _sanitize_path_token,
    _sanitize_token,
    _save_runtime_scene_lightweight_package_index,
    _save_runtime_scene_package_index,
    _save_runtime_scene_research_summary,
    _save_runtime_scene_summary,
    _save_scene_manifest,
    _scene_dirs,
    _scene_duration_seconds,
    _scene_event_file_signature,
    _scene_id,
    _seconds_between_iso,
    _should_index_browser_memory_sample,
    _should_index_browser_telemetry_event,
    _should_promote_scene_event_to_timeline,
    _slugify_index_token,
    _truncate_text,
    _update_backend_api_manifest,
    _update_browser_manifest,
    _update_ignored_browser_telemetry_manifest,
    _update_runtime_scene_package_manifest,
    _update_runtime_scene_package_manifest_lightweight,
    delete_runtime_scenes,
    record_backend_api_event,
    record_browser_telemetry,
    record_electron_supervisor_event,
    record_research_scene_event,
    record_runtime_scene_conversation_event,
    record_runtime_scene_event,
)
from .runtime_scene.query import (
    _analyze_runtime_scene_content,
    _can_delete_runtime_scene_for_retention,
    _closed_reconciliation_fields,
    _enforce_runtime_scene_retention,
    _get_runtime_scene_prompt_index_cache,
    _is_runtime_scene_reopen_event,
    _is_runtime_scene_retention_protected,
    _latest_closed_reconciliation_event,
    _record_runtime_scene_retention_pruned,
    _remember_runtime_scene_prompt_index_cache,
    _repair_runtime_scene_from_reconciliation_history,
    _runtime_scene_component_evidence_path,
    _runtime_scene_diagnosis_status,
    _runtime_scene_event_component_filename,
    _runtime_scene_event_datetime,
    _runtime_scene_event_endpoint,
    _runtime_scene_event_matches_agent,
    _runtime_scene_event_severity,
    _runtime_scene_event_status_code,
    _runtime_scene_is_diagnostic_mirror_event,
    _runtime_scene_is_operational_client_error_event,
    _runtime_scene_is_supervisor_clean_exit_adopted_event,
    _runtime_scene_list_diagnosis_summary,
    _runtime_scene_matched_fields,
    _runtime_scene_open_operation_payload,
    _runtime_scene_operation_timing_key,
    _runtime_scene_operation_timing_summary,
    _runtime_scene_package_sidecars_are_stale,
    _runtime_scene_package_summary,
    _runtime_scene_prompt_index_signature,
    _runtime_scene_reconciliation_history_events,
    _runtime_scene_retention_sort_key,
    _runtime_scene_severity_summary,
    _runtime_scene_sidecar_compare_payload,
    _runtime_scene_signal_raw_refs,
    _safe_current_runtime_scene_dir_for_retention,
    _sync_runtime_scene_package_sidecars_if_stale,
    _truncate_prompt_index_text,
    build_runtime_scene_prompt_index,
    get_runtime_scene_detail,
    list_runtime_scene_evidence_for_agent,
    list_runtime_scenes,
    read_runtime_scene_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_STATE_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "state.json"
MAX_TEXT_CHARS = 200_000
MAX_PACKAGE_INDEX_SEARCH_TEXT_CHARS = 6_000
JSONL_FILE_CACHE_LIMIT = 256
RUNTIME_SCENE_PROMPT_INDEX_CACHE_TTL_SECONDS = 5.0
BROWSER_TELEMETRY_RAW_PATH = "raw/browser.telemetry.log"
BROWSER_TELEMETRY_COMPONENT = "browser_page"
BROWSER_MEMORY_INDEX_MIN_SECONDS = 300.0
BROWSER_MEMORY_INDEX_HEAP_DELTA_MB = 128.0
BACKEND_API_RAW_PATH = "raw/backend.api.log"
BACKEND_COMPONENT = "backend"
CONFIG_MODEL_DISCOVERY_ENDPOINT = "/api/config/discover-models"
OPERATIONAL_CLIENT_ERROR_PATHS = {CONFIG_MODEL_DISCOVERY_ENDPOINT}
DIAGNOSTIC_PROBE_404_PATHS = {
    "/api/runtime",
    "/api/runtime/status",
}
TEST_CLIENT_HOSTS = {"testclient"}
AGENT_DIRECTORY_TRANSIENT_SLOW_TOTAL_MS = 8_000.0
AGENT_DIRECTORY_TRANSIENT_SLOW_REPEAT_LIMIT = 2
TIMELINE_PATH = "timeline.jsonl"
LIFECYCLE_PATH = "lifecycle.jsonl"
PACKAGE_INDEX_PATH = "package_index.json"
SUMMARY_PATH = "summary.json"
CONVERSATIONS_DIR = "conversations"
SESSIONS_DIR = "sessions"
RUNS_DIR = "runs"
AGENT_DIR = "agent"
ARTIFACTS_DIR = "artifacts"
EVENTS_DIR = "events"
RESEARCH_DIR = "research"
RESEARCH_EVENTS_PATH = f"{RESEARCH_DIR}/events.jsonl"
RESEARCH_SUMMARY_PATH = f"{RESEARCH_DIR}/summary.json"
RUNTIME_SCENE_RETENTION_LIMIT = 30
MAX_TELEMETRY_TEXT_CHARS = 4_000
MAX_TELEMETRY_FIELD_TEXT_CHARS = 1_200
MAX_TELEMETRY_FIELD_ITEMS = 24
STRUCTURED_TELEMETRY_KEYS = {"llm_bindings", "llmbindings", "agent_binding", "agentbinding"}
BROWSER_VISIBILITY_TIMELINE_MIN_SECONDS = 60.0
WORK_RUN_SNAPSHOT_EVENT_CODE = "work_run.snapshot.persisted"
WORK_RUN_SNAPSHOT_SUMMARY_EVENT_CODE = "work_run.snapshot.summary"
ELECTRON_SUPERVISOR_EVENT_CODES = {
    "electron.launcher.supervisor.started",
    "electron.launcher.window.opened",
    "electron.workbench.window.opened",
    "electron.launcher_service.started",
    "electron.launcher_service.exited",
    "electron.desktop_action.claimed",
    "electron.desktop_action.succeeded",
    "electron.desktop_action.failed",
}
WORK_RUN_HIGH_FREQUENCY_SNAPSHOT_THRESHOLD = 5
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
_JSONL_FILE_CACHE_LOCK = Lock()
_JSONL_FILE_CACHE: dict[tuple[str, bool, int, int], list[dict[str, Any]]] = {}
_SCENE_EVENT_SEQ_CACHE_LOCK = Lock()
_SCENE_EVENT_SEQ_CACHE: dict[str, tuple[int, int, int]] = {}
NON_PROBLEM_NEXT_STATE_KINDS = {
    "assistant_output_edited",
    "user_continues",
    "user_stops",
}
EXPECTED_RUNTIME_MANAGER_BLOCK_ERROR_TYPES = {
    "selfevolutionrunbusyerror",
    "workrunbusyerror",
    "runtimecommandbusyerror",
}
WORK_RUN_ACTIVE_STATUSES = {
    "queued",
    "starting",
    "running",
    "reading",
    "paused",
    "needs_continue",
    "needs_review",
    "pending",
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
OPERATION_TIMING_START_OUTCOME = "started"
OPERATION_TIMING_TERMINAL_OUTCOMES = {
    "blocked",
    "cancelled",
    "completed",
    "failed",
    "skipped",
    "succeeded",
}
OPERATION_TIMING_RECENT_LIMIT = 12
OPERATION_TIMING_SLOWEST_LIMIT = 8
OPERATION_TIMING_OPEN_LIMIT = 8
ISSUE_IDENTITY_FIELD_KEYS = (
    "activeRunId",
    "commandId",
    "pageInstanceId",
    "runId",
    "sessionId",
    "turnId",
)
TIMELINE_DIAGNOSTIC_ONLY_EVENT_CODES = {
    "agent.repaired",
    "agent_territory.resolved",
    "browser.session_stream.closed",
    "browser.session_stream.effect_started",
    "browser.session_stream.opened",
    "browser.session_stream.skipped",
    "browser.session_stream.snapshot_applied",
    "conversation.index.filtered_archived_team_rooms",
    "runtime.snapshot.reconciled",
    "session.agent_missing.hidden_from_index",
    "session.agent_missing.hidden_from_index.batch",
    "session.detail_snapshot.published",
    "session.detail_snapshot.throttled",
    "session.list.loaded",
}
TIMELINE_DIAGNOSTIC_ONLY_PHASES = {
    "agent",
    "session_detail",
    "session_index",
    "session_list",
    "session_stream",
}
TIMELINE_DIAGNOSTIC_ONLY_COMPONENT_PHASES = {
    ("agent_directory", "agent"),
    ("agent_directory", "territory"),
    ("conversation_service", "session_index"),
    ("runtime_manager", "runtime"),
}
from core.logging import pipeline_metrics


BROWSER_TELEMETRY_WRITE_LOCK = Lock()
BACKEND_API_WRITE_LOCK = Lock()
RUNTIME_SCENE_PACKAGE_WRITE_LOCK = Lock()
RUNTIME_SCENE_EVENT_WRITE_LOCK = Lock()
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
    "raw/browser.process-memory.log": "Managed browser process memory",
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
    "internal-focus": "工作台聚焦",
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
    "internal-focus": "workbench-focus",
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


_RUNTIME_SCENE_PROMPT_INDEX_CACHE_LOCK = Lock()
_RUNTIME_SCENE_PROMPT_INDEX_CACHE: dict[tuple[int, tuple[tuple[str, str, str, str], ...]], tuple[float, str]] = {}


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
    work_run_summary = diagnosis.get("workRunSummary") if isinstance(diagnosis.get("workRunSummary"), dict) else {}

    if active_count > 0 or severity in {"error", "critical"}:
        diagnosis_status = "active_issue"
        needs_action = True
        actionability = "fix_required"
        do_not_do = ["do not ignore active clusters without checking their evidence paths"]
        primary_issue = _runtime_scene_agent_brief_issue(first_signal, fallback=diagnosis_status)
    elif policy_count > 0:
        diagnosis_status = "policy_only"
        needs_action = False
        actionability = "policy_acknowledge_only"
        do_not_do = ["do not treat expected policy blocks as product/runtime bugs"]
        primary_issue = _runtime_scene_agent_brief_issue(first_signal, fallback=diagnosis_status)
    elif historical_count > 0:
        diagnosis_status = "resolved"
        needs_action = False
        actionability = "no_action_needed"
        do_not_do = ["do not keep chasing historical recovered errors as active blockers"]
        primary_issue = "none"
    else:
        diagnosis_status = "healthy"
        needs_action = False
        actionability = "no_action_needed"
        do_not_do = ["do not open raw logs unless a new signal appears"]
        primary_issue = "none"

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
        "work_run_focus": _runtime_scene_agent_work_run_focus(work_run_summary),
        "do_not_do": do_not_do,
    }


def _runtime_scene_agent_brief_issue(first_signal: dict[str, Any], *, fallback: str) -> str:
    return str(
        first_signal.get("event")
        or first_signal.get("type")
        or first_signal.get("eventCode")
        or first_signal.get("component")
        or fallback
    )


def _runtime_scene_agent_work_run_focus(work_run_summary: dict[str, Any]) -> dict[str, Any]:
    active_runs = work_run_summary.get("activeRuns") if isinstance(work_run_summary.get("activeRuns"), list) else []
    high_frequency_runs = work_run_summary.get("highFrequencyRuns") if isinstance(work_run_summary.get("highFrequencyRuns"), list) else []
    first_active = active_runs[0] if active_runs and isinstance(active_runs[0], dict) else {}
    first_high_frequency = high_frequency_runs[0] if high_frequency_runs and isinstance(high_frequency_runs[0], dict) else {}
    return {
        "events_path": str(work_run_summary.get("eventsPath") or ""),
        "snapshot_event_count": int(work_run_summary.get("snapshotEventCount") or 0),
        "run_count": int(work_run_summary.get("runCount") or 0),
        "active_run_count": int(work_run_summary.get("activeRunCount") or 0),
        "high_frequency_run_count": int(work_run_summary.get("highFrequencyRunCount") or 0),
        "first_active_run": {
            "runKind": str(first_active.get("runKind") or ""),
            "runId": str(first_active.get("runId") or ""),
            "latestStatus": str(first_active.get("latestStatus") or ""),
            "latestPhase": str(first_active.get("latestPhase") or ""),
            "latestAt": str(first_active.get("latestAt") or ""),
        },
        "first_high_frequency_run": {
            "runKind": str(first_high_frequency.get("runKind") or ""),
            "runId": str(first_high_frequency.get("runId") or ""),
            "snapshotCount": int(first_high_frequency.get("snapshotCount") or 0),
            "latestStatus": str(first_high_frequency.get("latestStatus") or ""),
        },
    }


def _sync_runtime_scene_package_index_if_stale(
    scene_dir: Path,
    manifest: dict[str, Any],
    package_index: dict[str, Any],
) -> None:
    if not _runtime_scene_package_index_sidecar_is_stale(scene_dir, manifest, package_index):
        return
    try:
        _save_runtime_scene_lightweight_package_index(scene_dir, package_index)
        _update_runtime_scene_manifest_package_index_fields(scene_dir, manifest, package_index)
    except OSError:
        return


def _runtime_scene_package_index_sidecar_is_stale(
    scene_dir: Path,
    manifest: dict[str, Any],
    package_index: dict[str, Any],
) -> bool:
    expected_index = _runtime_scene_sidecar_compare_payload(
        _runtime_scene_lightweight_package_index_payload(package_index)
    )
    actual_index = _runtime_scene_sidecar_compare_payload(
        _load_scene_json(scene_dir / PACKAGE_INDEX_PATH)
    )
    for key, expected_value in expected_index.items():
        if actual_index.get(key) != expected_value:
            return True

    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    expected_package_values = _runtime_scene_manifest_package_index_values(package_index)
    return any(package.get(key) != expected_value for key, expected_value in expected_package_values.items())


def _update_runtime_scene_manifest_package_index_fields(
    scene_dir: Path,
    manifest: dict[str, Any],
    package_index: dict[str, Any],
) -> None:
    package = manifest.get("package")
    if not isinstance(package, dict):
        package = {}
    package.update({"schema_version": 2, **_runtime_scene_manifest_package_index_values(package_index)})
    package["updated_at"] = _now_utc()
    manifest["package"] = package
    _save_scene_manifest(scene_dir, manifest)


def _runtime_scene_package_index_from_diagnosis(
    scene_dir: Path,
    manifest: dict,
    scene_id: str,
    diagnosis: dict[str, Any],
    *,
    cached_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    package_index = _runtime_scene_base_package_index(
        scene_dir,
        manifest,
        scene_id,
        cached_package=cached_package,
    )
    tags = list(package_index["tags"])
    diagnosis_tags = _runtime_scene_diagnosis_tags(diagnosis)
    tags = [*tags, *[tag for tag in diagnosis_tags if tag not in tags]]
    package_index["tags"] = tags
    issue_state = diagnosis.get("issueState") if isinstance(diagnosis.get("issueState"), dict) else {}
    primary_cluster = _runtime_scene_primary_issue_cluster(issue_state)
    first_signal = diagnosis.get("firstSignal") if isinstance(diagnosis.get("firstSignal"), dict) else None
    package_index["searchText"] = _join_search_text(
        [
            package_index["searchText"],
            _runtime_scene_diagnosis_status(issue_state),
            _runtime_scene_primary_cause_token(diagnosis, primary_cluster, first_signal),
            _runtime_scene_primary_cause_label(primary_cluster, first_signal),
            diagnosis.get("severity"),
            diagnosis.get("userSummary"),
            diagnosis.get("agentNextStep"),
            *tags,
        ]
    )
    return package_index


def _runtime_scene_diagnosis_events(scene_dir: Path, timeline: list[dict]) -> list[dict]:
    """Add low-noise component events needed only to prove recovery."""

    events = list(timeline)
    seen = {_runtime_scene_event_dedupe_key(event) for event in events}
    for event in _runtime_scene_recovery_evidence_events(scene_dir):
        key = _runtime_scene_event_dedupe_key(event)
        if key in seen:
            continue
        seen.add(key)
        events.append(event)
    events.sort(key=lambda item: (item["timestamp"], item["component"], item["seq"]))
    return events


def _runtime_scene_recovery_evidence_events(scene_dir: Path) -> list[dict]:
    browser_events_path = scene_dir / EVENTS_DIR / "browser_page.jsonl"
    events: list[dict] = []
    for entry in _read_jsonl_file(browser_events_path):
        event = _event_payload_to_client_item(entry, scene_dir, BROWSER_TELEMETRY_COMPONENT)
        if _runtime_scene_is_recovery_evidence_event(event):
            events.append(event)
    return events


def _runtime_scene_is_recovery_evidence_event(event: dict[str, Any]) -> bool:
    if str(event.get("component") or "") != BROWSER_TELEMETRY_COMPONENT:
        return False
    event_code = str(event.get("eventCode") or "").strip()
    if event_code in {
        "browser.session_stream.opened",
        "browser.session_stream.snapshot_applied",
    }:
        return True
    return False


def _runtime_scene_event_dedupe_key(event: dict[str, Any]) -> tuple[str, str, str, int, str]:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    identity = (
        str(fields.get("pageInstanceId") or "")
        or str(fields.get("sessionId") or "")
        or _runtime_scene_signal_message_signature(str(event.get("message") or ""))
    )
    return (
        str(event.get("timestamp") or ""),
        str(event.get("component") or ""),
        str(event.get("eventCode") or ""),
        int(event.get("seq") or 0),
        identity,
    )


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


def _runtime_scene_primary_cause_token(
    diagnosis: dict[str, Any],
    primary_cluster: dict[str, Any] | None,
    first_signal: dict[str, Any] | None,
) -> str:
    source = primary_cluster if isinstance(primary_cluster, dict) else first_signal if isinstance(first_signal, dict) else {}
    component = str(source.get("component") or "").strip()
    event_code = str(source.get("eventCode") or "").strip()
    if event_code.startswith("config.model_discovery."):
        return _slugify_index_token(event_code, default="runtime-signal")
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
    diagnosis_events = _runtime_scene_diagnosis_events(scene_dir, timeline)
    issue_state = _runtime_scene_issue_state(diagnosis_events)
    severity = str(issue_state.get("severity") or "info")
    first_signal = _runtime_scene_first_signal(diagnosis_events, issue_state=issue_state)
    if first_signal is None:
        first_signal = _runtime_scene_first_key_event(lifecycle, diagnosis_events)
    startup_trace = _runtime_scene_startup_trace(scene_dir=scene_dir, manifest=manifest, timeline=timeline)
    work_run_summary = _runtime_scene_work_run_summary(scene_dir, timeline)
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
        "workRunSummary": work_run_summary,
        "recommendedOrder": recommended_order,
        "keyEntries": key_entries,
        "evidencePaths": evidence_paths,
    }


def _runtime_scene_work_run_summary(scene_dir: Path, timeline: list[dict]) -> dict[str, Any]:
    events_path = f"{EVENTS_DIR}/work_run.jsonl"
    raw_rows = _read_jsonl_file(scene_dir / events_path)
    if raw_rows:
        work_run_events = [_event_payload_to_client_item(row, scene_dir, "work_run") for row in raw_rows]
        source_path = events_path
    else:
        timeline_rows = _read_jsonl_file(scene_dir / TIMELINE_PATH)
        if timeline_rows:
            work_run_events = [
                _event_payload_to_client_item(row, scene_dir, "timeline")
                for row in timeline_rows
                if str(row.get("component") or "").strip() == "work_run"
            ]
            source_path = TIMELINE_PATH
        else:
            work_run_events = [
                event
                for event in timeline
                if str(event.get("component") or "").strip() == "work_run"
            ]
            source_path = TIMELINE_PATH

    snapshot_events = [
        event
        for event in work_run_events
        if str(event.get("eventCode") or "") == WORK_RUN_SNAPSHOT_EVENT_CODE
    ]
    runs: dict[tuple[str, str], dict[str, Any]] = {}
    for event in snapshot_events:
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        run_kind = str(fields.get("runKind") or "").strip() or "unknown"
        run_id = str(fields.get("runId") or "").strip() or "unknown"
        key = (run_kind, run_id)
        run = runs.setdefault(
            key,
            {
                "runKind": run_kind,
                "runId": run_id,
                "snapshotCount": 0,
                "latestAt": "",
                "latestStatus": "",
                "latestPhase": "",
                "activeRunId": "",
                "runtimeStatus": "",
                "snapshotPath": "",
                "statusCounts": {},
            },
        )
        status = str(fields.get("status") or "").strip()
        timestamp = str(event.get("timestamp") or "").strip()
        run["snapshotCount"] = int(run.get("snapshotCount") or 0) + 1
        status_counts = run["statusCounts"] if isinstance(run.get("statusCounts"), dict) else {}
        if status:
            status_counts[status] = int(status_counts.get(status) or 0) + 1
        run["statusCounts"] = status_counts
        if timestamp >= str(run.get("latestAt") or ""):
            run["latestAt"] = timestamp
            run["latestStatus"] = status
            run["latestPhase"] = str(fields.get("phase") or "").strip()
            run["activeRunId"] = str(fields.get("activeRunId") or "").strip()
            run["runtimeStatus"] = str(fields.get("runtimeStatus") or "").strip()
            run["snapshotPath"] = str(fields.get("snapshotPath") or "").strip()

    run_summaries = sorted(
        runs.values(),
        key=lambda item: (str(item.get("latestAt") or ""), str(item.get("runKind") or ""), str(item.get("runId") or "")),
        reverse=True,
    )
    active_runs = [item for item in run_summaries if _work_run_status_is_active(str(item.get("latestStatus") or ""))]
    high_frequency_runs = sorted(
        [
            item
            for item in run_summaries
            if int(item.get("snapshotCount") or 0) >= WORK_RUN_HIGH_FREQUENCY_SNAPSHOT_THRESHOLD
        ],
        key=lambda item: (int(item.get("snapshotCount") or 0), str(item.get("latestAt") or "")),
        reverse=True,
    )
    return {
        "schemaVersion": 1,
        "eventsPath": source_path,
        "workRunEventCount": len(work_run_events),
        "snapshotEventCount": len(snapshot_events),
        "runCount": len(run_summaries),
        "activeRunCount": len(active_runs),
        "highFrequencyRunCount": len(high_frequency_runs),
        "latestRuns": [_runtime_scene_work_run_public_summary(item) for item in run_summaries[:8]],
        "activeRuns": [_runtime_scene_work_run_public_summary(item) for item in active_runs[:8]],
        "highFrequencyRuns": [_runtime_scene_work_run_public_summary(item) for item in high_frequency_runs[:8]],
    }


def _work_run_status_is_active(status: str) -> bool:
    return str(status or "").strip().lower() in WORK_RUN_ACTIVE_STATUSES


def _runtime_scene_work_run_public_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "runKind": str(item.get("runKind") or ""),
        "runId": str(item.get("runId") or ""),
        "snapshotCount": int(item.get("snapshotCount") or 0),
        "latestAt": str(item.get("latestAt") or ""),
        "latestStatus": str(item.get("latestStatus") or ""),
        "latestPhase": str(item.get("latestPhase") or ""),
        "activeRunId": str(item.get("activeRunId") or ""),
        "runtimeStatus": str(item.get("runtimeStatus") or ""),
        "snapshotPath": str(item.get("snapshotPath") or ""),
        "statusCounts": item.get("statusCounts") if isinstance(item.get("statusCounts"), dict) else {},
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
    startup_context = _runtime_scene_startup_failure_context(events)
    wrapped_failure_context = _runtime_scene_wrapped_failure_context(events)
    browser_lifecycle_context = _runtime_scene_browser_lifecycle_context(events)
    resource_lease_context = _runtime_scene_resource_lease_conflict_context(events)
    event_repeat_counts = _runtime_scene_event_repeat_counts(events)
    signals: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        severity = _runtime_scene_event_severity(event)
        if severity not in {"error", "warning"}:
            continue
        problem = _runtime_scene_signal_kind(
            event,
            startup_context=startup_context,
            wrapped_failure_context=wrapped_failure_context,
            browser_lifecycle_context=browser_lifecycle_context,
            resource_lease_context=resource_lease_context,
            event_repeat_counts=event_repeat_counts,
        )
        diagnosis_event = _runtime_scene_diagnosis_event(event, startup_context=startup_context)
        signals.append(
            {
                "index": index,
                "severity": severity,
                "problem": problem,
                "event": {**diagnosis_event, "diagnosisSeverity": severity},
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


def _runtime_scene_event_repeat_counts(events: list[dict[str, Any]]) -> dict[tuple[str, ...], int]:
    counts: dict[tuple[str, ...], int] = {}
    for event in events:
        key = _runtime_scene_issue_cluster_key(event)
        counts[key] = counts.get(key, 0) + 1
    return counts


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
    diagnosis_label = _runtime_scene_diagnosis_field(event, "diagnosisLabel")
    if diagnosis_label:
        return diagnosis_label
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


def _runtime_scene_startup_failure_context(events: list[dict]) -> dict[str, Any]:
    root_event: dict[str, Any] | None = None
    startup_failed = False
    open_workbench_command_ids: set[str] = set()
    for event in events:
        event_code = str(event.get("eventCode") or "").strip()
        if event_code == "runtime.scene.startup.failed":
            startup_failed = True
            continue
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        if (
            str(event.get("component") or "").strip() == "runtime_manager"
            and event_code == "command.failed"
            and str(fields.get("type") or "").strip() == "open_workbench"
        ):
            command_id = str(fields.get("commandId") or "").strip()
            if command_id:
                open_workbench_command_ids.add(command_id)
        if root_event is None and _runtime_scene_is_specific_startup_root_cause(event):
            root_event = event
    return {
        "startupFailed": startup_failed,
        "specificRootEventCode": str((root_event or {}).get("eventCode") or ""),
        "hasSpecificRootCause": root_event is not None,
        "openWorkbenchCommandIds": open_workbench_command_ids,
    }


def _runtime_scene_is_specific_startup_root_cause(event: dict[str, Any]) -> bool:
    event_code = str(event.get("eventCode") or "").strip()
    if event_code in {
        "frontend.build.failed",
        "frontend.dependencies.install.failed",
        "backend.dependencies.install.failed",
        "backend.start.failed",
        "backend.health.failed",
        "browser.window.launch.failed",
    }:
        return True
    component = str(event.get("component") or "").strip()
    phase = str(event.get("phase") or "").strip()
    if component in {"frontend", "backend", "browser"} and phase in {"build", "dependencies", "startup", "health", "window"}:
        return event_code.endswith(".failed")
    return False


def _runtime_scene_is_startup_failure_wrapper(
    event: dict[str, Any],
    *,
    startup_context: dict[str, Any] | None = None,
) -> bool:
    context = startup_context if isinstance(startup_context, dict) else {}
    event_code = str(event.get("eventCode") or "").strip()
    if event_code == "runtime.scene.startup.failed":
        return bool(context.get("hasSpecificRootCause"))
    if not context.get("startupFailed"):
        return False
    if str(event.get("component") or "").strip() != "runtime_manager":
        return False
    if event_code not in {"command.failed", "command_queue.command_result_written"}:
        return False
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    command_type = str(fields.get("type") or "").strip()
    if command_type == "open_workbench":
        return True
    command_id = str(fields.get("commandId") or "").strip()
    open_workbench_command_ids = context.get("openWorkbenchCommandIds")
    if command_id and isinstance(open_workbench_command_ids, set) and command_id in open_workbench_command_ids:
        return True
    message = _runtime_scene_failure_text(event).lower()
    specific_root = str(context.get("specificRootEventCode") or "").strip().lower()
    if specific_root and specific_root in message:
        return True
    return "launcher exit code" in message or "runtime scene startup" in message


def _runtime_scene_wrapped_failure_context(events: list[dict]) -> dict[str, Any]:
    image2_failed = False
    for event in events:
        if str(event.get("eventCode") or "").strip() == "image2.generate.failed":
            image2_failed = True
            break
    return {"image2Failed": image2_failed}


def _runtime_scene_is_conversation_failure_wrapper(
    event: dict[str, Any],
    *,
    wrapped_failure_context: dict[str, Any] | None = None,
) -> bool:
    context = wrapped_failure_context if isinstance(wrapped_failure_context, dict) else {}
    if str(event.get("component") or "").strip() != "conversation":
        return False
    if str(event.get("eventCode") or "").strip() != "conversation.assistant_artifact":
        return False
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    if str(fields.get("status") or event.get("outcome") or "").strip().lower() != "failed":
        return False
    diagnostic_text = " ".join(
        str(value or "")
        for value in (
            event.get("message"),
            fields.get("contentPreview"),
        )
    ).lower()
    return bool(context.get("image2Failed")) and "image2" in diagnostic_text


BROWSER_UNLOAD_NETWORK_FAILURE_WINDOW_SECONDS = 2.5
BROWSER_STALE_CHUNK_RELOAD_MATCH_WINDOW_SECONDS = 2.5
BROWSER_STALE_CHUNK_RECOVERY_WINDOW_SECONDS = 12.0
BROWSER_SESSION_STREAM_RECOVERY_WINDOW_SECONDS = 12.0
RESOURCE_LEASE_CONFLICT_MATCH_WINDOW_SECONDS = 5.0
RESOURCE_LEASE_TOKENS = {
    "readonly_chat",
    "worktree_write",
    "memory_write",
    "policy_write",
    "evaluation",
    "evolution_transaction",
}


def _runtime_scene_browser_lifecycle_context(events: list[dict]) -> dict[str, Any]:
    pagehide_by_instance: dict[str, list[float]] = {}
    for event in events:
        if str(event.get("eventCode") or "").strip() != "browser.page.hide":
            continue
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        page_instance_id = str(fields.get("pageInstanceId") or "").strip()
        if not page_instance_id:
            continue
        timestamp = _runtime_scene_event_epoch_seconds(event)
        if timestamp is None:
            continue
        pagehide_by_instance.setdefault(page_instance_id, []).append(timestamp)
    return {"pagehideByInstance": pagehide_by_instance}


def _runtime_scene_is_browser_unload_network_cancellation(
    event: dict[str, Any],
    *,
    browser_lifecycle_context: dict[str, Any] | None = None,
) -> bool:
    event_code = str(event.get("eventCode") or "").strip()
    if event_code != "browser.api.network_error":
        return False
    if str(event.get("component") or "").strip() != "browser_page":
        return False
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    if str(fields.get("failureKind") or "").strip().lower() != "network":
        return False
    method = str(fields.get("method") or "").strip().upper()
    if method != "GET":
        return False
    page_instance_id = str(fields.get("pageInstanceId") or "").strip()
    if not page_instance_id:
        return False
    event_timestamp = _runtime_scene_event_epoch_seconds(event)
    if event_timestamp is None:
        return False
    context = browser_lifecycle_context if isinstance(browser_lifecycle_context, dict) else {}
    pagehide_by_instance = context.get("pagehideByInstance") if isinstance(context.get("pagehideByInstance"), dict) else {}
    pagehide_timestamps = pagehide_by_instance.get(page_instance_id)
    if not isinstance(pagehide_timestamps, list):
        return False
    for pagehide_timestamp in pagehide_timestamps:
        if not isinstance(pagehide_timestamp, (int, float)):
            continue
        if abs(event_timestamp - float(pagehide_timestamp)) <= BROWSER_UNLOAD_NETWORK_FAILURE_WINDOW_SECONDS:
            return True
    return False


def _runtime_scene_resource_lease_conflict_context(events: list[dict]) -> dict[str, Any]:
    conflicts: list[dict[str, Any]] = []
    for event in events:
        if not _runtime_scene_event_has_resource_lease_conflict(event):
            continue
        timestamp = _runtime_scene_event_epoch_seconds(event)
        conflicts.append(
            {
                "timestamp": timestamp,
                "endpoints": _runtime_scene_event_endpoint_candidates(event),
                "sessionId": _runtime_scene_event_session_id(event),
            }
        )
    return {"conflicts": conflicts}


def _runtime_scene_is_expected_resource_lease_conflict(
    event: dict[str, Any],
    *,
    resource_lease_context: dict[str, Any] | None = None,
) -> bool:
    if _runtime_scene_event_has_resource_lease_conflict(event):
        return True

    if str(event.get("component") or "").strip().lower() != "backend":
        return False
    if str(event.get("eventCode") or "").strip() != "backend.api.request":
        return False
    if _runtime_scene_event_status_code(event) != 409:
        return False

    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    method = str(fields.get("method") or "").strip().upper()
    if method and method != "POST":
        return False

    context = resource_lease_context if isinstance(resource_lease_context, dict) else {}
    conflicts = context.get("conflicts") if isinstance(context.get("conflicts"), list) else []
    if not conflicts:
        return False

    event_timestamp = _runtime_scene_event_epoch_seconds(event)
    event_endpoints = set(_runtime_scene_event_endpoint_candidates(event))
    event_session_id = _runtime_scene_event_session_id(event)
    for conflict in conflicts:
        if not isinstance(conflict, dict):
            continue
        conflict_timestamp = conflict.get("timestamp")
        if (
            event_timestamp is not None
            and isinstance(conflict_timestamp, (int, float))
            and abs(event_timestamp - float(conflict_timestamp)) > RESOURCE_LEASE_CONFLICT_MATCH_WINDOW_SECONDS
        ):
            continue
        conflict_endpoints = {
            str(item or "").strip()
            for item in list(conflict.get("endpoints") or [])
            if str(item or "").strip()
        }
        if event_endpoints and conflict_endpoints and event_endpoints.intersection(conflict_endpoints):
            return True
        conflict_session_id = str(conflict.get("sessionId") or "").strip()
        if event_session_id and conflict_session_id and event_session_id == conflict_session_id:
            return True
        if conflict_session_id and any(conflict_session_id in endpoint for endpoint in event_endpoints):
            return True
    return False


def _runtime_scene_event_has_resource_lease_conflict(event: dict[str, Any]) -> bool:
    text = _runtime_scene_resource_lease_text(event)
    if not text:
        return False
    lowered = text.lower()
    if "resource lease conflict on" in lowered:
        return True
    if "资源正在被另一条运行占用" not in text:
        return False
    return any(token in lowered for token in RESOURCE_LEASE_TOKENS)


def _runtime_scene_resource_lease_text(event: dict[str, Any]) -> str:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    return " ".join(
        str(value or "")
        for value in (
            event.get("message"),
            fields.get("message"),
            fields.get("reason"),
            fields.get("detail"),
            fields.get("error"),
            fields.get("errorMessage"),
            fields.get("exceptionMessage"),
            fields.get("failureMessage"),
        )
    ).strip()


def _runtime_scene_event_endpoint_candidates(event: dict[str, Any]) -> list[str]:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    endpoints: list[str] = []
    seen: set[str] = set()
    for key in ("endpoint", "path", "pathTemplate"):
        endpoint = _normalize_endpoint_path(fields.get(key))
        if not endpoint or endpoint in seen:
            continue
        seen.add(endpoint)
        endpoints.append(endpoint)
    return endpoints


def _runtime_scene_event_session_id(event: dict[str, Any]) -> str:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    explicit = str(fields.get("sessionId") or "").strip()
    if explicit:
        return explicit
    for endpoint in _runtime_scene_event_endpoint_candidates(event):
        parts = endpoint.strip("/").split("/")
        for index, part in enumerate(parts[:-1]):
            if part == "sessions" and parts[index + 1]:
                return parts[index + 1]
    return ""


def _runtime_scene_event_epoch_seconds(event: dict[str, Any]) -> float | None:
    timestamp = str(event.get("ts") or event.get("timestamp") or "").strip()
    if not timestamp:
        return None
    try:
        normalized = timestamp.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return None


def _runtime_scene_issue_cluster_hint(cluster: dict[str, Any] | None) -> str:
    if not isinstance(cluster, dict):
        return ""
    representative = cluster.get("representativeSignal")
    if isinstance(representative, dict):
        return _runtime_scene_diagnosis_field(representative, "diagnosisHint")
    return ""


def _runtime_scene_signal_message_signature(message: str) -> str:
    text = " ".join(str(message or "").split())
    if not text:
        return ""
    first_line = text.split(" | ", 1)[0].splitlines()[0]
    return _truncate_text(first_line, 160)


def _runtime_scene_signal_kind(
    event: dict[str, Any],
    *,
    startup_context: dict[str, Any] | None = None,
    wrapped_failure_context: dict[str, Any] | None = None,
    browser_lifecycle_context: dict[str, Any] | None = None,
    resource_lease_context: dict[str, Any] | None = None,
    event_repeat_counts: dict[tuple[str, ...], int] | None = None,
) -> str:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    if str(event.get("eventCode") or "") == "conversation.next_state_signal.recorded":
        kind = str(fields.get("kind") or event.get("outcome") or "").strip().lower()
        if kind in NON_PROBLEM_NEXT_STATE_KINDS:
            return "control"
    if _runtime_scene_is_startup_failure_wrapper(event, startup_context=startup_context):
        return "control"
    if _runtime_scene_is_conversation_failure_wrapper(event, wrapped_failure_context=wrapped_failure_context):
        return "control"
    if _runtime_scene_is_browser_unload_network_cancellation(event, browser_lifecycle_context=browser_lifecycle_context):
        return "control"
    if _runtime_scene_is_expected_resource_lease_conflict(event, resource_lease_context=resource_lease_context):
        return "policy"
    if _runtime_scene_is_transient_agent_directory_slow_event(event, event_repeat_counts=event_repeat_counts):
        return "policy"
    if _runtime_scene_is_expected_runtime_manager_block(event):
        return "policy"
    if _runtime_scene_is_expected_work_run_manager_block(event):
        return "policy"
    if str(event.get("component") or "") == "tool_registry":
        if str(event.get("outcome") or "").strip().lower() == "blocked":
            return "policy"
        if str(fields.get("testPolicy") or "").strip().lower() == "blocked":
            return "policy"
    if str(event.get("eventCode") or "").endswith(".blocked"):
        if str(fields.get("source") or "").strip().lower() == "built_in":
            return "policy"
    return "problem"


def _runtime_scene_is_transient_agent_directory_slow_event(
    event: dict[str, Any],
    *,
    event_repeat_counts: dict[tuple[str, ...], int] | None = None,
) -> bool:
    if str(event.get("component") or "").strip() != "agent_directory":
        return False
    if str(event.get("phase") or "").strip() != "list_agents":
        return False
    if str(event.get("eventCode") or "").strip() != "agent_directory.list_agents.slow":
        return False
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    timings = fields.get("timingsMs") if isinstance(fields.get("timingsMs"), dict) else {}
    total_ms = _coerce_float(timings.get("total"), default=0.0)
    if total_ms <= 0 or total_ms >= AGENT_DIRECTORY_TRANSIENT_SLOW_TOTAL_MS:
        return False
    repeat_counts = event_repeat_counts if isinstance(event_repeat_counts, dict) else {}
    repeat_count = int(repeat_counts.get(_runtime_scene_issue_cluster_key(event)) or 1)
    return repeat_count <= AGENT_DIRECTORY_TRANSIENT_SLOW_REPEAT_LIMIT


def _runtime_scene_diagnosis_event(
    event: dict[str, Any],
    *,
    startup_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model_discovery = _runtime_scene_config_model_discovery_diagnosis(event)
    if model_discovery:
        fields = dict(event.get("fields") if isinstance(event.get("fields"), dict) else {})
        source_event_code = str(event.get("eventCode") or "").strip()
        fields.update(
            {
                "diagnosisEventCode": model_discovery["eventCode"],
                "diagnosisLabel": model_discovery["label"],
                "diagnosisReason": model_discovery["reason"],
                "diagnosisHint": model_discovery["hint"],
                "diagnosisEndpoint": CONFIG_MODEL_DISCOVERY_ENDPOINT,
            }
        )
        if source_event_code and source_event_code != model_discovery["eventCode"]:
            fields["sourceEventCode"] = source_event_code

        return {
            **event,
            "eventCode": model_discovery["eventCode"],
            "fields": fields,
        }

    startup_failure = _runtime_scene_startup_failure_diagnosis(event, startup_context=startup_context)
    if not startup_failure:
        return event

    fields = dict(event.get("fields") if isinstance(event.get("fields"), dict) else {})
    source_event_code = str(event.get("eventCode") or "").strip()
    fields.update(
        {
            "diagnosisEventCode": startup_failure["eventCode"],
            "diagnosisLabel": startup_failure["label"],
            "diagnosisReason": startup_failure["reason"],
            "diagnosisHint": startup_failure["hint"],
        }
    )
    if source_event_code and source_event_code != startup_failure["eventCode"]:
        fields["sourceEventCode"] = source_event_code
    return {
        **event,
        "eventCode": startup_failure["eventCode"],
        "fields": fields,
    }


def _runtime_scene_config_model_discovery_diagnosis(event: dict[str, Any]) -> dict[str, str] | None:
    event_code = str(event.get("eventCode") or "").strip()
    endpoint = _runtime_scene_event_endpoint(event)
    if endpoint != CONFIG_MODEL_DISCOVERY_ENDPOINT and not event_code.startswith("config.model_discovery."):
        return None

    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    failure_kind = str(fields.get("failureKind") or "").strip().lower()
    diagnostic_text = " ".join(
        str(value or "")
        for value in (
            event.get("message"),
            fields.get("failureMessage"),
            fields.get("exceptionMessage"),
            fields.get("error"),
        )
    )
    diagnostic_lower = diagnostic_text.lower()
    is_network = failure_kind == "network" or event_code.endswith(".network_error")
    if is_network:
        return {
            "eventCode": "config.model_discovery.network_error",
            "label": "配置模型发现失败：网络不可达",
            "reason": "network_error",
            "hint": "先确认模型发现接口、代理和本地网络是否可达。",
        }

    if "openai_api_key" in diagnostic_lower and (
        "未找到" in diagnostic_text
        or "missing" in diagnostic_lower
        or "not found" in diagnostic_lower
        or "not set" in diagnostic_lower
    ):
        return {
            "eventCode": "config.model_discovery.failed",
            "label": "配置模型发现失败：缺少 OPENAI_API_KEY",
            "reason": "missing_openai_api_key",
            "hint": "先配置 OPENAI_API_KEY，或把模型库条目切到已有可用密钥来源。",
        }

    if "认证失败" in diagnostic_text or "unauthorized" in diagnostic_lower or "http 401" in diagnostic_lower:
        return {
            "eventCode": "config.model_discovery.failed",
            "label": "配置模型发现失败：模型服务认证失败",
            "reason": "auth_failed",
            "hint": "先检查模型服务 API Key、base URL 和 provider 密钥来源。",
        }

    status_code = _runtime_scene_event_status_code(event)
    if status_code:
        label = f"配置模型发现失败：请求返回 {status_code}"
        reason = f"http_{status_code}"
    else:
        label = "配置模型发现失败"
        reason = "request_failed"
    return {
        "eventCode": "config.model_discovery.failed",
        "label": label,
        "reason": reason,
        "hint": "先检查模型发现接口返回体、provider 配置和密钥来源。",
    }


def _runtime_scene_startup_failure_diagnosis(
    event: dict[str, Any],
    *,
    startup_context: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    context = startup_context if isinstance(startup_context, dict) else {}
    event_code = str(event.get("eventCode") or "").strip()
    if event_code != "runtime.scene.startup.failed":
        return None
    if context.get("hasSpecificRootCause"):
        return None

    diagnostic_text = _runtime_scene_failure_text(event)
    diagnostic_lower = diagnostic_text.lower()
    missing_command = _runtime_scene_missing_powershell_command(diagnostic_text)
    if missing_command:
        return {
            "eventCode": "startup.launcher.command_missing",
            "label": f"启动失败：PowerShell 函数缺失 {missing_command}",
            "reason": "powershell_command_missing",
            "hint": f"先检查 scripts/vibelution_launcher.ps1 中 {missing_command} 的定义、加载顺序和最近脚本改动。",
        }

    if "npm run build failed" in diagnostic_lower or "frontend.build.failed" in diagnostic_lower:
        return {
            "eventCode": "startup.frontend_build.failed",
            "label": "启动失败：前端构建失败",
            "reason": "frontend_build_failed",
            "hint": "先打开 raw/frontend.build.log，定位第一条 TypeScript/Vite 构建错误。",
        }

    if "backend" in diagnostic_lower and ("failed" in diagnostic_lower or "health" in diagnostic_lower):
        return {
            "eventCode": "startup.backend.failed",
            "label": "启动失败：后端启动或健康检查失败",
            "reason": "backend_startup_failed",
            "hint": "先打开 raw/backend.stderr.log、raw/backend.stdout.log 和 events/backend.jsonl。",
        }

    return {
        "eventCode": "startup.launcher.failed",
        "label": "启动失败：启动器执行失败",
        "reason": "launcher_failed",
        "hint": "先打开 raw/launcher-control.log，并对照 timeline 中 runtime.scene.startup.failed 的 reason。",
    }


def _runtime_scene_failure_text(event: dict[str, Any]) -> str:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    return " ".join(
        str(value or "")
        for value in (
            event.get("message"),
            fields.get("reason"),
            fields.get("message"),
            fields.get("error"),
            fields.get("exceptionMessage"),
            fields.get("failureMessage"),
        )
    ).strip()


def _runtime_scene_missing_powershell_command(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    markers = ("The term '", "term \"")
    for marker in markers:
        if marker not in normalized:
            continue
        after = normalized.split(marker, 1)[1]
        quote = "'" if marker.endswith("'") else '"'
        command = after.split(quote, 1)[0].strip()
        if command:
            return command
    first_line = normalized.splitlines()[0].strip()
    if ":" in first_line and "not recognized" in first_line.lower():
        command = first_line.split(":", 1)[0].strip()
        if command:
            return command
    return ""


def _runtime_scene_diagnosis_field(event: dict[str, Any], key: str) -> str:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    value = fields.get(key)
    return _truncate_text(str(value or "").strip(), 320)


def _runtime_scene_is_expected_runtime_manager_block(event: dict[str, Any]) -> bool:
    if str(event.get("component") or "").strip().lower() != "runtime_manager":
        return False
    event_code = str(event.get("eventCode") or "").strip()
    if event_code not in {"command.failed", "command_queue.command_result_written"}:
        return False
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    error_type = str(fields.get("errorType") or "").strip().lower()
    if error_type in EXPECTED_RUNTIME_MANAGER_BLOCK_ERROR_TYPES:
        return True
    message = " ".join(
        [
            str(event.get("message") or ""),
            str(fields.get("message") or ""),
            str(fields.get("error") or ""),
        ]
    ).strip().lower()
    if not message:
        return False
    chinese_busy = "已经有一轮" in message and ("运行" in message or "暂停" in message)
    english_busy = "already" in message and ("running" in message or "paused" in message)
    return chinese_busy or english_busy


def _runtime_scene_is_expected_work_run_manager_block(event: dict[str, Any]) -> bool:
    if str(event.get("phase") or "").strip().lower() != "runtime_manager":
        return False
    event_code = str(event.get("eventCode") or "").strip()
    if not event_code.endswith(".manager.start_self_evolution_run.failed"):
        return False
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    error_type = str(fields.get("errorType") or "").strip().lower()
    if error_type in EXPECTED_RUNTIME_MANAGER_BLOCK_ERROR_TYPES:
        return True
    message = " ".join(
        [
            str(event.get("message") or ""),
            str(fields.get("message") or ""),
            str(fields.get("error") or ""),
        ]
    ).strip().lower()
    if not message:
        return False
    chinese_busy = "已经有一轮" in message and ("运行" in message or "暂停" in message)
    english_busy = "already" in message and ("running" in message or "paused" in message)
    return chinese_busy or english_busy


def _runtime_scene_signal_has_later_resolution(events: list[dict], signal: dict[str, Any]) -> bool:
    event = signal.get("event")
    index = int(signal.get("index") or 0)
    if not isinstance(event, dict):
        return False
    if _runtime_scene_browser_stale_chunk_signal_has_later_recovery(events, index, event):
        return True
    if _runtime_scene_browser_session_stream_signal_has_later_recovery(events, index, event):
        return True
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
    if _runtime_scene_agent_model_reference_resolution_matches(candidate, source):
        return True
    if identity:
        candidate_identity = _runtime_scene_event_identity(candidate)
        return any(candidate_identity.get(key) == value for key, value in identity.items())
    return str(candidate.get("phase") or "") == str(source.get("phase") or "")


def _runtime_scene_agent_model_reference_resolution_matches(
    candidate: dict[str, Any],
    source: dict[str, Any],
) -> bool:
    if str(source.get("component") or "") != "agent_config":
        return False
    if str(source.get("phase") or "") != "model_binding":
        return False
    source_code = str(source.get("eventCode") or "").strip()
    if source_code not in {
        "agent_config.unresolved_model_reference",
        "agent_config.unresolved_chat_room_participant_model_reference",
        "agent_config.model_references.unresolved",
    }:
        return False
    return str(candidate.get("eventCode") or "").strip() == "agent_config.model_references.resolved"


def _runtime_scene_browser_stale_chunk_signal_has_later_recovery(
    events: list[dict],
    source_index: int,
    source: dict[str, Any],
) -> bool:
    if not _runtime_scene_is_browser_stale_chunk_signal(source):
        return False
    if not _runtime_scene_has_related_chunk_reload_request(events, source_index, source):
        return False

    source_fields = source.get("fields") if isinstance(source.get("fields"), dict) else {}
    source_page_instance_id = str(source_fields.get("pageInstanceId") or "").strip()
    source_path = _runtime_scene_browser_event_path(source)
    source_timestamp = _runtime_scene_event_epoch_seconds(source)
    saw_old_page_hide = False

    for later in events[source_index + 1 :]:
        if str(later.get("component") or "") != BROWSER_TELEMETRY_COMPONENT:
            continue
        later_timestamp = _runtime_scene_event_epoch_seconds(later)
        if (
            source_timestamp is not None
            and later_timestamp is not None
            and later_timestamp - source_timestamp > BROWSER_STALE_CHUNK_RECOVERY_WINDOW_SECONDS
        ):
            break

        later_fields = later.get("fields") if isinstance(later.get("fields"), dict) else {}
        later_page_instance_id = str(later_fields.get("pageInstanceId") or "").strip()
        later_code = str(later.get("eventCode") or "").strip()
        if source_page_instance_id and later_page_instance_id == source_page_instance_id and later_code == "browser.page.hide":
            saw_old_page_hide = True
            continue
        if not saw_old_page_hide:
            continue
        if not source_page_instance_id or not later_page_instance_id or later_page_instance_id == source_page_instance_id:
            continue
        if _runtime_scene_browser_event_is_usable_page_after_reload(later, source_path):
            return True
    return False


def _runtime_scene_is_browser_stale_chunk_signal(event: dict[str, Any]) -> bool:
    if str(event.get("component") or "") != BROWSER_TELEMETRY_COMPONENT:
        return False
    event_code = str(event.get("eventCode") or "").strip()
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    reason = str(fields.get("reason") or "").strip()
    if event_code == "browser.route_chunk_recovery.reload_requested":
        return reason in {"built_asset_resource_error", "dynamic_import_fetch_error"}
    if event_code == "browser.resource.error":
        return _runtime_scene_browser_event_mentions_built_asset(event)
    if event_code in {"browser.console.error", "browser.promise.rejected", "browser.page.error"}:
        return _runtime_scene_browser_event_mentions_built_asset(event) or "dynamically imported module" in _runtime_scene_browser_event_failure_text(event).lower()
    return False


def _runtime_scene_has_related_chunk_reload_request(
    events: list[dict],
    source_index: int,
    source: dict[str, Any],
) -> bool:
    if str(source.get("eventCode") or "").strip() == "browser.route_chunk_recovery.reload_requested":
        return True

    source_fields = source.get("fields") if isinstance(source.get("fields"), dict) else {}
    source_page_instance_id = str(source_fields.get("pageInstanceId") or "").strip()
    source_path = _runtime_scene_browser_event_path(source)
    source_timestamp = _runtime_scene_event_epoch_seconds(source)
    for candidate in events[max(0, source_index - 12) : min(len(events), source_index + 13)]:
        if str(candidate.get("component") or "") != BROWSER_TELEMETRY_COMPONENT:
            continue
        if str(candidate.get("eventCode") or "").strip() != "browser.route_chunk_recovery.reload_requested":
            continue
        candidate_fields = candidate.get("fields") if isinstance(candidate.get("fields"), dict) else {}
        reason = str(candidate_fields.get("reason") or "").strip()
        if reason not in {"built_asset_resource_error", "dynamic_import_fetch_error"}:
            continue
        candidate_timestamp = _runtime_scene_event_epoch_seconds(candidate)
        if (
            source_timestamp is not None
            and candidate_timestamp is not None
            and abs(candidate_timestamp - source_timestamp) > BROWSER_STALE_CHUNK_RELOAD_MATCH_WINDOW_SECONDS
        ):
            continue
        candidate_page_instance_id = str(candidate_fields.get("pageInstanceId") or "").strip()
        if source_page_instance_id and candidate_page_instance_id and candidate_page_instance_id != source_page_instance_id:
            continue
        candidate_path = _runtime_scene_browser_event_path(candidate)
        if source_path and candidate_path and source_path != candidate_path:
            continue
        return True
    return False


def _runtime_scene_browser_event_is_usable_page_after_reload(event: dict[str, Any], source_path: str) -> bool:
    event_code = str(event.get("eventCode") or "").strip()
    if event_code not in {"browser.route.changed", "browser.page.snapshot", "browser.memory.sampled"}:
        return False
    event_path = _runtime_scene_browser_event_path(event)
    if source_path and event_path and source_path != event_path:
        return False
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    if event_code == "browser.memory.sampled":
        return str(fields.get("reason") or "").strip() == "route_settled"
    if event_code == "browser.page.snapshot":
        ready_state = str(fields.get("readyState") or "").strip().lower()
        return ready_state in {"", "complete", "interactive"}
    return True


def _runtime_scene_browser_session_stream_signal_has_later_recovery(
    events: list[dict],
    source_index: int,
    source: dict[str, Any],
) -> bool:
    if str(source.get("component") or "") != BROWSER_TELEMETRY_COMPONENT:
        return False
    if str(source.get("eventCode") or "").strip() != "browser.session_stream.error":
        return False
    session_id = _runtime_scene_event_session_id(source)
    if not session_id:
        return False
    source_timestamp = _runtime_scene_event_epoch_seconds(source)
    for later in events[source_index + 1 :]:
        if str(later.get("component") or "") != BROWSER_TELEMETRY_COMPONENT:
            continue
        later_timestamp = _runtime_scene_event_epoch_seconds(later)
        if (
            source_timestamp is not None
            and later_timestamp is not None
            and later_timestamp - source_timestamp > BROWSER_SESSION_STREAM_RECOVERY_WINDOW_SECONDS
        ):
            break
        if _runtime_scene_event_session_id(later) != session_id:
            continue
        if str(later.get("eventCode") or "").strip() in {"browser.session_stream.opened", "browser.session_stream.snapshot_applied"}:
            return True
    return False


def _runtime_scene_browser_event_mentions_built_asset(event: dict[str, Any]) -> bool:
    text = _runtime_scene_browser_event_failure_text(event).lower()
    return "/assets/" in text and (".js" in text or ".css" in text)


def _runtime_scene_browser_event_failure_text(event: dict[str, Any]) -> str:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    return " ".join(
        str(value or "")
        for value in (
            event.get("message"),
            fields.get("argsPreview"),
            fields.get("resourceUrl"),
            fields.get("errorMessage"),
            fields.get("failureMessage"),
        )
    ).strip()


def _runtime_scene_browser_event_path(event: dict[str, Any]) -> str:
    fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
    for key in ("pathname", "routeTarget", "href"):
        path = _normalize_browser_route_path(fields.get(key))
        if path:
            return path
    return ""


def _normalize_browser_route_path(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        scheme_index = text.find("://")
        path_index = text.find("/", scheme_index + 3)
        text = text[path_index:] if path_index >= 0 else "/"
    text = text.split("?", 1)[0].split("#", 1)[0].strip()
    if not text.startswith("/"):
        return ""
    return text or "/"


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
    if any(str(signal.get("severity") or "") == "error" for signal in active_signals):
        return "error"
    if any(str(signal.get("severity") or "") == "warning" for signal in active_signals):
        return "warning"
    if policy_signals:
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
        hint = _runtime_scene_issue_cluster_hint(issue_state.get("firstActiveCluster"))
        hint_sentence = f" 诊断提示：{hint}" if hint else ""
        return (
            f"先读 logs/runtime_scenes/{package_anchor}/{first_path}，确认 issueState.activeClusterCount；"
            f"再定位主问题簇 {cluster}，优先打开 summary/package_index 里的 evidence_paths 对应文件，"
            f"并沿同一 component/runId/pageInstanceId 向后找恢复或重复崩溃。{hint_sentence}"
        )
    if severity == "warning" and active_cluster_count and first_signal:
        cluster = _runtime_scene_issue_cluster_display(issue_state.get("firstActiveCluster"))
        hint = _runtime_scene_issue_cluster_hint(issue_state.get("firstActiveCluster"))
        hint_sentence = f" 诊断提示：{hint}" if hint else ""
        return (
            f"先读 logs/runtime_scenes/{package_anchor}/{first_path}，确认 issueState.activeClusterCount；"
            f"再定位主问题簇 {cluster}，判断它是退化、重试还是用户控制信号，必要时打开 evidence_paths 对应文件。{hint_sentence}"
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
        hint = _runtime_scene_issue_cluster_hint(issue_state.get("firstActiveCluster"))
        hint_sentence = f" 诊断提示：{hint}" if hint else ""
        return (
            f"先读 logs/runtime_scenes/{package_anchor}/{first_path}，确认 issueState.activeClusterCount；"
            f"再追踪主问题簇 {cluster}，把它和首个信号、证据路径、timeline 顺序对齐。{hint_sentence}"
        )
    return (
        f"先读 logs/runtime_scenes/{package_anchor}/{first_path}，再按推荐阅读顺序对照 timeline、lifecycle 和子日志确认周期完整性。"
    )


def _runtime_scene_diagnosis_signal_payload(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not event:
        return None
    payload = {
        "severity": str(event.get("diagnosisSeverity") or _runtime_scene_event_severity(event)),
        "timestamp": str(event.get("timestamp") or ""),
        "component": str(event.get("component") or ""),
        "phase": str(event.get("phase") or ""),
        "eventCode": str(event.get("eventCode") or ""),
        "message": _truncate_text(str(event.get("message") or ""), 320),
        "rawRefs": _runtime_scene_signal_raw_refs(event),
    }
    for source_key, payload_key in (
        ("diagnosisLabel", "diagnosisLabel"),
        ("diagnosisReason", "diagnosisReason"),
        ("diagnosisHint", "diagnosisHint"),
        ("sourceEventCode", "sourceEventCode"),
    ):
        value = _runtime_scene_diagnosis_field(event, source_key)
        if value:
            payload[payload_key] = value
    return payload


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
