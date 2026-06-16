"""Agent memory overview routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.web.services.memory_service import (
    create_user_memory_item,
    delete_memory_item,
    get_agent_memory_inventory,
    get_memory_item_detail,
    get_memory_overview,
    get_memory_usage_contract,
    restore_memory_item,
    update_memory_item,
)
from core.web.services.memory_graph_service import (
    MemoryKnowledgeGraphAmbiguousNodeError,
    get_memory_knowledge_graph,
    get_memory_knowledge_graph_node_detail,
    record_memory_knowledge_graph_blocked,
)
from core.web.services.memory_cleanup_service import (
    MemoryCleanupError,
    execute_memory_cleanup,
    preview_memory_cleanup,
)


router = APIRouter(tags=["memory"])


class MemoryItemPayload(BaseModel):
    title: str = Field("", max_length=160)
    summary: str = Field("", max_length=1000)
    content: str = Field("", max_length=20000)


class MemoryCleanupTargetPayload(BaseModel):
    targetType: str = Field("", max_length=80)
    agentId: str = Field("", max_length=160)
    teamId: str = Field("", max_length=160)
    ownerType: str = Field("", max_length=32)
    ownerId: str = Field("", max_length=160)
    knowledgeBaseId: str = Field("", max_length=260)
    scopedKnowledgeBaseId: str = Field("", max_length=320)


class MemoryCleanupPreviewPayload(BaseModel):
    targets: list[MemoryCleanupTargetPayload] = Field(default_factory=list, max_length=200)


class MemoryCleanupExecutePayload(MemoryCleanupPreviewPayload):
    confirmationPhrase: str = Field("", max_length=80)


@router.get("/memory/overview")
def memory_overview(includeContent: bool = True) -> dict:
    return get_memory_overview(include_content=includeContent)


@router.get("/memory/usage-contract")
def memory_usage_contract() -> dict:
    return get_memory_usage_contract()


@router.get("/memory/agents")
def memory_agents(agentId: str = "", includeContent: bool = False) -> dict:
    return get_agent_memory_inventory(agent_id=agentId, include_content=includeContent)


@router.get("/memory/agents/{agent_id}")
def memory_agent_detail(agent_id: str, includeContent: bool = True) -> dict:
    payload = get_agent_memory_inventory(agent_id=agent_id, include_content=includeContent)
    if payload.get("selectedAgent") is None:
        raise HTTPException(status_code=404, detail="Agent memory not found.")
    return payload


@router.get("/memory/knowledge-graph")
def memory_knowledge_graph(
    agentId: str = "",
    teamId: str = "",
    knowledgeBaseId: str = "",
    include: str = "",
    limit: int = 800,
) -> dict:
    normalized_agent_id = str(agentId or "").strip()
    if not normalized_agent_id:
        record_memory_knowledge_graph_blocked(reason="agent_id_required", team_id=teamId, knowledge_base_id=knowledgeBaseId, include=include)
        raise HTTPException(status_code=422, detail="agentId is required for memory knowledge graph.")
    return get_memory_knowledge_graph(
        agent_id=normalized_agent_id,
        team_id=teamId,
        knowledge_base_id=knowledgeBaseId,
        include=include,
        limit=limit,
    )


@router.get("/memory/knowledge-graph/node-detail")
def memory_knowledge_graph_node_detail(
    nodeId: str = "",
    agentId: str = "",
    limit: int = 40,
) -> dict:
    if not str(nodeId or "").strip():
        raise HTTPException(status_code=422, detail="nodeId is required.")
    normalized_agent_id = str(agentId or "").strip()
    if not normalized_agent_id:
        raise HTTPException(status_code=422, detail="agentId is required for memory graph node detail.")
    try:
        payload = get_memory_knowledge_graph_node_detail(nodeId, agent_id=normalized_agent_id, limit=limit)
    except MemoryKnowledgeGraphAmbiguousNodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Memory graph node detail not found.")
    return payload


@router.post("/memory/cleanup/preview")
def memory_cleanup_preview(payload: MemoryCleanupPreviewPayload) -> dict:
    try:
        return preview_memory_cleanup([target.model_dump() for target in payload.targets])
    except MemoryCleanupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/memory/cleanup/execute")
def memory_cleanup_execute(payload: MemoryCleanupExecutePayload) -> dict:
    try:
        return execute_memory_cleanup(
            [target.model_dump() for target in payload.targets],
            confirmation_phrase=payload.confirmationPhrase,
        )
    except MemoryCleanupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/memory/items", status_code=status.HTTP_201_CREATED)
def memory_item_create(payload: MemoryItemPayload) -> dict:
    try:
        return create_user_memory_item(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/memory/items/{section_id}/{item_id}")
def memory_item_detail(section_id: str, item_id: str) -> dict:
    payload = get_memory_item_detail(section_id, item_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Memory item not found.")
    return payload


@router.patch("/memory/items/{section_id}/{item_id}")
def memory_item_update(section_id: str, item_id: str, payload: MemoryItemPayload) -> dict:
    try:
        return update_memory_item(section_id, item_id, payload.model_dump(exclude_unset=True))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/memory/items/{section_id}/{item_id}")
def memory_item_delete(section_id: str, item_id: str) -> dict:
    try:
        return delete_memory_item(section_id, item_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/memory/items/{section_id}/{item_id}/restore")
def memory_item_restore(section_id: str, item_id: str) -> dict:
    try:
        return restore_memory_item(section_id, item_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
