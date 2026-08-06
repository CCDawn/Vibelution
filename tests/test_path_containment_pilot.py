"""Path containment pilot: Python reference + optional Rust parity."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.infrastructure.path_containment import (
    contain_path,
    contain_path_dict,
    resolve_path_containment_binary,
)


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


@pytest.mark.skipif(resolve_path_containment_binary() is None, reason="Rust binary not built")
def test_rust_binary_parity(tmp_path: Path):
    binary = resolve_path_containment_binary()
    assert binary is not None
    cases = [
        "workspace/a.txt",
        "../secret.txt",
        "a/b/../../c.txt",
    ]
    for candidate in cases:
        py = contain_path_dict(tmp_path, candidate, engine="python")
        completed = subprocess.run(
            [str(binary)],
            input=json.dumps({"projectRoot": str(tmp_path), "candidate": candidate}),
            text=True,
            capture_output=True,
            check=True,
        )
        rust = json.loads(completed.stdout)
        assert rust["ok"] is py["ok"]
        assert rust.get("error") == py.get("error")
        if py["ok"]:
            assert str(rust.get("relative") or "").replace("\\", "/") == str(py.get("relative") or "").replace("\\", "/")
