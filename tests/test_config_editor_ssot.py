"""Config editor + bootstrap single-source contracts."""

from __future__ import annotations

import re
from pathlib import Path

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

_WEB_SRC = Path(__file__).resolve().parents[1] / "web" / "src" / "routes"


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


def test_number_editor_meta_passes_through_pydantic_bounds_and_units() -> None:
    """Wave-1 settings alignment: number rows get read-only schema bounds + units."""
    public_config = {
        "context_compression": {
            "enabled": True,
            "max_token_limit": 16000,
            "compression_temperature": 0.3,
            "micro_compact_tool_whitelist": ["read_file_tool"],
        },
        "runtime": {"profile": "balanced"},
    }
    meta = editor_schema.build_editor_meta(public_config, "zh")

    token_limit = meta["context_compression.max_token_limit"]
    assert token_limit["kind"] == "number"
    # config.models declares max_token_limit with gt=0 -> exclusive minimum.
    assert token_limit["exclusiveMinimum"] == 0.0
    assert "minimum" not in token_limit
    # Badge "Token" carries the physical unit; localized for display.
    assert token_limit["unit"] == "令牌"

    temperature = meta["context_compression.compression_temperature"]
    assert temperature["minimum"] == 0.0
    assert temperature["maximum"] == 2.0
    # "Number" numbers carry no invented unit or bounds.
    assert "unit" not in temperature

    whitelist = meta["context_compression.micro_compact_tool_whitelist"]
    assert whitelist["kind"] == "string_list"
    assert "minimum" not in whitelist and "maximum" not in whitelist

    # English display unit follows the requested language.
    meta_en = editor_schema.build_editor_meta(public_config, "en")
    assert meta_en["context_compression.max_token_limit"]["unit"] == "Token"


# ---------------------------------------------------------------------------
# Settings-align wave 3 — settings section registration + field copy SSOT
# ---------------------------------------------------------------------------


def _frontend_navigation_source() -> str:
    return (_WEB_SRC / "ConfigSettingsNavigation.tsx").read_text(encoding="utf-8")


def _frontend_declared_section_vocabulary() -> tuple[set[str], set[tuple[str, str]]]:
    """Extract (group ids, (group, page) pairs) declared in PAGE_DEFINITIONS.

    Pages declared via the FALLBACK_PAGE_ID constant are intentionally excluded:
    the fallback page is a frontend-only safety net, never a backend-assignable
    membership target.
    """
    source = _frontend_navigation_source()
    block_match = re.search(
        r"const PAGE_DEFINITIONS: Record<ConfigSettingsGroupId, readonly PageDefinition\[\]> = \{(.*?)\n\};",
        source,
        re.S,
    )
    assert block_match, "PAGE_DEFINITIONS table not found"
    block = block_match.group(1)
    groups: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for group_match in re.finditer(r'"([a-z-]+)":\s*\[\n(.*?)\n  \],', block, re.S):
        group_id = group_match.group(1)
        groups.add(group_id)
        for page_id in re.findall(r'\{ id: "([a-z-]+)", zh:', group_match.group(2)):
            pairs.add((group_id, page_id))
    return groups, pairs


def test_settings_sections_carry_backend_group_page_membership() -> None:
    """Wave-3 SSOT: `_config_sections` is the only registration authority.

    Every emitted section (fixed + editor-derived) must carry group/page
    membership drawn from the frontend-declared vocabulary, so a newly
    registered backend section appears in the settings workbench with zero
    frontend edits (acceptance script lives in
    web/src/routes/configSettingsNavigationSsot.test.ts).
    """
    representative_config = {
        "ui": {"max_log_entries": 100},
        "network": {"timeout": 30},
        "session_recovery": {"enabled": True, "max_auto_retries": 2},
    }
    editor_sections = editor_schema.build_editor_sections(representative_config, "zh")
    sections = config_service._config_sections("zh", editor_sections)
    assert sections, "settings sections payload must not be empty"

    missing_membership = [section["id"] for section in sections if not section.get("group") or not section.get("page")]
    assert missing_membership == []

    declared_groups, declared_pairs = _frontend_declared_section_vocabulary()
    unknown_groups = sorted({section["group"] for section in sections} - declared_groups)
    unknown_pairs = sorted(
        (section["group"], section["page"])
        for section in sections
        if (section["group"], section["page"]) not in declared_pairs
    )
    assert unknown_groups == []
    assert unknown_pairs == []

    # Membership is an additive, optional API field: legacy consumers reading
    # only id/title/summary keep working.
    assert set(sections[0]) >= {"id", "title", "summary", "group", "page"}


def test_every_backend_editor_field_has_zh_frontend_copy() -> None:
    """Every field of every backend editor section has a zh copy entry in
    configSectionPresentation.ts (labels may be copied verbatim from the
    backend meta; hints may fall through to the backend)."""
    representative_config = {
        "avatar": {"preset": "cat"},
        "user_profile": {
            "display_name": "op",
            "avatar_preset": "cat",
            "avatar_image_path": "",
            "bio": "",
            "preferences": {},
        },
        "context_compression": {
            "enabled": True,
            "max_token_limit": 16000,
            "keep_recent_steps": 5,
            "summary_max_chars": 1000,
            "compression_model": "qwen",
            "compression_temperature": 0.3,
            "max_compressions_per_session": 5,
            "effectiveness_threshold": 0.1,
            "levels": {"light": 0.6, "standard": 0.75, "deep": 0.9, "emergency": 0.98},
            "summary_chars": {"light": 500, "standard": 800, "deep": 1200, "emergency": 2000},
            "preservation": {"keep_ai_messages": 10, "preserve_errors": True, "extract_key_decisions": True},
            "micro_compact_tool_whitelist": ["read_file_tool"],
        },
        "session_recovery": {"enabled": True, "max_auto_retries": 2},
        "security": {
            "enabled": True,
            "allowed_directories": ["."],
            "forbidden_patterns": [],
            "forbidden_delete_patterns": [],
            "dangerous_commands": [],
        },
        "log": {
            "level": "INFO",
            "format": "",
            "date_format": "",
            "file_enabled": True,
            "file_path": "logs/app.log",
            "max_file_size": 10,
            "backup_count": 3,
            "detailed_traceback": True,
            "third_party": {"httpx": "WARNING", "openai": "WARNING"},
        },
        "network": {
            "timeout": 30,
            "user_agent": "",
            "max_retries": 2,
            "retry_delay": 1,
            "verify_ssl": True,
            "proxy_enabled": False,
            "proxy_url": "",
        },
        "analysis": {"data_dir": "a", "feedback_dir": "b", "knowledge_graph_path": "c", "pattern_library_path": "d"},
        "git": {"commit_message_model_ref": "m", "commit_message_prompt": "p"},
        "ui": {
            "max_log_entries": 100,
            "refresh_rate": 5,
            "show_ascii_art": True,
            "show_welcome": True,
            "workbench_theme": {"background_image_path": "", "background_readability": "standard"},
        },
        "parser": {"strip_tags": [], "strip_thinking_alias": []},
        "debug": {"enabled": True, "verbose": False, "track_token_usage": True},
        "pet": {
            "enabled": True,
            "name": "pet",
            "auto_save": True,
            "save_interval": 60,
            "gene": {"inherit_from_model": True, "context_window_factor": 1.0},
            "heart": {"enabled": True, "active_rate": 1.0, "idle_rate": 0.5, "cooldown_time": 1},
            "dream": {"enabled": True, "compression_triggers_dream": True, "dream_duration": 10, "keep_key_memory_ratio": 0.5},
            "personality": {"enabled": True, "learning_window": 10, "trait_change_rate": 0.1},
            "hunger": {"enabled": True, "food_per_meal": 10, "hunger_decay_rate": 0.1, "mood_decay_rate": 0.1, "auto_feed_threshold": 30},
            "diary": {"enabled": True, "max_entries": 100, "auto_summarize": True, "sentiment_analysis": True},
            "social": {"enabled": True, "track_other_models": True, "friendship_gain_rate": 0.1, "max_friends": 5},
            "health": {"enabled": True, "check_interval": 60, "response_time_weight": 0.3, "error_rate_weight": 0.3, "efficiency_weight": 0.4},
            "skin": {"enabled": True, "unlock_by_achievement": True},
            "sound": {"enabled": True, "volume": 0.5, "mood_sounds": True, "action_sounds": True},
        },
    }
    sections = editor_schema.build_editor_sections(representative_config, "zh")
    # Every declared editor section is represented by the fixture config.
    assert {section_id for section_id, _ in editor_schema.EDITOR_SECTION_SPECS} == {section["id"] for section in sections}

    meta = editor_schema.build_editor_meta(representative_config, "zh")
    section_root_paths = {section["path"] for section in sections}
    leaf_paths = sorted(path for path in meta if path not in section_root_paths)

    presentation_source = (_WEB_SRC / "configSectionPresentation.ts").read_text(encoding="utf-8")
    match = re.search(
        r"const ZH_FIELD_COPY: Record<string, ConfigFieldPresentationCopy> = \{(.*?)\n\};",
        presentation_source,
        re.S,
    )
    assert match, "ZH_FIELD_COPY table not found"
    zh_copy_keys = set(re.findall(r'"([^"]+)":\s*\{', match.group(1)))

    missing = [path for path in leaf_paths if path not in zh_copy_keys]
    assert missing == []
