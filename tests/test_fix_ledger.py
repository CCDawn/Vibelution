# -*- coding: utf-8 -*-
"""Tests: scripts/fix_ledger.py (cross-session fix knowledge ledger)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fix_ledger  # noqa: E402


def _git_init(root: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    subprocess.run(
        ["git", "-C", str(root), "init", "--initial-branch=main"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git_init(root)
    return root


def test_record_and_query_roundtrip(repo: Path) -> None:
    entry = fix_ledger.record_entry(
        repo,
        category="erratum",
        severity="high",
        symptom="重启不重建误诊",
        root_cause="BuildKey 指纹门每次 start 必走",
        lesson="看 build_preflight 事件",
        files=["core/launcher/frontend_build.py"],
        tags=["restart", "frontend"],
    )
    assert entry["id"] == "fxl-0001"
    assert entry["tags"] == ["frontend", "restart"]

    by_keyword = fix_ledger.query_entries(repo, keywords=["误诊"])
    assert len(by_keyword) == 1
    assert by_keyword[0]["rootCause"] == "BuildKey 指纹门每次 start 必走"

    by_file = fix_ledger.query_entries(repo, files=["core/launcher"])
    assert len(by_file) == 1

    by_tag = fix_ledger.query_entries(repo, tags=["restart"])
    assert len(by_tag) == 1

    assert fix_ledger.query_entries(repo, keywords=["不存在"]) == []


def test_record_validates_category_and_secrets(repo: Path) -> None:
    with pytest.raises(fix_ledger.FixLedgerError):
        fix_ledger.record_entry(
            repo, category="bogus", severity="high", symptom="s", root_cause="r"
        )
    with pytest.raises(fix_ledger.FixLedgerError, match="secrets"):
        fix_ledger.record_entry(
            repo,
            category="defect",
            severity="high",
            symptom="key sk-abcdefghijklmnop",
            root_cause="r",
        )
    assert fix_ledger.ledger_path(repo).exists() is False


def test_append_preserves_history_and_ids_increment(repo: Path) -> None:
    fix_ledger.record_entry(repo, category="defect", severity="low", symptom="s1", root_cause="r1")
    fix_ledger.record_entry(repo, category="defect", severity="low", symptom="s2", root_cause="r2")
    entries = fix_ledger.query_entries(repo, limit=10)
    assert [e["id"] for e in entries] == ["fxl-0002", "fxl-0001"]


def test_corrupt_line_tolerated(repo: Path) -> None:
    path = fix_ledger.ledger_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-json\n", encoding="utf-8")
    fix_ledger.record_entry(repo, category="recipe", severity="medium", symptom="s", root_cause="r")
    entries = fix_ledger.query_entries(repo, keywords=["s"])
    assert len(entries) == 1


def test_import_is_idempotent(repo: Path, tmp_path: Path) -> None:
    seed = tmp_path / "seed.jsonl"
    seed.write_text(
        json.dumps(
            {
                "category": "erratum",
                "severity": "high",
                "symptom": "seed symptom",
                "rootCause": "seed cause",
                "tags": ["seed"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    first = fix_ledger.import_entries(repo, seed)
    assert first == {"added": 1, "skipped": 0}
    second = fix_ledger.import_entries(repo, seed)
    assert second == {"added": 0, "skipped": 1}
    assert len(fix_ledger.query_entries(repo, keywords=["seed"])) == 1


def test_render_entry_compact(repo: Path) -> None:
    entry = fix_ledger.record_entry(
        repo,
        category="recipe",
        severity="medium",
        symptom="junction 修复",
        root_cause="worktree 缺 node_modules",
        fix_sha="abc1234",
        files=["web"],
    )
    text = fix_ledger.render_entry(entry)
    assert "fxl-0001" in text
    assert "junction 修复" in text
    assert "fix=abc1234" in text
