from __future__ import annotations

import json

import pytest

from config.model_catalog import load_model_catalog_state
from config.runtime_capabilities import (
    apply_model_capability_overrides,
    record_model_image_input_capability,
    upgrade_legacy_capability_cache_if_needed,
)


MODEL_REF = "relay/vision-model"


def _public_config(model_entry: dict) -> dict:
    return {
        "llm": {
            "model_library": {
                MODEL_REF: {
                    "label": "Vision Model",
                    "model": "vision-model",
                    **model_entry,
                }
            }
        }
    }


def test_runtime_image_capability_cache_fills_unknown_model(tmp_path):
    cache_path = tmp_path / "model-capabilities.json"
    public_config = _public_config({})
    record_model_image_input_capability(
        MODEL_REF,
        {
            "supports_image_input": True,
            "capability_status": "supported",
            "capability_checked_at": "2026-06-13T18:30:58Z",
        },
        cache_path=cache_path,
    )

    updated = apply_model_capability_overrides(public_config, cache_path=cache_path)

    model = updated["llm"]["model_library"][MODEL_REF]
    assert model["supports_image_input"] is True
    assert model["capability_status"] == "supported"
    assert model["capability_source"] == "runtime_probe"


def test_runtime_image_capability_cache_does_not_override_manual_support(tmp_path):
    cache_path = tmp_path / "model-capabilities.json"
    public_config = _public_config(
        {
            "supports_image_input": True,
            "capability_status": "supported",
            "capability_source": "manual",
        }
    )
    record_model_image_input_capability(
        MODEL_REF,
        {
            "supports_image_input": False,
            "capability_status": "unsupported",
            "capability_checked_at": "2026-06-13T18:30:58Z",
            "capability_error": "image input is not supported by this model route",
        },
        cache_path=cache_path,
    )

    updated = apply_model_capability_overrides(public_config, cache_path=cache_path)

    model = updated["llm"]["model_library"][MODEL_REF]
    assert model["supports_image_input"] is True
    assert model["capability_status"] == "supported"
    assert model["capability_source"] == "manual"
    assert "capability_checked_at" not in model
    assert "capability_error" not in model


def test_runtime_image_capability_cache_does_not_override_manual_unsupported(tmp_path):
    cache_path = tmp_path / "model-capabilities.json"
    public_config = _public_config(
        {
            "supports_image_input": False,
            "capability_status": "unsupported",
            "capability_source": "manual_config",
        }
    )
    record_model_image_input_capability(
        MODEL_REF,
        {
            "supports_image_input": True,
            "capability_status": "supported",
            "capability_checked_at": "2026-06-13T18:30:58Z",
        },
        cache_path=cache_path,
    )

    updated = apply_model_capability_overrides(public_config, cache_path=cache_path)

    model = updated["llm"]["model_library"][MODEL_REF]
    assert model["supports_image_input"] is False
    assert model["capability_status"] == "unsupported"
    assert model["capability_source"] == "manual_config"


def test_runtime_image_capability_cache_does_not_override_legacy_explicit_support(tmp_path):
    cache_path = tmp_path / "model-capabilities.json"
    public_config = _public_config({"supports_image_input": True, "capability_status": "supported"})
    record_model_image_input_capability(
        MODEL_REF,
        {
            "supports_image_input": False,
            "capability_status": "unsupported",
            "capability_checked_at": "2026-06-13T18:30:58Z",
        },
        cache_path=cache_path,
    )

    updated = apply_model_capability_overrides(public_config, cache_path=cache_path)

    model = updated["llm"]["model_library"][MODEL_REF]
    assert model["supports_image_input"] is True
    assert model["capability_status"] == "supported"
    assert "capability_source" not in model


def test_runtime_image_capability_cache_can_refine_preset_support(tmp_path):
    cache_path = tmp_path / "model-capabilities.json"
    public_config = _public_config(
        {
            "supports_image_input": True,
            "capability_status": "supported",
            "capability_source": "preset",
        }
    )
    record_model_image_input_capability(
        MODEL_REF,
        {
            "supports_image_input": False,
            "capability_status": "unsupported",
            "capability_checked_at": "2026-06-13T18:30:58Z",
        },
        cache_path=cache_path,
    )

    updated = apply_model_capability_overrides(public_config, cache_path=cache_path)

    model = updated["llm"]["model_library"][MODEL_REF]
    assert model["supports_image_input"] is False
    assert model["capability_status"] == "unsupported"
    assert model["capability_source"] == "runtime_probe"


def test_runtime_capability_live_write_rejects_flat_model_id(tmp_path):
    with pytest.raises(ValueError, match="model_ref must use provider_id/model_key"):
        record_model_image_input_capability(
            "vision_model",
            {"capability_status": "supported"},
            cache_path=tmp_path / "model-capabilities.json",
        )
    assert not (tmp_path / "model-catalog-state.json").exists()


def test_runtime_capability_live_read_ignores_flat_model_id(tmp_path):
    catalog_path = tmp_path / "model-catalog-state.json"
    record_model_image_input_capability(
        MODEL_REF,
        {"capability_status": "supported"},
        cache_path=catalog_path,
    )
    public_config = {
        "llm": {
            "model_library": {
                "vision_model": {"model": "vision-model"},
            }
        }
    }

    updated = apply_model_capability_overrides(public_config, cache_path=catalog_path)

    assert "supports_image_input" not in updated["llm"]["model_library"]["vision_model"]


@pytest.mark.parametrize(
    "secret_shaped_error",
    [
        "sk_liveABC123XYZ",
        "Bearer dummyTokenABC123",
        "https://relay.example/error?api_key=dummyTokenABC123",
    ],
)
def test_runtime_capability_error_never_returns_or_persists_raw_secret(tmp_path, secret_shaped_error):
    result = record_model_image_input_capability(
        MODEL_REF,
        {
            "capability_status": "unknown",
            "capability_error": secret_shaped_error,
        },
        cache_path=tmp_path / "model-catalog-state.json",
    )
    state_text = (tmp_path / "model-catalog-state.json").read_text(encoding="utf-8")
    assert result["capability_error"] == "runtime capability probe failed"
    assert secret_shaped_error not in repr(result)
    assert secret_shaped_error not in state_text
    assert '"error": "other"' in state_text


def test_upgrader_corrupt_json_marks_complete_without_clobbering_catalog(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    catalog_path = tmp_path / "model-catalog-state.json"
    legacy_path = tmp_path / "model-capabilities.json"
    config_path.write_text("[llm]\nschema_version = 2\n", encoding="utf-8")
    catalog_path.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "providers": {
                    "relay": {
                        "models": {
                            "gpt-a": {"upstreamId": "gpt-a", "availability": "unknown"},
                        }
                    }
                },
                "metadata": {"legacyCapabilityImportCompleted": False, "keep": True},
            }
        ),
        encoding="utf-8",
    )
    legacy_path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("VIBELUTION_MODEL_CAPABILITY_CACHE", raising=False)

    upgrade_legacy_capability_cache_if_needed({"llm": {}}, config_path=config_path)

    catalog = load_model_catalog_state(catalog_path)
    assert catalog["metadata"]["legacyCapabilityImportCompleted"] is True
    assert catalog["metadata"]["keep"] is True
    assert catalog["providers"]["relay"]["models"]["gpt-a"]["upstreamId"] == "gpt-a"
    assert legacy_path.read_text(encoding="utf-8") == "{not json"


def test_upgrader_write_failure_restores_original_catalog(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    catalog_path = tmp_path / "model-catalog-state.json"
    legacy_path = tmp_path / "model-capabilities.json"
    original = json.dumps(
        {
            "schemaVersion": 2,
            "providers": {},
            "metadata": {"legacyCapabilityImportCompleted": False, "marker": "original"},
        },
        indent=2,
    )
    config_path.write_text("[llm]\nschema_version = 2\n", encoding="utf-8")
    catalog_path.write_text(original, encoding="utf-8")
    legacy_path.write_text('{"schemaVersion": 1, "models": {}}', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("VIBELUTION_MODEL_CAPABILITY_CACHE", raising=False)

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("config.runtime_capabilities.save_model_catalog_state", _boom)
    with pytest.raises(OSError, match="disk full"):
        upgrade_legacy_capability_cache_if_needed({"llm": {}}, config_path=config_path)

    assert catalog_path.read_text(encoding="utf-8") == original
    assert json.loads(catalog_path.read_text(encoding="utf-8"))["metadata"]["marker"] == "original"
