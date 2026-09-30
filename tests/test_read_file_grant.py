"""完整读取后才能改已有文件；局部读取和 shell 不构成写入授权。"""

import os
from pathlib import Path

from core.chat import file_change_ledger as fcl
from core.chat.read_file_grant import FULL_READ_REQUIRED
from core.prompt_manager.sections import make_reading_rules_section
from tools.code_analysis_tools import apply_diff_edit, apply_patch_edit
from tools.Key_Tools import _cli_tool_docstring, create_key_tools
from tools.shell_tools import create_file, edit_file, read_file


def _read_file_tool(file_path: str, *, max_lines: int = 0, offset: int = 0) -> str:
    tool = next(item for item in create_key_tools() if item.name == "read_file_tool")
    return tool.invoke({"file_path": file_path, "max_lines": max_lines, "offset": offset})


def _bind(root: Path, session: str = "grant-sess", turn: str = "grant-turn"):
    return fcl.bind_turn_scope(session, turn, project_root=root)


def _store(root: Path, session: str = "grant-sess") -> Path:
    return fcl.file_history_root(root, session) / "read_grants.jsonl"


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_partial_read_does_not_allow_edit(tmp_path: Path):
    target = tmp_path / "partial.py"
    _write(target, "alpha = 1\nbeta = 2\n")
    with _bind(tmp_path):
        viewed = read_file(str(target), max_lines=1, offset=0)
        result = edit_file(str(target), "alpha = 1", "alpha = 9")

    assert "(已截断)" in viewed
    assert FULL_READ_REQUIRED in result
    assert target.read_text(encoding="utf-8").startswith("alpha = 1")
    assert not _store(tmp_path).exists()


def test_full_read_allows_edit_until_bytes_change(tmp_path: Path):
    target = tmp_path / "full.py"
    _write(target, "alpha = 1\n")
    with _bind(tmp_path):
        assert read_file(str(target), max_lines=None, offset=0).startswith("[文件]")
        first = edit_file(str(target), "alpha = 1", "alpha = 2")
        assert "成功" in first
        stored = fcl._read_json_lines(_store(tmp_path))[-1]
        assert stored["source"] == "write"
        mutated = bytearray(target.read_bytes())
        mutated[0] = (mutated[0] + 1) % 256
        target.write_bytes(bytes(mutated))
        os.utime(target, ns=(target.stat().st_atime_ns, int(stored["mtimeNs"])))
        second = edit_file(str(target), "alpha = 2", "alpha = 3")

    assert FULL_READ_REQUIRED in second
    assert fcl._read_json_lines(_store(tmp_path))[-1]["revision"] == stored["revision"]


def test_mtime_only_change_rejects_same_bytes(tmp_path: Path):
    target = tmp_path / "touched.py"
    _write(target, "alpha = 1\n")
    original = target.read_bytes()
    with _bind(tmp_path):
        assert read_file(str(target), max_lines=0, offset=0).startswith("[文件]")
        stat = target.stat()
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
        result = edit_file(str(target), "alpha = 1", "alpha = 2")

    assert FULL_READ_REQUIRED in result
    assert target.read_bytes() == original


def test_new_file_can_be_created_and_then_edited(tmp_path: Path):
    target = tmp_path / "fresh.py"
    with _bind(tmp_path):
        created = create_file(str(target), "alpha = 1\n")
        edited = edit_file(str(target), "alpha = 1", "alpha = 2")

    assert "[OK]" in created
    assert "成功" in edited
    assert "alpha = 2" in target.read_text(encoding="utf-8")


def test_unbound_edit_keeps_current_behavior(tmp_path: Path):
    target = tmp_path / "free.py"
    _write(target, "alpha = 1\n")

    result = edit_file(str(target), "alpha = 1", "alpha = 2")

    assert "成功" in result
    assert not _store(tmp_path).exists()


def test_resume_keeps_stored_fingerprint_instead_of_current_disk(tmp_path: Path):
    target = tmp_path / "resume.py"
    _write(target, "alpha = 1\n")
    with _bind(tmp_path, turn="turn-1"):
        assert read_file(str(target), max_lines=None, offset=0).startswith("[文件]")
        stored = fcl._read_json_lines(_store(tmp_path))[-1]
    _write(target, "alpha = 8\n")
    with _bind(tmp_path, turn="turn-2"):
        result = edit_file(str(target), "alpha = 8", "alpha = 9")

    assert FULL_READ_REQUIRED in result
    assert fcl._read_json_lines(_store(tmp_path))[-1] == stored
    assert target.read_text(encoding="utf-8").startswith("alpha = 8")


def test_other_session_does_not_reuse_the_grant(tmp_path: Path):
    target = tmp_path / "session.py"
    _write(target, "alpha = 1\n")
    with _bind(tmp_path, session="sess-a"):
        assert read_file(str(target), max_lines=None, offset=0).startswith("[文件]")
    with _bind(tmp_path, session="sess-b"):
        result = edit_file(str(target), "alpha = 1", "alpha = 2")

    assert FULL_READ_REQUIRED in result
    assert target.read_text(encoding="utf-8").startswith("alpha = 1")


def test_offset_read_does_not_grant_even_when_the_rest_is_shown(tmp_path: Path):
    target = tmp_path / "offset.py"
    _write(target, "alpha = 1\nbeta = 2\n")
    with _bind(tmp_path):
        viewed = read_file(str(target), max_lines=None, offset=1)
        result = edit_file(str(target), "beta = 2", "beta = 9")

    assert "(已截断)" not in viewed
    assert "beta = 2" in viewed
    assert FULL_READ_REQUIRED in result


def test_default_page_grants_only_when_the_whole_file_fits(tmp_path: Path):
    short = tmp_path / "short.py"
    long = tmp_path / "long.py"
    _write(short, "alpha = 1\n")
    _write(long, "".join(f"line_{index} = {index}\n" for index in range(90)))
    with _bind(tmp_path):
        assert read_file(str(short), max_lines=80, offset=0).startswith("[文件]")
        short_edit = edit_file(str(short), "alpha = 1", "alpha = 2")
        assert read_file(str(long), max_lines=80, offset=0)
        long_edit = edit_file(str(long), "line_0 = 0", "line_0 = 1")

    assert "成功" in short_edit
    assert FULL_READ_REQUIRED in long_edit
    assert "line_0 = 0" in long.read_text(encoding="utf-8")


def test_empty_file_full_read_allows_overwrite(tmp_path: Path):
    target = tmp_path / "empty.py"
    _write(target, "")
    with _bind(tmp_path):
        assert read_file(str(target), max_lines=None, offset=0).startswith("[文件]")
        result = create_file(str(target), "alpha = 1\n")

    assert "[OK]" in result
    assert "alpha = 1" in target.read_text(encoding="utf-8")


def test_apply_patch_without_read_writes_nothing(tmp_path: Path):
    existing = tmp_path / "old.py"
    _write(existing, "old line\n")
    patch = """*** Begin Patch
*** Add File: fresh.py
+print("hi")
*** Update File: old.py
@@
-old line
+new line
*** Delete File: gone.py
*** End Patch"""
    gone = tmp_path / "gone.py"
    _write(gone, "delete me\n")
    with _bind(tmp_path):
        updated = apply_patch_edit(
            """*** Begin Patch
*** Update File: old.py
@@
-old line
+new line
*** End Patch""",
            cwd=str(tmp_path),
        )
        deleted = apply_patch_edit(
            """*** Begin Patch
*** Delete File: gone.py
*** End Patch""",
            cwd=str(tmp_path),
        )
        mixed = apply_patch_edit(patch, cwd=str(tmp_path))

    assert updated.startswith("[patch] 错误")
    assert deleted.startswith("[patch] 错误")
    assert mixed.startswith("[patch] 错误")
    assert existing.read_text(encoding="utf-8") == "old line\n"
    assert gone.read_text(encoding="utf-8") == "delete me\n"
    assert not (tmp_path / "fresh.py").exists()


def test_apply_diff_without_read_leaves_the_file(tmp_path: Path):
    target = tmp_path / "diff.py"
    _write(target, "alpha = 1\n")
    with _bind(tmp_path):
        result = apply_diff_edit(
            str(target),
            "<<<<<<< SEARCH\nalpha = 1\n=======\nalpha = 2\n>>>>>>> REPLACE",
        )

    assert result.startswith("[编辑] 错误")
    assert FULL_READ_REQUIRED in result
    assert target.read_text(encoding="utf-8").startswith("alpha = 1")


def test_read_file_tool_zero_max_lines_is_a_full_read(tmp_path: Path):
    target = tmp_path / "tool.py"
    _write(target, "alpha = 1\n")
    with _bind(tmp_path):
        viewed = _read_file_tool(str(target), max_lines=0, offset=0)
        result = edit_file(str(target), "alpha = 1", "alpha = 2")

    assert viewed.startswith("[文件]")
    assert "成功" in result


def test_prompts_suggest_read_file_tool_without_blocking_cli():
    common = (Path(__file__).resolve().parents[1] / "core" / "core_prompt" / "COMMON.md").read_text(encoding="utf-8")
    reading = make_reading_rules_section().compute() or ""
    cli_doc = _cli_tool_docstring()

    assert "读取文件内容用 `read_file_tool`" in common
    assert "git、测试、编译" in common
    assert "read_file_tool" in reading
    assert "不要调用 `read_file_tool`" not in reading
    assert "读取文件内容用 `read_file_tool`" in cli_doc
    assert "git、测试和编译" in cli_doc
    assert "读小段" not in cli_doc
    assert "Select-Object -First 80" not in cli_doc
    assert "禁用" not in cli_doc
