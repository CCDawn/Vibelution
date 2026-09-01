"""Shared persistent snapshot storage for manager-owned work runs."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from core.infrastructure import developer_sandbox

from .constants import PROJECT_ROOT, RUNTIME_MANAGER_DIR


WORK_RUNS_DIR = RUNTIME_MANAGER_DIR / "work_runs"
RECENT_RUN_IDS_LIMIT = 100
ACTIVE_RUN_IDS_LIMIT = 64
WRITE_RETRY_TIMEOUT_SECONDS = 5.0
READ_RETRY_ATTEMPTS = 5
READ_RETRY_DELAY_SECONDS = 0.05
# Index updates are read-modify-write across processes of store instances; a
# module-level reentrant lock keeps concurrent persist/delete RMW cycles from
# clobbering each other's active-run-id set within one process.
_STORE_LOCK = threading.RLock()
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ACTIVE_WORK_BLOCKING_STATUSES = {
    "",
    "active",
    "queued",
    "running",
    "stopping",
    "started",
    "in_progress",
    "pausing",
    "resuming",
    "force_stopping",
}


def default_work_runs_dir() -> Path:
    if developer_sandbox.is_developer_mode_enabled():
        sandbox_root = developer_sandbox.sandbox_root(PROJECT_ROOT, ensure=True)
        if sandbox_root is not None:
            return sandbox_root / ".runtime" / "runtime-manager" / "work_runs"
    return WORK_RUNS_DIR
_ACTIVE_WORK_NON_BLOCKING_STATUSES = {
    "cancelled",
    "closed",
    "completed",
    "done",
    "failed",
    "failed_provider",
    "failed_runtime",
    "idle",
    "needs_continue",
    "partial",
    "paused_limit",
    "ready",
    "routed",
    "stopped",
    "stopped_by_user",
    "stop_failed",
    "superseded",
}
STALE_SNAPSHOT_GRACE = timedelta(hours=6)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_run_kind(kind: str) -> str:
    normalized = str(kind or "").strip().lower()
    if not normalized or not _SAFE_NAME_RE.fullmatch(normalized):
        raise ValueError("Invalid work run kind.")
    if "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise ValueError("Invalid work run kind.")
    return normalized


def normalize_run_id(run_id: str) -> str:
    normalized = str(run_id or "").strip()
    if not normalized or not _SAFE_NAME_RE.fullmatch(normalized):
        raise ValueError("Invalid work run id.")
    if "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise ValueError("Invalid work run id.")
    return normalized


def _default_index() -> dict[str, Any]:
    now = _now_iso()
    return {
        "version": 1,
        "updatedAt": now,
        "activeRunId": "",
        "activeRunIds": [],
        "latestRunId": "",
        "recentRunIds": [],
    }


def _read_text_with_retry(path: Path) -> str:
    for attempt in range(READ_RETRY_ATTEMPTS):
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            if attempt + 1 >= READ_RETRY_ATTEMPTS:
                raise
            time.sleep(READ_RETRY_DELAY_SECONDS)
    raise OSError(f"Unable to read {path}")


def _corrupt_json_reason(text: str) -> str:
    if text and all(char == "\x00" for char in text):
        return "nul_bytes"
    if not str(text or "").strip():
        return "empty_json"
    if "\x00" in text and not text.replace("\x00", "").strip():
        return "nul_bytes"
    return "json_decode_error"


def _store_path_run_kind(path: Path) -> str:
    if path.name == "index.json":
        return path.parent.name
    if path.parent.name == "runs":
        return path.parent.parent.name
    return ""


def _store_path_run_id(path: Path) -> str:
    if path.parent.name == "runs" and path.suffix == ".json":
        return path.stem
    return ""


def _quarantine_corrupt_json(path: Path, *, reason: str, error: str = "") -> Path | None:
    if not path.exists():
        return None
    try:
        size_bytes = path.stat().st_size
    except OSError:
        size_bytes = 0
    timestamp = int(time.time() * 1000)
    target = path.with_name(f"{path.name}.corrupt-{timestamp}")
    suffix = 1
    while target.exists():
        target = path.with_name(f"{path.name}.corrupt-{timestamp}-{suffix}")
        suffix += 1
    try:
        os.replace(path, target)
    except OSError as exc:
        _record_work_run_event(
            "state",
            "work_run.store.corrupt_json_quarantine_failed",
            run_kind=_store_path_run_kind(path),
            run_id=_store_path_run_id(path),
            fields={
                "path": str(path),
                "reason": reason,
                "sizeBytes": size_bytes,
                "errorType": type(exc).__name__,
            },
            message="Work run store could not quarantine corrupt JSON.",
            outcome="failed",
            level="warning",
            lifecycle=True,
        )
        return None
    _record_work_run_event(
        "state",
        "work_run.store.corrupt_json_quarantined",
        run_kind=_store_path_run_kind(path),
        run_id=_store_path_run_id(path),
        fields={
            "path": str(path),
            "quarantinePath": str(target),
            "reason": reason,
            "sizeBytes": size_bytes,
            "errorType": error.split(":", 1)[0] if error else "",
        },
        message="Work run store quarantined corrupt JSON.",
        outcome="repaired",
        level="warning",
        lifecycle=True,
    )
    return target


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    last_text = ""
    last_error = ""
    for attempt in range(READ_RETRY_ATTEMPTS):
        try:
            last_text = _read_text_with_retry(path)
            payload = json.loads(last_text)
        except OSError:
            if attempt + 1 >= READ_RETRY_ATTEMPTS:
                return {}
            time.sleep(READ_RETRY_DELAY_SECONDS)
            continue
        except json.JSONDecodeError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 >= READ_RETRY_ATTEMPTS:
                _quarantine_corrupt_json(path, reason=_corrupt_json_reason(last_text), error=last_error)
                return {}
            time.sleep(READ_RETRY_DELAY_SECONDS)
            continue
        if isinstance(payload, dict):
            return payload
        _quarantine_corrupt_json(path, reason="non_object_json")
        return {}
    return {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        deadline = time.monotonic() + WRITE_RETRY_TIMEOUT_SECONDS
        attempt = 0
        while True:
            try:
                os.replace(temp_path, path)
                break
            except PermissionError:
                attempt += 1
                if time.monotonic() >= deadline:
                    raise
                time.sleep(min(0.05 * attempt, 0.25))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _run_sort_key(payload: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(payload.get("updatedAt") or ""),
        str(payload.get("startedAt") or ""),
        str(payload.get("runId") or ""),
    )


def _snapshot_lifecycle_signature(
    payload: dict[str, Any],
    *,
    active_run_id: str = "",
) -> tuple[str, ...]:
    return (
        str(payload.get("status") or "").strip(),
        str(payload.get("phase") or payload.get("currentPhase") or "").strip(),
        str(payload.get("runtimeStatus") or "").strip(),
        str(active_run_id or "").strip(),
        str(payload.get("finishedAt") or "").strip(),
        str(payload.get("errorType") or "").strip(),
        str(payload.get("error") or "").strip(),
    )


def active_work_status_blocks_lifecycle(status: str) -> bool:
    normalized = str(status or "").strip().lower()
    if normalized in _ACTIVE_WORK_NON_BLOCKING_STATUSES:
        return False
    if normalized in _ACTIVE_WORK_BLOCKING_STATUSES:
        return True
    return bool(normalized)


def active_work_payload_blocks_lifecycle(payload: dict[str, Any]) -> bool:
    if str(payload.get("finishedAt") or payload.get("endedAt") or "").strip():
        return False
    status = str(
        payload.get("status")
        or payload.get("currentPhase")
        or payload.get("phase")
        or payload.get("runtimeStatus")
        or ""
    ).strip().lower()
    return active_work_status_blocks_lifecycle(status)


def snapshot_run_id(payload: dict[str, Any]) -> str:
    return str(
        payload.get("runId")
        or payload.get("roundId")
        or payload.get("sessionId")
        or payload.get("id")
        or ""
    ).strip()


def snapshot_is_stale(payload: dict[str, Any]) -> bool:
    updated = _parse_datetime(str(payload.get("updatedAt") or payload.get("startedAt") or ""))
    if updated is None:
        return False
    return datetime.now(timezone.utc) - updated > STALE_SNAPSHOT_GRACE


def snapshot_is_current_or_fresh(payload: dict[str, Any], *, active_run_id: str = "") -> bool:
    run_id = snapshot_run_id(payload)
    if active_run_id and run_id == str(active_run_id or "").strip():
        return True
    return not snapshot_is_stale(payload)


def _snapshot_blocks_active_index(payload: dict[str, Any]) -> bool:
    return active_work_payload_blocks_lifecycle(payload)


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
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bounded_recent_run_ids(values: Any, latest_run_id: str = "") -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    raw_values = values if isinstance(values, list) else []
    for raw_run_id in [latest_run_id, *raw_values]:
        run_id = str(raw_run_id or "").strip()
        if not run_id or run_id in seen:
            continue
        try:
            normalized = normalize_run_id(run_id)
        except ValueError:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) >= RECENT_RUN_IDS_LIMIT:
            break
    return result


def _index_active_run_ids(index: dict[str, Any]) -> list[str]:
    """Return the raw active-run-id list from an index payload.

    Prefers the multi-slot ``activeRunIds`` field; falls back to the legacy
    single ``activeRunId`` value when the set field is missing or empty so
    indexes written before multi-slot support keep resolving their active run.
    """

    raw_values = index.get("activeRunIds")
    values = [str(item or "").strip() for item in raw_values] if isinstance(raw_values, list) else []
    if values:
        return values
    legacy_value = str(index.get("activeRunId") or "").strip()
    return [legacy_value] if legacy_value else []


def _bounded_active_run_ids(values: Any) -> list[str]:
    """Normalize an active-run-id set: safe ids only, ordered, bounded."""

    seen: set[str] = set()
    result: list[str] = []
    raw_values = values if isinstance(values, list) else [values]
    for raw_run_id in raw_values:
        run_id = str(raw_run_id or "").strip()
        if not run_id or run_id in seen:
            continue
        try:
            normalized = normalize_run_id(run_id)
        except ValueError:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) >= ACTIVE_RUN_IDS_LIMIT:
            break
    return result


def _bounded_snapshot_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 1
    return max(1, value)


def _record_work_run_event(
    phase: str,
    event_code: str,
    *,
    run_kind: str,
    run_id: str = "",
    status: str = "",
    fields: dict[str, Any] | None = None,
    message: str = "",
    outcome: str = "observed",
    level: str = "info",
    lifecycle: bool = False,
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        event_fields: dict[str, Any] = {
            "runKind": str(run_kind or "").strip(),
            "runId": str(run_id or "").strip(),
            "status": str(status or "").strip(),
        }
        if fields:
            event_fields.update(fields)
        record_runtime_scene_event(
            "work_run",
            phase,
            event_code,
            message=message or event_code,
            level=level,
            outcome=outcome,
            fields=event_fields,
            lifecycle=lifecycle,
        )
    except Exception:
        return


@dataclass(frozen=True)
class WorkRunStore:
    root: Path = field(default_factory=default_work_runs_dir)

    def kind_dir(self, run_kind: str) -> Path:
        return self.root / normalize_run_kind(run_kind)

    def runs_dir(self, run_kind: str) -> Path:
        return self.kind_dir(run_kind) / "runs"

    def index_path(self, run_kind: str) -> Path:
        return self.kind_dir(run_kind) / "index.json"

    def ensure_kind_dirs(self, run_kind: str) -> None:
        self.runs_dir(run_kind).mkdir(parents=True, exist_ok=True)

    def load_run_index(self, run_kind: str) -> dict[str, Any]:
        payload = _load_json(self.index_path(run_kind))
        if not payload:
            return _default_index()
        default = _default_index()
        default.update(payload)
        return default

    def save_run_index(
        self,
        run_kind: str,
        *,
        active_run_id: str = "",
        latest_run_id: str = "",
        recent_run_ids: Iterable[str] | None = None,
        active_run_ids: Iterable[str] | None = None,
        emit_event: bool = True,
    ) -> dict[str, Any]:
        with _STORE_LOCK:
            payload = self.load_run_index(run_kind)
            next_latest_run_id = str(latest_run_id or "").strip()
            next_recent_run_ids = _bounded_recent_run_ids(
                payload.get("recentRunIds") if recent_run_ids is None else recent_run_ids,
                latest_run_id=next_latest_run_id,
            )
            # ``active_run_ids`` carries the multi-slot set; when omitted the
            # legacy single-value argument defines the whole set (empty string
            # clears it), preserving pre-multi-slot callers.
            raw_active_run_ids = (
                list(active_run_ids)
                if active_run_ids is not None
                else [active_run_id]
            )
            next_active_run_ids = _bounded_active_run_ids(raw_active_run_ids)
            next_active_run_id = next_active_run_ids[-1] if next_active_run_ids else ""
            payload.update(
                {
                    "updatedAt": _now_iso(),
                    "activeRunId": next_active_run_id,
                    "activeRunIds": next_active_run_ids,
                    "latestRunId": next_latest_run_id,
                    "recentRunIds": next_recent_run_ids,
                }
            )
            self.ensure_kind_dirs(run_kind)
            _atomic_write_json(self.index_path(run_kind), payload)
        if emit_event:
            _record_work_run_event(
                "state",
                "work_run.index.saved",
                run_kind=run_kind,
                run_id=str(latest_run_id or next_active_run_id or "").strip(),
                fields={
                    "activeRunId": next_active_run_id,
                    "activeRunIds": next_active_run_ids,
                    "latestRunId": next_latest_run_id,
                    "recentRunCount": len(next_recent_run_ids),
                    "indexPath": str(self.index_path(run_kind)),
                },
                message="Work run index saved.",
                outcome="succeeded",
            )
        return payload

    def persist_snapshot(self, run_kind: str, snapshot: dict[str, Any], *, active_run_id: str = "") -> dict[str, Any]:
        raw_run_kind = str(run_kind or "").strip()
        raw_run_id = str(snapshot.get("runId") or "")
        raw_status = str(snapshot.get("status") or "").strip()
        if not raw_run_id.strip():
            _record_work_run_event(
                "state",
                "work_run.snapshot.rejected",
                run_kind=raw_run_kind,
                run_id="",
                status=raw_status,
                fields={"reason": "missing_run_id"},
                message="Work run snapshot rejected: missing runId.",
                outcome="rejected",
                level="warning",
                lifecycle=True,
            )
            raise ValueError("Work run snapshot is missing runId.")
        try:
            run_id = normalize_run_id(raw_run_id)
        except ValueError as exc:
            _record_work_run_event(
                "state",
                "work_run.snapshot.rejected",
                run_kind=raw_run_kind,
                run_id=raw_run_id.strip(),
                status=raw_status,
                fields={"reason": "invalid_run_id"},
                message="Work run snapshot rejected: invalid runId.",
                outcome="rejected",
                level="warning",
                lifecycle=True,
            )
            raise ValueError("Invalid work run id.") from exc
        payload = json.loads(json.dumps(snapshot, ensure_ascii=False))
        requested_active_run_id = str(active_run_id or "").strip()
        effective_active_run_id = requested_active_run_id
        if requested_active_run_id == run_id and not _snapshot_blocks_active_index(snapshot):
            effective_active_run_id = ""
        with _STORE_LOCK:
            previous_payload = self.load_snapshot(run_kind, run_id)
            previous_signature = (
                _snapshot_lifecycle_signature(previous_payload, active_run_id=effective_active_run_id)
                if previous_payload
                else ()
            )
            current_signature = _snapshot_lifecycle_signature(payload, active_run_id=effective_active_run_id)
            current_index = self.load_run_index(run_kind)
            current_active_run_ids = _bounded_active_run_ids(_index_active_run_ids(current_index))
            # Multi-slot semantics: this persist only mutates this run's own
            # membership. Marking this run active adds it; a terminal or
            # non-active declaration removes just this run so concurrent runs
            # keep their own active marks.
            next_active_run_ids = list(current_active_run_ids)
            if effective_active_run_id == run_id:
                if run_id not in next_active_run_ids:
                    next_active_run_ids.append(run_id)
            else:
                next_active_run_ids = [item for item in next_active_run_ids if item != run_id]
            if effective_active_run_id and effective_active_run_id != run_id and effective_active_run_id not in next_active_run_ids:
                next_active_run_ids.append(effective_active_run_id)
            next_active_run_id = next_active_run_ids[-1] if next_active_run_ids else ""
            current_recent_run_ids = _bounded_recent_run_ids(current_index.get("recentRunIds"))
            index_already_current = (
                current_active_run_ids == next_active_run_ids
                and str(current_index.get("latestRunId") or "").strip() == run_id
                and bool(current_recent_run_ids)
                and current_recent_run_ids[0] == run_id
            )
            if previous_payload == payload:
                if not index_already_current:
                    self.save_run_index(
                        run_kind,
                        active_run_ids=next_active_run_ids,
                        latest_run_id=run_id,
                        emit_event=False,
                    )
                return payload
            self.ensure_kind_dirs(run_kind)
            _atomic_write_json(self.runs_dir(run_kind) / f"{run_id}.json", payload)
            saved_index = self.save_run_index(run_kind, active_run_ids=next_active_run_ids, latest_run_id=run_id, emit_event=False)
        status = str(payload.get("status") or "").strip()
        phase = str(payload.get("phase") or payload.get("currentPhase") or "").strip()
        lifecycle_status = status in {
            "queued",
            "running",
            "paused",
            "stopping",
            "done",
            "completed",
            "partial",
            "needs_continue",
            "paused_limit",
            "stopped",
            "stopped_by_user",
            "force_stopping",
            "stop_failed",
            "failed",
            "failed_provider",
            "failed_runtime",
            "cancelled",
            "superseded",
        }
        lifecycle_changed = previous_signature != current_signature
        _record_work_run_event(
            "state",
            "work_run.snapshot.persisted",
            run_kind=run_kind,
            run_id=run_id,
            status=status,
            fields={
                "phase": phase,
                "activeRunId": effective_active_run_id,
                "requestedActiveRunId": requested_active_run_id,
                "runtimeStatus": str(payload.get("runtimeStatus") or "").strip(),
                "updatedAt": str(payload.get("updatedAt") or "").strip(),
                "finishedAt": str(payload.get("finishedAt") or "").strip(),
                "errorType": str(payload.get("errorType") or "").strip(),
                "error": str(payload.get("error") or "").strip(),
                "recentRunCount": len(saved_index.get("recentRunIds") or []),
                "snapshotPath": str(self.runs_dir(run_kind) / f"{run_id}.json"),
            },
            message=f"Work run snapshot persisted: {run_kind}/{run_id} {status or 'unknown'}",
            outcome="succeeded",
            level="warning" if status == "partial" else "info",
            lifecycle=lifecycle_status and (lifecycle_changed or status == "failed"),
        )
        return payload

    def load_snapshot(self, run_kind: str, run_id: str) -> dict[str, Any] | None:
        try:
            normalized = normalize_run_id(run_id)
        except ValueError:
            return None
        payload = _load_json(self.runs_dir(run_kind) / f"{normalized}.json")
        return payload or None

    def load_active_run_ids(self, run_kind: str) -> list[str]:
        """Return the active-run-id set for a kind, newest mark last."""

        return _bounded_active_run_ids(_index_active_run_ids(self.load_run_index(run_kind)))

    def load_active_snapshot(self, run_kind: str) -> dict[str, Any] | None:
        """Return the most recent resolvable active snapshot for a kind."""

        for run_id in reversed(self.load_active_run_ids(run_kind)):
            payload = self.load_snapshot(run_kind, run_id)
            if payload is not None:
                return payload
        return None

    def load_active_snapshots(self, run_kind: str) -> list[dict[str, Any]]:
        """Return every resolvable active snapshot, oldest mark first."""

        snapshots: list[dict[str, Any]] = []
        for run_id in self.load_active_run_ids(run_kind):
            payload = self.load_snapshot(run_kind, run_id)
            if payload is not None:
                snapshots.append(payload)
        return snapshots

    def load_active_snapshot_for_run(self, run_kind: str, run_id: str) -> dict[str, Any] | None:
        """Return the active snapshot of one run, or None when not marked active."""

        try:
            normalized = normalize_run_id(run_id)
        except ValueError:
            return None
        if normalized not in self.load_active_run_ids(run_kind):
            return None
        return self.load_snapshot(run_kind, normalized)

    def load_latest_snapshot(self, run_kind: str) -> dict[str, Any] | None:
        latest_run_id = str(self.load_run_index(run_kind).get("latestRunId") or "").strip()
        if latest_run_id:
            payload = self.load_snapshot(run_kind, latest_run_id)
            if payload is not None:
                return payload

        candidates = self.list_snapshots(run_kind)
        if not candidates:
            return None
        return max(candidates, key=_run_sort_key)

    def list_snapshots(self, run_kind: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        runs_dir = self.runs_dir(run_kind)
        if not runs_dir.exists():
            return []
        bounded_limit = _bounded_snapshot_limit(limit)
        if bounded_limit is not None:
            index = self.load_run_index(run_kind)
            raw_recent_run_ids = index.get("recentRunIds")
            index_recent_run_ids = _bounded_recent_run_ids(raw_recent_run_ids)[:bounded_limit]
            if index_recent_run_ids:
                snapshots: list[dict[str, Any]] = []
                for run_id in index_recent_run_ids:
                    payload = self.load_snapshot(run_kind, run_id)
                    if payload:
                        snapshots.append(payload)
                return snapshots[:bounded_limit]
        snapshots: list[dict[str, Any]] = []
        for path in sorted(runs_dir.glob("*.json")):
            payload = _load_json(path)
            if payload:
                snapshots.append(payload)
        if bounded_limit is None:
            return snapshots
        return sorted(snapshots, key=_run_sort_key, reverse=True)[:bounded_limit]

    def list_lifecycle_candidate_snapshots(self, run_kind: str) -> list[dict[str, Any]]:
        """Load snapshots that can still block a destructive lifecycle action.

        The active id and bounded recent index are always loaded for compatibility
        with restored stores whose file mtimes may not reflect payload timestamps.
        Other historical files are only parsed while their filesystem mtime is
        inside the same grace window used by ``snapshot_is_stale``.
        """

        runs_dir = self.runs_dir(run_kind)
        if not runs_dir.exists():
            return []
        index = self.load_run_index(run_kind)
        active_run_ids = _bounded_active_run_ids(_index_active_run_ids(index))
        candidate_run_ids: list[str] = []
        seen: set[str] = set()
        for run_id in [*active_run_ids, *_bounded_recent_run_ids(index.get("recentRunIds"))]:
            if run_id and run_id not in seen:
                seen.add(run_id)
                candidate_run_ids.append(run_id)
        fresh_run_ids: list[str] = []
        fresh_cutoff = time.time() - STALE_SNAPSHOT_GRACE.total_seconds()
        with os.scandir(runs_dir) as entries:
            for entry in entries:
                if not entry.name.endswith(".json"):
                    continue
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    pass
                try:
                    run_id = normalize_run_id(Path(entry.name).stem)
                except ValueError:
                    continue
                if run_id in seen:
                    continue
                try:
                    is_fresh = entry.stat(follow_symlinks=False).st_mtime >= fresh_cutoff
                except OSError:
                    is_fresh = True
                if not is_fresh:
                    continue
                seen.add(run_id)
                fresh_run_ids.append(run_id)

        snapshots: list[dict[str, Any]] = []
        for run_id in [*candidate_run_ids, *sorted(fresh_run_ids)]:
            payload = self.load_snapshot(run_kind, run_id)
            if payload:
                snapshots.append(payload)
        return snapshots

    def delete_snapshot(self, run_kind: str, run_id: str) -> dict[str, Any]:
        normalized = normalize_run_id(run_id)
        runs_dir = self.runs_dir(run_kind)
        target = runs_dir / f"{normalized}.json"
        with _STORE_LOCK:
            index = self.load_run_index(run_kind)
            active_run_ids = _bounded_active_run_ids(_index_active_run_ids(index))
            latest_run_id = str(index.get("latestRunId") or "").strip()
            existed = target.exists()

            try:
                target.unlink(missing_ok=True)
            except OSError:
                if target.exists():
                    raise

            cleared_active = normalized in active_run_ids
            cleared_latest = latest_run_id == normalized
            next_active_run_ids = [item for item in active_run_ids if item != normalized]
            next_active_id = next_active_run_ids[-1] if next_active_run_ids else ""
            next_latest_id = latest_run_id
            next_recent_run_ids = [
                item
                for item in _bounded_recent_run_ids(index.get("recentRunIds"))
                if item != normalized
            ]

            if cleared_latest:
                candidates: list[dict[str, Any]] = []
                for path in sorted(runs_dir.glob("*.json")):
                    if path.name == target.name:
                        continue
                    payload = _load_json(path)
                    if payload:
                        candidates.append(payload)
                next_latest_id = str(max(candidates, key=_run_sort_key).get("runId") or "") if candidates else ""

            if existed or cleared_active or cleared_latest:
                self.save_run_index(
                    run_kind,
                    active_run_ids=next_active_run_ids,
                    latest_run_id=next_latest_id,
                    recent_run_ids=next_recent_run_ids,
                )

        _record_work_run_event(
            "state",
            "work_run.snapshot.deleted",
            run_kind=run_kind,
            run_id=normalized,
            fields={
                "deleted": existed,
                "clearedActive": cleared_active,
                "clearedLatest": cleared_latest,
                "activeRunId": next_active_id,
                "latestRunId": next_latest_id,
                "snapshotPath": str(target),
            },
            message=f"Work run snapshot deleted: {run_kind}/{normalized}",
            outcome="succeeded" if existed else "skipped",
            lifecycle=True,
        )
        return {
            "deleted": existed,
            "runId": normalized,
            "clearedActive": cleared_active,
            "clearedLatest": cleared_latest,
            "activeRunId": next_active_id,
            "latestRunId": next_latest_id,
        }

    def clear(self, run_kinds: Iterable[str] | None = None) -> None:
        if run_kinds is None:
            if not self.root.exists():
                return
            run_kinds = [path.name for path in self.root.iterdir() if path.is_dir()]
        for run_kind in run_kinds:
            index_path = self.index_path(run_kind)
            paths = [index_path, *self.runs_dir(run_kind).glob("*.json")]
            for path in paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    continue


def build_work_run_summary(store: WorkRunStore | None = None, kinds: Iterable[str] | None = None) -> dict[str, Any]:
    current_store = store or WorkRunStore()
    selected_kinds = list(kinds or [])
    if not selected_kinds and current_store.root.exists():
        selected_kinds = [path.name for path in sorted(current_store.root.iterdir()) if path.is_dir()]
    return {
        normalize_run_kind(kind): {
            "active": current_store.load_active_snapshot(kind),
            "latest": current_store.load_latest_snapshot(kind),
        }
        for kind in selected_kinds
    }
