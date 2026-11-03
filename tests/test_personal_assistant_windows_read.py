"""Real Windows filesystem checks for the scoped source handle boundary."""
from __future__ import annotations

import os
import ctypes
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


def test_file_read_allows_unrelated_ancestor_directory_write_handle(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    target = folder / "example.py"
    target.write_bytes(b"safe")
    api = source._api()
    handle = api.CreateFileW(str(tmp_path), 0x40000000, 7, None, 3, 0x02200000, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        assert source.read_source_bytes(tmp_path, target, 100) == b"safe"
    finally:
        api.CloseHandle(handle)


def test_file_read_still_blocks_ancestor_directory_rename(tmp_path, monkeypatch):
    folder = tmp_path / "project"
    folder.mkdir()
    target = folder / "example.py"
    target.write_bytes(b"safe")
    real_verify = source._verify
    checked = []

    def verify(api, handle, path, *, directory):
        info = real_verify(api, handle, path, directory=directory)
        if not directory and not checked:
            checked.append(True)
            with pytest.raises(OSError):
                folder.rename(tmp_path / "moved")
        return info

    monkeypatch.setattr(source, "_verify", verify)
    assert source.read_source_bytes(tmp_path, target, 100) == b"safe"
    assert checked


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


def test_directory_reader_verifies_ancestors_once_and_preserves_file_sharing(tmp_path, monkeypatch):
    folder = tmp_path / "batch"
    folder.mkdir()
    first, second = folder / "first.json", folder / "second.json"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    real_verify = source._verify
    directory_checks, file_checks = [], []

    def verify(api, handle, path, *, directory):
        info = real_verify(api, handle, path, directory=directory)
        (directory_checks if directory else file_checks).append(path)
        if not directory:
            with pytest.raises(OSError):
                path.write_bytes(b"writer must be denied")
            with pytest.raises(OSError):
                path.rename(folder / "renamed.json")
        return info

    monkeypatch.setattr(source, "_verify", verify)
    with source.source_directory_reader(tmp_path, folder) as read:
        assert read(first, 32) == b"first"
        assert read(second, 32) == b"second"
        with pytest.raises(OSError):
            folder.rename(tmp_path / "moved")
        # The lease must allow ordinary unrelated writes and child replacement.
        replacement = folder / "replacement.json"
        replacement.write_bytes(b"new second")
        replacement.replace(second)
        assert read(second, 32) == b"new second"
    assert directory_checks == [*reversed(folder.parents), folder]
    assert len(file_checks) == 6  # Each file is verified before and after its read.
    with pytest.raises(ValueError, match="scope"):
        read(first, 32)
    folder.rename(tmp_path / "moved")


def test_directory_reader_rejects_nested_outside_ambiguous_and_hardlinked_children(tmp_path):
    folder = tmp_path / "batch"
    folder.mkdir()
    nested = folder / "nested"
    nested.mkdir()
    target = folder / "file.json"
    target.write_bytes(b"safe")
    alias = folder / "alias.json"
    os.link(target, alias)
    with source.source_directory_reader(tmp_path, folder) as read:
        with pytest.raises(ValueError, match="immediate"):
            read(nested / "file.json", 32)
        with pytest.raises(ValueError, match="outside"):
            read(tmp_path / "outside.json", 32)
        for name in ("file.json:stream", "trailing.", "trailing "):
            with pytest.raises(ValueError, match="unsafe"):
                read(folder / name, 32)
        with pytest.raises(ValueError, match="hard link"):
            read(alias, 32)
    alias.unlink()
    with source.source_directory_reader(tmp_path, folder) as read:
        with pytest.raises(ValueError, match="budget"):
            read(target, 3)


def test_directory_reader_rejects_reparse_directory_and_file(tmp_path):
    folder = tmp_path / "batch"
    folder.mkdir()
    target = folder / "file.json"
    target.write_bytes(b"safe")
    alias = tmp_path / "alias"
    file_alias = folder / "alias.json"
    try:
        alias.symlink_to(folder, target_is_directory=True)
        file_alias.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc.winerror}")
    with pytest.raises(ValueError):
        with source.source_directory_reader(tmp_path, alias):
            pytest.fail("Reparse directory must not be pinned")
    with source.source_directory_reader(tmp_path, folder) as read:
        with pytest.raises(ValueError):
            read(file_alias, 32)


@pytest.mark.parametrize("failure", ["verify", "read"])
def test_directory_reader_failure_expires_callback_and_closes_all_handles(tmp_path, monkeypatch, failure):
    folder = tmp_path / "batch"
    folder.mkdir()
    target = folder / "file.json"
    target.write_bytes(b"safe")
    real_verify = source._verify

    def fail(api, handle, path, *, directory):
        info = real_verify(api, handle, path, directory=directory)
        if not directory and failure == "verify":
            raise ValueError("Injected file validation failure")
        return info

    monkeypatch.setattr(source, "_verify", fail)
    if failure == "read":
        real_api = source._api()

        class FailedReadAPI:
            def __getattr__(self, name):
                return getattr(real_api, name)

            def ReadFile(self, *args):
                ctypes.set_last_error(5)
                return False

        monkeypatch.setattr(source, "_api", lambda: FailedReadAPI())
    with pytest.raises(ValueError if failure == "verify" else OSError):
        with source.source_directory_reader(tmp_path, folder) as read:
            read(target, 32)
    with pytest.raises(ValueError, match="scope"):
        read(target, 32)
    target.write_bytes(b"released")
    folder.rename(tmp_path / "moved")
