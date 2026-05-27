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
