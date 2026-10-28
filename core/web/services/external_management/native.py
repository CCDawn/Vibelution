"""Native catalog reuse in one target backend; never an execution-subject adapter."""
from __future__ import annotations

from pathlib import Path


class NativeAgentGateway:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()

    def _owners(self):
        from core.web.services import agent_directory_service as directory
        from core.web.services import session_service as sessions

        from .service import ManagementError
        if any(Path(owner.PROJECT_ROOT).resolve() != self.project_root for owner in (directory, sessions)):
            raise ManagementError("TARGET_BINDING_CHANGED", 409)
        if Path(directory._active_project_root()).resolve() != self.project_root:
            raise ManagementError("TARGET_BINDING_CHANGED", 409)
        return directory

    def read(self, agent_id: str):
        return self._owners().get_agent(agent_id, include_archived=True)

    def read_archive_state(self, agent_id: str):
        from .archive_state import ArchiveState
        directory = self._owners()
        with directory._STATE_LOCK:
            raw = ArchiveState(self.project_root, directory).agent(agent_id)
            if raw is None:
                return None
            metadata = raw.get("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError("Invalid Agent metadata")
            # Receipt fields are persisted facts, not a hydrated UI/default logo.
            return {**raw, "avatarImagePath": directory._agent_avatar_path_from_metadata(metadata)}

    def avatar_options(self):
        directory = self._owners()
        from config.public_config import read_existing_config_snapshot
        from core.infrastructure.developer_sandbox import existing_sandboxed_workspace_path
        from core.web.services.agent_directory.mutations import agent_avatar_options_snapshot
        from .service import ManagementError
        try:
            config_path = Path(directory.CONFIG_PATH).expanduser().resolve()
            config = read_existing_config_snapshot(config_path)
            legacy = existing_sandboxed_workspace_path(self.project_root, "avatars", public_config=config)
            return agent_avatar_options_snapshot((
                ("custom", config_path.parent / directory.AGENT_AVATAR_CONFIG_DIR_NAME / directory.AGENT_AVATAR_CONFIG_AGENT_DIR_NAME),
                ("bundled", self.project_root / "assets" / directory.AGENT_AVATAR_ASSET_DIR_NAME),
                ("legacy", legacy),
            ))
        except (OSError, ValueError, TypeError):
            raise ManagementError("AVATAR_LIBRARY_UNAVAILABLE", 503) from None

    def read_session(self, session_id: str):
        from .workspace import read_session
        return read_session(self.project_root, self._owners(), session_id)

    def pin_session(self, parameters: dict):
        from .workspace import pin_session
        return pin_session(self.project_root, self._owners(), parameters)

    def read_sessions(self, query):
        from .workspace import read_sessions
        return read_sessions(self.project_root, self._owners(), query)

    def read_active_tasks(self, query):
        from core.assistant_runtime.migration_io import read_stable_file, strict_json
        from core.web.services import runtime_task_registry as registry
        from vibelution_storage import resolve_project_runtime_home
        from .service import ManagementError

        self._owners()
        if Path(registry.PROJECT_ROOT).resolve() != self.project_root:
            raise ManagementError("TARGET_BINDING_CHANGED", 409)
        store = registry.store_for(resolve_project_runtime_home(self.project_root) / registry.STORE_DIR_NAME)
        try:
            def read_index():
                return read_stable_file(store.index_path, 1_000_000).raw

            before = read_index()
            index = strict_json(before)
            ids = index.get("activeTaskIds") if isinstance(index, dict) else None
            if (not isinstance(index, dict) or set(index) != {"schemaVersion", "activeTaskIds"}
                    or type(index.get("schemaVersion")) is not int or index.get("schemaVersion") != registry.INDEX_SCHEMA_VERSION
                    or not isinstance(ids, list) or len(ids) > 10000
                    or any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids))):
                raise ValueError("Invalid active index")
            summaries = {"cli_agent": "CLI agent task", "child_session": "Child session task", "research_task": "Research task"}
            projected = []
            bytes_remaining = 8_000_000
            for task_id in sorted(ids):
                raw_bytes = read_stable_file(store.task_state_path(task_id), min(1_000_000, bytes_remaining)).raw
                bytes_remaining -= len(raw_bytes)
                raw = strict_json(raw_bytes)
                if not isinstance(raw, dict) or raw.get("taskId") != task_id:
                    raise ValueError("Inconsistent task snapshot")
                kind, status = raw.get("kind"), raw.get("status")
                if kind not in summaries or status not in registry.ACTIVE_STATUSES:
                    raise ValueError("Invalid task state")
                projected.append({"taskId": task_id, "kind": kind, "status": status, "summary": summaries[kind],
                                  "startedAt": raw.get("startedAt"), "updatedAt": raw.get("updatedAt")})
            from .contracts import ActiveTask
            projected = [ActiveTask.model_validate(row).model_dump() for row in projected]
            if read_index() != before:
                raise ValueError("Changed active index")
            page = projected[query.offset:query.offset + query.limit]
            end = query.offset + len(page)
            return {"source": "native-active-task-index",
                    "coverage": "active index only; may omit active tasks; total counts indexed tasks only, not all active tasks or project health",
                    "indexCompleteness": "unknown",
                    "tasks": page, "offset": query.offset, "total": len(projected),
                    "nextOffset": end if end < len(projected) else None, "untrustedContent": True}
        except (OSError, ValueError, TypeError):
            raise ManagementError("TASK_INDEX_UNAVAILABLE", 503) from None

    def read_teams(self, query):
        from .workspace_queries import read_teams
        return read_teams(self.project_root, self._owners(), query)

    def read_team(self, team_id, query):
        from .workspace_queries import read_team
        return read_team(self.project_root, self._owners(), team_id, query)

    def read_rooms(self, query):
        from .workspace_queries import read_rooms
        return read_rooms(self.project_root, self._owners(), query)

    def read_room(self, room_id):
        from .workspace_queries import read_room
        return read_room(self.project_root, self._owners(), room_id)

    def read_session_config(self, session_id: str):
        from .workspace import read_session_config
        return read_session_config(self.project_root, self._owners(), session_id)

    def read_session_config_comparison(self, session_id: str):
        from .workspace import read_session_config_comparison
        return read_session_config_comparison(self.project_root, self._owners(), session_id)

    def read_session_parameters(self, session_id: str):
        from .session_parameters import read_session_parameters
        return read_session_parameters(self.project_root, self._owners(), session_id)

    def legacy_observation_snapshot(self, binding, source_agent_id, legacy_message_ids, expected_registry_sha256=None):
        from .legacy_native import LegacyNativeGateway
        # This source is private PA migration evidence, not an ordinary Session
        # read. Do not call hydrated Agent/Session getters or provisioning code.
        from core.web.services import agent_directory_service as directory
        from .service import ManagementError
        if (Path(directory.PROJECT_ROOT).resolve() != self.project_root
                or Path(directory._active_project_root()).resolve() != self.project_root):
            raise ManagementError("TARGET_BINDING_CHANGED", 409)
        return LegacyNativeGateway(self.project_root, directory).snapshot(
            binding, source_agent_id, legacy_message_ids, expected_registry_sha256)

    def find_created(self, request_key: str):
        directory = self._owners()
        # This is a recovery read of canonical native metadata, never a new creation.
        with directory._STATE_LOCK:
            state = directory.load_state()
            rows = state.get("agents", [])
            if not isinstance(rows, list) or len(rows) > 100_000:
                raise ValueError("Native recovery inventory unavailable")
            ids = [row["agentId"] for row in rows if isinstance(row, dict) and row.get("agentId")
                   and (row.get("metadata", {}).get("externalManagementCreation") or {}).get("requestKey") == request_key]
            return [directory.get_agent(agent_id, include_archived=True) for agent_id in ids]

    def _control_store(self):
        from core.web.services.session import directory_runtime
        self._owners()
        store = directory_runtime.get_open_directory_store()
        store_root = directory_runtime.directory_store_project_root()
        if store is None or store_root is None or Path(store_root).resolve() != self.project_root:
            return None
        return store

    def current_compiled(self, agent_id: str):
        store = self._control_store()
        snapshot = store.repository.get_current_agent_config(agent_id) if store is not None else None
        return snapshot.get("config") if snapshot else None

    def compiled(self, agent_id: str, session_id: str):
        store = self._control_store()
        if store is None:
            return None
        snapshot = store.repository.get_current_agent_config(agent_id)
        session = store.repository.get_session(session_id, include_archived=True)
        if (not snapshot or not session or session.get("agentId") != agent_id
            or session.get("agentConfigRevisionId") != snapshot.get("configRevisionId")):
            return None
        return snapshot.get("config")

    def _model(self, model_id: str):
        from config.public_config import list_llm_model_options, load_public_config

        from .service import ManagementError
        public = load_public_config()
        provider = (public.get("llm", {}).get("providers") or {}).get(model_id.split("/", 1)[0], {})
        if provider.get("enabled", True) is False or not any(row.get("model_id") == model_id for row in list_llm_model_options(public)):
            raise ManagementError("MODEL_UNAVAILABLE", 422)

    def create(self, parameters: dict, marker: dict):
        from core.web.services.agent_operation_service import (
            create_configured_agent_with_session,
        )
        self._owners()
        self._model(parameters["model_id"])
        return create_configured_agent_with_session(display_name=parameters["display_name"],
            primary_mode="chat", role_key="assistant_worker", prompt_template_id="prompt-chat-default",
            llm_bindings={"dialogue": {"modelId": parameters["model_id"]}},
            tool_policy={"allowedTools": [], "preferredTools": [], "readScopes": [], "writeScopes": [],
                "networkAccess": "none", "mutationAccess": "none", "maxCallsPerTurn": 0},
            task_profile={"mission": parameters["mission"]}, permission_preset="request_approval",
            delegation_policy={"allowSubagents": False, "allowWakeMessages": False},
            metadata={"externalManagementCreation": marker}, source="external_operator_management",
            session_idempotency_key=marker["requestKey"],
            session_metadata={"source": "external_operator_management", "externalTaskId": marker["requestKey"]})

    def _editable(self, agent: dict | None):
        from .service import ManagementError
        if not agent or agent.get("status") != "active":
            raise ManagementError("AGENT_UNAVAILABLE", 404)
        if agent.get("roleKey") == "personal_assistant" or (agent.get("metadata") or {}).get("personalAssistantProfile"):
            raise ManagementError("AGENT_PROTECTED", 403)

    def update(self, parameters: dict, marker: dict):
        from core.web.services.agent_config_authority import (
            canonical_agent_config_payload,
        )
        from core.web.services.agent_operation_service import (
            update_agent_from_catalog_request,
        )

        from .service import ManagementError
        directory = self._owners()
        changes = parameters["updates"]
        if "llmBindings" in changes:
            self._model(changes["llmBindings"]["dialogue"]["modelId"])
        with directory.agent_session_lifecycle_transaction(), directory._STATE_LOCK:
            current = directory.get_agent(parameters["agent_id"], include_archived=True)
            self._editable(current)
            if int(current.get("configRevision") or 0) != parameters["expected_config_revision"]:
                raise ManagementError("STATE_CONFLICT", 409)
            store = self._control_store()
            compiled = store.repository.get_current_agent_config(parameters["agent_id"]) if store is not None else None
            if not compiled:
                raise ManagementError("CONFIG_SNAPSHOT_UNAVAILABLE", 409)
            changes = dict(changes)
            for field in ("personaProfile", "taskProfile"):
                if field in changes:
                    if directory._is_profileless_session_agent(current):
                        raise ManagementError("PROFILE_UNAVAILABLE", 422)
                    changes[field] = {**current.get(field, {}), **changes[field]}
            changes["metadata"] = {**current.get("metadata", {}), "externalManagementMutation": marker}
            updated = update_agent_from_catalog_request(parameters["agent_id"], updates=changes,
                expected_config_revision=parameters["expected_config_revision"], source="external_operator_management")
            raw = directory._find_agent(directory.load_state(), parameters["agent_id"])
            # Reuse the native canonical payload and existing SQLite writer CAS.
            # This advances only Agent current; accepted Session revision pins
            # remain untouched. A conflict after the registry write is unknown,
            # never permission to overwrite the new current snapshot or retry.
            store.repository.compare_and_swap_agent_config(agent_id=parameters["agent_id"],
                expected_config_revision_id=compiled["configRevisionId"], display_name=raw["displayName"],
                kind=raw["kind"], status=raw["status"], config=canonical_agent_config_payload(raw),
                source="external_operator_management").result(timeout=3)
            return updated

    def avatar(self, parameters: dict, marker: dict):
        from .service import ManagementError
        directory = self._owners()
        with directory.agent_session_lifecycle_transaction(), directory._STATE_LOCK:
            current = directory.get_agent(parameters["agent_id"], include_archived=True)
            self._editable(current)
            if current.get("updatedAt") != parameters["expected_updated_at"]:
                raise ManagementError("STATE_CONFLICT", 409)
            # The same native RLock spans CAS, native library validation and both writes.
            agent = directory.update_agent_avatar(parameters["agent_id"], avatar_image_path=parameters["avatar_image_path"],
                                                   reset_to_default=parameters["reset_to_default"])
            return directory.update_agent_instance(agent["agentId"],
                metadata={**agent.get("metadata", {}), "externalManagementMutation": marker},
                expected_updated_at=agent["updatedAt"])

    def archive(self, parameters: dict, marker: dict):
        from core.web.routes.agents import _archive_agent_with_session_lifecycle
        from core.web.services import session_service as sessions
        from .service import ManagementError
        from .archive_state import ArchiveState

        directory = self._owners()
        agent_id = parameters["agent_id"]
        try:
            # The canonical transaction snapshots Sessions through legacy path
            # readers. Reject missing authority before entering that owner;
            # reload under its lock for identity and CAS before any effect.
            if ArchiveState(self.project_root, directory).agent(agent_id) is None:
                raise ManagementError("AGENT_UNAVAILABLE", 404)
            # Admission-first canonical lock excludes session submits and all
            # Agent config writers through CAS and the full owner transaction.
            with sessions.agent_archive_transaction(agent_id):
                with directory._STATE_LOCK:
                    state = ArchiveState(self.project_root, directory)
                    raw = state.agent(agent_id)
                    if not isinstance(raw, dict) or raw.get("status") != "active":
                        raise ManagementError("AGENT_UNAVAILABLE", 404)
                    try:
                        # Agent ownership is independent of Session index
                        # classification: configured Agents need not have a
                        # conversationIndexKind. Reuse the ordinary identity
                        # boundaries without inventing Session visibility.
                        metadata = raw.get("metadata", {})
                        role = raw.get("roleKey")
                        creation = (metadata.get("creationSpec") or {}) if isinstance(metadata, dict) else None
                        if (raw.get("kind") != directory.DEFAULT_AGENT_KIND or not isinstance(role, str) or not role
                            or role == "personal_assistant" or role.startswith(("challenge_cup_", "knowledge_expansion_"))
                            or not isinstance(metadata, dict) or not isinstance(creation, dict)
                            or any(metadata.get(key) for key in ("personalAssistantProfile", "protected", "systemRole", "researchOrgRole",
                                "teamId", "challengeCupTeamId", "knowledgeExpansionTeamId", "virtualHumanCompanion",
                                "virtualHumanSelfWake", "lifeStewardForAgentId"))
                            or (raw.get("createdBy") or creation.get("source")) in
                                directory.TEAM_PRIVATE_DIRECT_SESSION_CREATED_BY | directory.INTERNAL_RECOVERY_DIRECT_SESSION_CREATED_BY
                            or directory._agent_archive_protected(raw)):
                            raise ValueError("Private Agent")
                        for record in (raw, metadata):
                            for field, allowed in (("conversationIndexKind", {"", "personal_agent"}),
                                                   ("conversation_index_kind", {"", "personal_agent"}),
                                                   ("conversationIndexVisibility", {"", "user_visible"}),
                                                   ("conversation_index_visibility", {"", "user_visible"})):
                                if field in record and (not isinstance(record[field], str) or record[field] not in allowed):
                                    raise ValueError("Private or damaged Agent classification")
                            for field in ("hiddenFromIndex", "hidden_from_index"):
                                if field in record and record[field] is not False:
                                    raise ValueError("Hidden or damaged Agent marker")
                        if agent_id in state.team_member_ids():
                            raise ValueError("Private team Agent")
                        binding = state.binding(agent_id)
                        if binding is not None and (binding.get("enabled") is not False or binding.get("agentId") not in (None, agent_id)):
                            raise ValueError("Companion binding")
                    except (ManagementError, OSError, ValueError, TypeError, KeyError):
                        raise ManagementError("AGENT_PROTECTED", 403) from None
                    revision = raw.get("configRevision")
                    if type(revision) is not int or revision < 0 or revision != parameters["expected_config_revision"]:
                        raise ManagementError("STATE_CONFLICT", 409)
                # No metadata write before CAS or archive: the durable intent
                # already owns idempotency; only the canonical owner mutates.
                agent, _summary = _archive_agent_with_session_lifecycle(agent_id,
                    source="external_operator_management", timings={},
                    archive_write=lambda: directory.archive_agent_instance(agent_id, repair_mode_bindings=False))
                return agent
        except sessions.SessionBusyError:
            raise ManagementError("AGENT_BUSY", 409) from None
        except directory.AgentNotFoundError:
            raise ManagementError("AGENT_UNAVAILABLE", 404) from None
        except (OSError, ValueError, TypeError, KeyError):
            raise ManagementError("AGENT_UNAVAILABLE", 503) from None
