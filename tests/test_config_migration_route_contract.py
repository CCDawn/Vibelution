"""Config migration response contract regressions."""

from __future__ import annotations

from core.web.routes.config_migration_models import (
    ConfigMigrationApplyResponse,
    ConfigMigrationPreviewResponse,
    ConfigProviderMergePreviewResponse,
    ConfigProviderMergeResultResponse,
)


def test_config_migration_response_models_publish_known_schema_fields() -> None:
    expected_properties = {
        ConfigMigrationPreviewResponse: {
            "previewId",
            "baseHash",
            "status",
            "providers",
            "modelRefMap",
            "referenceImpact",
            "conflicts",
        },
        ConfigMigrationApplyResponse: {
            "migrationId",
            "status",
            "hash",
            "modelAliasUsage",
            "updatedReferenceCount",
        },
        ConfigProviderMergePreviewResponse: {
            "previewId",
            "status",
            "baseHash",
            "canonicalProviderId",
            "duplicateProviderIds",
            "modelRefMap",
            "modelsToAdd",
            "liveReferences",
            "historicalReferences",
            "liveReferenceCount",
            "historicalReferenceCount",
            "conflicts",
            "requiredProbeModelRef",
        },
        ConfigProviderMergeResultResponse: {
            "migrationId",
            "status",
            "hash",
            "updatedReferenceCount",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_config_migration_response_models_keep_unknown_fields_without_injecting_defaults() -> None:
    payload = ConfigMigrationApplyResponse.model_validate(
        {
            "migrationId": "migration-1",
            "status": "rolled_back",
            "hash": "hash-1",
            "futureEvidence": {"source": "operator"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "migrationId": "migration-1",
        "status": "rolled_back",
        "hash": "hash-1",
        "futureEvidence": {"source": "operator"},
    }
