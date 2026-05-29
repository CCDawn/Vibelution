"""AgentInstance registry API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.orchestration.context_engine import list_agent_runs_for_agent
from core.web.services import agent_directory_service, session_service
from core.web.services.runtime_scene_service import list_runtime_scene_evidence_for_agent
from core.web.services.agent_config_workspace_service import get_agent_config_workspace
from core.web.services.agent_directory_service import (
    AgentDirectoryError,
    AgentMessageNotFoundError,
    AgentNotFoundError,
    archive_agent_instance,
    consume_agent_inbox_message,
    ensure_agent_archive_allowed,
    ensure_agent_purge_allowed,
    get_agent,
    list_agent_inbox_messages_for_agent,
    list_agents,
    purge_archived_agent_instance,
    update_agent_instance,
    write_agent_inbox_message,
)
from core.web.services.agent_mode_binding_service import (
    AgentModeBindingError,
    get_mode_bindings_payload,
    remove_agent_from_mode_bindings,
    update_agent_mode_membership,
    update_mode_binding,
)
from core.web.services.chat_room_service import (
    ChatRoomBusyError,
    ChatRoomValidationError,
    remove_agent_from_chat_rooms,
    update_agent_chat_room_membership,
)
from core.web.services.prompt_template_service import (
    PromptTemplateError,
    get_prompt_template,
    list_prompt_templates,
    reset_prompt_template,
    update_prompt_template,
)
from core.web.services.self_evolution_control_service import (
    SELF_EVOLUTION_AGENT_ROLES,
    ensure_self_evolution_agent_instances,
)
from core.web.services.supervised_agent_service import (
    SUPERVISED_AGENT_ROLES,
    ensure_supervised_agent_instances,
)


router = APIRouter(tags=["agents"])


class AgentCreatePayload(BaseModel):
    displayName: str = ""
    templateId: str = ""
    profileId: str = ""
    primaryMode: str = ""
    roleKey: str = ""
    promptTemplateId: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentUpdatePayload(BaseModel):
    displayName: str | None = None
    templateId: str | None = None
    profileId: str | None = None
    primaryMode: str | None = None
    roleKey: str | None = None
    promptTemplateId: str | None = None
    toolPolicyId: str | None = None
    memoryPolicyId: str | None = None
    toolPolicy: dict[str, Any] | None = None
    memoryPolicy: dict[str, Any] | None = None
    delegationPolicy: dict[str, Any] | None = None
    supervisionPolicy: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    status: str | None = None


class AgentMessagePayload(BaseModel):
    content: str = ""
    sourceAgentId: str = ""
    sourceSessionId: str = ""
    sourceRoomId: str = ""
    sourceRoundId: str = ""
    threadId: str = ""
    kind: str = ""
    summary: str = ""
    promptEligible: bool = True
    createdBy: str = "agent"
    wakeTarget: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentMessageConsumePayload(BaseModel):
    consumedBySessionId: str = ""
    consumedByTurnId: str = ""


class PromptTemplateUpdatePayload(BaseModel):
    name: str | None = None
    category: str | None = None
    sourcePath: str | None = None
    content: str | None = None
    metadata: dict[str, Any] | None = None
    status: str | None = None


class ModeBindingUpdatePayload(BaseModel):
    defaultAgentId: str | None = None
    availableAgentIds: list[str] | None = None
    pool: list[str] | None = None
    flowBindings: dict[str, str] | None = None
    slots: dict[str, str] | None = None


class ModeBindingSlotUpdatePayload(BaseModel):
    agentId: str = ""


class ModeBindingPoolUpdatePayload(BaseModel):
    agentIds: list[str] = Field(default_factory=list)


class AgentModeMembershipUpdatePayload(BaseModel):
    chatDefault: bool | None = None
    chatAvailable: bool | None = None
    researchPool: bool | None = None
    supervisedSlot: str | None = None
    selfEvolutionSlot: str | None = None


class AgentChatRoomMembershipUpdatePayload(BaseModel):
    roomIds: list[str] = Field(default_factory=list)


def _ensure_config_agent_instances() -> None:
    if _config_agent_instances_present():
        return
    ensure_supervised_agent_instances()
    ensure_self_evolution_agent_instances()


def _config_agent_instances_present() -> bool:
    state = agent_directory_service.load_state()
    agents = [item for item in state.get("agents") or [] if isinstance(item, dict)]
    supervised_roles = {role.role for role in SUPERVISED_AGENT_ROLES}
    self_roles = {str(role.get("role") or "").strip() for role in SELF_EVOLUTION_AGENT_ROLES}
    present_supervised: set[str] = set()
    present_self: set[str] = set()
    for agent in agents:
        if str(agent.get("status") or "active").strip() == "archived":
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        mode = str(agent.get("primaryMode") or "").strip()
        role_key = str(agent.get("roleKey") or "").strip()
        supervised_role = str(metadata.get("supervisedRole") or "").strip()
        if mode == "supervised_evolution" and role_key in supervised_roles:
            supervised_role = supervised_role or role_key
        if supervised_role in supervised_roles:
            present_supervised.add(supervised_role)
        self_role = str(metadata.get("selfEvolutionRole") or "").strip()
        if mode == "self_evolution" and role_key in self_roles:
            self_role = self_role or role_key
        if self_role in self_roles:
            present_self.add(self_role)
    return supervised_roles.issubset(present_supervised) and self_roles.issubset(present_self)


@router.get("/agents")
def agent_list(includeArchived: bool = False) -> list[dict]:
    _ensure_config_agent_instances()
    return list_agents(include_archived=includeArchived)


@router.get("/agents/config-workspace")
def agent_config_workspace() -> dict:
    _ensure_config_agent_instances()
    return get_agent_config_workspace()


@router.post("/agents", status_code=status.HTTP_201_CREATED)
def agent_create(payload: AgentCreatePayload) -> dict:
    try:
        profile_id = payload.profileId or payload.templateId or "primary"
        session = session_service.create_chat_session(
            title=payload.displayName,
            profile_id=profile_id,
            created_by="api_agents",
        )
        agent_id = str(session.get("agentId") or "").strip()
        agent = get_agent(agent_id) if agent_id else None
        if not agent:
            raise AgentDirectoryError("Agent was not created for the direct session.")
        if payload.metadata:
            agent = update_agent_instance(agent_id, metadata=payload.metadata)
        if payload.templateId or payload.primaryMode or payload.roleKey or payload.promptTemplateId:
            agent = update_agent_instance(
                agent_id,
                template_id=payload.templateId or None,
                primary_mode=payload.primaryMode or None,
                role_key=payload.roleKey or None,
                prompt_template_id=payload.promptTemplateId or None,
            )
        return agent
    except session_service.SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/agents/{agent_id}")
def agent_detail(agent_id: str) -> dict:
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("/agents/{agent_id}/runs")
def agent_run_list(agent_id: str, limit: int = 20) -> dict:
    if not get_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return list_agent_runs_for_agent(agent_id, limit=limit)


@router.get("/agents/{agent_id}/runtime-evidence")
def agent_runtime_evidence(agent_id: str, sessionId: str = "", runId: str = "", limit: int = 5) -> dict:
    if not get_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return list_runtime_scene_evidence_for_agent(agent_id, session_id=sessionId, run_id=runId, limit=limit)


@router.get("/agents/{agent_id}/messages")
def agent_message_list(agent_id: str, status: str = "pending", limit: int = 20) -> list[dict]:
    if not get_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return list_agent_inbox_messages_for_agent(agent_id, status=status, limit=limit)


@router.post("/agents/{agent_id}/messages", status_code=status.HTTP_201_CREATED)
def agent_message_create(agent_id: str, payload: AgentMessagePayload) -> dict:
    try:
        message = write_agent_inbox_message(
            agent_id,
            content=payload.content,
            source_agent_id=payload.sourceAgentId,
            source_session_id=payload.sourceSessionId,
            source_room_id=payload.sourceRoomId,
            source_round_id=payload.sourceRoundId,
            thread_id=payload.threadId,
            kind=payload.kind or "agent_direct_message",
            summary=payload.summary,
            prompt_eligible=payload.promptEligible,
            created_by=payload.createdBy,
            metadata=payload.metadata,
        )
        if payload.wakeTarget:
            message["delivery"] = session_service.wake_agent_for_inbox_message(message)
        else:
            message["delivery"] = {
                "wakeRequested": False,
                "wakeStatus": "not_requested",
                "messageId": message.get("messageId") or message.get("eventId") or "",
                "targetAgentId": message.get("targetAgentId") or "",
                "targetSessionId": message.get("targetSessionId") or "",
                "turnId": "",
                "reason": "",
            }
        return message
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/messages/{message_id}/consume")
def agent_message_consume(agent_id: str, message_id: str, payload: AgentMessageConsumePayload) -> dict:
    try:
        return consume_agent_inbox_message(
            agent_id,
            message_id,
            consumed_by_session_id=payload.consumedBySessionId,
            consumed_by_turn_id=payload.consumedByTurnId,
        )
    except (AgentNotFoundError, AgentMessageNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/agents/{agent_id}")
def agent_update(agent_id: str, payload: AgentUpdatePayload) -> dict:
    try:
        return update_agent_instance(
            agent_id,
            display_name=payload.displayName,
            template_id=payload.templateId,
            profile_id=payload.profileId,
            primary_mode=payload.primaryMode,
            role_key=payload.roleKey,
            prompt_template_id=payload.promptTemplateId,
            tool_policy_id=payload.toolPolicyId,
            memory_policy_id=payload.memoryPolicyId,
            tool_policy=payload.toolPolicy,
            memory_policy=payload.memoryPolicy,
            delegation_policy=payload.delegationPolicy,
            supervision_policy=payload.supervisionPolicy,
            metadata=payload.metadata,
            status=payload.status,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/agents/{agent_id}/mode-membership")
def agent_mode_membership_update(agent_id: str, payload: AgentModeMembershipUpdatePayload) -> dict:
    try:
        _ensure_config_agent_instances()
        return update_agent_mode_membership(
            agent_id,
            chat_default=payload.chatDefault,
            chat_available=payload.chatAvailable,
            research_pool=payload.researchPool,
            supervised_slot=payload.supervisedSlot,
            self_evolution_slot=payload.selfEvolutionSlot,
        )
    except AgentModeBindingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/agents/{agent_id}/chat-rooms")
def agent_chat_room_membership_update(agent_id: str, payload: AgentChatRoomMembershipUpdatePayload) -> dict:
    try:
        _ensure_config_agent_instances()
        return update_agent_chat_room_membership(agent_id, payload.roomIds)
    except ChatRoomBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChatRoomValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/agents/{agent_id}")
def agent_archive(agent_id: str) -> dict:
    try:
        ensure_agent_archive_allowed(agent_id)
        room_cleanup = remove_agent_from_chat_rooms(agent_id)
        mode_cleanup = remove_agent_from_mode_bindings(agent_id)
        agent = archive_agent_instance(agent_id)
        return {
            **agent,
            "archiveSummary": {
                "modeBindingsRepaired": len(mode_cleanup.get("repairWarnings") or []),
                "removedFromRoomIds": list(room_cleanup.get("changedRoomIds") or []),
                "dataRetention": "archived_only",
            },
        }
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatRoomBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (AgentDirectoryError, AgentModeBindingError, ChatRoomValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/agents/{agent_id}/purge")
def agent_purge(agent_id: str) -> dict:
    try:
        ensure_agent_purge_allowed(agent_id)
        room_cleanup = remove_agent_from_chat_rooms(agent_id, allow_empty_rooms=True)
        mode_cleanup = remove_agent_from_mode_bindings(agent_id)
        purge = purge_archived_agent_instance(agent_id)
        return {
            **purge,
            "purgeSummary": {
                "modeBindingsRepaired": len(mode_cleanup.get("repairWarnings") or []),
                "removedFromRoomIds": list(room_cleanup.get("changedRoomIds") or []),
                "dataRetention": "purged",
            },
        }
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatRoomBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (AgentDirectoryError, AgentModeBindingError, ChatRoomValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/prompt-templates")
def prompt_template_list(includeInactive: bool = False) -> dict:
    return list_prompt_templates(include_inactive=includeInactive)


@router.get("/prompt-templates/{template_id}")
def prompt_template_detail(template_id: str) -> dict:
    try:
        template = get_prompt_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Prompt template not found")
        return template
    except PromptTemplateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/prompt-templates/{template_id}")
def prompt_template_update(template_id: str, payload: PromptTemplateUpdatePayload) -> dict:
    try:
        return update_prompt_template(
            template_id,
            name=payload.name,
            category=payload.category,
            source_path=payload.sourcePath,
            content=payload.content,
            metadata=payload.metadata,
            status=payload.status,
        )
    except PromptTemplateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/prompt-templates/{template_id}/reset")
def prompt_template_reset(template_id: str) -> dict:
    try:
        return reset_prompt_template(template_id)
    except PromptTemplateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/agent-mode-bindings")
def mode_binding_detail() -> dict:
    _ensure_config_agent_instances()
    return get_mode_bindings_payload()


@router.patch("/agent-mode-bindings/{mode}")
def mode_binding_update(mode: str, payload: ModeBindingUpdatePayload) -> dict:
    try:
        _ensure_config_agent_instances()
        return update_mode_binding(
            mode,
            default_agent_id=payload.defaultAgentId,
            available_agent_ids=payload.availableAgentIds,
            pool=payload.pool,
            flow_bindings=payload.flowBindings,
            slots=payload.slots,
        )
    except AgentModeBindingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/agent-mode-bindings/{mode}/slots/{slot}")
def mode_binding_slot_update(mode: str, slot: str, payload: ModeBindingSlotUpdatePayload) -> dict:
    try:
        _ensure_config_agent_instances()
        current = (get_mode_bindings_payload().get("modes") or {}).get(mode, {})
        slots = dict(current.get("slots") or {}) if isinstance(current, dict) else {}
        slots[slot] = payload.agentId
        return update_mode_binding(mode, slots=slots)
    except AgentModeBindingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/agent-mode-bindings/{mode}/pool")
def mode_binding_pool_update(mode: str, payload: ModeBindingPoolUpdatePayload) -> dict:
    try:
        _ensure_config_agent_instances()
        return update_mode_binding(mode, pool=payload.agentIds)
    except AgentModeBindingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
