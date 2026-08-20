"""Cross-language instances.json lock protocol v2.

Python and Electron must use the same on-disk shape:

- lockdir = ``<registry-file-name>.lockdir`` beside the registry
- claim = atomic ``mkdir`` then ``holder.json`` ``{pid, startedAt}``
- poll 10ms, timeout 5s
- holder ``startedAt`` older than 10s (or a lockdir with no valid holder
  after 100ms) may be broken, emitting ``launcher.registry.lock_stale_broken``
- release = recursive delete of the lockdir, only if we still own it
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

LOCKDIR_SUFFIX = ".lockdir"
HOLDER_FILE_NAME = "holder.json"
LOCK_POLL_SECONDS = 0.01
LOCK_TIMEOUT_SECONDS = 5.0
LOCK_STALE_SECONDS = 10.0
MISSING_HOLDER_GRACE_SECONDS = 0.1
LOCK_STALE_BROKEN_EVENT = "launcher.registry.lock_stale_broken"
_REMOVE_ATTEMPTS = 8
_REMOVE_RETRY_SECONDS = 0.01

LockEventEmitter = Callable[[str, dict[str, Any]], None]


class InstanceLockTimeoutError(TimeoutError):
    """Raised when the registry lockdir cannot be claimed before timeout."""


def instance_lockdir_path(registry_path: str | Path) -> Path:
    path = Path(registry_path)
    return path.with_name(f"{path.name}{LOCKDIR_SUFFIX}")


def holder_file_path(lockdir: str | Path) -> Path:
    return Path(lockdir) / HOLDER_FILE_NAME


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_timestamp(value: datetime | None = None) -> str:
    current = value or _utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    else:
        current = current.astimezone(UTC)
    return current.isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _default_emit_event(event_name: str, payload: dict[str, Any]) -> None:
    try:
        from core.runtime_manager.scene_logging import append_runtime_manager_file_event

        append_runtime_manager_file_event(event_name, payload, suppress_io_errors=True)
    except (OSError, TypeError, ValueError, RuntimeError, ImportError):
        return


def _remove_lockdir(lockdir: Path) -> None:
    for attempt in range(_REMOVE_ATTEMPTS):
        if not lockdir.exists():
            return
        try:
            shutil.rmtree(lockdir)
            return
        except OSError:
            if attempt >= _REMOVE_ATTEMPTS - 1:
                raise
            time.sleep(_REMOVE_RETRY_SECONDS)


def read_lock_holder(lockdir: str | Path) -> dict[str, Any] | None:
    path = holder_file_path(lockdir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        pid = int(payload.get("pid"))
    except (TypeError, ValueError):
        return None
    started_at = str(payload.get("startedAt") or "").strip()
    if pid <= 0 or not started_at:
        return None
    return {"pid": pid, "startedAt": started_at}


def write_lock_holder(lockdir: str | Path, *, pid: int, started_at: str) -> None:
    path = holder_file_path(lockdir)
    payload = {"pid": int(pid), "startedAt": str(started_at)}
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def plant_lockdir(
    registry_path: str | Path,
    *,
    pid: int,
    started_at: str | datetime,
) -> Path:
    """Create a lockdir without claiming (tests / crash-residue fixtures)."""

    lockdir = instance_lockdir_path(registry_path)
    lockdir.mkdir(parents=True, exist_ok=True)
    timestamp = started_at if isinstance(started_at, str) else _iso_timestamp(started_at)
    write_lock_holder(lockdir, pid=pid, started_at=timestamp)
    return lockdir


def _lockdir_age_seconds(lockdir: Path, *, now: datetime) -> float:
    try:
        mtime = lockdir.stat().st_mtime
    except OSError:
        return 0.0
    return max(0.0, now.timestamp() - mtime)


def _stale_reason(
    lockdir: Path,
    *,
    now: datetime,
    stale_seconds: float,
    missing_holder_grace_seconds: float,
) -> str | None:
    holder = read_lock_holder(lockdir)
    if holder is None:
        if _lockdir_age_seconds(lockdir, now=now) >= missing_holder_grace_seconds:
            return "missing_holder"
        return None
    started = _parse_timestamp(holder.get("startedAt"))
    if started is None:
        if _lockdir_age_seconds(lockdir, now=now) >= missing_holder_grace_seconds:
            return "invalid_holder"
        return None
    if now - started >= timedelta(seconds=stale_seconds):
        return "stale_started_at"
    return None


def _break_stale_lockdir(
    lockdir: Path,
    *,
    now: datetime,
    reason: str,
    emit_event: LockEventEmitter | None,
) -> None:
    holder = read_lock_holder(lockdir)
    previous_pid = holder.get("pid") if holder else None
    previous_started_at = str(holder.get("startedAt") or "") if holder else ""
    _remove_lockdir(lockdir)
    if emit_event is None:
        return
    emit_event(
        LOCK_STALE_BROKEN_EVENT,
        {
            "lockdir": str(lockdir),
            "previousPid": previous_pid,
            "previousStartedAt": previous_started_at,
            "brokenAt": _iso_timestamp(now),
            "reason": reason,
        },
    )


@contextmanager
def hold_instance_lock(
    registry_path: str | Path,
    *,
    timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
    stale_seconds: float = LOCK_STALE_SECONDS,
    poll_seconds: float = LOCK_POLL_SECONDS,
    missing_holder_grace_seconds: float = MISSING_HOLDER_GRACE_SECONDS,
    pid: int | None = None,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    emit_event: LockEventEmitter | None = _default_emit_event,
) -> Iterator[Path]:
    """Claim ``<registry>.lockdir`` until the context exits."""

    registry = Path(registry_path)
    registry.parent.mkdir(parents=True, exist_ok=True)
    lockdir = instance_lockdir_path(registry)
    owner_pid = int(os.getpid() if pid is None else pid)
    now_fn = clock or _utc_now
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    started_at = ""
    owned = False
    while True:
        try:
            lockdir.mkdir()
            started_at = _iso_timestamp(now_fn())
            write_lock_holder(lockdir, pid=owner_pid, started_at=started_at)
            owned = True
            break
        except FileExistsError:
            now = now_fn()
            reason = _stale_reason(
                lockdir,
                now=now,
                stale_seconds=stale_seconds,
                missing_holder_grace_seconds=missing_holder_grace_seconds,
            )
            if reason:
                _break_stale_lockdir(lockdir, now=now, reason=reason, emit_event=emit_event)
                continue
            if time.monotonic() >= deadline:
                raise InstanceLockTimeoutError(
                    f"Timed out acquiring instance registry lock: {lockdir}"
                ) from None
            sleep(max(0.0, float(poll_seconds)))
        except OSError:
            if time.monotonic() >= deadline:
                raise
            sleep(max(0.0, float(poll_seconds)))
    try:
        yield lockdir
    finally:
        if owned and started_at:
            holder = read_lock_holder(lockdir)
            if holder and holder.get("pid") == owner_pid and holder.get("startedAt") == started_at:
                _remove_lockdir(lockdir)


def _cmd_hold(args: argparse.Namespace) -> int:
    seconds = max(0.0, float(args.seconds))
    with hold_instance_lock(args.registry, timeout_seconds=args.timeout):
        sys.stdout.write(json.dumps({"status": "held", "pid": os.getpid()}, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        time.sleep(seconds)
    sys.stdout.write(json.dumps({"status": "released"}, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


def _cmd_wait_acquire(args: argparse.Namespace) -> int:
    sys.stdout.write(json.dumps({"status": "waiting"}, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    started = time.perf_counter()
    try:
        with hold_instance_lock(args.registry, timeout_seconds=args.timeout):
            waited_ms = (time.perf_counter() - started) * 1000.0
            sys.stdout.write(
                json.dumps({"ok": True, "waitedMs": round(waited_ms, 3)}, ensure_ascii=False) + "\n"
            )
            sys.stdout.flush()
            time.sleep(max(0.0, float(args.hold_seconds)))
    except InstanceLockTimeoutError as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return 2
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    lockdir = instance_lockdir_path(args.registry)
    payload = {
        "lockdir": str(lockdir),
        "exists": lockdir.exists(),
        "holder": read_lock_holder(lockdir),
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


def _cmd_plant_stale(args: argparse.Namespace) -> int:
    started_at = args.started_at or _iso_timestamp(
        _utc_now() - timedelta(seconds=LOCK_STALE_SECONDS + 1)
    )
    plant_lockdir(args.registry, pid=int(args.pid), started_at=started_at)
    sys.stdout.write(
        json.dumps(
            {"status": "planted", "lockdir": str(instance_lockdir_path(args.registry))},
            ensure_ascii=False,
        )
        + "\n"
    )
    sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="instances.json lock protocol v2 helper")
    sub = parser.add_subparsers(dest="command", required=True)

    hold = sub.add_parser("hold", help="Acquire the lock, print held, sleep, then release.")
    hold.add_argument("--registry", required=True)
    hold.add_argument("--seconds", type=float, default=1.0)
    hold.add_argument("--timeout", type=float, default=LOCK_TIMEOUT_SECONDS)
    hold.set_defaults(func=_cmd_hold)

    wait = sub.add_parser("wait-acquire", help="Wait for the lock, print waitedMs, optionally hold.")
    wait.add_argument("--registry", required=True)
    wait.add_argument("--timeout", type=float, default=LOCK_TIMEOUT_SECONDS)
    wait.add_argument("--hold-seconds", type=float, default=0.0)
    wait.set_defaults(func=_cmd_wait_acquire)

    inspect = sub.add_parser("inspect", help="Print lockdir existence and holder.")
    inspect.add_argument("--registry", required=True)
    inspect.set_defaults(func=_cmd_inspect)

    plant = sub.add_parser("plant-stale", help="Write a stale lockdir for interop tests.")
    plant.add_argument("--registry", required=True)
    plant.add_argument("--pid", type=int, default=1)
    plant.add_argument("--started-at", default="")
    plant.set_defaults(func=_cmd_plant_stale)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
