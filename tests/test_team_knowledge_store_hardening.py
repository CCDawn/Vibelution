# -*- coding: utf-8 -*-
"""Tests: team knowledge store hardening (line-tolerant read, atomic surrogate-immune write)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.web.services.team_knowledge import store  # noqa: E402


def test_read_jsonl_keeps_good_lines_when_one_line_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "index.jsonl"
    path.write_text(
        '{"id": "a"}\n{"id": broken\n{"id": "c"}\n',
        encoding="utf-8",
    )
    items = store._read_jsonl(path)
    assert [item["id"] for item in items] == ["a", "c"]


def test_read_jsonl_survives_bad_bytes_without_emptying(tmp_path: Path) -> None:
    path = tmp_path / "index.jsonl"
    path.write_bytes(b'{"id": "a"}\n\xff\xfe bad bytes \n{"id": "c"}\n')
    items = store._read_jsonl(path)
    ids = [item.get("id") for item in items]
    assert "a" in ids and "c" in ids


def test_write_json_is_surrogate_immune_and_roundtrips(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    payload = {"title": "lone surrogate \ud800 end", "plain": "正常中文"}
    store._write_json(path, payload)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["plain"] == "正常中文"
    assert loaded["title"].endswith(" end")


def test_write_jsonl_leaves_no_temp_residue(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    store._write_jsonl(path, [{"id": 1}, {"id": 2}])
    assert len(store._read_jsonl(path)) == 2
    assert list(tmp_path.glob(".rows.jsonl.*")) == []
