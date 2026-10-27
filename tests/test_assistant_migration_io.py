"""Migration readers never create, repair or silently truncate their sources."""
import hashlib
import json

import pytest

from core.assistant_runtime.migration_io import (
    MigrationIOError, check_path, fingerprint_tree, read_stable_file, strict_json, verify_snapshot,
    path_identity, publish_directory,
)


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
