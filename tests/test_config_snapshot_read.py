"""Explicit raw config snapshots never initialize, upgrade or write caches."""
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_existing_snapshot_reads_raw_toml_without_normalization_or_writes(tmp_path, monkeypatch):
    from config import public_config as owner
    source = tmp_path / "config.toml"
    source.write_text('[llm]\nschema_version = 1\nprivate_marker = "server-only"\n', encoding="utf-8")
    def forbidden(*_args, **_kwargs):
        pytest.fail("snapshot invoked initializer, upgrade or cache loader")
    for name in ("ensure_global_config_initialized", "upgrade_legacy_capability_cache_if_needed", "load_public_config", "_canonicalize_public_config"):
        monkeypatch.setattr(owner, name, forbidden)
    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    assert owner.read_existing_config_snapshot(source) == {"llm": {"schema_version": 1, "private_marker": "server-only"}}
    assert before == {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}


@pytest.mark.parametrize("contents", [None, b'broken [', b'\xff', b'#' * (16 * 1024 * 1024 + 1)], ids=['missing', 'invalid_toml', 'invalid_utf8', 'oversized'])
def test_existing_snapshot_rejects_missing_invalid_and_oversized_input(tmp_path, contents):
    from config.public_config import read_existing_config_snapshot
    source = tmp_path / 'config.toml'
    if contents is not None:
        source.write_bytes(contents)
    with pytest.raises(ValueError, match='EXISTING_CONFIG_UNAVAILABLE'):
        read_existing_config_snapshot(source)
    assert source.exists() is (contents is not None)


def test_existing_snapshot_rejects_metadata_changed_during_read(tmp_path, monkeypatch):
    from config.public_config import read_existing_config_snapshot
    source = tmp_path / 'config.toml'; source.write_text('value=1', encoding='utf-8')
    original = Path.stat
    calls = 0
    def changed(path, *args, **kwargs):
        nonlocal calls
        stat = original(path, *args, **kwargs)
        if path == source:
            calls += 1
            if calls > 1:
                return SimpleNamespace(**{name: getattr(stat, name) + (1 if name == 'st_mtime_ns' else 0)
                    for name in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode')})
        return stat
    monkeypatch.setattr(Path, 'stat', changed)
    with pytest.raises(ValueError, match='EXISTING_CONFIG_UNAVAILABLE'):
        read_existing_config_snapshot(source)


def test_existing_snapshot_compares_creation_time_within_path_and_handle_pairs(tmp_path, monkeypatch):
    import os
    from config.public_config import read_existing_config_snapshot
    source = tmp_path / 'config.toml'; source.write_text('value=1', encoding='utf-8')
    original = os.fstat
    def handle_stat(fd):
        stat = original(fd)
        return SimpleNamespace(**{name: getattr(stat, name) + (1 if name == 'st_ctime_ns' else 0)
            for name in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')})
    monkeypatch.setattr(os, 'fstat', handle_stat)
    assert read_existing_config_snapshot(source) == {'value': 1}
