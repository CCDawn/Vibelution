import pytest

from core.web.services.config_service import ConfigConflictError, _merge_submitted_config_changes


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
