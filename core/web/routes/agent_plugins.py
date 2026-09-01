"""Typed routes for trusted first-party Agent plugins."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.agent_plugins.virtual_human_life.geography import list_city_locations
from core.agent_plugins.virtual_human_life.service import (
    AgentUnavailableError,
    BindingConflictError,
    VirtualHumanLifeError,
)
from core.web.routes.agent_plugin_models import (
    AgentPluginBindingResponse,
    AgentPluginBindingUpdateRequest,
    AgentPluginCatalogEntryResponse,
    AgentPluginListResponse,
    VirtualHumanCompanionActivityResponse,
    VirtualHumanCompanionResponse,
)
from core.web.routes.virtual_human_life_models import VirtualHumanLocationResponse
from core.web.services.agent_plugin_service import (
    list_agent_plugin_catalog,
    list_agent_plugins,
    list_virtual_human_companion_activity,
    list_virtual_human_companions,
    update_agent_plugin_binding,
)

router = APIRouter(tags=["agent-plugins"])


@router.get(
    "/agent-plugins/catalog",
    response_model=list[AgentPluginCatalogEntryResponse],
    response_model_exclude_unset=True,
)
def agent_plugin_catalog() -> list[dict]:
    return list_agent_plugin_catalog()


@router.get(
    "/agent-plugins/virtual-human-life/companions",
    response_model=list[VirtualHumanCompanionResponse],
    response_model_exclude_unset=True,
)
def virtual_human_companion_list() -> list[dict]:
    return list_virtual_human_companions()


@router.get(
    "/agent-plugins/virtual-human-life/companion-activity",
    response_model=list[VirtualHumanCompanionActivityResponse],
    response_model_exclude_unset=True,
)
def virtual_human_companion_activity_list() -> list[dict]:
    return list_virtual_human_companion_activity()


@router.get(
    "/agent-plugins/virtual-human-life/locations",
    response_model=list[VirtualHumanLocationResponse],
    response_model_exclude_unset=True,
)
def virtual_human_location_list() -> list[dict]:
    return list_city_locations()


@router.get(
    "/agents/{agent_id}/plugins",
    response_model=AgentPluginListResponse,
    response_model_exclude_unset=True,
)
def agent_plugin_list(agent_id: str) -> dict:
    try:
        return list_agent_plugins(agent_id)
    except AgentUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/agents/{agent_id}/plugins/{plugin_id}/binding",
    response_model=AgentPluginBindingResponse,
    response_model_exclude_unset=True,
)
def agent_plugin_binding_update(
    agent_id: str,
    plugin_id: str,
    payload: AgentPluginBindingUpdateRequest,
) -> dict:
    try:
        return update_agent_plugin_binding(
            agent_id,
            plugin_id,
            enabled=payload.enabled,
            expected_version=payload.expectedVersion,
            config=payload.config,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BindingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except VirtualHumanLifeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
