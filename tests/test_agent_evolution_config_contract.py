"""Config-retirement contract for agent/evolution/web_chat/debug switches.

These fields were exposed on the panel but had no runtime consumer. The
contract keeps them readable for old config files while making the retirement
explicit, so the panel cannot promise behaviour the runtime never had.
"""

from __future__ import annotations

from config.models import (
    AgentConfig,
    DebugConfig,
    EvolutionConfig,
    SupervisedEvolutionFeatureConfig,
    WebChatConfig,
)

RETIRED = {
    AgentConfig: ("max_runtime", "auto_backup", "backup_interval", "exploration_mode"),
    EvolutionConfig: ("archive_dir", "backup_dir", "auto_check_approved"),
    SupervisedEvolutionFeatureConfig: ("compression_enabled", "memory_update_enabled"),
    DebugConfig: ("track_token_usage",),
    WebChatConfig: ("max_continuation_turns",),
}


def test_retired_fields_carry_the_marker():
    for model, names in RETIRED.items():
        for name in names:
            description = model.model_fields[name].description or ""
            assert "已退役" in description, f"{model.__name__}.{name} is not marked retired"


def test_retired_fields_still_accept_legacy_config():
    """Old config files keep loading; retirement must not break parsing."""
    for model, names in RETIRED.items():
        instance = model()
        for name in names:
            assert getattr(instance, name) is not None
