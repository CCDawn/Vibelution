"""Operator-granted neutral subjects; intents are receipts, never a second scheduler."""
from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from .contracts import (
    ACTION_MODELS,
    ACTION_SCOPES,
    SCOPES,
    Binding,
    BindSubject,
    DocumentationCatalogQuery,
    DocumentationDescribeQuery,
    Envelope,
    SessionMetadataQuery,
    contracts,
)
from .store import Store, digest


class ManagementError(Exception):
    def __init__(self, code: str, status_code: int = 403):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True)
class TargetIdentity:
    binding: dict
    signature: str


def _subset(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and _subset(value, actual[key]) for key, value in expected.items())
    return expected == actual


def _agent_view(agent: dict) -> dict:
    text = lambda key: str(agent.get(key) or "")[:200]
    model_id = (agent.get("llmBindings", {}).get("dialogue") or {}).get("modelId", "")
    return {"agentId": text("agentId"), "directSessionId": text("directSessionId"), "displayName": text("displayName"),
            "configRevision": max(0, int(agent.get("configRevision") or 0)), "updatedAt": text("updatedAt"),
            "modelId": str(model_id)[:200], "avatarImagePath": text("avatarImagePath")}


class ManagementService:
    def __init__(self, root: Path, *, identity: Callable[[], TargetIdentity], native, teams=None):
        self.root = Path(root)
        self.identity = identity
        self.native = native
        self.store = Store(self.root)
        self.teams = teams

    def _team_intents(self, grant):
        from .team import TeamIntents, TeamOwner
        from .team_native import NativeTeamGateway
        owner = TeamOwner(grant["subject_id"], grant["binding"], grant["authority"], self.root)
        native = self.teams if self.teams is not None else NativeTeamGateway(self.native.project_root)
        return TeamIntents(owner, native)

    def binding(self) -> dict:
        current = self.identity()
        Binding.model_validate(current.binding)
        return {"protocolVersion": 1, "binding": current.binding, "scopes": list(SCOPES), "actions": contracts()}

    def _expected(self, expected: dict):
        current = self.identity()
        if expected != current.binding:
            raise ManagementError("TARGET_BINDING_CHANGED", 409)
        return current

    def bind(self, payload: dict) -> dict:
        try:
            request = BindSubject.model_validate(payload)
        except ValidationError:
            raise ManagementError("INVALID_INPUT", 422) from None
        current = self._expected(request.expected_binding.model_dump())
        scopes = sorted(set(request.scopes))
        if len(scopes) != len(request.scopes):
            raise ManagementError("INVALID_INPUT", 422)
        client_path = self.store.path("clients", request.client_id)
        with self.store.lock("clients", request.client_id):
            index = self.store.read(client_path)
            if index is not None:
                grant = self.store.read(self.store.path("subjects", index["subject_id"]))
                if (not grant or grant.get("binding") != current.binding or grant.get("authority") != current.signature
                    or grant.get("scopes") != scopes):
                    raise ManagementError("SUBJECT_GRANT_CONFLICT", 409)
            else:
                grant = {"subject_id": "ops-" + uuid4().hex, "subject_capability": secrets.token_urlsafe(48),
                         "binding": current.binding, "authority": current.signature, "scopes": scopes}
                # The private grant is durable before its client index and before returning credentials.
                self.store.write(self.store.path("subjects", grant["subject_id"]), grant)
                self.store.write(client_path, {"subject_id": grant["subject_id"]})
        return {key: grant[key] for key in ("subject_id", "subject_capability", "binding", "scopes")} | {"protocolVersion": 1}

    def _authorize(self, subject: str, capability: str, scope: str | None, expected: dict | None = None) -> dict:
        if not re.fullmatch(r"ops-[0-9a-f]{32}", subject) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", capability):
            raise ManagementError("SUBJECT_DENIED")
        grant = self.store.read(self.store.path("subjects", subject))
        if not grant or not secrets.compare_digest(str(grant.get("subject_capability") or ""), capability):
            raise ManagementError("SUBJECT_DENIED")
        current = self.identity()
        if grant.get("binding") != current.binding or grant.get("authority") != current.signature:
            raise ManagementError("TARGET_BINDING_CHANGED", 409)
        if expected is not None and expected != current.binding:
            raise ManagementError("TARGET_BINDING_CHANGED", 409)
        if scope is not None and scope not in grant.get("scopes", []):
            raise ManagementError("SCOPE_DENIED")
        return grant

    def _authorization_upgrades(self):
        from .authorization_upgrade import UpgradeOwner
        # This self-subject operation is exposed only by operator-control
        # transport. Old read scopes do not grant an upgrade privilege.
        return UpgradeOwner(self.store,
            lambda subject, capability, expected=None: self._authorize(subject, capability, None, expected), self.identity)

    def authorization_status(self, subject, capability):
        from .contracts import AuthorizationStateResponse
        return AuthorizationStateResponse.model_validate(self._authorization_upgrades().current_subject(subject, capability)).model_dump()

    def read_agent(self, subject: str, capability: str, agent_id: str) -> dict:
        self._authorize(subject, capability, "agents:read")
        if not isinstance(agent_id, str) or not 1 <= len(agent_id) <= 128:
            raise ManagementError("INVALID_INPUT", 422)
        agent = self.native.read(agent_id)
        if not agent:
            raise ManagementError("AGENT_UNAVAILABLE", 404)
        return {"agent": _agent_view(agent)}

    def read_avatar_options(self, subject: str, capability: str, *, offset=0, limit=20) -> dict:
        from .contracts import AvatarOption, AvatarOptionsQuery, AvatarOptionsResponse
        self._authorize(subject, capability, "agents:read")
        try:
            query = AvatarOptionsQuery.model_validate({"offset": offset, "limit": limit})
        except ValidationError:
            raise ManagementError("INVALID_INPUT", 422) from None
        try:
            raw = self.native.avatar_options()
            if not isinstance(raw, list) or len(raw) > 50000:
                raise ValueError("Invalid avatar list")
            # Validate the whole native snapshot, including candidates outside
            # this page. A malformed tail cannot be silently skipped.
            rows = [AvatarOption.model_validate(row).model_dump() for row in raw]
            end = query.offset + query.limit
            return AvatarOptionsResponse.model_validate({"options": rows[query.offset:end], "total": len(rows),
                "offset": query.offset, "nextOffset": end if end < len(rows) else None,
                "untrustedContent": True}).model_dump()
        except (ValidationError, ValueError, TypeError):
            raise ManagementError("AVATAR_LIBRARY_UNAVAILABLE", 503) from None

    def read_sessions(self, subject: str, capability: str, **parameters) -> dict:
        from .contracts import SessionListQuery, SessionListResponse
        self._authorize(subject, capability, "sessions:read")
        try:
            query = SessionListQuery.model_validate(parameters)
        except ValidationError:
            raise ManagementError("INVALID_INPUT", 422) from None
        try:
            return SessionListResponse.model_validate(self.native.read_sessions(query)).model_dump()
        except ValidationError:
            raise ManagementError("SESSION_LIST_UNAVAILABLE", 503) from None

    def _directory_read(self, subject, capability, action, parameters):
        from .contracts import (DirectoryQuery, TeamReadQuery, RoomReadQuery, TeamListResponse,
            TeamReadResponse, RoomListResponse, RoomReadResponse)
        scope, query_model, response_model = {
            "team_list": ("teams:directory:read", DirectoryQuery, TeamListResponse),
            "team_get": ("teams:directory:read", TeamReadQuery, TeamReadResponse),
            "room_list": ("rooms:read", DirectoryQuery, RoomListResponse),
            "room_get": ("rooms:read", RoomReadQuery, RoomReadResponse),
        }[action]
        self._authorize(subject, capability, scope)
        try:
            query = query_model.model_validate(parameters)
        except ValidationError:
            raise ManagementError("INVALID_INPUT", 422) from None
        if action == "team_list":
            raw = self.native.read_teams(query)
        elif action == "team_get":
            raw = self.native.read_team(query.team_id, query)
        elif action == "room_list":
            raw = self.native.read_rooms(query)
        else:
            raw = self.native.read_room(query.room_id)
        try:
            return response_model.model_validate(raw).model_dump()
        except ValidationError:
            raise ManagementError("DIRECTORY_UNAVAILABLE", 503) from None

    def read_teams(self, subject, capability, **parameters):
        return self._directory_read(subject, capability, "team_list", parameters)

    def read_team(self, subject, capability, team_id, **parameters):
        return self._directory_read(subject, capability, "team_get", {**parameters, "team_id": team_id})

    def read_rooms(self, subject, capability, **parameters):
        return self._directory_read(subject, capability, "room_list", parameters)

    def read_room(self, subject, capability, room_id):
        return self._directory_read(subject, capability, "room_get", {"room_id": room_id})

    def read_session(self, subject: str, capability: str, session_id: str) -> dict:
        self._authorize(subject, capability, "sessions:read")
        try:
            query = SessionMetadataQuery.model_validate({"session_id": session_id})
        except ValidationError:
            raise ManagementError("INVALID_INPUT", 422) from None
        return self.native.read_session(query.session_id)

    def read_session_config(self, subject: str, capability: str, session_id: str) -> dict:
        from .contracts import SessionMetadataQuery
        self._authorize(subject, capability, "sessions:read")
        try:
            query = SessionMetadataQuery.model_validate({"session_id": session_id})
        except ValidationError:
            raise ManagementError("INVALID_INPUT", 422) from None
        return self.native.read_session_config(query.session_id)

    def read_session_config_comparison(self, subject: str, capability: str, session_id: str) -> dict:
        from .contracts import SessionMetadataQuery
        self._authorize(subject, capability, "sessions:read")
        try:
            query = SessionMetadataQuery.model_validate({"session_id": session_id})
        except ValidationError:
            raise ManagementError("INVALID_INPUT", 422) from None
        return self.native.read_session_config_comparison(query.session_id)

    def read_session_parameters(self, subject: str, capability: str, session_id: str) -> dict:
        from .contracts import SessionParametersResponse
        self._authorize(subject, capability, "sessions:read")
        self._authorize(subject, capability, "sessions:parameters:read")
        try:
            query = SessionMetadataQuery.model_validate({"session_id": session_id})
        except ValidationError:
            raise ManagementError("INVALID_INPUT", 422) from None
        try:
            return SessionParametersResponse.model_validate(self.native.read_session_parameters(query.session_id)).model_dump()
        except ValidationError:
            raise ManagementError("SESSION_PARAMETERS_UNAVAILABLE", 503) from None

    def documentation_catalog(self, subject: str, capability: str, *, query="", tag="", offset=0, limit=20) -> dict:
        from .documentation import api_catalog
        self._authorize(subject, capability, "platform:describe")
        try:
            parameters = DocumentationCatalogQuery.model_validate({"query": query, "tag": tag, "offset": offset, "limit": limit})
        except ValidationError:
            raise ManagementError("INVALID_INPUT", 422) from None
        self.native._owners()  # The documented registry belongs to this canonical backend binding.
        return api_catalog(**parameters.model_dump())

    def documentation_describe(self, subject: str, capability: str, operation_id: str) -> dict:
        from .documentation import api_describe
        self._authorize(subject, capability, "platform:describe")
        try:
            parameters = DocumentationDescribeQuery.model_validate({"operation_id": operation_id})
        except ValidationError:
            raise ManagementError("INVALID_INPUT", 422) from None
        self.native._owners()
        return api_describe(parameters.operation_id)

    def _request_key(self, subject: str, action: str, request_id: str) -> str:
        if action not in ACTION_MODELS or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", request_id):
            raise ManagementError("INVALID_INPUT", 422)
        return digest([subject, action, request_id])

    def _receipt(self, record: dict, *, reused: bool) -> dict:
        if record.get("receipt"):
            return {**record["receipt"], "reused": reused}
        return {"status": "unknown", "action": record["action"], "requestId": record["requestId"],
                "verified": False, "reused": reused, "code": "OPERATION_UNCONFIRMED"}

    def _verify(self, record: dict, agent: dict | None) -> bool:
        if not isinstance(agent, dict) or not agent.get("agentId") or agent.get("status") != "active":
            return False
        if agent.get("roleKey") == "personal_assistant" or (agent.get("metadata") or {}).get("personalAssistantProfile"):
            return False
        parameters = record["parameters"]
        metadata = agent.get("metadata") or {}
        if record["action"] == "agent_create":
            low_policy = {"allowedTools": [], "preferredTools": [], "readScopes": [], "writeScopes": [],
                          "networkAccess": "none", "mutationAccess": "none"}
            delegation = {"allowSubagents": False, "allowWakeMessages": False}
            registry_matches = (metadata.get("externalManagementCreation") == record["marker"] and bool(agent.get("directSessionId"))
                and agent.get("displayName") == parameters["display_name"] and agent.get("roleKey") == "assistant_worker"
                and agent.get("permissionPreset") == "request_approval"
                and _subset({"dialogue": {"modelId": parameters["model_id"]}}, agent.get("llmBindings"))
                and _subset({"mission": parameters["mission"]}, agent.get("taskProfile"))
                and _subset(low_policy, agent.get("toolPolicy"))
                and _subset(delegation, metadata.get("delegationPolicy")))
            if not registry_matches:
                return False
            compiled = self.native.compiled(agent["agentId"], agent["directSessionId"])
            return _subset({"displayName": parameters["display_name"], "permissionPreset": "request_approval",
                "llmBindings": {"dialogue": {"modelId": parameters["model_id"]}}, "taskProfile": {"mission": parameters["mission"]},
                "toolPolicy": low_policy, "delegationPolicy": delegation}, compiled)
        if agent.get("agentId") != parameters["agent_id"] or metadata.get("externalManagementMutation") != record["marker"]:
            return False
        if record["action"] == "agent_update":
            return (int(agent.get("configRevision") or 0) > parameters["expected_config_revision"]
                    and _subset(parameters["updates"], agent)
                    and _subset(parameters["updates"], self.native.current_compiled(agent["agentId"])))
        if parameters["reset_to_default"]:
            return bool(agent.get("avatarImagePath")) and metadata.get("avatarImageSource") == "default"
        return agent.get("avatarImagePath") == parameters["avatar_image_path"]

    def _confirm(self, record: dict) -> bool:
        if record["action"] == "agent_archive":
            try:
                from .contracts import AgentView
                agent = self.native.read_archive_state(record["parameters"]["agent_id"])
                if (not isinstance(agent, dict) or agent.get("agentId") != record["parameters"]["agent_id"]
                    or agent.get("status") != "archived" or type(agent.get("configRevision")) is not int
                    or agent["configRevision"] < record["parameters"]["expected_config_revision"]):
                    return False
                view = AgentView.model_validate(_agent_view(agent)).model_dump()
                record["receipt"] = {"status": "completed", "action": record["action"], "requestId": record["requestId"],
                    "verified": True, "agent": view}
                return True
            except Exception:  # noqa: BLE001 -- unknown intent permits readback only
                return False
        if record["action"] == "session_pin":
            # A completed receipt freezes this first canonical observation;
            # current state remains available through session_get.
            try:
                from .contracts import SessionReadResponse
                session = SessionReadResponse.model_validate(self.native.read_session(record["sessionId"])).session
                if session.id != record["sessionId"] or session.pinned is not record["parameters"]["pinned"]:
                    return False
                record["receipt"] = {"status": "completed", "action": record["action"], "requestId": record["requestId"],
                    "verified": True, "session": session.model_dump()}
                return True
            except Exception:  # noqa: BLE001 -- unavailable metadata never authorizes a repeat write
                return False
        try:
            if record["action"] == "agent_create":
                candidates = self.native.find_created(record["marker"]["requestKey"])
                if len(candidates) != 1:
                    return False
                agent = candidates[0]
                if record.get("agentId") and agent.get("agentId") != record["agentId"]:
                    return False
            else:
                agent = self.native.read(record["parameters"]["agent_id"])
            if not self._verify(record, agent):
                return False
            record["receipt"] = {"status": "completed", "action": record["action"], "requestId": record["requestId"],
                                 "verified": True, "agent": _agent_view(agent)}
            return True
        except Exception:  # noqa: BLE001 -- unavailable recovery reads cannot authorize a repeat write
            return False  # An unavailable native read never authorizes another write.

    def invoke(self, subject: str, capability: str, action: str, payload: dict) -> dict:
        if action not in ACTION_MODELS:
            raise ManagementError("UNKNOWN_ACTION", 404)
        try:
            envelope = Envelope.model_validate(payload)
        except ValidationError:
            raise ManagementError("INVALID_INPUT", 422) from None
        grant = self._authorize(subject, capability, ACTION_SCOPES[action], envelope.expected_binding.model_dump())
        try:
            from json import dumps
            if len(dumps(envelope.parameters, ensure_ascii=False, allow_nan=False).encode()) > 16_000:
                raise ValueError("parameters too large")
            parameters = ACTION_MODELS[action].model_validate(envelope.parameters).model_dump(exclude_unset=action == "agent_update")
        except (ValidationError, ValueError):
            raise ManagementError("INVALID_INPUT", 422) from None
        key = self._request_key(subject, action, envelope.request_id)
        if action == "authorization_upgrade":
            return self._authorization_upgrades().invoke(subject, capability, envelope.request_id,
                expected_binding=envelope.expected_binding.model_dump(), **parameters)
        if action == "team_run":
            return self._team_intents(grant).run(envelope.request_id, parameters)
        fingerprint = digest(parameters)
        path = self.store.path("requests", key)
        with self.store.lock("requests", key):
            record = self.store.read(path)
            if record is not None:
                if record.get("fingerprint") != fingerprint or record.get("binding") != grant["binding"]:
                    raise ManagementError("IDEMPOTENCY_CONFLICT", 409)
                if record.get("failure"):
                    raise ManagementError(record["failure"]["code"], record["failure"]["status_code"])
                if not record.get("receipt") and self._confirm(record):
                    self.store.write(path, record)
                return self._receipt(record, reused=True)
            marker = {"subjectType": "operator", "subjectId": subject, "requestKey": key, "requestFingerprint": fingerprint}
            record = {"action": action, "requestId": envelope.request_id, "fingerprint": fingerprint,
                      "binding": grant["binding"], "parameters": parameters, "marker": marker}
            if action == "session_pin":
                record["sessionId"] = parameters["session_id"]
            self.store.write(path, record)  # Admission is durable before any native side effect.
            try:
                if action == "session_pin":
                    self.native.pin_session(parameters)
                else:
                    agent = getattr(self.native, {"agent_create": "create", "agent_update": "update", "agent_avatar": "avatar", "agent_archive": "archive"}[action])(parameters, marker)
            except ManagementError as exc:
                record["failure"] = {"code": exc.code, "status_code": exc.status_code}
                self.store.write(path, record)
                raise
            except Exception:  # noqa: BLE001 -- lost native acknowledgement remains an unknown durable intent
                return self._receipt(record, reused=False)
            if action != "session_pin":
                record["agentId"] = agent.get("agentId", "")
            self.store.write(path, record)
            self._confirm(record)
            self.store.write(path, record)
            return self._receipt(record, reused=False)

    def receipt(self, subject: str, capability: str, action: str, request_id: str) -> dict:
        if action not in ACTION_MODELS:
            raise ManagementError("UNKNOWN_ACTION", 404)
        if action == "authorization_upgrade":
            return self._authorization_upgrades().receipt(subject, capability, request_id)
        if action == "team_run":
            return self.team_receipt(subject, capability, request_id)
        self._authorize(subject, capability, ACTION_SCOPES[action])
        key = self._request_key(subject, action, request_id)
        path = self.store.path("requests", key)
        with self.store.lock("requests", key):
            record = self.store.read(path)
            if record is None:
                raise ManagementError("REQUEST_UNAVAILABLE", 404)
            if record.get("failure"):
                raise ManagementError(record["failure"]["code"], record["failure"]["status_code"])
            if not record.get("receipt") and self._confirm(record):
                self.store.write(path, record)
            return self._receipt(record, reused=True)

    def team_receipt(self, subject: str, capability: str, request_id: str) -> dict:
        grant = self._authorize(subject, capability, "teams:read")
        self._request_key(subject, "team_run", request_id)
        return self._team_intents(grant).receipt(request_id)


def build_default_service(project_root: Path) -> ManagementService:
    from vibelution_storage import (
        instance_id_for_project,
        load_project_identity,
        resolve_project_data_home,
        resolve_project_runtime_home,
    )

    from .native import NativeAgentGateway
    root = Path(project_root).resolve()

    def identity():
        binding = {"projectId": load_project_identity(root).project_id, "instanceId": instance_id_for_project(root)}
        signature = digest([str(root).casefold(), str(resolve_project_data_home(root)).casefold(), str(resolve_project_runtime_home(root)).casefold(), binding])
        return TargetIdentity(binding, signature)

    identity()  # A missing canonical project identity cannot mint a grant.
    return ManagementService(resolve_project_runtime_home(root) / "external_management", identity=identity, native=NativeAgentGateway(root))
