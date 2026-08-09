"""Atomic durable projection store for managed external-Agent tasks."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.external_agent.contracts import TASK_ACTIVE_STATUSES, TASK_TERMINAL_STATUSES


class ExternalAgentTaskStoreError(RuntimeError):
    """Base persistent task-store error."""


class ExternalAgentTaskNotFoundError(ExternalAgentTaskStoreError):
    """Raised when an opaque task handle does not exist."""


class ExternalAgentTaskConflictError(ExternalAgentTaskStoreError):
    """Raised for stale revisions, invalid transitions, or key reuse."""


_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"queued", "running", "failed", "cancelled", "cancelling"}),
    "running": frozenset(
        {"running", "awaiting_approval", "succeeded", "failed", "cancelling"}
    ),
    "awaiting_approval": frozenset(
        {"awaiting_approval", "running", "failed", "cancelling"}
    ),
    "cancelling": frozenset(
        {"cancelling", "cancelled", "timed_out", "stop_unconfirmed"}
    ),
    "stop_unconfirmed": frozenset(
        {"stop_unconfirmed", "cancelled", "timed_out", "failed"}
    ),
    "succeeded": frozenset({"succeeded"}),
    "failed": frozenset({"failed"}),
    "cancelled": frozenset({"cancelled"}),
    "timed_out": frozenset({"timed_out"}),
}
_FORBIDDEN_CONTENT_FIELDS = frozenset(
    {"prompt", "task", "content", "messages", "reply", "response", "arguments"}
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _subject_hash(owner_id: str) -> str:
    normalized = str(owner_id or "").strip()
    if not normalized:
        raise ValueError("owner_id is required")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _safe_task_id(task_id: str) -> str:
    normalized = str(task_id or "").strip()
    if not normalized or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for char in normalized
    ):
        raise ExternalAgentTaskNotFoundError("external Agent task was not found")
    return normalized


class ExternalAgentTaskStore:
    """JSON-per-task store with atomic replace and optimistic revisions.

    The store is intentionally a projection. Full prompts, replies, tool
    arguments, and conversation messages are rejected so Session/Turn remains
    the sole content authority.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.tasks_dir = self.root / "tasks"
        self._lock = threading.RLock()

    def task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{_safe_task_id(task_id)}.json"

    def create_task(
        self,
        *,
        owner_id: str,
        agent_id: str,
        task_digest: str,
        client_request_id: str,
        request_digest: str,
        permission_profile: str,
        lease_seconds: int,
        adapter_connection_id: str,
        runtime_revision: str,
        max_task_seconds: int = 1800,
    ) -> tuple[dict[str, Any], bool]:
        owner_hash = _subject_hash(owner_id)
        normalized_request_id = str(client_request_id or "").strip()
        normalized_request_digest = str(request_digest or "").strip()
        now = _utc_now()
        with self._lock:
            if normalized_request_id:
                existing = self._find_idempotent_locked(
                    owner_hash, normalized_request_id
                )
                if existing:
                    if (
                        str(existing.get("requestDigest") or "")
                        != normalized_request_digest
                    ):
                        raise ExternalAgentTaskConflictError(
                            "idempotency key is already bound to another request"
                        )
                    return existing, False
            task_id = f"eat-{uuid.uuid4().hex}"
            lease_id = f"lease-{uuid.uuid4().hex}"
            record: dict[str, Any] = {
                "schemaVersion": 1,
                "taskId": task_id,
                "revision": 1,
                "status": "queued",
                "reasonCode": "task_queued",
                "ownerSubjectHash": owner_hash,
                "agentId": str(agent_id or "").strip(),
                "taskDigest": str(task_digest or "").strip(),
                "clientRequestId": normalized_request_id,
                "requestDigest": normalized_request_digest,
                "effectivePermissionProfile": str(
                    permission_profile or "read_only"
                ).strip()
                or "read_only",
                "adapterConnectionId": str(adapter_connection_id or "").strip(),
                "runtimeRevision": str(runtime_revision or "").strip(),
                "leaseId": lease_id,
                "leaseExpiresAt": _iso(
                    now + timedelta(seconds=max(5, int(lease_seconds)))
                ),
                "deadlineAt": _iso(
                    now + timedelta(seconds=max(5, int(max_task_seconds)))
                ),
                "sessionId": "",
                "turnId": "",
                "resultSummary": "",
                "error": None,
                "approvalDecisions": {},
                "createdAt": _iso(now),
                "updatedAt": _iso(now),
                "completedAt": None,
            }
            self._write_locked(record)
            return deepcopy(record), True

    def find_idempotent(
        self,
        *,
        owner_id: str,
        client_request_id: str,
    ) -> dict[str, Any] | None:
        normalized_request_id = str(client_request_id or "").strip()
        if not normalized_request_id:
            return None
        with self._lock:
            record = self._find_idempotent_locked(
                _subject_hash(owner_id),
                normalized_request_id,
            )
            return deepcopy(record) if record else None

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            path = self.task_path(task_id)
            if not path.is_file():
                raise ExternalAgentTaskNotFoundError(
                    "external Agent task was not found"
                )
            return deepcopy(self._read_path(path))

    def transition(
        self,
        task_id: str,
        *,
        status: str,
        expected_revision: int | None = None,
        reason_code: str = "",
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in _TRANSITIONS:
            raise ExternalAgentTaskConflictError(
                f"unsupported task status: {normalized_status}"
            )
        updates = dict(fields or {})
        forbidden = _FORBIDDEN_CONTENT_FIELDS.intersection(
            key.casefold() for key in updates
        )
        if forbidden:
            raise ExternalAgentTaskConflictError(
                f"task projection cannot persist content fields: {', '.join(sorted(forbidden))}"
            )
        with self._lock:
            record = self.get_task(task_id)
            revision = int(record.get("revision") or 0)
            if expected_revision is not None and int(expected_revision) != revision:
                raise ExternalAgentTaskConflictError("task revision conflict")
            current = str(record.get("status") or "").strip().lower()
            if normalized_status not in _TRANSITIONS.get(current, frozenset()):
                raise ExternalAgentTaskConflictError(
                    f"invalid task transition: {current} -> {normalized_status}"
                )
            record.update(updates)
            record["status"] = normalized_status
            record["revision"] = revision + 1
            record["updatedAt"] = _iso(_utc_now())
            if reason_code:
                record["reasonCode"] = str(reason_code).strip()
            if normalized_status in TASK_TERMINAL_STATUSES:
                record["completedAt"] = record.get("completedAt") or record["updatedAt"]
            self._write_locked(record)
            return deepcopy(record)

    def renew_lease(
        self,
        task_id: str,
        *,
        owner_id: str,
        lease_id: str,
        adapter_connection_id: str,
        lease_seconds: int,
    ) -> dict[str, Any]:
        with self._lock:
            record = self.get_task(task_id)
            if record.get("ownerSubjectHash") != _subject_hash(owner_id):
                raise ExternalAgentTaskNotFoundError(
                    "external Agent task was not found"
                )
            if str(record.get("leaseId") or "") != str(lease_id or "").strip():
                raise ExternalAgentTaskNotFoundError(
                    "external Agent task was not found"
                )
            if str(record.get("status") or "") not in TASK_ACTIVE_STATUSES:
                return record
            return self.transition(
                task_id,
                status=str(record["status"]),
                expected_revision=int(record["revision"]),
                reason_code="lease_renewed",
                fields={
                    "adapterConnectionId": str(adapter_connection_id or "").strip(),
                    "leaseExpiresAt": _iso(
                        _utc_now() + timedelta(seconds=max(5, int(lease_seconds)))
                    ),
                },
            )

    def list_nonterminal(self) -> list[dict[str, Any]]:
        with self._lock:
            result = [
                record
                for record in self._iter_locked()
                if str(record.get("status") or "") in TASK_ACTIVE_STATUSES
            ]
        result.sort(
            key=lambda item: (
                str(item.get("createdAt") or ""),
                str(item.get("taskId") or ""),
            )
        )
        return result

    @staticmethod
    def owner_matches(record: dict[str, Any], owner_id: str) -> bool:
        return str(record.get("ownerSubjectHash") or "") == _subject_hash(owner_id)

    def _find_idempotent_locked(
        self, owner_hash: str, client_request_id: str
    ) -> dict[str, Any] | None:
        for record in self._iter_locked():
            if (
                record.get("ownerSubjectHash") == owner_hash
                and record.get("clientRequestId") == client_request_id
            ):
                return record
        return None

    def _iter_locked(self) -> list[dict[str, Any]]:
        if not self.tasks_dir.is_dir():
            return []
        result: list[dict[str, Any]] = []
        for path in sorted(self.tasks_dir.glob("eat-*.json")):
            try:
                result.append(self._read_path(path))
            except (
                OSError,
                ValueError,
                json.JSONDecodeError,
                ExternalAgentTaskStoreError,
            ):
                continue
        return result

    @staticmethod
    def _read_path(path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ExternalAgentTaskStoreError(
                "external Agent task projection must be an object"
            )
        return payload

    def _write_locked(self, record: dict[str, Any]) -> None:
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        path = self.task_path(str(record.get("taskId") or ""))
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        data = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()


__all__ = [
    "ExternalAgentTaskConflictError",
    "ExternalAgentTaskNotFoundError",
    "ExternalAgentTaskStore",
    "ExternalAgentTaskStoreError",
]
