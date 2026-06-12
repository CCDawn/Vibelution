import json
from pathlib import Path

from config.paths import (
    CONFIG_META_SCHEMA_VERSION,
    CONFIG_HOME_ENV,
    CONFIG_PATH_ENV,
    ensure_global_config_initialized,
    resolve_config_backup_dir,
    resolve_config_home,
    resolve_config_meta_path,
    resolve_config_path,
)
from config.runtime_capabilities import MODEL_CAPABILITY_CACHE_ENV, get_model_capability_cache_path


def test_resolve_config_path_defaults_to_user_documents(monkeypatch, tmp_path):
    user_root = tmp_path / "user"
    monkeypatch.setenv("USERPROFILE", str(user_root))
    monkeypatch.delenv("VIBELUTION_CONFIG_PATH", raising=False)
    monkeypatch.delenv("VIBELUTION_CONFIG_HOME", raising=False)

    assert resolve_config_home() == user_root / "Documents" / "Vibelution" / "config"
    assert resolve_config_path() == user_root / "Documents" / "Vibelution" / "config" / "config.toml"


def test_resolve_config_path_prefers_explicit_config_path(monkeypatch, tmp_path):
    explicit_path = tmp_path / "custom" / "operator.toml"
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(explicit_path))
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(tmp_path / "ignored-home"))

    assert resolve_config_path() == explicit_path
    assert resolve_config_meta_path() == explicit_path.with_name("config.meta.json")
    assert resolve_config_backup_dir() == explicit_path.parent / "backups"


def test_resolve_config_path_uses_config_home_when_no_path_override(monkeypatch, tmp_path):
    config_home = tmp_path / "global-config"
    monkeypatch.delenv("VIBELUTION_CONFIG_PATH", raising=False)
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(config_home))

    assert resolve_config_path() == config_home / "config.toml"


def test_model_capability_cache_defaults_next_to_external_config(monkeypatch, tmp_path):
    config_path = tmp_path / "operator-config" / "operator.toml"
    monkeypatch.setenv(CONFIG_PATH_ENV, str(config_path))
    monkeypatch.setenv(CONFIG_HOME_ENV, str(tmp_path / "ignored-home"))
    monkeypatch.delenv(MODEL_CAPABILITY_CACHE_ENV, raising=False)

    assert get_model_capability_cache_path() == config_path.parent / "model-capabilities.json"


def test_model_capability_cache_env_override_stays_explicit(monkeypatch, tmp_path):
    cache_path = tmp_path / "runtime-cache" / "custom-model-capabilities.json"
    monkeypatch.setenv(MODEL_CAPABILITY_CACHE_ENV, str(cache_path))

    assert get_model_capability_cache_path() == cache_path


def test_global_config_initialization_creates_external_starter_without_project_migration(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    legacy_config = project_root / "config.toml"
    legacy_example = project_root / "config.example.toml"
    legacy_config.write_text("[workbench]\nbackend_port = 9101\n", encoding="utf-8")
    legacy_example.write_text("[workbench]\nbackend_port = 8000\n", encoding="utf-8")
    external_config = tmp_path / "external" / "config.toml"
    monkeypatch.delenv("VIBELUTION_CONFIG_PATH", raising=False)
    monkeypatch.delenv("VIBELUTION_CONFIG_HOME", raising=False)

    meta = ensure_global_config_initialized(external_config, project_root=project_root)

    assert "operator config" in external_config.read_text(encoding="utf-8")
    assert "backend_port = 9101" not in external_config.read_text(encoding="utf-8")
    assert "example operator config" in external_config.with_name("config.example.toml").read_text(encoding="utf-8")
    assert "backend_port = 8000" not in external_config.with_name("config.example.toml").read_text(encoding="utf-8")
    assert Path(meta["configPath"]) == external_config
    assert Path(meta["backupDir"]) == external_config.parent / "backups"
    assert Path(meta["lockPath"]) == external_config.parent / "config-edit.lock"
    assert meta["createdConfig"] is True
    assert meta["configSource"] == "external_starter"
    assert meta["exampleConfigSource"] == "external_example_starter"
    assert external_config.with_name("config.meta.json").exists()
    assert (external_config.parent / "backups").is_dir()

    external_config.write_text("[workbench]\nbackend_port = 9201\n", encoding="utf-8")
    legacy_config.write_text("[workbench]\nbackend_port = 9301\n", encoding="utf-8")

    ensure_global_config_initialized(external_config, project_root=project_root)

    assert external_config.read_text(encoding="utf-8") == "[workbench]\nbackend_port = 9201\n"


def test_global_config_initialization_upgrades_existing_meta_without_overwriting_config_origin(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "config.example.toml").write_text("[workbench]\nbackend_port = 8000\n", encoding="utf-8")
    external_config = tmp_path / "external" / "config.toml"
    external_config.parent.mkdir(parents=True)
    external_config.write_text("[workbench]\nbackend_port = 8000\n", encoding="utf-8")
    meta_path = external_config.with_name("config.meta.json")
    meta_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "configHome": str(external_config.parent),
                "configPath": str(external_config),
                "exampleConfigPath": str(external_config.with_name("config.example.toml")),
                "createdAt": "2026-06-11T09:20:00+00:00",
                "createdConfig": True,
                "createdExampleConfig": True,
                "configSource": "project_config",
                "exampleConfigSource": "project_example",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    ensure_global_config_initialized(external_config, project_root=project_root)

    upgraded = json.loads(meta_path.read_text(encoding="utf-8"))
    assert upgraded["schemaVersion"] == CONFIG_META_SCHEMA_VERSION
    assert upgraded["configSource"] == "project_config"
    assert upgraded["exampleConfigSource"] == "external_example_starter"
    assert upgraded["createdAt"] == "2026-06-11T09:20:00+00:00"
    assert Path(upgraded["backupDir"]) == external_config.parent / "backups"
    assert Path(upgraded["lockPath"]) == external_config.parent / "config-edit.lock"
