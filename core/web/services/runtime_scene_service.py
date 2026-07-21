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
from .runtime_scene.diagnosis import (
    _append_key_entry,
    _append_unique_path,
    _count_issue_signals,
    _first_event_by_code,
    _fold_repeated_work_run_snapshots,
    _manifest_nested_string,
    _normalize_browser_route_path,
    _parse_startup_raw_json_line,
    _runtime_scene_agent_brief,
    _runtime_scene_agent_brief_issue,
    _runtime_scene_agent_model_reference_resolution_matches,
    _runtime_scene_agent_work_run_focus,
    _runtime_scene_browser_event_failure_text,
    _runtime_scene_browser_event_is_usable_page_after_reload,
    _runtime_scene_browser_event_mentions_built_asset,
    _runtime_scene_browser_event_path,
    _runtime_scene_browser_lifecycle_context,
    _runtime_scene_browser_session_stream_signal_has_later_recovery,
    _runtime_scene_browser_stale_chunk_signal_has_later_recovery,
    _runtime_scene_config_model_discovery_diagnosis,
    _runtime_scene_diagnosis_event,
    _runtime_scene_diagnosis_events,
    _runtime_scene_diagnosis_evidence_paths,
    _runtime_scene_diagnosis_field,
    _runtime_scene_diagnosis_next_step,
    _runtime_scene_diagnosis_signal_payload,
    _runtime_scene_diagnosis_tags,
    _runtime_scene_diagnosis_user_summary,
    _runtime_scene_event_dedupe_key,
    _runtime_scene_event_endpoint_candidates,
    _runtime_scene_event_epoch_seconds,
    _runtime_scene_event_has_resource_lease_conflict,
    _runtime_scene_event_identity,
    _runtime_scene_event_repeat_counts,
    _runtime_scene_event_session_id,
    _runtime_scene_failure_text,
    _runtime_scene_first_key_event,
    _runtime_scene_first_ranked_signal,
    _runtime_scene_first_signal,
    _runtime_scene_has_related_chunk_reload_request,
    _runtime_scene_is_browser_stale_chunk_signal,
    _runtime_scene_is_browser_unload_network_cancellation,
    _runtime_scene_is_conversation_failure_wrapper,
    _runtime_scene_is_expected_resource_lease_conflict,
    _runtime_scene_is_expected_runtime_manager_block,
    _runtime_scene_is_expected_work_run_manager_block,
    _runtime_scene_is_recovery_evidence_event,
    _runtime_scene_is_specific_startup_root_cause,
    _runtime_scene_is_startup_failure_wrapper,
    _runtime_scene_is_transient_agent_directory_slow_event,
    _runtime_scene_issue_cluster_display,
    _runtime_scene_issue_cluster_hint,
    _runtime_scene_issue_cluster_key,
    _runtime_scene_issue_cluster_label,
    _runtime_scene_issue_cluster_sort_key,
    _runtime_scene_issue_clusters,
    _runtime_scene_issue_state,
    _runtime_scene_issue_state_severity,
    _runtime_scene_issue_state_summary,
    _runtime_scene_key_entries,
    _runtime_scene_missing_powershell_command,
    _runtime_scene_package_diagnosis,
    _runtime_scene_package_diagnosis_for_scene,
    _runtime_scene_package_index_from_diagnosis,
    _runtime_scene_primary_cause_label,
    _runtime_scene_primary_cause_token,
    _runtime_scene_primary_issue_cluster,
    _runtime_scene_recommended_reading_order,
    _runtime_scene_recovery_evidence_events,
    _runtime_scene_resolution_event_matches,
    _runtime_scene_resource_lease_conflict_context,
    _runtime_scene_resource_lease_text,
    _runtime_scene_signal_has_later_resolution,
    _runtime_scene_signal_kind,
    _runtime_scene_signal_label,
    _runtime_scene_signal_message_signature,
    _runtime_scene_startup_failure_context,
    _runtime_scene_startup_failure_diagnosis,
    _runtime_scene_startup_trace,
    _runtime_scene_startup_trace_summary,
    _runtime_scene_work_run_public_summary,
    _runtime_scene_work_run_summary,
    _runtime_scene_wrapped_failure_context,
    _scene_child_exists,
    _scene_child_has_content,
    _startup_step_evidence_path,
    _startup_step_raw_event,
    _startup_step_timestamp,
    _work_run_snapshot_fold_key,
    _work_run_snapshot_summary_event,
    _work_run_status_is_active,
)
from .runtime_scene.package_index import (
    _runtime_scene_package_index_sidecar_is_stale,
    _sync_runtime_scene_package_index_if_stale,
    _update_runtime_scene_manifest_package_index_fields,
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
