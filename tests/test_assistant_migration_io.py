"""Migration readers never create, repair or silently truncate their sources."""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from core.assistant_runtime.migration_io import (
    MigrationIOError, check_path, fingerprint_tree, read_stable_file, strict_json, verify_snapshot,
    path_identity, publish_directory,
    existing_migration_file_lock,
)


@pytest.mark.skipif(os.name != "nt", reason="Windows physical namespace pinning")
def test_existing_migration_lock_rejects_missing_empty_and_linked_leaf(tmp_path):
    target = tmp_path / "ledger"
    leaf = tmp_path / "ledger.lock"
    before = {p.name for p in tmp_path.iterdir()}
    with pytest.raises(MigrationIOError):
        with existing_migration_file_lock(target):
            pass
    assert {p.name for p in tmp_path.iterdir()} == before
    leaf.write_bytes(b"")
    with pytest.raises(MigrationIOError):
        with existing_migration_file_lock(target):
            pass
    assert leaf.read_bytes() == b""
    leaf.write_bytes(b"L")
    alias = tmp_path / "other.lock"
    alias.hardlink_to(leaf)
    with pytest.raises(MigrationIOError):
        with existing_migration_file_lock(tmp_path / "other"):
            pass
    assert leaf.read_bytes() == alias.read_bytes() == b"L"


@pytest.mark.skipif(os.name != "nt", reason="Windows physical namespace pinning")
def test_existing_migration_lock_excludes_writer_across_processes_without_writes(tmp_path):
    from core.infrastructure.file_lock import cross_process_file_lock

    target = tmp_path / "ledger"
    leaf = tmp_path / "ledger.lock"
    leaf.write_bytes(b"sentinel")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"other")
    before = {p.name for p in tmp_path.iterdir()}
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from core.infrastructure.file_lock import cross_process_file_lock\n"
        "from core.assistant_runtime.migration_io import existing_migration_file_lock\n"
        "target=Path(sys.argv[1])\n"
        "lock=cross_process_file_lock(target, timeout=0) if sys.argv[2]=='writer' else existing_migration_file_lock(target, timeout=0)\n"
        "try:\n"
        " with lock:\n"
        "  print('acquired', flush=True)\n"
        "  sys.stdin.readline()\n"
        "except TimeoutError:\n"
        " print('blocked', flush=True)\n"
    )
    def child(kind):
        return subprocess.Popen([sys.executable, "-c", script, str(target), kind],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW)

    with existing_migration_file_lock(target):
        with pytest.raises(OSError):
            os.replace(replacement, leaf)
        process = child("writer")
        output, error = process.communicate(timeout=10)
        assert process.returncode == 0, error
        assert output.strip() == "blocked"

    with cross_process_file_lock(target):
        process = child("reader")
        output, error = process.communicate(timeout=10)
        assert process.returncode == 0, error
        assert output.strip() == "blocked"

    with existing_migration_file_lock(target):
        with existing_migration_file_lock(target):
            pass
    assert {p.name for p in tmp_path.iterdir()} == before
    assert leaf.read_bytes() == b"sentinel"
    assert replacement.read_bytes() == b"other"


@pytest.mark.skipif(os.name != "nt", reason="Windows physical namespace pinning")
def test_affairs_readonly_keeps_offline_wait_and_online_nonblocking(tmp_path, monkeypatch):
    from core.assistant_runtime import migration_affairs_conflicts as conflicts, native
    from core.infrastructure import native_runtime
    from core.infrastructure.file_lock import cross_process_file_lock
    from core.web.services import personal_affairs_service
    from core.web.services.session import directory_runtime

    plugin = tmp_path / "agents" / "assistant" / "plugins" / "personal-affairs"
    ledger = plugin / "affairs" / "items.jsonl"
    ledger.parent.mkdir(parents=True)
    (tmp_path / "affairs_sync_receipts").mkdir()
    leaf = ledger.with_name(ledger.name + ".lock")
    leaf.write_bytes(b"sentinel")
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_AGENT_ID", "assistant")
    monkeypatch.setattr(native, "_SESSION_ID", "test")
    monkeypatch.setattr(native, "_STOP_REQUESTED", threading.Event())
    monkeypatch.setattr(native_runtime, "assistant_native_root", lambda: tmp_path)
    monkeypatch.setattr(directory_runtime, "directory_store_project_root", lambda: tmp_path)
    monkeypatch.setattr(personal_affairs_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(personal_affairs_service, "get_personal_affairs_service",
        lambda: SimpleNamespace(store=SimpleNamespace(plugin_root=lambda agent_id: plugin)))

    acquired, release = threading.Event(), threading.Event()
    def writer():
        with cross_process_file_lock(ledger):
            acquired.set()
            release.wait(5)
    worker = threading.Thread(target=writer, daemon=True)
    worker.start()
    assert acquired.wait(2)
    timer = None
    try:
        monkeypatch.setattr(native, "_OFFLINE_MIGRATION", False)
        with native._LOCK, pytest.raises(TimeoutError):
            with conflicts.locked_affairs_target(tmp_path, target_agent_id="assistant", readonly=True):
                pass
        monkeypatch.setattr(native, "_OFFLINE_MIGRATION", True)
        timer = threading.Timer(0.2, release.set)
        timer.start()
        start = time.monotonic()
        with native._LOCK, conflicts.locked_affairs_target(tmp_path, target_agent_id="assistant", readonly=True):
            assert time.monotonic() - start >= 0.1
    finally:
        release.set()
        if timer is not None:
            timer.join()
        worker.join(timeout=2)
    assert not worker.is_alive()
    assert leaf.read_bytes() == b"sentinel"
    assert not ledger.exists()


def test_stable_file_and_tree_are_exact_read_only_snapshots(tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    path = folder / "data.json"
    raw = b'{"private":"source body"}'
    path.write_bytes(raw)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    value = read_stable_file(path, len(raw))
    assert value.raw == raw and value.sha256 == hashlib.sha256(raw).hexdigest()
    assert strict_json(value.raw) == {"private": "source body"}
    verify_snapshot(value)
    assert fingerprint_tree(folder)[0] == value
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    path.write_bytes(b"modified")
    with pytest.raises(MigrationIOError, match="source_changed"):
        verify_snapshot(value)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}',
    b'{"a":"\\ud800"}', b'not json', b'\xff'])
def test_strict_json_does_not_echo_invalid_source(raw):
    with pytest.raises(MigrationIOError, match="^invalid_source_json$"):
        strict_json(raw)


def test_missing_size_and_tree_caps_do_not_mutate_source(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(MigrationIOError):
        check_path(missing)
    assert not missing.exists()
    path = tmp_path / "private-source"
    path.write_bytes(b"12345")
    with pytest.raises(MigrationIOError, match="file_byte_limit"):
        read_stable_file(path, 4)
    with pytest.raises(MigrationIOError):
        fingerprint_tree(tmp_path, max_total_bytes=4)
    (tmp_path / "second").write_bytes(b"x")
    with pytest.raises(MigrationIOError, match="file_limit"):
        fingerprint_tree(tmp_path, max_files=1)
    assert path.read_bytes() == b"12345"


def test_linked_file_and_linked_ancestor_are_not_read(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "body"
    target.write_bytes(b"private")
    link = tmp_path / "alias"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("native symlink privilege unavailable")
    with pytest.raises(MigrationIOError, match="linked_source"):
        read_stable_file(link / "body", 16)
    with pytest.raises(MigrationIOError, match="linked_source"):
        fingerprint_tree(link)


def test_hardlinked_source_is_rejected(tmp_path):
    path = tmp_path / "original"
    path.write_bytes(b"same bytes")
    other = tmp_path / "alias"
    other.hardlink_to(path)
    with pytest.raises(MigrationIOError, match="source_type_or_link_invalid"):
        read_stable_file(other, 64)


def test_no_source_or_content_in_error_messages(tmp_path):
    path = tmp_path / "PRIVATE_SOURCE_NAME"
    path.write_bytes(b"PRIVATE_BODY")
    with pytest.raises(MigrationIOError) as error:
        read_stable_file(path, 1)
    assert "PRIVATE" not in str(error.value)
    assert json.dumps({"code": str(error.value)})


def test_deletion_between_path_check_and_stat_has_a_bounded_error(tmp_path, monkeypatch):
    from core.assistant_runtime import migration_io as owner
    path = tmp_path / "PRIVATE_NAME"
    path.write_bytes(b"private")
    def removed(_path):
        raise FileNotFoundError("PRIVATE_PATH")
    monkeypatch.setattr(owner, "path_identity", removed)
    with pytest.raises(MigrationIOError) as error:
        read_stable_file(path, 32)
    assert str(error.value) == "source_unavailable_or_changed"


def test_verified_directory_is_published_by_handle(tmp_path):
    import os
    if os.name != "nt":
        pytest.skip("native Windows publication")
    pending, final = tmp_path / ".pending", tmp_path / "published"
    pending.mkdir()
    (pending / "file").write_bytes(b"verified")
    publish_directory(pending, final, path_identity(pending))
    assert not pending.exists() and (final / "file").read_bytes() == b"verified"


def test_rebound_pending_directory_cannot_be_published(tmp_path):
    import os
    if os.name != "nt":
        pytest.skip("native Windows publication")
    pending, final = tmp_path / ".pending", tmp_path / "published"
    pending.mkdir()
    expected = path_identity(pending)
    pending.rename(tmp_path / "original")
    pending.mkdir()
    with pytest.raises(MigrationIOError, match="target_pending_changed"):
        publish_directory(pending, final, expected)
    assert not final.exists()


def test_mutable_profile_lock_reuses_os_lock_and_pins_the_leaf(tmp_path):
    import os
    if os.name != "nt":
        pytest.skip("native Windows file lease")
    from core.assistant_runtime.migration_io import pinned_mutable_file
    from core.infrastructure.file_lock import cross_process_file_lock
    target = tmp_path / "host-owner"
    leaf = tmp_path / "host-owner.lock"
    with pinned_mutable_file(leaf):
        with cross_process_file_lock(target, timeout=0):
            pass
        assert leaf.read_bytes() == b"\0"
        with pytest.raises(OSError):
            leaf.rename(tmp_path / "rebound")
    leaf.rename(tmp_path / "after-release")


def test_mutable_profile_lock_rejects_hardlinked_leaf_before_writing(tmp_path):
    import os
    if os.name != "nt":
        pytest.skip("native Windows file lease")
    from core.assistant_runtime.migration_io import pinned_mutable_file
    original = tmp_path / "private"
    original.write_bytes(b"original")
    leaf = tmp_path / "host-owner.lock"
    leaf.hardlink_to(original)
    with pytest.raises((ValueError, OSError)):
        with pinned_mutable_file(leaf):
            pytest.fail("hardlinked lock admitted")
    assert original.read_bytes() == b"original"
