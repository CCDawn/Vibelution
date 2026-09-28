# -*- coding: utf-8 -*-
"""Tests: scripts/agent_session_status.py (read-only situational awareness)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import agent_session_status as status_tool  # noqa: E402


def _git(root: Path, *arguments: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env.setdefault("GIT_AUTHOR_NAME", "t")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "t")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@example.com")
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    (root / "a.txt").write_text("hello", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")
    return root


def _write_fake_coordination(directory: Path, payload: dict) -> Path:
    script = directory / "fake_coordination.py"
    script.write_text(
        "import json, sys\n"
        f"print(json.dumps({json.dumps(payload)}))\n",
        encoding="utf-8",
    )
    return script


def test_scope_covers_prefix_and_repo_scope() -> None:
    assert status_tool.scope_covers("core/llm", "core/llm/client.py")
    assert status_tool.scope_covers("core/llm", "core/llm")
    assert not status_tool.scope_covers("core/llm", "core/web/routes")
    assert status_tool.scope_covers(".", "anything/at/all")


def test_claims_touching_matches_by_scope() -> None:
    claims = [
        {"id": "c1", "scopes": ["core/llm"]},
        {"id": "c2", "scopes": ["web/src/routes/chat"]},
    ]
    touched = status_tool.claims_touching(claims, ["core/llm/client.py"])
    assert [c["id"] for c in touched] == ["c1"]


def test_report_degrades_without_coordination(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_tool, "GUARD_SCRIPT_CANDIDATES", ())
    report = status_tool.build_report(repo, [])
    assert report["coordinationAvailable"] is False
    assert report["activeClaims"] == []
    assert report["recentMainMerges"]
    assert report["mainDirtyPaths"] == []


def test_report_with_claims_and_dirty_main(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "claims": [
            {
                "id": "claim-1",
                "agentId": "agent-x",
                "branch": "codex/feature-a",
                "status": "active",
                "scopes": ["a.txt"],
            },
            {"id": "claim-2", "status": "completed", "scopes": ["a.txt"]},
        ],
        "agents": [],
    }
    script = _write_fake_coordination(tmp_path, payload)
    monkeypatch.setattr(status_tool, "GUARD_SCRIPT_CANDIDATES", (script,))
    (repo / "a.txt").write_text("dirty", encoding="utf-8")

    report = status_tool.build_report(repo, ["a.txt"])

    assert report["coordinationAvailable"] is True
    assert [c["claimId"] for c in report["activeClaims"]] == ["claim-1"]
    assert "a.txt" in report["mainDirtyPaths"]
    assert report["mainDirtySuspectedOwners"][0]["agentId"] == "agent-x"
    assessment = report["mergeAssessment"]
    assert assessment["readyToMerge"] is False
    assert assessment["mainDirty"] is True
    assert assessment["claimsTouchingTarget"][0]["agentId"] == "agent-x"


def test_merge_assessment_ready_when_clean(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(status_tool, "GUARD_SCRIPT_CANDIDATES", ())
    report = status_tool.build_report(repo, ["core/llm/client.py"])
    assert report["mergeAssessment"]["readyToMerge"] is True


def test_render_text_mentions_sections(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_tool, "GUARD_SCRIPT_CANDIDATES", ())
    report = status_tool.build_report(repo, [])
    text = status_tool.render_text(report)
    assert "并行会话态势" in text
    assert "活跃 worktree" in text
    assert "main 最近合入" in text
    assert "干净" in text
