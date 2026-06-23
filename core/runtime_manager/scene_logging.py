"""Runtime-manager logging helpers for lifecycle scene packages."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .constants import EVENTS_PATH, ensure_runtime_manager_dirs

SAFE_COMMAND_ARG_KEYS = {
    "mode",
    "noBrowser",
    "reason",
    "requestAudit",
    "runId",
    "run_id",
    "scope",
    "stopManager",
}

_BACKFILL_WINDOW_SECONDS = 15 * 60
_BACKFILLED_SCENE_KEYS: set[tuple[str, str]] = set()


def append_runtime_manager_file_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    events_path: Path | None = None,
    ensure_dirs: Any | None = None,
    suppress_io_errors: bool = False,
) -> str:
    event_at = datetime.now(timezone.utc).isoformat()
    target_path = events_path or EVENTS_PATH
    ensure_func = ensure_dirs or ensure_runtime_manager_dirs
    try:
        ensure_func()
        event = {
            "type": event_type,
            "at": event_at,
            "payload": payload,
        }
        with target_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        if not suppress_io_errors:
            raise
    return event_at


def command_event_payload(command: dict[str, Any], *, queue_path: str = "") -> dict[str, Any]:
    args = command.get("args") if isinstance(command.get("args"), dict) else {}
    payload: dict[str, Any] = {
        "commandId": str(command.get("commandId") or ""),
        "type": str(command.get("type") or ""),
        "requestedBy": str(command.get("requestedBy") or ""),
        "requestedAt": str(command.get("requestedAt") or ""),
        "args": safe_command_args(args),
    }
    if queue_path:
        payload["queuePath"] = queue_path
    return payload


def safe_command_args(args: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in sorted(SAFE_COMMAND_ARG_KEYS):
        if key not in args:
            continue
        value = args[key]
        if isinstance(value, (bool, int, float)) or value is None:
            safe[key] = value
        elif key == "requestAudit" and isinstance(value, dict):
            safe[key] = {
                str(nested_key): truncate_event_text(str(nested_value), limit=160)
                for nested_key, nested_value in sorted(value.items(), key=lambda item: str(item[0]))
                if isinstance(nested_value, (str, int, float, bool)) or nested_value is None
            }
        else:
            safe[key] = truncate_event_text(str(value), limit=160)
    extra_keys = sorted(str(key) for key in args.keys() if str(key) not in SAFE_COMMAND_ARG_KEYS)
    if extra_keys:
        safe["argKeys"] = extra_keys
    return safe


def record_runtime_manager_scene_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    phase: str = "",
    occurred_at: str = "",
    backfill: bool = True,
    backfilled: bool = False,
) -> bool:
    try:
        runtime_scene_service = _runtime_scene_service()
        allow_recent_completed = _allow_recent_completed_scene(event_type)
        if backfill and not backfilled:
            scene_id = _target_runtime_scene_id(
                runtime_scene_service,
                allow_recent_completed=allow_recent_completed,
            )
            command_id = _event_command_id(payload)
            if scene_id and command_id:
                _backfill_runtime_manager_scene_events(
                    runtime_scene_service,
                    scene_id=scene_id,
                    command_id=command_id,
                    before_at=occurred_at,
                    exclude_event=(event_type, occurred_at, _event_command_id(payload)),
                    allow_recent_completed=allow_recent_completed,
                )
        response = _record_scene_event(
            runtime_scene_service,
            event_type,
            payload,
            phase=phase,
            occurred_at=occurred_at,
            backfilled=backfilled,
            allow_recent_completed=allow_recent_completed,
        )
        accepted = bool(isinstance(response, dict) and response.get("accepted"))
        return accepted
    except Exception:
        return False


def runtime_manager_event_phase(event_type: str) -> str:
    event = str(event_type or "").strip()
    if event.startswith("command_queue."):
        return "queue"
    if event.startswith("command."):
        return "command"
    if event.startswith("workbench.open."):
        return "open"
    if event.startswith("workbench.close."):
        return "close"
    if event.startswith("workbench.restart."):
        return "restart"
    if event.startswith("workbench.consistency."):
        return "consistency"
    if event.startswith("daemon.shutdown."):
        return "shutdown"
    if event.startswith("daemon."):
        return "daemon"
    return "runtime"


def runtime_scene_event_level(event_type: str, payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    if "failed" in event_type or status == "failed" or payload.get("ok") is False:
        return "error"
    warning_markers = (
        "ignored",
        "joined",
        "orphaned",
        "rejected",
        "retry",
        "stale",
        "unreadable",
    )
    if any(marker in event_type for marker in warning_markers):
        return "warning"
    return "info"


def runtime_scene_event_outcome(event_type: str, payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    if "failed" in event_type or status == "failed" or payload.get("ok") is False:
        return "failed"
    if "queued" in event_type:
        return "queued"
    if "claimed" in event_type:
        return "started"
    if "rejected" in event_type:
        return "rejected"
    if "joined" in event_type:
        return "joined"
    if "ignored" in event_type:
        return "ignored"
    if "retry" in event_type:
        return "retrying"
    if "requested" in event_type:
        return "requested"
    if "completed" in event_type or "succeeded" in event_type or payload.get("ok") is True:
        return "succeeded"
    return "observed"


def truncate_event_text(value: str, *, limit: int = 240) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[: max(0, limit - 3)]}..."


def _runtime_scene_service():
    from core.web.services import runtime_scene_service

    return runtime_scene_service


def _record_scene_event(
    runtime_scene_service: Any,
    event_type: str,
    payload: dict[str, Any],
    *,
    phase: str,
    occurred_at: str,
    backfilled: bool,
    allow_recent_completed: bool,
) -> dict[str, Any]:
    fields = dict(payload)
    if occurred_at:
        fields["runtimeManagerEventAt"] = occurred_at
    if backfilled:
        fields["runtimeManagerBackfill"] = True
    return runtime_scene_service.record_runtime_scene_event(
        "runtime_manager",
        phase or runtime_manager_event_phase(event_type),
        event_type,
        message=f"Runtime manager {phase or runtime_manager_event_phase(event_type)} event: {event_type}",
        level=runtime_scene_event_level(event_type, payload),
        outcome=runtime_scene_event_outcome(event_type, payload),
        fields=fields,
        lifecycle=True,
        occurred_at=occurred_at,
        allow_recent_completed=allow_recent_completed,
    )


def _allow_recent_completed_scene(event_type: str) -> bool:
    return str(event_type or "").strip() not in {
        "command_queue.command_queued",
        "command_queue.command_claimed",
        "command_queue.command_rejected_shutdown",
        "command_queue.open_joined",
        "command_queue.close_joined",
        "command_queue.force_close_joined",
        "command_queue.restart_joined",
        "command_queue.stale_shutdown_state_ignored",
    }


def _backfill_runtime_manager_scene_events(
    runtime_scene_service: Any,
    *,
    scene_id: str,
    command_id: str,
    before_at: str,
    exclude_event: tuple[str, str, str],
    allow_recent_completed: bool,
) -> None:
    backfill_key = (scene_id, command_id)
    if backfill_key in _BACKFILLED_SCENE_KEYS:
        return
    _BACKFILLED_SCENE_KEYS.add(backfill_key)
    cutoff = _parse_event_datetime(before_at) or datetime.now(timezone.utc)
    earliest = cutoff - timedelta(seconds=_BACKFILL_WINDOW_SECONDS)
    existing_keys = _existing_scene_event_keys(
        runtime_scene_service,
        allow_recent_completed=allow_recent_completed,
    )
    for row in _read_runtime_manager_file_events():
        event_type = str(row.get("type") or "").strip()
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        occurred_at = str(row.get("at") or "").strip()
        if not event_type or not occurred_at:
            continue
        if _event_command_id(payload) != command_id:
            continue
        occurred = _parse_event_datetime(occurred_at)
        if occurred is not None and (occurred < earliest or occurred > cutoff + timedelta(seconds=1)):
            continue
        key = (event_type, occurred_at, _event_command_id(payload))
        if key == exclude_event or key in existing_keys:
            continue
        _record_scene_event(
            runtime_scene_service,
            event_type,
            payload,
            phase=runtime_manager_event_phase(event_type),
            occurred_at=occurred_at,
            backfilled=True,
            allow_recent_completed=allow_recent_completed,
        )


def _read_runtime_manager_file_events() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = EVENTS_PATH.read_text(encoding="utf-8-sig").splitlines()
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


def _existing_scene_event_keys(runtime_scene_service: Any, *, allow_recent_completed: bool) -> set[tuple[str, str, str]]:
    scene_dir = _target_scene_dir(runtime_scene_service, allow_recent_completed=allow_recent_completed)
    if scene_dir is None:
        return set()
    event_path = scene_dir / "events" / "runtime_manager.jsonl"
    keys: set[tuple[str, str, str]] = set()
    try:
        lines = event_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return keys
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
        occurred_at = str(fields.get("runtimeManagerEventAt") or row.get("ts") or "").strip()
        keys.add((str(row.get("event_code") or "").strip(), occurred_at, _event_command_id(fields)))
    return keys


def _target_scene_dir(runtime_scene_service: Any, *, allow_recent_completed: bool) -> Path | None:
    resolver = getattr(runtime_scene_service, "_resolve_current_runtime_scene_dir", None)
    if callable(resolver):
        try:
            scene_dir = resolver()
        except Exception:
            scene_dir = None
        if scene_dir is not None:
            return Path(scene_dir)
    if not allow_recent_completed:
        return None
    recent_resolver = getattr(runtime_scene_service, "_resolve_recent_completed_runtime_scene_dir", None)
    if callable(recent_resolver):
        try:
            scene_dir = recent_resolver()
        except Exception:
            scene_dir = None
        if scene_dir is not None:
            return Path(scene_dir)
    return None


def _target_runtime_scene_id(runtime_scene_service: Any, *, allow_recent_completed: bool) -> str:
    scene_dir = _target_scene_dir(runtime_scene_service, allow_recent_completed=allow_recent_completed)
    if scene_dir is None:
        return ""
    try:
        manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    if isinstance(manifest, dict):
        scene_id = str(manifest.get("runtime_scene_id") or "").strip()
        if scene_id:
            return scene_id
    name = scene_dir.name
    if "__" in name:
        return name.rsplit("__", 1)[-1].strip()
    return name.strip()


def _event_command_id(payload: dict[str, Any]) -> str:
    for key in ("commandId", "runId", "run_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _parse_event_datetime(value: str) -> datetime | None:
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
    return parsed.astimezone(timezone.utc)
