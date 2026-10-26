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
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from types import MappingProxyType
from typing import Any

import anyio

from core.external_agent.backend_client import (
    BackendClientError,
    ManagedAgentBackendClient,
)
from core.external_agent.contracts import TASK_TERMINAL_STATUSES
from core.infrastructure.atomic_io import atomic_write_json

_DISPATCH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}\Z")
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
        from .management import ManagementAdapter
        self.management = ManagementAdapter(profile_root, self._admitted_projects, self._call)

    def suspend_projects(self) -> dict:
        """Narrow project admissions without changing grants or native history."""
        self._projects_suspended.set()
        return {"schemaVersion": 1, "revision": self._registry_revision, "projectsSuspended": True}

    def _admitted_projects(self) -> Mapping[str, Path]:
        if self._projects_suspended.is_set():
            raise DispatchError("Project registry requires reconciliation.", code="PROJECT_REGISTRY_RECONCILE_REQUIRED")
        return self._projects

    def replace_projects(self, snapshot: dict, *, retain_suspension: bool = False) -> dict:
        """Apply only main's private, monotonically versioned authorization view.

        Main persists registration epochs and tombstones. This in-process
        projection owns no grant file and never restarts the native Session.
        Removed IDs cannot be recycled during this host generation.
        """
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
        from .task_source import resolve_task

        self._project(project_id)
        async with self._dispatch_lock(dispatch_id):
            self._project(project_id)
            record = self._read(dispatch_id) if self._path(dispatch_id).exists() else None
            if record is not None and "sourceRef" not in record:
                # Legacy acknowledged raw repeats can only return the known
                # task through the unchanged request digest. Never materialize
                # an unknown legacy request without original source proof.
                if not record.get("nativeTaskId") or task is None or task_source is not None:
                    raise DispatchError("原请求缺少任务原文引用；请先查询原 dispatch_id 回执，不要重新创建。", code="TASK_SOURCE_UNAVAILABLE")
                resolved, reference = task, None
            else:
                resolved, reference = await asyncio.to_thread(resolve_task, runtime, task=task, task_source=task_source,
                    source_ref=record.get("sourceRef") if record is not None else None)
        return await self.dispatch(project_id, agent_id=agent_id, dispatch_id=dispatch_id, task=resolved,
            title=title, permission_profile="read_only", source_ref=reference)

    async def reconcile(self, dispatch_id: str) -> dict[str, Any]:
        """Renew and read the known native task; never infer or create a new task."""
        async with self._dispatch_lock(dispatch_id):
            record = self._read(dispatch_id)
            unconfirmed = not record.get("nativeTaskId")

            async def query(client: Any) -> dict[str, Any]:
                if unconfirmed:
                    found = await client.get_task_for_request(client_request_id=record["clientRequestId"])
                    task_id = str(found.get("taskId") or "")
                else:
                    task_id = record["nativeTaskId"]
                await client.heartbeat_task(task_id=task_id)
                return await client.get_task(task_id=task_id)

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
        results: list[dict[str, Any]] = []

        async def renew(item: dict[str, Any]) -> None:
            try:
                results.append(await self.reconcile(item["dispatchId"]))
            except DispatchError as exc:
                item["lastError"] = {"code": exc.code, "message": str(exc)}
                results.append(item)

        async with anyio.create_task_group() as group:
            for item in self.list_dispatches():
                if item.get("stateInvalid"):
                    results.append(item)
                    continue
                receipt = item.get("receipt") or {}
                if receipt.get("status") not in TASK_TERMINAL_STATUSES:
                    group.start_soon(renew, item)
        return sorted(results, key=lambda item: item["dispatchId"])

    def list_dispatches(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """Return reference snapshots, never credentials or stored task prompts."""
        if project_id is not None:
            self._project(project_id, require_available=False)
        records = []
        for path in sorted((self._root / "records").glob("*.json")):
            try:
                record = self._read(path.stem, require_authorized=False)
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
                await client.diagnostics()
                if self._project(project_id, require_available=False) != project_root:
                    raise DispatchError("Project binding changed before admission.", code="PROJECT_BINDING_CHANGED")
                return await action(client)
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
