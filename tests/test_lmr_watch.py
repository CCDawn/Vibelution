#!/usr/bin/env python3
"""LMR watcher 单飞锁/队列/重试升级/端到端假执行器测试。

对应 docs/agents/pr-integration-workflow.md §12.2 / §14.2。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import lmr
import lmr_watch

pytestmark = pytest.mark.integration


@pytest.fixture()
def git_repo(tmp_path, monkeypatch):
    """临时 git 仓库 fixture：隔离继承的仓库级 GIT_* 环境变量。"""
    for key in [name for name in os.environ if name.upper().startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return completed.stdout.strip()

    git("init")
    git("config", "user.email", "lmr-test@example.com")
    git("config", "user.name", "LMR Test")
    (repo / "file.txt").write_text("one\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "c1")
    return repo, git


def _commit(repo: Path, git, content: str) -> str:
    (repo / "file.txt").write_text(content, encoding="utf-8")
    git("add", ".")
    git("commit", "-m", f"c-{content.strip()}")
    return git("rev-parse", "HEAD")


def _register(repo: Path, sha: str, branch: str = "codex/demo") -> dict:
    ledger = lmr.Ledger(lmr.ledger_dir_for(repo))
    record, _ = ledger.register(
        branch=branch,
        sha=sha,
        base="main",
        title=f"title-{sha[:8]}",
        grade="show",
        evidence="manifest.json",
    )
    return record


def _verdict_cmd(verdict: str, findings: list | None = None) -> str:
    """内联假执行器：向 {verdict_path} 写指定 verdict（模板仅用单引号）。"""
    findings_repr = repr(findings or [])
    inner = (
        "import json; json.dump({'verdict': '"
        + verdict
        + "', 'findings': "
        + findings_repr
        + ", 'evidence_section': 'evidence-"
        + verdict
        + "'}, open('{verdict_path}', 'w', encoding='utf-8'))"
    )
    return f'"{sys.executable}" -c "{inner}"'


_SLEEP_CMD = f'"{sys.executable}" -c "import time; time.sleep(30)"'


REVIEWER_CMD_KEY = "VIBELUTION_LMR_REVIEWER_CMD"


def _make_watcher(repo: Path, *, cmd: str | None = None, **overrides) -> lmr_watch.LmrWatcher:
    config_kwargs: dict = {
        "poll_interval": 0.05,
        "review_timeout": 30.0,
        "max_retries": 2,
        "retry_backoff": 0.0,
        "heartbeat_interval": 0.2,
        "lock_stale_after": 5.0,
        "lock_acquire_timeout": 2.0,
    }
    config_kwargs.update(overrides)
    config = lmr_watch.WatcherConfig(**config_kwargs)
    log = lmr_watch.EventLog(lmr.ledger_dir_for(repo) / "watch-test.log")
    env = {REVIEWER_CMD_KEY: cmd} if cmd is not None else {}
    return lmr_watch.LmrWatcher(root=repo, config=config, log=log, env=env)


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("VIBELUTION_LMR_POLL_INTERVAL", "1.5")
    monkeypatch.setenv("VIBELUTION_LMR_REVIEW_TIMEOUT", "7")
    monkeypatch.setenv("VIBELUTION_LMR_MAX_RETRIES", "1")
    config = lmr_watch.load_config_from_env(dict(os.environ))
    assert config.poll_interval == 1.5
    assert config.review_timeout == 7.0
    assert config.max_retries == 1

    monkeypatch.setenv("VIBELUTION_LMR_POLL_INTERVAL", "not-a-number")
    config = lmr_watch.load_config_from_env(dict(os.environ))
    assert config.poll_interval == 10.0


def test_fifo_order():
    queue = lmr_watch.ReviewQueue(aging_interval=100.0)
    assert queue.push("a", seq=1, enqueued_at=1000.0)
    assert queue.push("b", seq=2, enqueued_at=1000.1)
    assert queue.push("c", seq=3, enqueued_at=1000.2)
    assert queue.push("a") is False  # 去重
    assert queue.pop(now=1001.0).lmr_id == "a"
    assert queue.pop(now=1001.0).lmr_id == "b"
    assert queue.pop(now=1001.0).lmr_id == "c"
    assert queue.pop(now=1001.0) is None


def test_aging_boost_prevents_starvation():
    queue = lmr_watch.ReviewQueue(aging_interval=100.0)
    # early：seq 更差（3），但等待久；fresh：seq 更好（2），刚入队
    queue.push("early", seq=3, enqueued_at=1000.0)
    queue.push("fresh", seq=2, enqueued_at=1150.0)
    # now=1200：early 等待 200s → +2 档（eff=1）；fresh 等待 50s → 0 档（eff=2）
    assert queue.pop(now=1200.0).lmr_id == "early"
    assert queue.pop(now=1200.0).lmr_id == "fresh"


def test_split_command_keeps_backslashes_and_quotes():
    tokens = lmr_watch.split_command(r'"C:\path with space\python.exe" -c "import os; os.getcwd()"')
    assert tokens == ["C:\\path with space\\python.exe", "-c", "import os; os.getcwd()"]


def test_lock_takeover_stale_heartbeat(git_repo, tmp_path):
    repo, _ = git_repo
    lock_path = lmr.locks_dir_for(repo) / "review.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stale_ts = datetime.now(timezone.utc) - timedelta(seconds=120)
    lock_path.write_text(
        json.dumps({"pid": os.getpid(), "ts": stale_ts.strftime("%Y-%m-%dT%H:%M:%SZ")}),
        encoding="utf-8",
    )
    log = lmr_watch.EventLog(tmp_path / "log.jsonl")
    lock = lmr_watch.ReviewLock(
        lock_path, heartbeat_interval=30.0, stale_after=90.0, log=log
    )
    assert lock.acquire(timeout=2.0) is True
    assert lock_path.exists()
    lock.release()
    assert not lock_path.exists()
    assert any('"lock-takeover"' in line for line in log.lines())


def test_lock_refuses_fresh_holder(git_repo):
    repo, _ = git_repo
    lock_path = lmr.locks_dir_for(repo) / "review.lock"
    holder = lmr_watch.ReviewLock(lock_path, heartbeat_interval=30.0, stale_after=90.0)
    assert holder.acquire(timeout=1.0) is True
    other = lmr_watch.ReviewLock(lock_path, heartbeat_interval=30.0, stale_after=90.0)
    assert other.acquire(timeout=0.2) is False
    assert not other.held
    holder.release()
    assert holder.acquire(timeout=1.0) is True
    holder.release()


def test_executor_unconfigured_escalates(git_repo):
    repo, git = git_repo
    record = _register(repo, _commit(repo, git, "unconfigured\n"))
    watcher = _make_watcher(repo)  # env 无 reviewer cmd
    assert watcher.executor is None

    assert watcher.run_once() == "escalated"

    ledger = lmr.Ledger(lmr.ledger_dir_for(repo))
    escalated = ledger.get(record["id"])
    assert escalated["state"] == lmr.STATE_ESCALATED
    assert escalated["escalatedReason"] == "reviewer_executor_unconfigured"
    assert not (repo / ".worktrees" / f"lmr-review-{record['id']}").exists()


def test_end_to_end_fake_executor_approve(git_repo):
    repo, git = git_repo
    record = _register(repo, _commit(repo, git, "approve-me\n"))
    watcher = _make_watcher(repo, cmd=_verdict_cmd("approve"))

    assert watcher.poll() == [record["id"]]
    assert watcher.run_once() == "reviewed"

    ledger = lmr.Ledger(lmr.ledger_dir_for(repo))
    approved = ledger.get(record["id"])
    assert approved["state"] == lmr.STATE_APPROVED
    assert approved["publishState"] == lmr.PUBLISH_NA  # 未 merge，不进发布队列
    assert len(approved["reviews"]) == 1
    review = approved["reviews"][0]
    assert review["verdict"] == "approve"
    assert review["evidence_section"] == "evidence-approve"
    assert review["sha"] == record["sha"]
    assert not (repo / ".worktrees" / f"lmr-review-{record['id']}").exists()
    events = watcher.log.lines()
    names = {str(json.loads(line).get("event")) for line in events}
    assert {"enqueued", "started", "verdict", "completed"} <= names


def test_rework_verdict_stores_findings(git_repo):
    repo, git = git_repo
    record = _register(repo, _commit(repo, git, "rework-me\n"))
    findings = [
        {
            "file": "scripts/lmr.py",
            "start_line": 10,
            "end_line": 12,
            "severity": "blocker",
            "category": "logic",
            "confidence": "high",
            "message": "off-by-one",
        }
    ]
    watcher = _make_watcher(repo, cmd=_verdict_cmd("rework", findings))

    assert watcher.run_once() == "reviewed"

    ledger = lmr.Ledger(lmr.ledger_dir_for(repo))
    reworked = ledger.get(record["id"])
    assert reworked["state"] == lmr.STATE_REWORK
    assert reworked["reviews"][0]["findings"] == findings


def test_comment_verdict_stays_in_review(git_repo):
    repo, git = git_repo
    record = _register(repo, _commit(repo, git, "comment-me\n"))
    watcher = _make_watcher(repo, cmd=_verdict_cmd("comment"))

    assert watcher.run_once() == "reviewed"

    ledger = lmr.Ledger(lmr.ledger_dir_for(repo))
    commented = ledger.get(record["id"])
    assert commented["state"] == lmr.STATE_IN_REVIEW
    assert commented["reviews"][0]["verdict"] == "comment"


def test_review_timeout_retry_then_escalated(git_repo):
    repo, git = git_repo
    record = _register(repo, _commit(repo, git, "slow\n"))
    watcher = _make_watcher(
        repo,
        cmd=_SLEEP_CMD,
        review_timeout=0.5,
        max_retries=2,
        retry_backoff=0.0,
    )

    assert watcher.run_once() == "escalated"

    ledger = lmr.Ledger(lmr.ledger_dir_for(repo))
    escalated = ledger.get(record["id"])
    assert escalated["state"] == lmr.STATE_ESCALATED
    assert escalated["escalatedReason"] == "review_timeout_retries_exhausted"
    assert escalated["retryCount"] == 2  # 重试 ≤2，仍失败
    assert escalated["reviews"] == []
    assert not (repo / ".worktrees" / f"lmr-review-{record['id']}").exists()
    timeouts = [line for line in watcher.log.lines() if '"timeout"' in line]
    assert len(timeouts) == 3  # 1 次初始 + 2 次重试


def test_watcher_restart_recovers_queue_from_ledger(git_repo):
    repo, git = git_repo
    record = _register(repo, _commit(repo, git, "resume\n"))

    first = _make_watcher(repo)
    assert first.poll() == [record["id"]]

    # 模拟重启：全新 watcher 实例（空队列）从 ledger 恢复
    second = _make_watcher(repo, cmd=_verdict_cmd("approve"))
    assert second.poll() == [record["id"]]
    assert second.run_once() == "reviewed"
    ledger = lmr.Ledger(lmr.ledger_dir_for(repo))
    assert ledger.get(record["id"])["state"] == lmr.STATE_APPROVED
