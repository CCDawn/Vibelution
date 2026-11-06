import hashlib
import json
import threading
import tomllib
from pathlib import Path

import pytest

from config.paths import (
    CONFIG_META_SCHEMA_VERSION,
    DATA_HOME_ENV,
    CONFIG_HOME_ENV,
    CONFIG_PATH_ENV,
    ensure_global_config_initialized,
    resolve_config_backup_dir,
    resolve_config_home,
    resolve_config_lock_path,
    resolve_config_meta_path,
    resolve_config_path,
    resolve_data_backup_dir,
    resolve_data_home,
    resolve_workspace_home,
)
from config.runtime_capabilities import MODEL_CAPABILITY_CACHE_ENV, get_model_capability_cache_path


def test_resolve_config_path_defaults_to_user_documents(monkeypatch, tmp_path):
    user_root = tmp_path / "user"
    monkeypatch.setenv("USERPROFILE", str(user_root))
    monkeypatch.delenv("VIBELUTION_CONFIG_PATH", raising=False)
    monkeypatch.delenv("VIBELUTION_CONFIG_HOME", raising=False)

    assert resolve_config_home() == user_root / "Documents" / "Vibelution" / "config"
    assert resolve_config_path() == user_root / "Documents" / "Vibelution" / "config" / "config.toml"


def test_resolve_data_home_defaults_to_user_documents(monkeypatch, tmp_path):
    user_root = tmp_path / "user"
    monkeypatch.setenv("USERPROFILE", str(user_root))
    monkeypatch.delenv(DATA_HOME_ENV, raising=False)
    monkeypatch.delenv(CONFIG_PATH_ENV, raising=False)
    monkeypatch.delenv(CONFIG_HOME_ENV, raising=False)

    assert resolve_data_home() == user_root / "Documents" / "Vibelution" / "data"
    assert resolve_workspace_home() == user_root / "Documents" / "Vibelution" / "data" / "workspace"
    assert resolve_data_backup_dir() == user_root / "Documents" / "Vibelution" / "data" / "backups"


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


def test_resolve_data_home_prefers_env_override(monkeypatch, tmp_path):
    data_home = tmp_path / "operator-data"
    monkeypatch.setenv(DATA_HOME_ENV, str(data_home))

    assert resolve_data_home() == data_home
    assert resolve_workspace_home() == data_home / "workspace"


def test_resolve_data_home_uses_storage_config_when_no_env(monkeypatch, tmp_path):
    config_path = tmp_path / "config" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text("[storage]\ndata_home = \"../operator-data\"\n", encoding="utf-8")
    monkeypatch.delenv(DATA_HOME_ENV, raising=False)
    monkeypatch.setenv(CONFIG_PATH_ENV, str(config_path))

    assert resolve_data_home() == tmp_path / "operator-data"
    assert resolve_workspace_home() == tmp_path / "operator-data" / "workspace"


def test_resolve_data_home_caches_storage_config_until_file_changes(monkeypatch, tmp_path):
    from config import paths

    config_path = tmp_path / "config" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text("[storage]\ndata_home = \"../operator-data\"\n", encoding="utf-8")
    monkeypatch.delenv(DATA_HOME_ENV, raising=False)
    monkeypatch.setenv(CONFIG_PATH_ENV, str(config_path))
    paths._CONFIGURED_DATA_HOME_CACHE.clear()
    original_read_text = Path.read_text
    reads = []

    def counting_read_text(self, *args, **kwargs):
        if self == config_path:
            reads.append(str(self))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    assert resolve_data_home() == tmp_path / "operator-data"
    assert resolve_data_home() == tmp_path / "operator-data"
    assert len(reads) == 1

    config_path.write_text("[storage]\ndata_home = \"../operator-data-v2\"\n", encoding="utf-8")

    assert resolve_data_home() == tmp_path / "operator-data-v2"
    assert len(reads) == 2


@pytest.mark.parametrize("failure", ["read", "parse"])
@pytest.mark.parametrize("failed_reads", [1, 3])
def test_resolve_data_home_recovers_after_temporary_config_failure(
    monkeypatch, tmp_path, failure, failed_reads
):
    from config import paths

    config_path = tmp_path / "config.toml"
    config_path.write_text('[storage]\ndata_home = "operator-data"\n', encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "user"))
    monkeypatch.setenv(CONFIG_PATH_ENV, str(config_path))
    monkeypatch.delenv(DATA_HOME_ENV, raising=False)
    monkeypatch.setattr(paths, "_CONFIGURED_DATA_HOME_CACHE", {})
    initial_stat = config_path.stat()
    initial_hash = hashlib.sha256(config_path.read_bytes()).digest()
    original_read_text = Path.read_text
    reads = 0

    def failing_read_text(self, *args, **kwargs):
        nonlocal reads
        if self == config_path:
            reads += 1
            if reads <= failed_reads:
                if failure == "read":
                    raise OSError("temporary config read failure")
                return "[storage\n"
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", failing_read_text)

    for _ in range(failed_reads):
        assert resolve_data_home() == tmp_path / "user" / "Documents" / "Vibelution" / "data"

    current_stat = config_path.stat()
    assert (current_stat.st_mtime_ns, current_stat.st_size) == (
        initial_stat.st_mtime_ns, initial_stat.st_size
    )
    assert hashlib.sha256(config_path.read_bytes()).digest() == initial_hash
    assert resolve_data_home() == tmp_path / "operator-data"
    assert resolve_data_home() == tmp_path / "operator-data"
    assert reads == failed_reads + 1


@pytest.mark.parametrize("config_text", ['[app]\nname = "demo"\n', "[storage]\n", '[storage]\ndata_home = ""\n'])
def test_resolve_data_home_caches_valid_config_without_storage_override(
    monkeypatch, tmp_path, config_text
):
    from config import paths

    config_path = tmp_path / "config.toml"
    config_path.write_text(config_text, encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "user"))
    monkeypatch.setenv(CONFIG_PATH_ENV, str(config_path))
    monkeypatch.delenv(DATA_HOME_ENV, raising=False)
    monkeypatch.setattr(paths, "_CONFIGURED_DATA_HOME_CACHE", {})
    original_read_text = Path.read_text
    reads = 0

    def counting_read_text(self, *args, **kwargs):
        nonlocal reads
        if self == config_path:
            reads += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    assert paths.resolve_configured_data_home() is None
    assert resolve_data_home() == tmp_path / "user" / "Documents" / "Vibelution" / "data"
    assert paths.resolve_configured_data_home() is None
    assert reads == 1


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


def test_ensure_global_config_initialized_waits_for_config_edit_lock(tmp_path, monkeypatch):
    """ISS-034 regression: the bootstrap's check-then-write windows (starter,
    example, thin-starter upgrade, meta) used to run without any cross-process
    lock, so a concurrent writer could be clobbered between the exists check
    and the write. The whole bootstrap now holds the shared config edit lock,
    turning those checks into in-lock rechecks; while another holder owns the
    lock the bootstrap must neither write nor finish."""

    from config.public_config import _config_edit_lock

    external_config = tmp_path / "external" / "config.toml"
    monkeypatch.setenv(CONFIG_PATH_ENV, str(external_config))
    started = threading.Event()
    finished = threading.Event()
    failures: list[Exception] = []

    def initialize() -> None:
        try:
            started.set()
            ensure_global_config_initialized()
        except Exception as exc:  # collected and asserted below
            failures.append(exc)
        finally:
            finished.set()

    with _config_edit_lock(resolve_config_path()):
        worker = threading.Thread(target=initialize)
        worker.start()
        assert started.wait(5)
        assert not finished.wait(1.5), "bootstrap wrote while another holder owns the config edit lock"
        assert not external_config.exists()
    assert finished.wait(15)
    worker.join(timeout=15)
    assert failures == []
    assert external_config.exists()
    tomllib.loads(external_config.read_text(encoding="utf-8"))
    assert not resolve_config_lock_path(external_config).exists()


def test_ensure_global_config_initialized_concurrent_calls_serialize(tmp_path, monkeypatch):
    """Concurrent bootstraps serialize on the config edit lock: every caller
    succeeds, the starter is created exactly once and stays parseable."""

    external_config = tmp_path / "external" / "config.toml"
    monkeypatch.setenv(CONFIG_PATH_ENV, str(external_config))
    caller_count = 4
    barrier = threading.Barrier(caller_count, timeout=10)
    failures: list[Exception] = []

    def initialize() -> None:
        try:
            barrier.wait()
            ensure_global_config_initialized()
        except Exception as exc:  # collected and asserted below
            failures.append(exc)

    workers = [threading.Thread(target=initialize) for _ in range(caller_count)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=60)
    assert failures == []
    assert external_config.exists()
    tomllib.loads(external_config.read_text(encoding="utf-8"))
    assert not resolve_config_lock_path(external_config).exists()
