from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

import config.operator_config_transaction as transaction_module
from config.llm_identity import provider_discovery_fingerprint
from config.operator_config_transaction import OperatorConfigTransactionError
from config.paths import resolve_model_catalog_state_path
from config.public_config import (
    build_effective_config,
    load_public_config,
    public_config_hash,
)
from core.web.services import agent_directory_service
from core.web.services import agent_model_promotion_service as promotion
from tests.test_agent_config_workspace_service import _use_tmp_project_root


def _operator_config_text() -> str:
    return """# operator comment must survive promotion
[custom]
unknown = "keep-me" # preserve inline note

[llm]
schema_version = 2

[llm.providers.ai-pixel]
label = "Ai-Pixel"
service_class = "relay"
vendor = "multi_model"
driver = "openai"
base_url = "https://relay.example/v1"
auth_kind = "none"
credential_ref = "none"
requires_credential = false

[llm.providers.ai-pixel.protocols]
default = "responses"
allowed = ["responses", "chat_completions"]

[llm.providers.ai-pixel.discovery]
mode = "auto"
adapter = "openai_compatible"
cache_ttl_seconds = 300

[llm.providers.ai-pixel.models.old]
upstream_id = "old-model"
label = "Old model"
enabled = true

[llm.providers.ai-pixel.models."gpt-5.6-sol"]
upstream_id = "gpt-5.6-sol"
label = "Sol"
enabled = true

[llm.profiles.primary]
model_ref = "ai-pixel/old"
"""


def _write_catalog(config_path: Path, *, state: str = "fresh") -> Path:
    public_config = load_public_config(config_path)
    provider = public_config["llm"]["providers"]["ai-pixel"]
    fingerprint = provider_discovery_fingerprint(provider)
    provider_fingerprint = fingerprint
    catalog_stale = False
    models: dict[str, dict] = {
        "gpt-5.6-luna": {
            "upstreamId": "gpt-5.6-luna",
            "label": "Luna",
            "availability": "observed",
            "verification": {
                "status": "verified",
                "providerFingerprint": fingerprint,
            },
            "capabilities": {
                "text_output": {
                    "value": "supported",
                    "source": "runtime_probe",
                    "confidence": "high",
                },
                "image_input": {
                    "value": "unsupported",
                    "source": "runtime_probe",
                    "confidence": "high",
                },
            },
            "reasoningContract": {
                "verificationStatus": "verified",
                "providerFingerprint": fingerprint,
                "source": "runtime_probe",
                "effortValues": ["low", "high"],
                "default": "high",
                "adapter": "reasoning_object",
                "map": {"low": "low", "high": "high"},
            },
        }
    }
    if state == "catalog_stale":
        catalog_stale = True
    elif state == "fingerprint_mismatch":
        provider_fingerprint = "stale-provider-fingerprint"
    elif state == "candidate_missing":
        models = {}
    elif state == "candidate_unavailable":
        models["gpt-5.6-luna"]["availability"] = "unavailable"
    elif state == "unverified_facts":
        models["gpt-5.6-luna"]["verification"]["status"] = "unverified"
        models["gpt-5.6-luna"]["capabilities"]["text_output"]["source"] = (
            "provider_endpoint"
        )
        models["gpt-5.6-luna"]["reasoningContract"]["verificationStatus"] = "unverified"
    elif state == "invalid_reasoning_adapter":
        models["gpt-5.6-luna"]["reasoningContract"]["adapter"] = "reasoning.effort"
    elif state == "invalid_reasoning_map":
        models["gpt-5.6-luna"]["reasoningContract"]["adapter"] = "thinking_toggle"
        models["gpt-5.6-luna"]["reasoningContract"]["map"] = {
            "low": "maybe",
            "high": "on",
        }
    payload = {
        "schemaVersion": 2,
        "metadata": {"legacyCapabilityImportCompleted": True},
        "providers": {
            "ai-pixel": {
                "providerFingerprint": provider_fingerprint,
                "catalogStale": catalog_stale,
                "models": models,
            }
        },
    }
    path = resolve_model_catalog_state_path(config_path)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _setup(tmp_path: Path, monkeypatch, *, catalog_state: str = "fresh") -> dict:
    _use_tmp_project_root(tmp_path, monkeypatch)
    config_path = tmp_path / "config.toml"
    config_path.write_text(_operator_config_text(), encoding="utf-8", newline="")
    _write_catalog(config_path, state=catalog_state)
    monkeypatch.setattr(
        transaction_module,
        "reload_config",
        lambda path: build_effective_config(load_public_config(Path(path))),
    )
    monkeypatch.setattr(
        promotion, "record_runtime_scene_event", lambda *args, **kwargs: None
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="Promotion Agent",
        llm_bindings={"dialogue": {"modelId": "ai-pixel/old"}},
        primary_mode="chat",
    )
    return {
        "config_path": config_path,
        "base_hash": public_config_hash(load_public_config(config_path)),
        "agent": agent,
        "registry_path": agent_directory_service.registry_path(),
    }


def _promote(setup: dict, **overrides):
    payload = {
        "agent_id": setup["agent"]["agentId"],
        "slot": "dialogue",
        "model_ref": "ai-pixel/gpt-5.6-luna",
        "expected_base_hash": setup["base_hash"],
        "expected_agent_updated_at": setup["agent"]["updatedAt"],
        "confirmed": True,
        "config_path": setup["config_path"],
    }
    payload.update(overrides)
    return promotion.promote_agent_model(**payload)


def test_observed_model_is_pinned_then_bound_without_rewriting_existing_text(
    tmp_path, monkeypatch
):
    setup = _setup(tmp_path, monkeypatch)
    before = setup["config_path"].read_bytes()
    invalidations = []
    monkeypatch.setattr(
        promotion,
        "invalidate_agent_config_workspace_cache",
        lambda: invalidations.append(True),
    )

    result = _promote(setup)

    assert result["status"] == "completed"
    assert result["modelRef"] == "ai-pixel/gpt-5.6-luna"
    assert result["source"] == "discovered"
    assert result["manifestPath"]
    assert result["operatorConfigHash"] != setup["base_hash"]
    saved_bytes = setup["config_path"].read_bytes()
    assert saved_bytes.startswith(before)
    assert b"# operator comment must survive promotion" in saved_bytes
    assert b'unknown = "keep-me" # preserve inline note' in saved_bytes
    saved = tomllib.loads(saved_bytes.decode("utf-8"))
    pinned = saved["llm"]["providers"]["ai-pixel"]["models"]["gpt-5.6-luna"]
    assert pinned["upstream_id"] == "gpt-5.6-luna"
    assert pinned["enabled"] is True
    assert pinned["capabilities"]["text_output"]["source"] == "runtime_probe"
    assert pinned["defaults"] == {
        "reasoning_effort_values": ["low", "high"],
        "default_reasoning_effort": "high",
        "reasoning_effort_adapter": "reasoning_object",
        "reasoning_effort_map": {"low": "low", "high": "high"},
    }
    assert agent_directory_service.get_agent(setup["agent"]["agentId"])["llmBindings"][
        "dialogue"
    ] == {"modelId": "ai-pixel/gpt-5.6-luna"}
    assert invalidations == [True]


def test_unverified_catalog_facts_are_not_promoted_as_capabilities_or_defaults(
    tmp_path,
    monkeypatch,
):
    setup = _setup(tmp_path, monkeypatch, catalog_state="unverified_facts")

    result = _promote(setup)

    assert result["status"] == "completed"
    saved = tomllib.loads(setup["config_path"].read_text(encoding="utf-8"))
    pinned = saved["llm"]["providers"]["ai-pixel"]["models"]["gpt-5.6-luna"]
    assert "capabilities" not in pinned
    assert "defaults" not in pinned


@pytest.mark.parametrize(
    "catalog_state",
    ["invalid_reasoning_adapter", "invalid_reasoning_map"],
)
def test_invalid_verified_reasoning_metadata_is_not_fixed_into_operator_config(
    tmp_path,
    monkeypatch,
    catalog_state,
):
    setup = _setup(tmp_path, monkeypatch, catalog_state=catalog_state)

    result = _promote(setup)

    assert result["status"] == "completed"
    saved = tomllib.loads(setup["config_path"].read_text(encoding="utf-8"))
    pinned = saved["llm"]["providers"]["ai-pixel"]["models"]["gpt-5.6-luna"]
    assert pinned["capabilities"]["text_output"]["source"] == "runtime_probe"
    assert "defaults" not in pinned


def test_confirmed_false_performs_no_config_agent_backup_or_reload_mutation(
    tmp_path, monkeypatch
):
    setup = _setup(tmp_path, monkeypatch)
    before_config = setup["config_path"].read_bytes()
    before_registry = setup["registry_path"].read_bytes()
    monkeypatch.setattr(
        transaction_module,
        "reload_config",
        lambda *_args, **_kwargs: pytest.fail("reload must not run"),
    )

    with pytest.raises(promotion.AgentModelPromotionConflict, match="confirmation"):
        _promote(setup, confirmed=False)

    assert setup["config_path"].read_bytes() == before_config
    assert setup["registry_path"].read_bytes() == before_registry
    assert not (tmp_path / "backups").exists()


def test_rejected_unvalidated_model_identity_never_enters_runtime_event(
    tmp_path,
    monkeypatch,
):
    setup = _setup(tmp_path, monkeypatch)
    recorded = []
    secret = "raw-model-ref-secret"
    monkeypatch.setattr(
        promotion,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )

    with pytest.raises(promotion.AgentModelPromotionConflict, match="invalid"):
        _promote(setup, model_ref=secret)

    serialized = json.dumps(recorded, ensure_ascii=False, default=str)
    assert secret not in serialized


@pytest.mark.parametrize(
    ("condition", "kwargs"),
    [
        ("stale_config", {"expected_base_hash": "stale-config-hash"}),
        ("stale_agent", {"expected_agent_updated_at": "stale-agent-timestamp"}),
        ("catalog_stale", {}),
        ("fingerprint_mismatch", {}),
        ("candidate_missing", {}),
        ("candidate_unavailable", {}),
        ("incompatible_slot", {"slot": "vision"}),
    ],
)
def test_stale_or_incompatible_preflight_stops_before_any_write(
    tmp_path,
    monkeypatch,
    condition,
    kwargs,
):
    catalog_state = (
        condition
        if condition
        in {
            "catalog_stale",
            "fingerprint_mismatch",
            "candidate_missing",
            "candidate_unavailable",
        }
        else "fresh"
    )
    setup = _setup(tmp_path, monkeypatch, catalog_state=catalog_state)
    before_config = setup["config_path"].read_bytes()
    before_registry = setup["registry_path"].read_bytes()
    monkeypatch.setattr(
        transaction_module,
        "reload_config",
        lambda *_args, **_kwargs: pytest.fail("reload must not run"),
    )

    with pytest.raises(promotion.AgentModelPromotionConflict):
        _promote(setup, **kwargs)

    assert setup["config_path"].read_bytes() == before_config
    assert setup["registry_path"].read_bytes() == before_registry
    assert not (tmp_path / "backups").exists()


def test_agent_edit_racing_after_preflight_is_preserved_and_config_is_restored(
    tmp_path, monkeypatch
):
    setup = _setup(tmp_path, monkeypatch)
    before_config = setup["config_path"].read_bytes()
    original_apply = promotion.apply_operator_config_transaction

    def race_then_apply(prepared, *, participants=()):
        agent_directory_service.update_agent_instance(
            setup["agent"]["agentId"],
            display_name="Concurrent user edit",
        )
        return original_apply(prepared, participants=participants)

    monkeypatch.setattr(promotion, "apply_operator_config_transaction", race_then_apply)

    with pytest.raises(OperatorConfigTransactionError) as error:
        _promote(setup)

    assert error.value.status == "rolled_back"
    assert setup["config_path"].read_bytes() == before_config
    current = agent_directory_service.get_agent(setup["agent"]["agentId"])
    assert current["displayName"] == "Concurrent user edit"
    assert current["llmBindings"]["dialogue"]["modelId"] == "ai-pixel/old"


def test_agent_verify_failure_compensates_binding_and_exact_config_bytes(
    tmp_path, monkeypatch
):
    setup = _setup(tmp_path, monkeypatch)
    before_config = setup["config_path"].read_bytes()
    secret = "raw-agent-verify-secret"
    recorded = []
    monkeypatch.setattr(
        promotion,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )
    monkeypatch.setattr(
        promotion,
        "_assert_agent_binding",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(secret)),
    )

    with pytest.raises(OperatorConfigTransactionError) as error:
        _promote(setup)

    assert error.value.status == "rolled_back"
    assert setup["config_path"].read_bytes() == before_config
    assert (
        agent_directory_service.get_agent(setup["agent"]["agentId"])["llmBindings"][
            "dialogue"
        ]["modelId"]
        == "ai-pixel/old"
    )
    manifest = json.loads(error.value.manifest_path.read_text(encoding="utf-8"))
    serialized = json.dumps(
        {"manifest": manifest, "events": recorded}, ensure_ascii=False, default=str
    )
    assert manifest["failurePhase"] == "participant_verify"
    assert manifest["errorType"] == "RuntimeError"
    assert secret not in serialized


def test_binding_rollback_failure_is_bounded_and_manifest_is_truthful(
    tmp_path, monkeypatch
):
    setup = _setup(tmp_path, monkeypatch)
    before_config = setup["config_path"].read_bytes()
    original_replace = promotion.replace_agent_llm_bindings_if_current
    calls = 0

    def fail_second_replace(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("rollback-secret-must-not-leak")
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(
        promotion, "replace_agent_llm_bindings_if_current", fail_second_replace
    )
    monkeypatch.setattr(
        promotion,
        "_assert_agent_binding",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("verify failed")),
    )

    with pytest.raises(OperatorConfigTransactionError) as error:
        _promote(setup)

    assert error.value.status == "rollback_failed"
    assert setup["config_path"].read_bytes() == before_config
    manifest_text = error.value.manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["status"] == "rollback_failed"
    assert manifest["rollbackErrors"] == ["agent_binding:RuntimeError"]
    assert "rollback-secret-must-not-leak" not in manifest_text


def test_already_pinned_model_changes_only_agent_binding_without_config_transaction(
    tmp_path, monkeypatch
):
    setup = _setup(tmp_path, monkeypatch)
    before_config = setup["config_path"].read_bytes()
    monkeypatch.setattr(
        promotion,
        "prepare_operator_config_transaction",
        lambda **_kwargs: pytest.fail(
            "pinned model must not prepare a config transaction"
        ),
    )
    monkeypatch.setattr(
        transaction_module,
        "reload_config",
        lambda *_args, **_kwargs: pytest.fail("pinned model must not reload config"),
    )

    result = _promote(setup, model_ref="ai-pixel/gpt-5.6-sol")

    assert result["status"] == "completed"
    assert result["modelRef"] == "ai-pixel/gpt-5.6-sol"
    assert result["source"] == "pinned"
    assert result["operatorConfigHash"] == setup["base_hash"]
    assert result["manifestPath"] == ""
    assert result["agent"]["agentId"] == setup["agent"]["agentId"]
    assert (
        result["agent"]["llmBindings"]["dialogue"]["modelId"] == "ai-pixel/gpt-5.6-sol"
    )
    assert setup["config_path"].read_bytes() == before_config
    assert not (tmp_path / "backups").exists()
