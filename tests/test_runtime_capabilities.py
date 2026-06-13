from __future__ import annotations

from config.runtime_capabilities import apply_model_capability_overrides, record_model_image_input_capability


def _public_config(model_entry: dict) -> dict:
    return {
        "llm": {
            "model_library": {
                "vision_model": {
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
        "vision_model",
        {
            "supports_image_input": True,
            "capability_status": "supported",
            "capability_checked_at": "2026-06-13T18:30:58Z",
        },
        cache_path=cache_path,
    )

    updated = apply_model_capability_overrides(public_config, cache_path=cache_path)

    model = updated["llm"]["model_library"]["vision_model"]
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
        "vision_model",
        {
            "supports_image_input": False,
            "capability_status": "unsupported",
            "capability_checked_at": "2026-06-13T18:30:58Z",
            "capability_error": "image input is not supported by this model route",
        },
        cache_path=cache_path,
    )

    updated = apply_model_capability_overrides(public_config, cache_path=cache_path)

    model = updated["llm"]["model_library"]["vision_model"]
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
        "vision_model",
        {
            "supports_image_input": True,
            "capability_status": "supported",
            "capability_checked_at": "2026-06-13T18:30:58Z",
        },
        cache_path=cache_path,
    )

    updated = apply_model_capability_overrides(public_config, cache_path=cache_path)

    model = updated["llm"]["model_library"]["vision_model"]
    assert model["supports_image_input"] is False
    assert model["capability_status"] == "unsupported"
    assert model["capability_source"] == "manual_config"


def test_runtime_image_capability_cache_does_not_override_legacy_explicit_support(tmp_path):
    cache_path = tmp_path / "model-capabilities.json"
    public_config = _public_config({"supports_image_input": True, "capability_status": "supported"})
    record_model_image_input_capability(
        "vision_model",
        {
            "supports_image_input": False,
            "capability_status": "unsupported",
            "capability_checked_at": "2026-06-13T18:30:58Z",
        },
        cache_path=cache_path,
    )

    updated = apply_model_capability_overrides(public_config, cache_path=cache_path)

    model = updated["llm"]["model_library"]["vision_model"]
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
        "vision_model",
        {
            "supports_image_input": False,
            "capability_status": "unsupported",
            "capability_checked_at": "2026-06-13T18:30:58Z",
        },
        cache_path=cache_path,
    )

    updated = apply_model_capability_overrides(public_config, cache_path=cache_path)

    model = updated["llm"]["model_library"]["vision_model"]
    assert model["supports_image_input"] is False
    assert model["capability_status"] == "unsupported"
    assert model["capability_source"] == "runtime_probe"
