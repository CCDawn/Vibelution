"""Path containment contract tests (canonical Python implementation)."""

from __future__ import annotations

from pathlib import Path

from core.infrastructure.path_containment import contain_path, contain_path_dict


def test_relative_child_ok(tmp_path: Path):
    r = contain_path_dict(tmp_path, "workspace/a.txt")
    assert r["ok"] is True
    assert r["relative"] in {"workspace/a.txt", "workspace\\a.txt"} or str(r["relative"]).replace("\\", "/") == "workspace/a.txt"


def test_parent_escape_rejected(tmp_path: Path):
    r = contain_path_dict(tmp_path, "../secret.txt")
    assert r["ok"] is False
    assert r["error"] == "outside_root"


def test_nested_dotdot_stays_inside(tmp_path: Path):
    r = contain_path_dict(tmp_path, "a/b/../../c.txt")
    assert r["ok"] is True
    assert str(r["relative"]).replace("\\", "/") == "c.txt"


def test_absolute_outside_rejected(tmp_path: Path):
    outside = Path(tmp_path).parent / "outside_file.txt"
    r = contain_path_dict(tmp_path, outside)
    assert r["ok"] is False
    assert r["error"] == "outside_root"


def test_empty_and_null_byte():
    assert contain_path_dict("", "a")["error"] == "empty_root"
    assert contain_path_dict("c:/root", "")["error"] == "empty_candidate"
    assert contain_path_dict("c:/root", "a\x00b")["error"] == "null_byte"


def test_contain_path_delegates_with_python_engine(tmp_path: Path):
    r = contain_path(tmp_path, "a.txt")
    assert r["ok"] is True
    assert r["engine"] == "python"
