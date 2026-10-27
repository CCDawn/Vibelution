"""Bounded, ephemeral transport to Electron main; never a lifecycle authority.

An expired delivery is forgotten, never replayed. A native command already
accepted by main outlives this transport and is queried using its requestId.
All methods belong to the host event loop, including settle and close.
"""

from __future__ import annotations

import asyncio
import math
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass

from . import appearance_protocol as appearance


_OPERATIONS = {"start", "stop", "restart"}
_ACTIONS = {"project_status", "project_lifecycle", "project_lifecycle_receipt", "history_import"}
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


def _request(action, request):
    if type(action) is str and action in appearance.APPEARANCE_ACTIONS:
        return appearance.validate_request(action, request)
    if type(action) is not str or action not in _ACTIONS or type(request) is not dict:
        raise ValueError("Invalid main control request")
    if action == "history_import":
        if (set(request) != {"projectId", "previewId", "turnId"}
                or not _opaque(request.get("projectId"), 160)
                or type(request.get("previewId")) is not str
                or re.fullmatch(r"[0-9a-f]{64}", request["previewId"]) is None
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
    turn_id: str | None = None


class MainControlBroker:
    def __init__(self, project_ids: Callable, *, timeout_seconds=20, claim_seconds=10, max_pending=32, appearance_enabled=False, image_timeout_seconds=appearance.IMAGE_SELECTION_SECONDS):
        if (not callable(project_ids) or type(max_pending) is not int or not 1 <= max_pending <= 128
                or any(type(value) not in {int, float} or not math.isfinite(value) or value <= 0
                       for value in (timeout_seconds, claim_seconds))
                or timeout_seconds > 20 or claim_seconds > 10):
            raise ValueError("Invalid main control transport limits")
        if type(appearance_enabled) is not bool or type(image_timeout_seconds) not in {int, float} or not math.isfinite(image_timeout_seconds) or not 0 < image_timeout_seconds <= appearance.IMAGE_SELECTION_SECONDS:
            raise ValueError("Invalid appearance transport limits")
        self.appearance_enabled = appearance_enabled
        self._image_timeout = image_timeout_seconds
        self._project_ids = project_ids
        self._timeout = timeout_seconds
        self._claim_seconds = claim_seconds
        self._max_pending = max_pending
        self._queue = asyncio.Queue(maxsize=max_pending)
        self._pending: dict[str, _Delivery] = {}
        self._closed = asyncio.Event()

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
        if entry.action == "history_import":
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
                self._pending.pop(delivery_id)
                if not entry.future.done():
                    entry.future.set_result(self._unavailable(entry, "control_unavailable" if authorized else "project_unavailable"))
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
        if action == "history_import" and turn_id != captured["turnId"]:
            raise ValueError("Invalid history turn identity")
        if action in appearance.APPEARANCE_ACTIONS:
            if not self.appearance_enabled:
                raise ValueError("Appearance control is not enabled by Launcher")
        elif not self._authorized(captured["projectId"]):
            raise ValueError("Project is not authorized by Launcher")
        loop = asyncio.get_running_loop()
        timeout = self._image_timeout if action == "operator_image_upload" else 120 if action == "history_import" else self._timeout
        entry = _Delivery(action, captured, loop.time() + timeout, loop.create_future(), turn_id=turn_id)
        self._expire()
        if self._closed.is_set():
            return self._unavailable(entry)
        if len(self._pending) >= self._max_pending:
            return self._unavailable(entry, "control_busy")
        delivery_id = secrets.token_hex(16)
        self._pending[delivery_id] = entry
        self._queue.put_nowait(delivery_id)
        try:
            return await asyncio.wait_for(asyncio.shield(entry.future), timeout=timeout)
        except asyncio.TimeoutError:
            return self._unavailable(entry)
        finally:
            self._pending.pop(delivery_id, None)
            if not entry.future.done():
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
                remaining = {"timeoutMs": max(1, math.floor((entry.deadline - loop.time()) * 1000))} if entry.action in {"operator_image_upload", "history_import"} else {}
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
            if entry.action == "history_import" and entry.turn_id == turn_id:
                self._pending.pop(key)
                if not entry.future.done():
                    value = self._unavailable(entry)
                    if not entry.claimed:
                        value = {**value, "state": "rejected", "code": "cancelled"}
                    entry.future.set_result(value)
        self._compact_queue()

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
        captured = _result(entry.action, entry.request, result)
        self._pending.pop(delivery_id)
        entry.future.set_result(captured)
        return True

    def close(self) -> None:
        self._closed.set()
        for entry in self._pending.values():
            if not entry.future.done():
                entry.future.set_result(self._unavailable(entry))
        self._pending.clear()
        self._compact_queue()
