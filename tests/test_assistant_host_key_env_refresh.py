"""B1: the assistant host must apply freshly saved provider config.

Covers the Windows user-registry API-key refresh that runs at host startup
(``refresh_llm_api_key_envs_from_user_registry``): a launcher-spawned host
inherits the Electron main environment snapshot, which keeps serving a stale
key after the operator saves a new one, because every key lookup prefers
``os.environ`` over the registry fallback. The end-to-end case runs the real
config-read chain (TOML file → load_public_config → build_effective_config →
resolve_api_key_for_profile) in a fresh interpreter process and proves the
refreshed value is the one the runtime resolves.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from config.public_config import (
    collect_llm_api_key_env_names,
    refresh_llm_api_key_envs_from_user_registry,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

V2_RELAY_TOML = """
[llm]
schema_version = 2

[llm.providers.relay_a]
kind = "relay"
label = "Relay"
service_class = "relay"
vendor = "multi_model"
driver = "openai"
base_url = "http://127.0.0.1:9/v1"
auth_kind = "api_key"
credential_ref = "env:OPENAI_RELAY_KEY"
requires_credential = true

[llm.providers.relay_a.protocols]
default = "chat_completions"
allowed = ["chat_completions"]

[llm.providers.relay_a.discovery]
cache_ttl_seconds = 0

[llm.providers.relay_a.models.test_model]
model = "test-model"
label = "Test Model"
upstream_id = "upstream-test-model"

[llm.profiles.primary]
model_ref = "relay_a/test_model"
"""


def _v2_relay_config() -> dict:
    llm = {
        "schema_version": 2,
        "providers": {
            "relay_a": {
                "kind": "relay",
                "label": "Relay",
                "service_class": "relay",
                "vendor": "multi_model",
                "driver": "openai",
                "base_url": "http://127.0.0.1:9/v1",
                "auth_kind": "api_key",
                "credential_ref": "env:OPENAI_RELAY_KEY",
                "requires_credential": True,
            }
        },
    }
    return {"llm": llm}


def test_collect_covers_env_refs_kinds_and_aliases() -> None:
    config = _v2_relay_config()
    config["llm"]["providers"]["relay_a"]["kind"] = "anthropic"
    config["llm"]["model_library"] = {
        "m1": {"api_key_env": "ANTHROPIC_LIB_KEY", "provider": {"kind": "deepseek"}}
    }
    config["llm"]["profiles"] = {
        "p1": {"provider": {"credential_ref": "env:ANTHROPIC_NESTED_KEY"}}
    }
    names = collect_llm_api_key_env_names(config)
    assert names == [
        "ANTHROPIC_API_KEY",  # anthropic kind default
        "ANTHROPIC_AUTH_TOKEN",  # anthropic alias
        "ANTHROPIC_LIB_KEY",  # model library entry
        "ANTHROPIC_NESTED_KEY",  # nested provider credential_ref
        "DEEPSEEK_API_KEY",  # deepseek kind default
        "OPENAI_RELAY_KEY",  # v2 provider credential_ref
    ]


def test_collect_without_config_reference_stays_empty_for_kinds() -> None:
    assert collect_llm_api_key_env_names({"llm": {"schema_version": 2}}) == []


def test_collect_from_current_operator_config_returns_a_list(monkeypatch: pytest.MonkeyPatch) -> None:
    import config.public_config as public_config

    monkeypatch.setattr(public_config, "load_public_config", lambda: {"llm": {"schema_version": 2}})
    assert collect_llm_api_key_env_names(None) == []


def test_refresh_overrides_stale_inherited_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import config.public_config as public_config

    config = _v2_relay_config()
    monkeypatch.setattr(
        public_config,
        "_read_windows_user_env_var",
        lambda name: {"OPENAI_RELAY_KEY": "fresh-saved-key"}.get(name, ""),
    )
    monkeypatch.setenv("OPENAI_RELAY_KEY", "stale-inherited-key")
    refreshed = refresh_llm_api_key_envs_from_user_registry(config)
    assert refreshed == ["OPENAI_RELAY_KEY"]
    assert os.environ["OPENAI_RELAY_KEY"] == "fresh-saved-key"


def test_refresh_keeps_env_when_registry_has_no_value(monkeypatch: pytest.MonkeyPatch) -> None:
    import config.public_config as public_config

    config = _v2_relay_config()
    monkeypatch.setattr(public_config, "_read_windows_user_env_var", lambda name: "")
    monkeypatch.setenv("OPENAI_RELAY_KEY", "explicit-value")
    assert refresh_llm_api_key_envs_from_user_registry(config) == []
    assert os.environ["OPENAI_RELAY_KEY"] == "explicit-value"


def test_refresh_skips_invalid_env_names_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    import config.public_config as public_config

    config = {"llm": {"providers": {"x": {"credential_ref": "env:NOT A VALID NAME"}}}}
    monkeypatch.setattr(public_config, "_read_windows_user_env_var", lambda name: "v")
    assert refresh_llm_api_key_envs_from_user_registry(config) == []


def test_refresh_is_noop_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    import config.public_config as public_config

    monkeypatch.setattr(public_config.os, "name", "linux")
    assert refresh_llm_api_key_envs_from_user_registry(_v2_relay_config()) == []


_END_TO_END_SCRIPT = r"""
import json, os, sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import config.public_config as public_config
from config.public_config import (
    build_effective_config,
    load_public_config,
    refresh_llm_api_key_envs_from_user_registry,
)

config_path = Path(sys.argv[2])
config_path.parent.mkdir(parents=True, exist_ok=True)
config_path.write_text(Path(sys.argv[3]).read_text(encoding="utf-8"), encoding="utf-8")

# Simulate the launcher-inherited environment snapshot: the key in os.environ
# is the value saved BEFORE the operator updated the settings page.
os.environ["OPENAI_RELAY_KEY"] = "stale-inherited-key"

config = load_public_config(config_path)
base_url = config["llm"]["providers"]["relay_a"]["base_url"]
effective = build_effective_config(config)
key_before = effective.llm.resolve_api_key_for_profile(role="primary")

# The persisted user-level registry (HKCU\Environment) already holds the new
# key the backend saved. Stub only that persistence boundary; everything else
# runs the real chain.
registry = {"OPENAI_RELAY_KEY": "fresh-saved-key"}
public_config._read_windows_user_env_var = lambda name: registry.get(name, "")
refreshed = refresh_llm_api_key_envs_from_user_registry(config)
key_after = effective.llm.resolve_api_key_for_profile(role="primary")

print(json.dumps({
    "base_url": base_url,
    "key_before": key_before,
    "refreshed": refreshed,
    "key_after": key_after,
    "env_after": os.environ.get("OPENAI_RELAY_KEY", ""),
}))
"""


def test_end_to_end_fresh_process_resolves_new_config_after_refresh(
    tmp_path: Path,
) -> None:
    """Fresh process: new config.toml base_url is read directly, and the saved
    key only reaches the runtime resolution through the startup refresh —
    proving the restarted host really picks up both halves of a saved change."""

    script_path = tmp_path / "e2e_key_refresh_child.py"
    script_path.write_text(_END_TO_END_SCRIPT, encoding="utf-8")
    toml_template = tmp_path / "config-template.toml"
    toml_template.write_text(V2_RELAY_TOML, encoding="utf-8")
    live_toml = tmp_path / "live-config.toml"

    result = subprocess.run(
        [sys.executable, "-I", str(script_path), str(PROJECT_ROOT), str(live_toml), str(toml_template)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["base_url"] == "http://127.0.0.1:9/v1"
    assert payload["key_before"] == "stale-inherited-key"
    assert payload["refreshed"] == ["OPENAI_RELAY_KEY"]
    assert payload["key_after"] == "fresh-saved-key"
    assert payload["env_after"] == "fresh-saved-key"
