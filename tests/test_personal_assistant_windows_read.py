"""Real Windows filesystem checks for the scoped source handle boundary."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.web.services.personal_assistant_project import windows_read as source

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows handle boundary")


def test_read_ordinary_file_and_directory_enumeration(tmp_path):
    folder = tmp_path / "core"
    folder.mkdir()
    target = folder / "example.py"
    target.write_bytes(b"print('hello')\n")
    assert source.read_source_bytes(tmp_path, target, 100) == b"print('hello')\n"
    with source.lock_source_directory(tmp_path, folder):
        with os.scandir(folder) as entries:
            assert [entry.name for entry in entries] == ["example.py"]


def test_reject_oversize_hardlink_and_outside_root(tmp_path):
    target = tmp_path / "example.py"
    target.write_bytes(b"12345")
    with pytest.raises(ValueError, match="budget"):
        source.read_source_bytes(tmp_path, target, 4)
    alias = tmp_path / "alias.py"
    os.link(target, alias)
    with pytest.raises(ValueError, match="hard link"):
        source.read_source_bytes(tmp_path, alias, 10)
    with pytest.raises(ValueError, match="outside"):
        source.read_source_bytes(tmp_path / "nested", target, 10)


def test_reject_file_and_directory_symlinks(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    target = actual / "example.py"
    target.write_bytes(b"safe")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(actual, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc.winerror}")
    with pytest.raises(ValueError):
        source.read_source_bytes(tmp_path, alias / "example.py", 10)
    with pytest.raises(ValueError):
        with source.lock_source_directory(tmp_path, alias):
            pytest.fail("Reparse directory must not be exposed")
    file_alias = tmp_path / "alias.py"
    file_alias.symlink_to(target)
    with pytest.raises(ValueError):
        source.read_source_bytes(tmp_path, file_alias, 10)


def test_read_handle_blocks_writer_and_rename_then_releases(tmp_path, monkeypatch):
    target = tmp_path / "example.py"
    target.write_bytes(b"original")
    real_verify = source._verify
    checked = []

    def verify(api, handle, path, *, directory):
        info = real_verify(api, handle, path, directory=directory)
        if not directory and not checked:
            checked.append(True)
            with pytest.raises(OSError):
                with target.open("wb"):
                    pytest.fail("Concurrent writer was allowed")
            with pytest.raises(OSError):
                target.rename(tmp_path / "moved.py")
        return info

    monkeypatch.setattr(source, "_verify", verify)
    assert source.read_source_bytes(tmp_path, target, 100) == b"original"
    assert checked
    target.write_bytes(b"released")
    target.rename(tmp_path / "moved.py")


def test_directory_rename_blocked_and_failure_closes_handles(tmp_path, monkeypatch):
    folder = tmp_path / "core"
    folder.mkdir()
    with source.lock_source_directory(tmp_path, folder):
        with pytest.raises(OSError):
            folder.rename(tmp_path / "moved")
    folder.rename(tmp_path / "moved")
    target = tmp_path / "example.py"
    target.write_bytes(b"safe")
    real_verify = source._verify

    def fail(api, handle, path, *, directory):
        info = real_verify(api, handle, path, directory=directory)
        if not directory:
            raise ValueError("Injected validation failure")
        return info

    monkeypatch.setattr(source, "_verify", fail)
    with pytest.raises(ValueError, match="Injected"):
        source.read_source_bytes(tmp_path, target, 10)
    target.write_bytes(b"handles released")
    target.unlink()


@pytest.mark.parametrize("name", ["example.py:secret", "trailing.", "trailing "])
def test_reject_ambiguous_windows_components(tmp_path, name):
    with pytest.raises(ValueError, match="unsafe"):
        source.read_source_bytes(tmp_path, tmp_path / name, 10)
