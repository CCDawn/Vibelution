"""AgentInstance registry API routes."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from core.orchestration.context_engine import list_agent_runs_for_agent
from core.web.services import agent_directory_service, agent_tool_governance_service, session_service
from core.web.services.runtime_scene_service import list_runtime_scene_evidence_for_agent, record_runtime_scene_event
from core.web.services.agent_config_workspace_service import get_agent_config_workspace
from core.web.services.agent_directory_service import (
    AgentDirectoryError,
    AgentMemoryProposalNotFoundError,
    AgentMessageNotFoundError,
    AgentNotFoundError,
    archive_agent_instance,
    consume_all_agent_inbox_messages,
    consume_agent_inbox_message,
    ensure_agent_archive_allowed,
    ensure_agent_purge_allowed,
    get_agent,
    list_agent_avatar_options,
    list_agent_inbox_messages_for_agent,
    list_agents,
    list_project_memory_update_proposals,
    purge_archived_agent_instance,
    reset_agent_instance,
    resolve_agent_avatar_file,
    resolve_project_memory_update_proposal,
    store_agent_avatar_image,
    update_agent_avatar,
    update_agent_instance,
    write_agent_inbox_message,
    write_project_memory_update_proposal,
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


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 1)


def _record_agent_archive_route_event(
    event_code: str,
    agent_id: str,
    *,
    outcome: str,
    timings: dict[str, float] | None = None,
    room_cleanup: dict[str, Any] | None = None,
    mode_cleanup: dict[str, Any] | None = None,
    level: str = "info",
    error: Exception | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "archive",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={
                "agentId": str(agent_id or "").strip(),
                "timingsMs": dict(timings or {}),
                "removedRoomCount": len(list((room_cleanup or {}).get("changedRoomIds") or [])),
                "modeChangedCount": len(list((mode_cleanup or {}).get("changedModes") or [])),
                "repairWarningCount": len(list((mode_cleanup or {}).get("repairWarnings") or [])),
                "errorType": type(error).__name__ if error is not None else "",
                "source": "AgentArchiveAPI",
            },
            lifecycle=True,
        )
    except Exception:
        return


class AgentCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    displayName: str = ""
    llmBindings: dict[str, Any] = Field(default_factory=dict)
    primaryMode: str = ""
    roleKey: str = ""
    promptTemplateId: str = ""
    toolPolicy: dict[str, Any] = Field(default_factory=dict)
    personaProfile: dict[str, Any] = Field(default_factory=dict)
    taskProfile: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    displayName: str | None = None
    llmBindings: dict[str, Any] | None = None
    primaryMode: str | None = None
    roleKey: str | None = None
    promptTemplateId: str | None = None
    toolPolicyId: str | None = None
    memoryPolicyId: str | None = None
    toolPolicy: dict[str, Any] | None = None
    memoryPolicy: dict[str, Any] | None = None
    delegationPolicy: dict[str, Any] | None = None
    supervisionPolicy: dict[str, Any] | None = None
    personaProfile: dict[str, Any] | None = None
    taskProfile: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    status: str | None = None


class AgentAvatarUpdatePayload(BaseModel):
    avatarImagePath: str = ""
    resetToDefault: bool = False


class AgentResetPayload(BaseModel):
    clearRuntimeState: bool = True
    resetDirectSession: bool = True
    resetPersonaProfile: bool = False
    resetTaskProfile: bool = False
    resetToolPolicy: bool = False
    resetMemoryPolicy: bool = False
    resetRuntimePolicy: bool = False


class AgentAvatarUploadPayload(BaseModel):
    filename: str = ""
    contentType: str = ""
    dataBase64: str = ""


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


class AgentProjectMemoryUpdatePayload(BaseModel):
    laneId: str = ""
    focus: str = ""
    update: str = ""
    details: str = ""
    relatedFiles: list[str] = Field(default_factory=list)
    sourceSessionId: str = ""
    sourceTurnId: str = ""


class AgentProjectMemoryUpdateResolvePayload(BaseModel):
    status: str = ""
    resolvedBy: str = "coordinator"
    resolutionNote: str = ""


class AgentToolGovernanceRequestPayload(BaseModel):
    proposedByAgentId: str = ""
    grantTools: list[str] = Field(default_factory=list)
    revokeTools: list[str] = Field(default_factory=list)
    blockTools: list[str] = Field(default_factory=list)
    unblockTools: list[str] = Field(default_factory=list)
    reason: str = ""
    applyMode: str = "auto"


class AgentToolGovernanceResolvePayload(BaseModel):
    decision: str = ""
    resolvedBy: str = "user"
    resolutionNote: str = ""


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
    try:
        modes = get_mode_bindings_payload().get("modes") or {}
        supervised_mode = dict(modes.get("supervised_evolution") or {})
        self_mode = dict(modes.get("self_evolution") or {})
        present_supervised.update(
            item for item in list(supervised_mode.get("excludedSlots") or []) if item in supervised_roles
        )
        present_self.update(item for item in list(self_mode.get("excludedSlots") or []) if item in self_roles)
    except Exception:
        pass
    return supervised_roles.issubset(present_supervised) and self_roles.issubset(present_self)


@router.get("/agents")
def agent_list(includeArchived: bool = False) -> list[dict]:
    _ensure_config_agent_instances()
    return list_agents(include_archived=includeArchived)


@router.get("/agents/avatar-image/{filename}")
def agent_avatar_image(filename: str) -> FileResponse:
    try:
        path = resolve_agent_avatar_file(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent avatar image not found") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Agent avatar image not found")
    return FileResponse(path)


@router.get("/agents/avatar-options")
def agent_avatar_options() -> dict:
    return list_agent_avatar_options()


@router.get("/agents/config-workspace")
def agent_config_workspace() -> dict:
    _ensure_config_agent_instances()
    return get_agent_config_workspace()


@router.get("/agents/project-memory-updates")
def agent_project_memory_update_list(status: str = "pending", agentId: str = "", limit: int = 50) -> list[dict]:
    return list_project_memory_update_proposals(agent_id=agentId, status=status, limit=limit)


@router.get("/agents/tool-governance-requests")
def agent_tool_governance_request_list(status: str = "pending_review", agentId: str = "", limit: int = 50) -> list[dict]:
    return agent_tool_governance_service.list_tool_governance_requests(agent_id=agentId, status=status, limit=limit)


@router.patch("/agents/{agent_id}/avatar")
def agent_avatar_update(agent_id: str, payload: AgentAvatarUpdatePayload) -> dict:
    try:
        return update_agent_avatar(
            agent_id,
            avatar_image_path=payload.avatarImagePath,
            reset_to_default=payload.resetToDefault,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/avatar-image")
def agent_avatar_upload(agent_id: str, payload: AgentAvatarUploadPayload) -> dict:
    try:
        return store_agent_avatar_image(
            agent_id,
            filename=payload.filename,
            content_type=payload.contentType,
            data_base64=payload.dataBase64,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agents", status_code=status.HTTP_201_CREATED)
def agent_create(payload: AgentCreatePayload) -> dict:
    try:
        display_name = payload.displayName.strip()
        llm_bindings = agent_directory_service.normalize_agent_llm_bindings(payload.llmBindings)
        persona_profile = payload.personaProfile if isinstance(payload.personaProfile, dict) else {}
        task_profile = payload.taskProfile if isinstance(payload.taskProfile, dict) else {}
        tool_policy = payload.toolPolicy if isinstance(payload.toolPolicy, dict) else {}
        _validate_agent_create_payload(
            display_name=display_name,
            llm_bindings=llm_bindings,
            primary_mode=payload.primaryMode,
            role_key=payload.roleKey,
            prompt_template_id=payload.promptTemplateId,
            persona_profile=persona_profile,
            task_profile=task_profile,
            tool_policy=tool_policy,
        )
        metadata = dict(payload.metadata or {})
        session = session_service.create_chat_session(
            title=display_name,
            llm_bindings=llm_bindings,
            created_by="api_agents",
        )
        agent_id = str(session.get("agentId") or "").strip()
        agent = get_agent(agent_id) if agent_id else None
        if not agent:
            raise AgentDirectoryError("Agent was not created for the direct session.")
        if metadata:
            agent = update_agent_instance(agent_id, metadata=metadata)
        if persona_profile:
            agent = update_agent_instance(agent_id, persona_profile=persona_profile)
        if task_profile:
            agent = update_agent_instance(agent_id, task_profile=task_profile)
        if tool_policy:
            agent = update_agent_instance(agent_id, tool_policy=tool_policy)
        if payload.primaryMode or payload.roleKey or payload.promptTemplateId:
            agent = update_agent_instance(
                agent_id,
                llm_bindings=llm_bindings,
                primary_mode=payload.primaryMode or None,
                role_key=payload.roleKey or None,
                prompt_template_id=payload.promptTemplateId or None,
            )
        return agent
    except session_service.SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validate_agent_create_payload(
    *,
    display_name: str,
    llm_bindings: dict[str, Any],
    primary_mode: str,
    role_key: str,
    prompt_template_id: str,
    persona_profile: dict[str, Any],
    task_profile: dict[str, Any],
    tool_policy: dict[str, Any],
) -> None:
    missing: list[str] = []
    normalized_primary_mode = str(primary_mode or "").strip()
    is_work_session = normalized_primary_mode in {"", "chat"}
    if not display_name:
        missing.append("功能名")
    if not agent_directory_service.agent_dialogue_model_id({"llmBindings": llm_bindings}):
        missing.append("对话模型")
    if not normalized_primary_mode:
        missing.append("使用位置")
    if not is_work_session and not str(role_key or "").strip():
        missing.append("角色键")
    if not str(prompt_template_id or "").strip():
        missing.append("提示词")
    if not is_work_session and not agent_directory_service.agent_persona_profile_has_content(persona_profile):
        missing.append("人物档案")
    if not is_work_session and not agent_directory_service.agent_task_profile_has_content(task_profile):
        missing.append("任务档案")
    allowed_tools = tool_policy.get("allowedTools") if isinstance(tool_policy, dict) else []
    if not is_work_session and (not isinstance(allowed_tools, list) or not any(str(item or "").strip() for item in allowed_tools)):
        missing.append("工具包")
    if missing:
        raise AgentDirectoryError("Agent 创建信息不完整，请补齐：" + "、".join(missing) + "。")


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


@router.post("/agents/{agent_id}/project-memory-updates", status_code=status.HTTP_201_CREATED)
def agent_project_memory_update_create(agent_id: str, payload: AgentProjectMemoryUpdatePayload) -> dict:
    try:
        return write_project_memory_update_proposal(
            agent_id,
            lane_id=payload.laneId,
            focus=payload.focus,
            update=payload.update,
            details=payload.details,
            related_files=payload.relatedFiles,
            source_session_id=payload.sourceSessionId,
            source_turn_id=payload.sourceTurnId,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/agents/{agent_id}/project-memory-updates/{proposal_id}")
def agent_project_memory_update_resolve(
    agent_id: str,
    proposal_id: str,
    payload: AgentProjectMemoryUpdateResolvePayload,
) -> dict:
    try:
        return resolve_project_memory_update_proposal(
            agent_id,
            proposal_id,
            status=payload.status,
            resolved_by=payload.resolvedBy,
            resolution_note=payload.resolutionNote,
        )
    except (AgentNotFoundError, AgentMemoryProposalNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/tool-governance-requests", status_code=status.HTTP_201_CREATED)
def agent_tool_governance_request_create(agent_id: str, payload: AgentToolGovernanceRequestPayload) -> dict:
    try:
        return agent_tool_governance_service.submit_tool_governance_request(
            agent_id,
            proposed_by_agent_id=payload.proposedByAgentId,
            grant_tools=payload.grantTools,
            revoke_tools=payload.revokeTools,
            block_tools=payload.blockTools,
            unblock_tools=payload.unblockTools,
            reason=payload.reason,
            apply_mode=payload.applyMode,
        )
    except agent_directory_service.AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except agent_tool_governance_service.AgentToolGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/agents/{agent_id}/tool-governance-requests/{request_id}")
def agent_tool_governance_request_resolve(
    agent_id: str,
    request_id: str,
    payload: AgentToolGovernanceResolvePayload,
) -> dict:
    try:
        return agent_tool_governance_service.resolve_tool_governance_request(
            agent_id,
            request_id,
            decision=payload.decision,
            resolved_by=payload.resolvedBy,
            resolution_note=payload.resolutionNote,
        )
    except (agent_directory_service.AgentNotFoundError, agent_tool_governance_service.AgentToolGovernanceNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except agent_tool_governance_service.AgentToolGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


@router.post("/agents/{agent_id}/messages/consume-all")
def agent_messages_consume_all(agent_id: str, payload: AgentMessageConsumePayload) -> dict:
    try:
        return consume_all_agent_inbox_messages(
            agent_id,
            consumed_by_session_id=payload.consumedBySessionId,
            consumed_by_turn_id=payload.consumedByTurnId,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/agents/{agent_id}")
def agent_update(agent_id: str, payload: AgentUpdatePayload) -> dict:
    try:
        archive_summary: dict[str, Any] | None = None
        if str(payload.status or "").strip() == "archived":
            current = get_agent(agent_id)
            if current and str(current.get("status") or "active").strip() != "archived":
                ensure_agent_archive_allowed(agent_id)
                room_cleanup = remove_agent_from_chat_rooms(
                    agent_id,
                    include_chat_rooms=False,
                    repair_participants=False,
                )
                mode_cleanup = remove_agent_from_mode_bindings(agent_id, include_payload=False)
                archive_summary = {
                    "modeBindingsRepaired": len(mode_cleanup.get("repairWarnings") or []),
                    "removedFromRoomIds": list(room_cleanup.get("changedRoomIds") or []),
                    "dataRetention": "archived_only",
                    "source": "patch_status",
                }
        return update_agent_instance(
            agent_id,
            display_name=payload.displayName,
            llm_bindings=payload.llmBindings,
            primary_mode=payload.primaryMode,
            role_key=payload.roleKey,
            prompt_template_id=payload.promptTemplateId,
            tool_policy_id=payload.toolPolicyId,
            memory_policy_id=payload.memoryPolicyId,
            tool_policy=payload.toolPolicy,
            memory_policy=payload.memoryPolicy,
            delegation_policy=payload.delegationPolicy,
            supervision_policy=payload.supervisionPolicy,
            persona_profile=payload.personaProfile,
            task_profile=payload.taskProfile,
            metadata=payload.metadata,
            status=payload.status,
        ) | ({"archiveSummary": archive_summary} if archive_summary else {})
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatRoomBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (AgentDirectoryError, AgentModeBindingError, ChatRoomValidationError) as exc:
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


def _record_agent_reset_route_event(
    event_code: str,
    agent_id: str,
    payload: AgentResetPayload,
    *,
    outcome: str,
    level: str = "info",
    error: Exception | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "reset",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={
                "agentId": str(agent_id or "").strip(),
                "clearRuntimeState": bool(payload.clearRuntimeState),
                "resetDirectSession": bool(payload.resetDirectSession),
                "resetPersonaProfile": bool(payload.resetPersonaProfile),
                "resetTaskProfile": bool(payload.resetTaskProfile),
                "resetToolPolicy": bool(payload.resetToolPolicy),
                "resetMemoryPolicy": bool(payload.resetMemoryPolicy),
                "resetRuntimePolicy": bool(payload.resetRuntimePolicy),
                "errorType": type(error).__name__ if error is not None else "",
                "source": "AgentResetAPI",
            },
            lifecycle=True,
        )
    except Exception:
        return


@router.post("/agents/{agent_id}/reset")
def agent_reset(agent_id: str, payload: AgentResetPayload) -> dict:
    _record_agent_reset_route_event("agent.reset.requested", agent_id, payload, outcome="requested")
    try:
        return reset_agent_instance(
            agent_id,
            clear_runtime_state=payload.clearRuntimeState,
            reset_direct_session=payload.resetDirectSession,
            reset_persona_profile=payload.resetPersonaProfile,
            reset_task_profile=payload.resetTaskProfile,
            reset_tool_policy=payload.resetToolPolicy,
            reset_memory_policy=payload.resetMemoryPolicy,
            reset_runtime_policy=payload.resetRuntimePolicy,
        )
    except AgentNotFoundError as exc:
        _record_agent_reset_route_event("agent.reset.failed", agent_id, payload, outcome="failed", level="warning", error=exc)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        _record_agent_reset_route_event("agent.reset.failed", agent_id, payload, outcome="failed", level="warning", error=exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _record_agent_reset_route_event("agent.reset.failed", agent_id, payload, outcome="failed", level="error", error=exc)
        raise


@router.delete("/agents/{agent_id}")
def agent_archive(agent_id: str) -> dict:
    total_started = perf_counter()
    timings: dict[str, float] = {}
    room_cleanup: dict[str, Any] = {}
    mode_cleanup: dict[str, Any] = {}
    try:
        stage_started = perf_counter()
        ensure_agent_archive_allowed(agent_id)
        timings["validate"] = _elapsed_ms(stage_started)
        stage_started = perf_counter()
        room_cleanup = remove_agent_from_chat_rooms(
            agent_id,
            include_chat_rooms=False,
            repair_participants=False,
        )
        timings["chat_rooms"] = _elapsed_ms(stage_started)
        stage_started = perf_counter()
        mode_cleanup = remove_agent_from_mode_bindings(agent_id, include_payload=False)
        timings["mode_bindings"] = _elapsed_ms(stage_started)
        stage_started = perf_counter()
        agent = archive_agent_instance(agent_id, cleanup_mode_bindings=False)
        timings["directory"] = _elapsed_ms(stage_started)
        timings["total"] = _elapsed_ms(total_started)
        _record_agent_archive_route_event(
            "agent.archive.completed",
            agent_id,
            outcome="succeeded",
            timings=timings,
            room_cleanup=room_cleanup,
            mode_cleanup=mode_cleanup,
        )
        return {
            **agent,
            "archiveSummary": {
                "modeBindingsRepaired": len(mode_cleanup.get("repairWarnings") or []),
                "removedFromRoomIds": list(room_cleanup.get("changedRoomIds") or []),
                "dataRetention": "archived_only",
            },
        }
    except AgentNotFoundError as exc:
        timings["total"] = _elapsed_ms(total_started)
        _record_agent_archive_route_event(
            "agent.archive.failed",
            agent_id,
            outcome="failed",
            level="warning",
            timings=timings,
            room_cleanup=room_cleanup,
            mode_cleanup=mode_cleanup,
            error=exc,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatRoomBusyError as exc:
        timings["total"] = _elapsed_ms(total_started)
        _record_agent_archive_route_event(
            "agent.archive.failed",
            agent_id,
            outcome="failed",
            level="warning",
            timings=timings,
            room_cleanup=room_cleanup,
            mode_cleanup=mode_cleanup,
            error=exc,
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (AgentDirectoryError, AgentModeBindingError, ChatRoomValidationError) as exc:
        timings["total"] = _elapsed_ms(total_started)
        _record_agent_archive_route_event(
            "agent.archive.failed",
            agent_id,
            outcome="failed",
            level="warning",
            timings=timings,
            room_cleanup=room_cleanup,
            mode_cleanup=mode_cleanup,
            error=exc,
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/agents/{agent_id}/purge")
def agent_purge(agent_id: str) -> dict:
    try:
        ensure_agent_purge_allowed(agent_id)
        room_cleanup = remove_agent_from_chat_rooms(
            agent_id,
            allow_empty_rooms=True,
            include_chat_rooms=False,
            repair_participants=False,
        )
        mode_cleanup = remove_agent_from_mode_bindings(agent_id, include_payload=False)
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
