"""Research workbench routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from core.web.routes.research_models import (
    ResearchAgentTemplateUpdatePayload,
    ResearchDeepSearchPayload,
    ResearchFlowCanvasPayload,
    ResearchFlowCanvasResponse,
    ResearchKnowledgeBaseResponse,
    ResearchOrgMessagePayload,
    ResearchOrgMessageResponse,
    ResearchOrgProposalPayload,
    ResearchOrgProposalResponse,
    ResearchOrganizationGraphResponse,
    ResearchOrganizationPayload,
    ResearchPromptUpdatePayload,
    ResearchPromptsResponse,
    ThemeDiscoverySessionDeleteResponse,
    ThemeDiscoverySessionListResponse,
    ThemeDiscoverySessionPayload,
    ThemeDiscoverySessionResponse,
)
from core.web.services.research_service import (
    approve_theme_card,
    create_theme_discovery_session,
    delete_theme_discovery_session,
    extract_theme_discovery_evidence,
    generate_candidate_themes,
    generate_theme_card,
    get_research_knowledge_base,
    get_research_flow_canvas,
    get_theme_discovery_session,
    list_theme_discovery_sessions,
    list_research_prompts,
    run_broad_theme_search,
    run_deep_theme_search,
    run_theme_discovery_draft,
    select_candidate_theme,
    save_research_agent_binding,
    delete_research_agent_binding,
    save_research_flow_canvas,
    save_research_prompt,
)
from core.web.services.research_organization_service import (
    ResearchOrganizationError,
    apply_research_org_proposal,
    create_research_org_proposal,
    get_research_organization,
    retry_research_org_message_wake,
    save_research_organization,
    send_research_org_message,
)


router = APIRouter(tags=["research"])


@router.get(
    "/research/knowledge-base",
    response_model=ResearchKnowledgeBaseResponse,
    response_model_exclude_unset=True,
)
def research_knowledge_base(
    query: str = "",
    kind: str = "",
    category: str = "",
    limit: int = 100,
) -> dict:
    return get_research_knowledge_base(query=query, kind=kind, category=category, limit=limit)


@router.get(
    "/research/theme-discovery/sessions",
    response_model=ThemeDiscoverySessionListResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_sessions() -> dict:
    return list_theme_discovery_sessions()


@router.post(
    "/research/theme-discovery/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=ThemeDiscoverySessionResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_session_create(payload: ThemeDiscoverySessionPayload) -> dict:
    try:
        return create_theme_discovery_session(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/research/theme-discovery/sessions/{session_id}",
    response_model=ThemeDiscoverySessionResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_session_detail(session_id: str) -> dict:
    try:
        return get_theme_discovery_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/research/theme-discovery/sessions/{session_id}",
    response_model=ThemeDiscoverySessionDeleteResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_session_delete(session_id: str) -> dict:
    try:
        return delete_theme_discovery_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/research/theme-discovery/sessions/{session_id}/run-broad-search",
    response_model=ThemeDiscoverySessionResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_broad_search(session_id: str) -> dict:
    return _run_research_action(lambda: run_broad_theme_search(session_id))


@router.post(
    "/research/theme-discovery/sessions/{session_id}/run-deep-search",
    response_model=ThemeDiscoverySessionResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_deep_search(session_id: str, payload: ResearchDeepSearchPayload | None = None) -> dict:
    evidence_requests = payload.evidenceRequests if payload else []
    return _run_research_action(lambda: run_deep_theme_search(session_id, evidence_requests=evidence_requests))


@router.post(
    "/research/theme-discovery/sessions/{session_id}/extract-evidence",
    response_model=ThemeDiscoverySessionResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_extract_evidence(session_id: str) -> dict:
    return _run_research_action(lambda: extract_theme_discovery_evidence(session_id))


@router.post(
    "/research/theme-discovery/sessions/{session_id}/generate-themes",
    response_model=ThemeDiscoverySessionResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_generate_themes(session_id: str) -> dict:
    return _run_research_action(lambda: generate_candidate_themes(session_id))


@router.post(
    "/research/theme-discovery/sessions/{session_id}/run-draft",
    response_model=ThemeDiscoverySessionResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_run_draft(session_id: str) -> dict:
    return _run_research_action(lambda: run_theme_discovery_draft(session_id))


@router.post(
    "/research/theme-discovery/sessions/{session_id}/themes/{theme_id}/select",
    response_model=ThemeDiscoverySessionResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_select_theme(session_id: str, theme_id: str) -> dict:
    return _run_research_action(lambda: select_candidate_theme(session_id, theme_id))


@router.post(
    "/research/theme-discovery/sessions/{session_id}/themes/{theme_id}/theme-card",
    response_model=ThemeDiscoverySessionResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_theme_card(session_id: str, theme_id: str) -> dict:
    return _run_research_action(lambda: generate_theme_card(session_id, theme_id))


@router.post(
    "/research/theme-discovery/sessions/{session_id}/theme-cards/{card_id}/approve",
    response_model=ThemeDiscoverySessionResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_approve_card(session_id: str, card_id: str) -> dict:
    return _run_research_action(lambda: approve_theme_card(session_id, card_id))


@router.get(
    "/research/theme-discovery/prompts",
    response_model=ResearchPromptsResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_prompts() -> dict:
    return list_research_prompts()


@router.put(
    "/research/theme-discovery/prompts",
    response_model=ResearchPromptsResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_prompts_update(payload: ResearchPromptUpdatePayload) -> dict:
    try:
        return save_research_prompt(payload.key, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put(
    "/research/theme-discovery/agent-templates",
    response_model=ResearchPromptsResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_agent_templates_update(payload: ResearchAgentTemplateUpdatePayload) -> dict:
    try:
        return save_research_agent_binding(
            payload.key,
            payload.templateId,
            payload.profileId or payload.llmConfigId,
            label=payload.label,
            prompt_filename=payload.promptFilename,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/research/theme-discovery/agent-templates/{agent_key}",
    response_model=ResearchPromptsResponse,
    response_model_exclude_unset=True,
)
def research_theme_discovery_agent_templates_delete(agent_key: str) -> dict:
    try:
        return delete_research_agent_binding(agent_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/research/flow-canvas",
    response_model=ResearchFlowCanvasResponse,
    response_model_exclude_unset=True,
)
def research_flow_canvas() -> dict:
    try:
        return get_research_flow_canvas()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put(
    "/research/flow-canvas",
    response_model=ResearchFlowCanvasResponse,
    response_model_exclude_unset=True,
)
def research_flow_canvas_update(payload: ResearchFlowCanvasPayload) -> dict:
    try:
        return save_research_flow_canvas(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/research/organization",
    response_model=ResearchOrganizationGraphResponse,
    response_model_exclude_unset=True,
)
def research_organization() -> dict:
    return _run_research_action(get_research_organization)


@router.put(
    "/research/organization",
    response_model=ResearchOrganizationGraphResponse,
    response_model_exclude_unset=True,
)
def research_organization_update(payload: ResearchOrganizationPayload) -> dict:
    return _run_research_action(lambda: save_research_organization(payload.model_dump()))


@router.post(
    "/research/organization/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=ResearchOrgMessageResponse,
    response_model_exclude_unset=True,
)
def research_organization_message_create(payload: ResearchOrgMessagePayload) -> dict:
    data = payload.model_dump()
    if payload.humanOverride is None:
        data.pop("humanOverride", None)
    return _run_research_action(lambda: send_research_org_message(data))


@router.post(
    "/research/organization/proposals",
    status_code=status.HTTP_201_CREATED,
    response_model=ResearchOrgProposalResponse,
    response_model_exclude_unset=True,
)
def research_organization_proposal_create(payload: ResearchOrgProposalPayload) -> dict:
    return _run_research_action(lambda: create_research_org_proposal(payload.model_dump()))


@router.post(
    "/research/organization/proposals/{proposal_id}/apply",
    response_model=ResearchOrgProposalResponse,
    response_model_exclude_unset=True,
)
def research_organization_proposal_apply(proposal_id: str) -> dict:
    return _run_research_action(lambda: apply_research_org_proposal(proposal_id))


@router.post(
    "/research/organization/messages/{message_id}/retry-wake",
    response_model=ResearchOrgMessageResponse,
    response_model_exclude_unset=True,
)
def research_organization_message_retry_wake(message_id: str) -> dict:
    return _run_research_action(lambda: retry_research_org_message_wake(message_id))


def _run_research_action(action):
    try:
        return action()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ResearchOrganizationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
