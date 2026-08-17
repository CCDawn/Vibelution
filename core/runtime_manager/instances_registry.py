"""Global workbench instance registry (multi-project / multi-branch).

Each (project checkout, branch) worktree gets its own runtime-manager/daemon/
state under its directory. This registry is the only cross-project coordination
point: it maps instance ids to backend and control ports so separate worktrees
can run side by side without port collisions.

Writers: Launcher lifecycle actions. Readers: daemon observation, tray, CLI.
All writes take ``instances.json.lock`` then replace the payload atomically so
concurrent allocators and generation CAS cannot interleave. The registry does
not decide which checkout is main.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import time
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

REGISTRY_SCHEMA_VERSION = 1
DEFAULT_BASE_PORT = 8000
DEFAULT_CONTROL_PORT = 8765
PORT_SCAN_LIMIT = 64
IN_FLIGHT_STATUSES = frozenset({"starting", "restarting", "stopping"})
_READ_RETRY_ATTEMPTS = 3
_READ_RETRY_DELAY_SECONDS = 0.05
_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_POLL_SECONDS = 0.01

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

    path = instances_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            if _try_lock_handle(handle):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out acquiring instance registry lock: {lock_path}")
            time.sleep(_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            _unlock_handle(handle)


def mutate_registry(mutator: Callable[[dict[str, Any]], T]) -> T:
    """Load, mutate, and save the registry under the exclusive lock."""

    with registry_lock():
        payload = load_registry()
        result = mutator(payload)
        save_registry(payload)
        return result


def _try_lock_handle(handle: Any) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return False
    return True


def _unlock_handle(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


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


def upsert_instance(instance_id: str, **fields: Any) -> dict[str, Any]:
    """Create or update one instance entry, preserving unknown fields."""
    instance_id = _normalize_instance_id(instance_id)

    def mutator(payload: dict[str, Any]) -> dict[str, Any]:
        entry = _ensure_entry(payload, instance_id)
        entry.update(fields)
        return dict(entry)

    return mutate_registry(mutator)


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
        if isinstance(entry, dict):
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
) -> tuple[int, int]:
    """Reserve a disjoint backend + control port pair for one instance."""
    instance_id = _normalize_instance_id(instance_id)
    extra = {int(port) for port in (extra_used or []) if int(port or 0) > 0}

    def mutator(payload: dict[str, Any]) -> tuple[int, int]:
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
