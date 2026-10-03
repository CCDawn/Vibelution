"""Team bundle export / import routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from core.web.services.team_bundle_service import (
    TeamBundleError,
    export_team_bundle,
    import_team_bundle,
)

router = APIRouter(tags=["team-bundles"])


class TeamBundleMemberResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    bundleAgentKey: str = ""
    role: str = ""
    purpose: str = ""
    responsibilities: list[str] = Field(default_factory=list)


class TeamBundleChatRoomResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: str = ""
    purpose: str = ""


class TeamBundleTeamResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = ""
    description: str = ""
    purpose: str = ""
    members: list[TeamBundleMemberResponse] = Field(default_factory=list)
    chatRoom: TeamBundleChatRoomResponse = Field(default_factory=TeamBundleChatRoomResponse)


class TeamBundleAgentResponse(BaseModel):
    """Portable Agent configuration; policy/profile objects stay extensible."""

    model_config = ConfigDict(extra="allow")

    bundleAgentKey: str = ""
    agentCode: str | None = None
    displayName: str = ""
    kind: str | None = None
    primaryMode: str | None = None
    roleKey: str | None = None
    llmBindings: dict[str, Any] | None = None
    promptTemplateId: str | None = None
    toolPolicy: dict[str, Any] | None = None
    memoryPolicy: dict[str, Any] | None = None
    contextCompressionPolicy: dict[str, Any] | None = None
    permissionPreset: str | None = None
    metadata: dict[str, Any] | None = None
    personaProfile: dict[str, Any] | None = None
    taskProfile: dict[str, Any] | None = None


class TeamBundlePromptTemplateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    templateId: str
    label: str | None = None
    content: str | None = None
    description: str | None = None
    sourcePath: str | None = None


class TeamBundleCanvasNodeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class TeamBundleCanvasResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    nodes: list[TeamBundleCanvasNodeResponse] | None = None


class TeamBundleProviderDependencyResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    models: list[str] = Field(default_factory=list)


class TeamBundleExportDependenciesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    providers: dict[str, TeamBundleProviderDependencyResponse] = Field(default_factory=dict)


class TeamBundleExportResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str
    schemaVersion: int
    exportedAt: str
    appVersion: str
    team: TeamBundleTeamResponse
    agents: list[TeamBundleAgentResponse]
    promptTemplates: list[TeamBundlePromptTemplateResponse]
    canvas: TeamBundleCanvasResponse
    dependencies: TeamBundleExportDependenciesResponse


class TeamBundleImportTeamResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    action: str


class TeamBundleImportAgentsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    create: list[str]
    overwrite: list[str]


class TeamBundleMissingModelResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    providerId: str
    model: str


class TeamBundlePendingCredentialResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    providerId: str
    credentialEnv: str


class TeamBundleImportDependenciesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    missingProviders: list[str]
    missingModels: list[TeamBundleMissingModelResponse]
    pendingCredentials: list[TeamBundlePendingCredentialResponse]


class TeamBundleImportedAgentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentId: str
    action: str


class TeamBundleImportResultResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str
    agents: list[TeamBundleImportedAgentResponse]


class TeamBundleImportResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int
    bundleSchemaVersion: int
    status: str
    dryRun: bool
    team: TeamBundleImportTeamResponse
    agents: TeamBundleImportAgentsResponse
    dependencies: TeamBundleImportDependenciesResponse
    warnings: list[str]
    result: TeamBundleImportResultResponse | None = None

_ERROR_STATUS: dict[str, int] = {
    "team_not_found": status.HTTP_404_NOT_FOUND,
    "unsupported_kind": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "invalid_schema_version": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "invalid_team": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "invalid_agents": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "invalid_agent": status.HTTP_422_UNPROCESSABLE_ENTITY,
}


class TeamBundleImportPayload(BaseModel):
    bundle: dict[str, Any]
    dryRun: bool = True
    confirm: bool = Field(
        default=False,
        description="Required to execute an import whose bundle schema major exceeds the supported major.",
    )


@router.get(
    "/teams/{team_id}/bundle",
    response_model=TeamBundleExportResponse,
    response_model_exclude_unset=True,
)
def team_bundle_export(team_id: str) -> dict[str, Any]:
    try:
        return export_team_bundle(team_id)
    except TeamBundleError as error:
        raise HTTPException(
            status_code=_ERROR_STATUS.get(error.code, status.HTTP_400_BAD_REQUEST),
            detail=str(error),
        ) from error


@router.post(
    "/team-bundles/import",
    response_model=TeamBundleImportResponse,
    response_model_exclude_unset=True,
)
def team_bundle_import(payload: TeamBundleImportPayload) -> dict[str, Any]:
    try:
        return import_team_bundle(
            payload.bundle,
            dry_run=bool(payload.dryRun),
            confirm=bool(payload.confirm),
        )
    except TeamBundleError as error:
        raise HTTPException(
            status_code=_ERROR_STATUS.get(error.code, status.HTTP_400_BAD_REQUEST),
            detail=str(error),
        ) from error
