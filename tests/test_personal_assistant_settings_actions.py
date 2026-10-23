"""Closed PA preferences and provider-scoped model pins, with real temp config."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from tools import pa_settings_actions as actions


@pytest.fixture
def operator_config(tmp_path, monkeypatch):
    from config import operator_config_transaction as transaction
    from core.web.services import theme_background_service as backgrounds

    fixture = Path(__file__).parent / "fixtures/config/llm_schema_v2_provider.toml"
    path = tmp_path / "config.toml"
    path.write_text(fixture.read_text(encoding="utf-8") + '''
[user_profile]
display_name = "Operator"
avatar_preset = "default"
bio = "Public bio"
preferences = ["Concise"]

[ui]
language = "zh"
max_log_entries = 100
refresh_rate = 4
show_ascii_art = true
show_welcome = true

[ui.workbench_theme]
background_image_path = ""
background_readability = "standard"
''', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(path))
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(backgrounds, "CONFIG_PATH", path)
    # Transactions remain real; isolate process-global runtime reload only.
    monkeypatch.setattr(transaction, "reload_config", lambda *_: None)
    return path


def read_config(path):
    return tomllib.loads(path.read_text(encoding="utf-8"))


def update(section, key, value):
    return {"section": section, "key": key, "value": value}


def test_settings_update_persists_verified_preferences_and_preserves_provider(operator_config):
    before = read_config(operator_config)
    result = actions.settings_update([
        update("user_profile", "display_name", "小明"),
        update("user_profile", "avatar_preset", "spark"),
        update("ui", "language", "en"),
        update("ui", "show_welcome", False),
        update("ui", "workbench_theme.background_readability", "strong"),
    ])
    assert result["ok"] and result["verified"]
    after = read_config(operator_config)
    assert after["user_profile"]["display_name"] == "小明"
    assert after["user_profile"]["avatar_preset"] == "spark"
    assert after["ui"]["language"] == "en"
    assert after["ui"]["show_welcome"] is False
    assert after["ui"]["workbench_theme"]["background_readability"] == "strong"
    assert after["llm"] == before["llm"]
    assert "publicConfig" not in result


@pytest.mark.parametrize("bad", [
    update("llm", "providers.pixel_relay.base_url", "https://evil.test"),
    update("ui", "credential_ref", "secret"),
    update("ui", "show_welcome", "false"),
    update("ui", "refresh_rate", True),
    update("ui", "workbench_theme.background_readability", "invisible"),
    update("user_profile", "avatar_preset", "arbitrary"),
    update("user_profile", "avatar_image_path", "C:/private.png"),
    {"section": "ui", "key": "language", "value": "en", "extra": True},
])
def test_settings_invalid_batch_never_writes(operator_config, bad):
    before = operator_config.read_bytes()
    result = actions.settings_update([update("ui", "language", "en"), bad])
    assert not result["ok"]
    assert operator_config.read_bytes() == before


@pytest.mark.parametrize("value", [
    "C:/private.png", "../private.png", "theme_backgrounds/../private.png",
    "https://example.com/wallpaper.png", "theme_backgrounds/missing.png",
    "theme_backgrounds/file.txt", "theme_backgrounds/nested/file.png",
])
def test_wallpaper_rejects_arbitrary_missing_and_traversal_paths(operator_config, value):
    before = operator_config.read_bytes()
    result = actions.settings_update([update("ui", "workbench_theme.background_image_path", value)])
    assert not result["ok"]
    assert operator_config.read_bytes() == before


def test_wallpaper_accepts_bundle_and_existing_operator_resource_without_reading_image(operator_config, monkeypatch):
    from core.web.services import theme_background_service as backgrounds

    stored = operator_config.parent / "theme_backgrounds" / "uploaded.png"
    stored.parent.mkdir()
    stored.write_bytes(b"fixture: no decoding or image read needed")
    original = Path.read_bytes

    def no_image_read(path):
        assert path.suffix != ".png"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", no_image_read)
    for value in (backgrounds.DEFAULT_THEME_BACKGROUND_PATH, "theme_backgrounds/uploaded.png", ""):
        result = actions.settings_update([update("ui", "workbench_theme.background_image_path", value)])
        assert result["ok"], result
        assert read_config(operator_config)["ui"]["workbench_theme"]["background_image_path"] == value


def test_wallpaper_rejects_resolver_escape(operator_config, monkeypatch):
    from core.web.services import theme_background_service as backgrounds

    outside = operator_config.parent / "private.png"
    outside.write_bytes(b"private")
    monkeypatch.setattr(backgrounds, "resolve_theme_background_file", lambda _: outside)
    result = actions.settings_update([update("ui", "workbench_theme.background_image_path", "theme_backgrounds/secret.png")])
    assert not result["ok"]


def test_catalog_only_projects_bounded_public_whitelist(operator_config):
    result = actions.settings_catalog()
    assert result["ok"]
    encoded = json.dumps(result)
    for forbidden in ("credential_ref", "VIBELUTION_LLM_PROVIDER", "base_url", "relay.example", "artifact_path", "publicConfig"):
        assert forbidden not in encoded
    by_path = {entry["path"]: entry for entry in result["settings"]}
    assert by_path["ui.language"]["value"] == "zh"
    assert by_path["user_profile.avatar_preset"]["options"] == ["default", "circle", "spark", "codex", "minimal", "initial"]
    assert by_path["ui.workbench_theme.background_readability"]["options"] == ["soft", "standard", "strong"]


def test_settings_stale_transaction_is_not_retried(operator_config, monkeypatch):
    from config import operator_config_transaction as transaction

    calls = []
    def stale(**kwargs):
        calls.append(kwargs)
        raise ValueError("stale config hash: private credential detail")
    monkeypatch.setattr(transaction, "prepare_operator_config_transaction", stale)
    before = operator_config.read_bytes()
    result = actions.settings_update([update("ui", "language", "en")])
    assert result["error"] == "config_conflict"
    assert len(calls) == 1
    assert "private" not in json.dumps(result)
    assert operator_config.read_bytes() == before


def test_model_add_uses_canonical_pin_defaults_and_changes_only_one_model(operator_config):
    from config.llm_provider_registry import pin_llm_model

    before = read_config(operator_config)
    result = actions.model_add("pixel_relay", "gpt-new", label="New Model")
    assert result["ok"] and result["verified"]
    assert result["modelRef"] == "pixel_relay/gpt-new"
    expected = pin_llm_model(before, "pixel_relay", upstream_id="gpt-new", label="New Model")
    assert read_config(operator_config) == expected
    assert set(result) <= {"ok", "status", "verified", "providerId", "modelKey", "modelRef", "upstreamId"}


def test_model_add_is_idempotent_and_collision_does_not_overwrite(operator_config):
    first = actions.model_add("pixel_relay", "gpt-new", "alias", "First Label")
    assert first["ok"]
    before = operator_config.read_bytes()
    again = actions.model_add("pixel_relay", "gpt-new", "alias", "Changed Label")
    assert again["ok"] and again["status"] == "existing"
    assert operator_config.read_bytes() == before
    conflict = actions.model_add("pixel_relay", "different-model", "alias")
    assert not conflict["ok"] and conflict["error"] == "model_conflict"
    assert operator_config.read_bytes() == before


@pytest.mark.parametrize("arguments", [
    ("unknown", "model"), ("../bad", "model"), ("pixel_relay", ""),
    ("pixel_relay", "x" * 257), ("pixel_relay", "model", "../escape"),
    ("pixel_relay", "model", "alias", "x" * 121),
    ("pixel_relay", "https://evil.test/model"),
    ("pixel_relay", "model\nsecret"),
])
def test_model_add_rejects_invalid_input_without_write(operator_config, arguments):
    before = operator_config.read_bytes()
    assert not actions.model_add(*arguments)["ok"]
    assert operator_config.read_bytes() == before


def test_model_add_rejects_legacy_schema_without_migration(operator_config):
    text = operator_config.read_text(encoding="utf-8").replace("schema_version = 2", "schema_version = 1")
    operator_config.write_text(text, encoding="utf-8")
    assert not actions.model_add("pixel_relay", "new-model")["ok"]
    assert operator_config.read_text(encoding="utf-8") == text


def test_receipt_does_not_echo_internal_exception(operator_config, monkeypatch):
    from config import operator_config_transaction as transaction

    def fail(*args, **kwargs):
        raise RuntimeError("credential=super-secret /private/operator/config.toml")
    monkeypatch.setattr(transaction, "apply_operator_config_transaction", fail)
    result = actions.model_add("pixel_relay", "new-model")
    assert not result["ok"]
    assert "super-secret" not in json.dumps(result)
    assert "/private/" not in json.dumps(result)


def test_settings_validates_all_entries_before_preparing_transaction(operator_config, monkeypatch):
    from config import operator_config_transaction as transaction

    def forbidden(**kwargs):
        pytest.fail("transaction prepared before full batch validation")
    monkeypatch.setattr(transaction, "prepare_operator_config_transaction", forbidden)
    assert not actions.settings_update([
        update("ui", "language", "en"), update("ui", "unknown", True),
    ])["ok"]


@pytest.mark.parametrize("payload", [
    [], "not a list", [update("ui", "language", "en")] * 21,
    [update("user_profile", "preferences", [123])],
    [update("ui", "language", "en"), update("ui", "language", "zh")],
])
def test_malformed_or_ambiguous_updates_do_not_write(operator_config, payload):
    before = operator_config.read_bytes()
    assert not actions.settings_update(payload)["ok"]
    assert operator_config.read_bytes() == before


def test_multiline_fake_header_cannot_redirect_preference_patch(operator_config):
    text = operator_config.read_text(encoding="utf-8")
    text = 'operator_note = """\n[ui]\nlanguage = \'private text\'\n"""\n' + text
    operator_config.write_text(text, encoding="utf-8")
    result = actions.settings_update([update("ui", "language", "en")])
    assert not result["ok"]
    assert operator_config.read_text(encoding="utf-8") == text


def test_absent_profile_and_theme_tables_can_be_added(operator_config):
    fixture = Path(__file__).parent / "fixtures/config/llm_schema_v2_provider.toml"
    operator_config.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    result = actions.settings_update([
        update("user_profile", "display_name", "New Operator"),
        update("ui", "workbench_theme.background_readability", "soft"),
    ])
    assert result["ok"], result
    assert read_config(operator_config)["user_profile"]["display_name"] == "New Operator"
    assert read_config(operator_config)["ui"]["workbench_theme"]["background_readability"] == "soft"


def test_model_add_sanitizes_derived_key_for_namespaced_upstream(operator_config):
    from config.llm_identity import make_model_key

    result = actions.model_add("pixel_relay", "org/Model-Version")
    assert result["ok"], result
    assert result["modelKey"] == make_model_key("org/Model-Version")
    assert read_config(operator_config)["llm"]["providers"]["pixel_relay"]["models"][result["modelKey"]]["upstream_id"] == "org/Model-Version"


def test_model_add_stale_after_preparation_keeps_concurrent_update(operator_config, monkeypatch):
    from config import operator_config_transaction as transaction

    original = transaction.apply_operator_config_transaction
    concurrent = []
    def concurrent_apply(prepared):
        text = operator_config.read_text(encoding="utf-8").replace('display_name = "Operator"', 'display_name = "Peer edit"')
        operator_config.write_text(text, encoding="utf-8")
        concurrent.append(text)
        return original(prepared)
    monkeypatch.setattr(transaction, "apply_operator_config_transaction", concurrent_apply)
    result = actions.model_add("pixel_relay", "gpt-new")
    assert result["error"] == "config_conflict", result
    assert len(concurrent) == 1
    assert operator_config.read_text(encoding="utf-8") == concurrent[0]


@pytest.mark.parametrize("operation", ["settings", "model"])
def test_no_success_receipt_without_readback(operator_config, monkeypatch, operation):
    from config import operator_config_transaction as transaction

    monkeypatch.setattr(transaction, "apply_operator_config_transaction", lambda _: {"status": "applied"})
    if operation == "settings":
        result = actions.settings_update([update("ui", "language", "en")])
    else:
        result = actions.model_add("pixel_relay", "gpt-new")
    assert not result["ok"]
    assert result["error"] == "verification_failed"


def test_catalog_bounds_corrupt_stored_profile_values(operator_config):
    text = operator_config.read_text(encoding="utf-8").replace('display_name = "Operator"', 'display_name = "' + "x" * 5000 + '"')
    operator_config.write_text(text, encoding="utf-8")
    result = actions.settings_catalog()
    assert result["ok"]
    assert "x" * 121 not in json.dumps(result)


def test_wallpaper_rejects_operator_resource_symlink_escape(operator_config, tmp_path):
    root = operator_config.parent / "theme_backgrounds"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private")
    try:
        (root / "escape.png").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    result = actions.settings_update([update("ui", "workbench_theme.background_image_path", "theme_backgrounds/escape.png")])
    assert not result["ok"]
