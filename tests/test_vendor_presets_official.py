"""Official vendor presets (zhipu / moonshot / volcengine / openrouter)."""

from __future__ import annotations

import pytest

from config.llm_security import _REMOTE_PROVIDER_HOSTS, validate_llm_provider_target
from config.models import PROVIDER_API_KEY_ENV_MAP
from config.public_config import LLM_MODEL_PRESETS

OFFICIAL_PRESET_IDS = (
    "zhipu_glm_4_7",
    "moonshot_kimi_k2_5",
    "volcengine_doubao_seed_1_6",
    "openrouter_aggregator",
)


def test_official_presets_exist_with_required_fields() -> None:
    for preset_id in OFFICIAL_PRESET_IDS:
        preset = LLM_MODEL_PRESETS[preset_id]
        provider = preset["provider"]
        model = preset["model"]
        assert provider["kind"] and provider["base_url"].startswith("https://")
        assert provider["requires_api_key"] is True
        assert provider["api_key_env"], preset_id
        assert model["model"] and model["transport"] == "chat_completions"
        assert model["discovery_enabled"] is True


@pytest.mark.parametrize("preset_id", OFFICIAL_PRESET_IDS)
def test_official_preset_base_urls_pass_security_gate(preset_id: str) -> None:
    provider = LLM_MODEL_PRESETS[preset_id]["provider"]
    host = provider["base_url"].split("//", 1)[1].split("/", 1)[0]
    assert host in _REMOTE_PROVIDER_HOSTS[provider["kind"]], (
        f"{preset_id}: host {host} not whitelisted for kind {provider['kind']}"
    )
    validate_llm_provider_target(
        {
            "kind": provider["kind"],
            "base_url": provider["base_url"],
            "api_key_env": provider["api_key_env"],
            "requires_api_key": True,
        },
        context=f"preset.{preset_id}",
    )


def test_official_provider_kinds_have_api_key_env() -> None:
    for kind in ("zhipu", "moonshot", "volcengine", "openrouter"):
        assert PROVIDER_API_KEY_ENV_MAP[kind]
