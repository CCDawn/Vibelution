"""Launcher-only transport adapter over the unchanged external Agent SDK."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import quote

from core.external_agent.backend_client import BackendClientError, ManagedAgentBackendClient, _read_json
from core.infrastructure.launcher_assistant_authority import current_launcher_authority

_EXTERNAL_PREFIX = "/api/v1/external-agent/"
_LOCAL_PREFIX = "/api/local-assistant/v1/external-agent/"
_RECOVERY_PREFIX = "/api/v1/launcher-assistant-management/subjects/recovery/"


class LocalAssistantBackendClient(ManagedAgentBackendClient):
    """Route task traffic only when the host explicitly supplied local authority."""

    def __init__(self, project_root: Path, *, capability: str | None = None, **kwargs: Any) -> None:
        credential = current_launcher_authority() if capability is None else capability
        if credential is not None and (not isinstance(credential, str)
                or (credential != "" and re.fullmatch(r"[A-Za-z0-9_-]{32,128}", credential, re.ASCII) is None)):
            raise ValueError("Invalid Launcher authority credential.")
        # Keep this out of the inherited SDK state/ledger. File access belongs
        # exclusively to host bootstrap and the backend verifier.
        self._launcher_capability = credential or ""
        super().__init__(project_root, **kwargs)

    async def management_agent_list(self, **parameters) -> dict[str, Any]:
        return await super().management_agent_list(**{**parameters,
            "dispatch_context": "launcher_local" if self._launcher_capability else "external"})

    @property
    def management_epoch(self) -> str:
        return (self._state.get("management") or {}).get("recoveryEpoch", "")

    async def _management_grant(self, *, require_existing: bool):
        saved = self._state.get("management") or {}
        if self._launcher_capability and saved.get("subjectId") and saved.get("capability"):
            if saved.get("revoked"):
                raise BackendClientError("Management authorization revoked.", code="SUBJECT_REVOKED")
            # A normal read/write must never mint a subject after store loss.
            return await self._original_management_grant(require_original=True, require_complete=True)
        return await super()._management_grant(require_existing=require_existing)

    async def _recovery_source(self):
        from core.web.services.external_management.recovery import RecoveryIdentity

        if not self._launcher_capability:
            raise BackendClientError("Launcher authority required.", code="LAUNCHER_AUTHORITY_REQUIRED")
        old = await self._original_management_grant(require_original=True, require_complete=True)
        if old.get("revoked"):
            raise BackendClientError("Management authorization revoked.", code="SUBJECT_REVOKED")
        try:
            return RecoveryIdentity.model_validate({"client_id": old.get("clientId"),
                "subject_id": old["subjectId"], "expected_binding": old["binding"]}).model_dump()
        except ValueError:
            raise BackendClientError("Original credentials are invalid.", code="UNKNOWN_MANAGEMENT_SUBJECT") from None

    def _recovery_challenge(self, payload: dict, scopes: list[str]) -> str:
        from core.web.services.external_management.store import digest
        return hmac.digest(self._launcher_capability.encode(), digest([payload, scopes]).encode(), "sha256").hex()

    async def management_authorization_status(self, *, planned_scopes: list[str] | None = None):
        pending = (self._state.get("management") or {}).get("pendingRecovery")
        if pending and self._launcher_capability:
            await self.management_recover(**pending)
        try:
            return await super().management_authorization_status()
        except BackendClientError as exc:
            if exc.code != "SUBJECT_DENIED" or not self._launcher_capability:
                raise
            original = exc
        payload = await self._recovery_source()
        try:
            plan = await self._request_json("POST", _RECOVERY_PREFIX + "check",
                management_auth=("launcher-local", self._launcher_capability), json_payload=payload)
        except BackendClientError as exc:
            if exc.code in {"ORIGINAL_GRANT_PRESENT", "BACKEND_ERROR"}:
                raise original from None
            raise
        if plan.get("available") is not True:
            raise original
        result = {"status": "recovery_required", "scopes": []}
        if planned_scopes:
            result["recovery_challenge"] = self._recovery_challenge(payload, planned_scopes)
        return result

    async def management_recover(self, *, request_id: str, scopes: list[str], challenge: str) -> dict:
        from core.web.services.external_management.contracts import BoundSubjectResponse
        from core.web.services.external_management.recovery import RecoverSubject, recovery_key

        async with self._state_lock:
            payload = await self._recovery_source()
            if not secrets.compare_digest(challenge, self._recovery_challenge(payload, scopes)):
                raise BackendClientError("Recovery approval is stale.", code="RECOVERY_CONFLICT")
            binding = payload["expected_binding"]
            key = recovery_key(binding, payload["client_id"], payload["subject_id"])
            expected_client = "recovered-" + key
            expected_subject = "ops-" + key[:32]
            payload = RecoverSubject.model_validate({**payload, "request_id": request_id, "scopes": scopes}).model_dump()
            old = self._state["management"]
            approved = {"request_id": request_id, "scopes": scopes, "challenge": challenge}
            pending = old.get("pendingRecovery")
            if pending is not None and pending != approved:
                raise BackendClientError("An earlier recovery is unresolved.", code="RECOVERY_CONFLICT")
            self._state["management"] = {**old, "pendingRecovery": approved}
            self._save_state_locked()
            for attempt in range(2):
                try:
                    response = await self._request_json("POST", _RECOVERY_PREFIX + "enroll",
                        management_auth=("launcher-local", self._launcher_capability), json_payload=payload)
                    break
                except BackendClientError as exc:
                    ambiguous = exc.code in {"BACKEND_TIMEOUT", "BACKEND_UNAVAILABLE", "MANAGEMENT_UNAVAILABLE",
                                             "MANAGEMENT_BUSY", "BACKEND_PROTOCOL_ERROR"}
                    if exc.code in {"ORIGINAL_GRANT_PRESENT", "SUBJECT_REVOKED", "TARGET_BINDING_CHANGED",
                                    "RECOVERY_CONFLICT", "LAUNCHER_AUTHORITY_REQUIRED", "OPERATOR_CONTROL_REQUIRED",
                                    "INVALID_INPUT"}:
                        self._state["management"].pop("pendingRecovery", None)
                        self._save_state_locked()
                    if attempt or not ambiguous:
                        raise
            client_id = response.pop("client_id", None)
            try:
                grant = BoundSubjectResponse.model_validate(response)
                if (client_id != expected_client or grant.subject_id != expected_subject or grant.scopes != scopes
                        or grant.binding.model_dump() != binding
                        or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", grant.subject_capability)):
                    raise ValueError("Recovery identity disagrees")
            except ValueError:
                raise BackendClientError("Invalid recovery response.", code="BACKEND_PROTOCOL_ERROR") from None
            saved = {"clientId": client_id, "subjectId": grant.subject_id, "capability": grant.subject_capability,
                     "binding": binding, "scopes": scopes, "recoveryEpoch": key}
            current = await self._authorization_state(saved)
            if current["scopes"] != scopes or current["grantRevision"] != 0:
                raise BackendClientError("Recovery authorization changed.", code="RECOVERY_CONFLICT")
            self._state["management"] = saved
            self._save_state_locked()
            return {"status": "completed", "scopes": scopes, "grantRevision": 0}

    def _load_state(self) -> dict[str, Any]:
        state = super()._load_state()
        payload = _read_json(self.state_path)
        namespaces = payload.get("transportNamespaces")
        state["transportNamespaces"] = {
            digest: namespace for digest, namespace in namespaces.items()
            if isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest)
            and isinstance(namespace, str) and namespace in {"local", "external"}
        } if payload.get("projectRoot") == str(self.project_root) and isinstance(namespaces, dict) else {}
        return state

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
        if not request_id:
            raise BackendClientError("A stable request identity is required.", code="INVALID_REQUEST")
        async with self._state_lock:
            requests = self._state.setdefault("requests", {})
            saved = requests.get(request_id)
            capability = str(saved.get("taskCapability") or "").strip() if isinstance(saved, dict) else ""
            namespaces = self._state.setdefault("transportNamespaces", {})
            if capability:
                # A pre-upgrade request can already have been accepted after a
                # lost response. Absence of metadata always means external.
                namespaces.setdefault(hashlib.sha256(capability.encode()).hexdigest(), "external")
            else:
                if require_existing_capability:
                    raise BackendClientError("no durable credential for this request", code="UNKNOWN_REQUEST")
                capability = secrets.token_urlsafe(32)
                requests[request_id] = {"taskCapability": capability}
                namespaces[hashlib.sha256(capability.encode()).hexdigest()] = (
                    "local" if self._launcher_capability else "external")
            # Persist the capability and its immutable transport together before
            # the base implementation can send the first idempotent POST.
            self._save_state_locked()
            local_request = namespaces.get(hashlib.sha256(capability.encode()).hexdigest()) == "local"
        try:
            return await super().start_task(
                agent_id=agent_id, task=task, permission_profile=permission_profile,
                client_request_id=request_id, title=title, require_existing_capability=True,
            )
        except BackendClientError as start_error:
            if (not local_request or not self._launcher_capability
                    or start_error.code not in {"BACKEND_TIMEOUT", "BACKEND_UNAVAILABLE"}):
                raise
            # A slow checkout or lost acknowledgement can leave an accepted
            # queued task behind. Recover that exact authenticated request once;
            # never replay the POST or mint another capability/task identity.
            try:
                return await self.get_task_for_request(client_request_id=request_id)
            except BackendClientError:
                pass
            raise

    async def _cleanup_capability(self, task_id: str) -> tuple[str, str]:
        try:
            state = await self._task_state(task_id)
        except BackendClientError as error:
            if error.code == "TASK_NOT_FOUND":
                # Keep the local ledger stage distinguishable from the source's
                # own authenticated 404: a lost local capability record never
                # proves that the source task is gone.
                raise BackendClientError("local cleanup capability record is unavailable",
                                         code="TASK_CAPABILITY_UNAVAILABLE") from None
            raise
        capability = state["taskCapability"]
        async with self._state_lock:
            namespace = self._state.get("transportNamespaces", {}).get(
                hashlib.sha256(capability.encode()).hexdigest(), "external")
        if not self._launcher_capability:
            raise BackendClientError("Launcher authority is unavailable.", code="LAUNCHER_AUTHORITY_REQUIRED")
        return capability, namespace

    async def _request_cleanup(self, task_id: str, suffix: str, payload: dict[str, Any]) -> dict[str, Any]:
        capability, namespace = await self._cleanup_capability(task_id)
        # Old capabilities keep their original external transport for every
        # ordinary task operation. Only operator cleanup uses this explicit,
        # authenticated compatibility endpoint; no namespace migration occurs.
        prefix = _EXTERNAL_PREFIX + "tasks" if namespace == "local" else _LOCAL_PREFIX + "legacy-tasks"
        return await self._request_json("POST", f"{prefix}/{quote(task_id, safe='')}/{suffix}",
            task_capability=capability, management_auth=("launcher-local", self._launcher_capability),
            json_payload=payload)

    async def preview_task_cleanup(self, task_id: str) -> dict[str, Any]:
        return await self._request_cleanup(task_id, "cleanup/preview", {})

    async def cleanup_task(self, task_id: str, revision: str, fingerprint: str) -> dict[str, Any]:
        return await self._request_cleanup(task_id, "cleanup", {"revision": revision, "fingerprint": fingerprint})

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        task_capability: str = "",
        management_auth: tuple[str, str] | None = None,
        json_payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        max_response_bytes: int | None = None,
    ) -> dict[str, Any]:
        namespace = "external"
        if task_capability:
            async with self._state_lock:
                namespace = self._state.get("transportNamespaces", {}).get(
                    hashlib.sha256(task_capability.encode()).hexdigest(), "external")
        discovery = (not task_capability and method == "GET"
                     and path.split("?", 1)[0] == _EXTERNAL_PREFIX + "agents")
        if namespace == "local" and not self._launcher_capability:
            raise BackendClientError("Launcher authority is unavailable.", code="LAUNCHER_AUTHORITY_REQUIRED")
        if self._launcher_capability and (namespace == "local" or discovery) and path.startswith(_EXTERNAL_PREFIX):
            path = _LOCAL_PREFIX + path[len(_EXTERNAL_PREFIX):]
            management_auth = ("launcher-local", self._launcher_capability)
        # The base SDK retains its raw external /info identity handshake,
        # capability isolation, payload/timeout limits and single reconnect.
        return await super()._request_json(
            method, path, task_capability=task_capability, management_auth=management_auth,
            json_payload=json_payload, timeout_seconds=timeout_seconds, max_response_bytes=max_response_bytes,
        )
