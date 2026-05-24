"""Tool registry routes for the local web workbench."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.web.services.tool_registry_service import (
    ToolRegistryConflictError,
    ToolRegistryError,
    ToolRegistryPermissionError,
    create_generated_tool,
    delete_tool,
    get_tool_registry,
    set_generated_tool_enabled,
    test_tool,
    validate_generated_tool,
)


router = APIRouter(tags=["tools"])


class GeneratedToolPayload(BaseModel):
    name: str = ""
    description: str = ""
    argsSchema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    responseTemplate: str = ""


class GeneratedToolEnabledPayload(BaseModel):
    enabled: bool


class ToolTestPayload(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    agentScope: str = ""


def _raise_tool_registry_error(exc: Exception) -> None:
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ToolRegistryPermissionError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ToolRegistryConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ToolRegistryError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail="Tool registry operation failed") from exc


@router.get("/tools")
def tools_registry() -> dict:
    return get_tool_registry()


@router.post("/tools/generated")
def tools_generated_create(payload: GeneratedToolPayload) -> dict:
    try:
        return create_generated_tool(payload.model_dump())
    except Exception as exc:  # pragma: no cover - routed by helper
        _raise_tool_registry_error(exc)


@router.post("/tools/generated/{tool_id}/validate")
def tools_generated_validate(tool_id: str) -> dict:
    try:
        return validate_generated_tool(tool_id)
    except Exception as exc:  # pragma: no cover - routed by helper
        _raise_tool_registry_error(exc)


@router.put("/tools/generated/{tool_id}/enabled")
def tools_generated_enabled(tool_id: str, payload: GeneratedToolEnabledPayload) -> dict:
    try:
        return set_generated_tool_enabled(tool_id, payload.enabled)
    except Exception as exc:  # pragma: no cover - routed by helper
        _raise_tool_registry_error(exc)


@router.delete("/tools/{tool_id}")
def tools_delete(tool_id: str) -> dict:
    try:
        return delete_tool(tool_id)
    except Exception as exc:  # pragma: no cover - routed by helper
        _raise_tool_registry_error(exc)


@router.post("/tools/{tool_id}/test")
def tools_test(tool_id: str, payload: ToolTestPayload | None = None) -> dict:
    try:
        return test_tool(
            tool_id,
            args=(payload.args if payload else {}),
            agent_scope=(payload.agentScope if payload else ""),
        )
    except Exception as exc:  # pragma: no cover - routed by helper
        _raise_tool_registry_error(exc)
