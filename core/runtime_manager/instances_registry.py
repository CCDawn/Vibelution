"""Global workbench instance registry (multi-project / multi-branch).

Each (project checkout, branch) worktree gets its own runtime-manager/daemon/
state under its directory. This registry is the only cross-project coordination
point: it maps instance ids to backend and control ports so separate worktrees
can run side by side without port collisions.

Product writer: Electron ``instanceRegistryStore`` (lock protocol v2).
Python ``mutate_registry`` / ``reconcile_registry`` remain for tests and leftover
HTTP. Status refresh must call ``preview_reconcile_registry`` and must not save.
The registry does not decide which checkout is main.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import time
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, TypeVar

from core.runtime_manager.instance_lock import (
    LOCK_TIMEOUT_SECONDS,
    InstanceLockTimeoutError,
    hold_instance_lock,
)
from core.runtime_manager.process_identity import (
    capture_process_identity,
    inspect_listener_identity,
    inspect_process_identity,
)

REGISTRY_SCHEMA_VERSION = 3
DEFAULT_BASE_PORT = 8000
DEFAULT_CONTROL_PORT = 8765
PORT_SCAN_LIMIT = 64
IN_FLIGHT_STATUSES = frozenset({"starting", "restarting", "stopping"})
PORT_LEASE_RECLAIMABLE = frozenset({"quarantined", "reclaimable"})
OWNER_LEASE_TTL_MS = 15_000
OWNER_LEASE_HEARTBEAT_MS = 5_000
START_SUPERVISOR_LOST_MESSAGE = "启动监督进程已退出且超过启动期限，启动未完成。"
ISOLATED_START_TIMEOUT_SECONDS = 180
_READ_RETRY_ATTEMPTS = 3
_READ_RETRY_DELAY_SECONDS = 0.05
_LOCK_TIMEOUT_SECONDS = LOCK_TIMEOUT_SECONDS
_CLEANUP_OBSERVATION_GRACE_SECONDS = 10.0

T = TypeVar("T")


class InstanceBusyError(RuntimeError):
    """Raised when a generation CAS / in-flight claim cannot proceed."""

    def __init__(self, instance_id: str, *, status: str = "", generation: int = 0) -> None:
        self.instance_id = str(instance_id or "")
        self.status = str(status or "")
        self.generation = int(generation or 0)
        self.code = "instance_busy"
        super().__init__(
            f"instance {self.instance_id} is busy "
            f"({self.status or 'in-flight'} generation={self.generation})"
        )


def instances_registry_path() -> Path:
    """%LOCALAPPDATA%\\Vibelution\\instances.json (falls back to user home)."""
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "Vibelution" / "instances.json"


def empty_registry() -> dict[str, Any]:
    return {"schemaVersion": REGISTRY_SCHEMA_VERSION, "instances": {}}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime:
    current = value or _utc_now()
    if current.tzinfo is None:
        return current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def _iso_timestamp(value: datetime | None = None) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _iso_timestamp_seconds(value: datetime | None = None) -> str:
    return _as_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _touch_registry(payload: dict[str, Any], *, now: datetime | None = None) -> None:
    payload["schemaVersion"] = REGISTRY_SCHEMA_VERSION
    payload["updatedAt"] = _iso_timestamp(now)


def _touch_entry(entry: dict[str, Any], *, now: datetime | None = None) -> None:
    entry["schemaVersion"] = REGISTRY_SCHEMA_VERSION
    entry["updatedAt"] = _iso_timestamp(now)


def load_registry() -> dict[str, Any]:
    path = instances_registry_path()
    for _ in range(_READ_RETRY_ATTEMPTS):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("instances"), dict):
                return payload
            return empty_registry()
        except FileNotFoundError:
            return empty_registry()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            time.sleep(_READ_RETRY_DELAY_SECONDS)
    return empty_registry()


def save_registry(registry: dict[str, Any]) -> None:
    path = instances_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(registry, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


@contextmanager
def registry_lock(*, timeout: float = _LOCK_TIMEOUT_SECONDS):
    """Serialize one registry read-modify-write cycle across processes."""

    try:
        with hold_instance_lock(instances_registry_path(), timeout_seconds=timeout):
            yield
    except InstanceLockTimeoutError as exc:
        raise TimeoutError(str(exc)) from exc


def mutate_registry(mutator: Callable[[dict[str, Any]], T]) -> T:
    """Load, mutate, and save the registry under the exclusive lock."""

    with registry_lock():
        payload = load_registry()
        result = mutator(payload)
        _touch_registry(payload)
        save_registry(payload)
        return result


def _normalize_instance_id(instance_id: str) -> str:
    normalized = str(instance_id or "").strip()
    if not normalized:
        raise ValueError("instance_id must not be empty")
    return normalized


def _ensure_entry(registry: dict[str, Any], instance_id: str) -> dict[str, Any]:
    instances = registry.setdefault("instances", {})
    entry = instances.get(instance_id)
    if not isinstance(entry, dict):
        entry = {}
        instances[instance_id] = entry
    return entry


def apply_upsert(
    payload: dict[str, Any],
    instance_id: str,
    fields: dict[str, Any],
    *,
    expected_generation: int | None = None,
    now: datetime | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Apply a field patch. Generation CAS silently discards stale writers."""

    wanted = _normalize_instance_id(instance_id)
    entry = _ensure_entry(payload, wanted)
    if expected_generation is not None and int(entry.get("generation") or 0) != int(expected_generation):
        return False, dict(entry)
    entry.update(fields)
    if "deadlineAt" in fields and "inFlightDeadlineAt" not in fields:
        entry["inFlightDeadlineAt"] = fields.get("deadlineAt")
    elif "inFlightDeadlineAt" in fields and "deadlineAt" not in fields:
        entry["deadlineAt"] = fields.get("inFlightDeadlineAt")
    _capture_entry_identities(entry, fields)
    _touch_entry(entry, now=now)
    return True, dict(entry)


def apply_record_spawn_pid(
    payload: dict[str, Any],
    instance_id: str,
    spawn_pid: int,
    expected_generation: int,
    *,
    now: datetime | None = None,
) -> tuple[bool, dict[str, Any]]:
    return apply_upsert(
        payload,
        instance_id,
        {"spawnPid": int(spawn_pid)},
        expected_generation=int(expected_generation),
        now=now,
    )


def apply_claim_start(
    payload: dict[str, Any],
    *,
    instance_id: str,
    project_root: str,
    branch: str = "",
    operation: str = "start",
    command_id: str,
    deadline_at: str,
    owner_pid: int,
    extra_used: set[int] | None = None,
    preferred_backend: int = DEFAULT_BASE_PORT,
    preferred_control: int = DEFAULT_CONTROL_PORT,
    host: str = "127.0.0.1",
    started_at: str | None = None,
    slot_fields: dict[str, Any] | None = None,
    owner_id: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """In-flight 409 + generation+1 + disjoint ports in one payload transaction."""

    wanted = _normalize_instance_id(instance_id)
    extra = {int(port) for port in (extra_used or set()) if int(port or 0) > 0}
    entry = _ensure_entry(payload, wanted)
    current_status = str(entry.get("status") or "").strip().lower()
    if bool(entry.get("cleanupInProgress")):
        raise InstanceBusyError(
            wanted,
            status="cleanup",
            generation=int(entry.get("generation") or 0),
        )
    if current_status in IN_FLIGHT_STATUSES:
        raise InstanceBusyError(
            wanted,
            status=current_status,
            generation=int(entry.get("generation") or 0),
        )
    backend = _allocate_backend_locked(
        payload,
        wanted,
        preferred_backend,
        host=host,
        extra_used=extra,
    )
    control = _allocate_control_locked(
        payload,
        wanted,
        preferred_control,
        host=host,
        extra_used=extra | {int(backend)},
    )
    status = "restarting" if operation == "restart" else "starting"
    generation = int(entry.get("generation") or 0) + 1
    owner = int(owner_pid or 0)
    stamp = _as_utc(now)
    entry.update(
        {
            "projectRoot": str(project_root or ""),
            "branch": str(branch or ""),
            "port": int(backend),
            "controlPort": int(control),
            "host": host,
            "url": f"http://127.0.0.1:{int(backend)}",
            "status": status,
            "desiredState": "open",
            "phase": status,
            "generation": generation,
            "commandId": str(command_id or ""),
            "deadlineAt": str(deadline_at),
            "inFlightDeadlineAt": str(deadline_at),
            "failureMessage": "",
            "spawnPid": 0,
            "windowPid": 0,
            "ownerPid": owner,
            "ownerLease": build_owner_lease(owner_id=owner_id, owner_pid=owner, now=stamp),
            "startedAt": str(started_at or deadline_at),
            **dict(slot_fields or {}),
        }
    )
    if owner > 0:
        _capture_entry_identities(entry, {"ownerPid": owner})
    _touch_entry(entry, now=now)
    return dict(entry)


def apply_claim_stop(
    payload: dict[str, Any],
    *,
    instance_id: str,
    project_root: str = "",
    command_id: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bump generation first so in-flight start observers cannot write back."""

    wanted = _normalize_instance_id(instance_id)
    entry = _ensure_entry(payload, wanted)
    generation = int(entry.get("generation") or 0) + 1
    entry["status"] = "stopping"
    entry["phase"] = "stopping"
    entry["desiredState"] = "closed"
    entry["generation"] = generation
    stop_deadline = _iso_timestamp_seconds(
        _as_utc(now) + timedelta(seconds=ISOLATED_START_TIMEOUT_SECONDS)
    )
    entry["deadlineAt"] = stop_deadline
    entry["inFlightDeadlineAt"] = stop_deadline
    normalized_command_id = str(command_id or "").strip()
    if normalized_command_id:
        entry["commandId"] = normalized_command_id
    entry["failureMessage"] = ""
    entry.pop("ownerLease", None)
    root = str(project_root or "").strip()
    if root not in {"", "."}:
        entry["projectRoot"] = root
    _touch_entry(entry, now=now)
    return dict(entry)


def apply_observe(
    payload: dict[str, Any],
    *,
    instance_id: str,
    operation: str,
    expected_generation: int = 0,
    message: str = "",
    now: datetime | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Generation CAS for supervisor observe-ready / observe-error."""

    wanted = str(instance_id or "").strip()
    instances = payload.setdefault("instances", {})
    entry = instances.get(wanted)
    if not isinstance(entry, dict):
        return False, {}
    expected = int(expected_generation or 0)
    current_generation = int(entry.get("generation") or 0)
    status = str(entry.get("status") or "").strip().lower()
    if expected > 0 and current_generation != expected:
        return False, dict(entry)
    if status not in {"starting", "restarting"}:
        return False, dict(entry)
    if operation == "observe-error":
        entry["status"] = "failed"
        entry["phase"] = "failed"
        entry["desiredState"] = str(entry.get("desiredState") or "open")
        entry["failureMessage"] = str(message or "隔离实例启动超时或 HTTP 未就绪。")
    else:
        entry["status"] = "steady"
        entry["phase"] = "steady"
        entry["desiredState"] = "open"
        entry["failureMessage"] = ""
    entry.pop("ownerLease", None)
    _touch_entry(entry, now=now)
    return True, dict(entry)


def apply_renew_owner_lease(
    payload: dict[str, Any],
    *,
    instance_id: str,
    owner_id: str,
    expected_generation: int = 0,
    now: datetime | None = None,
) -> tuple[bool, dict[str, Any]]:
    wanted = str(instance_id or "").strip()
    instances = payload.setdefault("instances", {})
    entry = instances.get(wanted)
    if not isinstance(entry, dict):
        return False, {}
    expected = int(expected_generation or 0)
    if expected > 0 and int(entry.get("generation") or 0) != expected:
        return False, dict(entry)
    status = str(entry.get("status") or "").strip().lower()
    if status not in {"starting", "restarting"}:
        return False, dict(entry)
    identity = str(owner_id or "").strip()
    current = owner_lease_of(entry)
    if current and current.get("ownerId") and identity and current["ownerId"] != identity:
        return False, dict(entry)
    entry["ownerLease"] = build_owner_lease(
        owner_id=identity or str((current or {}).get("ownerId") or ""),
        now=now,
    )
    _touch_entry(entry, now=now)
    return True, dict(entry)


def apply_reclaim_stale_in_flight_start(
    payload: dict[str, Any],
    *,
    instance_id: str,
    expected_generation: int | None = None,
    now: datetime | None = None,
    backend_alive: bool = False,
    backend_listening: bool = False,
    window_open: bool = False,
) -> tuple[bool, dict[str, Any]]:
    wanted = str(instance_id or "").strip()
    instances = payload.setdefault("instances", {})
    entry = instances.get(wanted)
    if not isinstance(entry, dict):
        return False, {}
    expected = int(expected_generation or 0)
    if expected > 0 and int(entry.get("generation") or 0) != expected:
        return False, dict(entry)
    if is_stale_in_flight_stop(entry, now=now):
        entry["status"] = "closed"
        entry["phase"] = "steady"
        entry["desiredState"] = "closed"
        entry["failureMessage"] = ""
        entry["spawnPid"] = 0
        entry["windowPid"] = 0
        entry["portLeaseStatus"] = "reclaimable"
        entry.pop("ownerLease", None)
        _touch_entry(entry, now=now)
        return True, dict(entry)
    if not is_stale_in_flight_start(
        entry,
        now=now,
        backend_alive=backend_alive,
        backend_listening=backend_listening,
        window_open=window_open,
    ):
        return False, dict(entry)
    entry["status"] = "failed"
    entry["phase"] = "failed"
    entry["failureMessage"] = START_SUPERVISOR_LOST_MESSAGE
    entry.pop("ownerLease", None)
    _touch_entry(entry, now=now)
    return True, dict(entry)


def upsert_instance(
    instance_id: str,
    *,
    expected_generation: int | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Create or update one instance entry, preserving unknown fields."""
    instance_id = _normalize_instance_id(instance_id)

    def mutator(payload: dict[str, Any]) -> dict[str, Any]:
        _applied, entry = apply_upsert(
            payload,
            instance_id,
            fields,
            expected_generation=expected_generation,
        )
        return entry

    return mutate_registry(mutator)


def record_spawn_pid(instance_id: str, spawn_pid: int, expected_generation: int) -> bool:
    """Write spawnPid only when generation still matches the claiming start."""

    def mutator(payload: dict[str, Any]) -> bool:
        applied, _entry = apply_record_spawn_pid(
            payload,
            instance_id,
            spawn_pid,
            expected_generation,
        )
        return applied

    return mutate_registry(mutator)


def _capture_entry_identities(entry: dict[str, Any], changed_fields: dict[str, Any]) -> None:
    pid_fields = (
        ("ownerPid", "owner"),
        ("spawnPid", "spawn"),
        ("backendPid", "backend"),
        ("controlPid", "control"),
    )
    for pid_field, prefix in pid_fields:
        if pid_field not in changed_fields:
            continue
        try:
            pid = int(changed_fields.get(pid_field) or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid <= 0:
            continue
        captured = capture_process_identity(pid)
        if pid_field == "spawnPid":
            entry["spawnPid"] = pid
            if captured:
                entry["spawnCreateTime"] = captured["createTime"]
                entry["spawnExecutable"] = captured["executable"]
            if int(entry.get("ownerPid") or 0) <= 0:
                entry["ownerPid"] = pid
                if captured:
                    entry["ownerCreateTime"] = captured["createTime"]
                    entry["ownerExecutable"] = captured["executable"]
            continue
        entry[f"{prefix}Pid"] = pid
        if captured:
            entry[f"{prefix}CreateTime"] = captured["createTime"]
            entry[f"{prefix}Executable"] = captured["executable"]


def list_instances() -> list[dict[str, Any]]:
    registry = load_registry()
    instances = registry.get("instances")
    if not isinstance(instances, dict):
        return []
    return [
        {"instanceId": instance_id, **(entry if isinstance(entry, dict) else {})}
        for instance_id, entry in sorted(instances.items())
    ]


def get_instance(instance_id: str) -> dict[str, Any]:
    instance_id = _normalize_instance_id(instance_id)
    registry = load_registry()
    entry = registry.get("instances", {}).get(instance_id)
    return dict(entry) if isinstance(entry, dict) else {}


def find_instance_by_project_root(project_root: str | Path) -> dict[str, Any]:
    target = _norm_path(project_root)
    if not target:
        return {}
    for entry in list_instances():
        if _norm_path(str(entry.get("projectRoot") or "")) == target:
            return dict(entry)
    return {}


def release_instance(instance_id: str) -> dict[str, Any]:
    """Remove an instance entry; returns the removed entry (or {})."""
    instance_id = _normalize_instance_id(instance_id)

    def mutator(payload: dict[str, Any]) -> dict[str, Any]:
        instances = payload.setdefault("instances", {})
        removed = instances.pop(instance_id, {})
        return dict(removed) if isinstance(removed, dict) else {}

    return mutate_registry(mutator)


def _norm_path(value: str | Path) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return os.path.normcase(os.path.normpath(text))


def _port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """True when nothing listens on the loopback port (no side effects)."""
    if int(port or 0) <= 0 or int(port) >= 65536:
        return False
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        probe.bind((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _entry_raw_pids(entry: dict[str, Any]) -> list[int]:
    pids: list[int] = []
    seen: set[int] = set()
    for key in ("ownerPid", "spawnPid", "backendPid", "controlPid"):
        try:
            pid = int(entry.get(key) or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid <= 0 or pid in seen:
            continue
        seen.add(pid)
        pids.append(pid)
    return pids


def _pid_is_present(pid: int) -> bool:
    """Fail-closed: unknown presence is treated as still occupied."""
    try:
        import psutil
    except ImportError:
        return True
    try:
        return bool(psutil.pid_exists(int(pid)))
    except (psutil.Error, OSError, TypeError, ValueError):
        return True


def _entry_holds_port_lease(entry: dict[str, Any]) -> bool:
    status = str(entry.get("portLeaseStatus") or "").strip().lower()
    return status not in PORT_LEASE_RECLAIMABLE


def _entry_identities(entry: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    identities: list[dict[str, Any]] = []
    complete = True
    seen_pids: set[int] = set()
    fields = (
        ("ownerPid", "ownerCreateTime", "ownerExecutable"),
        ("spawnPid", "spawnCreateTime", "spawnExecutable"),
        ("backendPid", "backendCreateTime", "backendExecutable"),
        ("controlPid", "controlCreateTime", "controlExecutable"),
    )
    for pid_field, created_field, executable_field in fields:
        try:
            pid = int(entry.get(pid_field) or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid <= 0 or pid in seen_pids:
            continue
        seen_pids.add(pid)
        created_value = entry.get(created_field)
        executable_value = entry.get(executable_field)
        if pid_field == "spawnPid":
            created_value = created_value or entry.get("ownerCreateTime")
            executable_value = executable_value or entry.get("ownerExecutable")
        try:
            create_time = float(created_value or 0)
        except (TypeError, ValueError):
            create_time = 0
        executable = str(executable_value or "").strip()
        if create_time <= 0 or not executable:
            complete = False
            continue
        identities.append({"pid": pid, "createTime": create_time, "executable": executable})
    if not seen_pids:
        complete = False
    return identities, complete and len(identities) == len(seen_pids)


def _deadline_expired(entry: dict[str, Any], now: datetime) -> bool:
    deadline = _parse_timestamp(entry.get("inFlightDeadlineAt") or entry.get("deadlineAt"))
    return bool(deadline is not None and deadline <= now)


def build_owner_lease(
    *,
    owner_id: str = "",
    owner_pid: int = 0,
    now: datetime | None = None,
) -> dict[str, str]:
    identity = str(owner_id or "").strip()
    if not identity and int(owner_pid or 0) > 0:
        identity = f"pid:{int(owner_pid)}"
    expires = _as_utc(now) + timedelta(milliseconds=OWNER_LEASE_TTL_MS)
    return {"ownerId": identity, "expiresAt": _iso_timestamp_seconds(expires)}


def owner_lease_of(entry: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(entry, dict):
        return None
    lease = entry.get("ownerLease")
    if not isinstance(lease, dict):
        return None
    owner_id = str(lease.get("ownerId") or "").strip()
    expires_at = str(lease.get("expiresAt") or "").strip()
    if not owner_id and not expires_at:
        return None
    return {"ownerId": owner_id, "expiresAt": expires_at}


def owner_lease_expired(entry: dict[str, Any] | None, now: datetime | None = None) -> bool:
    lease = owner_lease_of(entry)
    if lease is None or not lease.get("expiresAt"):
        return True
    expires = _parse_timestamp(lease.get("expiresAt"))
    if expires is None:
        return True
    return expires <= _as_utc(now)


def is_stale_in_flight_start(
    entry: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    backend_alive: bool = False,
    backend_listening: bool = False,
    window_open: bool = False,
) -> bool:
    if not isinstance(entry, dict) or not entry:
        return False
    status = str(entry.get("status") or "").strip().lower()
    if status not in {"starting", "restarting"}:
        return False
    if str(entry.get("desiredState") or "").strip().lower() != "open":
        return False
    if backend_alive or backend_listening or window_open:
        return False
    stamp = _as_utc(now)
    return _deadline_expired(entry, stamp) and owner_lease_expired(entry, stamp)


def is_stale_in_flight_stop(
    entry: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> bool:
    if not isinstance(entry, dict) or not entry:
        return False
    status = str(entry.get("status") or "").strip().lower()
    if status != "stopping":
        return False
    if str(entry.get("desiredState") or "").strip().lower() != "closed":
        return False
    stamp = _as_utc(now)
    return _deadline_expired(entry, stamp) and owner_lease_expired(entry, stamp)


_OPEN_REGISTRY_STATUSES = frozenset({"starting", "restarting", "running", "steady", "stopping"})
_OPEN_DESIRED_STATES = frozenset({"open", "opening"})
_LEFTOVER_OPEN_PHASES = frozenset({"starting", "restarting", "opening", "stopping", "failed"})


def _close_leftover_open_claim(entry: dict[str, Any], now: datetime) -> bool:
    """Close leftover claims for a missing worktree without deleting metadata.

    A missing path is already a completed close. Do not leave ``phase=failed``
    plus ``failureMessage=worktree_path_missing``: that projects as 需要处理,
    while unknown leftovers are diagnostic-only and have no Close action.
    """
    changed = False
    status = str(entry.get("status") or "").strip().lower()
    desired = str(entry.get("desiredState") or "").strip().lower()
    phase = str(entry.get("phase") or "").strip().lower()
    failure = str(entry.get("failureMessage") or "").strip()
    if status in _OPEN_REGISTRY_STATUSES or status == "failed":
        entry["status"] = "closed"
        changed = True
    if desired in _OPEN_DESIRED_STATES:
        entry["desiredState"] = "closed"
        changed = True
    if phase in _LEFTOVER_OPEN_PHASES:
        entry["phase"] = "steady"
        changed = True
    if failure:
        entry["failureMessage"] = ""
        changed = True
    if changed:
        _touch_entry(entry, now=now)
    return changed


def _cleanup_fingerprint(instance_id: str, entry: dict[str, Any], identities: list[dict[str, Any]]) -> str:
    facts = {
        "instanceId": instance_id,
        "projectRoot": _norm_path(str(entry.get("projectRoot") or "")),
        "ports": sorted(_entry_ports(entry)),
        "identities": sorted(identities, key=lambda item: int(item.get("pid") or 0)),
        "rawPids": sorted(_entry_raw_pids(entry)),
        "generation": int(entry.get("generation") or 0),
        "commandId": str(entry.get("commandId") or ""),
        "deadline": str(entry.get("inFlightDeadlineAt") or entry.get("deadlineAt") or ""),
    }
    return sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _reconcile_payload(
    payload: dict[str, Any],
    *,
    git_worktree_roots: Iterable[str | Path] | None,
    electron_window_instance_ids: Iterable[str],
    now: datetime,
    identity_inspector: Callable[[dict[str, Any]], dict[str, Any]],
    listener_inspector: Callable[[int, Iterable[dict[str, Any]]], dict[str, Any]],
    pid_existence_inspector: Callable[[int], bool] = _pid_is_present,
) -> tuple[dict[str, Any], bool]:
    inventory = None if git_worktree_roots is None else {_norm_path(root) for root in git_worktree_roots}
    window_ids = {str(instance_id) for instance_id in electron_window_instance_ids}
    instances = payload.get("instances")
    if not isinstance(instances, dict):
        instances = {}
        payload["instances"] = instances
    changed = False
    removed: list[str] = []
    projections: list[dict[str, Any]] = []
    worktree_dry_run: list[dict[str, Any]] = []
    pending_next: list[datetime] = []

    for raw_instance_id, raw_entry in list(instances.items()):
        instance_id = str(raw_instance_id)
        if not isinstance(raw_entry, dict):
            projections.append({"instanceId": instance_id, "classification": "unknown", "reasons": ["invalid_entry"]})
            continue
        entry = raw_entry
        project_root = str(entry.get("projectRoot") or "").strip()
        normalized_root = _norm_path(project_root)
        root_missing = bool(normalized_root) and not Path(project_root).exists()
        outside_inventory = inventory is not None and bool(normalized_root) and normalized_root not in inventory
        worktree_candidate = bool(normalized_root) and (root_missing or outside_inventory)
        if worktree_candidate:
            worktree_dry_run.append(
                {
                    "instanceId": instance_id,
                    "projectRoot": project_root,
                    "reason": "path_missing" if root_missing else "not_in_git_registry",
                    "action": "dry_run_only",
                }
            )

        identities, identities_complete = _entry_identities(entry)
        identity_results = [identity_inspector(identity) for identity in identities]
        identity_statuses = {str(result.get("status") or "unknown") for result in identity_results}
        all_inactive = bool(identity_results) and identity_statuses.issubset({"dead", "mismatch"})
        any_active = "match" in identity_statuses
        any_identity_unknown = "unknown" in identity_statuses
        raw_pids = _entry_raw_pids(entry)
        pids_all_missing = all(not pid_existence_inspector(pid) for pid in raw_pids)

        listener_results = [listener_inspector(port, identities) for port in sorted(_entry_ports(entry))]
        listener_statuses = {str(result.get("status") or "unknown") for result in listener_results}
        has_external_listener = "external" in listener_statuses
        has_owned_listener = "owned" in listener_statuses
        listener_unknown = "unknown" in listener_statuses
        window_open = instance_id in window_ids
        deadline_expired = _deadline_expired(entry, now)
        lease_status = str(entry.get("portLeaseStatus") or "").strip().lower()

        reasons: list[str] = []
        if has_external_listener:
            classification = "conflict"
            reasons.append("external_listener")
        elif not identities_complete or any_identity_unknown or listener_unknown:
            classification = "unknown"
            reasons.append("identity_or_listener_unverified")
        elif any_active or has_owned_listener:
            classification = "healthy"
            reasons.append("owned_runtime_active")
        elif window_open:
            classification = "stale"
            reasons.append("electron_window_open")
        elif worktree_candidate and all_inactive and not has_owned_listener and (deadline_expired or root_missing):
            classification = "orphan"
            reasons.append("safe_metadata_cleanup_candidate")
        else:
            classification = "stale"
            reasons.append("inactive_but_not_safe_to_remove")

        if (
            root_missing
            and not window_open
            and not any_active
            and not has_owned_listener
            and pids_all_missing
            and _close_leftover_open_claim(entry, now)
        ):
            changed = True
            reasons.append("closed_missing_worktree_claim")

        observation_kind = ""
        if classification == "orphan" and not window_open:
            observation_kind = "orphan"
        elif (
            classification == "unknown"
            and worktree_candidate
            and (deadline_expired or root_missing)
            and not window_open
            and not has_owned_listener
            and not has_external_listener
            and not listener_unknown
            and not any_active
            and pids_all_missing
        ):
            observation_kind = "quarantine_candidate"

        observation = entry.get("cleanupObservation")
        instance_next_reconcile_at = ""
        first_observed_at_text = ""
        fingerprint = _cleanup_fingerprint(instance_id, entry, identities)
        if observation_kind:
            stored_kind = ""
            if isinstance(observation, dict):
                stored_kind = str(observation.get("kind") or "")
                if not stored_kind and str(observation.get("classification") or "") == "orphan":
                    stored_kind = "orphan"
            first_observed_at = _parse_timestamp(
                observation.get("firstObservedAt") if isinstance(observation, dict) else None
            )
            same_observation = bool(
                stored_kind == observation_kind
                and isinstance(observation, dict)
                and observation.get("fingerprint") == fingerprint
                and first_observed_at is not None
            )
            grace_elapsed = bool(
                same_observation
                and first_observed_at is not None
                and (now - first_observed_at).total_seconds() >= _CLEANUP_OBSERVATION_GRACE_SECONDS
            )
            if grace_elapsed:
                if observation_kind == "orphan":
                    instances.pop(instance_id, None)
                    removed.append(instance_id)
                    changed = True
                else:
                    if lease_status not in PORT_LEASE_RECLAIMABLE:
                        entry["portLeaseStatus"] = "reclaimable"
                        entry["portLease"] = {
                            "status": "reclaimable",
                            "reason": "legacy_unknown_idle",
                            "quarantinedAt": _iso_timestamp(now),
                        }
                        if isinstance(observation, dict):
                            stored_observation = dict(observation)
                            stored_observation["confirmedAt"] = _iso_timestamp(now)
                            entry["cleanupObservation"] = stored_observation
                        lease_status = "reclaimable"
                        _touch_entry(entry, now=now)
                        changed = True
                    if _close_leftover_open_claim(entry, now):
                        changed = True
            elif not same_observation:
                next_at = now + timedelta(seconds=_CLEANUP_OBSERVATION_GRACE_SECONDS)
                public_classification = "orphan" if observation_kind == "orphan" else "unknown"
                entry["cleanupObservation"] = {
                    "kind": observation_kind,
                    "classification": public_classification,
                    "fingerprint": fingerprint,
                    "firstObservedAt": _iso_timestamp(now),
                    "nextReconcileAt": _iso_timestamp(next_at),
                }
                _touch_entry(entry, now=now)
                changed = True
                instance_next_reconcile_at = _iso_timestamp(next_at)
                first_observed_at_text = _iso_timestamp(now)
            elif first_observed_at is not None:
                instance_next_reconcile_at = _iso_timestamp(
                    first_observed_at + timedelta(seconds=_CLEANUP_OBSERVATION_GRACE_SECONDS)
                )
                first_observed_at_text = _iso_timestamp(first_observed_at)
        else:
            if isinstance(observation, dict):
                entry.pop("cleanupObservation", None)
                _touch_entry(entry, now=now)
                changed = True
            keep_reclaimable = (
                lease_status in PORT_LEASE_RECLAIMABLE
                and classification == "unknown"
                and worktree_candidate
                and not window_open
                and not has_owned_listener
                and not has_external_listener
                and not any_active
            )
            if lease_status in PORT_LEASE_RECLAIMABLE and not keep_reclaimable:
                entry.pop("portLeaseStatus", None)
                entry.pop("portLease", None)
                _touch_entry(entry, now=now)
                changed = True
                lease_status = ""

        if instance_next_reconcile_at:
            parsed_next = _parse_timestamp(instance_next_reconcile_at)
            if parsed_next is not None:
                pending_next.append(parsed_next)
        if not first_observed_at_text and isinstance(entry.get("cleanupObservation"), dict):
            first_observed_at_text = str(entry["cleanupObservation"].get("firstObservedAt") or "")

        projection: dict[str, Any] = {
            "instanceId": instance_id,
            "classification": classification,
            "reasons": reasons,
            "windowOpen": window_open,
            "listener": sorted(listener_statuses) or ["none"],
            "portLeaseStatus": lease_status or "held",
        }
        if first_observed_at_text:
            projection["firstObservedAt"] = first_observed_at_text
        if instance_next_reconcile_at:
            projection["nextReconcileAt"] = instance_next_reconcile_at
        projections.append(projection)

    summary: dict[str, Any] = {
        "observedAt": _iso_timestamp(now),
        "instances": projections,
        "removedInstanceIds": removed,
        "worktreeDryRun": worktree_dry_run,
    }
    if pending_next:
        summary["nextReconcileAt"] = _iso_timestamp(min(pending_next))
    return summary, changed


def preview_reconcile_registry(
    *,
    git_worktree_roots: Iterable[str | Path] | None,
    electron_window_instance_ids: Iterable[str] = (),
    now: datetime | None = None,
    identity_inspector: Callable[[dict[str, Any]], dict[str, Any]] = inspect_process_identity,
    listener_inspector: Callable[[int, Iterable[dict[str, Any]]], dict[str, Any]] = inspect_listener_identity,
    pid_existence_inspector: Callable[[int], bool] = _pid_is_present,
) -> dict[str, Any]:
    """Classify registry rows without writing ``instances.json``.

    Product status refresh is not a second registry writer. Electron
    ``instanceRegistryStore`` owns durable claim/observe/CAS updates.
    """
    observed_at = _as_utc(now)
    payload = load_registry()
    summary, _changed = _reconcile_payload(
        payload,
        git_worktree_roots=git_worktree_roots,
        electron_window_instance_ids=electron_window_instance_ids,
        now=observed_at,
        identity_inspector=identity_inspector,
        listener_inspector=listener_inspector,
        pid_existence_inspector=pid_existence_inspector,
    )
    return summary


def reconcile_registry(
    *,
    git_worktree_roots: Iterable[str | Path] | None,
    electron_window_instance_ids: Iterable[str] = (),
    now: datetime | None = None,
    identity_inspector: Callable[[dict[str, Any]], dict[str, Any]] = inspect_process_identity,
    listener_inspector: Callable[[int, Iterable[dict[str, Any]]], dict[str, Any]] = inspect_listener_identity,
    pid_existence_inspector: Callable[[int], bool] = _pid_is_present,
) -> dict[str, Any]:
    """Reconcile registry metadata and persist; leftover/test writer only."""
    observed_at = _as_utc(now)
    with registry_lock():
        payload = load_registry()
        summary, changed = _reconcile_payload(
            payload,
            git_worktree_roots=git_worktree_roots,
            electron_window_instance_ids=electron_window_instance_ids,
            now=observed_at,
            identity_inspector=identity_inspector,
            listener_inspector=listener_inspector,
            pid_existence_inspector=pid_existence_inspector,
        )
        if changed:
            _touch_registry(payload, now=observed_at)
            save_registry(payload)
        return summary


def _entry_ports(entry: dict[str, Any]) -> set[int]:
    used: set[int] = set()
    for key in ("port", "controlPort"):
        try:
            port = int(entry.get(key) or 0)
        except (TypeError, ValueError):
            port = 0
        if 0 < port < 65536:
            used.add(port)
    return used


def _registered_ports(registry: dict[str, Any], *, exclude_id: str = "") -> set[int]:
    used: set[int] = set()
    instances = registry.get("instances")
    if not isinstance(instances, dict):
        return used
    for instance_id, entry in instances.items():
        if exclude_id and str(instance_id) == exclude_id:
            continue
        if isinstance(entry, dict) and _entry_holds_port_lease(entry):
            used.update(_entry_ports(entry))
    return used


def _pick_port(
    preferred: int,
    used: set[int],
    default_base: int,
    host: str,
) -> int:
    base = int(preferred or default_base)
    if base <= 0 or base >= 65536:
        base = default_base
    for offset in range(max(1, PORT_SCAN_LIMIT)):
        candidate = base + offset
        if candidate >= 65536:
            candidate = default_base + (offset % 1000)
        if candidate <= 0 or candidate >= 65536:
            continue
        if candidate in used:
            continue
        if not _port_is_free(candidate, host=host):
            continue
        return int(candidate)
    raise RuntimeError(
        f"No free port found near {base} (scanned {PORT_SCAN_LIMIT} candidates)."
    )


def _existing_reusable_port(entry: dict[str, Any] | None, key: str, used: set[int], host: str) -> int:
    if not isinstance(entry, dict):
        return 0
    try:
        existing_port = int(entry.get(key) or 0)
    except (TypeError, ValueError):
        existing_port = 0
    if existing_port and existing_port not in used and _port_is_free(existing_port, host=host):
        return existing_port
    return 0


def _allocate_backend_locked(
    payload: dict[str, Any],
    instance_id: str,
    preferred: int,
    *,
    host: str,
    extra_used: set[int],
) -> int:
    used = _registered_ports(payload, exclude_id=instance_id) | extra_used
    entry = payload.get("instances", {}).get(instance_id)
    preferred_port = _existing_reusable_port(entry if isinstance(entry, dict) else None, "port", used, host) or preferred
    try:
        chosen = _pick_port(preferred_port, used, DEFAULT_BASE_PORT, host)
    except RuntimeError as exc:
        raise RuntimeError(
            f"No free backend port found near {preferred or DEFAULT_BASE_PORT} "
            f"for instance {instance_id} (scanned {PORT_SCAN_LIMIT} candidates)."
        ) from exc
    stored = _ensure_entry(payload, instance_id)
    stored["port"] = int(chosen)
    stored["host"] = host
    _touch_entry(stored)
    return int(chosen)


def _allocate_control_locked(
    payload: dict[str, Any],
    instance_id: str,
    preferred: int,
    *,
    host: str,
    extra_used: set[int],
) -> int:
    used = _registered_ports(payload, exclude_id=instance_id) | extra_used
    entry = payload.get("instances", {}).get(instance_id)
    preferred_port = (
        _existing_reusable_port(entry if isinstance(entry, dict) else None, "controlPort", used, host) or preferred
    )
    try:
        chosen = _pick_port(preferred_port, used, DEFAULT_CONTROL_PORT, host)
    except RuntimeError as exc:
        raise RuntimeError(
            f"No free control port found near {preferred or DEFAULT_CONTROL_PORT} "
            f"for instance {instance_id} (scanned {PORT_SCAN_LIMIT} candidates)."
        ) from exc
    stored = _ensure_entry(payload, instance_id)
    stored["controlPort"] = int(chosen)
    stored["host"] = host
    _touch_entry(stored)
    return int(chosen)


def allocate_backend_port(
    instance_id: str,
    preferred: int = DEFAULT_BASE_PORT,
    *,
    host: str = "127.0.0.1",
    extra_used: Iterable[int] | None = None,
) -> int:
    """Pick a free loopback backend port for an instance.

    Skips ports already claimed by other registered instances and ports with a
    live listener. The chosen port is recorded in the registry before return so
    concurrent allocators converge on disjoint ports.
    """
    instance_id = _normalize_instance_id(instance_id)
    extra = {int(port) for port in (extra_used or []) if int(port or 0) > 0}

    def mutator(payload: dict[str, Any]) -> int:
        return _allocate_backend_locked(payload, instance_id, preferred, host=host, extra_used=extra)

    return mutate_registry(mutator)


def allocate_control_port(
    instance_id: str,
    preferred: int = DEFAULT_CONTROL_PORT,
    *,
    host: str = "127.0.0.1",
    extra_used: Iterable[int] | None = None,
) -> int:
    """Pick a free loopback launcher-control port for an instance."""
    instance_id = _normalize_instance_id(instance_id)
    extra = {int(port) for port in (extra_used or []) if int(port or 0) > 0}

    def mutator(payload: dict[str, Any]) -> int:
        return _allocate_control_locked(payload, instance_id, preferred, host=host, extra_used=extra)

    return mutate_registry(mutator)


def allocate_instance_ports(
    instance_id: str,
    *,
    preferred_backend: int = DEFAULT_BASE_PORT,
    preferred_control: int = DEFAULT_CONTROL_PORT,
    host: str = "127.0.0.1",
    extra_used: Iterable[int] | None = None,
    git_worktree_roots: Iterable[str | Path] | None = None,
    electron_window_instance_ids: Iterable[str] = (),
    reconcile_now: datetime | None = None,
    identity_inspector: Callable[[dict[str, Any]], dict[str, Any]] = inspect_process_identity,
    listener_inspector: Callable[[int, Iterable[dict[str, Any]]], dict[str, Any]] = inspect_listener_identity,
    pid_existence_inspector: Callable[[int], bool] = _pid_is_present,
) -> tuple[int, int]:
    """Reconcile safely, then reserve a disjoint port pair under one lock."""
    instance_id = _normalize_instance_id(instance_id)
    extra = {int(port) for port in (extra_used or []) if int(port or 0) > 0}

    def mutator(payload: dict[str, Any]) -> tuple[int, int]:
        _reconcile_payload(
            payload,
            git_worktree_roots=git_worktree_roots,
            electron_window_instance_ids=electron_window_instance_ids,
            now=_as_utc(reconcile_now),
            identity_inspector=identity_inspector,
            listener_inspector=listener_inspector,
            pid_existence_inspector=pid_existence_inspector,
        )
        backend = _allocate_backend_locked(
            payload,
            instance_id,
            preferred_backend,
            host=host,
            extra_used=extra,
        )
        control = _allocate_control_locked(
            payload,
            instance_id,
            preferred_control,
            host=host,
            extra_used=extra | {int(backend)},
        )
        return int(backend), int(control)

    return mutate_registry(mutator)
