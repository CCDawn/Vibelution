"""Bounded manager-owned evolution metadata and fenced native controls.

Reads use a capability-protected loopback endpoint owned by the existing daemon.
They never enqueue commands, initialize storage, or invoke repairing run getters.
Mutations retain the existing manager queue and the original run-state locks.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from . import constants, process_identity, state_store

SCHEMA_VERSION = 1
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10000
READ_TIMEOUT_SECONDS = 2.0
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_REVISION = re.compile(r"[a-f0-9]{64}\Z")
_KINDS = {"supervised", "self"}
_STATUSES = {"queued", "running", "stopping", "paused", "done", "failed", "cancelled", "unknown"}
_ROW_KEYS = {"runId", "status", "agentId", "sessionId", "teamId", "flowId", "pauseRequested",
             "stopRequested", "finishedAt", "commands", "revision"}


class Unavailable(RuntimeError):
    """The current manager cannot prove a complete observation or acknowledgement."""


class Conflict(RuntimeError):
    """The observed native owner or control state changed."""


class NotFound(LookupError):
    """The current manager has no such in-memory run slot."""


class InputError(ValueError):
    """An input is outside the closed metadata/control protocol."""


def _token(value, *, empty=False):
    if empty and value in (None, ""):
        return ""
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise InputError("Invalid evolution identity")
    return value


def _kind(value):
    if not isinstance(value, str) or value not in _KINDS:
        raise InputError("Invalid evolution kind")
    return value


def public_identity(value):
    try:
        pid, created, executable = value["pid"], value["createTime"], value["executable"]
        if (type(pid) is not int or pid <= 0 or type(created) not in (int, float)
                or not 0 < created < 10**12 or not isinstance(executable, str)
                or not executable or len(executable) > 4096):
            raise ValueError
        return {"pid": pid, "createTime": float(created), "executable": executable}
    except (KeyError, TypeError, ValueError):
        raise Unavailable("Manager identity unavailable") from None


def _same_identity(left, right):
    return public_identity(left) == public_identity(right)


def metadata_row(kind, raw, owner, *, live_context):
    """Select only control metadata; caller holds the original run-state lock."""
    _kind(kind)
    owner = public_identity(owner)
    rid = _token(raw.get("runId"))
    status = raw.get("status")
    if status not in _STATUSES:
        status = "unknown"
    flags = {}
    for key in ("pauseRequested", "stopRequested", "cancelRequested"):
        value = raw.get(key, False)
        if type(value) is not bool:
            raise Unavailable("Invalid native control state")
        flags[key] = value
    action = raw.get("controlAction") or ""
    if kind == "self" and action not in {"", "pause", "terminate"}:
        raise Unavailable("Invalid native control intent")
    pause = flags["pauseRequested"] or kind == "self" and action == "pause"
    stop = flags["stopRequested"] or flags["cancelRequested"] or kind == "self" and action == "terminate"
    finished = raw.get("finishedAt") or ""
    if not isinstance(finished, str) or finished and not re.fullmatch(r"[0-9TZ:+.\-]{1,80}", finished):
        raise Unavailable("Invalid native terminal metadata")
    control = raw.get("runtimeManagerControl")
    control = control if isinstance(control, dict) else {}
    live = (live_context and control.get("kind") == kind and type(control.get("ownerPid")) is int
            and control["ownerPid"] == owner["pid"])
    commands = []
    if live and not finished and status in {"queued", "running", "paused"} and not stop:
        commands = ["stop", "resume" if status == "paused" or pause else "pause"]
    row = {"runId": rid, "status": status,
           **{key: _token(raw.get(key), empty=True) for key in ("agentId", "sessionId", "teamId", "flowId")},
           "pauseRequested": bool(pause), "stopRequested": bool(stop), "finishedAt": finished,
           "commands": commands}
    # The counter belongs to the original run snapshot and advances inside the
    # native action lock, including actions initiated through legacy controls.
    # Native timestamps have only second precision and cannot fence ABA alone.
    cursor = {key: raw.get(key) for key in ("updatedAt", "pauseRequestedAt", "stopRequestedAt",
              "cancelRequestedAt", "controlRequestedAt", "resumeCount", "controlRevision")}
    control_revision = raw.get("controlRevision", 0)
    if type(control_revision) is not int or not 0 <= control_revision < 2**63:
        raise Unavailable("Invalid native control revision")
    for value in cursor.values():
        if value is not None and (type(value) not in (str, int) or isinstance(value, str) and len(value) > 160):
            raise Unavailable("Invalid native revision metadata")
    row["revision"] = hashlib.sha256(json.dumps([kind, owner, row, cursor], sort_keys=True,
                                               separators=(",", ":")).encode()).hexdigest()
    return row


def advance_control_revision(raw):
    """Advance the existing run's native control cursor while its lock is held."""
    revision = raw.get("controlRevision", 0)
    if type(revision) is not int or not 0 <= revision < 2**63 - 1:
        raise Unavailable("Invalid native control revision")
    raw["controlRevision"] = revision + 1


def require_expected(kind, raw, expected_revision, expected_owner, *, live_context):
    """Compare and mutate under the same native lock, never a wrapper lock."""
    if expected_revision is None and expected_owner is None:
        return
    if not isinstance(expected_revision, str) or not _REVISION.fullmatch(expected_revision) or expected_owner is None:
        raise InputError("Missing native control fence")
    owner = public_identity(expected_owner)
    if owner["pid"] != os.getpid() or not _same_identity(owner, process_identity.capture_process_identity(os.getpid())):
        raise Conflict("Manager owner changed")
    if raw is None or not live_context:
        raise NotFound("Native run slot unavailable")
    row = metadata_row(kind, raw, owner, live_context=live_context)
    if row["revision"] != expected_revision or not row["commands"]:
        raise Conflict("Native control state changed")


def _validate_row(row):
    if not isinstance(row, dict) or set(row) != _ROW_KEYS:
        raise Unavailable("Invalid manager metadata response")
    try:
        _token(row["runId"])
        for key in ("agentId", "sessionId", "teamId", "flowId"):
            _token(row[key], empty=True)
    except InputError:
        raise Unavailable("Invalid manager metadata identity") from None
    if (row["status"] not in _STATUSES or type(row["pauseRequested"]) is not bool
            or type(row["stopRequested"]) is not bool or not isinstance(row["finishedAt"], str)
            or row["finishedAt"] and not re.fullmatch(r"[0-9TZ:+.\-]{1,80}", row["finishedAt"])
            or not isinstance(row["commands"], list)
            or row["commands"] not in ([], ["stop", "pause"], ["stop", "resume"])
            or not isinstance(row["revision"], str) or not _REVISION.fullmatch(row["revision"])):
        raise Unavailable("Invalid manager metadata response")
    return row


def _observe_owner(project_root):
    """Observe existing identity and role without starting or repairing anything."""
    try:
        import psutil
        if Path(project_root).resolve() != Path(constants.PROJECT_ROOT).resolve():
            raise Unavailable("Manager project mismatch")
        record = state_store.load_pid_identity()
        owner = public_identity(record)
        if (state_store.load_pid() != owner["pid"]
                or process_identity.inspect_process_identity(owner).get("status") != "match"
                or not process_identity.is_runtime_manager_process(owner["pid"])
                or Path(psutil.Process(owner["pid"]).cwd()).resolve() != Path(project_root).resolve()):
            raise Unavailable("Current manager identity unavailable")
        endpoint = record.get("evolutionControl")
        if (not isinstance(endpoint, dict) or set(endpoint) != {"schemaVersion", "port", "capability"}
                or type(endpoint["schemaVersion"]) is not int or endpoint["schemaVersion"] != SCHEMA_VERSION
                or type(endpoint["port"]) is not int
                or not 1 <= endpoint["port"] <= 65535 or not isinstance(endpoint["capability"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", endpoint["capability"])):
            raise Unavailable("Manager metadata protocol unavailable")
        return owner, endpoint
    except Unavailable:
        raise
    except Exception:
        raise Unavailable("Current manager identity unavailable") from None


def read_inventory(project_root, kind, *, run_id=None):
    """Read actual manager memory; no filesystem or command-queue writes."""
    _kind(kind)
    if run_id is not None:
        _token(run_id)
    owner, endpoint = _observe_owner(project_root)
    query = {"kind": kind}
    if run_id is not None:
        query["runId"] = run_id
    connection = http.client.HTTPConnection("127.0.0.1", endpoint["port"], timeout=READ_TIMEOUT_SECONDS)
    try:
        connection.request("GET", "/evolution/metadata?" + urlencode(query),
                           headers={"Authorization": "Bearer " + endpoint["capability"], "Connection": "close"})
        response = connection.getresponse()
        data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise Unavailable("Manager metadata response exceeds limit")
        after_owner, after_endpoint = _observe_owner(project_root)
        if not _same_identity(owner, after_owner) or endpoint != after_endpoint:
            raise Unavailable("Manager changed during metadata read")
        if response.status == 404:
            raise NotFound("Native run slot unavailable")
        if response.status != 200:
            raise Unavailable("Manager metadata unavailable")
        payload = json.loads(data)
        if (not isinstance(payload, dict) or set(payload) != {"schemaVersion", "kind", "owner", "rows", "complete"}
                or type(payload["schemaVersion"]) is not int or payload["schemaVersion"] != SCHEMA_VERSION
                or payload["kind"] != kind or set(payload["owner"]) != {"pid", "createTime", "executable"}
                or payload["complete"] is not True or not _same_identity(owner, payload["owner"])
                or not isinstance(payload["rows"], list) or len(payload["rows"]) > MAX_ROWS):
            raise Unavailable("Invalid manager metadata response")
        rows = [_validate_row(row) for row in payload["rows"]]
        if len({row["runId"] for row in rows}) != len(rows):
            raise Unavailable("Ambiguous native run slots")
        if run_id is not None and (len(rows) != 1 or rows[0]["runId"] != run_id):
            raise Unavailable("Native run identity changed")
        return payload
    except (Unavailable, NotFound, InputError):
        raise
    except Exception:
        raise Unavailable("Manager metadata unavailable") from None
    finally:
        connection.close()


def _legacy_command(project_root, kind, run_id, action, expected_revision):
    """Submit exactly one fenced command to an already running manager."""
    _kind(kind)
    _token(run_id)
    if not isinstance(action, str) or action not in {"stop", "pause", "resume"} or not isinstance(expected_revision, str) or not _REVISION.fullmatch(expected_revision):
        raise InputError("Invalid native control request")
    before = read_inventory(project_root, kind, run_id=run_id)
    if before["rows"][0]["revision"] != expected_revision or action not in before["rows"][0]["commands"]:
        raise Conflict("Native control state changed")
    from .command_queue import submit_command, wait_for_result
    try:
        queued = submit_command("managed_evolution_control", args={"kind": kind, "runId": run_id,
            "action": action, "expectedRevision": expected_revision, "owner": before["owner"]},
            requested_by="external_management")
        result = wait_for_result(queued["commandId"])
        if result.get("ok") is not True:
            error = {"Conflict": Conflict, "NotFound": NotFound, "InputError": InputError}.get(result.get("errorType"), Unavailable)
            raise error("Native evolution control was not confirmed")
        row = _validate_row(result.get("operation"))
        if row["runId"] != run_id or result.get("revisionCheck") != "native_cas" or result.get("accepted") is not True:
            raise Unavailable("Native evolution control was not confirmed")
        return {"operation": row, "accepted": True, "stopRequested": row["stopRequested"] or row["status"] == "cancelled",
                "revisionCheck": "native_cas"}
    except (Unavailable, Conflict, NotFound, InputError):
        raise
    except Exception:
        # Lost acknowledgement never authorizes a retry or manager restart.
        raise Unavailable("Native evolution control acknowledgement unavailable") from None


def read_command_outcome(project_root, kind, run_id, action, expected_revision, *, request_id):
    """Recover only the original native proof, including after daemon restart."""
    from .command_queue import ManagedCommandConflict, ManagedCommandUnavailable, read_managed_command_record

    try:
        command_id, state, result = read_managed_command_record(project_root, request_id, kind, run_id, action, expected_revision)
        if state == "unconfirmed":
            state = "unknown"
        row = None
        if state == "completed":
            row = _validate_row(result.get("operation"))
            if (row["runId"] != run_id or result.get("revisionCheck") != "native_cas"
                    or result.get("accepted") is not True):
                raise Unavailable("Original native control proof incomplete")
        return {"commandId": command_id, "state": state, "operation": row,
                "accepted": state == "completed", "stopRequested": bool(action == "stop" and row and (row["stopRequested"] or row["status"] == "cancelled")),
                "revisionCheck": "native_cas" if row else None}
    except ManagedCommandConflict:
        raise Conflict("Original native command binding changed") from None
    except ManagedCommandUnavailable:
        raise Unavailable("Original native command evidence unavailable") from None
    except ValueError:
        raise InputError("Invalid native command lookup") from None


def command(project_root, kind, run_id, action, expected_revision, *, request_id=""):
    """Submit once, or recover the same native queue receipt without replay."""
    if not request_id:
        return _legacy_command(project_root, kind, run_id, action, expected_revision)
    from .command_queue import (ManagedCommandConflict, ManagedCommandUnavailable, read_managed_command_record,
                                submit_managed_evolution_command, wait_for_result)

    prior = read_command_outcome(project_root, kind, run_id, action, expected_revision, request_id=request_id)
    if prior["state"] == "completed":
        return {key: prior[key] for key in ("operation", "accepted", "stopRequested", "revisionCheck")}
    if prior["state"] == "rejected":
        raise Conflict("Original native control request was rejected")
    try:
        command_id = prior["commandId"]
        if prior["state"] == "unknown":
            _, native_state, _ = read_managed_command_record(
                project_root, request_id, kind, run_id, action, expected_revision)
            if native_state == "unconfirmed":
                raise Unavailable("Original native control result is unconfirmed")
            before = read_inventory(project_root, kind, run_id=run_id)
            row = before["rows"][0]
            if row["revision"] != expected_revision or action not in row["commands"]:
                raise Conflict("Native control state changed")
            queued = submit_managed_evolution_command(project_root, request_id, args={"kind": kind, "runId": run_id,
                "action": action, "expectedRevision": expected_revision, "owner": before["owner"]})
            command_id = queued["commandId"]
        # Pending evidence is joined, never enqueued again, even if the old
        # daemon exited and the current manager has no matching slot.
        wait_for_result(command_id)
        outcome = read_command_outcome(project_root, kind, run_id, action, expected_revision, request_id=request_id)
        if outcome["state"] == "rejected":
            raise Conflict("Original native control request was rejected")
        if outcome["state"] != "completed":
            raise Unavailable("Original native control acknowledgement unavailable")
        return {key: outcome[key] for key in ("operation", "accepted", "stopRequested", "revisionCheck")}
    except ManagedCommandConflict:
        raise Conflict("Original native command binding changed") from None
    except (ManagedCommandUnavailable, TimeoutError):
        raise Unavailable("Original native control acknowledgement unavailable") from None
    except (Unavailable, Conflict, NotFound, InputError):
        raise
    except Exception:
        raise Unavailable("Original native control acknowledgement unavailable") from None


def snapshot(kind, owner, *, run_id=None):
    """Manager-only dispatch to pure metadata functions on the native owners."""
    _kind(kind)
    from core.web.services import self_evolution_control_service, supervised_control_service
    service = supervised_control_service if kind == "supervised" else self_evolution_control_service
    rows = service.read_managed_evolution_metadata(public_identity(owner), run_id=run_id)
    if len(rows) > MAX_ROWS or any(row["status"] == "unknown" for row in rows):
        raise Unavailable("Native metadata inventory exceeds limit")
    return {"schemaVersion": SCHEMA_VERSION, "kind": kind, "owner": public_identity(owner), "rows": rows, "complete": True}


class MetadataServer:
    """Fixed read protocol, not a general callable or method-dispatch RPC."""

    def __init__(self, owner):
        self.owner = public_identity(owner)
        self.capability = secrets.token_urlsafe(32)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                self.request.settimeout(READ_TIMEOUT_SECONDS)
                super().setup()

            def log_message(self, *_args):
                pass  # Never log the capability or untrusted request headers.

            def _reply(self, status, payload):
                data = json.dumps(payload, separators=(",", ":")).encode()
                if len(data) > MAX_RESPONSE_BYTES:
                    status, data = 503, b'{"code":"unavailable"}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)
                self.close_connection = True

            def do_GET(self):
                try:
                    if (not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + outer.capability)
                            or len(self.path) > 512 or self.headers.get("Content-Length", "0") != "0"
                            or self.headers.get("Transfer-Encoding") is not None):
                        self._reply(403, {"code": "forbidden"})
                        return
                    parsed = urlsplit(self.path)
                    query = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True, max_num_fields=2)
                    if (parsed.path != "/evolution/metadata" or parsed.scheme or parsed.netloc or parsed.fragment
                            or set(query) - {"kind", "runId"} or "kind" not in query
                            or any(len(values) != 1 for values in query.values())):
                        raise InputError("Invalid metadata request")
                    kind = _kind(query["kind"][0])
                    rid = _token(query["runId"][0]) if "runId" in query else None
                    self._reply(200, snapshot(kind, outer.owner, run_id=rid))
                except NotFound:
                    self._reply(404, {"code": "not_found"})
                except (InputError, ValueError):
                    self._reply(400, {"code": "invalid_input"})
                except Exception:
                    self._reply(503, {"code": "unavailable"})

            def do_POST(self):
                self._reply(405, {"code": "method_not_allowed"})

            do_HEAD = do_POST
            do_PUT = do_POST
            do_DELETE = do_POST
            do_PATCH = do_POST
            do_OPTIONS = do_POST
            do_TRACE = do_POST
            do_CONNECT = do_POST

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = False

            def __init__(self):
                self.slots = threading.BoundedSemaphore(8)
                super().__init__(("127.0.0.1", 0), Handler)

            def process_request(self, request, client_address):
                if not self.slots.acquire(blocking=False):
                    self.shutdown_request(request)
                    return
                try:
                    super().process_request(request, client_address)
                except Exception:
                    self.slots.release()
                    raise

            def process_request_thread(self, request, client_address):
                try:
                    super().process_request_thread(request, client_address)
                finally:
                    self.slots.release()

            def handle_error(self, *_args):
                pass

        self._server = Server()
        self._thread = threading.Thread(target=lambda: self._server.serve_forever(poll_interval=0.1),
                                        name="manager-evolution-metadata", daemon=True)

    def start(self):
        self._thread.start()
        return {"schemaVersion": SCHEMA_VERSION, "port": self._server.server_port, "capability": self.capability}

    def close(self):
        if self._thread.is_alive():
            self._server.shutdown()
        self._server.server_close()
        if self._thread.is_alive():
            self._thread.join(timeout=READ_TIMEOUT_SECONDS)
