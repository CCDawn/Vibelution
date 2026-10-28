"""Launcher-owned references to native external-Agent tasks.

The host injects its authorized project registry and drives heartbeat/reconcile.
This adapter never owns Sessions, Turn state, leases, or a second transcript.
Discarding an adapter/client is deliberately different from MCP shutdown: only
an explicit cancel calls the native cancellation API. Native lease expiry and
eligibility revocation continue to apply even while the Launcher is offline.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock
from types import MappingProxyType
from typing import Any

import anyio

from core.external_agent.backend_client import (
    BackendClientError,
    ManagedAgentBackendClient,
    _checkout_revision,
)
from core.external_agent.contracts import TASK_TERMINAL_STATUSES
from core.infrastructure.atomic_io import atomic_write_json

_DISPATCH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}\Z")
_DRAIN_ADMISSION_TIMEOUT = 5.0
_DRAIN_RECORD_TIMEOUT = 20.0
_DRAIN_OBSERVE_TIMEOUT = 60.0
_DRAIN_HEARTBEAT_INTERVAL = 10.0
_NATIVE_REQUEST_TIMEOUT = 30.0
_RECEIPT_FIELDS = frozenset({
    "taskId", "status", "effectivePermissionProfile", "createdAt", "updatedAt",
    "completedAt", "resultSummary", "error", "pendingApprovals", "pollAfterMs",
    "shouldPoll", "guideUri", "guideVersion",
})


class DispatchError(RuntimeError):
    """Bounded adapter error; raw backend exceptions and credentials stay private."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class _ActiveProjectClient:
    """A verified SDK client owned by one in-progress project operation."""

    def __init__(self, client: ManagedAgentBackendClient) -> None:
        self.client = client
        self.closing = False
        self.borrowers = 0
        self.drained = anyio.Event()

    def borrow(self) -> bool:
        if self.closing:
            return False
        if self.borrowers == 0:
            self.drained = anyio.Event()
        self.borrowers += 1
        return True

    def release(self) -> None:
        self.borrowers -= 1
        if self.borrowers == 0:
            self.drained.set()


async def _bounded_native_request(awaitable: Awaitable[Any]) -> Any:
    try:
        with anyio.fail_after(_NATIVE_REQUEST_TIMEOUT):
            return await awaitable
    except TimeoutError:
        raise DispatchError("Native task request timed out.", code="BACKEND_TIMEOUT") from None


async def _checked_task_receipt(client: Any, task_id: str) -> dict[str, Any]:
    if not isinstance(task_id, str) or not task_id:
        raise DispatchError("Invalid native task reference.", code="BACKEND_PROTOCOL_ERROR")
    payload = await _bounded_native_request(client.get_task(task_id=task_id))
    if not isinstance(payload, dict) or payload.get("taskId") != task_id:
        raise DispatchError("Invalid native task reference.", code="BACKEND_PROTOCOL_ERROR")
    return payload


class DispatchDrainFence:
    """Single-owner observation scope; successful proof retains record locks."""

    def __init__(self, service: "DispatchService", token: object) -> None:
        self._service = service
        self._token = token
        self._task_id = anyio.get_current_task().id
        self._sealed_locks: list[anyio.Lock] = []
        self._sealed = False

    async def observe(self) -> dict[str, Any]:
        """Poll every original record; return drained only with durable terminal receipts.

        A successful result remains valid only while this fence stays open,
        the host is the sole profile writer, and all other producers are fenced.
        Failure is retryable and does not cancel tasks or stop heartbeat.
        """
        service = self._service
        if anyio.get_current_task().id != self._task_id:
            raise DispatchError("Dispatch drain has a different task owner.", code="DISPATCH_DRAIN_OWNER")
        service._check_fence_owner(self._token)
        if self._sealed:
            raise DispatchError("Dispatch drain is already sealed.", code="DISPATCH_DRAIN_SEALED")
        try:
            with anyio.fail_after(_DRAIN_OBSERVE_TIMEOUT):
                return await self._observe()
        except TimeoutError:
            return {"drained": False, "reason": "records_unknown"}

    async def _observe(self) -> dict[str, Any]:
        service = self._service
        paths = service._drain_record_paths()
        if paths is None:
            return {"drained": False, "reason": "records_unknown"}
        blocked = ""
        ids: list[str] = []
        for path in paths:
            if path.is_symlink() or not path.is_file() or path.suffix != ".json" or not _DISPATCH_ID.fullmatch(path.stem):
                blocked = "records_unknown"
                continue
            ids.append(path.stem)
        results = await service._refresh_batch(ids, include_terminal=True)
        if len(results) != len(ids):
            blocked = "records_unknown"
        for result in results:
            receipt = result.get("receipt")
            if (result.get("lastError") is not None or not isinstance(receipt, dict)
                    or receipt.get("status") not in TASK_TERMINAL_STATUSES
                    or not result.get("nativeTaskId") or receipt.get("taskId") != result["nativeTaskId"]
                    or receipt.get("pendingApprovals") not in (None, [])):
                blocked = blocked or "not_terminal"
        if blocked:
            return {"drained": False, "reason": blocked}
        # Seal only after every remote read settles. Lock all records and
        # re-read durable evidence so concurrent heartbeat cannot invalidate it.
        locks: list[anyio.Lock] = []
        try:
            for path in paths:
                lock = service._dispatch_lock(path.stem)
                try:
                    with anyio.fail_after(_DRAIN_RECORD_TIMEOUT):
                        await lock.acquire()
                except TimeoutError:
                    return {"drained": False, "reason": "records_unknown"}
                locks.append(lock)
            service._check_fence_owner(self._token)
            if service._drain_record_paths() != paths:
                return {"drained": False, "reason": "records_changed"}
            for path in paths:
                try:
                    row = service._read(path.stem)
                    receipt = row.get("receipt")
                    if (not isinstance(receipt, dict) or receipt.get("status") not in TASK_TERMINAL_STATUSES
                            or not row.get("nativeTaskId") or receipt.get("taskId") != row["nativeTaskId"]
                            or receipt.get("pendingApprovals") not in (None, [])
                            or row.get("lastError") is not None):
                        return {"drained": False, "reason": "records_changed"}
                except (DispatchError, OSError, ValueError, TypeError):
                    return {"drained": False, "reason": "records_unknown"}
            self._sealed_locks = locks
            self._sealed = True
            locks = []
            return {"drained": True, "recordCount": len(paths)}
        finally:
            for lock in reversed(locks):
                lock.release()

    def _close(self) -> None:
        for lock in reversed(self._sealed_locks):
            lock.release()
        self._sealed_locks.clear()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lexical_root(value: str | Path) -> Path:
    """Normalize main's binding without following a changed physical root."""
    if "\x00" in os.fspath(value):
        raise ValueError("Invalid project root")
    return Path(os.path.abspath(value))


class DispatchService:
    """Single host owner for a profile's dispatch references.

    ``projects`` must come from the host's authorized registry, never tool input.
    All path arguments and client factories are construction-time capabilities.
    Public operations accept only registry IDs and opaque dispatch/task refs.
    The host must keep one service per profile; atomic writes protect file
    integrity, but they are not a multi-process scheduler or ownership lock.
    """

    def __init__(
        self,
        profile_root: Path,
        projects: Mapping[str, Path],
        *,
        client_factory: Callable[..., Any] = ManagedAgentBackendClient,
        projects_suspended: bool = False,
    ) -> None:
        self._root = Path(profile_root).expanduser().resolve() / "assistant_dispatch"
        self._projects = MappingProxyType({
            str(project_id): _lexical_root(Path(path).expanduser())
            for project_id, path in projects.items()
        })
        # The first main-supplied envelope establishes the version, including
        # a valid revision-zero initial authorization. Zero is not an already
        # accepted empty snapshot.
        self._registry_revision = -1
        # Invalidates only reads explicitly bound to a live registry gate.
        # Ordinary admitted transactions and heartbeat retain their contract.
        self._registry_gate_generation = 0
        self._seen_projects = dict(self._projects)
        self._revoked_projects: set[str] = set()
        self._client_factory = client_factory
        # Main may narrow admission while native recovery/tool threads exist.
        # Keep this synchronous and independent of an asyncio loop or SDK.
        self._projects_suspended = Event()
        if projects_suspended:
            self._projects_suspended.set()
        self._dispatch_locks: dict[str, anyio.Lock] = {}
        self._project_locks: dict[str, anyio.Lock] = {}
        self._active_project_clients: dict[str, _ActiveProjectClient] = {}
        self._dispatch_admission = anyio.Lock()
        self._dispatch_state = RLock()
        self._dispatch_fence_owner: object | None = None
        from .management import ManagementAdapter
        self.management = ManagementAdapter(profile_root, self._admitted_projects, self._call)

    def suspend_projects(self) -> dict:
        """Narrow project admissions without changing grants or native history."""
        with self._dispatch_state:
            self._check_registry_unfenced()
            self._projects_suspended.set()
            self._registry_gate_generation += 1
            return {"schemaVersion": 1, "revision": self._registry_revision, "projectsSuspended": True}

    def _admitted_projects(self) -> Mapping[str, Path]:
        if self._projects_suspended.is_set():
            raise DispatchError("Project registry requires reconciliation.", code="PROJECT_REGISTRY_RECONCILE_REQUIRED")
        return self._projects

    def _check_dispatch_unfenced(self) -> None:
        with self._dispatch_state:
            if self._dispatch_fence_owner is not None:
                raise DispatchError("Dispatch admission is temporarily fenced.", code="DISPATCH_DRAIN_ACTIVE")

    def _check_registry_unfenced(self) -> None:
        if self._dispatch_fence_owner is not None:
            raise DispatchError("Dispatch registry is temporarily fenced.", code="DISPATCH_DRAIN_ACTIVE")

    def _check_fence_owner(self, token: object) -> None:
        with self._dispatch_state:
            if self._dispatch_fence_owner is not token:
                raise DispatchError("Dispatch drain fence is no longer active.", code="DISPATCH_DRAIN_INACTIVE")

    async def _borrowed_lease_identity_current(
        self, project_id: str, task_id: str, slot: _ActiveProjectClient,
    ) -> bool:
        """Recheck the original local binding and credentials before lease-only use."""
        client = slot.client
        root = self._project(project_id)
        expected_state = (self._root / "credentials" / f"{_digest(project_id + self._binding(root))}.json").resolve()
        if client.project_root != root.resolve() or client.state_path != expected_state or not client._verified:
            return False
        descriptor = client._runtime_descriptor()
        revision = descriptor.get("runtimeSourceRevision")
        if (descriptor.get("baseUrl") != client._base_url or not revision
                or revision != str(client._runtime_info.get("runtimeSourceRevision") or "")
                or revision != _checkout_revision(client.project_root)):
            return False
        async with client._state_lock:
            disk = json.loads(client.state_path.read_text(encoding="utf-8"))
            if not isinstance(disk, dict) or disk.get("projectRoot") != str(client.project_root):
                return False
            tasks, own_tasks = disk.get("tasks"), client._state.get("tasks")
            if (not isinstance(tasks, dict) or not isinstance(own_tasks, dict) or set(tasks) != set(own_tasks)
                    or disk.get("requests") != client._state.get("requests")
                    or disk.get("management", {}) != client._state.get("management", {})):
                return False
            for identity, saved in tasks.items():
                owned = own_tasks.get(identity)
                if not isinstance(saved, dict) or not isinstance(owned, dict):
                    return False
                if any(saved.get(key) != owned.get(key) for key in ("taskCapability", "leaseId")):
                    return False
            saved = tasks.get(task_id)
            return isinstance(saved, dict) and all(isinstance(saved.get(key), str) and saved[key]
                                                   for key in ("taskCapability", "leaseId"))

    def _drain_record_paths(self) -> list[Path] | None:
        directory = self._root / "records"
        try:
            if directory.is_symlink():
                return None
            if not directory.exists():
                return []
            if not directory.is_dir():
                return None
            paths = sorted(directory.iterdir())
            names = {path.name for path in paths}
            # atomic_write_json retains lock sidecars. An orphaned sidecar is
            # ambiguous and must not disappear from the proof.
            return [path for path in paths if not (
                path.name.endswith(".json.lock") and path.name[:-5] in names
                and path.is_file() and not path.is_symlink())]
        except OSError:
            return None

    @asynccontextmanager
    async def drain_fence(self):
        """Fence new dispatch/source admissions; retain heartbeats while waiting.

        The single owning host must also fence all non-dispatch producers.
        Scope exit releases the proof and admits dispatch again.
        """
        token = object()
        try:
            with anyio.fail_after(_DRAIN_ADMISSION_TIMEOUT):
                await self._dispatch_admission.acquire()
        except TimeoutError:
            raise DispatchError("Dispatch admission is busy.", code="DISPATCH_DRAIN_ADMISSION_BUSY") from None
        try:
            with self._dispatch_state:
                self._check_registry_unfenced()
                self._dispatch_fence_owner = token
        finally:
            self._dispatch_admission.release()
        fence = DispatchDrainFence(self, token)

        async def keep_alive() -> None:
            while not fence._sealed:
                try:
                    await self.heartbeat()
                except Exception:  # a failed renewal is never proof of completion
                    pass
                await anyio.sleep(min(_DRAIN_HEARTBEAT_INTERVAL, 2.0))

        async def renew_with_active_client(dispatch_id: str) -> None:
            # A prior reconcile may own both locks. Borrow its already-verified
            # SDK object rather than creating a competing credential writer.
            while not fence._sealed:
                slot = None
                sent = False
                try:
                    record = self._read(dispatch_id)
                    task_id, project_id = record.get("nativeTaskId"), record.get("projectId")
                    receipt = record.get("receipt")
                    if (not isinstance(task_id, str) or not task_id or not isinstance(project_id, str)
                            or receipt is not None and not isinstance(receipt, dict)):
                        await anyio.sleep(min(_DRAIN_HEARTBEAT_INTERVAL, 1.0))
                        continue
                    if isinstance(receipt, dict) and receipt.get("status") in TASK_TERMINAL_STATUSES:
                        return
                    slot = self._active_project_clients.get(project_id)
                    if slot is not None and slot.borrow():
                        try:
                            if await self._borrowed_lease_identity_current(project_id, task_id, slot):
                                await _bounded_native_request(slot.client.heartbeat_task(task_id=task_id))
                                sent = True
                        finally:
                            slot.release()
                except Exception:
                    pass  # no receipt or drain proof is produced here
                await anyio.sleep(_DRAIN_HEARTBEAT_INTERVAL if sent else min(_DRAIN_HEARTBEAT_INTERVAL, 1.0))

        try:
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(keep_alive)
                paths = self._drain_record_paths()
                if paths is not None:
                    for path in paths:
                        if (not path.is_symlink() and path.is_file() and path.suffix == ".json"
                                and _DISPATCH_ID.fullmatch(path.stem)):
                            tasks.start_soon(renew_with_active_client, path.stem)
                try:
                    yield fence
                finally:
                    fence._close()
                    tasks.cancel_scope.cancel()
        finally:
            with self._dispatch_state:
                if self._dispatch_fence_owner is token:
                    self._dispatch_fence_owner = None

    def replace_projects(self, snapshot: dict, *, retain_suspension: bool = False) -> dict:
        """Apply only main's private, monotonically versioned authorization view.

        Main persists registration epochs and tombstones. This in-process
        projection owns no grant file and never restarts the native Session.
        Removed IDs cannot be recycled during this host generation.
        """
        with self._dispatch_state:
            self._check_registry_unfenced()
            return self._replace_projects(snapshot, retain_suspension=retain_suspension)

    def _replace_projects(self, snapshot: dict, *, retain_suspension: bool) -> dict:
        if (not isinstance(snapshot, dict) or set(snapshot) != {"schemaVersion", "revision", "projects"}
                or type(snapshot["schemaVersion"]) is not int or snapshot["schemaVersion"] != 1 or type(snapshot["revision"]) is not int
                or snapshot["revision"] < 0 or not isinstance(snapshot["projects"], dict)
                or len(snapshot["projects"]) > 128):
            raise DispatchError("Invalid private project snapshot.", code="PROJECT_REGISTRY_INVALID")
        projects = {}
        for key, value in snapshot["projects"].items():
            if (not isinstance(key, str) or not key.strip() or len(key) > 160
                    or not isinstance(value, str) or not Path(value).is_absolute()):
                raise DispatchError("Invalid private project registration.", code="PROJECT_REGISTRY_INVALID")
            try:
                projects[key] = _lexical_root(value)
            except (OSError, ValueError, RuntimeError):
                raise DispatchError("Invalid private project registration.", code="PROJECT_REGISTRY_INVALID") from None
        revision = snapshot["revision"]
        if revision < self._registry_revision:
            raise DispatchError("Older project snapshot refused.", code="PROJECT_REGISTRY_STALE")
        if revision == self._registry_revision and projects != self._projects:
            raise DispatchError("Project snapshot revision conflicts.", code="PROJECT_REGISTRY_CONFLICT")
        if set(projects) & self._revoked_projects:
            raise DispatchError("Revoked registration cannot be reused.", code="PROJECT_REGISTRY_REVOKED")
        if any(key in self._seen_projects and self._seen_projects[key] != path for key, path in projects.items()):
            raise DispatchError("Project registration binding changed.", code="PROJECT_BINDING_CHANGED")
        if self._projects_suspended.is_set() and not retain_suspension:
            # Validate the entire envelope before mutating revocations, seen
            # bindings or the gate. Path equality follows platform case rules.
            physical_roots: set[Path] = set()
            try:
                for supplied in projects.values():
                    physical = supplied.resolve(strict=True)
                    if supplied != physical or not physical.is_dir() or physical in physical_roots:
                        raise ValueError("Unavailable or aliased project root")
                    physical_roots.add(physical)
            except (OSError, ValueError, RuntimeError):
                raise DispatchError("Project registry requires reconciliation.", code="PROJECT_REGISTRY_RECONCILE_REQUIRED") from None
        self._revoked_projects.update(set(self._projects) - set(projects))
        self._seen_projects.update(projects)
        self._projects = MappingProxyType(projects)
        self._registry_revision = revision
        self._registry_gate_generation += 1
        if not retain_suspension:
            self._projects_suspended.clear()
        return {"schemaVersion": 1, "revision": revision, "projectCount": len(projects)}

    def project_ids(self) -> tuple[str, ...]:
        """Expose registered IDs to the action index without disclosing paths."""
        return tuple(sorted(self._projects))

    async def discover(self, project_id: str, *, limit: int = 50) -> dict[str, Any]:
        """Discover through the native non-team eligibility policy."""
        payload = await self._call(project_id, lambda client: client.list_agents(limit=limit))
        return {**payload, "projectId": project_id}

    async def dispatch(
        self, project_id: str, *, agent_id: str, task: str, dispatch_id: str,
        title: str = "", permission_profile: str = "read_only", source_ref: dict | None = None,
    ) -> dict[str, Any]:
        """Serialize new admissions with the migration dispatch fence."""
        async with self._dispatch_admission:
            self._check_dispatch_unfenced()
            return await self._dispatch(project_id, agent_id=agent_id, task=task, dispatch_id=dispatch_id,
                                        title=title, permission_profile=permission_profile, source_ref=source_ref)

    async def _dispatch(
        self,
        project_id: str,
        *,
        agent_id: str,
        task: str,
        dispatch_id: str,
        title: str = "",
        permission_profile: str = "read_only",
        source_ref: dict | None = None,
    ) -> dict[str, Any]:
        """Persist the idempotency ref before sending, without storing the prompt.

        A failed/unacknowledged start can be retried only by calling this method
        with the same dispatch ID and original inputs. A known native task is
        never started again, including after transport errors or lease expiry.
        """
        project_root = self._project(project_id)
        self._validate_id(dispatch_id)
        agent_id, task, title = str(agent_id).strip(), str(task).strip(), str(title).strip()
        if not agent_id or len(agent_id) > 200 or not task or len(task) > 64_000 or len(title) > 160:
            raise DispatchError("Invalid bounded dispatch input.", code="INVALID_DISPATCH")
        if permission_profile not in {"read_only", "workspace_write", "full_access"}:
            raise DispatchError("Unsupported permission profile.", code="INVALID_DISPATCH")
        if source_ref is not None:
            from pydantic import ValidationError
            from .task_source import SourceReference
            try:
                source_ref = SourceReference.model_validate(source_ref).model_dump()
            except ValidationError:
                raise DispatchError("Invalid native task source reference.", code="INVALID_DISPATCH") from None
            if source_ref["spanHash"] != _digest(task):
                raise DispatchError("Native task source hash changed.", code="DISPATCH_CONFLICT")
        request_digest = _digest(json.dumps({
            "projectId": project_id, "agentId": agent_id, "task": task,
            "title": title, "permissionProfile": permission_profile,
        }, sort_keys=True, ensure_ascii=False))
        async with self._dispatch_lock(dispatch_id):
            self._project(project_id)
            path = self._path(dispatch_id)
            retrying = path.exists()
            if path.exists():
                record = self._read(dispatch_id)
                if record.get("requestDigest") != request_digest:
                    raise DispatchError("Dispatch ID already belongs to another request.", code="DISPATCH_CONFLICT")
                if source_ref is not None and record.get("sourceRef") != source_ref:
                    raise DispatchError("Dispatch source reference changed.", code="DISPATCH_CONFLICT")
                if record.get("nativeTaskId"):
                    return self._public(record)
            else:
                record = {
                    "schemaVersion": 1,
                    "dispatchId": dispatch_id,
                    "projectId": project_id,
                    "projectBinding": self._binding(project_root),
                    "agentId": agent_id,
                    "clientRequestId": f"launcher-assistant:{dispatch_id}",
                    "requestDigest": request_digest,
                    "nativeTaskId": "",
                    "receipt": None,
                    "lastError": None,
                    "createdAt": _now(),
                    "updatedAt": _now(),
                }
                if source_ref is not None:
                    record["sourceRef"] = deepcopy(source_ref)
                self._save(record)
            return await self._update(record, lambda client: client.start_task(
                agent_id=agent_id, task=task, permission_profile=permission_profile,
                client_request_id=record["clientRequestId"], title=title,
                require_existing_capability=retrying,
            ))

    async def dispatch_from_source(self, project_id: str, *, agent_id: str, dispatch_id: str, runtime: dict,
                                   task: str | None = None, task_source: dict | None = None, title: str = "") -> dict:
        """Model-only admission; source resolution precedes every record/client effect."""
        async with self._dispatch_admission:
            self._check_dispatch_unfenced()
            return await self._dispatch_from_source(project_id, agent_id=agent_id, dispatch_id=dispatch_id,
                runtime=runtime, task=task, task_source=task_source, title=title)

    async def dispatch_write_from_source(self, project_id: str, *, agent_id: str, dispatch_id: str,
                                         runtime: dict, task: str, title: str = "") -> dict:
        """Request workspace write for an exact source span after the caller's native policy gate.

        This internal entry point does not grant or decide approval. The caller
        must bind its approval to these exact arguments and route through the
        native manage tool; the target still applies its own permission ceiling.
        """
        if not isinstance(task, str) or not task or task != task.strip():
            raise DispatchError("Invalid exact task source.", code="TASK_SOURCE_INVALID")
        async with self._dispatch_admission:
            self._check_dispatch_unfenced()
            return await self._dispatch_from_source(project_id, agent_id=agent_id, dispatch_id=dispatch_id,
                runtime=runtime, task=task, title=title, permission_profile="workspace_write")

    async def _dispatch_from_source(self, project_id: str, *, agent_id: str, dispatch_id: str, runtime: dict,
                                    task: str | None = None, task_source: dict | None = None, title: str = "",
                                    permission_profile: str = "read_only") -> dict:
        from .task_source import resolve_task

        self._project(project_id)
        async with self._dispatch_lock(dispatch_id):
            self._project(project_id)
            record = self._read(dispatch_id) if self._path(dispatch_id).exists() else None
            if record is not None and "sourceRef" not in record:
                # Legacy acknowledged raw repeats can only return the known
                # task through the unchanged request digest. Never materialize
                # an unknown legacy request without original source proof.
                if (permission_profile != "read_only" or not record.get("nativeTaskId")
                        or task is None or task_source is not None):
                    raise DispatchError("原请求缺少任务原文引用；请先查询原 dispatch_id 回执，不要重新创建。", code="TASK_SOURCE_UNAVAILABLE")
                resolved, reference = task, None
            else:
                resolved, reference = await asyncio.to_thread(resolve_task, runtime, task=task, task_source=task_source,
                    source_ref=record.get("sourceRef") if record is not None else None,
                    require_full_message=permission_profile == "workspace_write")
        return await self._dispatch(project_id, agent_id=agent_id, dispatch_id=dispatch_id, task=resolved,
            title=title, permission_profile=permission_profile, source_ref=reference)

    async def reconcile(self, dispatch_id: str) -> dict[str, Any]:
        """Renew and read the known native task; never infer or create a new task."""
        async with self._dispatch_lock(dispatch_id):
            record = self._read(dispatch_id)
            unconfirmed = not record.get("nativeTaskId")

            async def query(client: Any) -> dict[str, Any]:
                if unconfirmed:
                    found = await _bounded_native_request(client.get_task_for_request(client_request_id=record["clientRequestId"]))
                    task_id = str(found.get("taskId") or "")
                else:
                    task_id = record["nativeTaskId"]
                await _bounded_native_request(client.heartbeat_task(task_id=task_id))
                return await _checked_task_receipt(client, task_id)

            try:
                return await self._update(record, query)
            except DispatchError as exc:
                if unconfirmed and exc.code in {"TASK_NOT_FOUND", "UNKNOWN_REQUEST"}:
                    # The request might never have reached the backend. Keep
                    # its stable key and denial; only an explicit same-payload
                    # retry can start it. A heartbeat never resubmits a prompt.
                    return self._public(record)
                raise

    async def resolve_approval(
        self,
        dispatch_id: str,
        *,
        approval_id: str,
        decision: str,
        expected_revision: str,
        reason: str = "",
    ) -> dict[str, Any]:
        """Forward only an explicit decision; the native owner/revision gates apply."""
        async with self._dispatch_admission:
            self._check_dispatch_unfenced()
            return await self._resolve_approval(dispatch_id, approval_id=approval_id, decision=decision,
                                                expected_revision=expected_revision, reason=reason)

    async def _resolve_approval(
        self, dispatch_id: str, *, approval_id: str, decision: str, expected_revision: str, reason: str,
    ) -> dict[str, Any]:
        async with self._dispatch_lock(dispatch_id):
            record = self._read(dispatch_id)
            self._require_task(record)

            async def resolve(client: Any) -> dict[str, Any]:
                await client.resolve_approval(
                    task_id=record["nativeTaskId"], approval_id=approval_id,
                    decision=decision, expected_revision=expected_revision, reason=reason,
                )
                return await client.get_task(task_id=record["nativeTaskId"])

            return await self._update(record, resolve)

    async def cancel(self, dispatch_id: str) -> dict[str, Any]:
        """Explicitly request native cancellation and retain stop-unconfirmed state."""
        async with self._dispatch_admission:
            self._check_dispatch_unfenced()
            return await self._cancel(dispatch_id)

    async def _cancel(self, dispatch_id: str) -> dict[str, Any]:
        async with self._dispatch_lock(dispatch_id):
            record = self._read(dispatch_id)
            self._require_task(record)
            return await self._update(record, lambda client: client.cancel_task(task_id=record["nativeTaskId"]))

    async def heartbeat(self) -> list[dict[str, Any]]:
        """Renew active refs and read receipts; one failed dispatch does not stop peers.

        Native heartbeat swallows individual renewal failures. Reading each task
        afterwards provides an observed receipt/error rather than claiming that
        a transport attempt acknowledged a renewal. Scheduling belongs to host.
        """
        rows = self.list_dispatches()
        invalid = [row for row in rows if row.get("stateInvalid")]
        ids = [row["dispatchId"] for row in rows if not row.get("stateInvalid")
               and (row.get("receipt") or {}).get("status") not in TASK_TERMINAL_STATUSES]
        return sorted([*invalid, *(await self._refresh_batch(ids, include_terminal=False))],
                      key=lambda item: item["dispatchId"])

    async def _refresh_batch(self, ids: list[str], *, include_terminal: bool,
                             terminal_registry_generation: int | None = None) -> list[dict[str, Any]]:
        """Use one authenticated SDK per project and renew its tasks concurrently.

        The SDK serializes its shared credential writes internally. Holding the
        project lock excludes other SDK instances that could overwrite that
        credential snapshot; record locks protect each persisted receipt.
        """
        groups: dict[str, list[str]] = {}
        results: list[dict[str, Any]] = []
        for dispatch_id in ids:
            try:
                record = self._read(dispatch_id)
                groups.setdefault(record["projectId"], []).append(dispatch_id)
            except Exception:
                results.append({"dispatchId": dispatch_id, "lastError": {"code": "DISPATCH_STATE_UNKNOWN"}})

        async def project_batch(project_id: str, project_ids: list[str]) -> None:
            locks: list[anyio.Lock] = []
            records: list[dict[str, Any]] = []
            try:
                for dispatch_id in sorted(project_ids):
                    lock = self._dispatch_lock(dispatch_id)
                    await lock.acquire()
                    locks.append(lock)
                    try:
                        row = self._read(dispatch_id)
                        if row.get("projectId") != project_id:
                            raise DispatchError("Project binding changed.", code="PROJECT_BINDING_CHANGED")
                        receipt = row.get("receipt")
                        if (row.get("clientRequestId") != f"launcher-assistant:{dispatch_id}"
                                or not isinstance(row.get("nativeTaskId"), str)
                                or receipt is not None and not isinstance(receipt, dict)
                                or isinstance(receipt, dict) and receipt.get("taskId") != row.get("nativeTaskId")
                                or row.get("lastError") is not None and not isinstance(row.get("lastError"), dict)):
                            raise DispatchError("Invalid native task state.", code="DISPATCH_STATE_INVALID")
                        records.append(row)
                    except Exception:
                        results.append({"dispatchId": dispatch_id, "lastError": {"code": "DISPATCH_STATE_UNKNOWN"}})

                async def run(client: Any) -> dict[str, Any]:
                    outcomes: dict[str, dict[str, Any]] = {}
                    first_done = anyio.Event()
                    attempted = 0

                    async def attempt(record: dict[str, Any]) -> None:
                        try:
                            task_id = record.get("nativeTaskId") or ""
                            if terminal_registry_generation is not None:
                                # Patrol's recheck is a new read admission, not
                                # a lease renewal. Diagnose first, then fence
                                # each read against suspend/rebind. No await is
                                # performed while holding the registry lock.
                                receipt = record.get("receipt")
                                if (not task_id or not isinstance(receipt, dict)
                                        or receipt.get("status") not in TASK_TERMINAL_STATUSES):
                                    raise DispatchError("Terminal task changed.", code="DISPATCH_STATE_INVALID")
                                with self._dispatch_state:
                                    self._project(project_id)
                                    if self._registry_gate_generation != terminal_registry_generation:
                                        raise DispatchError("Project registry changed.", code="PROJECT_REGISTRY_RECONCILE_REQUIRED")
                                payload = await _checked_task_receipt(client, task_id)
                                record["receipt"] = {key: deepcopy(value) for key, value in payload.items() if key in _RECEIPT_FIELDS}
                                record["lastError"] = None
                                self._save(record)
                                outcomes[record["dispatchId"]] = self._public(record)
                                return
                            if not task_id:
                                request_id = record.get("clientRequestId")
                                if not isinstance(request_id, str) or not request_id:
                                    raise DispatchError("Missing native request identity.", code="DISPATCH_STATE_INVALID")
                                found = await _bounded_native_request(client.get_task_for_request(client_request_id=request_id))
                                task_id = str(found.get("taskId") or "")
                            receipt = record.get("receipt")
                            terminal = isinstance(receipt, dict) and receipt.get("status") in TASK_TERMINAL_STATUSES
                            if not terminal:
                                await _bounded_native_request(client.heartbeat_task(task_id=task_id))
                            if terminal and not include_terminal:
                                outcomes[record["dispatchId"]] = self._public(record)
                                return
                            payload = await _checked_task_receipt(client, task_id)
                            record["nativeTaskId"] = task_id
                            record["receipt"] = {key: deepcopy(value) for key, value in payload.items() if key in _RECEIPT_FIELDS}
                            record["lastError"] = None
                            self._save(record)
                            try:
                                outcomes[record["dispatchId"]] = self._public(record)
                            except Exception:
                                outcomes[record["dispatchId"]] = {
                                    "dispatchId": record["dispatchId"], "lastError": record["lastError"]}
                        except Exception as exc:
                            code = (exc.code if isinstance(exc, (DispatchError, BackendClientError))
                                    else "DISPATCH_STATE_UNKNOWN")
                            code = re.sub(r"[^A-Z0-9_]", "_", str(code).upper())[:80]
                            record["lastError"] = {"code": code, "message": "Native task observation failed."}
                            try:
                                self._save(record)
                            except OSError:
                                pass
                            try:
                                outcomes[record["dispatchId"]] = self._public(record)
                            except Exception:
                                outcomes[record["dispatchId"]] = {
                                    "dispatchId": record["dispatchId"], "lastError": record["lastError"]}

                    async def refresh(record: dict[str, Any]) -> None:
                        nonlocal attempted
                        await attempt(record)
                        attempted += 1
                        if attempted == len(records):
                            first_done.set()
                        # One slow task must not stop healthy peers renewing
                        # while the shared project client remains in use.
                        while not first_done.is_set():
                            receipt = record.get("receipt")
                            if (not record.get("nativeTaskId") or
                                    isinstance(receipt, dict) and receipt.get("status") in TASK_TERMINAL_STATUSES):
                                await first_done.wait()
                                break
                            with anyio.move_on_after(_DRAIN_HEARTBEAT_INTERVAL):
                                await first_done.wait()
                            if not first_done.is_set():
                                await attempt(record)

                    async with anyio.create_task_group() as group:
                        for record in records:
                            group.start_soon(refresh, record)
                    results.extend(outcomes.values())
                    return {}

                if records:
                    try:
                        await self._call(project_id, run)
                    except Exception as exc:
                        code = exc.code if isinstance(exc, DispatchError) else "BACKEND_UNAVAILABLE"
                        for row in records:
                            try:
                                public = self._public(row)
                            except Exception:
                                public = {"dispatchId": row["dispatchId"]}
                            public["lastError"] = {"code": code, "message": "Native task observation failed."}
                            results.append(public)
            finally:
                for lock in reversed(locks):
                    lock.release()

        async with anyio.create_task_group() as group:
            for project_id, project_ids in groups.items():
                group.start_soon(project_batch, project_id, project_ids)
        return results

    def list_dispatches(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """Return reference snapshots, never credentials or stored task prompts."""
        if project_id is not None:
            self._project(project_id, require_available=False)
        records = []
        for path in sorted((self._root / "records").glob("*.json")):
            try:
                record = self._read(path.stem, require_authorized=False)
                if record.get("receipt") is not None and not isinstance(record["receipt"], dict):
                    raise DispatchError("Dispatch receipt is invalid.", code="DISPATCH_STATE_INVALID")
            except DispatchError:
                # Preserve the original file. One broken reference must not
                # prevent healthy tasks from renewing their finite leases.
                ref = path.stem if _DISPATCH_ID.fullmatch(path.stem) else "invalid-" + _digest(path.name)[:12]
                records.append({"dispatchId": ref, "projectId": "", "nativeTaskId": "", "receipt": None,
                    "stateInvalid": True, "lastError": {"code": "DISPATCH_STATE_INVALID",
                    "message": "Dispatch reference is unreadable; it was retained for recovery."}})
                continue
            registered = self._projects.get(str(record.get("projectId") or ""))
            if registered is None or record.get("projectBinding") != self._binding(registered):
                continue
            if project_id is None or record["projectId"] == project_id:
                records.append(self._public(record))
        return records

    async def _call(self, project_id: str, action: Callable[[Any], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        project_root = self._project(project_id)
        async with self._project_locks.setdefault(project_id, anyio.Lock()):
            if self._project(project_id) != project_root:
                raise DispatchError("Project binding changed before admission.", code="PROJECT_BINDING_CHANGED")
            # Reconstructing re-reads the native credential ledger and Launcher
            # descriptor, including changed token/URL/revision after a restart.
            # No MCP lifecycle or shutdown is entered when this object expires.
            client = self._client_factory(
                project_root,
                state_path=self._root / "credentials" / f"{_digest(project_id + self._binding(project_root))}.json",
            )
            try:
                await _bounded_native_request(client.diagnostics())
                if self._project(project_id, require_available=False) != project_root:
                    raise DispatchError("Project binding changed before admission.", code="PROJECT_BINDING_CHANGED")
                previous = self._active_project_clients.get(project_id)
                if previous is not None:
                    # The verifier was constructed before the previous client
                    # stopped renewing. Drain its SDK writes, then reload the
                    # atomic credential snapshot before the new client acts.
                    previous.closing = True
                    with anyio.CancelScope(shield=True):
                        if previous.borrowers:
                            await previous.drained.wait()
                        if isinstance(client, ManagedAgentBackendClient):
                            async with client._state_lock:
                                client._state = client._load_state()
                    if self._active_project_clients.get(project_id) is previous:
                        self._active_project_clients.pop(project_id, None)
                slot = _ActiveProjectClient(client) if isinstance(client, ManagedAgentBackendClient) else None
                if slot is not None:
                    self._active_project_clients[project_id] = slot
                try:
                    return await action(client)
                finally:
                    if slot is not None:
                        # Stop new borrows before waiting. Otherwise staggered
                        # renewals can keep the count above zero indefinitely.
                        slot.closing = True
                        try:
                            with anyio.CancelScope(shield=True):
                                if slot.borrowers:
                                    await slot.drained.wait()
                        finally:
                            # Retain the verified cache for the next diagnostics
                            # window, unless another generation replaced it.
                            if self._active_project_clients.get(project_id) is slot:
                                slot.closing = False
            except BackendClientError as exc:
                code = re.sub(r"[^A-Z0-9_]", "_", str(exc.code).upper())[:80] or "BACKEND_ERROR"
                raise DispatchError(
                    "Native task operation failed; existing references were retained.", code=code,
                ) from None

    async def _update(self, record: dict[str, Any], action: Callable[[Any], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        try:
            payload = await self._call(record["projectId"], action)
            task_id = str(payload.get("taskId") or "")
            if not task_id or (record.get("nativeTaskId") and task_id != record["nativeTaskId"]):
                raise DispatchError("Invalid native task reference.", code="BACKEND_PROTOCOL_ERROR")
        except DispatchError as exc:
            record["lastError"] = {"code": exc.code, "message": str(exc)}
            self._save(record)
            raise
        record["nativeTaskId"] = task_id
        record["receipt"] = {key: deepcopy(value) for key, value in payload.items() if key in _RECEIPT_FIELDS}
        record["lastError"] = None
        self._save(record)
        return self._public(record)

    def _project(self, project_id: str, *, require_available: bool = True) -> Path:
        projects = self._admitted_projects() if require_available else self._projects
        path = projects.get(project_id)
        if path is None:
            raise DispatchError("Project is not in the host-authorized registry.", code="PROJECT_NOT_AUTHORIZED")
        return path

    @staticmethod
    def _binding(project_root: Path) -> str:
        return _digest(str(project_root).casefold())

    @staticmethod
    def _validate_id(dispatch_id: str) -> None:
        if not isinstance(dispatch_id, str) or not _DISPATCH_ID.fullmatch(dispatch_id):
            raise DispatchError("Invalid dispatch ID.", code="INVALID_DISPATCH")

    def _path(self, dispatch_id: str) -> Path:
        self._validate_id(dispatch_id)
        return self._root / "records" / f"{dispatch_id}.json"

    def _dispatch_lock(self, dispatch_id: str) -> anyio.Lock:
        self._validate_id(dispatch_id)
        return self._dispatch_locks.setdefault(dispatch_id, anyio.Lock())

    def _read(self, dispatch_id: str, *, require_authorized: bool = True) -> dict[str, Any]:
        path = self._path(dispatch_id)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise DispatchError("Dispatch reference was not found.", code="DISPATCH_NOT_FOUND") from None
        except (OSError, ValueError):
            raise DispatchError("Dispatch reference is unreadable; refusing to recreate it.", code="DISPATCH_STATE_INVALID") from None
        if not isinstance(record, dict) or record.get("schemaVersion") != 1 or record.get("dispatchId") != dispatch_id:
            raise DispatchError("Dispatch reference is invalid; refusing to recreate it.", code="DISPATCH_STATE_INVALID")
        if require_authorized:
            project_root = self._project(str(record.get("projectId") or ""))
            if record.get("projectBinding") != self._binding(project_root):
                raise DispatchError("Project registry binding changed; native references were retained.", code="PROJECT_BINDING_CHANGED")
        return record

    def _save(self, record: dict[str, Any]) -> None:
        record["updatedAt"] = _now()
        atomic_write_json(self._path(record["dispatchId"]), record, sort_keys=True, indent=2, strict_replace=True)

    @staticmethod
    def _require_task(record: dict[str, Any]) -> None:
        if not record.get("nativeTaskId"):
            raise DispatchError("Native start has not been acknowledged.", code="DISPATCH_NOT_CONFIRMED")

    @staticmethod
    def _public(record: dict[str, Any]) -> dict[str, Any]:
        result = {key: deepcopy(value) for key, value in record.items() if key not in {"requestDigest", "projectBinding", "schemaVersion", "sourceRef"}}
        receipt = record.get("receipt") or {}
        result["completionEvidence"] = {
            "source": "native_external_agent_task",
            "nativeTaskId": record.get("nativeTaskId") or "",
            "nativeStatus": receipt.get("status") or "",
            "resultAvailable": bool(receipt.get("resultSummary")),
            # Native ready/idle/stopped can project to succeeded. A task status
            # alone cannot establish that a user's requested outcome was met.
            "businessAcceptance": "not_evaluated",
        }
        return result


__all__ = ["DispatchError", "DispatchService"]
