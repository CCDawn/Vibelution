# -*- coding: utf-8 -*-
"""file_change_ledger 单元测试：pre-image 账本、崩溃安全、rewind 分类与幂等。"""

from pathlib import Path

import pytest

from core.chat import file_change_ledger as fcl


class _Scope:
    """Deterministic ledger scope bound to a tmp project root."""

    def __init__(self, root: Path):
        self.root = root
        self.session_id = "ledger-sess"
        self.turn_id = "ledger-turn-1"


@pytest.fixture()
def scope(tmp_path):
    return _Scope(tmp_path)


def _bind(scope: _Scope):
    return fcl.bind_turn_scope(scope.session_id, scope.turn_id, project_root=scope.root)


def _summary(scope: _Scope, turn_id: str = ""):
    return fcl.turn_file_changes(
        scope.root,
        scope.session_id,
        turn_id or scope.turn_id,
    )


def _preview(scope: _Scope, turn_id: str = ""):
    return fcl.preview_turn_rewind(scope.root, scope.session_id, turn_id or scope.turn_id)


def _apply(scope: _Scope, **kwargs):
    return fcl.apply_turn_rewind(scope.root, scope.session_id, scope.turn_id, **kwargs)


def test_capture_pre_write_records_absent_sentinel_for_new_file(scope):
    target = scope.root / "created.txt"
    with _bind(scope):
        fcl.capture_pre_write(target)

    entry = fcl._read_json_lines(
        fcl.turn_history_dir(scope.root, scope.session_id, scope.turn_id) / "pre.jsonl"
    )
    assert len(entry) == 1
    assert entry[0]["existed"] is False
    assert not entry[0].get("image")


def test_same_turn_double_write_keeps_first_pre_image(scope):
    target = scope.root / "doc.txt"
    target.write_text("v1\n", encoding="utf-8")
    pre_size = target.stat().st_size
    with _bind(scope):
        fcl.capture_pre_write(target)
        target.write_text("v2\n", encoding="utf-8")
        fcl.capture_post_write(target)
        fcl.capture_pre_write(target)  # second capture must be ignored
        target.write_text("v3\n", encoding="utf-8")
        fcl.capture_post_write(target)

    pre_entries = fcl._read_json_lines(
        fcl.turn_history_dir(scope.root, scope.session_id, scope.turn_id) / "pre.jsonl"
    )
    assert len(pre_entries) == 1
    assert pre_entries[0]["size"] == pre_size

    result = _apply(scope)
    assert result["status"] == "applied"
    assert target.read_text(encoding="utf-8") == "v1\n"


def test_turn_summary_states_created_modified_deleted(scope):
    created = scope.root / "created.txt"
    modified = scope.root / "modified.txt"
    modified.write_text("a\nb\n", encoding="utf-8")
    deleted = scope.root / "deleted.txt"
    deleted.write_text("gone\n", encoding="utf-8")

    with _bind(scope):
        for path in (created, modified, deleted):
            fcl.capture_pre_write(path)
        created.write_text("n1\nn2\nn3\n", encoding="utf-8")
        modified.write_text("a\nb\nc\nd\n", encoding="utf-8")
        deleted.unlink()
        for path in (created, modified, deleted):
            fcl.capture_post_write(path)

    summary = {item["path"]: item for item in _summary(scope)}
    assert summary["created.txt"]["state"] == "created"
    assert summary["created.txt"]["additions"] == 3
    assert summary["modified.txt"]["state"] == "modified"
    assert summary["modified.txt"]["additions"] == 2
    assert summary["modified.txt"]["deletions"] == 0
    assert summary["deleted.txt"]["state"] == "deleted"
    assert summary["deleted.txt"]["deletions"] == 1


def test_created_then_deleted_in_turn_is_net_noop(scope):
    target = scope.root / "ephemeral.txt"
    with _bind(scope):
        fcl.capture_pre_write(target)
        target.write_text("temp\n", encoding="utf-8")
        fcl.capture_post_write(target)
        target.unlink()
        fcl.capture_post_write(target)

    assert _summary(scope) == []
    preview = _preview(scope)
    assert preview["canApply"] is True
    assert preview["files"][0]["classification"] == "safe"
    assert preview["files"][0]["action"] == "none"


def test_external_modified_is_unsafe_and_strict_apply_rejects(scope):
    target = scope.root / "mod.txt"
    target.write_text("one\n", encoding="utf-8")
    with _bind(scope):
        fcl.capture_pre_write(target)
        target.write_text("two\n", encoding="utf-8")
        fcl.capture_post_write(target)
    target.write_text("external\n", encoding="utf-8")

    preview = _preview(scope)
    assert preview["canApply"] is False
    file_item = preview["files"][0]
    assert file_item["classification"] == "external_modified"
    assert file_item["action"] == "none"

    with pytest.raises(fcl.FileChangeRewindConflictError) as exc_info:
        _apply(scope)
    assert exc_info.value.unsafe_files
    # strict rejection must not touch the file
    assert target.read_text(encoding="utf-8") == "external\n"

    forced = _apply(scope, force=True)
    assert forced["applied"] == []
    assert forced["skipped"][0]["classification"] == "external_modified"
    assert target.read_text(encoding="utf-8") == "external\n"


def test_apply_is_idempotent_via_audit_marker(scope):
    target = scope.root / "doc.txt"
    target.write_text("before\n", encoding="utf-8")
    with _bind(scope):
        fcl.capture_pre_write(target)
        target.write_text("after\n", encoding="utf-8")
        fcl.capture_post_write(target)

    first = _apply(scope)
    assert first["alreadyApplied"] is False
    assert target.read_text(encoding="utf-8") == "before\n"

    second = _apply(scope)
    assert second["alreadyApplied"] is True
    assert target.read_text(encoding="utf-8") == "before\n"


def test_missing_pre_image_file_is_checkpoint_missing(scope):
    target = scope.root / "doc.txt"
    target.write_text("before\n", encoding="utf-8")
    with _bind(scope):
        fcl.capture_pre_write(target)
        target.write_text("after\n", encoding="utf-8")
        fcl.capture_post_write(target)

    # Simulate checkpoint corruption: the stored pre-image payload is gone.
    turn_dir = fcl.turn_history_dir(scope.root, scope.session_id, scope.turn_id)
    for image in (turn_dir / "images").glob("*.bin"):
        image.unlink()

    preview = _preview(scope)
    assert preview["files"][0]["classification"] == "checkpoint_missing"
    assert preview["canApply"] is False


def test_write_without_after_snapshot_is_ignored(scope):
    target = scope.root / "doc.txt"
    target.write_text("before\n", encoding="utf-8")
    with _bind(scope):
        fcl.capture_pre_write(target)
        # simulates a crash between pre capture and the post-write capture
    target.write_text("after\n", encoding="utf-8")

    preview = _preview(scope)
    assert preview["files"][0]["classification"] == "ignored"
    assert preview["canApply"] is False
    assert preview["capabilityNote"]


def test_torn_trailing_line_is_skipped_on_read(scope):
    target = scope.root / "doc.txt"
    target.write_text("before\n", encoding="utf-8")
    with _bind(scope):
        fcl.capture_pre_write(target)
        target.write_text("after\n", encoding="utf-8")
        fcl.capture_post_write(target)

    pre_file = (
        fcl.turn_history_dir(scope.root, scope.session_id, scope.turn_id) / "pre.jsonl"
    )
    with pre_file.open("ab") as handle:
        handle.write(b'{"v":1,"kind":"pre","path":"C:/torn')  # crash mid-append

    # The valid entry survives the torn tail and still drives the rewind.
    result = _apply(scope)
    assert result["status"] == "applied"
    assert target.read_text(encoding="utf-8") == "before\n"


def test_preview_and_apply_return_none_or_empty_without_checkpoint(scope):
    assert _preview(scope) is None
    assert _summary(scope) == []
    result = _apply(scope)
    assert result["status"] == "empty"
    assert result["applied"] == []


def test_capture_outside_turn_context_is_noop(tmp_path):
    target = tmp_path / "doc.txt"
    target.write_text("data\n", encoding="utf-8")
    fcl.capture_pre_write(target)
    fcl.capture_post_write(target)
    assert not (tmp_path / "workspace" / "sessions").exists()


def test_display_path_is_project_relative_inside_root(scope):
    target = scope.root / "sub" / "doc.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x\n", encoding="utf-8")
    with _bind(scope):
        fcl.capture_pre_write(target)
    summary = _summary(scope)
    assert summary == []  # pre without post is not a change
    preview = _preview(scope)
    assert preview["files"][0]["path"] == "sub/doc.txt"
