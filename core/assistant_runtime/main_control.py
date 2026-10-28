"""Bounded, ephemeral transport to Electron main; never a lifecycle authority.

An expired delivery is forgotten, never replayed. A native command already
accepted by main outlives this transport and is queried using its requestId.
All methods belong to the host event loop, including settle and close.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import appearance_protocol as appearance


_OPERATIONS = {"start", "stop", "restart"}
_ACTIONS = {"project_status", "project_lifecycle", "project_lifecycle_receipt", "history_import", "history_import_receipt", "affairs_sync", "episodic_sync", "initial_migration_queue", "initial_migration_receipt"}
_STATUS_STATES = {"stopped", "starting", "running", "stopping", "failed", "unknown"}
_WRITE_STATES = {"completed", "queued", "rejected", "unknown", "not_found"}
_FACADE_CODES = {
    "invalid_request", "project_unavailable", "registration_changed", "storage_owner_changed",
    "prerequisite_required", "context_limit", "status_unavailable", "lifecycle_failed", "cancelled",
    "status", "accepted", "rejected", "active_work_blocked", "restart_queued",
    "lifecycle_intent_superseded", "backend_retire_incomplete", "close_backoff_coalesced",
}
_WRITE_CODES = _FACADE_CODES | {
    "request_invalid", "request_failed", "request_unbound", "receipt_unavailable", "request_not_found",
    "request_conflict", "request_limit_exceeded", "reservation_invalid", "binding_conflict",
    "request_store_invalid", "request_store_read_failed", "request_store_write_failed",
    "control_unavailable", "control_busy",
}


def _opaque(value, maximum):
    return (type(value) is str and 1 <= len(value) <= maximum
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is not None
            and re.match(r"(?:https?|file|data|javascript|mailto|ftp|wss?):", value, re.I) is None)


def affairs_migration_id(project_id, preview_id):
    return "affairs-" + hashlib.sha256((project_id + ":" + preview_id).encode("utf-8")).hexdigest()[:40]


def history_request_id(project_id, preview_id):
    raw = json.dumps([project_id, preview_id], ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return "history-" + hashlib.sha256(raw).hexdigest()[:40]


def episodic_migration_id(project_id, preview_id):
    return "episodic-" + hashlib.sha256((project_id + ":" + preview_id).encode("utf-8")).hexdigest()[:40]


def initial_migration_id(project_id, preview_id, category):
    # New previews of the same registered project and category must never mint
    # a replacement ID for an earlier unconfirmed attempt.
    _ = preview_id
    return "initial-" + hashlib.sha256((project_id + ":" + category).encode("utf-8")).hexdigest()[:40]


def knowledge_sync_id(project_id, preview_id):
    return "ksync-" + hashlib.sha256((project_id + ":" + preview_id).encode("utf-8")).hexdigest()[:40]


def knowledge_recovery_id(project_id, preview_id, original_sync_id):
    return "krec-" + hashlib.sha256((project_id + ":" + preview_id + ":" + original_sync_id).encode("utf-8")).hexdigest()[:40]


def initial_model_env_unavailable():
    return any(key.upper().startswith("AGENT_LLM__") and value.strip() for key, value in os.environ.items())


def _request(action, request):
    if type(action) is str and action in appearance.APPEARANCE_ACTIONS:
        return appearance.validate_request(action, request)
    if type(action) is not str or action not in _ACTIONS or type(request) is not dict:
        raise ValueError("Invalid main control request")
    if action == "initial_migration_receipt":
        if (set(request) != {"projectId", "category", "operationId"} or not _opaque(request.get("projectId"), 160)
                or type(request.get("category")) is not str or request["category"] not in {"personal", "knowledge", "reminder_handoff"}
                or request.get("operationId") != initial_migration_id(request["projectId"], "", request["category"])):
            raise ValueError("Invalid initial migration receipt request")
        return dict(request)
    if action == "initial_migration_queue":
        recovery = request.get("category") == "knowledge_recovery"
        if (set(request) != ({"projectId", "previewId", "turnId", "category", "operationId", "originalSyncId"} if recovery
                             else {"projectId", "previewId", "turnId", "category", "operationId"})
                or not _opaque(request.get("projectId"), 160) or not _opaque(request.get("turnId"), 160)
                or type(request.get("previewId")) is not str or re.fullmatch(r"[0-9a-f]{64}", request["previewId"]) is None
                or type(request.get("category")) is not str or request["category"] not in {"personal", "knowledge", "knowledge_sync", "knowledge_recovery", "reminder_handoff"}
                or recovery and (type(request.get("originalSyncId")) is not str or re.fullmatch(r"ksync-[a-f0-9]{40}", request["originalSyncId"]) is None)
                or request.get("operationId") != (knowledge_recovery_id(request["projectId"], request["previewId"], request["originalSyncId"]) if recovery
                    else knowledge_sync_id(request["projectId"], request["previewId"]) if request["category"] == "knowledge_sync"
                    else initial_migration_id(request["projectId"], request["previewId"], request["category"]))):
            raise ValueError("Invalid initial migration request")
        return dict(request)
    if action == "history_import_receipt":
        if (set(request) != {"projectId", "previewId"} or not _opaque(request.get("projectId"), 160)
                or type(request.get("previewId")) is not str or re.fullmatch(r"[0-9a-f]{64}", request["previewId"]) is None):
            raise ValueError("Invalid history receipt request")
        return dict(request)
    if action in {"history_import", "affairs_sync", "episodic_sync"}:
        expected = {"projectId", "previewId", "turnId"}
        optional = ({"recoverSyncId", "resolveSyncId", "reviewToken"} if action == "episodic_sync"
                    else {"recoverSyncId"} if action == "affairs_sync" else set())
        if (not expected <= set(request) or set(request) - expected - optional
                or not _opaque(request.get("projectId"), 160)
                or type(request.get("previewId")) is not str
                or re.fullmatch(r"[0-9a-f]{64}", request["previewId"]) is None
                or "recoverSyncId" in request and (type(request["recoverSyncId"]) is not str
                    or re.fullmatch((r"affairs-" if action == "affairs_sync" else r"episodic-") + r"[0-9a-f]{40}", request["recoverSyncId"]) is None)
                or ("resolveSyncId" in request) != ("reviewToken" in request)
                or "resolveSyncId" in request and ("recoverSyncId" in request
                    or type(request["resolveSyncId"]) is not str
                    or re.fullmatch(r"episodic-[0-9a-f]{40}", request["resolveSyncId"]) is None
                    or type(request["reviewToken"]) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", request["reviewToken"]) is None)
                or not _opaque(request.get("turnId"), 160)):
            raise ValueError("Invalid history import request")
        return dict(request)
    status = action == "project_status"
    expected = {"projectId", "operation"} | (set() if status else {"requestId"})
    if (set(request) != expected or not _opaque(request.get("projectId"), 160)
            or type(request.get("operation")) is not str
            or request["operation"] not in ({"status"} if status else _OPERATIONS)
            or (not status and not _opaque(request.get("requestId"), 128))):
        raise ValueError("Invalid main control request")
    return dict(request)


def _result(action, request, result):
    """Reject unknown fields rather than copying errors, paths or credentials."""
    if action in appearance.APPEARANCE_ACTIONS:
        return appearance.validate_result(action, request, result)
    if action == "initial_migration_receipt":
        required = {"schemaVersion", "projectId", "category", "operationId", "state", "code", "readyForCutover"}
        extra = {"waitingFor", "syncId"} if request["category"] == "reminder_handoff" and type(result) is dict and result.get("state") == "queued" else set()
        if (type(result) is not dict or set(result) != required | extra
                or type(result.get("schemaVersion")) is not int or result["schemaVersion"] != 1
                or any(result.get(key) != request[key] for key in ("projectId", "category", "operationId"))
                or type(result.get("state")) is not str or result["state"] not in {"queued", "completed", "partial", "unknown", "not_found"}
                or result.get("code") != result["state"] or result.get("readyForCutover") is not False
                or request["category"] == "reminder_handoff" and result["state"] not in {"queued", "unknown"}
                or extra and (result.get("waitingFor") not in {"window", "close_transaction", "drain", "unknown"}
                    or result.get("syncId") != "affairs-" + request["operationId"][len("initial-"):])):
            raise ValueError("Invalid initial migration receipt result")
        return dict(result)
    if action == "initial_migration_queue":
        required = {"schemaVersion", "projectId", "previewId", "category", "operationId", "state", "code", "readyForCutover"}
        if request["category"] == "knowledge_recovery":
            required.add("originalSyncId")
        if (type(result) is not dict or set(result) != required or type(result.get("schemaVersion")) is not int
                or result["schemaVersion"] != 1 or any(result.get(key) != request[key] for key in ("projectId", "previewId", "category", "operationId"))
                or request["category"] == "knowledge_recovery" and result.get("originalSyncId") != request["originalSyncId"]
                or result.get("readyForCutover") is not False or type(result.get("state")) is not str
                or type(result.get("code")) is not str or (result.get("state"), result.get("code")) not in {
                    ("queued", "queued"), ("unknown", "unknown"), ("rejected", "cancelled"),
                    ("rejected", "unavailable"), ("rejected", "busy")}):
            raise ValueError("Invalid initial migration result")
        return dict(result)
    if action in {"affairs_sync", "episodic_sync"}:
        required = {"schemaVersion", "projectId", "previewId", "migrationId", "state", "code", "readyForCutover"}
        counts = {"appliedCount", "conflictCount"}
        has_counts = (type(result) is dict and type(result.get("state")) is str
                      and result["state"] in {"complete", "partial"})
        has_confirmation = type(result) is dict and result.get("state") == "confirmed"
        if (type(result) is not dict or set(result) != required | (counts if has_counts else {"conflictCount"} if has_confirmation else set())
                or type(result.get("schemaVersion")) is not int or result["schemaVersion"] != 1
                or result.get("projectId") != request["projectId"] or result.get("previewId") != request["previewId"]
                or result.get("migrationId") != request.get("recoverSyncId", (affairs_migration_id if action == "affairs_sync" else episodic_migration_id)(request["projectId"], request["previewId"]))
                or result.get("readyForCutover") is not False
                or type(result.get("state")) is not str or type(result.get("code")) is not str
                or "recoverSyncId" in request and result.get("state") not in {"confirmed", "unknown"}
                or has_confirmation and "recoverSyncId" not in request
                or (result.get("state"), result.get("code")) not in {
                    ("complete", "synchronized"), ("complete", "resolved"), ("partial", "unresolved"), ("confirmed", "matched"),
                    ("rejected", "preview_invalid"), ("rejected", "project_unavailable"),
                    ("rejected", "cancelled"), ("rejected", "busy"),
                    ("rejected", "unresolved"), ("rejected", "pending"),
                    ("rejected", "baseline_unavailable"), ("rejected", "row_limit"), ("rejected", "review_changed"), ("unknown", "unknown")}
                or (result.get("state"), result.get("code")) == ("complete", "resolved") and (action != "episodic_sync" or "resolveSyncId" not in request)
                or "resolveSyncId" in request and result.get("state") == "complete" and result.get("code") != "resolved"
                or "resolveSyncId" in request and result.get("state") == "partial"
                or result.get("code") == "resolved" and result.get("appliedCount") != 0
                or has_counts and (any(type(result.get(key)) is not int or not 0 <= result[key] <= 4096 for key in counts)
                    or (result["conflictCount"] == 0) != (result["state"] == "complete"))
                or has_confirmation and (type(result.get("conflictCount")) is not int or not 0 <= result["conflictCount"] <= 4096)):
            raise ValueError("Invalid affairs sync result")
        return dict(result)
    if action == "history_import_receipt":
        base = {"schemaVersion", "projectId", "previewId", "state", "code", "readyForCutover"}
        published = type(result) is dict and result.get("state") == "published"
        if (type(result) is not dict or set(result) != base | ({"requestId", "migrationId", "historyCount"} if published else set())
                or type(result.get("schemaVersion")) is not int or result["schemaVersion"] != 1
                or any(result.get(k) != request[k] for k in ("projectId", "previewId"))
                or result.get("readyForCutover") is not False
                or (result.get("state"), result.get("code")) not in {("unknown", "unknown"), ("published", "imported")}
                or published and (result.get("requestId") != history_request_id(request["projectId"], request["previewId"])
                    or type(result.get("migrationId")) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", result["migrationId"]) is None
                    or type(result.get("historyCount")) is not int or not 0 <= result["historyCount"] <= 10000)):
            raise ValueError("Invalid history receipt result")
        return dict(result)
    if action == "history_import":
        required = {"schemaVersion", "projectId", "previewId", "state", "code", "readyForCutover"}
        if (type(result) is not dict or not required <= result.keys() or result.keys() - required - {"historyCount"}
                or type(result.get("schemaVersion")) is not int or result["schemaVersion"] != 1
                or result.get("projectId") != request["projectId"] or result.get("previewId") != request["previewId"]
                or result.get("readyForCutover") is not False
                or type(result.get("state")) is not str or type(result.get("code")) is not str
                or (result.get("state"), result.get("code")) not in {
                    ("published", "imported"), ("rejected", "preview_invalid"),
                    ("rejected", "project_unavailable"), ("rejected", "cancelled"),
                    ("rejected", "busy"), ("unknown", "unknown")}
                or ("historyCount" in result and (type(result["historyCount"]) is not int or not 0 <= result["historyCount"] <= 10000))
                or (result.get("state") == "published") != ("historyCount" in result)):
            raise ValueError("Invalid history import result")
        return dict(result)
    status = action == "project_status"
    required = {"schemaVersion", *request, "accepted", "code"} if status else {
        "schemaVersion", *request, "state", "code"}
    optional = {"status"} if status else {"accepted"}
    if (type(result) is not dict or not required <= result.keys() or result.keys() - required - optional
            or type(result.get("schemaVersion")) is not int or result["schemaVersion"] != 1
            or any(type(result.get(key)) is not str or result[key] != value for key, value in request.items())
            or type(result.get("code")) is not str
            or result["code"] not in (_FACADE_CODES if status else _WRITE_CODES)
            or ("accepted" in result and type(result["accepted"]) is not bool)):
        raise ValueError("Invalid main control result")
    if status and "status" in result:
        projection = result["status"]
        if (type(projection) is not dict or "state" not in projection
                or set(projection) - {"state", "activeWorkCount"}
                or type(projection["state"]) is not str or projection["state"] not in _STATUS_STATES
                or ("activeWorkCount" in projection and (type(projection["activeWorkCount"]) is not int
                    or not 0 <= projection["activeWorkCount"] <= 2**53 - 1))):
            raise ValueError("Invalid main control result")
    if not status and (type(result["state"]) is not str or result["state"] not in _WRITE_STATES):
        raise ValueError("Invalid main control result")
    if not status and (
        result["state"] in {"completed", "queued"} and result.get("accepted") is not True
        or result["state"] == "completed" and result["code"] not in {"accepted", "close_backoff_coalesced"}
        or result["state"] == "queued" and result["code"] != "restart_queued"
        or result["state"] in {"rejected", "unknown", "not_found"} and result.get("accepted") is True
    ):
        raise ValueError("Invalid main control result")
    return {**result, **({"status": dict(result["status"])} if "status" in result else {})}


@dataclass
class _Delivery:
    action: str
    request: dict
    deadline: float
    future: asyncio.Future
    claimed: bool = False
    image_admitted: bool = False
    initial_admitted: bool = False
    initial_prepared: bool = False
    initial_token: object = None
    turn_id: str | None = None
    delivery_id: str | None = None


class _InitialPublication:
    """Order revocation and publication without waiting on the event loop."""
    def __init__(self, deadline, turn_id, delivery_id, operation_id):
        self._lock = threading.Lock()
        self._deadline = deadline
        self._revoked = threading.Event()
        self._done = threading.Event()
        self.turn_id = turn_id
        self.delivery_id = delivery_id
        self.operation_id = operation_id
        self._published = False
        self._busy = False

    def revoke(self):
        # The event loop must never wait for a filesystem commit.
        self._revoked.set()

    def drain(self, timeout):
        if not self._lock.acquire(timeout=max(0, timeout)):
            return False
        self._lock.release()
        return True

    def finished(self):
        self._done.set()

    def wait_finished(self, timeout):
        return self._done.wait(max(0, timeout))

    def check(self):
        if self._revoked.is_set() or time.monotonic() >= self._deadline:
            raise ValueError("initial migration delivery unavailable")

    def wait_retry(self, timeout):
        self._revoked.wait(max(0, timeout))
        self.check()

    def publish(self, writer):
        with self._lock:
            if self._revoked.is_set() or self._published or time.monotonic() >= self._deadline:
                raise ValueError("initial migration delivery unavailable")
            result = writer()
            self._published = True
            return result

    def published(self):
        with self._lock:
            return self._published and not self._revoked.is_set() and time.monotonic() < self._deadline

    def confirm_busy(self):
        with self._lock:
            if not self._done.is_set() or self._published or self._revoked.is_set() or time.monotonic() >= self._deadline:
                return False
            self._busy = True
            return True

    def busy_confirmed(self):
        with self._lock:
            return self._busy and self._done.is_set() and not self._published and not self._revoked.is_set() and time.monotonic() < self._deadline


def _revoke_initial(entry):
    if entry.initial_token is not None:
        entry.initial_token.revoke()


class MainControlBroker:
    def __init__(self, project_ids: Callable, *, timeout_seconds=20, claim_seconds=10, max_pending=32, appearance_enabled=False, image_timeout_seconds=appearance.IMAGE_SELECTION_SECONDS, initial_migration_enabled=False):
        if (not callable(project_ids) or type(max_pending) is not int or not 1 <= max_pending <= 128
                or any(type(value) not in {int, float} or not math.isfinite(value) or value <= 0
                       for value in (timeout_seconds, claim_seconds))
                or timeout_seconds > 20 or claim_seconds > 10):
            raise ValueError("Invalid main control transport limits")
        if type(appearance_enabled) is not bool or type(image_timeout_seconds) not in {int, float} or not math.isfinite(image_timeout_seconds) or not 0 < image_timeout_seconds <= appearance.IMAGE_SELECTION_SECONDS:
            raise ValueError("Invalid appearance transport limits")
        self.appearance_enabled = appearance_enabled
        if type(initial_migration_enabled) is not bool:
            raise ValueError("Invalid initial migration capability")
        self.initial_migration_enabled = initial_migration_enabled
        self._image_timeout = image_timeout_seconds
        self._project_ids = project_ids
        self._timeout = timeout_seconds
        self._claim_seconds = claim_seconds
        self._max_pending = max_pending
        self._queue = asyncio.Queue(maxsize=max_pending)
        self._pending: dict[str, _Delivery] = {}
        self._closed = asyncio.Event()
        self._initial_fences: dict[str | None, int] = {}
        self._initial_tokens: set[_InitialPublication] = set()
        # Never reuse an issued initial delivery ID during this host lifetime.
        # Reserve capacity before admitting a request, so every issued ID can
        # later be drained even after the pending entry has expired.
        self._initial_issued_ids: dict[str, tuple[str, str]] = {}
        # An issued operation remains fenced until a proven outcome settles.
        # In particular a lost response must not admit the same ID.
        self._initial_operation_uncertain: set[str] = set()
        self._retire_preview = None

    def bind_preview_retirement(self, callback):
        """Bind the host's nonblocking preview fence before requests are served."""
        if not callable(callback) or self._retire_preview is not None:
            raise ValueError("Invalid preview retirement owner")
        self._retire_preview = callback

    def _retire_entry(self, entry):
        if self._retire_preview is not None and entry.action in {"history_import", "initial_migration_queue"}:
            operation_id = entry.delivery_id if entry.action == "history_import" else entry.request["operationId"]
            self._retire_preview(entry.request["previewId"], entry.action, operation_id)

    def _unknown(self, entry, code="control_unavailable"):
        self._retire_entry(entry)
        return self._unavailable(entry, code)

    def _authorized(self, project_id):
        try:
            return project_id in self._project_ids()
        except Exception:  # noqa: BLE001 - fail closed without exposing registry errors.
            return False

    def _authorized_request(self, entry):
        return self.appearance_enabled if entry.action in appearance.APPEARANCE_ACTIONS else self._authorized(entry.request["projectId"])

    @staticmethod
    def _unavailable(entry, code="control_unavailable"):
        if entry.action in appearance.APPEARANCE_ACTIONS:
            return appearance.unavailable(entry.action, entry.request)
        if entry.action == "initial_migration_queue":
            return {"schemaVersion": 1, **{key: entry.request[key] for key in ("projectId", "previewId", "category", "operationId")},
                    **({"originalSyncId": entry.request["originalSyncId"]} if entry.request["category"] == "knowledge_recovery" else {}),
                    "state": "unknown", "code": "unknown", "readyForCutover": False}
        if entry.action == "initial_migration_receipt":
            return {"schemaVersion": 1, **entry.request, "state": "unknown", "code": "unknown", "readyForCutover": False}
        if entry.action in {"affairs_sync", "episodic_sync"}:
            return {"schemaVersion": 1, "projectId": entry.request["projectId"], "previewId": entry.request["previewId"],
                    "migrationId": entry.request.get("recoverSyncId", (affairs_migration_id if entry.action == "affairs_sync" else episodic_migration_id)(entry.request["projectId"], entry.request["previewId"])),
                    "state": "unknown", "code": "unknown", "readyForCutover": False}
        if entry.action in {"history_import", "history_import_receipt"}:
            return {"schemaVersion": 1, "projectId": entry.request["projectId"], "previewId": entry.request["previewId"],
                    "state": "unknown", "code": "unknown", "readyForCutover": False}
        if entry.action == "project_status":
            return {"schemaVersion": 1, **entry.request, "accepted": False,
                    "code": "project_unavailable" if code == "project_unavailable" else "status_unavailable"}
        return {"schemaVersion": 1, **entry.request, "state": "unknown", "code": code}

    def _expire(self):
        now = asyncio.get_running_loop().time()
        for delivery_id, entry in list(self._pending.items()):
            authorized = self._authorized_request(entry)
            if entry.deadline <= now or not authorized:
                _revoke_initial(entry)
                self._pending.pop(delivery_id)
                if not entry.future.done():
                    entry.future.set_result(self._unknown(entry, "control_unavailable" if authorized else "project_unavailable"))
        self._compact_queue()

    def _compact_queue(self):
        # Only retain unclaimed live entries. A claimed delivery never returns
        # to this queue, including after timeout, cancellation or failed settle.
        keep = []
        while not self._queue.empty():
            delivery_id = self._queue.get_nowait()
            if delivery_id in self._pending:
                keep.append(delivery_id)
        for delivery_id in keep:
            self._queue.put_nowait(delivery_id)

    async def invoke(self, action: str, request: dict, *, turn_id: str | None = None) -> dict:
        captured = _request(action, request)
        if turn_id is not None and not _opaque(turn_id, 160):
            raise ValueError("Invalid appearance turn identity")
        if action in {"history_import", "affairs_sync", "episodic_sync", "initial_migration_queue"} and turn_id != captured["turnId"]:
            raise ValueError("Invalid history turn identity")
        if action in {"initial_migration_queue", "initial_migration_receipt"} and not self.initial_migration_enabled:
            raise ValueError("Initial migration capability is unavailable")
        if action == "initial_migration_queue" and initial_model_env_unavailable():
            raise ValueError("Initial migration source model configuration unavailable")
        if action in appearance.APPEARANCE_ACTIONS:
            if not self.appearance_enabled:
                raise ValueError("Appearance control is not enabled by Launcher")
        elif not self._authorized(captured["projectId"]):
            raise ValueError("Project is not authorized by Launcher")
        loop = asyncio.get_running_loop()
        timeout = self._image_timeout if action == "operator_image_upload" else 120 if action in {"history_import", "affairs_sync", "episodic_sync", "initial_migration_queue"} else self._timeout
        entry = _Delivery(action, captured, loop.time() + timeout, loop.create_future(), turn_id=turn_id)
        self._expire()
        preview_actions = {"history_import", "affairs_sync", "episodic_sync", "initial_migration_queue"}
        if action in preview_actions and any(
                previous.action in preview_actions and previous.request["previewId"] == captured["previewId"]
                for previous in self._pending.values()):
            # Do not enqueue a second delivery or retire the preview owned by
            # the first. Unknown preserves the original key for later receipt.
            return self._unavailable(entry)
        if self._closed.is_set():
            return self._unknown(entry)
        if action == "initial_migration_queue" and (None in self._initial_fences or turn_id in self._initial_fences):
            return self._unknown(entry)
        if len(self._pending) >= self._max_pending:
            return self._unknown(entry, "control_busy")
        if action == "initial_migration_queue" and len(self._initial_issued_ids) >= 4096:
            return self._unknown(entry, "control_busy")
        if action == "initial_migration_queue" and captured["operationId"] in self._initial_operation_uncertain:
            return self._unknown(entry)
        delivery_id = secrets.token_hex(16)
        if (delivery_id in self._pending or delivery_id in self._initial_issued_ids
                or any(token.delivery_id == delivery_id for token in self._initial_tokens)):
            return self._unknown(entry, "control_busy")
        entry.delivery_id = delivery_id
        if action == "initial_migration_queue":
            self._initial_issued_ids[delivery_id] = (captured["operationId"], captured["previewId"])
            self._initial_operation_uncertain.add(captured["operationId"])
        self._pending[delivery_id] = entry
        self._queue.put_nowait(delivery_id)
        try:
            return await asyncio.wait_for(asyncio.shield(entry.future), timeout=timeout)
        except asyncio.TimeoutError:
            return self._unknown(entry)
        finally:
            _revoke_initial(entry)
            self._pending.pop(delivery_id, None)
            if not entry.future.done():
                self._retire_entry(entry)
                entry.future.cancel()
            self._compact_queue()

    async def claim(self) -> dict:
        empty = {"schemaVersion": 1, "request": None}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._claim_seconds
        while not self._closed.is_set():
            self._expire()
            remaining = deadline - loop.time()
            if remaining <= 0:
                return empty
            queued = asyncio.create_task(self._queue.get())
            closed = asyncio.create_task(self._closed.wait())
            try:
                done, _ = await asyncio.wait({queued, closed}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
                if self._closed.is_set() or queued not in done:
                    return empty
                delivery_id = queued.result()
            finally:
                for task in (queued, closed):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(queued, closed, return_exceptions=True)
            self._expire()
            entry = self._pending.get(delivery_id)
            if entry is not None:
                entry.claimed = True
                remaining = {"timeoutMs": max(1, math.floor((entry.deadline - loop.time()) * 1000))} if entry.action in {"operator_image_upload", "history_import", "affairs_sync", "episodic_sync", "initial_migration_queue"} else {}
                return {"schemaVersion": 1, "request": {"deliveryId": delivery_id, "action": entry.action, **entry.request, **remaining}}
        return empty

    def cancel_image_imports(self, turn_id: str) -> None:
        """A successful native stop retires only that Turn's unadmitted chooser."""
        for key, entry in list(self._pending.items()):
            if entry.action == "operator_image_upload" and entry.turn_id == turn_id and not entry.image_admitted:
                self._pending.pop(key)
                if not entry.future.done():
                    entry.future.set_result({"schemaVersion":1, **entry.request, "code":"cancelled", "verified":False})
        self._compact_queue()

    def cancel_history_imports(self, turn_id: str) -> None:
        """Retire this Turn's waiters after the host has fenced publication."""
        for key, entry in list(self._pending.items()):
            if entry.action in {"history_import", "affairs_sync", "episodic_sync", "initial_migration_queue"} and entry.turn_id == turn_id:
                _revoke_initial(entry)
                self._pending.pop(key)
                if not entry.future.done():
                    value = self._unknown(entry)
                    if not entry.claimed and not (entry.action in {"affairs_sync", "episodic_sync"} and "recoverSyncId" in entry.request):
                        value = {**value, "state": "rejected", "code": "cancelled"}
                    entry.future.set_result(value)
        self._compact_queue()

    def begin_initial_fence(self, turn_id=None):
        """Revoke on the event loop before a stop/registry guard wait."""
        self._initial_fences[turn_id] = self._initial_fences.get(turn_id, 0) + 1
        tokens = [token for token in self._initial_tokens
                  if not token._done.is_set() and (turn_id is None or token.turn_id == turn_id)]
        for token in tokens:
            token.revoke()
        for key, entry in list(self._pending.items()):
            if entry.action != "initial_migration_queue" or (turn_id is not None and entry.turn_id != turn_id):
                continue
            if entry.initial_token is not None:
                entry.initial_token.revoke()
            self._pending.pop(key)
            if not entry.future.done():
                entry.future.set_result(self._unknown(entry))
        self._compact_queue()
        return tokens

    def end_initial_fence(self, turn_id=None):
        count = self._initial_fences[turn_id] - 1
        if count:
            self._initial_fences[turn_id] = count
        else:
            del self._initial_fences[turn_id]

    def begin_initial_drain(self, delivery_id, operation_id):
        """Revoke an exact claimed delivery, including an expired in-flight worker."""
        if not self.initial_migration_enabled:
            return False, None
        issued = self._initial_issued_ids.get(delivery_id)
        if issued is None or issued[0] != operation_id:
            return False, None
        entry = self._pending.get(delivery_id)
        related = [item for item in self._initial_tokens if item.delivery_id == delivery_id]
        if (entry is not None and (not entry.claimed or entry.action != "initial_migration_queue"
                                  or entry.request["operationId"] != operation_id)
                or any(item.operation_id != operation_id for item in related)):
            return False, None
        if entry is not None and any(item is not entry.initial_token for item in related):
            # A broken or reused delivery identity cannot acknowledge one
            # worker while a different worker with that ID is still retained.
            return False, None
        if self._retire_preview is not None:
            self._retire_preview(issued[1], "initial_migration_queue", operation_id)
        if (entry is not None and entry.claimed and entry.action == "initial_migration_queue"
                and entry.request["operationId"] == operation_id):
            token = entry.initial_token
            if token is not None:
                token.revoke()
            self._pending.pop(delivery_id)
            if not entry.future.done():
                entry.future.set_result(self._unknown(entry))
            self._compact_queue()
            return True, token
        token = next((item for item in self._initial_tokens
                      if item.delivery_id == delivery_id and item.operation_id == operation_id), None)
        if token is None:
            # The issued ID cannot be reused, and without a pending entry a
            # delayed prepare cannot admit a worker after this acknowledgement.
            return True, None
        token.revoke()
        return True, token

    @staticmethod
    def drain_initial_fence(tokens, timeout=2.0):
        deadline = time.monotonic() + timeout
        return all(token.drain(deadline - time.monotonic()) for token in tokens)

    def initial_delivery(self, delivery_id, request, *, admit=False, confirm=False, busy=False):
        """Check one claimed, live, exact native-policy-admitted delivery."""
        self._expire()
        entry = self._pending.get(delivery_id) if type(delivery_id) is str else None
        if (not self.initial_migration_enabled or self._closed.is_set() or entry is None or not entry.claimed
                or entry.action != "initial_migration_queue" or entry.request != request
                or None in self._initial_fences or entry.turn_id in self._initial_fences
                or not self._authorized_request(entry) or (admit and (entry.initial_admitted or initial_model_env_unavailable()))
                or (not admit and not entry.initial_admitted)):
            return False
        if admit:
            # Keep completed identities for a lost drain response. Reclaim
            # only under the bound; in-flight workers are never evicted.
            if len(self._initial_tokens) >= 512:
                self._initial_tokens = {token for token in self._initial_tokens if not token._done.is_set()}
            if len(self._initial_tokens) >= 512:
                return False
            entry.initial_admitted = True
            entry.initial_token = _InitialPublication(time.monotonic() + max(0, entry.deadline - asyncio.get_running_loop().time()),
                                                      entry.turn_id, delivery_id, entry.request["operationId"])
            self._initial_tokens.add(entry.initial_token)
        if confirm:
            if entry.initial_token is None or not entry.initial_token.published():
                return False
            entry.initial_prepared = True
        if busy and (entry.initial_token is None or not entry.initial_token.confirm_busy()):
            return False
        return entry.initial_token if admit else True

    def admit_image_import(self, delivery_id: str, kind: str) -> bool:
        """One live chooser result may enter the canonical writer; no upload replay."""
        if type(delivery_id) is not str or re.fullmatch(r"[0-9a-f]{32}", delivery_id) is None or kind not in {"avatar", "background"}:
            return False
        self._expire()
        entry = self._pending.get(delivery_id)
        if (entry is None or not self.appearance_enabled or self._closed.is_set() or not entry.claimed
                or entry.action != "operator_image_upload" or entry.request["kind"] != kind or entry.image_admitted):
            return False
        entry.image_admitted = True
        return True

    def settle(self, delivery_id: str, result: dict) -> bool:
        if type(delivery_id) is not str or re.fullmatch(r"[0-9a-f]{32}", delivery_id) is None:
            raise ValueError("Invalid main control delivery")
        self._expire()
        entry = self._pending.get(delivery_id)
        if entry is None or not entry.claimed or self._closed.is_set():
            return False
        if entry.action == "initial_migration_queue" and type(result) is dict and result.get("state") == "queued" and not entry.initial_prepared:
            raise ValueError("Initial migration source not prepared")
        if (entry.action == "initial_migration_queue" and type(result) is dict and result.get("state") == "rejected"
                and result.get("code") == "busy" and (entry.initial_token is None or not entry.initial_token.busy_confirmed()
                    or None in self._initial_fences or entry.turn_id in self._initial_fences or not self._authorized_request(entry))):
            raise ValueError("Initial migration busy unconfirmed")
        captured = _result(entry.action, entry.request, result)
        if (entry.action == "initial_migration_queue" and (captured["state"], captured["code"])
                in {("rejected", "busy"), ("queued", "queued")}):
            self._initial_operation_uncertain.discard(entry.request["operationId"])
        if entry.action in {"history_import", "initial_migration_queue"} and captured.get("state") not in {"published", "queued"}:
            self._retire_entry(entry)
        _revoke_initial(entry)
        self._pending.pop(delivery_id)
        entry.future.set_result(captured)
        return True

    def close(self) -> None:
        self._closed.set()
        for entry in self._pending.values():
            _revoke_initial(entry)
            if not entry.future.done():
                entry.future.set_result(self._unknown(entry))
        self._pending.clear()
        self._compact_queue()
