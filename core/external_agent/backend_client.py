"""Bounded loopback client used by the stdio MCP adapter."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import anyio
import httpx

from core.external_agent.contracts import (
    API_PROTOCOL_VERSION,
    SERVER_VERSION,
    TASK_TERMINAL_STATUSES,
)

CONTROL_TOKEN_HEADER = "X-Vibelution-Control-Token"
TASK_CAPABILITY_HEADER = "X-Vibelution-External-Agent-Task-Capability"
ADAPTER_CONNECTION_HEADER = "X-Vibelution-External-Agent-Connection"


class BackendClientError(RuntimeError):
    """Fail-closed runtime discovery, identity, auth, or API error."""

    def __init__(self, message: str, *, code: str = "BACKEND_ERROR") -> None:
        super().__init__(str(message or code))
        self.code = str(code or "BACKEND_ERROR")


def _default_state_path(project_root: Path) -> Path:
    app_data = Path(
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("XDG_STATE_HOME")
        or (Path.home() / ".local" / "state")
    )
    project_key = hashlib.sha256(
        str(project_root.resolve()).casefold().encode("utf-8")
    ).hexdigest()[:20]
    return app_data / "Vibelution" / "mcp" / f"managed-agent-{project_key}.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _checkout_revision(project_root: Path) -> str:
    git_entry = project_root / ".git"
    git_dir = git_entry
    if git_entry.is_file():
        text = git_entry.read_text(encoding="utf-8", errors="replace").strip()
        if not text.lower().startswith("gitdir:"):
            return ""
        git_dir = Path(text.split(":", 1)[1].strip())
        if not git_dir.is_absolute():
            git_dir = (project_root / git_dir).resolve()
    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        return ""
    head = head_path.read_text(encoding="utf-8", errors="replace").strip()
    if not head.startswith("ref:"):
        return head
    ref = head.split(":", 1)[1].strip()
    candidates = [git_dir / ref]
    common_dir_path = git_dir / "commondir"
    if common_dir_path.is_file():
        common_dir = Path(common_dir_path.read_text(encoding="utf-8").strip())
        if not common_dir.is_absolute():
            common_dir = (git_dir / common_dir).resolve()
        candidates.append(common_dir / ref)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace").strip()
    return ""


class ManagedAgentBackendClient:
    """Official adapter's only bridge to backend-owned task writes."""

    def __init__(
        self,
        project_root: Path,
        *,
        state_path: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        adapter_connection_id: str = "",
        timeout_seconds: float = 5.0,
        heartbeat_seconds: float = 10.0,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.state_path = (
            Path(state_path or _default_state_path(self.project_root))
            .expanduser()
            .resolve()
        )
        self.transport = transport
        self.adapter_connection_id = (
            str(adapter_connection_id or "").strip() or f"mcp-{uuid.uuid4().hex}"
        )
        self.timeout_seconds = max(0.5, min(float(timeout_seconds), 30.0))
        self.heartbeat_seconds = max(1.0, min(float(heartbeat_seconds), 60.0))
        self._base_url = ""
        self._control_header = CONTROL_TOKEN_HEADER
        self._control_token = ""
        self._verified = False
        self._runtime_info: dict[str, Any] = {}
        self._state_lock = anyio.Lock()
        self._state = self._load_state()

    async def list_agents(self, *, limit: int = 50) -> dict[str, Any]:
        return await self._request_json(
            "GET", f"/api/v1/external-agent/agents?limit={max(1, min(int(limit), 200))}"
        )

    async def diagnostics(self) -> dict[str, Any]:
        await self._ensure_connected()
        return {
            "status": "healthy",
            "baseUrl": self._base_url,
            **deepcopy(self._runtime_info),
        }

    async def start_task(
        self,
        *,
        agent_id: str,
        task: str,
        permission_profile: str,
        client_request_id: str,
        title: str,
    ) -> dict[str, Any]:
        request_id = str(client_request_id or "").strip()
        async with self._state_lock:
            requests = self._state.setdefault("requests", {})
            request_state = (
                requests.get(request_id)
                if request_id and isinstance(requests.get(request_id), dict)
                else None
            )
            capability = str((request_state or {}).get("taskCapability") or "").strip()
            if not capability:
                capability = secrets.token_urlsafe(32)
                if request_id:
                    requests[request_id] = {"taskCapability": capability}
                    self._save_state_locked()
        payload = await self._request_json(
            "POST",
            "/api/v1/external-agent/tasks",
            task_capability=capability,
            json_payload={
                "agent_id": agent_id,
                "task": task,
                "permission_profile": permission_profile,
                "client_request_id": request_id,
                "title": title,
            },
        )
        task_id = str(payload.get("taskId") or "").strip()
        lease_id = str(payload.get("_leaseId") or "").strip()
        if not task_id or not lease_id:
            raise BackendClientError(
                "backend task creation omitted private task or lease identity",
                code="BACKEND_PROTOCOL_ERROR",
            )
        async with self._state_lock:
            self._state.setdefault("tasks", {})[task_id] = {
                "taskCapability": capability,
                "leaseId": lease_id,
                "status": str(payload.get("status") or "queued"),
            }
            if request_id:
                self._state.setdefault("requests", {})[request_id] = {
                    "taskCapability": capability,
                    "taskId": task_id,
                }
            self._save_state_locked()
        return self._public_payload(payload)

    async def get_task(self, *, task_id: str) -> dict[str, Any]:
        task_state = await self._task_state(task_id)
        payload = await self._request_json(
            "GET",
            f"/api/v1/external-agent/tasks/{task_id}",
            task_capability=str(task_state["taskCapability"]),
        )
        await self._record_task_status(task_id, payload)
        return self._public_payload(payload)

    async def resolve_approval(
        self,
        *,
        task_id: str,
        approval_id: str,
        decision: str,
        expected_revision: str,
        reason: str,
    ) -> dict[str, Any]:
        task_state = await self._task_state(task_id)
        return self._public_payload(
            await self._request_json(
                "POST",
                f"/api/v1/external-agent/tasks/{task_id}/approvals/{approval_id}/resolve",
                task_capability=str(task_state["taskCapability"]),
                json_payload={
                    "decision": decision,
                    "expected_revision": expected_revision,
                    "reason": reason,
                },
            )
        )

    async def cancel_task(self, *, task_id: str) -> dict[str, Any]:
        task_state = await self._task_state(task_id)
        payload = await self._request_json(
            "POST",
            f"/api/v1/external-agent/tasks/{task_id}/cancel",
            task_capability=str(task_state["taskCapability"]),
            json_payload={},
        )
        await self._record_task_status(task_id, payload)
        return self._public_payload(payload)

    async def heartbeat_once(self) -> None:
        async with self._state_lock:
            tasks = deepcopy(self._state.get("tasks") or {})
        for task_id, task_state in tasks.items():
            if not isinstance(task_state, dict):
                continue
            status = str(task_state.get("status") or "")
            if status in TASK_TERMINAL_STATUSES:
                continue
            capability = str(task_state.get("taskCapability") or "")
            lease_id = str(task_state.get("leaseId") or "")
            if not capability or not lease_id:
                continue
            try:
                payload = await self._request_json(
                    "POST",
                    f"/api/v1/external-agent/tasks/{task_id}/heartbeat",
                    task_capability=capability,
                    json_payload={"lease_id": lease_id},
                )
            except BackendClientError:
                continue
            await self._record_task_status(task_id, payload)

    async def shutdown(self) -> None:
        async with self._state_lock:
            tasks = deepcopy(self._state.get("tasks") or {})
        for task_id, task_state in tasks.items():
            if not isinstance(task_state, dict):
                continue
            if str(task_state.get("status") or "") in TASK_TERMINAL_STATUSES:
                await self._forget_task(task_id)
                continue
            capability = str(task_state.get("taskCapability") or "")
            if not capability:
                await self._forget_task(task_id)
                continue
            try:
                await self._request_json(
                    "POST",
                    f"/api/v1/external-agent/tasks/{task_id}/cancel",
                    task_capability=capability,
                    json_payload={},
                )
            except BackendClientError:
                # The backend lease remains the fail-closed recovery path.
                continue
            await self._forget_task(task_id)
        try:
            await self._request_json(
                "POST",
                "/api/v1/external-agent/connections/shutdown",
                json_payload={},
            )
        except BackendClientError:
            pass

    @asynccontextmanager
    async def lifecycle(self) -> AsyncIterator[ManagedAgentBackendClient]:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(self._heartbeat_loop)
            try:
                yield self
            finally:
                await self.shutdown()
                task_group.cancel_scope.cancel()

    async def _heartbeat_loop(self) -> None:
        while True:
            await anyio.sleep(self.heartbeat_seconds)
            await self.heartbeat_once()

    async def _task_state(self, task_id: str) -> dict[str, Any]:
        async with self._state_lock:
            task_state = (self._state.get("tasks") or {}).get(
                str(task_id or "").strip()
            )
            if not isinstance(task_state, dict) or not str(
                task_state.get("taskCapability") or ""
            ):
                raise BackendClientError(
                    "task capability is unavailable for this adapter",
                    code="TASK_NOT_FOUND",
                )
            return deepcopy(task_state)

    async def _record_task_status(self, task_id: str, payload: dict[str, Any]) -> None:
        status = str(payload.get("status") or "")
        async with self._state_lock:
            task_state = (self._state.get("tasks") or {}).get(task_id)
            if not isinstance(task_state, dict):
                return
            task_state["status"] = status or task_state.get("status") or ""
            private_lease = str(payload.get("_leaseId") or "").strip()
            if private_lease:
                task_state["leaseId"] = private_lease
            self._save_state_locked()

    async def _forget_task(self, task_id: str) -> None:
        async with self._state_lock:
            self._state.setdefault("tasks", {}).pop(task_id, None)
            self._save_state_locked()

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        task_capability: str = "",
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._ensure_connected()
        headers = {
            self._control_header: self._control_token,
            ADAPTER_CONNECTION_HEADER: self.adapter_connection_id,
        }
        if task_capability:
            headers[TASK_CAPABILITY_HEADER] = task_capability
        async with httpx.AsyncClient(
            base_url=self._base_url,
            transport=self.transport,
            timeout=self.timeout_seconds,
            trust_env=False,
        ) as client:
            try:
                response = await client.request(
                    method, path, headers=headers, json=json_payload
                )
            except httpx.HTTPError as exc:
                raise BackendClientError(
                    f"managed backend is unreachable: {type(exc).__name__}",
                    code="BACKEND_UNAVAILABLE",
                ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise BackendClientError(
                f"managed backend returned non-JSON status {response.status_code}",
                code="BACKEND_PROTOCOL_ERROR",
            ) from exc
        if response.status_code >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if isinstance(detail, dict):
                code = str(detail.get("code") or "BACKEND_ERROR")
                message = str(detail.get("message") or code)
            else:
                code = "BACKEND_ERROR"
                message = str(detail or response.reason_phrase or code)
            raise BackendClientError(message, code=code)
        if not isinstance(payload, dict):
            raise BackendClientError(
                "managed backend response must be an object",
                code="BACKEND_PROTOCOL_ERROR",
            )
        return payload

    async def _ensure_connected(self) -> None:
        if self._verified:
            return
        descriptor = self._runtime_descriptor()
        self._base_url = descriptor["baseUrl"]
        async with httpx.AsyncClient(
            base_url=self._base_url,
            transport=self.transport,
            timeout=self.timeout_seconds,
            trust_env=False,
        ) as client:
            try:
                token_response = await client.get("/api/control-token")
                token_payload = token_response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise BackendClientError(
                    "managed backend control token is unavailable",
                    code="BACKEND_UNAVAILABLE",
                ) from exc
            if token_response.status_code >= 400 or not isinstance(token_payload, dict):
                raise BackendClientError(
                    "managed backend control token is unavailable",
                    code="BACKEND_UNAVAILABLE",
                )
            self._control_header = str(
                token_payload.get("header") or CONTROL_TOKEN_HEADER
            ).strip()
            self._control_token = str(token_payload.get("controlToken") or "").strip()
            if not self._control_token:
                raise BackendClientError(
                    "managed backend control token is unavailable",
                    code="BACKEND_UNAVAILABLE",
                )
            try:
                info_response = await client.get(
                    "/api/v1/external-agent/info",
                    headers={
                        self._control_header: self._control_token,
                        ADAPTER_CONNECTION_HEADER: self.adapter_connection_id,
                    },
                )
                info = info_response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise BackendClientError(
                    "managed backend identity is unavailable",
                    code="BACKEND_UNAVAILABLE",
                ) from exc
        if info_response.status_code >= 400 or not isinstance(info, dict):
            raise BackendClientError(
                "managed backend identity is unavailable",
                code="BACKEND_UNAVAILABLE",
            )
        if str(info.get("apiProtocolVersion") or "") != API_PROTOCOL_VERSION:
            raise BackendClientError(
                "managed backend API protocol version mismatch",
                code="RUNTIME_IDENTITY_MISMATCH",
            )
        if str(info.get("serverVersion") or "") != SERVER_VERSION:
            raise BackendClientError(
                "managed backend server version mismatch",
                code="RUNTIME_IDENTITY_MISMATCH",
            )
        actual_root = Path(str(info.get("projectRoot") or "")).expanduser().resolve()
        if os.path.normcase(str(actual_root)) != os.path.normcase(
            str(self.project_root)
        ):
            raise BackendClientError(
                "managed backend project root mismatch",
                code="RUNTIME_IDENTITY_MISMATCH",
            )
        expected_revision = descriptor["runtimeSourceRevision"]
        actual_revision = str(info.get("runtimeSourceRevision") or "").strip()
        checkout_revision = _checkout_revision(self.project_root)
        if (
            not checkout_revision
            or not expected_revision
            or actual_revision != expected_revision
            or actual_revision != checkout_revision
        ):
            raise BackendClientError(
                "managed backend runtime source revision mismatch",
                code="RUNTIME_IDENTITY_MISMATCH",
            )
        self._runtime_info = dict(info)
        self._verified = True

    def _runtime_descriptor(self) -> dict[str, str]:
        launcher_state = _read_json(
            self.project_root / ".runtime" / "launcher" / "state.json"
        )
        url = str(launcher_state.get("url") or "").strip().rstrip("/")
        if not url:
            raise BackendClientError(
                "managed Launcher runtime descriptor is missing",
                code="BACKEND_UNAVAILABLE",
            )
        parsed = urlparse(url)
        hostname = str(parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise BackendClientError(
                "managed backend URL must use loopback",
                code="RUNTIME_IDENTITY_MISMATCH",
            )
        declared_root = (
            Path(
                str(
                    launcher_state.get("runtimeProjectRoot")
                    or launcher_state.get("projectRoot")
                    or ""
                )
            )
            .expanduser()
            .resolve()
        )
        if os.path.normcase(str(declared_root)) != os.path.normcase(
            str(self.project_root)
        ):
            raise BackendClientError(
                "Launcher runtime project root mismatch",
                code="RUNTIME_IDENTITY_MISMATCH",
            )
        return {
            "baseUrl": url,
            "runtimeSourceRevision": str(
                launcher_state.get("runtimeSourceCommit")
                or launcher_state.get("sourceCommit")
                or ""
            ).strip(),
        }

    def _load_state(self) -> dict[str, Any]:
        payload = _read_json(self.state_path)
        if str(payload.get("projectRoot") or "") != str(self.project_root):
            payload = {}
        return {
            "schemaVersion": 1,
            "projectRoot": str(self.project_root),
            "tasks": payload.get("tasks")
            if isinstance(payload.get("tasks"), dict)
            else {},
            "requests": payload.get("requests")
            if isinstance(payload.get("requests"), dict)
            else {},
        }

    def _save_state_locked(self) -> None:
        _atomic_write_json(self.state_path, self._state)

    @staticmethod
    def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            key: deepcopy(value)
            for key, value in payload.items()
            if not str(key).startswith("_")
        }


__all__ = ["BackendClientError", "ManagedAgentBackendClient"]
