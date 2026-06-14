from __future__ import annotations

import copy
import json

import pytest
from fastapi import HTTPException

from config.public_config import UNCONFIGURED_MODEL_REF, load_public_config, public_config_hash
from core.web.routes import config as config_routes
from core.web.services import config_service
from core.web.services import model_reference_service
from core.web.services.model_reference_service import (
    ModelReferenceConflictError,
    assert_model_delete_safe,
    rebind_model_references,
    scan_model_references,
)

pytestmark = pytest.mark.serial


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _public_config_with_refs(model_id: str, other_model_id: str = "model-b") -> dict:
    return {
        "llm": {
            "profiles": {
                "primary": {"model_ref": model_id, "overrides": {}},
                "other": {"model_ref": other_model_id, "overrides": {}},
            }
        },
        "tools": {"image2": {"default_model_ref": model_id}},
        "git": {"commit_message_model_ref": model_id},
    }


def _seed_agent_registry(root, model_id: str, other_model_id: str = "model-b") -> None:
    _write_json(
        root / "workspace" / "agents" / "agents.json",
        {
            "version": 1,
            "agents": [
                {
                    "agentId": "agent-a",
                    "displayName": "Agent A",
                    "dialogueModelId": model_id,
                    "agentTemplateLabel": model_id,
                    "llmBindings": {
                        "dialogue": {"modelId": model_id},
                        "summary": {"modelId": other_model_id},
                    },
                }
            ],
        },
    )


def _seed_chat_rooms(root, model_id: str) -> None:
    _write_json(
        root / "workspace" / "chat_rooms" / "chat_rooms.json",
        {
            "rooms": [
                {
                    "roomId": "room-a",
                    "participants": [
                        {
                            "participantId": "participant-a",
                            "title": "Participant A",
                            "dialogueModelId": model_id,
                            "agentTemplateLabel": model_id,
                            "llmBindings": {"dialogue": {"modelId": model_id}},
                        }
                    ],
                }
            ]
        },
    )


def test_scan_model_references_reports_live_and_historical_sources(tmp_path):
    model_id = "model-a"
    _seed_agent_registry(tmp_path, model_id)
    _seed_chat_rooms(tmp_path, model_id)
    _write_json(
        tmp_path / ".runtime" / "runtime-manager" / "work_runs" / "supervised" / "index.json",
        {"activeRunId": "run-a"},
    )
    _write_json(
        tmp_path / ".runtime" / "runtime-manager" / "work_runs" / "supervised" / "runs" / "run-a.json",
        {
            "runId": "run-a",
            "status": "running",
            "currentAgentBinding": {"dialogueModelId": model_id, "llmBindings": {"dialogue": {"modelId": model_id}}},
            "agentBindings": {
                "baseline": {"dialogueModelId": model_id, "llmBindings": {"dialogue": {"modelId": model_id}}}
            },
        },
    )
    _write_json(
        tmp_path / "workspace" / "supervised_evolution" / "decisions" / "decision-a.json",
        {"agent_bindings": {"baseline": {"dialogueModelId": model_id}}},
    )

    impact = scan_model_references(model_id, public_config=_public_config_with_refs(model_id), project_root=tmp_path)

    assert impact["blocking"] is True
    assert impact["liveReferenceCount"] >= 8
    assert impact["historicalReferenceCount"] == 1
    assert {item["source"] for item in impact["liveReferences"]} >= {
        "public_config",
        "agent_registry",
        "chat_room_registry",
        "active_supervised_run",
    }
    assert impact["historicalReferences"][0]["source"] == "supervised_decision"
    with pytest.raises(ModelReferenceConflictError) as exc_info:
        assert_model_delete_safe(model_id, public_config=_public_config_with_refs(model_id), project_root=tmp_path)
    assert exc_info.value.impact["liveReferenceCount"] == impact["liveReferenceCount"]


def test_rebind_model_references_updates_live_sources_without_rewriting_history(tmp_path):
    _seed_agent_registry(tmp_path, "model-a")
    _seed_chat_rooms(tmp_path, "model-a")
    decision_path = tmp_path / "workspace" / "supervised_evolution" / "decisions" / "decision-a.json"
    _write_json(decision_path, {"agent_bindings": {"baseline": {"dialogueModelId": "model-a"}}})

    result = rebind_model_references(
        "model-a",
        "model-b",
        public_config=_public_config_with_refs("model-a"),
        project_root=tmp_path,
    )

    assert result["updatedReferenceCount"] >= 8
    assert result["impactBefore"]["liveReferenceCount"] >= 8
    assert result["impactAfter"]["liveReferenceCount"] == 0
    assert result["impactAfter"]["historicalReferenceCount"] == 1
    assert result["publicConfig"]["llm"]["profiles"]["primary"]["model_ref"] == "model-b"
    assert result["publicConfig"]["tools"]["image2"]["default_model_ref"] == "model-b"
    assert result["publicConfig"]["git"]["commit_message_model_ref"] == "model-b"

    agents = json.loads((tmp_path / "workspace" / "agents" / "agents.json").read_text(encoding="utf-8"))
    assert agents["agents"][0]["dialogueModelId"] == "model-b"
    assert agents["agents"][0]["agentTemplateLabel"] == "model-b"
    assert agents["agents"][0]["llmBindings"]["dialogue"]["modelId"] == "model-b"
    rooms = json.loads((tmp_path / "workspace" / "chat_rooms" / "chat_rooms.json").read_text(encoding="utf-8"))
    participant = rooms["rooms"][0]["participants"][0]
    assert participant["dialogueModelId"] == "model-b"
    assert participant["agentTemplateLabel"] == "model-b"
    assert participant["llmBindings"]["dialogue"]["modelId"] == "model-b"
    assert "model-a" in decision_path.read_text(encoding="utf-8")


def test_scan_can_ignore_public_config_refs_for_workspace_guard(tmp_path):
    impact = scan_model_references(
        "model-a",
        public_config=_public_config_with_refs("model-a"),
        project_root=tmp_path,
        include_public_config=False,
    )

    assert impact["blocking"] is False
    assert impact["liveReferences"] == []


def test_draft_delete_model_blocks_workspace_agent_reference(tmp_path, monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["model_a"] = copy.deepcopy(
        public_config["llm"]["model_library"]["relay_openai_gpt_5_5"]
    )
    _seed_agent_registry(tmp_path, "model_a")
    scene_events = []

    monkeypatch.setattr(model_reference_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
    )

    with pytest.raises(ModelReferenceConflictError) as exc_info:
        config_service.draft_delete_model(public_config, model_id="model_a")

    assert exc_info.value.impact["liveReferenceCount"] >= 1
    assert all(item["source"] == "agent_registry" for item in exc_info.value.impact["liveReferences"])
    assert scene_events[-1][1] == "config.model_delete.blocked"


def test_draft_delete_model_keeps_non_primary_profile_unconfigured(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["model_a"] = copy.deepcopy(
        public_config["llm"]["model_library"]["relay_openai_gpt_5_5"]
    )
    public_config["llm"]["profiles"]["mental_model"]["model_ref"] = "model_a"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    payload = config_service.draft_delete_model(public_config, model_id="model_a")

    assert "model_a" not in payload["publicConfig"]["llm"]["model_library"]
    assert payload["publicConfig"]["llm"]["profiles"]["mental_model"]["model_ref"] == UNCONFIGURED_MODEL_REF


def test_apply_config_workspace_blocks_removed_model_with_workspace_reference(tmp_path, monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["model_a"] = copy.deepcopy(
        public_config["llm"]["model_library"]["relay_openai_gpt_5_5"]
    )
    submitted = copy.deepcopy(public_config)
    submitted["llm"]["model_library"].pop("model_a", None)
    _seed_agent_registry(tmp_path, "model_a")

    monkeypatch.setattr(model_reference_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    with pytest.raises(ModelReferenceConflictError) as exc_info:
        config_service.apply_config_workspace(
            submitted,
            base_config=public_config,
            base_hash=public_config_hash(public_config),
        )

    assert exc_info.value.impact["blocking"] is True
    assert {item["source"] for item in exc_info.value.impact["liveReferences"]} == {"agent_registry"}


def test_config_route_maps_model_reference_conflict_to_conflict_response():
    impact = {
        "modelId": "model-a",
        "liveReferenceCount": 1,
        "historicalReferenceCount": 0,
        "liveReferences": [{"source": "agent_registry"}],
        "historicalReferences": [],
        "blocking": True,
    }

    with pytest.raises(HTTPException) as exc_info:
        config_routes._raise_config_http_error(ModelReferenceConflictError(impact))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == impact
