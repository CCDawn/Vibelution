#!/usr/bin/env python3
"""LMR ledger 并发原子性、同分支顶替、状态机与 status 输出测试。

对应 docs/agents/pr-integration-workflow.md §12-14（LMR 台账）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import lmr

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


def _ledger(repo: Path) -> lmr.Ledger:
    return lmr.Ledger(lmr.ledger_dir_for(repo))


def _register(ledger: lmr.Ledger, branch: str, sha: str, **overrides) -> tuple[dict, str]:
    kwargs: dict = {
        "base": "main",
        "title": f"title-{sha[:8]}",
        "grade": "show",
        "evidence": "manifest.json",
    }
    kwargs.update(overrides)
    return ledger.register(branch=branch, sha=sha, **kwargs)


def test_register_concurrent_same_branch_atomic(git_repo):
    repo, git = git_repo
    ledger = _ledger(repo)
    first, _ = _register(ledger, "codex/demo", _commit(repo, git, "base\n"))
    first["reviews"].append(
        {"verdict": "approve", "findings": [], "evidence_section": "stale", "sha": first["sha"]}
    )
    ledger.save(first)

    shas = [_commit(repo, git, f"sha-{index}\n") for index in range(6)]
    barrier = __import__("threading").Barrier(len(shas))

    def worker(sha: str):
        barrier.wait()
        return _register(ledger, "codex/demo", sha, grade="ask")

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(shas)) as pool:
        futures = [pool.submit(worker, sha) for sha in shas]
        registered = [future.result() for future in futures]

    records = ledger.list_records()
    active = [r for r in records if r["state"] != lmr.STATE_SUPERSEDED]
    assert len(active) == 1, [r["state"] for r in records]
    winner = active[0]
    assert winner["sha"] in shas
    assert len(records) == 1 + len(shas)
    superseded = [r for r in records if r["state"] == lmr.STATE_SUPERSEDED]
    assert len(superseded) == len(shas)
    by_id = {r["id"]: r for r in records}
    for record in superseded:
        assert record["reviews"] == []
        # supersededBy 是顶替链指针：链式追溯必须终止于唯一 winner
        current, hops = record, 0
        while current.get("state") == lmr.STATE_SUPERSEDED:
            next_id = current.get("supersededBy")
            assert next_id and hops < 20, f"broken-chain:{record['id']}"
            current = by_id[str(next_id)]
            hops += 1
        assert current["id"] == winner["id"]
    assert winner["reviews"] == []
    assert winner["grade"] == "ask"
    assert winner["id"] in {record["id"] for record, _ in registered}


def test_register_new_sha_supersedes_and_invalidates_reviews(git_repo):
    repo, git = git_repo
    ledger = _ledger(repo)
    old, action = _register(ledger, "codex/demo", _commit(repo, git, "old\n"))
    assert action == "created"
    ledger.transition(old["id"], lmr.STATE_IN_REVIEW)
    ledger.append_review(
        old["id"],
        {
            "verdict": "approve",
            "findings": [{"file": "a.py", "severity": "nit"}],
            "evidence_section": "old-evidence",
            "sha": old["sha"],
            "ts": lmr.utcnow(),
        },
    )

    new_sha = _commit(repo, git, "new\n")
    record, action = _register(ledger, "codex/demo", new_sha)

    assert action == "created"
    assert record["id"] == lmr.make_record_id("codex/demo", new_sha)
    assert record["state"] == lmr.STATE_PENDING_REVIEW
    assert record["reviews"] == []
    assert record["publishState"] == lmr.PUBLISH_NA
    assert record["retryCount"] == 0

    superseded = ledger.get(old["id"])
    assert superseded["state"] == lmr.STATE_SUPERSEDED
    assert superseded["reviews"] == []
    assert superseded["supersededBy"] == record["id"]

    # 同 SHA 重复登记是幂等刷新，不重置状态
    refreshed, action = _register(ledger, "codex/demo", new_sha, title="updated")
    assert action == "refreshed"
    assert refreshed["state"] == lmr.STATE_PENDING_REVIEW
    assert refreshed["title"] == "updated"


def test_transition_state_machine_and_publish_state(git_repo):
    repo, git = git_repo
    ledger = _ledger(repo)
    record, _ = _register(ledger, "codex/flow", _commit(repo, git, "flow\n"))

    with pytest.raises(lmr.LedgerError):
        ledger.transition(record["id"], lmr.STATE_MERGED)

    ledger.transition(record["id"], lmr.STATE_IN_REVIEW)
    ledger.transition(record["id"], lmr.STATE_APPROVED)
    ledger.transition(record["id"], lmr.STATE_MERGING)
    merged = ledger.transition(record["id"], lmr.STATE_MERGED)
    assert merged["publishState"] == lmr.PUBLISH_PENDING

    # escalated 带 reason，恢复时清除
    record2, _ = _register(ledger, "codex/flow2", _commit(repo, git, "flow2\n"))
    escalated = ledger.transition(record2["id"], lmr.STATE_ESCALATED, reason="blocked")
    assert escalated["escalatedReason"] == "blocked"
    resumed = ledger.transition(record2["id"], lmr.STATE_PENDING_REVIEW)
    assert resumed["escalatedReason"] is None
    assert resumed["retryCount"] == 0


def test_invalidate_without_register(git_repo):
    repo, git = git_repo
    ledger = _ledger(repo)
    record, _ = _register(ledger, "codex/inv", _commit(repo, git, "inv\n"))
    ledger.transition(record["id"], lmr.STATE_IN_REVIEW)
    ledger.append_review(
        record["id"],
        {"verdict": "comment", "findings": [], "evidence_section": "", "sha": record["sha"]},
    )

    new_sha = _commit(repo, git, "inv2\n")
    new_id, changed = ledger.invalidate("codex/inv", new_sha)
    assert changed is True
    assert new_id == lmr.make_record_id("codex/inv", new_sha)
    assert ledger.get(record["id"])["reviews"] == []
    assert ledger.get(record["id"])["state"] == lmr.STATE_SUPERSEDED
    # invalidate 本身不建新记录
    assert all(r["id"] != new_id for r in ledger.list_records())

    _, changed_again = ledger.invalidate("codex/inv", new_sha)
    assert changed_again is False


def test_status_output(git_repo):
    repo, git = git_repo
    ledger = _ledger(repo)
    pending, _ = _register(ledger, "codex/st-pending", _commit(repo, git, "p\n"))
    escalated, _ = _register(ledger, "codex/st-esc", _commit(repo, git, "e\n"))
    ledger.transition(escalated["id"], lmr.STATE_IN_REVIEW)
    ledger.transition(escalated["id"], lmr.STATE_ESCALATED, reason="reviewer_executor_unconfigured")
    merged, _ = _register(ledger, "codex/st-merged", _commit(repo, git, "m\n"))
    ledger.transition(merged["id"], lmr.STATE_IN_REVIEW)
    ledger.transition(merged["id"], lmr.STATE_APPROVED)
    ledger.transition(merged["id"], lmr.STATE_MERGING)
    ledger.transition(merged["id"], lmr.STATE_MERGED)

    text = lmr.format_status(ledger.list_records())

    assert (
        "counts: pending_review=1 in_review=0 rework=0 review_timeout=0 approved=0"
        " merging=0 merged=1 rejected=0 escalated=1 superseded=0" in text
    )
    assert "reason=reviewer_executor_unconfigured" in text
    assert escalated["id"] in text
    assert "pending_publish (1):" in text
    assert merged["id"] in text
    assert "waiting (1):" in text
    assert f"{pending['id']} state=pending_review" in text
    assert "wait=" in text


def test_register_rejects_bad_input(git_repo):
    repo, _ = git_repo
    ledger = _ledger(repo)
    with pytest.raises(lmr.LedgerError):
        _register(ledger, "codex/bad", "zzzz-not-a-sha")
    with pytest.raises(lmr.LedgerError):
        _register(ledger, "codex/bad", "abcdef123456", grade="ultra")


def test_transition_register_concurrent_amplified(git_repo):
    """回归：register × transition/append/retry 并发放大，无失败无裸异常。

    台账全部变更串行在同一把 per-branch 跨进程锁后（含锁内重读），
    Windows 下不再出现 os.replace PermissionError 或 register 失败。
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    repo, git = git_repo
    ledger = _ledger(repo)
    shas = [_commit(repo, git, f"amp-{index}\n") for index in range(20)]
    errors: list[Exception] = []
    start = threading.Barrier(3)

    def registrar() -> None:
        start.wait()
        for sha in shas:
            try:
                ledger.register(
                    branch="codex/amp", sha=sha, base="main", title="amp", grade="show"
                )
            except Exception as exc:  # noqa: BLE001 - 回归测试收集一切异常
                errors.append(exc)

    def churner() -> None:
        start.wait()
        for _ in range(300):
            actives = [
                r
                for r in ledger.list_records()
                if r.get("branch") == "codex/amp"
                and r.get("state") == lmr.STATE_PENDING_REVIEW
            ]
            if not actives:
                continue
            target = actives[0]
            try:
                ledger.transition(target["id"], lmr.STATE_IN_REVIEW)
            except lmr.LedgerError as exc:
                # 并发顶替后目标记录已 superseded：合法竞争结果，不算失败
                if "invalid_transition" not in str(exc):
                    errors.append(exc)
                continue
            try:
                ledger.append_review(
                    target["id"],
                    {
                        "verdict": "comment",
                        "findings": [],
                        "evidence_section": "amp",
                        "sha": target["sha"],
                    },
                )
                ledger.set_retry_count(target["id"], 1)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(registrar), pool.submit(churner), pool.submit(churner)]
        for future in futures:
            future.result()

    assert errors == []
    records = ledger.list_records()
    active = [
        r
        for r in records
        if r.get("branch") == "codex/amp" and r.get("state") != lmr.STATE_SUPERSEDED
    ]
    assert len(active) == 1


def test_atomic_write_wraps_oserror(git_repo, monkeypatch):
    repo, _ = git_repo
    target = lmr.ledger_dir_for(repo) / "boom.json"

    def always_denied(src, dst, **_kwargs):
        raise PermissionError(5, "denied")

    monkeypatch.setattr(lmr.os, "replace", always_denied)
    with pytest.raises(lmr.LedgerError, match="atomic_write_failed"):
        lmr.atomic_write_json(target, {"a": 1})


def test_read_transient_corruption_retries(git_repo, monkeypatch):
    """回归：读者对并发 os.replace 的瞬态共享冲突有界重试后成功。"""
    repo, git = git_repo
    ledger = _ledger(repo)
    record, _ = _register(ledger, "codex/retry", _commit(repo, git, "retry\n"))
    real_read_text = Path.read_text
    flaky = {"count": 0}

    def flaky_read_text(self, *args, **kwargs):
        if self.suffix == ".json" and flaky["count"] < 2:
            flaky["count"] += 1
            raise PermissionError(5, "transient sharing violation")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    assert ledger.get(record["id"])["id"] == record["id"]
    assert flaky["count"] == 2
