"""Team template JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.team_template_models import (
    TeamTemplateDetailResponse,
    TeamTemplateInstantiateResponse,
    TeamTemplateListResponse,
)


def test_team_template_models_publish_known_schema_fields() -> None:
    expected_properties = {
        TeamTemplateListResponse: {"schemaVersion", "templates", "summary", "updatedAt"},
        TeamTemplateDetailResponse: {
            "templateId",
            "name",
            "description",
            "purpose",
            "defaultTeamName",
            "safetyLevel",
            "memberIdPrefix",
            "agentMetadata",
            "chatRoom",
            "canvas",
            "roles",
        },
        TeamTemplateInstantiateResponse: {
            "schemaVersion",
            "template",
            "team",
            "createdAgents",
            "linkedChatRoom",
            "updatedAt",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_team_template_models_keep_unknown_fields() -> None:
    payload = TeamTemplateDetailResponse.model_validate(
        {
            "templateId": "medical-consultation-demo",
            "name": "医疗问诊",
            "roles": [{"role": "问诊主持 / 结果整理"}],
        }
    ).model_dump()

    assert payload["roles"] == [{"role": "问诊主持 / 结果整理"}]
    listed = TeamTemplateListResponse.model_validate(
        {
            "schemaVersion": 1,
            "templates": [{"templateId": "medical-consultation-demo", "chatRoom": {"mode": "round_robin"}}],
            "summary": {"templateCount": 1},
            "updatedAt": "2026-08-16T00:00:00Z",
        }
    ).model_dump()
    assert listed["templates"][0]["chatRoom"] == {"mode": "round_robin"}


def test_team_template_models_keep_unknown_fields_without_injecting_defaults() -> None:
    payload = TeamTemplateInstantiateResponse.model_validate(
        {
            "schemaVersion": 1,
            "template": {"templateId": "medical-consultation-demo"},
            "futureHint": {"owner": "templates"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "schemaVersion": 1,
        "template": {"templateId": "medical-consultation-demo"},
        "futureHint": {"owner": "templates"},
    }
