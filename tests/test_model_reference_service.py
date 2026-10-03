from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from config.public_config import UNCONFIGURED_MODEL_REF, load_public_config, public_config_hash
from core.web.routes import config as config_routes
from core.web.services import config_service
from core.web.services import model_reference_service
from core.web.services.model_reference_service import (
    ModelReferenceConflictError,
    apply_model_reference_rewrite_plan,
    assert_model_delete_safe,
    build_model_reference_rewrite_plan,
    rebind_model_references,
    rewrite_model_reference_payload,
    scan_model_alias_usage,
    scan_model_references,
    scan_provider_live_references,
)
from core.web.services.session.directory_runtime import conversation_store_path

@pytest.fixture(autouse=True)
def _isolate_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))


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


def _schema_v1_public_config() -> dict:
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "config"
        / "llm_schema_v1_inline.toml"
    )
    return load_public_config(fixture)


@pytest.mark.parametrize(
    ("owner_kind", "payload", "expected_count"),
    [
        (
            "public_config",
            {
                "llm": {"profiles": {"primary": {"model_ref": "legacy_model"}}},
                "tools": {"image2": {"default_model_ref": "legacy_model"}},
                "git": {"commit_message_model_ref": "legacy_model"},
            },
            3,
        ),
        (
            "agent_registry",
            {"agents": [{"dialogueModelId": "legacy_model", "llmBindings": {"dialogue": {"modelId": "legacy_model"}}}]},
            2,
        ),
        (
            "chat_room_registry",
            {"rooms": [{"participants": [{"dialogueModelId": "legacy_model", "llmBindings": {"vision": {"modelId": "legacy_model"}}}]}]},
            2,
        ),
        (
            "active_supervised_run",
            {"status": "running", "currentAgentBinding": {"modelId": "legacy_model"}, "agentBindings": {"baseline": {"modelId": "legacy_model"}}},
            2,
        ),
        ("team_live_prompt_cache_policy", {"promptCachePolicy": {"modelId": "legacy_model"}}, 1),
    ],
)
def test_known_live_reference_payloads_rewrite_only_owned_model_fields(owner_kind, payload, expected_count) -> None:
    updated, references = rewrite_model_reference_payload(owner_kind, payload, {"legacy_model": "relay/gpt-a"})
    assert json.dumps(updated).count("relay/gpt-a") == expected_count
    assert len(references) == expected_count


def test_historical_payload_is_never_rewritten() -> None:
    payload = {"decision": {"modelId": "legacy_model"}}
    updated, references = rewrite_model_reference_payload(
        "historical_supervised_artifact", payload, {"legacy_model": "relay/gpt-a"}
    )
    assert updated == payload
    assert references == ()


def test_unknown_reference_owner_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown model reference owner"):
        rewrite_model_reference_payload("plugin_payload", {"modelId": "legacy_model"}, {"legacy_model": "relay/gpt-a"})


def test_historical_alias_usage_is_reported_but_does_not_block_exit(tmp_path) -> None:
    decision_path = tmp_path / "workspace" / "supervised_evolution" / "decisions" / "decision-a.json"
    _write_json(decision_path, {"modelId": "legacy_model"})
    usage = scan_model_alias_usage(
        {"llm": {"model_aliases": {"legacy_model": "relay/gpt-a"}}},
        project_root=tmp_path,
    )
    assert usage["totalLiveReferenceCount"] == 0
    assert usage["totalHistoricalReferenceCount"] == 1
    assert usage["canRemoveAliases"] is True


def test_scan_model_alias_usage_yields_gil_between_chunks(tmp_path, monkeypatch) -> None:
    alias_ids = ["legacy-a", "legacy-b"]
    decisions_root = tmp_path / "workspace" / "supervised_evolution" / "decisions"
    for index in range(30):
        _write_json(
            decisions_root / f"decision-{index:02d}.json",
            {"modelId": alias_ids[index % 2]},
        )
    alias_config = {"llm": {"model_aliases": {alias: "relay/gpt-a" for alias in alias_ids}}}

    baseline = scan_model_alias_usage(alias_config, project_root=tmp_path)
    assert baseline["totalHistoricalReferenceCount"] == 30
    assert [item["historicalReferenceCount"] for item in baseline["aliases"]] == [15, 15]

    real_sleep = model_reference_service.time.sleep
    sleep_calls: list[float] = []

    def _counting_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        real_sleep(seconds)

    monkeypatch.setattr(model_reference_service.time, "sleep", _counting_sleep)
    yielded = scan_model_alias_usage(alias_config, project_root=tmp_path)

    assert len(sleep_calls) >= 1
    assert all(seconds == 0 for seconds in sleep_calls)
    assert yielded == baseline


@pytest.mark.parametrize(
    "status",
    ["", "queued", "stopping", "started", "in_progress", "unknown", "completed", "failed", "cancelled"],
)
def test_rewrite_plan_treats_non_writable_indexed_run_as_historical(tmp_path, status) -> None:
    index_path = tmp_path / ".runtime" / "runtime-manager" / "work_runs" / "supervised" / "index.json"
    run_path = index_path.parent / "runs" / "run-old.json"
    _write_json(index_path, {"activeRunId": "run-old"})
    _write_json(
        run_path,
        {
            "runId": "run-old",
            "status": status,
            "currentAgentBinding": {"modelId": "legacy_model"},
        },
    )
    before = run_path.read_bytes()

    plan = build_model_reference_rewrite_plan(
        {"legacy_model": "relay/gpt-a"},
        public_config={"llm": {"profiles": {}}},
        project_root=tmp_path,
    )

    assert all(rewrite.path != run_path for rewrite in plan.file_rewrites)
    assert {item["source"] for item in plan.historical_references} == {"historical_supervised_run"}
    result = apply_model_reference_rewrite_plan(plan)
    assert result["updatedReferenceCount"] == 0
    assert run_path.read_bytes() == before
    general_impact = scan_model_references("legacy_model", project_root=tmp_path)
    if status in {"", "queued", "stopping", "started", "in_progress"}:
        assert general_impact["liveReferenceCount"] == 1


@pytest.mark.parametrize("status", ["active", "running", "paused"])
def test_rewrite_plan_accepts_only_live_indexed_run_candidates(tmp_path, status) -> None:
    index_path = tmp_path / ".runtime" / "runtime-manager" / "work_runs" / "supervised" / "index.json"
    run_path = index_path.parent / "runs" / "run-live.json"
    _write_json(index_path, {"activeRunId": "run-live"})
    _write_json(
        run_path,
        {
            "runId": "run-live",
            "status": status,
            "currentAgentBinding": {"modelId": "legacy_model"},
        },
    )

    plan = build_model_reference_rewrite_plan(
        {"legacy_model": "relay/gpt-a"},
        public_config={"llm": {"profiles": {}}},
        project_root=tmp_path,
    )

    assert [rewrite.path for rewrite in plan.file_rewrites] == [run_path]
    result = apply_model_reference_rewrite_plan(plan)
    assert result["updatedReferenceCount"] == 1
    assert "relay/gpt-a" in run_path.read_text(encoding="utf-8")


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


def _seed_agent_store(project_root, *, dialogue_model_id: str, stale_dialogue_model_id: str) -> Path:
    """Create a conversations.sqlite3 whose agent carries two config revisions."""
    db_path = conversation_store_path(Path(project_root))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE agents (
              agent_id TEXT PRIMARY KEY,
              display_name TEXT NOT NULL,
              kind TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              current_config_revision_id TEXT,
              created_at_ms INTEGER NOT NULL,
              updated_at_ms INTEGER NOT NULL,
              archived_at_ms INTEGER
            );
            CREATE TABLE agent_config_revisions (
              revision_id TEXT PRIMARY KEY,
              agent_id TEXT NOT NULL,
              config_hash TEXT NOT NULL,
              config_json TEXT NOT NULL,
              source TEXT NOT NULL,
              created_at_ms INTEGER NOT NULL
            );
            """
        )
        now_ms = 1_700_000_000_000
        connection.execute(
            "INSERT INTO agents (agent_id, display_name, kind, status, created_at_ms, updated_at_ms)"
            " VALUES ('agent-store', 'Store Agent', 'chat', 'active', ?, ?)",
            (now_ms, now_ms),
        )
        latest_config = {
            "dialogueModelId": dialogue_model_id,
            "llmBindings": {"dialogue": {"modelId": dialogue_model_id}},
        }
        stale_config = {
            "dialogueModelId": stale_dialogue_model_id,
            "llmBindings": {"dialogue": {"modelId": stale_dialogue_model_id}},
        }
        for revision_id, config_json, created_at_ms in (
            ("agent-store:stale", stale_config, now_ms),
            ("agent-store:latest", latest_config, now_ms + 1),
        ):
            connection.execute(
                "INSERT INTO agent_config_revisions"
                " (revision_id, agent_id, config_hash, config_json, source, created_at_ms)"
                " VALUES (?, 'agent-store', 'hash', ?, 'test', ?)",
                (revision_id, json.dumps(config_json), created_at_ms),
            )
        connection.commit()
    finally:
        connection.close()
    return db_path


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


def test_rebind_agent_registry_persists_through_surface_gate(tmp_path, monkeypatch):
    _seed_agent_registry(tmp_path, "model-a")
    from core.web.services.agent_directory import ops_residual

    calls: list[dict] = []
    original = ops_residual.save_registry_payload

    def _spy(payload, **kwargs):
        calls.append({"payload": payload, **kwargs})
        return original(payload, **kwargs)

    monkeypatch.setattr(ops_residual, "save_registry_payload", _spy)

    result = rebind_model_references("model-a", "model-b", project_root=tmp_path)

    assert result["updatedReferenceCount"] == 3
    assert len(calls) == 1
    assert calls[0]["project_root"] == tmp_path
    registry_path = tmp_path / "workspace" / "agents" / "agents.json"
    assert list(tmp_path.rglob("agents.json")) == [registry_path]
    agents = json.loads(registry_path.read_text(encoding="utf-8"))
    assert agents["agents"][0]["dialogueModelId"] == "model-b"
    assert agents["agents"][0]["agentTemplateLabel"] == "model-b"
    assert agents["agents"][0]["llmBindings"]["dialogue"]["modelId"] == "model-b"
    assert agents["agents"][0]["llmBindings"]["summary"]["modelId"] == "model-b"


def test_rebind_detached_registry_copy_stays_atomic_without_surface_lock(tmp_path, monkeypatch):
    _seed_agent_registry(tmp_path, "model-a")
    from core.web.services.agent_directory import ops_residual

    surface_calls: list[dict] = []
    monkeypatch.setattr(
        ops_residual,
        "save_registry_payload",
        lambda payload, **kwargs: surface_calls.append({"payload": payload, **kwargs}),
    )
    monkeypatch.setattr(
        ops_residual,
        "registry_path",
        lambda *, project_root=None: tmp_path / "elsewhere" / "agents.json",
    )

    result = rebind_model_references("model-a", "model-b", project_root=tmp_path)

    assert result["updatedReferenceCount"] == 3
    assert surface_calls == []
    agents = json.loads(
        (tmp_path / "workspace" / "agents" / "agents.json").read_text(encoding="utf-8")
    )
    assert agents["agents"][0]["dialogueModelId"] == "model-b"


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
    public_config = _schema_v1_public_config()
    public_config["llm"]["model_library"]["model_a"] = copy.deepcopy(
        public_config["llm"]["model_library"]["relay_text"]
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
    public_config = _schema_v1_public_config()
    public_config["llm"]["model_library"]["model_a"] = copy.deepcopy(
        public_config["llm"]["model_library"]["relay_text"]
    )
    public_config["llm"]["profiles"]["mental_model"] = {
        "model_ref": "model_a",
        "overrides": {},
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    payload = config_service.draft_delete_model(public_config, model_id="model_a")

    assert "model_a" not in payload["publicConfig"]["llm"]["model_library"]
    assert payload["publicConfig"]["llm"]["profiles"]["mental_model"]["model_ref"] == UNCONFIGURED_MODEL_REF


def test_apply_config_workspace_blocks_removed_model_with_workspace_reference(tmp_path, monkeypatch):
    public_config = _schema_v1_public_config()
    public_config["llm"]["model_library"]["model_a"] = copy.deepcopy(
        public_config["llm"]["model_library"]["relay_text"]
    )
    base_config = config_service._with_config_workspace_defaults(public_config)
    submitted = copy.deepcopy(base_config)
    submitted["llm"]["model_library"].pop("model_a", None)
    _seed_agent_registry(tmp_path, "model_a")

    monkeypatch.setattr(model_reference_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    with pytest.raises(ModelReferenceConflictError) as exc_info:
        config_service.apply_config_workspace(
            submitted,
            base_config=base_config,
            base_hash=public_config_hash(base_config),
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


def test_scan_model_references_reads_sqlite_agent_store_bindings(tmp_path):
    _seed_agent_store(tmp_path, dialogue_model_id="model-store", stale_dialogue_model_id="model-stale")

    impact = scan_model_references("model-store", project_root=tmp_path)

    assert impact["blocking"] is True
    store_refs = [item for item in impact["liveReferences"] if item["source"] == "agent_store"]
    assert {item["field"] for item in store_refs} == {"dialogueModelId", "llmBindings.dialogue.modelId"}
    assert all(item["ownerType"] == "agent" for item in store_refs)
    assert all(item["ownerId"] == "agent-store" for item in store_refs)
    assert all(item["label"] == "Store Agent" for item in store_refs)

    # Only the latest revision (max created_at_ms) counts as live: the stale
    # revision's binding must not block deleting model-stale.
    stale_impact = scan_model_references("model-stale", project_root=tmp_path)
    assert stale_impact["liveReferences"] == []


def test_scan_model_references_survives_missing_agent_store(tmp_path):
    impact = scan_model_references("model-store", project_root=tmp_path)
    assert impact["blocking"] is False
    assert impact["liveReferences"] == []


def test_scan_provider_live_references_matches_provider_prefix_across_agent_store(tmp_path):
    _seed_agent_store(
        tmp_path,
        dialogue_model_id="opencode_go/deepseek-v4.1-flash",
        stale_dialogue_model_id="relay_dead/legacy-model",
    )

    impact = scan_provider_live_references("opencode_go", project_root=tmp_path)

    assert impact["blocking"] is True
    assert impact["liveReferenceCount"] == 2
    assert {item["field"] for item in impact["liveReferences"]} == {
        "dialogueModelId",
        "llmBindings.dialogue.modelId",
    }

    other = scan_provider_live_references("other_provider", project_root=tmp_path)
    assert other["blocking"] is False
    assert other["liveReferences"] == []
