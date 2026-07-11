from __future__ import annotations

import json

import pytest

import config.settings as config_settings
from config.model_config_migration import apply_v1_to_v2, preview_v1_to_v2, rollback_v1_to_v2
from config.public_config import load_public_config, public_config_hash
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


def test_preview_blocks_conflicting_provider_classification_with_stable_redacted_context(tmp_path) -> None:
    legacy = legacy_config_with_models(
        ("z_relay", "https://gateway.example/v1", "SHARED_KEY", "gpt-z"),
        ("a_official", "https://gateway.example/v1", "SHARED_KEY", "claude-a"),
    )
    legacy["llm"]["model_library"]["a_official"]["provider"].update(
        {"kind": "anthropic", "compat_mode": "anthropic"}
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(dumps_public_config(legacy), encoding="utf-8")
    before = config_path.read_bytes()

    preview = preview_v1_to_v2(legacy, project_root=tmp_path)

    conflict = next(item for item in preview.conflicts if item["code"] == "provider_classification_conflict")
    assert preview.status == "NEEDS_REVIEW"
    assert conflict == {
        "code": "provider_classification_conflict",
        "modelIds": ["a_official", "z_relay"],
        "fields": ["adapter", "driver", "service_class"],
    }
    assert "SHARED_KEY" not in json.dumps(conflict)
    with pytest.raises(ValueError, match="unresolved conflicts"):
        apply_v1_to_v2(
            preview.preview_id,
            expected_base_hash=public_config_hash(legacy),
            config_path=config_path,
            project_root=tmp_path,
        )
    assert config_path.read_bytes() == before


def test_preview_merges_multi_protocol_gateway_without_classification_conflict(tmp_path) -> None:
    legacy = legacy_config_with_models(
        ("relay_chat", "https://gateway.example/v1", "SHARED_KEY", "gpt-chat"),
        ("relay_responses", "https://gateway.example/v1", "SHARED_KEY", "gpt-responses"),
    )
    legacy["llm"]["model_library"]["relay_responses"]["transport"] = "responses"
    legacy["llm"]["model_library"]["relay_responses"]["protocol"] = "responses-v2"

    preview = preview_v1_to_v2(legacy, project_root=tmp_path)

    assert preview.status == "READY"
    assert len(preview.providers) == 1
    assert preview.providers[0]["protocols"] == {
        "default": "chat_completions",
        "allowed": ["chat_completions", "responses"],
    }
    assert all(item["code"] != "provider_classification_conflict" for item in preview.conflicts)


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
    with pytest.raises(RuntimeError, match="migration failed and restored config reload failed"):
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


@pytest.mark.parametrize(
    "model",
    [
        r"C:\models\weights",
        r"\\server\share\weights",
        r"\\?\C:\models\weights",
        r"\\?\UNC\server\share\weights",
        "/opt/models/weights",
        "weights.safetensors",
        "model.bin",
    ],
)
def test_preview_rejects_suspected_artifact_paths(tmp_path, model) -> None:
    legacy = legacy_config_with_models(("relay_a", "https://relay.example/v1", "RELAY_KEY", model))
    preview = preview_v1_to_v2(legacy, project_root=tmp_path)
    assert preview.status == "NEEDS_REVIEW"
    assert preview.conflicts[0]["code"] == "artifact_path_suspected"
    assert "relay_a" not in preview.model_ref_map


def test_preview_preserves_local_artifact_as_wire_id_with_explicit_resolution(tmp_path) -> None:
    artifact_path = r"C:\models\private\weights.gguf"
    legacy = legacy_config_with_models(
        ("local_a", "http://127.0.0.1:8080/v1", "", artifact_path),
    )
    legacy["llm"]["model_library"]["local_a"]["provider"]["kind"] = "local"

    preview = preview_v1_to_v2(
        legacy,
        project_root=tmp_path,
        artifact_resolutions=[
            {"modelId": "local_a", "decision": "preserve_upstream_id"},
        ],
    )

    assert preview.status == "READY"
    provider = preview.providers[0]
    assert provider["deployment"] == {
        "runtime_framework": "",
        "artifact_path": artifact_path,
    }
    provider_id, model_key = preview.model_ref_map["local_a"].split("/", 1)
    proposed_provider = preview.proposed_public_config["llm"]["providers"][provider_id]
    assert proposed_provider["models"][model_key]["upstream_id"] == artifact_path
    assert proposed_provider["deployment"] == provider["deployment"]
    assert preview.proposed_public_config["llm"]["profiles"]["primary"]["model_ref"] == (
        preview.model_ref_map["local_a"]
    )
    assert preview.proposed_public_config["tools"]["image2"]["default_model_ref"] == (
        preview.model_ref_map["local_a"]
    )
    assert preview.proposed_public_config["git"]["commit_message_model_ref"] == (
        preview.model_ref_map["local_a"]
    )
    assert "weights.gguf" not in repr(preview)


def test_preview_preserve_keeps_exact_legacy_artifact_string_with_surrounding_whitespace(tmp_path) -> None:
    artifact_path = "  C:\\models\\private\\weights.gguf  "
    legacy = legacy_config_with_models(
        ("local_a", "http://127.0.0.1:8080/v1", "", artifact_path),
    )
    legacy["llm"]["model_library"]["local_a"]["provider"]["kind"] = "local"

    preview = preview_v1_to_v2(
        legacy,
        project_root=tmp_path,
        artifact_resolutions=[
            {"modelId": "local_a", "decision": "preserve_upstream_id"},
        ],
    )

    provider_id, model_key = preview.model_ref_map["local_a"].split("/", 1)
    provider = preview.proposed_public_config["llm"]["providers"][provider_id]
    assert provider["models"][model_key]["upstream_id"] == artifact_path
    assert provider["deployment"]["artifact_path"] == artifact_path


def test_preview_splits_deployment_artifact_from_explicit_wire_id(tmp_path) -> None:
    artifact_path = "/srv/models/private/weights.gguf"
    legacy = legacy_config_with_models(
        ("local_a", "http://127.0.0.1:8080/v1", "", artifact_path),
    )
    legacy["llm"]["model_library"]["local_a"]["provider"]["kind"] = "local_runtime"

    preview = preview_v1_to_v2(
        legacy,
        project_root=tmp_path,
        artifact_resolutions=[
            {
                "modelId": "local_a",
                "decision": "split_deployment_artifact",
                "upstreamId": "served-model-a",
            },
        ],
    )

    assert preview.status == "READY"
    provider = preview.providers[0]
    assert provider["deployment"] == {
        "runtime_framework": "",
        "artifact_path": artifact_path,
    }
    provider_id, model_key = preview.model_ref_map["local_a"].split("/", 1)
    assert model_key == "served-model-a"
    model = preview.proposed_public_config["llm"]["providers"][provider_id]["models"][model_key]
    assert model["upstream_id"] == "served-model-a"
    assert artifact_path not in json.dumps(model)


def test_preview_split_accepts_namespace_slash_upstream_id(tmp_path) -> None:
    legacy = legacy_config_with_models(
        ("local_a", "http://127.0.0.1:8080/v1", "", r"C:\models\private.gguf"),
    )
    legacy["llm"]["model_library"]["local_a"]["provider"]["kind"] = "local"

    preview = preview_v1_to_v2(
        legacy,
        project_root=tmp_path,
        artifact_resolutions=[
            {
                "modelId": "local_a",
                "decision": "split_deployment_artifact",
                "upstreamId": "namespace/served-model-a",
            },
        ],
    )

    provider_id, model_key = preview.model_ref_map["local_a"].split("/", 1)
    model = preview.proposed_public_config["llm"]["providers"][provider_id]["models"][model_key]
    assert preview.status == "READY"
    assert model["upstream_id"] == "namespace/served-model-a"


def test_preview_blocks_multiple_artifact_paths_in_one_provider_group(tmp_path) -> None:
    legacy = legacy_config_with_models(
        ("local_a", "http://127.0.0.1:8080/v1", "", r"C:\models\a.gguf"),
        ("local_b", "http://127.0.0.1:8080/v1", "", r"C:\models\b.gguf"),
    )
    for entry in legacy["llm"]["model_library"].values():
        entry["provider"]["kind"] = "local"

    preview = preview_v1_to_v2(
        legacy,
        project_root=tmp_path,
        artifact_resolutions=[
            {"modelId": "local_a", "decision": "preserve_upstream_id"},
            {"modelId": "local_b", "decision": "preserve_upstream_id"},
        ],
    )

    conflict = next(item for item in preview.conflicts if item["code"] == "provider_artifact_path_conflict")
    assert preview.status == "NEEDS_REVIEW"
    assert conflict == {
        "code": "provider_artifact_path_conflict",
        "modelIds": ["local_a", "local_b"],
    }
    assert "deployment" not in preview.providers[0]
    assert "a.gguf" not in json.dumps(conflict)
    assert "b.gguf" not in json.dumps(conflict)


def test_preview_rejects_preserve_for_non_local_provider_without_path_disclosure(tmp_path) -> None:
    artifact_path = r"C:\private\relay.gguf"
    legacy = legacy_config_with_models(
        ("relay_a", "https://relay.example/v1", "RELAY_KEY", artifact_path),
    )

    with pytest.raises(ValueError, match="requires a local provider") as exc_info:
        preview_v1_to_v2(
            legacy,
            project_root=tmp_path,
            artifact_resolutions=[
                {"modelId": "relay_a", "decision": "preserve_upstream_id"},
            ],
        )

    assert "relay.gguf" not in str(exc_info.value)


def test_preview_rejects_preserve_for_official_provider(tmp_path) -> None:
    legacy = legacy_config_with_models(
        ("official_a", "https://api.openai.example/v1", "OFFICIAL_KEY", r"C:\private\official.gguf"),
    )
    legacy["llm"]["model_library"]["official_a"]["provider"]["kind"] = "openai"

    with pytest.raises(ValueError, match="requires a local provider"):
        preview_v1_to_v2(
            legacy,
            project_root=tmp_path,
            artifact_resolutions=[
                {"modelId": "official_a", "decision": "preserve_upstream_id"},
            ],
        )


@pytest.mark.parametrize(
    "artifact_resolutions, error",
    [
        (
            [
                {
                    "modelId": "local_a",
                    "decision": "split_deployment_artifact",
                    "upstreamId": r"D:\served\model.gguf",
                }
            ],
            "must not be an artifact path",
        ),
        (
            [
                {
                    "modelId": "local_a",
                    "decision": "split_deployment_artifact",
                    "upstreamId": "./served-model",
                }
            ],
            "must not be an artifact path",
        ),
        (
            [
                {
                    "modelId": "local_a",
                    "decision": "split_deployment_artifact",
                    "upstreamId": "../served-model",
                }
            ],
            "must not be an artifact path",
        ),
        (
            [
                {
                    "modelId": "local_a",
                    "decision": "split_deployment_artifact",
                    "upstreamId": r".\served-model",
                }
            ],
            "must not be an artifact path",
        ),
        (
            [
                {
                    "modelId": "local_a",
                    "decision": "split_deployment_artifact",
                    "upstreamId": r"..\served-model",
                }
            ],
            "must not be an artifact path",
        ),
        ([{"modelId": "local_a", "decision": "guess_runtime"}], "unknown.*decision"),
        ([{"modelId": "missing", "decision": "preserve_upstream_id"}], "unknown.*modelId"),
        (
            [
                {"modelId": "local_a", "decision": "preserve_upstream_id"},
                {"modelId": "local_a", "decision": "preserve_upstream_id"},
            ],
            "duplicate.*modelId",
        ),
        (
            [
                {
                    "modelId": "local_a",
                    "decision": "preserve_upstream_id",
                    "artifactPath": "not accepted",
                }
            ],
            "invalid.*fields",
        ),
    ],
)
def test_preview_rejects_invalid_artifact_resolutions(tmp_path, artifact_resolutions, error) -> None:
    legacy = legacy_config_with_models(
        ("local_a", "http://127.0.0.1:8080/v1", "", r"C:\models\private.gguf"),
    )
    legacy["llm"]["model_library"]["local_a"]["provider"]["kind"] = "local"

    with pytest.raises(ValueError, match=error):
        preview_v1_to_v2(
            legacy,
            project_root=tmp_path,
            artifact_resolutions=artifact_resolutions,
        )


def test_preview_rejects_resolution_for_non_artifact_model(tmp_path) -> None:
    legacy = legacy_config_with_models(
        ("local_a", "http://127.0.0.1:8080/v1", "", "served-model-a"),
    )
    legacy["llm"]["model_library"]["local_a"]["provider"]["kind"] = "local"

    with pytest.raises(ValueError, match="does not target an artifact path"):
        preview_v1_to_v2(
            legacy,
            project_root=tmp_path,
            artifact_resolutions=[
                {"modelId": "local_a", "decision": "preserve_upstream_id"},
            ],
        )


def test_artifact_resolution_is_stable_and_bound_to_preview_id(tmp_path) -> None:
    artifact_path = r"C:\models\private.gguf"
    legacy = legacy_config_with_models(
        ("local_a", "http://127.0.0.1:8080/v1", "", artifact_path),
    )
    legacy["llm"]["model_library"]["local_a"]["provider"]["kind"] = "local"
    preserve = [{"modelId": "local_a", "decision": "preserve_upstream_id"}]
    split_a = [
        {
            "modelId": "local_a",
            "decision": "split_deployment_artifact",
            "upstreamId": "served-model-a",
        }
    ]
    split_b = [
        {
            "modelId": "local_a",
            "decision": "split_deployment_artifact",
            "upstreamId": "served-model-b",
        }
    ]

    first = preview_v1_to_v2(legacy, project_root=tmp_path, artifact_resolutions=preserve)
    second = preview_v1_to_v2(legacy, project_root=tmp_path, artifact_resolutions=preserve)
    split_first = preview_v1_to_v2(legacy, project_root=tmp_path, artifact_resolutions=split_a)
    split_second = preview_v1_to_v2(legacy, project_root=tmp_path, artifact_resolutions=split_b)

    assert first.preview_id == second.preview_id
    assert len({first.preview_id, split_first.preview_id, split_second.preview_id}) == 3


def test_artifact_resolution_preview_performs_no_network_or_disk_writes(tmp_path, monkeypatch) -> None:
    artifact_path = r"C:\models\private.gguf"
    legacy = legacy_config_with_models(
        ("local_a", "http://192.0.2.10:8080/v1", "", artifact_path),
    )
    legacy["llm"]["model_library"]["local_a"]["provider"]["kind"] = "local"

    def fail_network(*_args, **_kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr("socket.create_connection", fail_network)
    monkeypatch.setattr(
        "core.llm.provider_discovery.service.discover_provider_models",
        fail_network,
    )
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))

    preview = preview_v1_to_v2(
        legacy,
        project_root=tmp_path,
        artifact_resolutions=[
            {"modelId": "local_a", "decision": "preserve_upstream_id"},
        ],
    )

    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert preview.status == "READY"
    assert before == after


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
    assert conflict["fields"] == ["defaults.timeout"]
    assert "60" not in json.dumps(conflict)
    assert "120" not in json.dumps(conflict)


def test_same_secret_suggestion_includes_deterministic_proposed_provider_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RELAY_A_KEY", "shared-secret")
    monkeypatch.setenv("RELAY_B_KEY", "shared-secret")
    legacy = legacy_config_with_models(
        ("relay_a", "https://relay.example/v1", "RELAY_A_KEY", "gpt-a"),
        ("relay_b", "https://relay.example/v1", "RELAY_B_KEY", "gpt-b"),
    )

    preview = preview_v1_to_v2(legacy, project_root=tmp_path)

    suggestion = next(item for item in preview.conflicts if item["code"] == "same_secret_different_reference")
    assert suggestion["proposedProviderId"] == preview.providers[0]["provider_id"]
    assert "shared-secret" not in json.dumps(suggestion)


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


def test_apply_never_rewrites_stale_index_completed_run(tmp_path, monkeypatch) -> None:
    config_path, project_root, legacy = write_migration_fixture(tmp_path)
    index_path = project_root / ".runtime" / "runtime-manager" / "work_runs" / "supervised" / "index.json"
    run_path = index_path.parent / "runs" / "run-old.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(json.dumps({"activeRunId": "run-old"}) + "\n", encoding="utf-8")
    run_path.parent.mkdir()
    run_path.write_text(
        json.dumps(
            {
                "runId": "run-old",
                "status": "completed",
                "currentAgentBinding": {"modelId": "relay_a"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = run_path.read_bytes()
    monkeypatch.setattr("config.model_config_migration.reload_config", lambda path: object())

    preview = preview_v1_to_v2(legacy, project_root=project_root)
    applied = apply_v1_to_v2(
        preview.preview_id,
        expected_base_hash=public_config_hash(legacy),
        config_path=config_path,
        project_root=project_root,
    )

    assert applied["status"] == "applied"
    assert run_path.read_bytes() == before


def test_post_reload_failure_restores_disk_and_global_runtime_config(tmp_path, monkeypatch) -> None:
    from core.web.services import runtime_service

    config_path, project_root, legacy = write_migration_fixture(tmp_path)
    monkeypatch.setattr(config_settings, "_settings", None)
    monkeypatch.setattr(config_settings, "_config_path", None)
    config_settings.reload_config(str(config_path))
    assert config_settings.get_config().llm.schema_version == 1
    preview = preview_v1_to_v2(legacy, project_root=project_root)
    monkeypatch.setattr(
        "config.model_config_migration.scan_model_alias_usage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("late validation failed")),
    )

    with pytest.raises(RuntimeError, match="late validation failed"):
        apply_v1_to_v2(
            preview.preview_id,
            expected_base_hash=public_config_hash(legacy),
            config_path=config_path,
            project_root=project_root,
        )

    assert load_public_config(config_path)["llm"].get("schema_version", 1) == 1
    assert config_settings.get_config().llm.schema_version == 1
    assert runtime_service.get_config().llm.schema_version == 1


def test_rollback_reload_failure_raises_fixed_compound_error_with_disk_restored(tmp_path, monkeypatch) -> None:
    config_path, project_root, legacy = write_migration_fixture(tmp_path)
    preview = preview_v1_to_v2(legacy, project_root=project_root)
    reload_calls = []

    def fail_only_rollback(path):
        reload_calls.append(path)
        if len(reload_calls) == 2:
            raise RuntimeError("raw secret rollback detail")
        return object()

    monkeypatch.setattr("config.model_config_migration.reload_config", fail_only_rollback)
    monkeypatch.setattr(
        "config.model_config_migration.scan_model_alias_usage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("raw secret late detail")),
    )

    with pytest.raises(RuntimeError, match="migration failed and restored config reload failed") as exc_info:
        apply_v1_to_v2(
            preview.preview_id,
            expected_base_hash=public_config_hash(legacy),
            config_path=config_path,
            project_root=project_root,
        )

    assert "raw secret" not in str(exc_info.value)
    assert load_public_config(config_path)["llm"].get("schema_version", 1) == 1
    manifests = list((config_path.parent / "backups").glob("llm-config-migration-*.json"))
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["status"] == "rolled_back"
    assert "raw secret" not in json.dumps(manifest)
