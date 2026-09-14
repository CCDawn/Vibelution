"""Config editor + bootstrap single-source contracts."""

from __future__ import annotations

import core.web.services.config_editor_schema as editor_schema
from config import editor_schema_data
from config.models import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_ROLE_PROFILE_IDS,
    IMPLICIT_DEFAULT_PROVIDER_CONTEXT_WINDOW,
    PROFILE_LABELS,
    UNCONFIGURED_PROVIDER_CONTEXT_WINDOW,
    VALID_AGENT_MODES,
    LLMConfig,
    LLMProfile,
    PinnedModelDefaults,
)
from config.operator_bootstrap import _BOOTSTRAP_EXCLUDED_PROFILE_IDS, _PROFILE_IDS
from config.settings import _unconfigured_profile_stub
from core.web.services import config_service
from scripts import config_panel


def test_editor_option_lists_have_single_source() -> None:
    assert config_panel.RUNTIME_PROFILE_OPTIONS is editor_schema_data.RUNTIME_PROFILE_OPTIONS
    assert editor_schema.RUNTIME_PROFILE_OPTIONS is editor_schema_data.RUNTIME_PROFILE_OPTIONS
    assert config_panel.SEGMENTATION_STRATEGY_OPTIONS is editor_schema_data.SEGMENTATION_STRATEGY_OPTIONS
    assert editor_schema.SEGMENTATION_STRATEGY_OPTIONS is editor_schema_data.SEGMENTATION_STRATEGY_OPTIONS
    assert config_panel.AVATAR_PRESET_OPTIONS is editor_schema_data.AVATAR_PRESET_OPTIONS
    assert editor_schema.AVATAR_PRESET_OPTIONS is editor_schema_data.AVATAR_PRESET_OPTIONS
    assert config_panel.AGENT_MODE_OPTIONS == list(VALID_AGENT_MODES)
    assert editor_schema_data.AGENT_MODE_OPTIONS == list(VALID_AGENT_MODES)


def test_shared_editor_label_tables_are_single_source() -> None:
    for table_name in ("SECTION_LABELS", "FIELD_LABELS", "FIELD_HINTS"):
        shared = getattr(editor_schema_data, table_name)
        assert getattr(editor_schema, table_name) is shared

        panel_table = getattr(config_panel, table_name)
        for lang in ("zh", "en"):
            for key, value in shared[lang].items():
                assert panel_table[lang][key] == value, f"{table_name}.{lang}.{key}"


def test_bootstrap_profile_ids_derive_from_default_role_profile_ids() -> None:
    assert _PROFILE_IDS == tuple(
        profile_id
        for profile_id in DEFAULT_ROLE_PROFILE_IDS
        if profile_id not in _BOOTSTRAP_EXCLUDED_PROFILE_IDS
    )
    assert set(_PROFILE_IDS).isdisjoint(_BOOTSTRAP_EXCLUDED_PROFILE_IDS)


def test_default_max_output_tokens_has_single_constant() -> None:
    assert LLMProfile.model_fields["max_output_tokens"].default == DEFAULT_MAX_OUTPUT_TOKENS
    assert PinnedModelDefaults.model_fields["max_output_tokens"].default == DEFAULT_MAX_OUTPUT_TOKENS


def test_profile_labels_have_single_source() -> None:
    assert config_service.PROFILE_LABELS is PROFILE_LABELS
    assert set(PROFILE_LABELS) == set(DEFAULT_ROLE_PROFILE_IDS)
    for lang in ("zh", "en"):
        panel_table = config_panel.IDENTIFIER_LABELS[lang]["profile_id"]
        for profile_id, labels in PROFILE_LABELS.items():
            assert panel_table[profile_id] == labels[lang], f"profile_id.{profile_id}.{lang}"


def test_context_window_seed_defaults_have_single_constants() -> None:
    seeded = LLMConfig()
    assert (
        seeded.providers["default"].context_window
        == IMPLICIT_DEFAULT_PROVIDER_CONTEXT_WINDOW
    )
    stub_provider = _unconfigured_profile_stub()["provider"]
    assert stub_provider["context_window"] == UNCONFIGURED_PROVIDER_CONTEXT_WINDOW
