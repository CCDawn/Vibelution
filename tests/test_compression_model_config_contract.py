"""compression_model / compression_temperature are retired selectors.

Compression LLM selection lives on the Agent summary slot
(AGENT_LLM_SLOT_SUMMARY), not on a global config profile. The two fields
stay for config compatibility but must say so, so nobody re-wires them as
if they selected the compressor model.
"""

from __future__ import annotations

from config.models import ContextCompressionConfig


def test_compression_model_is_marked_retired():
    description = ContextCompressionConfig.model_fields["compression_model"].description or ""
    assert "已退役" in description
    assert "summary slot" in description


def test_compression_temperature_is_marked_retired():
    description = ContextCompressionConfig.model_fields["compression_temperature"].description or ""
    assert "已退役" in description
    assert "summary slot" in description


def test_defaults_stay_for_config_compatibility():
    config = ContextCompressionConfig()
    assert config.compression_model == "qwen-turbo"
    assert config.compression_temperature == 0.3
