"""Runtime scene write / record path helpers.

Claim scope: record_* entrypoints, delete scenes, jsonl/log append,
browser/backend manifests, and write-side package/summary materialize.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _service():
    from core.web.services import runtime_scene_service

    return runtime_scene_service


def _append_agent_tool_call_logs(scene_dir: Path, conversation_payload: dict[str, Any]) -> None:
    s = _service()
    tool_calls = conversation_payload.get("tool_calls")
    if not isinstance(tool_calls, list):
        return
    for index, item in enumerate(tool_calls):
        if not isinstance(item, dict):
            continue
        invocation_id = s._runtime_scene_safe_id(item.get("invocationId")) or str(
            conversation_payload.get("invocation_id") or ""
        )
        s._append_scene_jsonl(
            scene_dir,
            f"{s.AGENT_DIR}/tool_calls.jsonl",
            {
                "schema_version": 1,
                "runtime_scene_id": conversation_payload.get("runtime_scene_id") or "",
                "ts": conversation_payload.get("ts") or "",
                "session_id": conversation_payload.get("session_id") or "",
                "turn_id": conversation_payload.get("turn_id") or "",
                "client_submission_id": conversation_payload.get("client_submission_id") or "",
                "invocation_id": invocation_id,
                "event": conversation_payload.get("event") or "",
                "role": conversation_payload.get("role") or "",
                "index": index,
                "id": s._runtime_scene_safe_id(item.get("id")),
                "callId": s._runtime_scene_safe_id(item.get("callId")),
                "invocationId": invocation_id,
                "name": str(item.get("name") or "").strip(),
                "status": str(item.get("status") or "").strip(),
                "summary": s._truncate_text(str(item.get("summary") or ""), 800),
            },
        )


def _append_agent_turn_log(scene_dir: Path, conversation_payload: dict[str, Any]) -> None:
    s = _service()
    content = s._truncate_text(str(conversation_payload.get("content") or ""), 800)
    active_task = conversation_payload.get("active_task")
    s._append_scene_jsonl(
        scene_dir,
        f"{s.AGENT_DIR}/turns.jsonl",
        {
            "schema_version": 1,
            "runtime_scene_id": conversation_payload.get("runtime_scene_id") or "",
            "ts": conversation_payload.get("ts") or "",
            "session_id": conversation_payload.get("session_id") or "",
            "turn_id": conversation_payload.get("turn_id") or "",
            "client_submission_id": conversation_payload.get("client_submission_id") or "",
            "invocation_id": conversation_payload.get("invocation_id") or "",
            "event": conversation_payload.get("event") or "",
            "role": conversation_payload.get("role") or "",
            "status": conversation_payload.get("status") or "",
            "content_preview": content,
            "content_length": s._coerce_int(conversation_payload.get("content_length"), default=0),
            "content_redacted": bool(conversation_payload.get("content_redacted")),
            "active_task": active_task if isinstance(active_task, dict) else {},
        },
    )


def _append_scene_event(scene_dir: Path, component: str, payload: dict[str, Any]) -> None:
    s = _service()
    with s.pipeline_metrics.measure("append", priority="normal"):
        with s.RUNTIME_SCENE_EVENT_WRITE_LOCK:
            sequenced_payload = dict(payload)
            sequenced_payload["seq"] = s._next_scene_event_seq(scene_dir, component)
            events_dir = scene_dir / "events"
            events_dir.mkdir(parents=True, exist_ok=True)
            event_path = events_dir / f"{component}.jsonl"
            with event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(sequenced_payload, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
            s._remember_scene_event_seq(event_path, int(sequenced_payload.get("seq") or 0))
            if not s._should_promote_scene_event_to_timeline(sequenced_payload):
                return
        s._append_scene_jsonl(scene_dir, s.TIMELINE_PATH, sequenced_payload)
        if s._is_lifecycle_event(sequenced_payload):
            s._append_scene_jsonl(scene_dir, s.LIFECYCLE_PATH, sequenced_payload)


def _append_scene_jsonl(scene_dir: Path, relative_path: str, payload: dict[str, Any]) -> None:
    s = _service()
    target = s._resolve_scene_child(scene_dir, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")


def _append_scene_log_line(scene_dir: Path, relative_path: str, message: str) -> None:
    s = _service()
    target = s._resolve_scene_child(scene_dir, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


def _browser_manifest_for_role(manifest: dict[str, Any], browser_key: str) -> dict[str, Any]:
    s = _service()
    browser = manifest.get(browser_key)
    if isinstance(browser, dict):
        return dict(browser)
    legacy_browser = manifest.get("browser")
    if isinstance(legacy_browser, dict) and s._browser_manifest_key_for_existing_browser(legacy_browser) == browser_key:
        return dict(legacy_browser)
    return {}


def _browser_manifest_key_for_existing_browser(browser: dict[str, Any]) -> str:
    s = _service()
    role = str(browser.get("browser_role") or browser.get("window_purpose") or "").strip().lower()
    surface = str(browser.get("telemetry_surface") or "").strip().lower()
    profile_dir = str(browser.get("profile_dir") or browser.get("profileDir") or "").strip().lower()
    app_url = str(browser.get("app_url") or browser.get("current_href") or "").strip().lower()
    pathname = str(browser.get("current_pathname") or "").strip().lower()
    if role in {"launcher", "launcher_control_surface", "control_surface"}:
        return "launcherBrowser"
    if surface in {"managed_launcher", "launcher_control_surface"}:
        return "launcherBrowser"
    if "launcher-control-profile" in profile_dir:
        return "launcherBrowser"
    if pathname == "/launcher" or app_url.endswith("/launcher"):
        return "launcherBrowser"
    return "workbenchBrowser"


def _browser_manifest_key_for_telemetry(fields: dict[str, Any]) -> str:
    s = _service()
    role = str(fields.get("browserRole") or "").strip().lower()
    surface = str(fields.get("telemetrySurface") or "").strip().lower()
    pathname = str(fields.get("pathname") or "").strip().lower()
    href = str(fields.get("href") or "").strip().lower()
    if role in {"launcher", "launcher_control_surface", "control_surface"}:
        return "launcherBrowser"
    if surface in {"managed_launcher", "launcher_control_surface"}:
        return "launcherBrowser"
    if pathname == "/launcher" or href.endswith("/launcher"):
        return "launcherBrowser"
    return "workbenchBrowser"


def _camel_to_snake(value: str) -> str:
    s = _service()
    explicit = {
        "usedJSHeapMB": "used_js_heap_mb",
        "totalJSHeapMB": "total_js_heap_mb",
        "jsHeapLimitMB": "js_heap_limit_mb",
        "usedJSHeapBytes": "used_js_heap_bytes",
        "totalJSHeapBytes": "total_js_heap_bytes",
        "jsHeapLimitBytes": "js_heap_limit_bytes",
    }
    if value in explicit:
        return explicit[value]
    chars: list[str] = []
    for index, char in enumerate(str(value or "")):
        if char.isupper() and index > 0:
            chars.append("_")
        chars.append(char.lower())
    return "".join(chars).strip("_")


def _coerce_float(value: object, *, default: float = 0.0) -> float:
    s = _service()
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: object, *, default: int = 0) -> int:
    s = _service()
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _copy_jsonl_rows(rows: list[dict]) -> list[dict]:
    s = _service()
    return copy.deepcopy(rows)


def _count_runtime_scene_files(scene_dir: Path, relative_path: str) -> int:
    s = _service()
    target = scene_dir / relative_path
    try:
        if target.is_file():
            return 1
        if not target.is_dir():
            return 0
        return sum(1 for item in s._iter_runtime_scene_descendants(target) if s._is_readable_file(item))
    except OSError:
        return 0


def _display_name_status_label(manifest: dict) -> str:
    s = _service()
    status = s._runtime_scene_status(manifest)
    result = str(manifest.get("result") or "").strip().lower()
    stop_reason = str(manifest.get("stop_reason") or "").strip().lower()
    if status == "stopped" and (result or stop_reason):
        return s.DISPLAY_NAME_RESULT_LABELS.get(result) or s._humanize_runtime_token(stop_reason or result)
    return s.DISPLAY_NAME_STATUS_LABELS.get(status, s._humanize_runtime_token(status))


def _display_name_time_label(started_at: str, scene_dir: Path) -> str:
    s = _service()
    parsed = s._resolve_scene_started_at(started_at, scene_dir)
    if parsed is None:
        return ""
    local_value = parsed.astimezone()
    return local_value.strftime("%Y-%m-%d %H:%M")


def _display_name_trigger_label(trigger: str) -> str:
    s = _service()
    normalized = str(trigger or "").strip().lower()
    if not normalized:
        return "工作台运行"
    return s.DISPLAY_NAME_TRIGGER_LABELS.get(normalized, s._humanize_runtime_token(normalized))


def _event_payload_to_client_item(entry: dict[str, Any], scene_dir: Path, component: str) -> dict[str, Any]:
    s = _service()
    return {
        "runtimeSceneId": str(entry.get("runtime_scene_id") or s._scene_id(scene_dir, {})),
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


def _file_timestamp(path: Path) -> str:
    s = _service()
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return ""


def _get_jsonl_file_cache(signature: tuple[str, bool, int, int]) -> list[dict] | None:
    s = _service()
    with s._JSONL_FILE_CACHE_LOCK:
        rows = s._JSONL_FILE_CACHE.get(signature)
    return s._copy_jsonl_rows(rows) if rows is not None else None


def _humanize_runtime_token(value: str) -> str:
    s = _service()
    token = str(value or "").strip(" ._-")
    if not token:
        return ""
    return token.replace("_", " ").replace("-", " ")


def _is_current_runtime_scene_manifest(scene_dir: Path, manifest: dict[str, Any], launcher_state: dict[str, Any]) -> bool:
    s = _service()
    status = str(manifest.get("status") or "").strip().lower()
    if status and status not in {"running", "starting", "queued", "opening", "stopping", "closing"}:
        return False

    target_scene_id = str(launcher_state.get("runtimeSceneId") or "").strip()
    if target_scene_id and s._scene_id(scene_dir, manifest) != target_scene_id:
        return False

    if not s._runtime_scene_project_matches(manifest):
        return False
    return True


def _is_dev_browser_telemetry_surface(fields: dict[str, Any]) -> bool:
    s = _service()
    surface = str(fields.get("telemetrySurface") or "").strip().lower()
    if surface == "vite_dev":
        return True
    port = str(fields.get("port") or "").strip()
    if port in {"5173", "5174"}:
        return True
    href = str(fields.get("href") or fields.get("origin") or "").strip()
    return ":5173" in href or ":5174" in href


def _is_diagnostic_probe_404(
    *,
    method: str,
    path: str,
    path_template: str,
    status_code: int,
) -> bool:
    s = _service()
    if int(status_code or 0) != 404:
        return False
    normalized_method = str(method or "").strip().upper()
    if normalized_method not in {"GET", "HEAD"}:
        return False
    return s._normalize_endpoint_path(path_template) in s.DIAGNOSTIC_PROBE_404_PATHS or s._normalize_endpoint_path(path) in s.DIAGNOSTIC_PROBE_404_PATHS


def _is_known_benign_browser_event(payload: dict[str, Any]) -> bool:
    s = _service()
    event_code = str(payload.get("event_code") or "").strip()
    if event_code != "browser.page.error":
        return False
    message = str(payload.get("message") or "")
    fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    field_message = " ".join(
        str(fields.get(key) or "")
        for key in ("message", "error", "errorMessage", "stack")
    )
    text = f"{message} {field_message}".lower()
    return "resizeobserver loop completed with undelivered notifications" in text


def _is_lifecycle_event(payload: dict[str, Any]) -> bool:
    s = _service()
    if bool(payload.get("lifecycle")):
        return True
    phase = str(payload.get("phase") or "").strip().lower()
    event_code = str(payload.get("event_code") or "").strip()
    component = str(payload.get("component") or "").strip().lower()
    if event_code.startswith("runtime.scene."):
        return True
    if phase in s.LIFECYCLE_INDEX_PHASES:
        return True
    return component in {"launcher", "supervisor"} and phase in {"session", "shutdown"}


def _is_readable_file(path: Path) -> bool:
    s = _service()
    try:
        return path.is_file()
    except OSError:
        return False


def _is_safe_usage_counter_key(normalized_key: str) -> bool:
    s = _service()
    compact = str(normalized_key or "").replace("_", "")
    return compact in {
        "inputtokens",
        "outputtokens",
        "totaltokens",
        "cachedinputtokens",
        "uncachedinputtokens",
        "prompttokens",
        "completiontokens",
        "prompttokencount",
        "completiontokencount",
        "inputtokencount",
        "outputtokencount",
        "cachedtokens",
        "maxtokens",
        "beforetokens",
        "aftertokens",
        "savedtokens",
        "totaltokenusage",
        "turninputtokens",
        "turncachedinputtokens",
        "totalinputtokens",
        "totalcachedinputtokens",
        "lastinputtokens",
        "lastcachedinputtokens",
        "cacheinputtokens",
        "cachereadinputtokens",
        "cachecreationinputtokens",
        "promptcachehittokens",
    }


def _is_sensitive_telemetry_key(key: str) -> bool:
    s = _service()
    normalized = str(key or "").strip().lower().replace("-", "_")
    if s._is_safe_usage_counter_key(normalized):
        return False
    return any(keyword in normalized for keyword in s.SENSITIVE_FIELD_KEYWORDS)


def _is_structured_telemetry_key(key: str) -> bool:
    s = _service()
    normalized = str(key or "").strip().lower().replace("-", "_")
    compact = normalized.replace("_", "")
    return normalized in s.STRUCTURED_TELEMETRY_KEYS or compact in s.STRUCTURED_TELEMETRY_KEYS


def _is_test_client_client_error(*, client: str, status_code: int) -> bool:
    s = _service()
    if not (400 <= int(status_code or 0) < 500):
        return False
    normalized_client = str(client or "").strip().lower()
    return normalized_client in s.TEST_CLIENT_HOSTS


def _iter_runtime_scene_descendants(root: Path) -> list[Path]:
    s = _service()
    try:
        return sorted(root.rglob("*"))
    except OSError:
        return []


def _join_index_key_parts(parts: list[str]) -> str:
    s = _service()
    return "_".join(s._slugify_index_token(part, default="") for part in parts if s._slugify_index_token(part, default=""))


def _join_search_text(parts: list[str]) -> str:
    s = _service()
    chunks: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = " ".join(str(part or "").strip().split())
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        chunks.append(text)
    joined = " ".join(chunks)
    if len(joined) <= s.MAX_PACKAGE_INDEX_SEARCH_TEXT_CHARS:
        return joined
    return joined[:s.MAX_PACKAGE_INDEX_SEARCH_TEXT_CHARS].rstrip() + " ..."


def _jsonl_file_signature(path: Path) -> tuple[str, bool, int, int]:
    s = _service()
    try:
        stat = path.stat()
    except OSError:
        return (str(path), False, 0, 0)
    return (str(path), True, int(stat.st_mtime_ns), int(stat.st_size))


def _list_agent_logs(scene_dir: Path) -> list[dict[str, Any]]:
    s = _service()
    return s._list_package_files(scene_dir, s.AGENT_DIR, label_prefix="Agent")


def _list_artifacts(scene_dir: Path) -> list[dict[str, Any]]:
    s = _service()
    return s._list_package_files(scene_dir, s.ARTIFACTS_DIR, label_prefix="Artifact")


def _list_conversation_logs(scene_dir: Path) -> list[dict[str, Any]]:
    s = _service()
    return (
        s._list_package_files(scene_dir, s.SESSIONS_DIR, label_prefix="Session")
        + s._list_package_files(scene_dir, s.CONVERSATIONS_DIR, label_prefix="Conversation")
    )


def _list_event_logs(scene_dir: Path) -> list[dict[str, Any]]:
    s = _service()
    return s._list_package_files(scene_dir, s.EVENTS_DIR, label_prefix="Event stream")


def _list_package_files(scene_dir: Path, relative_dir: str, *, label_prefix: str) -> list[dict[str, Any]]:
    s = _service()
    root = scene_dir / relative_dir
    items: list[dict[str, Any]] = []
    try:
        if not root.exists() or not root.is_dir():
            return items
    except OSError:
        return items
    for file_path in s._iter_runtime_scene_descendants(root):
        if not s._is_readable_file(file_path):
            continue
        relative = file_path.relative_to(scene_dir).as_posix()
        size = s._runtime_scene_file_size(file_path)
        if size is None:
            continue
        items.append(
            {
                "path": relative,
                "label": f"{label_prefix}: {file_path.stem}",
                "size": size,
                "language": s.LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text"),
                "updatedAt": s._file_timestamp(file_path),
            }
        )
    return items


def _list_raw_files(scene_dir: Path) -> list[dict]:
    s = _service()
    raw_dir = scene_dir / "raw"
    items: list[dict] = []
    try:
        if not raw_dir.exists() or not raw_dir.is_dir():
            return items
    except OSError:
        return items
    for file_path in s._iter_runtime_scene_descendants(raw_dir):
        if not s._is_readable_file(file_path):
            continue
        relative = file_path.relative_to(scene_dir).as_posix()
        size = s._runtime_scene_file_size(file_path)
        if size is None:
            continue
        items.append(
            {
                "path": relative,
                "label": s.RAW_LABELS.get(relative, file_path.name),
                "size": size,
                "language": s.LANGUAGE_BY_SUFFIX.get(file_path.suffix.lower(), "text"),
            }
        )
    return items


def _list_research_logs(scene_dir: Path) -> list[dict[str, Any]]:
    s = _service()
    return s._list_package_files(scene_dir, s.RESEARCH_DIR, label_prefix="Research")


def _load_active_runtime_scene_reference() -> dict[str, Any]:
    """Read the Launcher-owned runtime-scene reference beside its state projection."""
    s = _service()

    active_scene_path = s.LAUNCHER_STATE_PATH.with_name("active-runtime-scene.json")
    try:
        payload = json.loads(active_scene_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_launcher_state() -> dict[str, Any]:
    s = _service()
    try:
        payload = json.loads(s.LAUNCHER_STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_scene_json(path: Path) -> dict[str, Any]:
    s = _service()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_scene_manifest(scene_dir: Path) -> dict:
    s = _service()
    manifest_path = scene_dir / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _looks_like_windows_absolute_path(value: str) -> bool:
    s = _service()
    return len(value) >= 3 and value[1] == ":" and value[0].isalpha() and value[2] == "/"


def _maybe_close_runtime_scene_from_reconciliation(
    scene_dir: Path,
    manifest: dict[str, Any],
    event_name: str,
    fields: dict[str, Any],
    timestamp: str,
) -> bool:
    s = _service()
    if event_name != "runtime.snapshot.reconciled":
        return False
    if str(manifest.get("status") or "").strip().lower() not in {"", "running", "starting", "queued", "opening", "stopping", "closing"}:
        return False
    observed_state = str(fields.get("observedState") or "").strip().lower()
    desired_state = str(fields.get("desiredState") or "").strip().lower()
    manager_running = bool(fields.get("managerRunning"))
    backend_pid = s._coerce_int(fields.get("backendPid"), default=0)
    browser_pid = s._coerce_int(fields.get("browserWindowPid"), default=0)
    if observed_state != "closed" or desired_state != "closed" or manager_running or backend_pid or browser_pid:
        return False

    manifest["status"] = "stopped"
    manifest["result"] = str(manifest.get("result") or "state_reconciled")
    manifest["stop_reason"] = str(manifest.get("stop_reason") or "runtime manager observed all workbench processes closed")
    manifest["ended_at"] = str(manifest.get("ended_at") or timestamp or s._now_utc())

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


def _next_research_event_seq(scene_dir: Path) -> int:
    s = _service()
    last_seq = 0
    for row in s._read_jsonl_file(scene_dir / s.RESEARCH_EVENTS_PATH):
        try:
            last_seq = max(last_seq, int(row.get("seq") or 0))
        except (TypeError, ValueError):
            continue
    return last_seq + 1


def _next_scene_event_seq(scene_dir: Path, component: str) -> int:
    s = _service()
    event_path = scene_dir / "events" / f"{component}.jsonl"
    signature = s._scene_event_file_signature(event_path)
    cache_key = str(event_path.resolve())
    with s._SCENE_EVENT_SEQ_CACHE_LOCK:
        cached = s._SCENE_EVENT_SEQ_CACHE.get(cache_key)
    if cached is not None and cached[:2] == signature:
        return cached[2] + 1

    last_seq = s._read_last_scene_event_seq(event_path)
    with s._SCENE_EVENT_SEQ_CACHE_LOCK:
        s._SCENE_EVENT_SEQ_CACHE[cache_key] = (*signature, last_seq)
    return last_seq + 1


def _normalize_endpoint_path(value: object) -> str:
    s = _service()
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.split("?", 1)[0].split("#", 1)[0]
    if "://" in text:
        marker = "://"
        remainder = text.split(marker, 1)[1]
        slash_index = remainder.find("/")
        text = remainder[slash_index:] if slash_index >= 0 else ""
    return text.rstrip("/") or text


def _normalize_event_timestamp(value: object) -> str:
    s = _service()
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
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _normalize_raw_refs(value: object) -> list[dict[str, Any]]:
    s = _service()
    if not isinstance(value, list):
        return []
    refs: list[dict[str, Any]] = []
    for item in value[:s.MAX_TELEMETRY_FIELD_ITEMS]:
        if not isinstance(item, dict):
            continue
        path = s._truncate_text(str(item.get("path") or "").strip().replace("\\", "/"), 240)
        if not path:
            continue
        ref: dict[str, Any] = {"path": path}
        tail_lines = s._coerce_int(item.get("tail_lines"), default=0)
        if tail_lines > 0:
            ref["tail_lines"] = min(tail_lines, 1_000)
        refs.append(ref)
    return refs


def _normalize_relative_path(value: str) -> str:
    s = _service()
    relative = str(value or "").strip().replace("\\", "/")
    if not relative:
        raise ValueError("Runtime scene path is required")
    return relative


def _normalize_scene_ids(scene_ids: list[str] | tuple[str, ...]) -> list[str]:
    s = _service()
    normalized: list[str] = []
    for item in scene_ids:
        value = str(item or "").strip()
        if not value or value in normalized:
            continue
        normalized.append(value)
    return normalized


def _normalize_structured_telemetry_value(value: object, *, depth: int = 0) -> Any:
    s = _service()
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return s._truncate_text(value, s.MAX_TELEMETRY_FIELD_TEXT_CHARS)
    if depth >= 5:
        return s._truncate_text(str(value), s.MAX_TELEMETRY_FIELD_TEXT_CHARS)
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= s.MAX_TELEMETRY_FIELD_ITEMS:
                break
            key_text = str(key)
            normalized[key_text] = (
                s.REDACTED_FIELD_VALUE
                if s._is_sensitive_telemetry_key(key_text)
                else s._normalize_structured_telemetry_value(item, depth=depth + 1)
            )
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            s._normalize_structured_telemetry_value(item, depth=depth + 1)
            for item in list(value)[:s.MAX_TELEMETRY_FIELD_ITEMS]
        ]
    return s._truncate_text(str(value), s.MAX_TELEMETRY_FIELD_TEXT_CHARS)


def _normalize_telemetry_fields(value: object) -> dict[str, Any]:
    s = _service()
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= s.MAX_TELEMETRY_FIELD_ITEMS:
                break
            key_text = str(key)
            if s._is_structured_telemetry_key(key_text):
                normalized[key_text] = s._normalize_structured_telemetry_value(item)
                continue
            normalized[key_text] = (
                s.REDACTED_FIELD_VALUE
                if s._is_sensitive_telemetry_key(key_text)
                else s._normalize_telemetry_value(item, depth=0)
            )
        return normalized
    if value is None:
        return {}
    return {"value": s._normalize_telemetry_value(value, depth=0)}


def _normalize_telemetry_value(value: object, *, depth: int) -> Any:
    s = _service()
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return s._truncate_text(value, s.MAX_TELEMETRY_FIELD_TEXT_CHARS)
    if depth >= 2:
        return s._truncate_text(str(value), s.MAX_TELEMETRY_FIELD_TEXT_CHARS)
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= s.MAX_TELEMETRY_FIELD_ITEMS:
                break
            key_text = str(key)
            if s._is_structured_telemetry_key(key_text):
                normalized[key_text] = s._normalize_structured_telemetry_value(item, depth=depth + 1)
                continue
            normalized[key_text] = (
                s.REDACTED_FIELD_VALUE
                if s._is_sensitive_telemetry_key(key_text)
                else s._normalize_telemetry_value(item, depth=depth + 1)
            )
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            s._normalize_telemetry_value(item, depth=depth + 1)
            for item in list(value)[:s.MAX_TELEMETRY_FIELD_ITEMS]
        ]
    return s._truncate_text(str(value), s.MAX_TELEMETRY_FIELD_TEXT_CHARS)


def _now_utc() -> str:
    s = _service()
    return datetime.now(timezone.utc).isoformat()


def _package_index_status_token(manifest: dict) -> str:
    s = _service()
    status = s._runtime_scene_status(manifest)
    result = str(manifest.get("result") or "").strip().lower()
    stop_reason = str(manifest.get("stop_reason") or "").strip().lower()
    if status == "stopped" and (result or stop_reason):
        return s.PACKAGE_INDEX_RESULT_TOKENS.get(result) or s._slugify_index_token(stop_reason or result, default="stopped")
    return s.PACKAGE_INDEX_STATUS_TOKENS.get(status, s._slugify_index_token(status, default="unknown"))


def _package_index_trigger_token(trigger: str) -> str:
    s = _service()
    normalized = str(trigger or "").strip().lower()
    if not normalized:
        return "workbench-run"
    return s.PACKAGE_INDEX_TRIGGER_TOKENS.get(normalized, s._slugify_index_token(normalized, default="workbench-run"))


def _parse_datetime(value: str) -> datetime | None:
    s = _service()
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
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_directory_timestamp_token(value: str) -> datetime | None:
    s = _service()
    text = str(value or "").strip()
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S"):
        try:
            parsed = datetime.strptime(text, pattern)
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone.utc)
    return None


def _read_jsonl_file(path: Path) -> list[dict]:
    s = _service()
    signature = s._jsonl_file_signature(path)
    if not signature[1]:
        return []
    cached = s._get_jsonl_file_cache(signature)
    if cached is not None:
        return cached
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
    s._remember_jsonl_file_cache(signature, rows)
    return s._copy_jsonl_rows(rows)


def _read_last_scene_event_seq(event_path: Path) -> int:
    """Read only the bounded tail needed to recover a component sequence."""
    s = _service()

    try:
        with event_path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - s.MAX_TEXT_CHARS))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return 0
    for line in reversed(tail.splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            return max(0, int(payload.get("seq") or 0)) if isinstance(payload, dict) else 0
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return 0


def _read_scene_lifecycle(scene_dir: Path, fallback_timeline: list[dict] | None = None) -> list[dict]:
    s = _service()
    lifecycle_path = scene_dir / s.LIFECYCLE_PATH
    events = [
        s._event_payload_to_client_item(row, scene_dir, "lifecycle")
        for row in s._read_jsonl_file(lifecycle_path)
    ]
    if events:
        events.sort(key=lambda item: (item["timestamp"], item["component"], item["seq"]))
        return events
    return [
        item
        for item in list(fallback_timeline or [])
        if str(item.get("phase") or "").strip().lower() in s.LIFECYCLE_INDEX_PHASES
        or str(item.get("eventCode") or "").startswith("runtime.scene.")
    ]


def _read_scene_timeline(scene_dir: Path) -> list[dict]:
    s = _service()
    timeline_rows = s._read_jsonl_file(scene_dir / s.TIMELINE_PATH)
    if timeline_rows:
        timeline = [
            s._event_payload_to_client_item(entry, scene_dir, "timeline")
            for entry in timeline_rows
        ]
        timeline.sort(key=lambda item: (item["timestamp"], item["component"], item["seq"]))
        return s._fold_repeated_work_run_snapshots(timeline)

    events_dir = scene_dir / "events"
    timeline: list[dict] = []
    if not events_dir.exists() or not events_dir.is_dir():
        return timeline

    for file_path in sorted(events_dir.glob("*.jsonl")):
        component = file_path.stem
        for entry in s._read_jsonl_file(file_path):
            timeline.append(s._event_payload_to_client_item(entry, scene_dir, component))

    timeline.sort(key=lambda item: (item["timestamp"], item["component"], item["seq"]))
    return s._fold_repeated_work_run_snapshots(timeline)


def _remember_jsonl_file_cache(signature: tuple[str, bool, int, int], rows: list[dict]) -> None:
    s = _service()
    with s._JSONL_FILE_CACHE_LOCK:
        if len(s._JSONL_FILE_CACHE) > s.JSONL_FILE_CACHE_LIMIT:
            s._JSONL_FILE_CACHE.clear()
        s._JSONL_FILE_CACHE[signature] = s._copy_jsonl_rows(rows)


def _remember_scene_event_seq(event_path: Path, seq: int) -> None:
    s = _service()
    signature = s._scene_event_file_signature(event_path)
    cache_key = str(event_path.resolve())
    with s._SCENE_EVENT_SEQ_CACHE_LOCK:
        if len(s._SCENE_EVENT_SEQ_CACHE) > s.JSONL_FILE_CACHE_LIMIT:
            s._SCENE_EVENT_SEQ_CACHE.clear()
        s._SCENE_EVENT_SEQ_CACHE[cache_key] = (*signature, max(0, int(seq)))


def _resolve_current_runtime_scene_dir() -> Path | None:
    # The Launcher writes the active-scene reference directly.  state.json is a
    # runtime projection and can legitimately omit the runtime scene fields.
    s = _service()
    for runtime_reference in (s._load_active_runtime_scene_reference(), s._load_launcher_state()):
        raw_dir = str(runtime_reference.get("runtimeSceneDir") or "").strip()
        if not raw_dir:
            continue

        scene_dir = Path(raw_dir).resolve()
        try:
            scene_dir.relative_to(s._runtime_scene_root())
        except ValueError:
            continue

        if not scene_dir.exists() or not scene_dir.is_dir():
            continue
        manifest = s._load_scene_manifest(scene_dir)
        if s._is_current_runtime_scene_manifest(scene_dir, manifest, runtime_reference):
            return scene_dir
    return None


def _resolve_recent_completed_runtime_scene_dir(*, max_age_seconds: float = 180.0) -> Path | None:
    s = _service()
    now = datetime.now(timezone.utc)
    for scene_dir in s._scene_dirs():
        manifest = s._load_scene_manifest(scene_dir)
        if not s._runtime_scene_project_matches(manifest):
            continue
        status = str(manifest.get("status") or "").strip().lower()
        if status not in {"failed", "stopped"}:
            continue
        ended_at = s._parse_datetime(str(manifest.get("ended_at") or ""))
        if ended_at is None:
            continue
        age = max(0.0, (now - ended_at.astimezone(timezone.utc)).total_seconds())
        if age <= max_age_seconds:
            return scene_dir
    return None


def _resolve_scene_child(scene_dir: Path, relative_path: str) -> Path:
    s = _service()
    candidate = (scene_dir / relative_path).resolve()
    try:
        candidate.relative_to(scene_dir.resolve())
    except ValueError as exc:
        raise ValueError("Runtime scene path must stay inside the selected scene") from exc
    return candidate


def _resolve_scene_dir(scene_id: str) -> Path:
    s = _service()
    target = str(scene_id or "").strip()
    if not target:
        raise FileNotFoundError("Runtime scene id is required")
    for scene_dir in s._scene_dirs():
        manifest = s._load_scene_manifest(scene_dir)
        if s._scene_id(scene_dir, manifest) == target:
            return scene_dir
    raise FileNotFoundError(f"Runtime scene not found: {target}")


def _resolve_scene_started_at(started_at: str, scene_dir: Path) -> datetime | None:
    s = _service()
    parsed = s._parse_datetime(started_at)
    if parsed is not None:
        return parsed
    marker = "__"
    token = scene_dir.name.split(marker, 1)[0] if marker in scene_dir.name else scene_dir.name
    return s._parse_directory_timestamp_token(token)


def _runtime_scene_base_package_index(
    scene_dir: Path,
    manifest: dict,
    scene_id: str,
    *,
    cached_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    cached = cached_package if isinstance(cached_package, dict) else {}
    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    raw_started_at = str(manifest.get("started_at") or package.get("started_at") or "").strip()
    started = s._resolve_scene_started_at(raw_started_at, scene_dir)
    started_at = raw_started_at or (started.isoformat() if started else "")
    ended_at = str(manifest.get("ended_at") or "").strip() if s._runtime_scene_has_completed(manifest) else ""
    ended = s._parse_datetime(ended_at)
    display_name = s._runtime_scene_display_name(scene_dir, manifest, scene_id)
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
    trigger_token = s._package_index_trigger_token(str(manifest.get("trigger") or ""))
    status_token = s._package_index_status_token(manifest)
    index_key = s._join_index_key_parts([started_date, started_time.replace(":", "-"), trigger_token, status_token])
    duration_seconds = s._scene_duration_seconds(started, ended)
    tags = s._runtime_scene_index_tags(manifest, trigger_token, status_token)
    cached_tags = cached.get("tags")
    if isinstance(cached_tags, list):
        for tag in cached_tags:
            token = str(tag or "").strip()
            if token and token not in tags:
                tags.append(token)
    search_text = s._join_search_text(
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
        "summaryRef": s.SUMMARY_PATH,
    }


def _runtime_scene_conversation_correlation_ids(
    session_id: str,
    message: dict[str, Any] | None,
) -> dict[str, str]:
    s = _service()
    sources: list[dict[str, Any]] = []
    if isinstance(message, dict):
        sources.append(message)
        metadata = message.get("metadata")
        if isinstance(metadata, dict):
            sources.append(metadata)

    return {
        "session_id": s._runtime_scene_safe_id(session_id)
        or s._runtime_scene_first_safe_id(sources, ("sessionId", "session_id")),
        "turn_id": s._runtime_scene_first_safe_id(sources, ("turnId", "turn_id")),
        "client_submission_id": s._runtime_scene_first_safe_id(
            sources,
            ("clientSubmissionId", "submissionId", "client_submission_id", "submission_id"),
        ),
        "invocation_id": s._runtime_scene_first_safe_id(sources, ("invocationId", "invocation_id")),
    }


def _runtime_scene_conversation_message_summary(
    message: dict[str, Any] | None,
    correlation_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    s = _service()
    if not isinstance(message, dict):
        return {}
    summary: dict[str, Any] = {}
    for key in ("id", "messageId", "apiId", "role", "timestamp", "createdAt", "updatedAt"):
        value = message.get(key)
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            summary[key] = value
    metadata = message.get("metadata")
    if isinstance(metadata, dict):
        safe_metadata = {
            key: metadata[key]
            for key in ("source", "kind")
            if isinstance(metadata.get(key), (str, int, float, bool)) and metadata.get(key) not in ("", None)
        }
        normalized_ids = correlation_ids or s._runtime_scene_conversation_correlation_ids("", message)
        for source_key, target_key in (
            ("turn_id", "turnId"),
            ("client_submission_id", "clientSubmissionId"),
            ("invocation_id", "invocationId"),
        ):
            value = normalized_ids.get(source_key) or ""
            if value:
                safe_metadata[target_key] = value
        if safe_metadata:
            summary["metadata"] = safe_metadata
    return summary


def _runtime_scene_display_name(scene_dir: Path, manifest: dict, scene_id: str) -> str:
    s = _service()
    label = s._display_name_time_label(str(manifest.get("started_at") or ""), scene_dir)
    trigger_label = s._display_name_trigger_label(str(manifest.get("trigger") or ""))
    status_label = s._display_name_status_label(manifest)
    parts = [item for item in [label, trigger_label, status_label] if item]
    if parts:
        return " · ".join(parts)
    return str(manifest.get("title") or scene_dir.name or scene_id).strip()


def _runtime_scene_event_requires_full_projection_refresh(
    *,
    level: str,
    reconciliation_closed: bool,
) -> bool:
    """Keep expensive diagnosis generation off the ordinary event write path."""
    s = _service()

    if reconciliation_closed:
        return True
    return str(level or "").strip().lower() in {"warning", "error", "critical", "fatal"}


def _runtime_scene_event_requires_immediate_projection(
    *,
    event_code: str,
    level: str,
    outcome: str,
) -> bool:
    """Keep recovered hot-path telemetry append-only until an on-demand refresh."""
    s = _service()

    normalized_event = str(event_code or "").strip()
    normalized_outcome = str(outcome or "").strip().lower()
    if normalized_event == "llm.replay_state.degraded" and normalized_outcome == "degraded":
        return False
    return (
        normalized_event == "runtime.snapshot.reconciled"
        or str(level or "").strip().lower() in {"warning", "error", "critical", "fatal"}
    )


def _runtime_scene_file_size(path: Path) -> int | None:
    s = _service()
    try:
        return path.stat().st_size
    except OSError:
        return None


def _runtime_scene_first_safe_id(
    sources: list[dict[str, Any]],
    aliases: tuple[str, ...],
) -> str:
    s = _service()
    for alias in aliases:
        for source in sources:
            normalized = s._runtime_scene_safe_id(source.get(alias))
            if normalized:
                return normalized
    return ""


def _runtime_scene_has_completed(manifest: dict) -> bool:
    s = _service()
    status = s._runtime_scene_status(manifest)
    return status not in {"running", "starting", "queued", "stopping"}


def _runtime_scene_index_tags(manifest: dict, trigger_token: str, status_token: str) -> list[str]:
    s = _service()
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
        token = s._slugify_index_token(value, default="")
        if not token or token in seen:
            continue
        seen.add(token)
        tags.append(token)
    return tags


def _runtime_scene_is_diagnostic_only_observation(payload: dict[str, Any]) -> bool:
    s = _service()
    event_code = str(payload.get("event_code") or "").strip()
    component = str(payload.get("component") or "").strip()
    phase = str(payload.get("phase") or "").strip()
    if event_code in s.TIMELINE_DIAGNOSTIC_ONLY_EVENT_CODES:
        return True
    if event_code in {"browser.memory.sampled", "browser.process_memory.sampled"}:
        return True
    if phase in s.TIMELINE_DIAGNOSTIC_ONLY_PHASES:
        return True
    return (component, phase) in s.TIMELINE_DIAGNOSTIC_ONLY_COMPONENT_PHASES


def _runtime_scene_lightweight_package_index(
    scene_dir: Path,
    manifest: dict,
    scene_id: str,
    summary_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    summary = summary_payload if isinstance(summary_payload, dict) else s._load_scene_json(scene_dir / s.SUMMARY_PATH)
    package_sidecar = s._load_scene_json(scene_dir / s.PACKAGE_INDEX_PATH)
    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    diagnosis = summary.get("diagnosis") if isinstance(summary.get("diagnosis"), dict) else None
    if isinstance(diagnosis, dict):
        return s._runtime_scene_package_index_from_diagnosis(
            scene_dir,
            manifest,
            scene_id,
            diagnosis,
            cached_package=package_sidecar if package_sidecar else package,
        )
    return s._runtime_scene_base_package_index(
        scene_dir,
        manifest,
        scene_id,
        cached_package=package_sidecar if package_sidecar else package,
    )


def _runtime_scene_lightweight_package_index_payload(package_index: dict[str, Any]) -> dict[str, Any]:
    """Build the package_index sidecar shape without reading timeline/raw logs."""
    s = _service()

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
        "summary_ref": s.SUMMARY_PATH,
        "timeline_path": s.TIMELINE_PATH,
        "lifecycle_path": s.LIFECYCLE_PATH,
        "raw_dir": "raw",
        "conversations_dir": s.CONVERSATIONS_DIR,
        "sessions_dir": s.SESSIONS_DIR,
        "runs_dir": s.RUNS_DIR,
        "agent_dir": s.AGENT_DIR,
        "artifacts_dir": s.ARTIFACTS_DIR,
        "research_dir": s.RESEARCH_DIR,
    }


def _runtime_scene_manifest_package_index_values(package_index: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    return {
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
        "package_index_path": s.PACKAGE_INDEX_PATH,
        "summary_path": s.SUMMARY_PATH,
        "timeline_path": s.TIMELINE_PATH,
        "lifecycle_path": s.LIFECYCLE_PATH,
        "raw_dir": "raw",
        "conversations_dir": s.CONVERSATIONS_DIR,
        "agent_dir": s.AGENT_DIR,
        "artifacts_dir": s.ARTIFACTS_DIR,
        "research_dir": s.RESEARCH_DIR,
    }


def _runtime_scene_package_index(scene_dir: Path, manifest: dict, scene_id: str) -> dict[str, Any]:
    s = _service()
    return s._runtime_scene_package_index_from_diagnosis(
        scene_dir,
        manifest,
        scene_id,
        s._runtime_scene_package_diagnosis_for_scene(scene_dir, manifest, scene_id),
    )


def _runtime_scene_package_index_payload(scene_dir: Path, package_index: dict[str, Any]) -> dict[str, Any]:
    s = _service()
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
        "summary_ref": s.SUMMARY_PATH,
        "timeline_path": s.TIMELINE_PATH,
        "lifecycle_path": s.LIFECYCLE_PATH,
        "raw_dir": "raw",
        "conversations_dir": s.CONVERSATIONS_DIR,
        "sessions_dir": s.SESSIONS_DIR,
        "runs_dir": s.RUNS_DIR,
        "agent_dir": s.AGENT_DIR,
        "artifacts_dir": s.ARTIFACTS_DIR,
        "research_dir": s.RESEARCH_DIR,
        "snapshot_metadata": s._runtime_scene_snapshot_metadata(scene_dir),
    }


def _runtime_scene_payload_has_diagnostic_signal(payload: dict[str, Any]) -> bool:
    s = _service()
    event = {
        "runtimeSceneId": str(payload.get("runtime_scene_id") or ""),
        "component": str(payload.get("component") or ""),
        "phase": str(payload.get("phase") or ""),
        "eventCode": str(payload.get("event_code") or ""),
        "level": str(payload.get("level") or "info"),
        "message": str(payload.get("message") or ""),
        "timestamp": str(payload.get("ts") or ""),
        "seq": int(payload.get("seq") or 0),
        "outcome": str(payload.get("outcome") or ""),
        "fields": payload.get("fields") if isinstance(payload.get("fields"), dict) else {},
        "rawRefs": payload.get("raw_refs") if isinstance(payload.get("raw_refs"), list) else [],
    }
    return s._runtime_scene_event_severity(event) in {"warning", "error"}


def _runtime_scene_project_matches(manifest: dict[str, Any]) -> bool:
    s = _service()
    manifest_project_root = str(
        manifest.get("project_root")
        or manifest.get("projectRoot")
        or ((manifest.get("project") or {}) if isinstance(manifest.get("project"), dict) else {}).get("root")
        or ""
    ).strip()
    if manifest_project_root and not s._same_path(manifest_project_root, s.PROJECT_ROOT):
        return False
    return True


def _runtime_scene_research_summary_event(event: dict[str, Any] | None) -> dict[str, Any] | None:
    s = _service()
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


def _runtime_scene_research_summary_payload(events: list[dict[str, Any]]) -> dict[str, Any]:
    s = _service()
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
        "latest_event": s._runtime_scene_research_summary_event(latest_event),
        "events_path": s.RESEARCH_EVENTS_PATH,
        "generated_at": s._now_utc(),
    }


def _runtime_scene_root() -> Path:
    s = _service()
    return (s.PROJECT_ROOT / "logs" / "runtime_scenes").resolve()


def _runtime_scene_safe_id(value: Any) -> str:
    s = _service()
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return s._truncate_text(str(value).strip(), 320)


def _runtime_scene_safe_tool_calls(tool_calls: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    s = _service()
    if not isinstance(tool_calls, list):
        return []
    safe_items: list[dict[str, str]] = []
    for item in tool_calls:
        if not isinstance(item, dict):
            continue
        safe_item: dict[str, str] = {}
        for key in ("id", "callId", "name", "status"):
            value = s._runtime_scene_safe_id(item.get(key))
            if value:
                safe_item[key] = value
        invocation_id = s._runtime_scene_first_safe_id([item], ("invocationId", "invocation_id"))
        if invocation_id:
            safe_item["invocationId"] = invocation_id
        summary = s._truncate_text(str(item.get("summary") or ""), 800)
        if summary:
            safe_item["summary"] = summary
        safe_items.append(safe_item)
    return safe_items


def _runtime_scene_snapshot_metadata(scene_dir: Path) -> dict[str, Any]:
    s = _service()
    timeline = s._read_scene_timeline(scene_dir)
    lifecycle = s._read_scene_lifecycle(scene_dir, timeline)
    last_event_timestamp = ""
    for event in [*timeline, *lifecycle]:
        ts = str(event.get("ts") or event.get("timestamp") or event.get("recordedAt") or "")
        if ts and (not last_event_timestamp or ts > last_event_timestamp):
            last_event_timestamp = ts
    return {
        "generated_at": s._now_utc(),
        "source_event_count": len(timeline) + len(lifecycle),
        "timeline_event_count": len(timeline),
        "lifecycle_event_count": len(lifecycle),
        "last_event_timestamp": last_event_timestamp,
        "is_live_snapshot": not s._runtime_scene_has_completed(s._load_scene_manifest(scene_dir)),
    }


def _runtime_scene_status(manifest: dict) -> str:
    s = _service()
    status = str(manifest.get("status") or "").strip().lower()
    if status and status != "unknown":
        return status
    if str(manifest.get("ended_at") or "").strip():
        return status or "unknown"
    return "running"


def _runtime_scene_summary_counts(scene_dir: Path) -> dict[str, int]:
    s = _service()
    timeline = s._read_scene_timeline(scene_dir)
    lifecycle = s._read_scene_lifecycle(scene_dir, timeline)
    raw_files = s._list_raw_files(scene_dir)
    conversation_logs = s._list_conversation_logs(scene_dir)
    agent_logs = s._list_agent_logs(scene_dir)
    artifacts = s._list_artifacts(scene_dir)
    event_logs = s._list_event_logs(scene_dir)
    research_logs = s._list_research_logs(scene_dir)
    research_events = s._read_jsonl_file(scene_dir / s.RESEARCH_EVENTS_PATH)
    severity = s._runtime_scene_severity_summary(timeline)
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
        "supervised_evolution_logs": s._count_runtime_scene_files(scene_dir, f"{s.RUNS_DIR}/supervised")
        + s._count_runtime_scene_files(scene_dir, f"{s.RUNS_DIR}/supervised_worktree")
        + s._count_runtime_scene_files(scene_dir, f"{s.AGENT_DIR}/supervised_runs")
        + s._count_runtime_scene_files(scene_dir, f"{s.AGENT_DIR}/supervised_worktree_runs"),
        "self_evolution_logs": s._count_runtime_scene_files(scene_dir, f"{s.RUNS_DIR}/self_evolution")
        + s._count_runtime_scene_files(scene_dir, f"{s.AGENT_DIR}/self_evolution_runs"),
        "errors": severity["errorCount"],
        "warnings": severity["warningCount"],
    }


def _runtime_scene_summary_payload(
    scene_dir: Path,
    manifest: dict[str, Any],
    package_index: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    diagnosis = s._runtime_scene_package_diagnosis_for_scene(scene_dir, manifest, package_index["packageId"])
    timeline = s._read_scene_timeline(scene_dir)
    return {
        "schema_version": 2,
        "package_id": package_index["packageId"],
        "display_name": package_index["displayName"],
        "index_key": package_index["indexKey"],
        "status": s._runtime_scene_status(manifest),
        "result": str(manifest.get("result") or ""),
        "stop_reason": str(manifest.get("stop_reason") or ""),
        "trigger": str(manifest.get("trigger") or ""),
        "started_at": package_index["startedAt"],
        "started_at_local": package_index["startedAtLocal"],
        "started_date": package_index["startedDate"],
        "started_time": package_index["startedTime"],
        "ended_at": package_index["endedAt"],
        "duration_seconds": package_index["durationSeconds"],
        "event_counts": s._runtime_scene_summary_counts(scene_dir),
        "snapshot_metadata": s._runtime_scene_snapshot_metadata(scene_dir),
        "operation_timings": s._runtime_scene_operation_timing_summary(timeline),
        "agent_brief": s._runtime_scene_agent_brief(diagnosis),
        "diagnosis": diagnosis,
        "primary_files": {
            "summary": s.SUMMARY_PATH,
            "package_index": s.PACKAGE_INDEX_PATH,
            "manifest": "manifest.json",
            "timeline": s.TIMELINE_PATH,
            "lifecycle": s.LIFECYCLE_PATH,
            "startup": "raw/desktop-entry.log",
            "research": s.RESEARCH_SUMMARY_PATH,
        },
        "sections": s._runtime_scene_summary_sections(),
        "diagnostic_entrypoint": {
            "first_read": s.SUMMARY_PATH,
            "purpose": "Agent first-read summary for reconstructing this lifecycle package before opening child logs.",
            "package_root": f"logs/runtime_scenes/{scene_dir.name}",
            "path_mode": "package_relative",
            "evidence_paths": diagnosis.get("evidencePaths", []),
            "recommended_order": [
                s.SUMMARY_PATH,
                s.PACKAGE_INDEX_PATH,
                "raw/desktop-entry-vbs.log",
                "raw/desktop-entry.log",
                "raw/launcher-control.log",
                s.TIMELINE_PATH,
                s.LIFECYCLE_PATH,
                "sessions/",
                "conversations/",
                "agent/turns.jsonl",
                "agent/tool_calls.jsonl",
                "runs/supervised/",
                "runs/supervised_worktree/",
                "runs/self_evolution/",
                s.RESEARCH_SUMMARY_PATH,
                s.RESEARCH_EVENTS_PATH,
                "raw/",
                "artifacts/",
            ],
        },
        "generated_at": s._now_utc(),
    }


def _runtime_scene_summary_sections() -> dict[str, dict[str, str]]:
    s = _service()
    return {
        "startup": {
            "path": "raw/desktop-entry.log",
            "vbs_path": "raw/desktop-entry-vbs.log",
            "launcher_path": "raw/launcher-control.log",
            "purpose": "Desktop entry, launcher handoff, runtime manager, backend, browser, and supervisor startup breadcrumbs.",
        },
        "lifecycle": {
            "path": s.LIFECYCLE_PATH,
            "purpose": "Workbench startup, shutdown, recovery, supervision, and lifecycle state changes.",
        },
        "timeline": {
            "path": s.TIMELINE_PATH,
            "purpose": "Merged chronological event stream for the whole runtime scene package.",
        },
        "raw": {
            "path": "raw",
            "purpose": "Raw launcher, backend, frontend, browser, supervisor, and API output.",
        },
        "conversations": {
            "path": s.CONVERSATIONS_DIR,
            "purpose": "Legacy per-session conversation logs retained for read compatibility.",
        },
        "sessions": {
            "path": s.SESSIONS_DIR,
            "purpose": "Canonical session transcripts and isolated per-turn execution evidence.",
        },
        "agent": {
            "path": s.AGENT_DIR,
            "purpose": "Agent turn and tool-call child logs used to diagnose reasoning and execution flow.",
        },
        "supervised_evolution": {
            "path": f"{s.RUNS_DIR}/supervised",
            "worktree_path": f"{s.RUNS_DIR}/supervised_worktree",
            "legacy_path": f"{s.AGENT_DIR}/supervised_runs",
            "purpose": "Supervised evolution run, candidate, review, selection, promotion, and rollback breadcrumbs when present.",
        },
        "self_evolution": {
            "path": f"{s.RUNS_DIR}/self_evolution",
            "legacy_path": f"{s.AGENT_DIR}/self_evolution_runs",
            "purpose": "Unsupervised self-evolution run, checkpoint, reflection, guard, and validation breadcrumbs when present.",
        },
        "research": {
            "path": s.RESEARCH_DIR,
            "events_path": s.RESEARCH_EVENTS_PATH,
            "summary_path": s.RESEARCH_SUMMARY_PATH,
            "purpose": "Research theme discovery sessions, prompt and agent-template edits, searches, evidence extraction, theme selection, and theme-card operations.",
        },
        "artifacts": {
            "path": s.ARTIFACTS_DIR,
            "purpose": "Reports, generated files, snapshots, and other run artifacts referenced by events.",
        },
        "events": {
            "path": s.EVENTS_DIR,
            "purpose": "Component-specific structured event streams backing the merged timeline.",
        },
    }


def _safe_optional_relative_path(value: object) -> str:
    s = _service()
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    try:
        relative = s._normalize_relative_path(text)
    except ValueError:
        return ""
    if (
        relative.startswith("/")
        or relative.startswith("//")
        or relative.startswith("../")
        or "/../" in relative
        or relative == ".."
        or s._looks_like_windows_absolute_path(relative)
    ):
        return ""
    return s._truncate_text(relative, 240)


def _same_path(left: str | Path, right: str | Path) -> bool:
    s = _service()
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return str(left).strip().replace("\\", "/").rstrip("/").lower() == str(right).strip().replace("\\", "/").rstrip("/").lower()


def _sanitize_path_token(value: object, *, default: str) -> str:
    s = _service()
    token = str(value or "").strip()
    if not token:
        token = default
    normalized = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in token)
    normalized = normalized.strip("._-")
    return s._truncate_text(normalized or default, 120)


def _sanitize_token(value: object, *, default: str) -> str:
    s = _service()
    token = str(value or "").strip()
    if not token:
        return default
    return s._truncate_text(token, 120)


def _save_runtime_scene_lightweight_package_index(scene_dir: Path, package_index: dict[str, Any]) -> None:
    s = _service()
    index_path = scene_dir / s.PACKAGE_INDEX_PATH
    payload = s._runtime_scene_lightweight_package_index_payload(package_index)
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_runtime_scene_package_index(scene_dir: Path, package_index: dict[str, Any]) -> None:
    s = _service()
    index_path = scene_dir / s.PACKAGE_INDEX_PATH
    payload = s._runtime_scene_package_index_payload(scene_dir, package_index)
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_runtime_scene_research_summary(scene_dir: Path) -> None:
    s = _service()
    events = s._read_jsonl_file(scene_dir / s.RESEARCH_EVENTS_PATH)
    if not events:
        return
    summary_path = s._resolve_scene_child(scene_dir, s.RESEARCH_SUMMARY_PATH)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(s._runtime_scene_research_summary_payload(events), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _save_runtime_scene_summary(scene_dir: Path, manifest: dict[str, Any], package_index: dict[str, Any]) -> None:
    s = _service()
    summary_path = scene_dir / s.SUMMARY_PATH
    payload = s._runtime_scene_summary_payload(scene_dir, manifest, package_index)
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_scene_manifest(scene_dir: Path, manifest: dict[str, Any]) -> None:
    s = _service()
    manifest_path = scene_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _scene_dirs() -> list[Path]:
    s = _service()
    runtime_scene_root = s._runtime_scene_root()
    if not runtime_scene_root.exists() or not runtime_scene_root.is_dir():
        return []
    return sorted([path for path in runtime_scene_root.iterdir() if path.is_dir()], reverse=True)


def _scene_duration_seconds(started: datetime | None, ended: datetime | None) -> float | None:
    s = _service()
    if started is None or ended is None:
        return None
    return max(0.0, round((ended - started).total_seconds(), 3))


def _scene_event_file_signature(event_path: Path) -> tuple[int, int]:
    s = _service()
    try:
        stat = event_path.stat()
    except OSError:
        return (0, 0)
    return (int(stat.st_size), int(stat.st_mtime_ns))


def _scene_id(scene_dir: Path, manifest: dict) -> str:
    s = _service()
    value = str(manifest.get("runtime_scene_id") or "").strip()
    if value:
        return value
    marker = "__"
    if marker in scene_dir.name:
        return scene_dir.name.split(marker, 1)[1].strip()
    return scene_dir.name


def _seconds_between_iso(start: str, end: str) -> float:
    s = _service()
    try:
        start_at = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        end_at = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return s.BROWSER_VISIBILITY_TIMELINE_MIN_SECONDS
    return max(0.0, (end_at - start_at).total_seconds())


def _should_index_browser_memory_sample(
    manifest: dict[str, Any],
    timestamp: str,
    fields: dict[str, Any],
) -> bool:
    s = _service()
    browser = manifest.get("browser") if isinstance(manifest.get("browser"), dict) else {}
    last_indexed_at = str(browser.get("last_indexed_memory_sample_at") or "").strip()
    if not last_indexed_at:
        return True
    reason = str(fields.get("reason") or "").strip()
    previous_reason = str(browser.get("last_indexed_memory_reason") or "").strip()
    pathname = str(fields.get("pathname") or "").strip()
    previous_pathname = str(browser.get("last_indexed_memory_pathname") or "").strip()
    if reason and reason != previous_reason:
        return True
    if pathname and pathname != previous_pathname:
        return True
    previous_heap = s._coerce_float(browser.get("last_indexed_memory_used_js_heap_mb"), default=0.0)
    next_heap = s._coerce_float(fields.get("usedJSHeapMB"), default=0.0)
    if next_heap and previous_heap and abs(next_heap - previous_heap) >= s.BROWSER_MEMORY_INDEX_HEAP_DELTA_MB:
        return True
    return s._seconds_between_iso(last_indexed_at, timestamp) >= s.BROWSER_MEMORY_INDEX_MIN_SECONDS


def _should_index_browser_telemetry_event(
    manifest: dict[str, Any],
    timestamp: str,
    event_code: str,
    level: str,
    fields: dict[str, Any],
) -> bool:
    """Keep noisy browser focus changes in raw logs unless they add timeline signal."""
    s = _service()

    if level in {"warning", "error"}:
        return True
    if event_code == "browser.memory.sampled":
        return s._should_index_browser_memory_sample(manifest, timestamp, fields)
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
    return s._seconds_between_iso(last_indexed_at, timestamp) >= s.BROWSER_VISIBILITY_TIMELINE_MIN_SECONDS


def _should_promote_scene_event_to_timeline(payload: dict[str, Any]) -> bool:
    """Keep component evidence complete while reserving timeline for diagnostic signals."""
    s = _service()

    event_code = str(payload.get("event_code") or "").strip()
    level = str(payload.get("level") or "").strip().lower()
    fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    if s._is_known_benign_browser_event(payload):
        return False
    if s._runtime_scene_is_diagnostic_only_observation(payload):
        return s._runtime_scene_payload_has_diagnostic_signal(payload)
    if bool(fields.get("controlSignal")) and level in {"", "debug", "info"}:
        return False
    return True


def _slugify_index_token(value: str, *, default: str) -> str:
    s = _service()
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


def _truncate_text(value: str, limit: int) -> str:
    s = _service()
    text = str(value or "")
    return text if len(text) <= limit else f"{text[: max(0, limit - 3)]}..."


def _update_backend_api_manifest(
    scene_dir: Path,
    manifest: dict[str, Any],
    timestamp: str,
    level: str,
    fields: dict[str, Any],
) -> None:
    s = _service()
    backend = manifest.get("backend")
    if not isinstance(backend, dict):
        backend = {}

    backend["api_log_path"] = s.BACKEND_API_RAW_PATH
    backend["last_api_event_at"] = timestamp
    backend["last_api_event_level"] = level

    status_code = fields.get("statusCode")
    if isinstance(status_code, int):
        backend["last_api_status_code"] = status_code
    path_template = fields.get("pathTemplate")
    if isinstance(path_template, str) and path_template.strip():
        backend["last_api_path"] = s._truncate_text(path_template.strip(), s.MAX_TELEMETRY_FIELD_TEXT_CHARS)
    method = fields.get("method")
    if isinstance(method, str) and method.strip():
        backend["last_api_method"] = method.strip()

    manifest["backend"] = backend
    s._save_scene_manifest(scene_dir, manifest)


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
    s = _service()
    browser_key = s._browser_manifest_key_for_telemetry(fields)
    browser = s._browser_manifest_for_role(manifest, browser_key)

    browser["telemetry_path"] = s.BROWSER_TELEMETRY_RAW_PATH
    browser["last_event_at"] = timestamp
    browser["last_event_indexed"] = bool(indexed)
    browser["browser_role"] = "launcher_control_surface" if browser_key == "launcherBrowser" else "workbench"
    surface = fields.get("telemetrySurface")
    if isinstance(surface, str) and surface.strip():
        browser["telemetry_surface"] = s._truncate_text(surface.strip(), s.MAX_TELEMETRY_FIELD_TEXT_CHARS)
    page_instance_id = fields.get("pageInstanceId")
    if isinstance(page_instance_id, str) and page_instance_id.strip():
        browser["page_instance_id"] = s._truncate_text(page_instance_id.strip(), s.MAX_TELEMETRY_FIELD_TEXT_CHARS)

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
            browser[manifest_key] = s._truncate_text(value.strip(), s.MAX_TELEMETRY_FIELD_TEXT_CHARS)

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

    if event_code == "browser.memory.sampled":
        browser["last_memory_sample_at"] = timestamp
        for field_name in (
            "available",
            "usedJSHeapMB",
            "totalJSHeapMB",
            "jsHeapLimitMB",
            "queryCount",
            "activeQueryCount",
            "fetchingQueryCount",
            "staleQueryCount",
            "sessionQueryCount",
            "logQueryCount",
            "reason",
            "pathname",
        ):
            if field_name in fields:
                browser[f"last_memory_{s._camel_to_snake(field_name)}"] = fields.get(field_name)
        memory_sample_count = s._coerce_int(browser.get("memory_sample_count"), default=0) + 1
        browser["memory_sample_count"] = memory_sample_count
        if indexed:
            browser["last_indexed_memory_sample_at"] = timestamp
            browser["last_indexed_memory_reason"] = str(fields.get("reason") or "").strip()
            browser["last_indexed_memory_pathname"] = str(fields.get("pathname") or "").strip()
            browser["last_indexed_memory_used_js_heap_mb"] = fields.get("usedJSHeapMB")
        else:
            browser["memory_sample_suppressed_count"] = s._coerce_int(browser.get("memory_sample_suppressed_count"), default=0) + 1

    if event_code == "browser.process_memory.sampled":
        browser["last_process_memory_sample_at"] = timestamp
        for field_name in (
            "supported",
            "profileDir",
            "count",
            "totalWorkingSetMB",
            "totalPrivateMB",
            "topProcesses",
        ):
            if field_name in fields:
                browser[f"last_process_memory_{s._camel_to_snake(field_name)}"] = fields.get(field_name)

    if event_code in {"browser.session_stream.opened", "browser.session_stream.closed"}:
        browser["last_session_stream_event_at"] = timestamp
        browser["last_session_stream_event_code"] = event_code
        session_id = fields.get("sessionId")
        if isinstance(session_id, str) and session_id.strip():
            browser["last_session_stream_session_id"] = s._truncate_text(
                session_id.strip(),
                s.MAX_TELEMETRY_FIELD_TEXT_CHARS,
            )

    if event_code in {"browser.chat_room_stream.opened", "browser.chat_room_stream.closed"}:
        browser["last_chat_room_stream_event_at"] = timestamp
        browser["last_chat_room_stream_event_code"] = event_code
        room_id = fields.get("roomId")
        if isinstance(room_id, str) and room_id.strip():
            browser["last_chat_room_stream_room_id"] = s._truncate_text(
                room_id.strip(),
                s.MAX_TELEMETRY_FIELD_TEXT_CHARS,
            )

    manifest[browser_key] = browser
    manifest["browser"] = browser
    s._save_scene_manifest(scene_dir, manifest)


def _update_ignored_browser_telemetry_manifest(
    scene_dir: Path,
    manifest: dict[str, Any],
    timestamp: str,
    fields: dict[str, Any],
    *,
    reason: str,
) -> None:
    s = _service()
    browser_key = s._browser_manifest_key_for_telemetry(fields)
    browser = s._browser_manifest_for_role(manifest, browser_key)
    browser["telemetry_path"] = s.BROWSER_TELEMETRY_RAW_PATH
    browser["last_event_at"] = timestamp
    browser["last_event_indexed"] = False
    browser["browser_role"] = "launcher_control_surface" if browser_key == "launcherBrowser" else "workbench"
    browser["last_ignored_telemetry_at"] = timestamp
    browser["last_ignored_telemetry_reason"] = s._truncate_text(reason, 120)
    ignored_count = s._coerce_int(browser.get("ignored_telemetry_count"), default=0)
    browser["ignored_telemetry_count"] = ignored_count + 1
    href = fields.get("href")
    if isinstance(href, str) and href.strip():
        browser["last_ignored_telemetry_href"] = s._truncate_text(href.strip(), s.MAX_TELEMETRY_FIELD_TEXT_CHARS)
    surface = fields.get("telemetrySurface")
    if isinstance(surface, str) and surface.strip():
        browser["last_ignored_telemetry_surface"] = s._truncate_text(surface.strip(), s.MAX_TELEMETRY_FIELD_TEXT_CHARS)
    manifest[browser_key] = browser
    manifest["browser"] = browser
    s._save_scene_manifest(scene_dir, manifest)


def _update_runtime_scene_package_manifest(scene_dir: Path, manifest: dict[str, Any]) -> None:
    s = _service()
    package = manifest.get("package")
    if not isinstance(package, dict):
        package = {}
    scene_id = s._scene_id(scene_dir, manifest)
    package_index = s._runtime_scene_package_index(scene_dir, manifest, scene_id)
    package.update({"schema_version": 2, **s._runtime_scene_manifest_package_index_values(package_index)})
    package["updated_at"] = s._now_utc()
    manifest["package"] = package
    s._save_runtime_scene_research_summary(scene_dir)
    s._save_runtime_scene_package_index(scene_dir, package_index)
    s._save_runtime_scene_summary(scene_dir, manifest, package_index)
    s._save_scene_manifest(scene_dir, manifest)


def _update_runtime_scene_package_manifest_lightweight(scene_dir: Path, manifest: dict[str, Any]) -> None:
    s = _service()
    package = manifest.get("package")
    if not isinstance(package, dict):
        package = {}
    scene_id = s._scene_id(scene_dir, manifest)
    package_index = s._runtime_scene_lightweight_package_index(scene_dir, manifest, scene_id)
    package.update({"schema_version": 2, **s._runtime_scene_manifest_package_index_values(package_index)})
    package["updated_at"] = s._now_utc()
    manifest["package"] = package
    s._save_scene_manifest(scene_dir, manifest)
    try:
        s._save_runtime_scene_lightweight_package_index(scene_dir, package_index)
    except OSError:
        return


def delete_runtime_scenes(scene_ids: list[str] | tuple[str, ...]) -> dict:
    """Delete one or more runtime scene bundles as a unit."""
    s = _service()

    normalized_ids = s._normalize_scene_ids(scene_ids)
    if not normalized_ids:
        raise ValueError("Select at least one runtime scene to delete")

    deleted_ids: list[str] = []
    missing_ids: list[str] = []
    for scene_id in normalized_ids:
        try:
            scene_dir = s._resolve_scene_dir(scene_id)
        except FileNotFoundError:
            missing_ids.append(scene_id)
            continue
        manifest = s._load_scene_manifest(scene_dir)
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


def record_backend_api_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Append one backend API request event into the active runtime scene bundle."""
    s = _service()

    scene_dir = s._resolve_current_runtime_scene_dir()
    if scene_dir is None:
        return {
            "accepted": False,
            "reason": "no_runtime_scene",
        }

    timestamp = datetime.now(timezone.utc).isoformat()
    method = s._truncate_text(str(payload.get("method") or "").upper(), 16)
    path = s._truncate_text(str(payload.get("path") or ""), 240)
    status_code = s._coerce_int(payload.get("status_code"), default=0)
    duration_ms = s._coerce_float(payload.get("duration_ms"), default=0.0)
    path_template = s._truncate_text(str(payload.get("path_template") or path), 240)
    client = s._truncate_text(str(payload.get("client") or ""), 160)
    is_diagnostic_probe = s._is_diagnostic_probe_404(
        method=method,
        path=path,
        path_template=path_template,
        status_code=status_code,
    )
    is_test_client_probe = s._is_test_client_client_error(client=client, status_code=status_code)
    is_operational_client_error = status_code >= 400 and (
        path_template in s.OPERATIONAL_CLIENT_ERROR_PATHS
        or is_diagnostic_probe
        or is_test_client_probe
    )
    level = "error" if status_code >= 500 else "info" if is_operational_client_error else "warning" if status_code >= 400 else "info"
    outcome = (
        "failed"
        if status_code >= 500
        else "operational_client_error"
        if is_operational_client_error
        else "client_error"
        if status_code >= 400
        else "succeeded"
    )
    event_code = s._sanitize_token(payload.get("event_code"), default="backend.api.request")
    message = s._truncate_text(
        str(payload.get("message") or f"{method or 'API'} {path_template or path} -> {status_code or '?'}"),
        320,
    )
    fields = s.developer_sandbox.enrich_debug_fields(s._normalize_telemetry_fields(
        {
            "method": method,
            "path": path,
            "pathTemplate": path_template,
            "statusCode": status_code,
            "durationMs": round(duration_ms, 2),
            "query": s._truncate_text(str(payload.get("query") or ""), 240),
            "queryParamCount": s._coerce_int(payload.get("query_param_count"), default=0),
            "queryKeys": [
                s._truncate_text(str(item or ""), 80)
                for item in list(payload.get("query_keys") or [])[:12]
            ],
            "queryLength": s._coerce_int(payload.get("query_length"), default=0),
            "sensitiveQueryKeyCount": s._coerce_int(payload.get("sensitive_query_key_count"), default=0),
            "client": client,
            "refererPath": s._truncate_text(str(payload.get("referer_path") or ""), 240),
            "requestOrigin": s._truncate_text(str(payload.get("request_origin") or ""), 160),
            "userAgentFamily": s._truncate_text(str(payload.get("user_agent_family") or ""), 40),
            "exceptionType": s._truncate_text(str(payload.get("exception_type") or ""), 120),
            "exceptionMessage": s._truncate_text(str(payload.get("exception_message") or ""), 320),
            "operationalClientError": is_operational_client_error,
            "diagnosticProbe": is_diagnostic_probe,
            "testClientProbe": is_test_client_probe,
        }
    ), project_root=s.PROJECT_ROOT)

    raw_line = f"[{timestamp}] {event_code} [{level}] {message}"
    if fields:
        raw_line = f"{raw_line} :: {json.dumps(fields, ensure_ascii=False, separators=(',', ':'))}"

    with s.BACKEND_API_WRITE_LOCK:
        manifest = s._load_scene_manifest(scene_dir)
        scene_id = s._scene_id(scene_dir, manifest)
        s._append_scene_log_line(scene_dir, s.BACKEND_API_RAW_PATH, s._truncate_text(raw_line, s.MAX_TELEMETRY_TEXT_CHARS))
        event_payload = {
            "schema_version": 1,
            "runtime_scene_id": scene_id,
            "ts": timestamp,
            "component": s.BACKEND_COMPONENT,
            "phase": "api",
            "event_code": event_code,
            "level": level,
            "outcome": outcome,
            "message": message,
            "fields": fields,
            "raw_refs": [
                {
                    "path": s.BACKEND_API_RAW_PATH,
                    "tail_lines": 80,
                },
            ],
        }
        s._append_scene_event(scene_dir, s.BACKEND_COMPONENT, event_payload)
        # API telemetry runs inline with the request middleware. Rebuilding the
        # complete diagnosis here can turn one slow request into a feedback loop:
        # the rebuild blocks other requests, which then cross the slow-request
        # threshold and trigger more rebuilds. Keep the request path append-only
        # plus lightweight sidecars. Runtime-scene detail reads rebuild the full
        # diagnosis on demand through s.get_runtime_scene_detail().
        s._update_runtime_scene_package_manifest_lightweight(scene_dir, manifest)
        projection_refresh = "lightweight"
        s._update_backend_api_manifest(scene_dir, manifest, timestamp, level, fields)

    return {
        "accepted": True,
        "runtimeSceneId": scene_id,
        "recordedAt": timestamp,
        "projectionRefresh": projection_refresh,
    }


def record_browser_telemetry(payload: dict[str, Any]) -> dict[str, Any]:
    """Append one browser-side telemetry event into the active runtime scene bundle."""
    s = _service()

    scene_dir = s._resolve_current_runtime_scene_dir()
    if scene_dir is None:
        return {
            "accepted": False,
            "reason": "no_runtime_scene",
        }

    timestamp = datetime.now(timezone.utc).isoformat()
    phase = s._sanitize_token(payload.get("phase"), default="page")
    event_code = s._sanitize_token(payload.get("eventCode"), default="browser.telemetry")
    level = s._sanitize_token(payload.get("level"), default="info")
    message = s._truncate_text(str(payload.get("message") or event_code), 320)
    fields = s.developer_sandbox.enrich_debug_fields(s._normalize_telemetry_fields(payload.get("fields")), project_root=s.PROJECT_ROOT)

    raw_line = f"[{timestamp}] {event_code} [{level}] {message}"
    if fields:
        raw_line = f"{raw_line} :: {json.dumps(fields, ensure_ascii=False, separators=(',', ':'))}"
    with s.BROWSER_TELEMETRY_WRITE_LOCK:
        manifest = s._load_scene_manifest(scene_dir)
        scene_id = s._scene_id(scene_dir, manifest)
        s._append_scene_log_line(scene_dir, s.BROWSER_TELEMETRY_RAW_PATH, s._truncate_text(raw_line, s.MAX_TELEMETRY_TEXT_CHARS))

        raw_refs = [
            {
                "path": s.BROWSER_TELEMETRY_RAW_PATH,
                "tail_lines": 80,
            },
        ]
        ignored_dev_surface = s._is_dev_browser_telemetry_surface(fields)
        indexed = (not ignored_dev_surface) and s._should_index_browser_telemetry_event(manifest, timestamp, event_code, level, fields)
        event_payload = {
            "schema_version": 1,
            "runtime_scene_id": scene_id,
            "ts": timestamp,
            "component": s.BROWSER_TELEMETRY_COMPONENT,
            "phase": phase,
            "event_code": event_code,
            "level": level,
            "outcome": "observed",
            "message": message,
            "fields": fields,
            "raw_refs": raw_refs,
        }
        if indexed:
            s._append_scene_event(scene_dir, s.BROWSER_TELEMETRY_COMPONENT, event_payload)
            s._update_browser_manifest(scene_dir, manifest, timestamp, event_code, level, message, fields, indexed=indexed)
        else:
            if ignored_dev_surface:
                s._update_ignored_browser_telemetry_manifest(
                    scene_dir,
                    manifest,
                    timestamp,
                    fields,
                    reason="vite_dev_surface",
                )
            else:
                s._update_browser_manifest(scene_dir, manifest, timestamp, event_code, level, message, fields, indexed=indexed)
        s._update_runtime_scene_package_manifest_lightweight(scene_dir, manifest)

    return {
        "accepted": True,
        "runtimeSceneId": scene_id,
        "recordedAt": timestamp,
        "indexed": indexed,
    }


def record_electron_supervisor_event(
    event_code: str,
    *,
    message: str = "",
    fields: dict[str, Any] | None = None,
    level: str = "info",
    outcome: str = "observed",
    occurred_at: str = "",
) -> dict[str, Any]:
    s = _service()
    event_name = str(event_code or "").strip()
    if event_name not in s.ELECTRON_SUPERVISOR_EVENT_CODES:
        raise ValueError(f"unsupported electron supervisor event: {event_name}")
    return s.record_runtime_scene_event(
        "electron_launcher",
        "desktop_supervisor",
        event_name,
        message=message or event_name,
        level=level,
        outcome=outcome,
        fields=fields,
        occurred_at=occurred_at,
        lifecycle=True,
    )


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
    s = _service()

    scene_dir = s._resolve_current_runtime_scene_dir()
    if scene_dir is None and allow_recent_completed:
        scene_dir = s._resolve_recent_completed_runtime_scene_dir()
    if scene_dir is None:
        return {
            "accepted": False,
            "reason": "no_runtime_scene",
        }

    timestamp = s._normalize_event_timestamp(occurred_at) or s._now_utc()
    event_name = s._sanitize_token(event_code, default="research.event")
    phase_name = s._sanitize_token(phase, default="theme_discovery")
    level_name = s._sanitize_token(level, default="info")
    outcome_name = s._sanitize_token(outcome, default="observed")
    normalized_fields = s.developer_sandbox.enrich_debug_fields(s._normalize_telemetry_fields(fields), project_root=s.PROJECT_ROOT)
    normalized_session_id = str(session_id or normalized_fields.get("sessionId") or "").strip()
    normalized_agent_key = str(agent_key or normalized_fields.get("agentKey") or "").strip()
    if normalized_session_id:
        normalized_fields["sessionId"] = normalized_session_id
    if normalized_agent_key:
        normalized_fields["agentKey"] = normalized_agent_key
    message_text = s._truncate_text(str(message or event_name), 320)

    with s.RUNTIME_SCENE_PACKAGE_WRITE_LOCK:
        manifest = s._load_scene_manifest(scene_dir)
        scene_id = s._scene_id(scene_dir, manifest)
        research_payload = {
            "schema_version": 1,
            "runtime_scene_id": scene_id,
            "ts": timestamp,
            "seq": s._next_research_event_seq(scene_dir),
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
        s._append_scene_jsonl(scene_dir, s.RESEARCH_EVENTS_PATH, research_payload)
        s._append_scene_event(
            scene_dir,
            "research",
            {
                "schema_version": 1,
                "runtime_scene_id": scene_id,
                "ts": timestamp,
                "component": "research",
                "phase": phase_name,
                "event_code": event_name,
                "level": level_name,
                "outcome": outcome_name,
                "message": message_text,
                "fields": normalized_fields,
                "raw_refs": [
                    {
                        "path": s.RESEARCH_EVENTS_PATH,
                        "tail_lines": 80,
                    },
                ],
            },
        )
        s._save_runtime_scene_research_summary(scene_dir)
        s._update_runtime_scene_package_manifest(scene_dir, manifest)

    return {
        "accepted": True,
        "runtimeSceneId": scene_id,
        "recordedAt": timestamp,
        "path": s.RESEARCH_EVENTS_PATH,
        "summaryPath": s.RESEARCH_SUMMARY_PATH,
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
    s = _service()

    scene_dir = s._resolve_current_runtime_scene_dir()
    if scene_dir is None:
        return {
            "accepted": False,
            "reason": "no_runtime_scene",
        }

    timestamp = s._now_utc()
    manifest = s._load_scene_manifest(scene_dir)
    scene_id = s._scene_id(scene_dir, manifest)
    normalized_session_id = s._sanitize_path_token(session_id, default="session")
    role_label = s._sanitize_token(role, default="message")
    event_code = f"conversation.{s._sanitize_path_token(event, default='message')}"
    relative_path = f"{s.SESSIONS_DIR}/{normalized_session_id}/transcript.jsonl"
    content_length = len(str(content or ""))
    content_redacted = content_length > 0
    correlation_ids = s._runtime_scene_conversation_correlation_ids(session_id, message)
    payload = {
        "schema_version": 1,
        "runtime_scene_id": scene_id,
        "ts": timestamp,
        **correlation_ids,
        "event": str(event or "message").strip() or "message",
        "role": role_label,
        "status": str(status or "").strip(),
        "content": "",
        "content_length": content_length,
        "content_redacted": content_redacted,
        "message": s._runtime_scene_conversation_message_summary(message, correlation_ids),
        "tool_calls": s._runtime_scene_safe_tool_calls(tool_calls),
        "active_task": active_task if isinstance(active_task, dict) else {},
    }
    with s.RUNTIME_SCENE_PACKAGE_WRITE_LOCK:
        s._append_scene_jsonl(scene_dir, relative_path, payload)
        s._append_agent_turn_log(scene_dir, payload)
        s._append_agent_tool_call_logs(scene_dir, payload)
        s._append_scene_event(
            scene_dir,
            "conversation",
            {
                "schema_version": 1,
                "runtime_scene_id": scene_id,
                "ts": timestamp,
                "component": "conversation",
                "phase": str(event or "message").strip() or "message",
                "event_code": event_code,
                "level": "info" if str(status or "").strip().lower() != "failed" else "error",
                "outcome": str(status or "observed").strip() or "observed",
                "message": f"{role_label} conversation message recorded ({content_length} chars).",
                "fields": {
                    "sessionId": correlation_ids["session_id"],
                    "turnId": correlation_ids["turn_id"],
                    "clientSubmissionId": correlation_ids["client_submission_id"],
                    "invocationId": correlation_ids["invocation_id"],
                    "role": role_label,
                    "status": str(status or "").strip(),
                    "contentLength": content_length,
                    "contentRedacted": content_redacted,
                },
                "raw_refs": [
                    {
                        "path": relative_path,
                        "tail_lines": 80,
                    },
                ],
            },
        )
        # Conversation breadcrumbs are emitted from the chat turn hot path (or
        # its ordered projection worker). A complete diagnosis rebuild can hold
        # the GIL and package lock for seconds, delaying turn scheduling even
        # when the caller uses a background executor. Persist the bounded event
        # and lightweight sidecars here; runtime-scene detail reads rebuild the
        # full diagnosis on demand.
        s._update_runtime_scene_package_manifest_lightweight(scene_dir, manifest)

    return {
        "accepted": True,
        "runtimeSceneId": scene_id,
        "recordedAt": timestamp,
        "path": relative_path,
        "projectionRefresh": "lightweight",
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
    s = _service()

    scene_dir = s._resolve_current_runtime_scene_dir()
    if scene_dir is None and allow_recent_completed:
        scene_dir = s._resolve_recent_completed_runtime_scene_dir()
    if scene_dir is None:
        return {
            "accepted": False,
            "reason": "no_runtime_scene",
        }

    timestamp = s._normalize_event_timestamp(occurred_at) or s._now_utc()
    component_name = s._sanitize_path_token(component, default="runtime")
    phase_name = s._sanitize_token(phase, default="runtime")
    event_name = s._sanitize_token(event_code, default=f"{component_name}.event")
    level_name = s._sanitize_token(level, default="info")
    outcome_name = s._sanitize_token(outcome, default="observed")
    message_text = s._truncate_text(str(message or event_name), 320)
    normalized_fields = s.developer_sandbox.enrich_debug_fields(s._normalize_telemetry_fields(fields), project_root=s.PROJECT_ROOT)
    normalized_raw_refs = s._normalize_raw_refs(raw_refs)
    normalized_child_path = s._safe_optional_relative_path(child_log_path)
    if normalized_child_path:
        normalized_raw_refs = [
            *normalized_raw_refs,
            {
                "path": normalized_child_path,
                "tail_lines": 80,
            },
        ]

    manifest = s._load_scene_manifest(scene_dir)
    scene_id = s._scene_id(scene_dir, manifest)
    if normalized_child_path:
        child_payload = s.developer_sandbox.enrich_debug_fields(
            s._normalize_telemetry_fields(child_log_payload or {}),
            project_root=s.PROJECT_ROOT,
        )
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
        s._append_scene_jsonl(scene_dir, normalized_child_path, child_payload)
    event_payload = {
        "schema_version": 1,
        "runtime_scene_id": scene_id,
        "ts": timestamp,
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
    s._append_scene_event(scene_dir, component_name, event_payload)

    projection_refresh = "deferred"
    requires_projection_lock = s._runtime_scene_event_requires_immediate_projection(
        event_code=event_name,
        level=level_name,
        outcome=outcome_name,
    )
    if requires_projection_lock:
        # Full diagnosis generation is intentionally isolated from the append
        # lock. A slow warning projection must not queue ordinary Agent events
        # ahead of the provider request.
        with s.pipeline_metrics.measure("projection", priority="high"):
            with s.RUNTIME_SCENE_PACKAGE_WRITE_LOCK:
                manifest = s._load_scene_manifest(scene_dir)
                reconciliation_closed = s._maybe_close_runtime_scene_from_reconciliation(
                    scene_dir,
                    manifest,
                    event_name,
                    normalized_fields,
                    timestamp,
                )
                full_projection_refresh = s._runtime_scene_event_requires_full_projection_refresh(
                    level=level_name,
                    reconciliation_closed=reconciliation_closed,
                )
                if full_projection_refresh:
                    s._update_runtime_scene_package_manifest(scene_dir, manifest)
                    projection_refresh = "full"

    return {
        "accepted": True,
        "runtimeSceneId": scene_id,
        "recordedAt": timestamp,
        "path": normalized_child_path,
        "projectionRefresh": projection_refresh,
    }
