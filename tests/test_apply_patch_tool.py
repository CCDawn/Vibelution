import json
from pathlib import Path

from tools.code_analysis_tools import apply_patch_edit


class TestApplyPatchEdit:
    def test_apply_patch_update_file(self, tmp_path: Path):
        file_path = tmp_path / "demo.py"
        file_path.write_text("value = 1\nprint(value)\n", encoding="utf-8")

        result = apply_patch_edit(
            patch_text="""*** Begin Patch
*** Update File: demo.py
@@
-value = 1
+value = 2
*** End Patch""",
            cwd=str(tmp_path),
        )

        payload = json.loads(result)
        assert payload["status"] == "ok"
        assert file_path.read_text(encoding="utf-8") == "value = 2\nprint(value)\n"

    def test_apply_patch_add_and_delete_file(self, tmp_path: Path):
        old_path = tmp_path / "old.txt"
        old_path.write_text("remove me\n", encoding="utf-8")

        result = apply_patch_edit(
            patch_text="""*** Begin Patch
*** Add File: new.txt
+hello
+world
*** Delete File: old.txt
*** End Patch""",
            cwd=str(tmp_path),
        )

        payload = json.loads(result)
        assert payload["status"] == "ok"
        assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello\nworld\n"
        assert not old_path.exists()

    def test_apply_patch_returns_correction_hint_for_missing_hunk(self, tmp_path: Path):
        file_path = tmp_path / "demo.py"
        file_path.write_text("value = 1\n", encoding="utf-8")

        result = apply_patch_edit(
            patch_text="""*** Begin Patch
*** Update File: demo.py
*** End Patch""",
            cwd=str(tmp_path),
        )

        assert "[patch] 错误" in result
        assert "缺少 @@ hunk" in result

    def test_apply_patch_rejects_target_outside_cwd(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "outside.txt"

        result = apply_patch_edit(
            patch_text="""*** Begin Patch
*** Add File: ../outside.txt
+must not escape
*** End Patch""",
            cwd=str(workspace),
        )

        assert "[patch] [SECURITY]" in result
        assert not outside.exists()

    def test_apply_patch_validation_failure_does_not_leave_partial_writes(self, tmp_path: Path):
        first = tmp_path / "first.txt"
        second = tmp_path / "second.txt"
        first.write_text("before one\n", encoding="utf-8")
        second.write_text("before two\n", encoding="utf-8")

        result = apply_patch_edit(
            patch_text="""*** Begin Patch
*** Update File: first.txt
@@
-before one
+after one
*** Update File: second.txt
@@
-missing content
+after two
*** End Patch""",
            cwd=str(tmp_path),
        )

        assert "[patch] 错误" in result
        assert first.read_text(encoding="utf-8") == "before one\n"
        assert second.read_text(encoding="utf-8") == "before two\n"

    def test_apply_patch_write_failure_rolls_back_prior_files(
        self,
        monkeypatch,
        tmp_path: Path,
    ):
        first = tmp_path / "first.txt"
        second = tmp_path / "second.txt"
        first.write_text("before one\n", encoding="utf-8")
        second.write_text("before two\n", encoding="utf-8")
        original_write_text = Path.write_text

        def fail_second_write(path: Path, *args, **kwargs):
            if path == second:
                original_write_text(path, "partial write\n", encoding="utf-8")
                raise OSError("simulated write failure")
            return original_write_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", fail_second_write)

        result = apply_patch_edit(
            patch_text="""*** Begin Patch
*** Update File: first.txt
@@
-before one
+after one
*** Update File: second.txt
@@
-before two
+after two
*** End Patch""",
            cwd=str(tmp_path),
        )

        assert "原子应用失败" in result
        assert "rollback=completed" in result
        assert first.read_text(encoding="utf-8") == "before one\n"
        assert second.read_text(encoding="utf-8") == "before two\n"
