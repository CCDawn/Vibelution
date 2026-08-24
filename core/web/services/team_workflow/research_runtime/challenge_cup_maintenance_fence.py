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
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .atomic_fs import atomic_write_text
from .paths import research_workflow_data_root

RESEARCH_TEAM_ID = "research-team"
FENCE_KIND = "challenge_cup_maintenance"
SCHEMA_VERSION = 1
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
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": FENCE_KIND,
        "teamId": RESEARCH_TEAM_ID,
        "purgePlanId": plan_id,
        "inventoryHash": inventory_hash,
        "acquiredAt": acquired_at,
        "acquiredAtMs": acquired_at_ms,
        "acquiredBy": str(active.get("acquiredBy") or "system").strip()[:160] or "system",
    }


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


def read_fence(team_id: str) -> dict[str, Any] | None:
    """Read the active governed fence for ``research-team``."""

    _target_team_id(team_id)
    with _LOCK:
        active = _read_active_fence()
        return copy.deepcopy(active) if active is not None else None


def acquire_fence(
    team_id: str,
    *,
    purge_plan_id: str,
    inventory_hash: str,
    acquired_by: str = "system",
) -> dict[str, Any]:
    """Persist a reset fence, reusing only the exact same reset identity."""

    normalized_team_id = _target_team_id(team_id)
    plan_id = _required_text(purge_plan_id, field="purgePlanId", max_length=200)
    hash_value = _inventory_hash(inventory_hash)
    actor = _required_text(acquired_by, field="acquiredBy", max_length=160)
    with _LOCK:
        existing = _read_active_fence()
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
        acquired_at, acquired_at_ms = _utc_now()
        active = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": FENCE_KIND,
            "teamId": normalized_team_id,
            "purgePlanId": plan_id,
            "inventoryHash": hash_value,
            "acquiredAt": acquired_at,
            "acquiredAtMs": acquired_at_ms,
            "acquiredBy": actor,
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
    with _LOCK:
        active = _read_active_fence()
    if active is None:
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
assert_write_allowed = assert_writes_allowed


__all__ = [
    "FENCE_KIND",
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
    "read",
    "read_fence",
    "release",
    "release_fence",
]
