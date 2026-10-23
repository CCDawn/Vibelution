"""Assistant configuration actions with temp TOML and native transactions."""
from __future__ import annotations

import copy
import json
import tomllib
from pathlib import Path

import pytest

from tools import pa_config_actions as actions


@pytest.fixture
def operator(tmp_path, monkeypatch):
    from config import operator_config_transaction as transaction
    from core.web.services import model_reference_service as references
    fixture = Path(__file__).parent / "fixtures/config/llm_schema_v2_provider.toml"
    path = tmp_path / "config.toml"
    path.write_text(fixture.read_text(encoding="utf-8") + '\n# untouched sentinel\n[user_profile]\ndisplay_name = "Operator"\n', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(path))
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(transaction, "reload_config", lambda *_: None)
    monkeypatch.setattr(references, "PROJECT_ROOT", tmp_path)
    # Always use this fixture root, never the actual project's registries.
    monkeypatch.setattr(actions, "_assert_model_unused", lambda config, model_id:
                        references.assert_model_delete_safe(model_id, public_config=config, project_root=tmp_path))
    monkeypatch.setattr(actions, "_assert_provider_unused", lambda provider_id:
                        _assert_no_provider_refs(references, provider_id, tmp_path))
    return path


def _assert_no_provider_refs(references, provider_id, root):
    if references.scan_provider_live_references(provider_id, project_root=root)["liveReferenceCount"]:
        raise PermissionError("references")


def read(path):
    return tomllib.loads(path.read_text(encoding="utf-8"))


def call(action, parameters, *, governed=False):
    return actions.execute(action, parameters, {"agentId": "fixture-assistant"}, governed=governed)


def add_spare(path):
    from config.operator_config_transaction import append_toml_table
    path.write_text(append_toml_table(path.read_text(encoding="utf-8"),
        ("llm", "providers", "pixel_relay", "models", "spare"),
        {"upstream_id": "spare", "label": "Spare", "enabled": True}), encoding="utf-8")


def test_contracts_are_closed_and_expose_field_schema():
    contracts = actions.contracts()
    assert contracts["model_update"]["governed"] is False
    for name in ("provider_add", "provider_update", "provider_remove", "provider_test", "provider_discover", "model_remove", "model_default"):
        assert contracts[name]["governed"] is True
    assert contracts["model_update"]["updatesSchema"]["additionalProperties"] is False
    assert actions.describe("model_default")["parameters"]["properties"]["target"]["enum"] == ["profile", "image2", "git"]
    assert len(actions.catalog()["actions"]) == len(contracts)


@pytest.mark.parametrize("action", ["provider_add", "provider_update", "provider_remove", "provider_test", "provider_discover", "model_remove", "model_default"])
def test_governed_actions_fail_before_reading_config(monkeypatch, action):
    monkeypatch.setattr(actions, "_path", lambda: pytest.fail("approval gate must precede config read"))
    result = call(action, {"governed": True})
    assert result["error"] == "native_approval_required"


def test_catalog_is_paginated_and_never_returns_connection_or_credential(operator):
    result = call("provider_catalog", {"query": "Pixel", "limit": 1})
    assert result["ok"] and result["total"] == 1
    assert result["providers"][0]["providerId"] == "pixel_relay"
    assert result["providers"][0]["origin"] == "https://relay.example"
    encoded = json.dumps(result)
    for forbidden in ("rawToml", "publicConfig", "credential_ref", "VIBELUTION_LLM_PROVIDER", "relay.example/v1", "artifact_path"):
        assert forbidden not in encoded


def test_model_update_persists_only_owned_entry(operator):
    before = read(operator)
    result = call("model_update", {"model_id": "pixel_relay/gpt-5.6-luna", "updates": {
        "label": "Changed", "temperature": 0.4, "timeout": 90, "streaming": False}})
    assert result["ok"] and result["verified"]
    expected = copy.deepcopy(before)
    entry = expected["llm"]["providers"]["pixel_relay"]["models"]["gpt-5.6-luna"]
    entry["label"] = "Changed"
    entry["defaults"].update(temperature=0.4, timeout=90, streaming=False)
    assert read(operator) == expected
    assert "# untouched sentinel" in operator.read_text(encoding="utf-8")


@pytest.mark.parametrize("updates", [
    {"credential_ref": "env:SECRET_NAME"}, {"wire_protocol": "responses"},
    {"capabilities": {"api_key": "secret"}}, {"enabled": 1},
    {"temperature": 4}, {"timeout": 0}, {"label": None}, {},
])
def test_model_invalid_edits_do_not_write_or_echo(operator, updates):
    before = operator.read_bytes()
    result = call("model_update", {"model_id": "pixel_relay/gpt-5.6-luna", "updates": updates})
    assert result["ok"] is False
    assert operator.read_bytes() == before
    assert "SECRET_NAME" not in json.dumps(result) and '"secret"' not in json.dumps(result)


def test_model_remove_checks_native_references(operator):
    before = operator.read_bytes()
    result = call("model_remove", {"model_id": "pixel_relay/gpt-5.6-luna"}, governed=True)
    assert result["error"] == "live_model_references"
    assert operator.read_bytes() == before
    add_spare(operator)
    expected = read(operator)
    expected["llm"]["providers"]["pixel_relay"]["models"].pop("spare")
    result = call("model_remove", {"model_id": "pixel_relay/spare"}, governed=True)
    assert result["ok"] and result["verified"]
    assert read(operator) == expected


@pytest.mark.parametrize("target", ["profile", "git"])
def test_default_targets_persist_real_schema_bindings_without_materializing_pins(operator, target):
    before = read(operator)
    model_id = "lab_llamacpp_a/qwen3.6-35b-a3b"
    result = call("model_default", {"model_id": model_id, "target": target}, governed=True)
    assert result["ok"] and result["verified"]
    after = read(operator)
    assert after["llm"]["providers"] == before["llm"]["providers"]
    if target == "profile":
        assert after["llm"]["profiles"]["primary"]["model_ref"] == model_id
    else:
        assert after["git"]["commit_message_model_ref"] == model_id


def test_image2_default_rejects_text_model_before_write(operator):
    before = operator.read_bytes()
    result = call("model_default", {"model_id": "pixel_relay/gpt-5.6-luna", "target": "image2"}, governed=True)
    assert result["error"] == "image_model_required"
    assert operator.read_bytes() == before


def test_image2_default_accepts_native_image_discovery_candidate(operator):
    from config.operator_config_transaction import append_toml_table
    operator.write_text(append_toml_table(operator.read_text(encoding="utf-8"),
        ("llm", "providers", "pixel_relay", "models", "image"),
        {"upstream_id": "gpt-image-1.5", "label": "Image", "enabled": True}), encoding="utf-8")
    before = read(operator)
    result = call("model_default", {"model_id": "pixel_relay/image", "target": "image2"}, governed=True)
    assert result["ok"] and result["verified"]
    after = read(operator)
    assert after["tools"]["image2"]["default_model_ref"] == "pixel_relay/image"
    assert after["llm"] == before["llm"]


def test_context_window_null_clears_only_its_override_and_schema_matches(operator):
    schema = actions.contracts()["model_update"]["updatesSchema"]["properties"]
    assert {item.get("type") for item in schema["context_window"]["anyOf"]} == {"integer", "null"}
    assert schema["label"]["type"] == "string"
    assert call("model_update", {"model_id": "pixel_relay/gpt-5.6-luna", "updates": {"context_window": 120000}})["ok"]
    before = read(operator)
    expected = copy.deepcopy(before)
    del expected["llm"]["providers"]["pixel_relay"]["models"]["gpt-5.6-luna"]["context_window"]
    result = call("model_update", {"model_id": "pixel_relay/gpt-5.6-luna", "updates": {"context_window": None}})
    assert result["ok"] and result["verified"]
    assert read(operator) == expected


def test_default_rejects_unknown_profile_and_model(operator):
    before = operator.read_bytes()
    for params in ({"model_id": "pixel_relay/missing"},
                   {"model_id": "pixel_relay/gpt-5.6-luna", "profile_id": "invented"}):
        assert not call("model_default", params, governed=True)["ok"]
    assert operator.read_bytes() == before


def test_provider_add_reuses_duplicate_and_same_origin_auth_without_exposing_reference(operator):
    before = operator.read_bytes()
    result = call("provider_add", {"provider_id": "copy", "source_provider_id": "pixel_relay"}, governed=True)
    assert result == {"ok": True, "status": "existing", "verified": True, "providerId": "pixel_relay"}
    assert operator.read_bytes() == before
    result = call("provider_add", {"provider_id": "alternate", "source_provider_id": "pixel_relay",
                  "base_url": "https://relay.example/v2"}, governed=True)
    assert result["ok"]
    providers = read(operator)["llm"]["providers"]
    assert providers["alternate"]["credential_ref"] == providers["pixel_relay"]["credential_ref"]
    assert "env:" not in json.dumps(result)


@pytest.mark.parametrize("url", ["https://other.example/v1", "http://relay.example/v1", "https://relay.example:444/v1"])
def test_provider_cross_origin_auth_reuse_is_blocked(operator, url):
    before = operator.read_bytes()
    assert not call("provider_add", {"provider_id": "bad", "source_provider_id": "pixel_relay", "base_url": url}, governed=True)["ok"]
    result = call("provider_update", {"provider_id": "pixel_relay", "base_url": url}, governed=True)
    assert result["error"] == "credential_origin_blocked"
    assert operator.read_bytes() == before


def test_provider_cross_origin_can_explicitly_drop_auth(operator):
    result = call("provider_update", {"provider_id": "pixel_relay", "base_url": "https://other.example/v1",
                  "clear_credential": True}, governed=True)
    assert result["ok"]
    provider = read(operator)["llm"]["providers"]["pixel_relay"]
    assert provider["credential_ref"] == "none" and provider["auth_kind"] == "none"
    assert not provider["requires_credential"]


def test_provider_update_preserves_models_and_unrelated_provider(operator):
    before = read(operator)
    result = call("provider_update", {"provider_id": "pixel_relay", "label": "New label", "enabled": False}, governed=True)
    assert result["ok"]
    expected = copy.deepcopy(before)
    expected["llm"]["providers"]["pixel_relay"].update(label="New label", enabled=False)
    assert read(operator) == expected


def test_provider_remove_requires_no_models_and_prunes_only_owned_catalog(operator):
    assert call("provider_remove", {"provider_id": "pixel_relay"}, governed=True)["error"] == "provider_has_models"
    assert call("provider_add", {"provider_id": "empty", "base_url": "https://empty.example/v1"}, governed=True)["ok"]
    from config.paths import resolve_model_catalog_state_path
    catalog = resolve_model_catalog_state_path(operator)
    catalog.write_text(json.dumps({"schemaVersion": 2, "providers": {"empty": {"secret": "fixture-only"},
        "pixel_relay": {"models": []}, "unrelated_stale": {"models": []}},
        "metadata": {"legacyCapabilityImportCompleted": True, "legacyCapabilityImportOutcome": "not_present"}}), encoding="utf-8")
    result = call("provider_remove", {"provider_id": "empty"}, governed=True)
    assert result["ok"], result
    assert "empty" not in read(operator)["llm"]["providers"]
    assert set(json.loads(catalog.read_text(encoding="utf-8"))["providers"]) == {"pixel_relay", "unrelated_stale"}


def test_provider_test_uses_native_probe_but_projects_only_outcome(operator, monkeypatch):
    from core.web.services import config_service
    seen = []
    def probe(config, **kwargs):
        seen.append(kwargs)
        return {"ok": True, "api_key": "fixture-secret", "publicConfig": config, "message": "env:SECRET"}
    monkeypatch.setattr(config_service, "run_draft_llm_test", probe)
    result = call("provider_test", {"provider_id": "pixel_relay", "model_id": "pixel_relay/gpt-5.6-luna"}, governed=True)
    assert result["connectionVerified"] is True
    assert seen == [{"model_id": "pixel_relay/gpt-5.6-luna", "capability": "text"}]
    assert "SECRET" not in json.dumps(result) and "fixture-secret" not in json.dumps(result)


def test_native_error_is_not_echoed(operator, monkeypatch):
    monkeypatch.setattr(actions, "_commit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fixture-secret env:SECRET")))
    result = call("model_update", {"model_id": "pixel_relay/gpt-5.6-luna", "updates": {"label": "L"}})
    assert result["status"] == "unknown" and "SECRET" not in json.dumps(result)


def test_transaction_drift_does_not_overwrite_other_writer(operator, monkeypatch):
    from config import operator_config_transaction as transaction
    original = transaction.apply_operator_config_transaction
    def concurrent(prepared, **kwargs):
        operator.write_text(operator.read_text(encoding="utf-8") + "\n# concurrent writer\n", encoding="utf-8")
        return original(prepared, **kwargs)
    monkeypatch.setattr(transaction, "apply_operator_config_transaction", concurrent)
    result = call("model_update", {"model_id": "pixel_relay/gpt-5.6-luna", "updates": {"label": "L"}})
    assert result["error"] == "config_conflict"
    assert read(operator)["llm"]["providers"]["pixel_relay"]["models"]["gpt-5.6-luna"]["label"] != "L"
    assert "# concurrent writer" in operator.read_text(encoding="utf-8")


def test_provider_discovery_uses_native_server_credentials_and_projects_only_ids(operator, monkeypatch):
    import httpx
    from core.llm.provider_discovery import service as discovery
    original = discovery.discover_provider_models
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_PIXEL_RELAY_API_KEY", "fixture-secret")
    monkeypatch.setattr(discovery, "validate_llm_provider_target", lambda *args, **kwargs: None)
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "family/model-v2", "unsafe": "do not echo"}, {"id": "another"}]})
    def discover(config, provider_id, **kwargs):
        return original(config, provider_id, **kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(discovery, "discover_provider_models", discover)
    before = operator.read_bytes()
    result = call("provider_discover", {"provider_id": "pixel_relay", "query": "family", "limit": 1}, governed=True)
    assert result["ok"] and result["status"] == "discovered", result
    assert result["models"] == [{"upstreamId": "family/model-v2"}]
    assert requests[0].headers["Authorization"] == "Bearer fixture-secret"
    assert "fixture-secret" not in json.dumps(result) and "do not echo" not in json.dumps(result)
    assert operator.read_bytes() == before
    cached = call("provider_models", {"provider_id": "pixel_relay", "query": "family"})
    assert cached["models"] == result["models"] and cached["stale"] is False


def test_cached_models_are_bounded_and_stale_cache_is_identified(operator):
    from config.paths import resolve_model_catalog_state_path
    state = {"schemaVersion": 2, "metadata": {}, "providers": {"pixel_relay": {
        "providerFingerprint": "obsolete", "models": {
            "model": {"upstreamId": "family/model", "secret": "fixture-secret"},
            "bad": {"upstreamId": "env:NOT_A_REAL_VARIABLE"},
            "huge": {"upstreamId": "X" * 300},
        }}}}
    resolve_model_catalog_state_path(operator).write_text(json.dumps(state), encoding="utf-8")
    result = call("provider_models", {"provider_id": "pixel_relay", "limit": 1})
    assert result["models"] == [{"upstreamId": "family/model"}] and result["stale"] is True
    assert result["total"] == 1
    assert "fixture-secret" not in json.dumps(result) and "env:" not in json.dumps(result)


def test_discovery_rejects_cross_origin_credential_override_before_network(operator, monkeypatch):
    from config.operator_config_transaction import append_toml_table, remove_toml_table_tree
    from core.llm.provider_discovery import service as discovery
    config = read(operator)
    settings = config["llm"]["providers"]["pixel_relay"]["discovery"]
    settings["models_url_override"] = "https://different.example/models"
    text = remove_toml_table_tree(operator.read_text(encoding="utf-8"), ("llm", "providers", "pixel_relay", "discovery"))
    operator.write_text(append_toml_table(text, ("llm", "providers", "pixel_relay", "discovery"), settings), encoding="utf-8")
    monkeypatch.setattr(discovery, "discover_provider_models", lambda *args, **kwargs: pytest.fail("no network"))
    result = call("provider_discover", {"provider_id": "pixel_relay"}, governed=True)
    assert result["error"] == "credential_origin_blocked"


def test_no_success_receipt_when_readback_differs(operator, monkeypatch):
    original = actions._read
    count = 0
    def readback(path):
        nonlocal count
        count += 1
        config = original(path)
        if count > 1:
            config["user_profile"]["display_name"] = "other writer"
        return config
    monkeypatch.setattr(actions, "_read", readback)
    result = call("model_update", {"model_id": "pixel_relay/gpt-5.6-luna", "updates": {"label": "Changed"}})
    assert result["error"] == "verification_failed" and result["status"] == "unknown"


def test_new_provider_discovers_through_real_native_adapter_instead_of_manual(operator, monkeypatch):
    import httpx
    from core.llm.provider_discovery import service as discovery
    original = discovery.discover_provider_models
    requests = []
    monkeypatch.setattr(discovery, "validate_llm_provider_target", lambda *args, **kwargs: None)
    def respond(request):
        requests.append(request)
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"data": [{"id": "upstream/image-model"}]})
    monkeypatch.setattr(discovery, "discover_provider_models", lambda config, provider_id, **kwargs:
        original(config, provider_id, **kwargs, transport=httpx.MockTransport(respond)))
    assert call("provider_add", {"provider_id": "new", "base_url": "https://new.example/v1"}, governed=True)["ok"]
    result = call("provider_discover", {"provider_id": "new"}, governed=True)
    assert requests and requests[0].url.path == "/v1/models"
    assert result["status"] == "discovered" and result["models"] == [{"upstreamId": "upstream/image-model"}]


def test_manual_provider_discovery_never_reports_completed_network_discovery(operator, monkeypatch):
    from config.operator_config_transaction import append_toml_table, remove_toml_table_tree
    from core.llm.provider_discovery import service as discovery
    text = remove_toml_table_tree(operator.read_text(encoding="utf-8"), ("llm", "providers", "pixel_relay", "discovery"))
    operator.write_text(append_toml_table(text, ("llm", "providers", "pixel_relay", "discovery"),
        {"adapter": "manual", "mode": "manual"}), encoding="utf-8")
    monkeypatch.setattr(discovery, "discover_provider_models", lambda *a, **k: pytest.fail("manual mode has no network discovery"))
    result = call("provider_discover", {"provider_id": "pixel_relay"}, governed=True)
    assert result["ok"] is False and result["status"] == "manual" and result["stale"] is True


@pytest.mark.parametrize("driver,wire,adapter", [
    ("openai", "responses", "openai_compatible"),
    ("anthropic", "anthropic_messages", "anthropic"),
    ("gemini", "gemini_generate_content", "gemini"),
])
def test_new_provider_driver_defaults_select_supported_native_discovery_adapter(operator, driver, wire, adapter):
    result = call("provider_add", {"provider_id": "driver_test", "base_url": "https://new.example/v1",
        "driver": driver, "wire_protocol": wire}, governed=True)
    assert result["ok"], result
    assert read(operator)["llm"]["providers"]["driver_test"]["discovery"]["adapter"] == adapter


def test_source_provider_copies_bounded_same_origin_discovery_without_secret_headers(operator):
    from config.operator_config_transaction import append_toml_table
    operator.write_text(append_toml_table(operator.read_text(encoding="utf-8"),
        ("llm", "providers", "pixel_relay", "extra_headers"),
        {"X-Private-Metadata": "fixture-only-private"}), encoding="utf-8")
    result = call("provider_add", {"provider_id": "copy_route", "source_provider_id": "pixel_relay",
        "base_url": "https://relay.example/v2"}, governed=True)
    assert result["ok"]
    provider = read(operator)["llm"]["providers"]["copy_route"]
    assert provider["discovery"] == {"adapter": "openai_compatible", "mode": "auto", "cache_ttl_seconds": 3600}
    assert "extra_headers" not in provider


def test_loopback_provider_local_runtime_passes_real_native_validators_and_persists(operator):
    from config.llm_security import validate_llm_public_config
    from config.public_config import build_effective_config
    before = read(operator)
    result = call("provider_add", {"provider_id": "pa-api-212542", "base_url": "http://127.0.0.1:9/v1",
        "service_class": "local_runtime", "label": "本地API验收"}, governed=True)
    assert result["ok"] and result["verified"], result
    persisted = read(operator)
    validate_llm_public_config(persisted)
    effective = build_effective_config(persisted)
    assert effective.llm.providers["pa-api-212542"].service_class == "local_runtime"
    assert persisted["llm"]["providers"]["pa-api-212542"]["credential_ref"] == "none"
    del persisted["llm"]["providers"]["pa-api-212542"]
    assert persisted == before


def test_loopback_self_hosted_reports_native_classification_correction_before_write(operator):
    before = operator.read_bytes()
    result = call("provider_add", {"provider_id": "pa-api-212542", "base_url": "http://127.0.0.1:9/v1",
        "service_class": "self_hosted", "label": "本地API验收"}, governed=True)
    assert result["error"] == "local_endpoint_requires_local_runtime"
    assert result["field"] == "service_class" and result["suggestedValue"] == "local_runtime"
    assert result["retryRequiresApproval"] is True
    assert operator.read_bytes() == before


def test_loopback_provider_without_explicit_class_uses_native_local_runtime(operator):
    from config.llm_security import validate_llm_public_config
    from config.public_config import build_effective_config
    result = call("provider_add", {"provider_id": "local_inferred", "base_url": "http://127.0.0.1:9/v1"}, governed=True)
    assert result["ok"] and result["verified"], result
    persisted = read(operator)
    assert persisted["llm"]["providers"]["local_inferred"]["service_class"] == "local_runtime"
    validate_llm_public_config(persisted)
    assert build_effective_config(persisted).llm.providers["local_inferred"].service_class == "local_runtime"


def test_model_details_independently_reads_editable_values_without_route_or_secret(operator):
    result = call("model_update", {"model_id": "pixel_relay/gpt-5.6-luna", "updates": {"temperature": 0.45}})
    assert result["ok"]
    before = operator.read_bytes()
    result = call("model_details", {"model_id": "pixel_relay/gpt-5.6-luna"})
    assert result["ok"] and result["values"]["temperature"] == 0.45
    assert result["values"]["timeout"] == 120
    assert set(result["values"]) == set(actions.ModelEdits.model_fields)
    assert len(result["values"]) == 9
    assert "temperature" in result["configuredFields"]
    for forbidden in ("base_url", "wire_protocol", "credential_ref", "VIBELUTION_LLM_PROVIDER", "rawToml", "publicConfig"):
        assert forbidden not in json.dumps(result)
    assert operator.read_bytes() == before


def test_model_defaults_lists_profile_identifiers_without_overrides_or_config(operator):
    before = operator.read_bytes()
    result = call("model_defaults", {})
    assert result["ok"] and result["gitModelId"] == "" and result["imageModelId"] == ""
    assert result["profiles"] == [
        {"profileId": "primary", "label": "primary", "modelId": "pixel_relay/gpt-5.6-luna"},
        {"profileId": "local", "label": "local", "modelId": "lab_llamacpp_a/qwen3.6-35b-a3b"},
    ]
    assert "overrides" not in json.dumps(result) and "credential_ref" not in json.dumps(result)
    assert operator.read_bytes() == before


@pytest.mark.parametrize("target,key", [("git", "gitModelId"), ("image2", "imageModelId")])
def test_git_and_image_default_can_be_cleared_and_read_back_as_automatic(operator, target, key):
    from config.operator_config_transaction import append_toml_table
    operator.write_text(append_toml_table(operator.read_text(encoding="utf-8"),
        ("llm", "providers", "pixel_relay", "models", "image"),
        {"upstream_id": "gpt-image-1.5", "enabled": True}), encoding="utf-8")
    assert call("model_default", {"model_id": "pixel_relay/image", "target": target}, governed=True)["ok"]
    assert call("model_defaults", {})[key] == "pixel_relay/image"
    before = read(operator)
    result = call("model_default", {"model_id": "", "target": target}, governed=True)
    assert result["ok"] and result["verified"]
    assert call("model_defaults", {})[key] == ""
    assert read(operator)["llm"] == before["llm"]


def test_profile_default_cannot_be_cleared(operator):
    before = operator.read_bytes()
    result = call("model_default", {"model_id": "", "target": "profile", "profile_id": "primary"}, governed=True)
    assert result["error"] == "profile_model_required"
    assert operator.read_bytes() == before
