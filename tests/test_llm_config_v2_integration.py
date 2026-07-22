from __future__ import annotations

import copy
import tomllib
from pathlib import Path

import pytest

from config import settings as config_settings
from config.model_config_migration import preview_v1_to_v2
from config.operator_bootstrap import (
    is_thin_local_only_starter,
    render_default_operator_config_text,
)
from config.paths import CONFIG_STARTER_TEXT, EXAMPLE_CONFIG_STARTER_TEXT
from config.public_config import (
    add_llm_model,
    apply_llm_model_preset,
    build_effective_config,
    delete_llm_model,
    load_public_config,
    update_llm_model,
)
from config.toml_writer import dumps_public_config
from core.web.services import config_service
from tests import select_tests


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "config"
SCHEMA_V2_LEGACY_WRITE_MESSAGE = (
    "schema v2 model writes must use provider-scoped configuration; "
    "use migration preview for schema v1 configuration"
)


def _fixture(name: str) -> dict:
    return tomllib.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_v2_toml_round_trip_preserves_provider_scoped_models(tmp_path) -> None:
    source = _fixture("llm_schema_v2_provider.toml")
    path = tmp_path / "config.toml"
    path.write_text(dumps_public_config(source), encoding="utf-8")
    loaded = load_public_config(path)
    assert loaded == source
    effective = build_effective_config(loaded)
    assert set(effective.llm.providers) == {"pixel_relay", "lab_llamacpp_a"}
    assert "pixel_relay/gpt-5.6-luna" in effective.llm.model_library
    assert effective.llm.model_library["lab_llamacpp_a/qwen3.6-35b-a3b"]["model"] == "qwen3.6-35b-a3b"


def test_v2_responses_relay_defaults_prompt_cache_without_enabling_local_cache() -> None:
    source = _fixture("llm_schema_v2_provider.toml")

    effective = build_effective_config(source)

    assert effective.llm.model_library["pixel_relay/gpt-5.6-luna"]["prompt_cache"] == {
        "mode": "automatic"
    }
    assert effective.llm.get_profile("primary").prompt_cache.mode == "automatic"
    assert "prompt_cache" not in effective.llm.model_library["lab_llamacpp_a/qwen3.6-35b-a3b"]
    assert effective.llm.get_profile("local").prompt_cache.mode == "disabled"


def test_v2_responses_relay_preserves_explicit_disabled_prompt_cache() -> None:
    source = _fixture("llm_schema_v2_provider.toml")
    source["llm"]["providers"]["pixel_relay"]["models"]["gpt-5.6-luna"]["defaults"]["prompt_cache"] = {
        "mode": "disabled"
    }

    effective = build_effective_config(source)

    assert effective.llm.model_library["pixel_relay/gpt-5.6-luna"]["prompt_cache"] == {
        "mode": "disabled"
    }
    assert effective.llm.get_profile("primary").prompt_cache.mode == "disabled"


def test_config_load_never_calls_discovery(monkeypatch, tmp_path) -> None:
    source = _fixture("llm_schema_v2_provider.toml")
    path = tmp_path / "config.toml"
    path.write_text(dumps_public_config(source), encoding="utf-8")
    monkeypatch.setattr(
        "core.llm.provider_discovery.service.discover_provider_models",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network discovery called")),
    )
    build_effective_config(load_public_config(path))


def test_alias_is_read_only_and_new_writes_are_canonical() -> None:
    source = _fixture("llm_schema_v2_provider.toml")
    source["llm"]["model_aliases"] = {"legacy_gpt": "pixel_relay/gpt-5.6-luna"}
    effective = build_effective_config(source)
    assert effective.llm.model_aliases["legacy_gpt"] == "pixel_relay/gpt-5.6-luna"
    assert set(effective.llm.model_library) == {
        "pixel_relay/gpt-5.6-luna",
        "lab_llamacpp_a/qwen3.6-35b-a3b",
    }


def test_v1_fixture_remains_readable_and_migration_preview_is_write_free(tmp_path) -> None:
    source = _fixture("llm_schema_v1_inline.toml")
    before = copy.deepcopy(source)
    effective = build_effective_config(source)
    preview = preview_v1_to_v2(source, project_root=tmp_path)

    assert effective.llm.schema_version == 1
    assert effective.llm.get_profile("primary").model == "gpt-5.6-luna"
    assert preview.proposed_public_config["llm"]["schema_version"] == 2
    assert preview.model_ref_map["relay_text"].endswith("/gpt-5.6-luna")
    assert source == before
    assert list(tmp_path.rglob("*")) == []


def test_migrated_runtime_projection_uses_split_upstream_id_not_artifact_path(tmp_path) -> None:
    artifact_path = r"C:\models\private\weights.gguf"
    source = {
        "llm": {
            "model_library": {
                "local_a": {
                    "provider": {
                        "kind": "local",
                        "base_url": "http://127.0.0.1:8080/v1",
                        "requires_api_key": False,
                    },
                    "model": artifact_path,
                    "label": artifact_path,
                    "transport": "chat_completions",
                    "contract": "tool_chat",
                }
            },
            "profiles": {"primary": {"model_ref": "local_a"}},
        }
    }

    preview = preview_v1_to_v2(
        source,
        project_root=tmp_path,
        artifact_resolutions=[
            {
                "modelId": "local_a",
                "decision": "split_deployment_artifact",
                "upstreamId": "served-model-a",
            }
        ],
    )
    effective = build_effective_config(preview.proposed_public_config)
    provider_id = preview.model_ref_map["local_a"].split("/", 1)[0]

    assert effective.llm.get_profile("primary").model == "served-model-a"
    assert effective.llm.providers[provider_id].deployment.artifact_path == artifact_path


def test_schema_v2_inline_provider_materializer_is_inert() -> None:
    source = _fixture("llm_schema_v2_provider.toml")
    llm = copy.deepcopy(source["llm"])
    before = copy.deepcopy(llm)

    config_settings._materialize_inline_llm_providers(llm)

    assert llm == before


def test_fresh_install_starters_are_schema_v2_bootstrap_from_fixed_templates() -> None:
    starter = CONFIG_STARTER_TEXT
    example = EXAMPLE_CONFIG_STARTER_TEXT
    expected_starter = render_default_operator_config_text(example=False)
    expected_example = render_default_operator_config_text(example=True)

    assert starter == expected_starter
    assert example == expected_example
    assert starter.startswith("# Vibelution operator config")
    assert example.startswith("# Vibelution example operator config")

    payload = tomllib.loads(starter)
    assert payload["llm"]["schema_version"] == 2
    providers = payload["llm"]["providers"]
    assert "local_openai" in providers
    # Vendor templates materialize as provider instances (not only local placeholder).
    assert len(providers) >= 5
    assert "openai_main" in providers or "relay_openai" in providers or "deepseek_main" in providers
    for provider in providers.values():
        assert "credential_ref" in provider
        assert "api_key" not in provider
    assert build_effective_config(payload).llm.schema_version == 2
    assert not is_thin_local_only_starter(payload)


@pytest.mark.parametrize(
    "write",
    [
        lambda source: apply_llm_model_preset(source, "relay_gpt_5_6_luna"),
        lambda source: add_llm_model(source, "legacy", "pixel_relay", "legacy"),
        lambda source: update_llm_model(source, "legacy", "pixel_relay", "legacy"),
        lambda source: delete_llm_model(source, "legacy"),
    ],
)
def test_schema_v2_public_model_library_writes_are_rejected(write) -> None:
    with pytest.raises(ValueError, match=f"^{SCHEMA_V2_LEGACY_WRITE_MESSAGE}$"):
        write(_fixture("llm_schema_v2_provider.toml"))


@pytest.mark.parametrize(
    "write",
    [
        lambda source: config_service.draft_add_model(
            source,
            model_id="legacy",
            provider="pixel_relay",
            model="legacy",
        ),
        lambda source: config_service.draft_update_model(
            source,
            model_id="legacy",
            provider="pixel_relay",
            model="legacy",
        ),
        lambda source: config_service.draft_delete_model(source, model_id="legacy"),
    ],
)
def test_schema_v2_legacy_model_routes_reject_before_operator_or_network_access(monkeypatch, write) -> None:
    monkeypatch.setattr(
        config_service,
        "load_public_config",
        lambda: (_ for _ in ()).throw(AssertionError("operator config accessed")),
    )
    monkeypatch.setattr(
        "core.llm.provider_discovery.service.discover_provider_models",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network discovery called")),
    )

    with pytest.raises(ValueError, match=f"^{SCHEMA_V2_LEGACY_WRITE_MESSAGE}$"):
        write(_fixture("llm_schema_v2_provider.toml"))


def test_schema_v2_legacy_discovery_route_rejects_before_operator_or_network_access(monkeypatch) -> None:
    monkeypatch.setattr(
        config_service,
        "load_public_config",
        lambda: (_ for _ in ()).throw(AssertionError("operator config accessed")),
    )
    monkeypatch.setattr(
        "core.llm.provider_discovery.service.discover_provider_models",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network discovery called")),
    )

    with pytest.raises(
        ValueError,
        match=r"^provider_id is required for schema v2 provider-scoped discovery; .*migration preview.*$",
    ):
        config_service.discover_config_models(_fixture("llm_schema_v2_provider.toml"))


def test_selector_adds_provider_config_protocol_matrix_for_convergence_paths() -> None:
    changed = [
        "config/llm_identity.py",
        "config/model_catalog.py",
        "config/model_config_migration.py",
        "core/llm/provider_discovery/service.py",
        "core/web/services/provider_config_service.py",
        "web/src/routes/ConfigProviderDetailPanel.tsx",
        "web/src/routes/configProviderLogic.ts",
    ]
    result = select_tests.select_tests(changed, select_tests.load_matrix())
    rule = next(rule for rule in result["matchedRules"] if rule["id"] == "llm-provider-config-v2")

    assert set(rule["matchedFiles"]) == set(changed)
    assert any("tests/test_llm_config_v2_integration.py" in command for command in result["commands"])
    assert any("tests/test_llm_protocol_resolver.py" in command for command in result["commands"])
    assert (
        "node web/node_modules/vitest/vitest.mjs run src/routes/configProviderLogic.test.ts "
        "src/routes/configRouteLogic.test.ts src/routes/ConfigRoute.layout.test.ts"
    ) in result["commands"]
    assert "npm --prefix web run build" in result["commands"]
