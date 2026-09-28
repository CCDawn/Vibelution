# -*- coding: utf-8 -*-
"""Tests: scripts/task_brief.py (kickoff brief aggregation)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import agent_session_status as status_tool  # noqa: E402
import fix_ledger  # noqa: E402
import task_brief  # noqa: E402


def _git(root: Path, *arguments: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env.setdefault("GIT_AUTHOR_NAME", "t")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "t")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@example.com")
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    (root / "a.txt").write_text("x", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")
    matrix_dir = root / "tests"
    matrix_dir.mkdir()
    (matrix_dir / "test_matrix.yaml").write_text(
        """
rules:
  - id: llm-core
    description: "LLM client core."
    paths:
      - "core/llm/**"
    commands:
      - "pytest tests/test_llm_client.py -q"
  - id: chat-route
    description: "Chat route surface."
    paths:
      - "web/src/routes/chat/**"
    commands:
      - "pytest tests/test_chat.py -q"
""",
        encoding="utf-8",
    )
    return root


def test_keywords_extract_filters_stopwords() -> None:
    keywords = task_brief.extract_keywords("修复 fallback 路由 重连 问题")
    assert "fallback" in keywords
    assert "路由" in keywords
    assert "重连" in keywords
    assert "修复" not in keywords
    assert "问题" not in keywords


def test_brief_matches_matrix_rules_and_reports_commands(repo: Path) -> None:
    brief = task_brief.build_brief(repo, task="修 LLM 客户端", files=["core/llm/client.py"])
    ids = [rule["id"] for rule in brief["matchedRules"]]
    assert ids == ["llm-core"]
    assert brief["matchedRules"][0]["commands"] == ["pytest tests/test_llm_client.py -q"]


def test_brief_flags_claim_conflicts(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "fake_coordination.py"
    fake.write_text(
        "import json\n"
        + f"print(json.dumps({json.dumps({'claims': [{'id': 'c1', 'agentId': 'agent-busy', 'branch': 'codex/other', 'status': 'active', 'scopes': ['core/llm']}]})}))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(status_tool, "GUARD_SCRIPT_CANDIDATES", (fake,))

    brief = task_brief.build_brief(repo, task="改 llm", files=["core/llm/client.py"])

    assert len(brief["claimConflicts"]) == 1
    assert brief["claimConflicts"][0]["agentId"] == "agent-busy"


def test_brief_includes_fix_history_from_ledger(repo: Path) -> None:
    fix_ledger.record_entry(
        repo,
        category="erratum",
        severity="high",
        symptom="fallback 路由缺失是设计",
        root_cause="c56d432dc 有意拆除后重建",
        files=["core/llm"],
    )
    brief = task_brief.build_brief(repo, task="fallback 路由失效", files=["core/llm/client.py"])
    assert len(brief["fixHistory"]) == 1
    assert "fallback" in brief["fixHistory"][0]["symptom"]


def test_brief_doc_guides(repo: Path) -> None:
    brief = task_brief.build_brief(repo, task="chat 面板", files=["web/src/routes/chat/x.tsx"])
    assert "web/src/routes/chat/README.md" in brief["docGuides"]


def test_brief_degrades_when_coordination_missing(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_tool, "GUARD_SCRIPT_CANDIDATES", ())
    brief = task_brief.build_brief(repo, task="任意", files=["core/llm/client.py"])
    assert brief["claimConflicts"] == []
    assert brief["matchedRules"]


def test_render_text_contains_sections(repo: Path) -> None:
    brief = task_brief.build_brief(repo, task="llm 重连", files=["core/llm/client.py"])
    text = task_brief.render_text(brief)
    assert "任务简报" in text
    assert "域定位与测试建议" in text
    assert "claim 冲突预检" in text
    assert "相关修复历史" in text
    assert "pytest tests/test_llm_client.py -q" in text
