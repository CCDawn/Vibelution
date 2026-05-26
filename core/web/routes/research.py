"""Research workbench routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.web.services.research_service import (
    approve_theme_card,
    create_theme_discovery_session,
    delete_theme_discovery_session,
    extract_theme_discovery_evidence,
    generate_candidate_themes,
    generate_theme_card,
    get_research_flow_canvas,
    get_theme_discovery_session,
    list_theme_discovery_sessions,
    list_research_prompts,
    run_broad_theme_search,
    run_deep_theme_search,
    run_theme_discovery_draft,
    select_candidate_theme,
    save_research_agent_binding,
    save_research_flow_canvas,
    save_research_prompt,
)


router = APIRouter(tags=["research"])


class ThemeDiscoverySessionPayload(BaseModel):
    openGoal: str = Field("", max_length=8000)
    constraints: str = Field("", max_length=8000)
    preferences: str = Field("", max_length=8000)
    candidateCount: int = 5


class ResearchPromptUpdatePayload(BaseModel):
    key: str = Field("", max_length=64)
    content: str = Field("", max_length=50000)


class ResearchAgentTemplateUpdatePayload(BaseModel):
    key: str = Field("", max_length=64)
    templateId: str = Field("", max_length=128)
    llmConfigId: str = Field("", max_length=128)


class ResearchDeepSearchPayload(BaseModel):
    evidenceRequests: list[str] = Field(default_factory=list, max_length=8)


class ResearchFlowCanvasPayload(BaseModel):
    schemaVersion: int = 1
    viewport: dict = Field(default_factory=dict)
    nodes: list[dict] = Field(default_factory=list, max_length=80)
    edges: list[dict] = Field(default_factory=list, max_length=160)


@router.get("/research/theme-discovery/sessions")
def research_theme_discovery_sessions() -> dict:
    return list_theme_discovery_sessions()


@router.post("/research/theme-discovery/sessions", status_code=status.HTTP_201_CREATED)
def research_theme_discovery_session_create(payload: ThemeDiscoverySessionPayload) -> dict:
    try:
        return create_theme_discovery_session(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/research/theme-discovery/sessions/{session_id}")
def research_theme_discovery_session_detail(session_id: str) -> dict:
    try:
        return get_theme_discovery_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/research/theme-discovery/sessions/{session_id}")
def research_theme_discovery_session_delete(session_id: str) -> dict:
    try:
        return delete_theme_discovery_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/research/theme-discovery/sessions/{session_id}/run-broad-search")
def research_theme_discovery_broad_search(session_id: str) -> dict:
    return _run_research_action(lambda: run_broad_theme_search(session_id))


@router.post("/research/theme-discovery/sessions/{session_id}/run-deep-search")
def research_theme_discovery_deep_search(session_id: str, payload: ResearchDeepSearchPayload | None = None) -> dict:
    evidence_requests = payload.evidenceRequests if payload else []
    return _run_research_action(lambda: run_deep_theme_search(session_id, evidence_requests=evidence_requests))


@router.post("/research/theme-discovery/sessions/{session_id}/extract-evidence")
def research_theme_discovery_extract_evidence(session_id: str) -> dict:
    return _run_research_action(lambda: extract_theme_discovery_evidence(session_id))


@router.post("/research/theme-discovery/sessions/{session_id}/generate-themes")
def research_theme_discovery_generate_themes(session_id: str) -> dict:
    return _run_research_action(lambda: generate_candidate_themes(session_id))


@router.post("/research/theme-discovery/sessions/{session_id}/run-draft")
def research_theme_discovery_run_draft(session_id: str) -> dict:
    return _run_research_action(lambda: run_theme_discovery_draft(session_id))


@router.post("/research/theme-discovery/sessions/{session_id}/themes/{theme_id}/select")
def research_theme_discovery_select_theme(session_id: str, theme_id: str) -> dict:
    return _run_research_action(lambda: select_candidate_theme(session_id, theme_id))


@router.post("/research/theme-discovery/sessions/{session_id}/themes/{theme_id}/theme-card")
def research_theme_discovery_theme_card(session_id: str, theme_id: str) -> dict:
    return _run_research_action(lambda: generate_theme_card(session_id, theme_id))


@router.post("/research/theme-discovery/sessions/{session_id}/theme-cards/{card_id}/approve")
def research_theme_discovery_approve_card(session_id: str, card_id: str) -> dict:
    return _run_research_action(lambda: approve_theme_card(session_id, card_id))


@router.get("/research/theme-discovery/prompts")
def research_theme_discovery_prompts() -> dict:
    return list_research_prompts()


@router.put("/research/theme-discovery/prompts")
def research_theme_discovery_prompts_update(payload: ResearchPromptUpdatePayload) -> dict:
    try:
        return save_research_prompt(payload.key, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/research/theme-discovery/agent-templates")
def research_theme_discovery_agent_templates_update(payload: ResearchAgentTemplateUpdatePayload) -> dict:
    try:
        return save_research_agent_binding(payload.key, payload.templateId, payload.llmConfigId)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/research/flow-canvas")
def research_flow_canvas() -> dict:
    try:
        return get_research_flow_canvas()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/research/flow-canvas")
def research_flow_canvas_update(payload: ResearchFlowCanvasPayload) -> dict:
    try:
        return save_research_flow_canvas(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _run_research_action(action):
    try:
        return action()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
