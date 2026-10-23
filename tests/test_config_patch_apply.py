import copy
from pathlib import Path

import pytest

from config.llm_schema_upgrader import convert_legacy_llm_config
from config.public_config import load_public_config, public_config_hash
from core.web.services import config_service
from core.web.services.config_service import (
    ConfigConflictError,
    _merge_submitted_config_changes,
    _resolve_apply_base_config,
    _with_config_workspace_defaults,
)

DRIFT_EVENT_CODE = "config.language.apply_drift_suppressed"


def _stored_schema_v2_config(language: str | None) -> dict:
    """A schema-v2 config fixture, mirroring what production persists."""

    fixture_path = (
        Path(__file__).resolve().parent / "fixtures" / "config" / "llm_schema_v1_inline.toml"
    )
    config = convert_legacy_llm_config(load_public_config(fixture_path), allow_missing_credentials=True)
    if language is None:
        config.pop("ui", None)
    else:
        config.setdefault("ui", {})["language"] = language
    return config


def _patch_apply_persistence(monkeypatch, tmp_path, stored: dict):
    """Pin apply_config_workspace persistence into memory; keep derived catalog state in tmp."""

    persisted: dict = {"value": copy.deepcopy(stored)}
    scene_events: list[tuple[str, str, dict]] = []
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(stored))
    monkeypatch.setattr(
        config_service,
        "save_public_config",
        lambda value: persisted.update(value=copy.deepcopy(value)),
    )
    monkeypatch.setattr(config_service, "reload_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
    )
    return persisted, scene_events


def _drift_events(scene_events: list[tuple[str, str, dict]]) -> list[tuple[str, str, dict]]:
    return [event for event in scene_events if event[1] == DRIFT_EVENT_CODE]


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


def test_apply_config_workspace_suppresses_submitted_ui_language_drift(tmp_path, monkeypatch):
    """Whole-config apply must not rewrite ui.language; drift is kept on disk
    value and recorded for forensics (regression: settings apply flipped the
    whole product UI to "en" with no scene-log trace)."""

    stored = _stored_schema_v2_config("zh")
    submitted = copy.deepcopy(stored)
    submitted["ui"]["language"] = "en"
    persisted, scene_events = _patch_apply_persistence(monkeypatch, tmp_path, stored)

    config_service.apply_config_workspace(submitted)

    assert persisted["value"]["ui"]["language"] == "zh"
    drift = _drift_events(scene_events)
    assert len(drift) == 1
    phase, _, kwargs = drift[0]
    assert phase == "persist"
    assert kwargs["outcome"] == "suppressed"
    assert kwargs["fields"]["submittedLanguage"] == "en"
    assert kwargs["fields"]["storedLanguage"] == "zh"
    assert kwargs["fields"]["configPath"]


def test_apply_config_workspace_keeps_matching_ui_language_without_drift_event(tmp_path, monkeypatch):
    stored = _stored_schema_v2_config("zh")
    submitted = copy.deepcopy(stored)
    persisted, scene_events = _patch_apply_persistence(monkeypatch, tmp_path, stored)

    config_service.apply_config_workspace(submitted)

    assert persisted["value"]["ui"]["language"] == "zh"
    assert _drift_events(scene_events) == []


def test_apply_config_workspace_passes_language_through_when_stored_ui_has_none(tmp_path, monkeypatch):
    stored = _stored_schema_v2_config(None)
    submitted = copy.deepcopy(stored)
    submitted["ui"] = {"language": "en"}
    persisted, scene_events = _patch_apply_persistence(monkeypatch, tmp_path, stored)

    config_service.apply_config_workspace(submitted)

    assert persisted["value"]["ui"]["language"] == "en"
    assert _drift_events(scene_events) == []


def test_update_language_remains_the_legitimate_ui_language_writer(monkeypatch):
    stored = _stored_schema_v2_config("zh")
    persisted: dict = {"value": copy.deepcopy(stored)}
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(persisted["value"]))
    monkeypatch.setattr(
        config_service,
        "save_public_config",
        # update_language 经 ui_language_override 显式声明语言写入。
        lambda value, **_kwargs: persisted.update(value=copy.deepcopy(value)),
    )
    monkeypatch.setattr(config_service, "_record_config_scene_event", lambda *_args, **_kwargs: None)

    summary = config_service.update_language("en")

    assert persisted["value"]["ui"]["language"] == "en"
    assert summary["language"] == "en"
    summary = config_service.update_language("zh")
    assert persisted["value"]["ui"]["language"] == "zh"
    assert summary["language"] == "zh"


@pytest.mark.parametrize("use_alias", [False, True])
def test_apply_accepts_v2_git_model_reference_without_persisting_runtime_library(tmp_path, monkeypatch, use_alias):
    fixture = Path(__file__).parent / "fixtures/config/llm_schema_v2_provider.toml"
    stored = load_public_config(fixture)
    model_id = "lab_llamacpp_a/qwen3.6-35b-a3b"
    if use_alias:
        stored["llm"]["model_aliases"] = {"git-default": model_id}
        model_id = "git-default"
    submitted = copy.deepcopy(stored)
    submitted["git"] = {"commit_message_model_ref": model_id}
    persisted, _ = _patch_apply_persistence(monkeypatch, tmp_path, stored)
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(persisted["value"]))
    monkeypatch.setattr(config_service, "_read_raw_public_config", lambda: "")
    monkeypatch.setattr(config_service, "MODEL_REFERENCE_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config_service, "materialize_observed_binding_pins", lambda payload: payload)
    config_service.apply_config_workspace(submitted)
    assert persisted["value"]["git"]["commit_message_model_ref"] == model_id
    assert "model_library" not in persisted["value"]["llm"]
    assert persisted["value"]["llm"]["providers"] == stored["llm"]["providers"]


@pytest.mark.parametrize("model_id,aliases", [
    ("pixel_relay/missing", {}), ("missing-alias", {}), ("cycle", {"cycle": "cycle"}),
])
def test_apply_git_validation_rejects_unknown_and_cyclic_v2_reference(model_id, aliases):
    fixture = Path(__file__).parent / "fixtures/config/llm_schema_v2_provider.toml"
    public = load_public_config(fixture)
    public["llm"]["model_aliases"] = aliases
    public["git"] = {"commit_message_model_ref": model_id}
    with pytest.raises(ValueError, match="unknown Git commit message model"):
        config_service._validate_git_commit_settings(public)
