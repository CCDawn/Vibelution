"""Bounded loopback client used by the stdio MCP adapter."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import anyio
import httpx

from core.external_agent.contracts import (
    API_PROTOCOL_VERSION,
    SERVER_VERSION,
    TASK_TERMINAL_STATUSES,
)
from core.infrastructure.atomic_io import atomic_write_json
from vibelution_storage import resolve_project_runtime_home

CONTROL_TOKEN_HEADER = "X-Vibelution-Control-Token"
TASK_CAPABILITY_HEADER = "X-Vibelution-External-Agent-Task-Capability"
ADAPTER_CONNECTION_HEADER = "X-Vibelution-External-Agent-Connection"
_MANAGEMENT_PREFIX = "/api/v1/launcher-assistant-management"
_MANAGEMENT_ACTIONS = frozenset({"agent_create", "agent_update", "agent_avatar", "team_run", "session_pin"})
_MANAGEMENT_SCOPES = ["agents:avatar", "agents:create", "agents:read", "agents:update", "platform:describe", "sessions:pin", "sessions:read", "teams:read", "teams:run"]
_LEGACY_MANAGEMENT_SCOPES = [scope for scope in _MANAGEMENT_SCOPES if scope != "sessions:pin"]


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
    # The shared helper locks the target across processes and bounds
    # PermissionError retries; the previous bare os.replace could fail on a
    # concurrent reader/writer of the managed-agent state file. Strict replace
    # keeps the original all-or-nothing contract (no in-place fallback).
    atomic_write_json(path, payload, sort_keys=True, indent=2, strict_replace=True)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


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

    async def _management_grant(self, *, require_existing: bool) -> dict[str, Any]:
        """Private operator handshake, never a tool result or task capability."""
        async with self._state_lock:
            if self._management_state_invalid:
                raise BackendClientError("Management credentials are unreadable.", code="UNKNOWN_MANAGEMENT_SUBJECT")
            saved = self._state.get("management") or {}
            if require_existing and not saved.get("clientId"):
                raise BackendClientError("Original management subject is missing.", code="UNKNOWN_MANAGEMENT_SUBJECT")
            info = await self._request_json("GET", _MANAGEMENT_PREFIX + "/binding")
            binding = info.get("binding")
            if info.get("protocolVersion") != 1 or not isinstance(binding, dict) or set(binding) != {"projectId", "instanceId"} or any(
                not isinstance(value, str) or not value or len(value) > 160 for value in binding.values()
            ):
                raise BackendClientError("Invalid management binding.", code="BACKEND_PROTOCOL_ERROR")
            if saved.get("binding") and saved["binding"] != binding:
                raise BackendClientError("Management instance changed.", code="RUNTIME_IDENTITY_MISMATCH")
            client_id = str(saved.get("clientId") or secrets.token_urlsafe(32))
            if not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", client_id):
                raise BackendClientError("Invalid management credential state.", code="UNKNOWN_MANAGEMENT_SUBJECT")
            # Old credentials did not persist scopes. Keep their original
            # grant; only a fresh client may explicitly request the new scope.
            requested_scopes = saved.get("scopes", _LEGACY_MANAGEMENT_SCOPES if saved.get("clientId") else _MANAGEMENT_SCOPES)
            if (not isinstance(requested_scopes, list) or not requested_scopes
                or any(not isinstance(scope, str) or scope not in _MANAGEMENT_SCOPES for scope in requested_scopes)
                or requested_scopes != sorted(set(requested_scopes))):
                raise BackendClientError("Invalid management scopes.", code="UNKNOWN_MANAGEMENT_SUBJECT")
            self._state["management"] = {**saved, "clientId": client_id, "binding": binding, "scopes": requested_scopes}
            self._save_state_locked()  # A lost bind response must reuse the same operator subject.
            grant = await self._request_json("POST", _MANAGEMENT_PREFIX + "/subjects/bind", json_payload={
                "client_id": client_id, "expected_binding": binding, "scopes": requested_scopes})
            subject = grant.get("subject_id")
            capability = grant.get("subject_capability")
            scopes = grant.get("scopes")
            if grant.get("protocolVersion") != 1 or grant.get("binding") != binding or not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes) or sorted(scopes) != requested_scopes or not (
                isinstance(subject, str) and re.fullmatch(r"ops-[A-Za-z0-9_-]{10,128}", subject)
                and isinstance(capability, str) and re.fullmatch(r"[A-Za-z0-9_-]{32,256}", capability)
            ) or (saved.get("subjectId") and saved["subjectId"] != subject):
                raise BackendClientError("Management grant mismatch.", code="RUNTIME_IDENTITY_MISMATCH")
            result = {"clientId": client_id, "binding": binding, "subjectId": subject, "capability": capability, "scopes": requested_scopes}
            self._state["management"] = result
            self._save_state_locked()
            return result

    async def management_action(self, *, action: str, request_id: str, parameters: dict[str, Any],
                                require_existing_subject: bool = False) -> dict[str, Any]:
        if action not in _MANAGEMENT_ACTIONS or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", request_id):
            raise BackendClientError("Unsupported management request.", code="INVALID_MANAGEMENT_REQUEST")
        if action == "session_pin":
            from pydantic import ValidationError
            from core.web.services.external_management.contracts import SessionPin
            try:
                parameters = SessionPin.model_validate(parameters).model_dump()
            except ValidationError:
                raise BackendClientError("Invalid Session pin parameters.", code="INVALID_MANAGEMENT_REQUEST") from None
        grant = await self._management_grant(require_existing=require_existing_subject)
        result = await self._request_json("POST", f"{_MANAGEMENT_PREFIX}/actions/{action}",
            management_auth=(grant["subjectId"], grant["capability"]), json_payload={
                "request_id": request_id, "expected_binding": grant["binding"], "parameters": parameters})
        public = self._management_public_receipt(result, action=action, request_id=request_id)
        if action == "session_pin" and public["status"] == "completed" and (
            public["session"]["id"] != parameters["session_id"] or public["session"]["pinned"] is not parameters["pinned"]
        ):
            raise BackendClientError("Mismatched Session pin receipt.", code="BACKEND_PROTOCOL_ERROR")
        return public

    async def management_receipt(self, *, action: str, request_id: str) -> dict[str, Any]:
        if action not in _MANAGEMENT_ACTIONS or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", request_id):
            raise BackendClientError("Unsupported management request.", code="INVALID_MANAGEMENT_REQUEST")
        grant = await self._management_grant(require_existing=True)
        result = await self._request_json("GET", f"{_MANAGEMENT_PREFIX}/actions/{action}/requests/{request_id}",
            management_auth=(grant["subjectId"], grant["capability"]))
        return self._management_public_receipt(result, action=action, request_id=request_id)

    async def management_agent(self, *, agent_id: str) -> dict[str, Any]:
        if not isinstance(agent_id, str) or not 1 <= len(agent_id) <= 128:
            raise BackendClientError("Invalid Agent identifier.", code="INVALID_MANAGEMENT_REQUEST")
        grant = await self._management_grant(require_existing=False)
        result = await self._request_json("GET", f"{_MANAGEMENT_PREFIX}/agents/{quote(agent_id, safe='')}",
            management_auth=(grant["subjectId"], grant["capability"]))
        agent = result.get("agent")
        if not isinstance(agent, dict) or agent.get("agentId") != agent_id:
            raise BackendClientError("Invalid Agent projection.", code="BACKEND_PROTOCOL_ERROR")
        return {"agent": self._management_agent_view(agent)}

    async def management_avatar_options(self, *, offset: int = 0, limit: int = 20) -> dict[str, Any]:
        from pydantic import ValidationError
        from core.web.services.external_management.contracts import AvatarOptionsQuery, AvatarOptionsResponse
        try:
            query = AvatarOptionsQuery.model_validate({"offset": offset, "limit": limit})
        except ValidationError:
            raise BackendClientError("Invalid avatar query.", code="INVALID_MANAGEMENT_REQUEST") from None
        grant = await self._management_grant(require_existing=False)
        result = await self._request_json("GET", _MANAGEMENT_PREFIX + "/avatar-options?" + urlencode(query.model_dump()),
            management_auth=(grant["subjectId"], grant["capability"]))
        try:
            public = AvatarOptionsResponse.model_validate(result).model_dump()
            if public["offset"] != query.offset or len(public["options"]) > query.limit:
                raise ValueError("Avatar query response changed")
        except (ValidationError, ValueError):
            raise BackendClientError("Invalid avatar projection.", code="BACKEND_PROTOCOL_ERROR") from None
        return public

    async def management_session_list(self, **parameters) -> dict[str, Any]:
        from pydantic import ValidationError
        from core.web.services.external_management.contracts import SessionListQuery, SessionListResponse

        try:
            query = SessionListQuery.model_validate(parameters)
        except ValidationError:
            raise BackendClientError("Invalid Session list query.", code="INVALID_MANAGEMENT_REQUEST") from None
        grant = await self._management_grant(require_existing=False)
        result = await self._request_json("GET", _MANAGEMENT_PREFIX + "/sessions?" + urlencode(query.model_dump()),
            management_auth=(grant["subjectId"], grant["capability"]))
        try:
            public = SessionListResponse.model_validate(result).model_dump()
        except ValidationError:
            raise BackendClientError("Invalid Session list projection.", code="BACKEND_PROTOCOL_ERROR") from None
        if (public["offset"] != query.offset or public["limit"] > query.limit
            or query.agent_id and any(row["agentId"] != query.agent_id for row in public["sessions"])):
            raise BackendClientError("Session list query binding changed.", code="BACKEND_PROTOCOL_ERROR")
        return public

    async def management_session(self, *, session_id: str) -> dict[str, Any]:
        from pydantic import ValidationError

        from core.web.services.external_management.contracts import SessionMetadataQuery, SessionReadResponse

        try:
            query = SessionMetadataQuery.model_validate({"session_id": session_id})
        except ValidationError:
            raise BackendClientError("Invalid Session identifier.", code="INVALID_MANAGEMENT_REQUEST") from None
        grant = await self._management_grant(require_existing=False)
        result = await self._request_json("GET", f"{_MANAGEMENT_PREFIX}/sessions/{quote(query.session_id, safe='')}",
            management_auth=(grant["subjectId"], grant["capability"]))
        try:
            public = SessionReadResponse.model_validate(result).model_dump()
        except ValidationError:
            raise BackendClientError("Invalid Session projection.", code="BACKEND_PROTOCOL_ERROR") from None
        if public["session"]["id"] != query.session_id:
            raise BackendClientError("Session identity changed.", code="BACKEND_PROTOCOL_ERROR")
        return public

    async def management_session_config(self, *, session_id: str) -> dict[str, Any]:
        from pydantic import ValidationError
        from core.web.services.external_management.contracts import SessionMetadataQuery, SessionConfigResponse

        try:
            query = SessionMetadataQuery.model_validate({"session_id": session_id})
        except ValidationError:
            raise BackendClientError("Invalid Session identifier.", code="INVALID_MANAGEMENT_REQUEST") from None
        # The caller names a Session, not an Agent. Independently bind the DTO
        # to that Session's public owner before accepting the compiled snapshot.
        session = await self.management_session(session_id=query.session_id)
        grant = await self._management_grant(require_existing=False)
        result = await self._request_json("GET", f"{_MANAGEMENT_PREFIX}/sessions/{quote(query.session_id, safe='')}/config",
            management_auth=(grant["subjectId"], grant["capability"]))
        try:
            public = SessionConfigResponse.model_validate(result).model_dump()
        except ValidationError:
            raise BackendClientError("Invalid Session config projection.", code="BACKEND_PROTOCOL_ERROR") from None
        if public["config"]["sessionId"] != query.session_id or public["config"]["agentId"] != session["session"]["agentId"]:
            raise BackendClientError("Session config identity changed.", code="BACKEND_PROTOCOL_ERROR")
        return public

    async def management_session_config_compare(self, *, session_id: str) -> dict[str, Any]:
        from pydantic import ValidationError
        from core.web.services.external_management.contracts import SessionMetadataQuery, SessionConfigComparisonResponse

        try:
            query = SessionMetadataQuery.model_validate({"session_id": session_id})
        except ValidationError:
            raise BackendClientError("Invalid Session identifier.", code="INVALID_MANAGEMENT_REQUEST") from None
        session = await self.management_session(session_id=query.session_id)
        grant = await self._management_grant(require_existing=False)
        result = await self._request_json("GET", f"{_MANAGEMENT_PREFIX}/sessions/{quote(query.session_id, safe='')}/config-comparison",
            management_auth=(grant["subjectId"], grant["capability"]))
        try:
            public = SessionConfigComparisonResponse.model_validate(result).model_dump()
        except ValidationError:
            raise BackendClientError("Invalid Session config comparison.", code="BACKEND_PROTOCOL_ERROR") from None
        pinned, current = public["pinned"], public["current"]
        changed = [key for key in ("modelId", "contextWindow", "reasoningEffort") if pinned[key] != current[key]]
        if (public["sessionId"] != query.session_id or public["agentId"] != session["session"]["agentId"]
            or not all(re.fullmatch(re.escape(public["agentId"]) + r":[0-9a-f]{64}", item["agentConfigRevisionId"])
                       for item in (pinned, current))
            or public["sameRevision"] != (pinned["agentConfigRevisionId"] == current["agentConfigRevisionId"])
            or public["changedFields"] != changed or (public["sameRevision"] and changed)):
            raise BackendClientError("Session config comparison identity or values changed.", code="BACKEND_PROTOCOL_ERROR")
        return public

    async def management_documentation(self, *, operation_id: str | None = None, **query) -> dict[str, Any]:
        from pydantic import ValidationError

        from core.web.services.external_management.contracts import (
            DocumentationCatalogQuery,
            DocumentationDescribeQuery,
            DocumentationResponse,
        )
        try:
            if operation_id is None:
                parameters = DocumentationCatalogQuery.model_validate(query).model_dump()
                suffix = "/api-documentation/catalog?" + urlencode(parameters)
            else:
                if query:
                    raise ValueError("Unexpected documentation query")
                parameters = DocumentationDescribeQuery.model_validate({"operation_id": operation_id})
                suffix = "/api-documentation/operations/" + quote(parameters.operation_id, safe="")
        except (ValidationError, ValueError):
            raise BackendClientError("Invalid documentation query.", code="INVALID_MANAGEMENT_REQUEST") from None
        grant = await self._management_grant(require_existing=False)
        result = await self._request_json("GET", _MANAGEMENT_PREFIX + suffix,
            management_auth=(grant["subjectId"], grant["capability"]), timeout_seconds=20.0)
        try:
            public = DocumentationResponse.model_validate(result).model_dump(exclude_none=True)
        except ValidationError:
            raise BackendClientError("Invalid API documentation.", code="BACKEND_PROTOCOL_ERROR") from None
        if operation_id is not None and public.get("ok") and (public.get("operation") or {}).get("operationId") != operation_id:
            raise BackendClientError("API operation identity changed.", code="BACKEND_PROTOCOL_ERROR")
        return public

    @staticmethod
    def _management_agent_view(agent: dict[str, Any]) -> dict[str, Any]:
        return {key: deepcopy(agent[key]) for key in (
            "agentId", "directSessionId", "displayName", "configRevision", "updatedAt", "modelId", "avatarImagePath") if key in agent}

    @staticmethod
    def _management_public_receipt(payload: dict[str, Any], *, action: str, request_id: str) -> dict[str, Any]:
        if payload.get("action") != action or payload.get("requestId") != request_id or payload.get("status") not in {"completed", "unknown"}:
            raise BackendClientError("Invalid management receipt.", code="BACKEND_PROTOCOL_ERROR")
        result = {key: deepcopy(payload[key]) for key in ("status", "action", "requestId", "verified", "reused", "code") if key in payload}
        if action == "session_pin":
            from pydantic import ValidationError
            from core.web.services.external_management.contracts import ReceiptResponse
            try:
                receipt = ReceiptResponse.model_validate(payload)
                if (receipt.status == "completed" and (receipt.session is None or receipt.verified is not True)
                    or receipt.status == "unknown" and (receipt.session is not None or receipt.verified is not False)
                    or any(getattr(receipt, key) is not None for key in ("agent", "teamRun", "phase", "resumeAllowed"))):
                    raise ValueError("Invalid Session receipt state")
                return receipt.model_dump(exclude_none=True)
            except (ValidationError, ValueError) as exc:
                raise BackendClientError("Invalid Session receipt.", code="BACKEND_PROTOCOL_ERROR") from exc
        if isinstance(payload.get("agent"), dict):
            result["agent"] = ManagedAgentBackendClient._management_agent_view(payload["agent"])
        if action == "team_run":
            from pydantic import ValidationError

            from core.web.services.external_management.contracts import TeamRunView

            phase, resume = payload.get("phase"), payload.get("resumeAllowed")
            if phase not in {None, "materialization_pending", "materialized", "flow_saved", "started"} or (resume is not None and not isinstance(resume, bool)):
                raise BackendClientError("Invalid team receipt.", code="BACKEND_PROTOCOL_ERROR")
            if phase is not None:
                result["phase"] = phase
            if resume is not None:
                result["resumeAllowed"] = resume
            team = payload.get("teamRun")
            if team is not None:
                if not isinstance(team, dict):
                    raise BackendClientError("Invalid team projection.", code="BACKEND_PROTOCOL_ERROR")
                fields = TeamRunView.model_fields
                try:
                    # Drop private additions while validating all public DTO
                    # fields; nested rows have their own positive field lists.
                    public = {key: deepcopy(value) for key, value in team.items() if key in fields}
                    for key, allowed in (("attempts", {"nodeId", "number", "agentId", "sessionId", "turnId", "status"}),
                                         ("artifactRefs", {"nodeId", "sessionId", "turnId"})):
                        if isinstance(public.get(key), list):
                            public[key] = [{field: value for field, value in row.items() if field in allowed}
                                           if isinstance(row, dict) else row for row in public[key]]
                    result["teamRun"] = TeamRunView.model_validate(public).model_dump(exclude_none=True)
                except ValidationError as exc:
                    raise BackendClientError("Invalid team projection.", code="BACKEND_PROTOCOL_ERROR") from exc
        return result

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
        require_existing_capability: bool = False,
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
                if require_existing_capability:
                    raise BackendClientError("no durable credential for this request", code="UNKNOWN_REQUEST")
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
        return await self._record_acceptance(request_id, capability, payload)

    async def get_task_for_request(self, *, client_request_id: str) -> dict[str, Any]:
        """Recover a native ref after a lost start response, without its prompt."""
        request_id = str(client_request_id or "").strip()
        async with self._state_lock:
            request_state = self._state.get("requests", {}).get(request_id) or {}
            capability = str(request_state.get("taskCapability") or "").strip()
        if not capability:
            raise BackendClientError("no durable credential for this request", code="UNKNOWN_REQUEST")
        payload = await self._request_json("GET",
            "/api/v1/external-agent/task-request?" + urlencode({"client_request_id": request_id}),
            task_capability=capability)
        return await self._record_acceptance(request_id, capability, payload)

    async def _record_acceptance(self, request_id: str, capability: str,
                                 payload: dict[str, Any]) -> dict[str, Any]:
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

    async def heartbeat_task(self, *, task_id: str) -> dict[str, Any]:
        """Renew only one already-owned task; never construct a new capability."""
        task_state = await self._task_state(task_id)
        if str(task_state.get("status") or "") in TASK_TERMINAL_STATUSES:
            return {"taskId": task_id, "status": task_state["status"]}
        payload = await self._request_json(
            "POST", f"/api/v1/external-agent/tasks/{task_id}/heartbeat",
            task_capability=str(task_state["taskCapability"]),
            json_payload={"lease_id": str(task_state["leaseId"])},
        )
        await self._record_task_status(task_id, payload)
        return self._public_payload(payload)

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
        management_auth: tuple[str, str] | None = None,
        json_payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        await self._ensure_connected()
        headers = {
            self._control_header: self._control_token,
            ADAPTER_CONNECTION_HEADER: self.adapter_connection_id,
        }
        if task_capability:
            headers[TASK_CAPABILITY_HEADER] = task_capability
        if management_auth is not None:
            headers["X-Vibelution-Management-Subject"], headers["X-Vibelution-Management-Capability"] = management_auth
        async with httpx.AsyncClient(
            base_url=self._base_url,
            transport=self.transport,
            timeout=self.timeout_seconds if timeout_seconds is None else max(0.5, min(float(timeout_seconds), 30.0)),
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
            resolve_project_runtime_home(self.project_root) / "launcher" / "state.json"
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
        self._management_state_invalid = self.state_path.exists() and (
            payload.get("projectRoot") != str(self.project_root)
            or ("management" in payload and not isinstance(payload["management"], dict)))
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
            "management": deepcopy(payload.get("management")) if isinstance(payload.get("management"), dict) else {},
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
