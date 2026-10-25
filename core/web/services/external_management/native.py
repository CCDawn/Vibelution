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

    def read_sessions(self, query):
        from .workspace import read_sessions
        return read_sessions(self.project_root, self._owners(), query)

    def read_session_config(self, session_id: str):
        from .workspace import read_session_config
        return read_session_config(self.project_root, self._owners(), session_id)

    def read_session_config_comparison(self, session_id: str):
        from .workspace import read_session_config_comparison
        return read_session_config_comparison(self.project_root, self._owners(), session_id)

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
