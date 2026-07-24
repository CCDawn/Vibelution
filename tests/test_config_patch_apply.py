import copy

import pytest

from config.public_config import public_config_hash
from core.web.services.config_service import (
    ConfigConflictError,
    _merge_submitted_config_changes,
    _resolve_apply_base_config,
    _with_config_workspace_defaults,
)


def test_patch_apply_preserves_current_unmodified_paths():
    base_config = {
        "llm": {
            "model_library": {
                "relay": {"provider": {"base_url": "https://old.example/v1"}, "model": "gpt-5.5"},
                "claude": {"model": "claude-opus-4-7"},
            }
        }
    }
    submitted = {
        "llm": {
            "model_library": {
                "relay": {"provider": {"base_url": "https://old.example/v1"}, "model": "gpt-5.5"},
            }
        }
    }
    current = {
        "llm": {
            "model_library": {
                "relay": {"provider": {"base_url": "https://new.example/v1"}, "model": "gpt-5.5"},
                "claude": {"model": "claude-opus-4-7"},
            }
        }
    }

    merged, changed_paths, _ = _merge_submitted_config_changes(
        base_config=base_config,
        submitted=submitted,
        old_public=current,
        lang="zh",
    )

    assert changed_paths == [("llm", "model_library", "claude")]
    assert "claude" not in merged["llm"]["model_library"]
    assert merged["llm"]["model_library"]["relay"]["provider"]["base_url"] == "https://new.example/v1"


def test_patch_apply_conflicts_on_same_path_current_change():
    base_config = {"ui": {"language": "zh"}}
    submitted = {"ui": {"language": "en"}}
    current = {"ui": {"language": "ja"}}

    with pytest.raises(ConfigConflictError) as exc_info:
        _merge_submitted_config_changes(
            base_config=base_config,
            submitted=submitted,
            old_public=current,
            lang="zh",
        )

    assert "ui.language" in str(exc_info.value)


def test_resolve_apply_base_heals_draft_as_base_config_when_hash_matches_disk():
    """Multi-pin UI bug: baseHash is disk, baseConfig is already the draft."""
    disk = _with_config_workspace_defaults({"ui": {"language": "zh"}, "llm": {"schema_version": 1}})
    draft = copy.deepcopy(disk)
    draft["ui"]["language"] = "en"
    disk_hash = public_config_hash(disk)
    draft_hash = public_config_hash(_with_config_workspace_defaults(draft))
    assert disk_hash != draft_hash

    healed = _resolve_apply_base_config(
        base_hash=disk_hash,
        submitted_base=draft,
        old_public=disk,
        current_public=disk,
        lang="zh",
    )
    assert healed == disk


def test_resolve_apply_base_heals_wrong_base_hash_when_base_config_matches_disk():
    disk = _with_config_workspace_defaults({"ui": {"language": "zh"}, "llm": {"schema_version": 1}})
    draft = copy.deepcopy(disk)
    draft["ui"]["language"] = "en"
    disk_hash = public_config_hash(disk)
    draft_hash = public_config_hash(_with_config_workspace_defaults(draft))

    healed = _resolve_apply_base_config(
        base_hash=draft_hash,
        submitted_base=disk,
        old_public=disk,
        current_public=disk,
        lang="zh",
    )
    assert healed == disk
    assert public_config_hash(_with_config_workspace_defaults(healed)) == disk_hash


def test_resolve_apply_base_accepts_consistent_pair_even_if_not_disk():
    """Self-consistent client baseline is accepted; concurrent disk edits are handled by merge."""
    disk = _with_config_workspace_defaults({"ui": {"language": "zh"}, "llm": {"schema_version": 1}})
    stale = _with_config_workspace_defaults({"ui": {"language": "ja"}, "llm": {"schema_version": 1}})
    resolved = _resolve_apply_base_config(
        base_hash=public_config_hash(stale),
        submitted_base=stale,
        old_public=disk,
        current_public=disk,
        lang="zh",
    )
    assert resolved == stale


def test_resolve_apply_base_rejects_inconsistent_pair_with_no_disk_anchor():
    disk = _with_config_workspace_defaults({"ui": {"language": "zh"}, "llm": {"schema_version": 1}})
    other_a = _with_config_workspace_defaults({"ui": {"language": "ja"}, "llm": {"schema_version": 1}})
    other_b = _with_config_workspace_defaults({"ui": {"language": "en"}, "llm": {"schema_version": 1}})
    with pytest.raises(ConfigConflictError, match="基线已过期|baseline is stale"):
        _resolve_apply_base_config(
            base_hash=public_config_hash(other_a),
            submitted_base=other_b,
            old_public=disk,
            current_public=disk,
            lang="zh",
        )
