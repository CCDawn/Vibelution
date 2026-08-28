"""Durable, team-scoped maintenance fence for Challenge Cup reset operations.

The reset workflow must stop accepting *new* Challenge Cup work before it
starts draining existing work.  This module owns that small coordination
boundary.  It deliberately stores only the active fence identity (not a copy
of the reset inventory) under the canonical research-workflow data root and
uses an atomic replace for crash-safe persistence.

The fence is intentionally narrower than a process/global lock:

* only ``research-team`` can acquire, read, or release it;
* an existing fence is idempotent for the same ``purgePlanId`` and
  ``inventoryHash`` and conflicts with every other identity;
* write guards only reject work created after the fence was acquired.  Work
  that was already accepted is allowed to drain and is not force-stopped.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from core.infrastructure.process_liveness import is_pid_alive

from .atomic_fs import atomic_write_text
from .paths import research_workflow_data_root

RESEARCH_TEAM_ID = "research-team"
FENCE_KIND = "challenge_cup_maintenance"
SCHEMA_VERSION = 1
# A reset is a bounded destructive operation, but it can legitimately span
# several worker passes.  The lease is deliberately much longer than the
# graph worker's retry delay.
DEFAULT_FENCE_TTL_MS = 15 * 60 * 1000
MAINTENANCE_FENCE_TTL_MS = DEFAULT_FENCE_TTL_MS
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOCK = threading.RLock()


class ChallengeCupMaintenanceError(RuntimeError):
    """Base error for the governed Challenge Cup maintenance boundary."""

    def __init__(self, message: str, *, code: str = "challenge_cup_maintenance"):
        self.code = str(code or "challenge_cup_maintenance")
        super().__init__(message)


class ChallengeCupMaintenanceScopeError(ChallengeCupMaintenanceError):
    """Raised when a caller tries to use this fence for another team."""

    def __init__(self) -> None:
        super().__init__(
            "challenge_cup_maintenance is only available for the governed research team.",
            code="challenge_cup_maintenance_scope",
        )


class ChallengeCupMaintenanceConflictError(ChallengeCupMaintenanceError):
    """Raised when an active fence belongs to another reset identity."""

    def __init__(self, *, operation: str = "acquire") -> None:
        # Do not include the competing plan or inventory hash in the message:
        # those are reset inventory facts and are not needed to diagnose the
        # coordination failure.
        super().__init__(
            f"challenge_cup_maintenance fence conflict during {operation}; "
            "the active reset identity must be drained or released first.",
            code="challenge_cup_maintenance_conflict",
        )


class ChallengeCupMaintenanceActiveError(ChallengeCupMaintenanceError):
    """Raised when new work is attempted while the fence is active."""

    def __init__(self, *, operation: str) -> None:
        safe_operation = _safe_operation(operation)
        super().__init__(
            f"challenge_cup_maintenance fence is active; new {safe_operation} is blocked.",
            code="challenge_cup_maintenance_active",
        )


class ChallengeCupMaintenanceCorruptError(ChallengeCupMaintenanceError):
    """Raised when the persisted fence cannot be trusted."""

    def __init__(self, message: str = "challenge_cup_maintenance fence is corrupt") -> None:
        super().__init__(message, code="challenge_cup_maintenance_corrupt")


def _safe_operation(value: Any) -> str:
    text = str(value or "write").strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "_", text)[:80]
    return text or "write"


def _target_team_id(team_id: Any) -> str:
    normalized = str(team_id or "").strip()
    if normalized != RESEARCH_TEAM_ID:
        raise ChallengeCupMaintenanceScopeError()
    return normalized


def _optional_target_team_id(team_id: Any) -> str:
    """Return the team id for a write guard without affecting other teams."""

    return str(team_id or "").strip()


def _required_text(value: Any, *, field: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_length:
        raise ChallengeCupMaintenanceError(
            f"challenge_cup_maintenance requires a valid {field}.",
            code="challenge_cup_maintenance_invalid_request",
        )
    return text


def _inventory_hash(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not _HEX_SHA256.fullmatch(text):
        raise ChallengeCupMaintenanceError(
            "challenge_cup_maintenance requires a SHA-256 inventoryHash.",
            code="challenge_cup_maintenance_invalid_request",
        )
    return text


def _utc_now() -> tuple[str, int]:
    now = datetime.now(UTC)
    return (
        now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        int(now.timestamp() * 1000),
    )


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso_from_ms(value: int) -> str:
    """Format a millisecond clock value without depending on local time."""

    return (
        datetime.fromtimestamp(int(value) / 1000, UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _clock_ms(value: Any | None) -> int:
    if value is None:
        return _now_ms()
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ChallengeCupMaintenanceError(
            "challenge_cup_maintenance requires a valid nowMs.",
            code="challenge_cup_maintenance_invalid_request",
        ) from exc
    if normalized <= 0:
        raise ChallengeCupMaintenanceError(
            "challenge_cup_maintenance requires a positive nowMs.",
            code="challenge_cup_maintenance_invalid_request",
        )
    return normalized


def _ttl_ms(value: Any) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ChallengeCupMaintenanceError(
            "challenge_cup_maintenance requires a valid ttlMs.",
            code="challenge_cup_maintenance_invalid_request",
        ) from exc
    if normalized <= 0:
        raise ChallengeCupMaintenanceError(
            "challenge_cup_maintenance requires a positive ttlMs.",
            code="challenge_cup_maintenance_invalid_request",
        )
    return normalized


def _owner_pid(
    value: Any | None,
    *,
    default_current: bool = False,
    require_positive: bool = False,
) -> int:
    if value is None and default_current:
        return int(os.getpid())
    try:
        normalized = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ChallengeCupMaintenanceError(
            "challenge_cup_maintenance requires a valid ownerPid.",
            code="challenge_cup_maintenance_invalid_request",
        ) from exc
    if normalized < 0 or (require_positive and normalized <= 0):
        raise ChallengeCupMaintenanceError(
            "challenge_cup_maintenance requires a positive ownerPid."
            if require_positive
            else "challenge_cup_maintenance requires a non-negative ownerPid.",
            code="challenge_cup_maintenance_invalid_request",
        )
    return normalized


def _default_owner_alive(pid: int) -> bool:
    """Return process liveness while treating probe permission as alive.

    A failed liveness probe is not permission to drop a destructive fence.
    The shared helper keeps that stance: on Windows it answers via kernel32
    instead of ``os.kill(pid, 0)`` (which raises for dead *and* live pids
    alike in console-less processes, wrongly releasing the fence), and
    ``ACCESS_DENIED``/``PermissionError`` remain alive, matching the other
    local process-lease implementations in this repository.
    """

    return is_pid_alive(int(pid or 0))


def _owner_alive_value(
    active: Mapping[str, Any],
    owner_alive: Callable[[int], bool | None] | None,
) -> bool | None:
    """Resolve owner liveness; ``None`` means unknown and stays fail-closed."""

    try:
        pid = int(active.get("ownerPid") or 0)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    probe = owner_alive or _default_owner_alive
    try:
        result = probe(pid)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if result is None:
        return None
    return bool(result)


def _fence_path() -> Path:
    return Path(research_workflow_data_root()) / f"{FENCE_KIND}.json"


def _read_active_fence() -> dict[str, Any] | None:
    path = _fence_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChallengeCupMaintenanceCorruptError() from exc
    if not isinstance(raw, Mapping) or raw.get("schemaVersion") != SCHEMA_VERSION:
        raise ChallengeCupMaintenanceCorruptError()
    if raw.get("kind") != FENCE_KIND:
        raise ChallengeCupMaintenanceCorruptError()
    active = raw.get("activeFence")
    if active is None:
        return None
    if not isinstance(active, Mapping):
        raise ChallengeCupMaintenanceCorruptError()
    required = ("teamId", "purgePlanId", "inventoryHash", "acquiredAt", "acquiredAtMs")
    if any(key not in active for key in required):
        raise ChallengeCupMaintenanceCorruptError()
    if str(active.get("teamId") or "").strip() != RESEARCH_TEAM_ID:
        raise ChallengeCupMaintenanceCorruptError()
    # Reuse the request validators as a fail-closed read validation.  This
    # avoids treating a hand-edited marker as an active authority.
    plan_id = _required_text(active.get("purgePlanId"), field="purgePlanId", max_length=200)
    inventory_hash = _inventory_hash(active.get("inventoryHash"))
    acquired_at = _required_text(active.get("acquiredAt"), field="acquiredAt", max_length=80)
    try:
        acquired_at_ms = int(active.get("acquiredAtMs"))
    except (TypeError, ValueError) as exc:
        raise ChallengeCupMaintenanceCorruptError() from exc
    if acquired_at_ms <= 0:
        raise ChallengeCupMaintenanceCorruptError()
    normalized: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": FENCE_KIND,
        "teamId": RESEARCH_TEAM_ID,
        "purgePlanId": plan_id,
        "inventoryHash": inventory_hash,
        "acquiredAt": acquired_at,
        "acquiredAtMs": acquired_at_ms,
        "acquiredBy": str(active.get("acquiredBy") or "system").strip()[:160] or "system",
    }
    # V1 fences written before lease support remain readable, but their
    # missing owner/expiry facts are intentionally unknown and therefore
    # cannot be reclaimed automatically.
    if "ownerPid" in active:
        try:
            owner_pid = int(active.get("ownerPid") or 0)
        except (TypeError, ValueError) as exc:
            raise ChallengeCupMaintenanceCorruptError() from exc
        if owner_pid < 0:
            raise ChallengeCupMaintenanceCorruptError()
        normalized["ownerPid"] = owner_pid
    if "expiresAtMs" in active:
        try:
            expires_at_ms = int(active.get("expiresAtMs") or 0)
        except (TypeError, ValueError) as exc:
            raise ChallengeCupMaintenanceCorruptError() from exc
        if expires_at_ms <= 0:
            raise ChallengeCupMaintenanceCorruptError()
        normalized["expiresAtMs"] = expires_at_ms
    if "expiresAt" in active:
        expires_at = str(active.get("expiresAt") or "").strip()
        if not expires_at or len(expires_at) > 80:
            raise ChallengeCupMaintenanceCorruptError()
        normalized["expiresAt"] = expires_at
    if "ttlMs" in active:
        try:
            ttl_ms = int(active.get("ttlMs") or 0)
        except (TypeError, ValueError) as exc:
            raise ChallengeCupMaintenanceCorruptError() from exc
        if ttl_ms <= 0:
            raise ChallengeCupMaintenanceCorruptError()
        normalized["ttlMs"] = ttl_ms
    # A lease marker must carry both machine-readable expiry and its readable
    # counterpart.  Partial lease fields are untrusted rather than silently
    # filled in from wall-clock time.
    lease_fields = {"ownerPid", "expiresAtMs", "expiresAt"}
    if lease_fields.intersection(active) and not lease_fields.issubset(normalized):
        raise ChallengeCupMaintenanceCorruptError()
    return normalized


def _write_active_fence(active: Mapping[str, Any] | None) -> None:
    now, _ = _utc_now()
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": FENCE_KIND,
        "activeFence": dict(active) if isinstance(active, Mapping) else None,
        "updatedAt": now,
    }
    atomic_write_text(
        _fence_path(),
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


def _fence_state(
    active: Mapping[str, Any],
    *,
    now_ms: int,
    owner_alive: Callable[[int], bool | None] | None,
) -> tuple[str, bool | None, bool]:
    """Classify a fence without mutating it.

    ``unknown`` is deliberately active.  A missing legacy owner or an
    unavailable liveness probe must never turn a destructive boundary into an
    implicit allow.  A known dead owner is reclaimable immediately; a known
    expired lease is reclaimable even if the old process is still around,
    because the owner must renew before the TTL elapses.
    """

    owner_alive_value = _owner_alive_value(active, owner_alive)
    try:
        expires_at_ms = int(active.get("expiresAtMs") or 0)
    except (TypeError, ValueError):
        expires_at_ms = 0
    if expires_at_ms <= 0:
        return "unknown", owner_alive_value, False
    expired = int(now_ms) >= expires_at_ms
    if owner_alive_value is None:
        return "unknown", None, expired
    if not expired and not owner_alive_value:
        return "orphaned", False, False
    if expired:
        return "expired", owner_alive_value, True
    return "active", owner_alive_value, False


def _inspect_fence_locked(
    *,
    now_ms: int,
    owner_alive: Callable[[int], bool | None] | None,
    reap: bool = True,
) -> dict[str, Any]:
    active = _read_active_fence()
    if active is None:
        return {"status": "absent", "activeFence": None, "reclaimed": False}
    status, owner_alive_value, expired = _fence_state(
        active,
        now_ms=now_ms,
        owner_alive=owner_alive,
    )
    reclaimable = status in {"orphaned", "expired"}
    if reclaimable and reap:
        _write_active_fence(None)
        return {
            "status": status,
            "activeFence": None,
            "reclaimed": True,
            "expired": expired,
            "ownerAlive": owner_alive_value,
        }
    return {
        "status": status,
        "activeFence": copy.deepcopy(active),
        "reclaimed": False,
        "expired": expired,
        "ownerAlive": owner_alive_value,
    }


def inspect_fence(
    team_id: str,
    *,
    now_ms: int | None = None,
    owner_alive: Callable[[int], bool | None] | None = None,
    reap: bool = True,
) -> dict[str, Any]:
    """Return the fence state and reclaim known expired/orphaned leases.

    This is the diagnostic/read path used by workers before they defer.  It
    may clear only a fence whose lease is known expired or whose recorded
    owner is known dead.  Corrupt and otherwise unknown markers raise or stay
    active, preserving the existing fail-closed contract.
    """

    _target_team_id(team_id)
    current_ms = _clock_ms(now_ms)
    with _LOCK:
        return _inspect_fence_locked(
            now_ms=current_ms,
            owner_alive=owner_alive,
            reap=reap,
        )


def read_fence(
    team_id: str,
    *,
    now_ms: int | None = None,
    owner_alive: Callable[[int], bool | None] | None = None,
) -> dict[str, Any] | None:
    """Read the active governed fence, reaping known stale leases."""

    state = inspect_fence(
        team_id,
        now_ms=now_ms,
        owner_alive=owner_alive,
    )
    active = state.get("activeFence")
    return copy.deepcopy(active) if isinstance(active, Mapping) else None


def acquire_fence(
    team_id: str,
    *,
    purge_plan_id: str,
    inventory_hash: str,
    acquired_by: str = "system",
    ttl_ms: int = DEFAULT_FENCE_TTL_MS,
    owner_pid: int | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Persist a reset fence, reusing only the exact same reset identity."""

    normalized_team_id = _target_team_id(team_id)
    plan_id = _required_text(purge_plan_id, field="purgePlanId", max_length=200)
    hash_value = _inventory_hash(inventory_hash)
    actor = _required_text(acquired_by, field="acquiredBy", max_length=160)
    lease_ttl_ms = _ttl_ms(ttl_ms)
    normalized_owner_pid = _owner_pid(
        owner_pid,
        default_current=True,
        require_positive=True,
    )
    current_ms = _clock_ms(now_ms)
    with _LOCK:
        state = _inspect_fence_locked(
            now_ms=current_ms,
            owner_alive=None,
        )
        existing = state.get("activeFence")
        if existing is not None:
            if (
                existing["purgePlanId"] != plan_id
                or existing["inventoryHash"] != hash_value
            ):
                raise ChallengeCupMaintenanceConflictError(operation="acquire")
            return {
                **copy.deepcopy(existing),
                "status": "reused",
            }
        acquired_at_ms = current_ms
        acquired_at = _iso_from_ms(acquired_at_ms)
        expires_at_ms = acquired_at_ms + lease_ttl_ms
        active = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": FENCE_KIND,
            "teamId": normalized_team_id,
            "purgePlanId": plan_id,
            "inventoryHash": hash_value,
            "acquiredAt": acquired_at,
            "acquiredAtMs": acquired_at_ms,
            "acquiredBy": actor,
            "ownerPid": normalized_owner_pid,
            "ttlMs": lease_ttl_ms,
            "expiresAt": _iso_from_ms(expires_at_ms),
            "expiresAtMs": expires_at_ms,
        }
        _write_active_fence(active)
        return {**copy.deepcopy(active), "status": "acquired"}


def release_fence(
    team_id: str,
    *,
    purge_plan_id: str,
    inventory_hash: str,
) -> dict[str, Any]:
    """Release only the fence identified by the exact reset plan and hash."""

    normalized_team_id = _target_team_id(team_id)
    plan_id = _required_text(purge_plan_id, field="purgePlanId", max_length=200)
    hash_value = _inventory_hash(inventory_hash)
    with _LOCK:
        existing = _read_active_fence()
        if existing is None:
            return {"status": "absent", "teamId": normalized_team_id}
        if (
            existing["purgePlanId"] != plan_id
            or existing["inventoryHash"] != hash_value
        ):
            raise ChallengeCupMaintenanceConflictError(operation="release")
        _write_active_fence(None)
        return {
            "status": "released",
            "teamId": normalized_team_id,
            "purgePlanId": plan_id,
            "inventoryHash": hash_value,
        }


def assert_writes_allowed(
    team_id: str,
    *,
    operation: str,
    created_at_ms: int | None = None,
    now_ms: int | None = None,
    owner_alive: Callable[[int], bool | None] | None = None,
) -> dict[str, Any] | None:
    """Fail closed for new Challenge Cup writes while a fence is active.

    Calls for other teams are intentionally no-ops so this Challenge Cup
    maintenance operation cannot freeze unrelated teams.  When a dispatch
    already existed before the fence was acquired, ``created_at_ms`` proves it
    belongs to the drain set and it is allowed to continue.
    """

    normalized_team_id = _optional_target_team_id(team_id)
    if normalized_team_id != RESEARCH_TEAM_ID:
        return None
    state = inspect_fence(
        normalized_team_id,
        now_ms=now_ms,
        owner_alive=owner_alive,
    )
    active = state.get("activeFence")
    if not isinstance(active, Mapping):
        return None
    if created_at_ms is not None:
        try:
            accepted_at = int(created_at_ms)
        except (TypeError, ValueError):
            accepted_at = 0
        if accepted_at > 0 and accepted_at < int(active["acquiredAtMs"]):
            return copy.deepcopy(active)
    raise ChallengeCupMaintenanceActiveError(operation=operation)


# Short aliases keep call sites readable while the public names remain
# explicit for reset adapters and tests.
acquire = acquire_fence
read = read_fence
release = release_fence
inspect = inspect_fence
assert_write_allowed = assert_writes_allowed


__all__ = [
    "FENCE_KIND",
    "DEFAULT_FENCE_TTL_MS",
    "MAINTENANCE_FENCE_TTL_MS",
    "RESEARCH_TEAM_ID",
    "SCHEMA_VERSION",
    "ChallengeCupMaintenanceActiveError",
    "ChallengeCupMaintenanceConflictError",
    "ChallengeCupMaintenanceCorruptError",
    "ChallengeCupMaintenanceError",
    "ChallengeCupMaintenanceScopeError",
    "acquire",
    "acquire_fence",
    "assert_write_allowed",
    "assert_writes_allowed",
    "inspect",
    "inspect_fence",
    "read",
    "read_fence",
    "release",
    "release_fence",
]
