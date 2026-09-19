"""Route-level tests for team bundle export / import."""

from __future__ import annotations

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    prompt_template_service,
    session_service,
    team_bundle_service,
    team_service,
)
from tests.helpers.system_agent_state import _mark_config_agent_instances_present

MODEL_ID = "model-primary"


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    for module in (
        agent_directory_service,
        chat_room_service,
        prompt_template_service,
        session_service,
        team_service,
        team_bundle_service,
    ):
        monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        agent_directory_service,
        "_configured_model_library_ids",
        lambda *args, **kwargs: {MODEL_ID},
    )


def _bundle_payload() -> dict:
    return {
        "kind": "vibelution-team-bundle",
        "schemaVersion": 1,
        "team": {
            "name": "路由导入团队",
            "description": "via api",
            "purpose": "route test",
            "members": [
                {"bundleAgentKey": "a", "role": "调研", "purpose": "p", "responsibilities": []},
            ],
            "chatRoom": {"mode": "round_robin", "purpose": "meeting"},
        },
        "agents": [
            {
                "bundleAgentKey": "a",
                "displayName": "调研",
                "llmBindings": {"dialogue": {"modelId": MODEL_ID}},
            },
        ],
    }


def test_export_unknown_team_returns_404(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _mark_config_agent_instances_present()

    response = _client().get("/api/teams/does-not-exist/bundle")

    assert response.status_code == 404, response.text


def test_import_route_dry_run_then_execute(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _mark_config_agent_instances_present()
    client = _client()

    preview = client.post("/api/team-bundles/import", json={"bundle": _bundle_payload(), "dryRun": True})
    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] == "ready"
    assert preview.json()["agents"]["create"] == ["调研"]

    executed = client.post("/api/team-bundles/import", json={"bundle": _bundle_payload(), "dryRun": False})
    assert executed.status_code == 200, executed.text
    body = executed.json()
    assert body["status"] == "completed"
    assert body["result"]["teamId"]

    exported = client.get(f"/api/teams/{body['result']['teamId']}/bundle")
    assert exported.status_code == 200, exported.text
    assert exported.json()["team"]["name"] == "路由导入团队"


def test_import_route_rejects_unsupported_kind(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _mark_config_agent_instances_present()
    payload = _bundle_payload()
    payload["kind"] = "something-else"

    response = _client().post("/api/team-bundles/import", json={"bundle": payload, "dryRun": True})

    assert response.status_code == 422, response.text
