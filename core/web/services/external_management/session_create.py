"""Authorize the existing Agent and confirm the native Session creation record."""
from __future__ import annotations

import hashlib

from .archive_state import ArchiveState
from .service import ManagementError
from .workspace import _public_session, _validated_session_snapshot

_SOURCE = "launcher_assistant"


def _idempotency_key(marker):
    return "launcher-assistant-session-create:" + marker["requestKey"]


def _require_directory_pin(project_root, directory_runtime):
    try:
        pin = directory_runtime.pin_open_directory_store(project_root)
    except ValueError:
        raise ManagementError("TARGET_BINDING_CHANGED", 409) from None
    if pin is None:
        raise ManagementError("SESSION_DIRECTORY_UNAVAILABLE", 503)
    return pin


def create_session(native, parameters, marker):
    from core.web.services import session_service
    from core.web.services.local_assistant.eligibility import local_assistant_eligibility
    from core.web.services.session import directory_runtime
    from core.web.services.team import team_store

    directory = native._owners()
    agent_id = parameters["agent_id"]
    with session_service.session_agent_lifecycle_transaction():
        pin = _require_directory_pin(native.project_root, directory_runtime)
        # Use a nonblocking roster lock to preserve native lock ordering when
        # another Team operation already owns it. Keep membership stable
        # between validation and the Session admission.
        acquired = team_store._try_acquire_team_lock()
        if not acquired:
            raise ManagementError("AGENT_BUSY", 409)
        try:
            try:
                state = ArchiveState(native.project_root, directory, pin_workspace=True)
                with directory._STATE_LOCK:
                    agent = state.agent(agent_id)
                if agent is None or agent.get("status") != "active":
                    raise ManagementError("AGENT_UNAVAILABLE", 404)
                classification = directory.agent_conversation_index_classification(agent)
                role = directory._normalize_role_key(agent.get("roleKey") or directory._infer_agent_role_key(agent))
                # Roster validation belongs to the stricter native identity check below.
                eligibility = local_assistant_eligibility({**agent, "roleKey": role}, active_team_lookup=lambda _: None)
                if (native._ordinary_agent_identity_reason(state, agent, directory) is not None
                        or classification["kind"] != directory.CONVERSATION_INDEX_KIND_PERSONAL_AGENT
                        or classification["errors"] or not eligibility.eligible
                        or any(key in agent and agent[key] != agent_id for key in ("id", "agent_id"))):
                    raise ManagementError("AGENT_UNAVAILABLE", 404)
                state.verify_workspace()
            except (OSError, ValueError, TypeError, KeyError):
                raise ManagementError("AGENT_DIRECTORY_UNAVAILABLE", 503) from None
            if not directory_runtime.directory_store_pin_is_current(pin):
                raise ManagementError("TARGET_BINDING_CHANGED", 409)
            session_service.create_chat_session(agent_id=agent_id, title=parameters["title"],
                created_by=_SOURCE, conversation_index_kind=directory.CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
                activate=False, lightweight=True, idempotency_key=_idempotency_key(marker),
                session_metadata={"source": _SOURCE})
        finally:
            team_store._release_team_lock_if_acquired(acquired)


def confirm_session_creation(native, parameters, marker):
    from core.web.services.session import conversation_index, directory_runtime

    directory = native._owners()
    pin = _require_directory_pin(native.project_root, directory_runtime)
    key_hash = hashlib.sha256(_idempotency_key(marker).encode("ascii")).hexdigest()
    proof = conversation_index._read_session_create_idempotency_record(
        conversation_index._session_create_idempotency_path(native.project_root, key_hash))
    if (proof is None or proof["state"] != "committed" or proof["agentId"] != parameters["agent_id"]
            or proof["requestDigest"] != conversation_index._session_create_request_digest(**parameters)):
        return None
    session_id = proof["sessionId"]
    _, row, runtime, agent, store = _validated_session_snapshot(
        native.project_root, directory, session_id, strict_shape=True, return_agent=True,
        _return_store=True, allow_roleless_agent=True)
    if (store is not pin.store or not directory_runtime.directory_store_pin_is_current(pin)
            or row["agentId"] != parameters["agent_id"] or row["title"] != parameters["title"]
            or row.get("sessionRole") != "workspace" or row.get("conversationIndexKind") != "personal_agent"
            or row.get("conversationIndexVisibility") != "user_visible"
            or runtime["source"] != _SOURCE or session_id == agent.get("directSessionId")):
        return None
    return _public_session(row, runtime)
