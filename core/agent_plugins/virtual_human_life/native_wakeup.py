"""Companion-only adapter to a hidden native execution identity.

Reuse the life-steward pairing pattern. Never bind a second Session to the
Companion Agent: native directory synchronization would replace its chat.
"""

from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from typing import Any

from .manifest import VIRTUAL_HUMAN_TOOL_NAMES
from .self_continuity import SESSION_PATH

logger = logging.getLogger(__name__)


def _services():
    from core.web.services import agent_directory_service, session_service
    from core.web.services.virtual_human_life_service import (
        get_virtual_human_life_service,
    )

    return get_virtual_human_life_service(), agent_directory_service, session_service


def _allowed(policy: dict[str, Any]) -> set[str]:
    return set(policy.get("allowedTools") or []) - set(policy.get("blockedTools") or [])


def resolve_worker(
    agent_id: str, *, session_id: str = "", require_enabled: bool = True
) -> str:
    """Verify the persisted owner/worker/session triple, never trust a caller alias."""
    service, directory, sessions = _services()
    worker = directory.get_agent(agent_id, include_archived=not require_enabled) or {}
    metadata = worker.get("metadata") or {}
    owner_id = str(metadata.get("selfWakeForAgentId") or "")
    binding = service.binding_for(owner_id) if owner_id else None
    owner = (
        service._agent(owner_id, include_archived=not require_enabled)
        if owner_id
        else None
    )
    reference = service.store.read_json(owner_id, SESSION_PATH) if owner_id else None
    target_session = str((reference or {}).get("sessionId") or "")
    state = (
        sessions.load_session_chat_state(sessions.PROJECT_ROOT, target_session)
        if target_session
        else None
    )
    state_metadata = (state or {}).get("metadata") or {}
    if not (
        owner
        and (not require_enabled or owner.get("status") == "active")
        and (
            not require_enabled
            or (
                binding
                and binding.get("enabled")
                and binding.get("autonomyLevel") == "autonomous"
            )
        )
        and (not require_enabled or worker.get("status") == "active")
        and metadata.get("virtualHumanSelfWake") is True
        and reference
        and reference.get("agentId") == owner_id
        and reference.get("runtimeAgentId") == agent_id
        and agent_id != owner_id
        and target_session
        and worker.get("directSessionId") == target_session
        and (not session_id or session_id == target_session)
        and target_session != owner.get("directSessionId")
        and metadata.get("conversationIndexKind")
        == directory.CONVERSATION_INDEX_KIND_HIDDEN
        and (state or {}).get("agent_id") == agent_id
        and state_metadata.get("source") == "virtual_human_self_wake"
        and state_metadata.get("externalTaskId") == owner_id
    ):
        raise ValueError("Autonomous native worker pair identity is not verified.")
    return owner_id


def ensure_session(owner_id: str) -> str:
    service, directory, sessions = _services()
    with service._lock_for(owner_id):
        service.self_continuity._enabled(owner_id)
        owner = service._agent(owner_id, include_archived=False) or {}
        reference = service.store.read_json(owner_id, SESSION_PATH) or {}
        runtime_id = str(reference.get("runtimeAgentId") or "")
        session_id = str(reference.get("sessionId") or "")
        if reference and (
            reference.get("agentId") != owner_id or not runtime_id or not session_id
        ):
            raise ValueError("Autonomous native worker reference is incomplete.")
        if not reference:
            created = sessions.create_chat_session(
                title=f"{owner.get('displayName') or '虚拟人'}的自主行动",
                llm_bindings=deepcopy(owner.get("llmBindings") or {}),
                created_by="virtual_human_self_wake",
                conversation_index_kind=directory.CONVERSATION_INDEX_KIND_HIDDEN,
                session_metadata={
                    "source": "virtual_human_self_wake",
                    "externalTaskId": owner_id,
                },
                lightweight=True,
                activate=False,
                idempotency_key=f"companion-self-wake:{owner_id}",
            )
            runtime_id, session_id = (
                str(created.get("agentId") or ""),
                str(created.get("id") or ""),
            )
            if not runtime_id or runtime_id == owner_id or not session_id:
                raise ValueError(
                    "Autonomous native worker creation returned an invalid identity."
                )
        # Validate the native pair before updating any identity, including an
        # idempotent replay after interruption between create and reference save.
        worker = directory.get_agent(runtime_id, include_archived=False) or {}
        state = (
            sessions.load_session_chat_state(sessions.PROJECT_ROOT, session_id) or {}
        )
        state_metadata = state.get("metadata") or {}
        if (
            worker.get("status") != "active"
            or worker.get("directSessionId") != session_id
            or state.get("agent_id") != runtime_id
            or session_id == owner.get("directSessionId")
            or state_metadata.get("source") != "virtual_human_self_wake"
            or state_metadata.get("externalTaskId") != owner_id
        ):
            raise ValueError("Autonomous native worker creation identity conflicts.")
        if reference:
            resolve_worker(runtime_id, session_id=session_id)
        wake = service.self_continuity.snapshot(owner_id)
        capabilities = set(VIRTUAL_HUMAN_TOOL_NAMES) | set(
            wake.get("requiredToolNames") or []
        )
        capabilities.discard("virtual_human_dialogue_decision_v2_tool")
        # Preserve scope, access and call-budget restrictions; shrink tool names
        # to current owner permission intersected with this planned action.
        policy = deepcopy(owner.get("toolPolicy") or {})
        policy["allowedTools"] = sorted(_allowed(policy) & capabilities)
        expected = {
            "roleKey": "virtual_human_self_wake",
            "displayName": str(owner.get("displayName") or "虚拟人"),
            "llmBindings": deepcopy(owner.get("llmBindings") or {}),
            "personaProfile": deepcopy(owner.get("personaProfile") or {}),
            "promptTemplateId": str(
                owner.get("promptTemplateId") or "prompt-chat-default"
            ),
            "toolPolicy": policy,
        }
        metadata = {
            "agentMode": "chat",
            "configSurface": "companion_self_wake",
            "conversationIndexKind": directory.CONVERSATION_INDEX_KIND_HIDDEN,
            "conversationIndexVisibility": directory.CONVERSATION_INDEX_VISIBILITY_HIDDEN,
            "showInSessionIndex": False,
            "virtualHumanSelfWake": True,
            "selfWakeForAgentId": owner_id,
        }
        if any(worker.get(key) != value for key, value in expected.items()) or any(
            (worker.get("metadata") or {}).get(key) != value
            for key, value in metadata.items()
        ):
            directory.update_agent_instance(
                runtime_id,
                display_name=expected["displayName"],
                llm_bindings=expected["llmBindings"],
                persona_profile=expected["personaProfile"],
                prompt_template_id=expected["promptTemplateId"],
                primary_mode="chat",
                role_key=expected["roleKey"],
                permission_preset=owner.get("permissionPreset") or None,
                tool_policy=policy,
                metadata=metadata,
                preserve_generated_display_name=True,
            )
        service.store.write_json(
            owner_id,
            SESSION_PATH,
            {
                "agentId": owner_id,
                "runtimeAgentId": runtime_id,
                "sessionId": session_id,
                "ownerToolPolicyStamp": _policy_stamp(owner),
            },
        )
        resolve_worker(runtime_id, session_id=session_id)
        return session_id


def _policy_stamp(owner: dict[str, Any]) -> str:
    # Administrative version/id changes are not authority changes.
    policy = owner.get("toolPolicy") or {}
    effective = {
        key: value
        for key, value in policy.items()
        if key not in {"policyId", "id", "policyVersion"}
    }
    authority = {"toolPolicy": effective, "permissionPreset": owner.get("permissionPreset")}
    return hashlib.sha256(json.dumps(authority, sort_keys=True).encode()).hexdigest()


def execution_denial(runtime: dict[str, Any], tool_name: str) -> str | None:
    """A running autonomous Turn cannot retain revoked owner permissions."""
    metadata = (runtime.get("agent") or {}).get("metadata") or {}
    if metadata.get("virtualHumanSelfWake") is not True:
        return None
    try:
        runtime_id = str(runtime.get("agentId") or "")
        session_id = str(runtime.get("sessionId") or "")
        owner_id = resolve_worker(runtime_id, session_id=session_id)
        service, _directory, _sessions = _services()
        if (
            service.runtime_acceptance_provider is not None
            and not service.runtime_acceptance_provider()
        ):
            return "自主行动服务正在停止。"
        reference = service.store.read_json(owner_id, SESSION_PATH) or {}
        owner = service._agent(owner_id, include_archived=False) or {}
        if reference.get("ownerToolPolicyStamp") != _policy_stamp(owner):
            return "人物授权已变化，请结束当前自主回合并重新规划。"
        if tool_name not in authorized_tool_names(
            runtime_id, [tool_name], session_id=session_id
        ):
            return "该工具不在人物当前授权与本次自主行动的交集中。"
    except Exception:  # noqa: BLE001 - unresolved autonomous identity denies execution
        return "自主行动身份或当前授权无法验证。"
    return None


def archive_pair(owner_id: str, *, purging: bool) -> dict[str, Any] | None:
    service, directory, sessions = _services()
    reference = service.store.read_json(owner_id, SESSION_PATH) or {}
    runtime_id = str(reference.get("runtimeAgentId") or "")
    if not runtime_id:
        return None
    if resolve_worker(runtime_id, require_enabled=False) != owner_id:
        raise ValueError("Autonomous archive owner conflicts.")
    if purging and sessions._is_session_running(str(reference["sessionId"])):
        raise ValueError(
            "Autonomous native Turn is stopping; retry purge after it closes."
        )
    worker = directory.get_agent(runtime_id, include_archived=True) or {}
    if purging:
        directory.ensure_agent_purge_workspace_deletable(worker)
    token = {**reference, "previousStatus": str(worker.get("status") or "active")}
    if worker.get("status") != "archived":
        directory.archive_agent_instance(runtime_id, repair_mode_bindings=False)
    return token


def rollback_pair(token: dict[str, Any] | None) -> None:
    if not token:
        return
    _service, directory, _sessions = _services()
    runtime_id = str(token["runtimeAgentId"])
    if resolve_worker(runtime_id, require_enabled=False) != token["agentId"]:
        raise ValueError("Autonomous rollback identity conflicts.")
    directory.update_agent_instance(runtime_id, status=str(token["previousStatus"]))


def purge_pair(token: dict[str, Any] | None) -> None:
    if not token:
        return
    _service, directory, sessions = _services()
    runtime_id, session_id = str(token["runtimeAgentId"]), str(token["sessionId"])
    worker = directory.get_agent(runtime_id, include_archived=True)
    if worker is None:
        return
    metadata = worker.get("metadata") or {}
    state = sessions.load_session_chat_state(sessions.PROJECT_ROOT, session_id)
    if (
        worker.get("status") != "archived"
        or metadata.get("virtualHumanSelfWake") is not True
        or metadata.get("selfWakeForAgentId") != token["agentId"]
        or worker.get("directSessionId") != session_id
        or (
            state is not None
            and (
                (state.get("agent_id") != runtime_id)
                or (state.get("metadata") or {}).get("externalTaskId")
                != token["agentId"]
            )
        )
    ):
        raise ValueError("Autonomous purge identity conflicts.")
    if state is not None:
        # Owner deletion has committed. Retain an archived native cleanup
        # marker until both resources are gone; I/O failures survive restart.
        directory.update_agent_instance(
            runtime_id,
            metadata={
                "selfWakePurgePending": {
                    "agentId": token["agentId"],
                    "runtimeAgentId": runtime_id,
                    "sessionId": session_id,
                }
            },
        )
        sessions.delete_chat_session_lightweight(session_id)
    directory.purge_archived_agent_instance(runtime_id)


def recover_pending_purges() -> None:
    _service, directory, _sessions = _services()
    pending = [
        (agent.get("metadata") or {}).get("selfWakePurgePending")
        for agent in directory.load_state().get("agents", [])
        if agent.get("status") == "archived"
        and (agent.get("metadata") or {}).get("virtualHumanSelfWake") is True
        and isinstance((agent.get("metadata") or {}).get("selfWakePurgePending"), dict)
    ]
    for token in pending[:32]:
        try:
            purge_pair(token)
        except Exception as exc:  # noqa: BLE001 - an archived native cleanup receipt remains for retry
            logger.warning("Autonomous pair cleanup deferred (%s).", type(exc).__name__)


def authorized_tool_names(
    runtime_id: str, names: list[str], *, session_id: str
) -> list[str]:
    owner_id = resolve_worker(runtime_id, session_id=session_id)
    service, directory, _sessions = _services()
    owner = service._agent(owner_id, include_archived=False) or {}
    worker = directory.get_agent(runtime_id, include_archived=False) or {}
    permitted = _allowed(owner.get("toolPolicy") or {}) & _allowed(
        worker.get("toolPolicy") or {}
    )
    return [name for name in names if name in permitted]


def context_owner(context: dict[str, Any]) -> str:
    runtime_id = str(context.get("agent_id") or "")
    metadata = context.get("proactive_plugin") or {}
    trigger = metadata.get("trigger") or {}
    if trigger.get("deliveryKind") != "self_wake":
        return runtime_id
    return resolve_worker(runtime_id, session_id=str(context.get("session_id") or ""))


def cancel_turn(owner_id: str, session_id: str, turn_id: str) -> None:
    service, _directory, sessions = _services()
    reference = service.store.read_json(owner_id, SESSION_PATH) or {}
    if reference.get("sessionId") != session_id:
        raise ValueError("Autonomous work cancellation identity conflicts.")
    if (
        resolve_worker(
            str(reference.get("runtimeAgentId") or ""),
            session_id=session_id,
            require_enabled=False,
        )
        != owner_id
    ):
        raise ValueError("Autonomous work cancellation owner conflicts.")
    if sessions._is_session_turn_current(session_id, turn_id):
        sessions.request_stop_session_turn(
            session_id, expected_turn_id=turn_id, fast_ack=True
        )
