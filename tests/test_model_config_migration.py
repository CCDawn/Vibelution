from __future__ import annotations

import json

import pytest

from config.model_config_migration import apply_v1_to_v2, preview_v1_to_v2, rollback_v1_to_v2
from config.public_config import public_config_hash
from config.toml_writer import dumps_public_config


def legacy_config_with_models(*rows: tuple[str, str, str, str]) -> dict:
    model_library: dict[str, dict] = {}
    profiles: dict[str, dict] = {}
    for index, (model_id, base_url, api_key_env, upstream_id) in enumerate(rows):
        model_library[model_id] = {
            "provider": {
                "kind": "relay" if model_id.startswith("relay") else "openai_compatible",
                "base_url": base_url,
                "api_key_env": api_key_env,
                "compat_mode": "openai",
                "requires_api_key": bool(api_key_env),
            },
            "model": upstream_id,
            "label": upstream_id,
            "transport": "chat_completions",
            "contract": "tool_chat",
            "timeout": 60,
        }
        profiles["primary" if index == 0 else f"profile_{index}"] = {"model_ref": model_id}
    first_model_id = rows[0][0] if rows else ""
    return {
        "llm": {"model_library": model_library, "profiles": profiles},
        "tools": {"image2": {"default_model_ref": first_model_id}},
        "git": {"commit_message_model_ref": first_model_id},
    }


def write_migration_fixture(tmp_path) -> tuple:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    config_path = tmp_path / "operator" / "config.toml"
    config_path.parent.mkdir()
    legacy = legacy_config_with_models(
        ("relay_a", "https://relay.example/v1", "VIBELUTION_LLM_MODEL_RELAY_A_API_KEY", "gpt-a"),
    )
    config_path.write_text(dumps_public_config(legacy), encoding="utf-8")
    return config_path, project_root, legacy


def test_preview_groups_same_endpoint_and_credential_without_writing(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[llm]\n", encoding="utf-8")
    legacy = legacy_config_with_models(
        ("relay_text", "https://relay.example/v1", "RELAY_KEY", "gpt-a"),
        ("relay_image", "https://relay.example/v1", "RELAY_KEY", "image-a"),
    )
    before = config_path.read_text(encoding="utf-8")
    preview = preview_v1_to_v2(legacy, project_root=tmp_path)
    assert len(preview.providers) == 1
    assert set(preview.model_ref_map) == {"relay_text", "relay_image"}
    assert config_path.read_text(encoding="utf-8") == before


def test_preview_splits_same_endpoint_with_different_credentials(tmp_path) -> None:
    legacy = legacy_config_with_models(
        ("relay_a", "https://relay.example/v1", "RELAY_A_KEY", "gpt-a"),
        ("relay_b", "https://relay.example/v1", "RELAY_B_KEY", "gpt-a"),
    )
    preview = preview_v1_to_v2(legacy, project_root=tmp_path)
    assert len(preview.providers) == 2


def test_missing_credential_source_requires_review(tmp_path) -> None:
    legacy = legacy_config_with_models(("relay_a", "https://relay.example/v1", "", "gpt-a"))
    preview = preview_v1_to_v2(legacy, project_root=tmp_path)
    assert preview.status == "NEEDS_REVIEW"
    assert preview.conflicts[0]["code"] == "credential_source_missing"


def test_preview_strips_only_adapter_confirmed_protocol_route(tmp_path) -> None:
    legacy = legacy_config_with_models(
        ("relay_a", "https://relay.example/v1/responses", "RELAY_A_KEY", "gpt-a"),
    )
    legacy["llm"]["model_library"]["relay_a"]["transport"] = "responses"
    preview = preview_v1_to_v2(legacy, project_root=tmp_path)
    assert preview.providers[0]["base_url"] == "https://relay.example/v1"
    custom = legacy_config_with_models(
        ("custom_a", "https://custom.example/gateway/responses", "CUSTOM_KEY", "gpt-a"),
    )
    custom["llm"]["model_library"]["custom_a"]["provider"]["compat_mode"] = "custom"
    custom_preview = preview_v1_to_v2(custom, project_root=tmp_path)
    assert custom_preview.providers[0]["base_url"] == "https://custom.example/gateway/responses"


def test_apply_rejects_stale_hash_without_writes(tmp_path) -> None:
    config_path, project_root, legacy = write_migration_fixture(tmp_path)
    preview = preview_v1_to_v2(legacy, project_root=project_root)
    with pytest.raises(ValueError, match="stale config hash"):
        apply_v1_to_v2(
            preview.preview_id,
            expected_base_hash="stale",
            config_path=config_path,
            project_root=project_root,
        )
    assert "schema_version = 2" not in config_path.read_text(encoding="utf-8")


def test_apply_writes_aliases_and_rolls_back_all_staged_files_on_failure(tmp_path, monkeypatch) -> None:
    config_path, project_root, legacy = write_migration_fixture(tmp_path)
    preview = preview_v1_to_v2(legacy, project_root=project_root)
    monkeypatch.setattr(
        "config.model_config_migration.reload_config",
        lambda path: (_ for _ in ()).throw(RuntimeError("reload failed")),
    )
    with pytest.raises(RuntimeError, match="reload failed"):
        apply_v1_to_v2(
            preview.preview_id,
            expected_base_hash=public_config_hash(legacy),
            config_path=config_path,
            project_root=project_root,
        )
    assert "schema_version = 2" not in config_path.read_text(encoding="utf-8")
    manifests = list((config_path.parent / "backups").glob("llm-config-migration-*.json"))
    assert manifests
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["status"] == "rolled_back"
    assert "secret" not in json.dumps(manifest).lower()


def test_preview_is_stable_and_does_not_create_files(tmp_path) -> None:
    legacy = legacy_config_with_models(
        ("relay_b", "https://relay.example/v1", "RELAY_KEY", "gpt-b"),
        ("relay_a", "https://relay.example/v1", "RELAY_KEY", "gpt-a"),
    )
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    first = preview_v1_to_v2(legacy, project_root=tmp_path)
    second = preview_v1_to_v2(legacy, project_root=tmp_path)
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert first.preview_id == second.preview_id
    assert first.providers == second.providers
    assert first.model_ref_map == second.model_ref_map
    assert before == after


@pytest.mark.parametrize("model", [r"C:\\models\\large.gguf", "weights.safetensors", "model.bin"])
def test_preview_rejects_suspected_artifact_paths(tmp_path, model) -> None:
    legacy = legacy_config_with_models(("relay_a", "https://relay.example/v1", "RELAY_KEY", model))
    preview = preview_v1_to_v2(legacy, project_root=tmp_path)
    assert preview.status == "NEEDS_REVIEW"
    assert preview.conflicts[0]["code"] == "artifact_path_suspected"
    assert "relay_a" not in preview.model_ref_map


def test_preview_moves_profile_fields_to_overrides(tmp_path) -> None:
    legacy = legacy_config_with_models(("relay_a", "https://relay.example/v1", "RELAY_KEY", "gpt-a"))
    legacy["llm"]["profiles"]["primary"]["temperature"] = 0.2
    preview = preview_v1_to_v2(legacy, project_root=tmp_path)
    profile = preview.proposed_public_config["llm"]["profiles"]["primary"]
    assert profile["overrides"]["temperature"] == 0.2
    assert "temperature" not in profile


def test_preview_reports_behavioral_defaults_conflict_without_values(tmp_path) -> None:
    legacy = legacy_config_with_models(
        ("relay_a", "https://relay.example/v1", "RELAY_KEY", "gpt-a"),
        ("relay_b", "https://relay.example/v1", "RELAY_KEY", "gpt-a"),
    )
    legacy["llm"]["model_library"]["relay_b"]["timeout"] = 120
    preview = preview_v1_to_v2(legacy, project_root=tmp_path)
    conflict = next(item for item in preview.conflicts if item["code"] == "model_defaults_conflict")
    assert preview.status == "NEEDS_REVIEW"
    assert conflict["fields"] == ["defaults"]
    assert "60" not in json.dumps(conflict)
    assert "120" not in json.dumps(conflict)


def test_apply_and_manual_rollback_restore_config_and_live_reference(tmp_path, monkeypatch) -> None:
    config_path, project_root, legacy = write_migration_fixture(tmp_path)
    agent_path = project_root / "workspace" / "agents" / "agents.json"
    agent_path.parent.mkdir(parents=True)
    agent_path.write_text(
        json.dumps({"agents": [{"agentId": "agent-a", "dialogueModelId": "relay_a"}]}) + "\n",
        encoding="utf-8",
    )
    before_config = config_path.read_bytes()
    before_agent = agent_path.read_bytes()
    monkeypatch.setattr("config.model_config_migration.reload_config", lambda path: object())
    preview = preview_v1_to_v2(legacy, project_root=project_root)
    applied = apply_v1_to_v2(
        preview.preview_id,
        expected_base_hash=public_config_hash(legacy),
        config_path=config_path,
        project_root=project_root,
    )
    assert applied["status"] == "applied"
    assert "schema_version = 2" in config_path.read_text(encoding="utf-8")
    assert "relay_a" not in agent_path.read_text(encoding="utf-8")
    rolled_back = rollback_v1_to_v2(
        applied["migrationId"],
        config_path=config_path,
        project_root=project_root,
        expected_current_hash=applied["hash"],
    )
    assert rolled_back["status"] == "rolled_back"
    assert config_path.read_bytes() == before_config
    assert agent_path.read_bytes() == before_agent


def test_rollback_rejects_target_hash_drift_without_writes(tmp_path, monkeypatch) -> None:
    config_path, project_root, legacy = write_migration_fixture(tmp_path)
    monkeypatch.setattr("config.model_config_migration.reload_config", lambda path: object())
    preview = preview_v1_to_v2(legacy, project_root=project_root)
    applied = apply_v1_to_v2(
        preview.preview_id,
        expected_base_hash=public_config_hash(legacy),
        config_path=config_path,
        project_root=project_root,
    )
    config_path.write_text(config_path.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    drifted = config_path.read_bytes()
    with pytest.raises(ValueError, match="drift|stale"):
        rollback_v1_to_v2(
            applied["migrationId"],
            config_path=config_path,
            project_root=project_root,
            expected_current_hash=applied["hash"],
        )
    assert config_path.read_bytes() == drifted
