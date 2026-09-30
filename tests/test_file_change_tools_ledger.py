# -*- coding: utf-8 -*-
"""四个写工具与 file_change_ledger 的集成测试（真实临时目录落盘验证）。"""

from pathlib import Path

import pytest

from core.chat import file_change_ledger as fcl
from tools.shell_tools import create_file, edit_file
from tools.code_analysis_tools import apply_diff_edit, apply_patch_edit


@pytest.fixture()
def ledger_scope(tmp_path: Path):
    holder = type("Scope", (), {})()
    holder.root = tmp_path
    holder.session_id = "tools-sess"
    holder.turn_id = "tools-turn-1"
    return holder


def _bind(scope):
    return fcl.bind_turn_scope(scope.session_id, scope.turn_id, project_root=scope.root)


def _changes(scope):
    return {
        item["path"]: item
        for item in fcl.turn_file_changes(scope.root, scope.session_id, scope.turn_id)
    }


def _full_read(path: Path) -> None:
    from tools.shell_tools import read_file

    result = read_file(str(path), max_lines=None, offset=0)
    assert result.startswith("[文件]"), result


def test_create_file_new_records_created_state(ledger_scope):
    target = ledger_scope.root / "fresh.py"
    with _bind(ledger_scope):
        result = create_file(str(target), "a = 1\nb = 2\n")

    assert "[OK]" in result
    changes = _changes(ledger_scope)
    assert changes["fresh.py"]["state"] == "created"
    assert changes["fresh.py"]["additions"] == 2


def test_create_file_overwrite_restores_previous_content(ledger_scope):
    target = ledger_scope.root / "over.txt"
    target.write_text("original\n", encoding="utf-8")
    with _bind(ledger_scope):
        _full_read(target)
        create_file(str(target), "replaced\n")

    changes = _changes(ledger_scope)
    assert changes["over.txt"]["state"] == "modified"

    result = fcl.apply_turn_rewind(
        ledger_scope.root, ledger_scope.session_id, ledger_scope.turn_id
    )
    assert result["status"] == "applied"
    assert target.read_text(encoding="utf-8") == "original\n"


def test_edit_file_checkpoint_restores_pre_image(ledger_scope):
    target = ledger_scope.root / "code.py"
    target.write_text("value = 1\nprint(value)\n", encoding="utf-8")
    with _bind(ledger_scope):
        _full_read(target)
        result = edit_file(str(target), "value = 1", "value = 42")

    assert "成功" in result
    assert target.read_text(encoding="utf-8").startswith("value = 42")
    changes = _changes(ledger_scope)
    assert changes["code.py"]["state"] == "modified"

    fcl.apply_turn_rewind(ledger_scope.root, ledger_scope.session_id, ledger_scope.turn_id)
    assert target.read_text(encoding="utf-8") == "value = 1\nprint(value)\n"


def test_apply_diff_edit_checkpoint(ledger_scope):
    target = ledger_scope.root / "diffed.py"
    target.write_text("x = 1\ny = 2\n", encoding="utf-8")
    with _bind(ledger_scope):
        _full_read(target)
        result = apply_diff_edit(
            str(target),
            "<<<<<<< SEARCH\nx = 1\ny = 2\n=======\nx = 999\ny = 2\n>>>>>>> REPLACE",
        )
    assert "成功" in result
    assert "x = 999" in target.read_text(encoding="utf-8")

    preview = fcl.preview_turn_rewind(
        ledger_scope.root, ledger_scope.session_id, ledger_scope.turn_id
    )
    assert preview["canApply"] is True
    fcl.apply_turn_rewind(ledger_scope.root, ledger_scope.session_id, ledger_scope.turn_id)
    assert target.read_text(encoding="utf-8") == "x = 1\ny = 2\n"
def test_apply_patch_edit_add_and_delete_rewind(ledger_scope):
    existing = ledger_scope.root / "victim.txt"
    existing.write_text("delete me\n", encoding="utf-8")
    patch = """*** Begin Patch
*** Add File: added.txt
+hello
*** Delete File: victim.txt
*** End Patch"""
    with _bind(ledger_scope):
        _full_read(existing)
        result = apply_patch_edit(patch, cwd=str(ledger_scope.root))

    import json

    assert json.loads(result)["status"] == "ok"
    changes = _changes(ledger_scope)
    assert changes["added.txt"]["state"] == "created"
    assert changes["victim.txt"]["state"] == "deleted"

    rewind = fcl.apply_turn_rewind(
        ledger_scope.root, ledger_scope.session_id, ledger_scope.turn_id
    )
    assert rewind["status"] == "applied"
    assert not (ledger_scope.root / "added.txt").exists()
    assert existing.read_text(encoding="utf-8") == "delete me\n"


def test_multi_write_turn_rewinds_to_pre_turn_state(ledger_scope):
    target = ledger_scope.root / "story.txt"
    target.write_text("v1\n", encoding="utf-8")
    with _bind(ledger_scope):
        _full_read(target)
        create_file(str(target), "v2\n")
        edit_file(str(target), "v2", "v3")
        edit_file(str(target), "v3", "v4")

    assert target.read_text(encoding="utf-8") == "v4\n"
    # Only one pre-image row (first write wins), latest after wins for stats.
    pre_entries = fcl._read_json_lines(
        fcl.turn_history_dir(
            ledger_scope.root, ledger_scope.session_id, ledger_scope.turn_id
        )
        / "pre.jsonl"
    )
    assert len(pre_entries) == 1

    fcl.apply_turn_rewind(ledger_scope.root, ledger_scope.session_id, ledger_scope.turn_id)
    assert target.read_text(encoding="utf-8") == "v1\n"


def test_ledger_failure_does_not_fail_write_tools(ledger_scope, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("ledger exploded")

    monkeypatch.setattr(fcl, "capture_pre_write", boom)
    monkeypatch.setattr(fcl, "capture_post_write", boom)

    target = ledger_scope.root / "resilient.txt"
    with _bind(ledger_scope):
        result = create_file(str(target), "still written\n")

    assert "[OK]" in result
    assert target.read_text(encoding="utf-8") == "still written\n"
