"""Decision models stay a local catalog beside the chat model library."""

import pytest
from pydantic import ValidationError

from config.decision_models import (
    DECISION_MODEL_PRESETS,
    bound_decision_model,
    normalize_decision_base_url,
    validate_decision_catalog,
)
from config.models import AppConfig, LLMConfig
from config.public_config import list_llm_model_options
from config.settings import normalize_public_config_dict
from core.research.operator_optimization.d1_action import decision_reason_name
from tests.test_llm_config_schema_v2 import _v2_config


def _entry(**overrides):
    payload = {
        "label": "d1-3B",
        "model_id": "LiquidAI/d1-3B",
        "base_url": "http://127.0.0.1:8088/v1/systemone",
        "min_probability": 0.80,
        "enabled": True,
        "note": "",
    }
    payload.update(overrides)
    return payload


def test_presets_cover_the_local_decision_class():
    assert [item.preset_id for item in DECISION_MODEL_PRESETS] == [
        "d1-3b",
        "julia-1",
        "laya",
        "kev-4b",
        "lev",
        "openjev",
    ]
    openjev = DECISION_MODEL_PRESETS[-1]
    assert "非商用" in openjev.note_zh
    assert "27B" in openjev.note_zh


def test_empty_path_becomes_systemone_and_other_paths_are_rejected():
    assert normalize_decision_base_url("http://127.0.0.1:8088") == (
        "http://127.0.0.1:8088/v1/systemone"
    )
    assert normalize_decision_base_url("http://127.0.0.1:8088/") == (
        "http://127.0.0.1:8088/v1/systemone"
    )
    with pytest.raises(ValueError, match="local"):
        normalize_decision_base_url("https://example.com/v1/systemone")
    with pytest.raises(ValueError, match="/v1/systemone"):
        normalize_decision_base_url("http://127.0.0.1:8088/v1/chat/completions")


def test_handoff_must_name_one_enabled_entry():
    catalog = validate_decision_catalog({"d1-3b": _entry()}, "")
    assert catalog["d1-3b"]["base_url"].endswith("/v1/systemone")
    with pytest.raises(ValueError, match="enabled"):
        validate_decision_catalog({"d1-3b": _entry(enabled=False)}, "d1-3b")
    with pytest.raises(ValueError, match="enabled"):
        validate_decision_catalog({"d1-3b": _entry()}, "missing")
    assert bound_decision_model({"d1-3b": _entry()}, "") is None
    assert bound_decision_model({"d1-3b": _entry(enabled=False)}, "d1-3b") is None
    bound = bound_decision_model({"d1-3b": _entry()}, "d1-3b")
    assert bound["id"] == "d1-3b"
    assert bound["model_id"] == "LiquidAI/d1-3B"


def test_catalog_rejects_remote_ids_and_too_many_entries():
    with pytest.raises(ValueError, match="id"):
        validate_decision_catalog({"D1": _entry()}, "")
    with pytest.raises(ValueError, match="24"):
        validate_decision_catalog(
            {f"m{index}": _entry(label=f"M{index}") for index in range(25)},
            "",
        )


def test_llm_config_keeps_decision_models_out_of_chat_options():
    config = LLMConfig.model_validate({
        "decision_models": {"d1-3b": _entry(base_url="http://127.0.0.1:8088")},
        "decision_handoff_model_id": "d1-3b",
    })
    assert config.decision_models["d1-3b"].base_url == "http://127.0.0.1:8088/v1/systemone"
    assert "d1-3b" not in config.model_library
    assert config.decision_handoff_model_id == "d1-3b"
    with pytest.raises(ValidationError, match="enabled"):
        LLMConfig.model_validate({
            "decision_models": {"d1-3b": _entry(enabled=False)},
            "decision_handoff_model_id": "d1-3b",
        })


def test_public_config_accepts_the_decision_catalog_keys():
    raw = _v2_config()
    raw["llm"]["decision_models"] = {"d1-3b": _entry(base_url="http://127.0.0.1:8088")}
    raw["llm"]["decision_handoff_model_id"] = "d1-3b"
    normalized = normalize_public_config_dict(raw)
    assert normalized["llm"]["decision_models"]["d1-3b"]["model_id"] == "LiquidAI/d1-3B"
    app = AppConfig.model_validate(normalized)
    assert app.llm.decision_models["d1-3b"].base_url == "http://127.0.0.1:8088/v1/systemone"
    assert app.llm.decision_handoff_model_id == "d1-3b"
    rendered = str(list_llm_model_options(raw))
    assert "LiquidAI/d1-3B" not in rendered
    assert "julia-1" not in rendered
    bad = _v2_config()
    bad["llm"]["surprise"] = True
    with pytest.raises(ValueError, match="Unsupported"):
        normalize_public_config_dict(bad)
    assert decision_reason_name("LiquidAI/d1-3B") == "d1-3B"
    assert decision_reason_name("ggml-org/Julia-1-GGUF") == "ggml-org/Julia-1-GGUF"
