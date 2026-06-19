"""Workspace storage migration routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.web.services.workspace_data_migration_service import (
    WorkspaceDataMigrationError,
    apply_workspace_migration,
    execute_legacy_workspace_cleanup,
    get_workspace_migration_status,
    preview_legacy_workspace_cleanup,
    preview_workspace_migration,
    verify_workspace_migration,
)


router = APIRouter(tags=["storage"])


class WorkspaceMigrationPayload(BaseModel):
    reportPath: str = Field("", max_length=1000)


class LegacyWorkspaceCleanupPayload(BaseModel):
    confirmationPhrase: str = Field("", max_length=80)


@router.get("/storage/workspace-migration/status")
def workspace_migration_status() -> dict:
    return get_workspace_migration_status()


@router.post("/storage/workspace-migration/preview")
def workspace_migration_preview(_: WorkspaceMigrationPayload | None = None) -> dict:
    return preview_workspace_migration()


@router.post("/storage/workspace-migration/apply")
def workspace_migration_apply(payload: WorkspaceMigrationPayload | None = None) -> dict:
    try:
        return apply_workspace_migration(report_path=(payload.reportPath if payload else ""))
    except WorkspaceDataMigrationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/storage/workspace-migration/verify")
def workspace_migration_verify(payload: WorkspaceMigrationPayload | None = None) -> dict:
    return verify_workspace_migration(report_path=(payload.reportPath if payload else ""))


@router.post("/storage/legacy-workspace/cleanup-preview")
def legacy_workspace_cleanup_preview() -> dict:
    return preview_legacy_workspace_cleanup()


@router.post("/storage/legacy-workspace/cleanup-execute")
def legacy_workspace_cleanup_execute(payload: LegacyWorkspaceCleanupPayload) -> dict:
    try:
        return execute_legacy_workspace_cleanup(confirmation_phrase=payload.confirmationPhrase)
    except WorkspaceDataMigrationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
