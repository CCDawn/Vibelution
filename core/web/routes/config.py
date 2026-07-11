"""Config workspace routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.web.services.avatar_image_service import resolve_user_avatar_file, store_user_avatar_image
from core.web.services.config_service import (
    ConfigConflictError,
    apply_config_workspace,
    draft_add_model,
    draft_check_model_image_input_capabilities,
    draft_delete_model,
    discover_config_models,
    draft_update_model,
    get_config_summary,
    get_config_workspace,
    open_system_environment_settings,
    preview_config_workspace,
    run_draft_llm_test,
    update_intake_mode,
    update_language,
)
from core.web.services.model_reference_service import ModelReferenceConflictError
from core.web.services import provider_config_service
from core.web.services.theme_background_service import (
    resolve_theme_background_file,
    store_theme_background_image,
)


router = APIRouter(tags=["config"])


class IntakeModeUpdateRequest(BaseModel):
    intakeMode: Literal["manual_review", "auto"]


class LanguageUpdateRequest(BaseModel):
    language: Literal["zh", "en"]


class ConfigDraftPayload(BaseModel):
    publicConfig: dict[str, Any] = Field(default_factory=dict)
    baseConfig: dict[str, Any] | None = None
    draftMeta: dict[str, Any] = Field(default_factory=dict)
    baseHash: str = ""


class ConfigProviderDraftPayload(ConfigDraftPayload):
    providerId: str
    provider: dict[str, Any] = Field(default_factory=dict)
    credentialValue: str = ""
    routePreviewToken: str = ""


class ConfigProviderModelPayload(ConfigDraftPayload):
    providerId: str
    upstreamId: str
    modelKey: str = ""
    label: str = ""
    overrides: dict[str, Any] = Field(default_factory=dict)


class ConfigProviderDiscoveryPayload(ConfigDraftPayload):
    providerId: str
    credentialValue: str = ""


class ConfigProviderSuggestionPayload(ConfigDraftPayload):
    provider: dict[str, Any] = Field(default_factory=dict)


class ConfigDraftAddModelPayload(ConfigDraftPayload):
    presetId: str = ""
    modelId: str = ""
    provider: dict[str, Any] = Field(default_factory=dict)
    model: str = ""
    label: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    apiKeyEnv: str = ""
    apiKey: str = ""


class ConfigDraftUpdateModelPayload(ConfigDraftPayload):
    modelId: str = ""
    provider: dict[str, Any] = Field(default_factory=dict)
    model: str = ""
    label: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    apiKeyEnv: str = ""
    apiKey: str = ""
    clearApiKey: bool = False


class ConfigDraftDeleteModelPayload(ConfigDraftPayload):
    modelId: str = ""


class ConfigDraftTestPayload(ConfigDraftPayload):
    modelId: str = ""
    profileId: str = ""
    capability: str = "text"


class ConfigDraftCapabilityPayload(ConfigDraftPayload):
    modelIds: list[str] = Field(default_factory=list)


class ConfigDiscoverModelsPayload(ConfigDraftPayload):
    provider: dict[str, Any] = Field(default_factory=dict)
    modelId: str = ""
    apiKeyEnv: str = ""
    apiKey: str = ""


class ConfigAvatarImagePayload(BaseModel):
    filename: str = ""
    contentType: str = ""
    dataBase64: str = ""


class ConfigThemeBackgroundImagePayload(BaseModel):
    filename: str = ""
    contentType: str = ""
    dataBase64: str = ""


class ConfigMigrationApplyPayload(BaseModel):
    previewId: str = Field(min_length=1)
    baseHash: str = Field(min_length=1)


class ConfigMigrationRollbackPayload(BaseModel):
    migrationId: str = Field(min_length=1)
    baseHash: str = Field(min_length=1)


def _raise_config_http_error(exc: Exception) -> None:
    if isinstance(exc, ModelReferenceConflictError):
        raise HTTPException(
            status_code=409,
            detail=provider_config_service.project_model_reference_impact(
                exc.impact
            ),
        ) from exc
    if isinstance(exc, ConfigConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ValueError) and any(
        token in str(exc).lower()
        for token in ("stale config hash", "hash drift", "live model alias references")
    ):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/config/public")
def public_config_summary() -> dict:
    return get_config_summary()


@router.get("/config/workspace")
def config_workspace() -> dict:
    return get_config_workspace()


@router.post("/config/migration/llm-v2/preview")
def config_llm_v2_migration_preview() -> dict:
    try:
        return provider_config_service.project_llm_v2_migration_preview(
            provider_config_service.preview_llm_v2_migration()
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/migration/llm-v2/apply")
def config_llm_v2_migration_apply(payload: ConfigMigrationApplyPayload) -> dict:
    try:
        return provider_config_service.apply_llm_v2_migration(
            preview_id=payload.previewId,
            base_hash=payload.baseHash,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/migration/llm-v2/{migration_id}/rollback")
def config_llm_v2_migration_rollback(
    migration_id: str,
    payload: ConfigMigrationRollbackPayload,
) -> dict:
    if payload.migrationId != migration_id:
        raise HTTPException(status_code=409, detail="migration id mismatch")
    try:
        return provider_config_service.rollback_llm_v2_migration(
            migration_id=migration_id,
            base_hash=payload.baseHash,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/open-environment")
def config_open_environment() -> dict:
    try:
        return open_system_environment_settings()
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/avatar-image")
def config_upload_avatar_image(payload: ConfigAvatarImagePayload) -> dict:
    try:
        return store_user_avatar_image(
            filename=payload.filename,
            content_type=payload.contentType,
            data_base64=payload.dataBase64,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.get("/config/avatar-image/{filename}")
def config_get_avatar_image(filename: str) -> FileResponse:
    try:
        path = resolve_user_avatar_file(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Avatar image not found") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Avatar image not found")
    return FileResponse(path)


@router.post("/config/theme-background-image")
def config_upload_theme_background_image(payload: ConfigThemeBackgroundImagePayload) -> dict:
    try:
        return store_theme_background_image(
            filename=payload.filename,
            content_type=payload.contentType,
            data_base64=payload.dataBase64,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.get("/config/theme-background-image/{filename}")
def config_get_theme_background_image(filename: str) -> FileResponse:
    try:
        path = resolve_theme_background_file(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Theme background image not found") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Theme background image not found")
    return FileResponse(path)


@router.post("/config/draft/preview")
def config_draft_preview(payload: ConfigDraftPayload) -> dict:
    try:
        return preview_config_workspace(payload.publicConfig, payload.draftMeta, payload.baseHash)
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/draft/providers/id-suggestion")
def config_draft_provider_id_suggestion(
    payload: ConfigProviderSuggestionPayload,
) -> dict:
    try:
        return provider_config_service.suggest_draft_provider_id(
            payload.publicConfig,
            base_hash=payload.baseHash,
            provider=payload.provider,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/draft/providers")
def config_draft_add_provider(payload: ConfigProviderDraftPayload) -> dict:
    try:
        return provider_config_service.project_provider_draft_response(
            provider_config_service.draft_add_provider(
                payload.publicConfig,
                draft_meta=payload.draftMeta,
                base_hash=payload.baseHash,
                provider_id=payload.providerId,
                provider=payload.provider,
                credential_value=payload.credentialValue,
            )
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.put("/config/draft/providers/{provider_id}")
def config_draft_update_provider(
    provider_id: str,
    payload: ConfigProviderDraftPayload,
) -> dict:
    try:
        return provider_config_service.project_provider_draft_response(
            provider_config_service.draft_update_provider(
                payload.publicConfig,
                draft_meta=payload.draftMeta,
                base_hash=payload.baseHash,
                provider_id=provider_id,
                provider=payload.provider,
                credential_value=payload.credentialValue,
                route_preview_token=payload.routePreviewToken,
            )
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.delete("/config/draft/providers/{provider_id}")
def config_draft_delete_provider(
    provider_id: str,
    payload: ConfigProviderDraftPayload,
) -> dict:
    try:
        return provider_config_service.project_provider_draft_response(
            provider_config_service.draft_delete_provider(
                payload.publicConfig,
                draft_meta=payload.draftMeta,
                base_hash=payload.baseHash,
                provider_id=provider_id,
            )
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/draft/providers/{provider_id}/route-preview")
def config_draft_preview_provider_route(
    provider_id: str,
    payload: ConfigProviderDraftPayload,
) -> dict:
    try:
        return provider_config_service.project_provider_route_preview_response(
            provider_config_service.preview_draft_provider_route(
                payload.publicConfig,
                base_hash=payload.baseHash,
                provider_id=provider_id,
                provider=payload.provider,
            )
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/draft/providers/{provider_id}/discover")
def config_draft_discover_provider(
    provider_id: str,
    payload: ConfigProviderDiscoveryPayload,
) -> dict:
    try:
        return provider_config_service.project_provider_draft_response(
            provider_config_service.discover_draft_provider(
                payload.publicConfig,
                draft_meta=payload.draftMeta,
                base_hash=payload.baseHash,
                provider_id=provider_id,
                credential_value=payload.credentialValue,
            )
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/draft/providers/{provider_id}/models")
def config_draft_pin_provider_model(
    provider_id: str,
    payload: ConfigProviderModelPayload,
) -> dict:
    try:
        return provider_config_service.project_provider_draft_response(
            provider_config_service.draft_pin_provider_model(
                payload.publicConfig,
                draft_meta=payload.draftMeta,
                base_hash=payload.baseHash,
                provider_id=provider_id,
                upstream_id=payload.upstreamId,
                model_key=payload.modelKey,
                label=payload.label,
                overrides=payload.overrides,
            )
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.delete("/config/draft/providers/{provider_id}/models/{model_key}")
def config_draft_unpin_provider_model(
    provider_id: str,
    model_key: str,
    payload: ConfigProviderModelPayload,
) -> dict:
    try:
        return provider_config_service.project_provider_draft_response(
            provider_config_service.draft_unpin_provider_model(
                payload.publicConfig,
                draft_meta=payload.draftMeta,
                base_hash=payload.baseHash,
                provider_id=provider_id,
                model_key=model_key,
            )
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/draft/add-model")
def config_draft_add_model(payload: ConfigDraftAddModelPayload) -> dict:
    try:
        return draft_add_model(
            payload.publicConfig,
            draft_meta=payload.draftMeta,
            base_hash=payload.baseHash,
            preset_id=payload.presetId,
            model_id=payload.modelId,
            provider=payload.provider,
            model=payload.model,
            label=payload.label,
            details=payload.details,
            api_key_env=payload.apiKeyEnv,
            api_key=payload.apiKey,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/draft/update-model")
def config_draft_update_model(payload: ConfigDraftUpdateModelPayload) -> dict:
    try:
        return draft_update_model(
            payload.publicConfig,
            draft_meta=payload.draftMeta,
            base_hash=payload.baseHash,
            model_id=payload.modelId,
            provider=payload.provider,
            model=payload.model,
            label=payload.label,
            details=payload.details,
            api_key_env=payload.apiKeyEnv,
            api_key=payload.apiKey,
            clear_api_key=payload.clearApiKey,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/draft/delete-model")
def config_draft_delete_model(payload: ConfigDraftDeleteModelPayload) -> dict:
    try:
        return draft_delete_model(
            payload.publicConfig,
            draft_meta=payload.draftMeta,
            base_hash=payload.baseHash,
            model_id=payload.modelId,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/test-llm")
def config_test_llm(payload: ConfigDraftTestPayload) -> dict:
    try:
        return run_draft_llm_test(
            payload.publicConfig,
            draft_meta=payload.draftMeta,
            model_id=payload.modelId,
            profile_id=payload.profileId,
            capability=payload.capability,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/draft/check-model-capabilities")
def config_draft_check_model_capabilities(payload: ConfigDraftCapabilityPayload) -> dict:
    try:
        return draft_check_model_image_input_capabilities(
            payload.publicConfig,
            draft_meta=payload.draftMeta,
            base_hash=payload.baseHash,
            model_ids=payload.modelIds,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.post("/config/discover-models")
def config_discover_models(payload: ConfigDiscoverModelsPayload) -> dict:
    try:
        return discover_config_models(
            payload.publicConfig,
            draft_meta=payload.draftMeta,
            provider=payload.provider,
            model_id=payload.modelId,
            api_key_env=payload.apiKeyEnv,
            api_key=payload.apiKey,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.put("/config/apply")
def config_apply(payload: ConfigDraftPayload) -> dict:
    try:
        return apply_config_workspace(
            payload.publicConfig,
            base_config=payload.baseConfig,
            draft_meta=payload.draftMeta,
            base_hash=payload.baseHash,
        )
    except Exception as exc:  # pragma: no cover - routed below
        _raise_config_http_error(exc)


@router.put("/config/intake-mode")
def set_intake_mode(payload: IntakeModeUpdateRequest) -> dict:
    return update_intake_mode(payload.intakeMode)


@router.put("/config/language")
def set_language(payload: LanguageUpdateRequest) -> dict:
    return update_language(payload.language)
