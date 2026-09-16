#!/usr/bin/env python3
"""LMR（Local Merge Request）台账 CLI。

设计权威：docs/agents/pr-integration-workflow.md §12-14。

- 存储：``<git-common-dir>/lmr/``（worktree 共享 common dir）；一条记录一个文件
  ``lmr-<id>.json``，id = ``<branchslug>-<sha8>``。
- 写入语义（§14.2.1）：temp + ``os.replace`` 原子替换（OSError 有界重试并包装为
  ``LedgerError``）；**全部**台账变更（register/transition/append_review/
  set_retry_count/supersede）都串行在同一把 per-branch 跨进程 OS 文件锁之后
  （复用 ``core/infrastructure/file_lock.py``：字节范围 OS 锁随进程死亡自动
  释放，等待有界超时报错），锁内重读并校验状态再写；无全局长锁，登记永不
  互相阻塞，Windows 下并发 os.replace 不再产生 PermissionError。
- 状态机：pending_review → in_review →（rework → pending_review）* →
  approved → merging → merged / rejected / escalated / review_timeout。
  ``superseded`` 为登记器内部状态：同 branch 新 SHA 顶替旧记录并作废旧 reviews。

子命令：register / list / show / transition / invalidate / status。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path

# scripts -> core 复用（先例：no_console_git）；台账变更锁用跨进程 OS 文件锁。
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.infrastructure.file_lock import cross_process_file_lock

LEDGER_DIRNAME = "lmr"
LOCKS_DIRNAME = "locks"
RECORD_GLOB = "lmr-*.json"
RECORD_PREFIX = "lmr-"
RECORD_SUFFIX = ".json"
BRANCH_LOCK_PREFIX = "branch-"

GRADES = ("show", "ask")
PUBLISH_NA = "na"
PUBLISH_PENDING = "pending_publish"
PUBLISH_PUBLISHED = "published"
PUBLISH_STATES = (PUBLISH_NA, PUBLISH_PENDING, PUBLISH_PUBLISHED)

STATE_PENDING_REVIEW = "pending_review"
STATE_IN_REVIEW = "in_review"
STATE_REWORK = "rework"
STATE_APPROVED = "approved"
STATE_MERGING = "merging"
STATE_MERGED = "merged"
STATE_REJECTED = "rejected"
STATE_ESCALATED = "escalated"
STATE_REVIEW_TIMEOUT = "review_timeout"
STATE_SUPERSEDED = "superseded"

ACTIVE_STATES = frozenset(
    {
        STATE_PENDING_REVIEW,
        STATE_IN_REVIEW,
        STATE_REWORK,
        STATE_APPROVED,
        STATE_MERGING,
        STATE_REVIEW_TIMEOUT,
    }
)
TERMINAL_STATES = frozenset({STATE_MERGED, STATE_REJECTED, STATE_SUPERSEDED})

# §13.1 状态机 + watcher 重试路径（review_timeout -> in_review）+ 升级恢复。
TRANSITIONS: dict[str, frozenset[str]] = {
    STATE_PENDING_REVIEW: frozenset({STATE_IN_REVIEW, STATE_ESCALATED}),
    # in_review → pending_review：watcher 孤儿恢复（崩溃后无人驱动的记录重入队）。
    STATE_IN_REVIEW: frozenset(
        {
            STATE_PENDING_REVIEW,
            STATE_REWORK,
            STATE_APPROVED,
            STATE_REJECTED,
            STATE_REVIEW_TIMEOUT,
            STATE_ESCALATED,
        }
    ),
    STATE_REWORK: frozenset({STATE_PENDING_REVIEW, STATE_ESCALATED}),
    STATE_REVIEW_TIMEOUT: frozenset(
        {STATE_IN_REVIEW, STATE_PENDING_REVIEW, STATE_ESCALATED}
    ),
    STATE_APPROVED: frozenset({STATE_MERGING, STATE_REJECTED, STATE_ESCALATED}),
    STATE_MERGING: frozenset({STATE_MERGED, STATE_ESCALATED}),
    STATE_MERGED: frozenset(),
    STATE_REJECTED: frozenset(),
    STATE_ESCALATED: frozenset({STATE_PENDING_REVIEW}),
    STATE_SUPERSEDED: frozenset(),
}

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SHA_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class LedgerError(RuntimeError):
    """台账操作失败（IO、状态机、参数校验、git 调用）。"""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime(TS_FORMAT)


def parse_ts(value: object) -> float | None:
    """ISO 时间戳 -> epoch 秒；解析失败返回 None。"""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def run_git(
    arguments: Sequence[str], *, cwd: Path | str | None = None, timeout: float = 60.0
) -> str:
    """执行 git 命令并返回 stdout；失败抛 LedgerError。

    Windows 上带 CREATE_NO_WINDOW，遵守仓库无控制台红线（§8.0）。
    """
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LedgerError(f"git_failed:{arguments[0]}:{exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[:200]
        raise LedgerError(f"git_failed:{arguments[0]}:{detail}")
    return completed.stdout


def git_common_dir(root: Path | str | None = None) -> Path:
    """解析 git common dir（worktree 共享），ledger 存放地。"""
    cwd = Path(root) if root is not None else Path.cwd()
    out = run_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=cwd)
    return Path(out.strip())


def ledger_dir_for(root: Path | str | None = None) -> Path:
    return git_common_dir(root) / LEDGER_DIRNAME


def locks_dir_for(root: Path | str | None = None) -> Path:
    return ledger_dir_for(root) / LOCKS_DIRNAME


def main_worktree_root(root: Path | str | None = None) -> Path:
    """主 checkout 根（worktree list 首项）；失败退回 common dir 父目录。"""
    cwd = Path(root) if root is not None else Path.cwd()
    try:
        out = run_git(["worktree", "list", "--porcelain"], cwd=cwd, timeout=30.0)
    except LedgerError:
        return git_common_dir(cwd).parent
    for line in out.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree ") :].strip())
    return git_common_dir(cwd).parent


def branch_slug(branch: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", branch.strip()).strip("-.")
    return slug or "branch"


def validate_sha(sha: str) -> str:
    normalized = sha.strip().lower()
    if not SHA_PATTERN.match(normalized):
        raise LedgerError(f"invalid_sha:{sha}")
    return normalized


def make_record_id(branch: str, sha: str) -> str:
    return f"{branch_slug(branch)}-{sha[:8]}"


def atomic_write_json(path: Path, payload: dict) -> None:
    """temp + os.replace 原子写（§14.2.1），LF 行尾。

    Windows 下与并发读者/写者竞争时 os.replace 可能瞬态 OSError
    （PermissionError），有界重试收敛；最终失败包装为 LedgerError，
    CLI 干净报错不裸栈。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    last_exc: OSError | None = None
    for attempt in range(5):
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
            return
        except OSError as exc:
            last_exc = exc
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            time.sleep(0.01 * (attempt + 1))
    raise LedgerError(f"atomic_write_failed:{path.name}:{last_exc}")


def _read_payload(path: Path) -> object:
    """读取记录 JSON；对并发 os.replace 的瞬态共享冲突做有界重试。"""
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise LedgerError(f"record_not_found:{path.stem}") from exc
        except (OSError, ValueError) as exc:
            last_exc = exc
            time.sleep(0.005 * (attempt + 1))
    raise LedgerError(f"record_unreadable:{path.name}:{last_exc}")


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def _new_record(
    branch: str,
    sha: str,
    base: str,
    title: str,
    grade: str,
    evidence: str,
    now: str,
) -> dict:
    return {
        "id": make_record_id(branch, sha),
        "branch": branch,
        "sha": sha,
        "base": base,
        "title": title,
        "grade": grade,
        "evidence": evidence,
        "state": STATE_PENDING_REVIEW,
        "created": now,
        "updated": now,
        "reviews": [],
        "publishState": PUBLISH_NA,
        "escalatedReason": None,
        "retryCount": 0,
    }


class Ledger:
    """LMR 台账：一记录一文件 + per-branch 短临界锁。"""

    def __init__(self, directory: Path | str | None = None) -> None:
        self.directory = Path(directory) if directory is not None else ledger_dir_for(None)

    # -- 基础读写 -----------------------------------------------------------

    @property
    def locks_dir(self) -> Path:
        return self.directory / LOCKS_DIRNAME

    def _path_for(self, record_id: str) -> Path:
        return self.directory / f"{RECORD_PREFIX}{record_id}{RECORD_SUFFIX}"

    def list_records(self) -> list[dict]:
        records: list[dict] = []
        if not self.directory.exists():
            return records
        for path in sorted(self.directory.glob(RECORD_GLOB)):
            try:
                payload = _read_payload(path)
            except LedgerError:
                continue
            if isinstance(payload, dict) and payload.get("id"):
                records.append(payload)
        records.sort(key=lambda rec: (str(rec.get("created") or ""), str(rec.get("id"))))
        return records

    def get(self, record_id: str) -> dict:
        payload = _read_payload(self._path_for(record_id))
        if not isinstance(payload, dict) or not payload.get("id"):
            raise LedgerError(f"record_unreadable:{record_id}")
        return payload

    def save(self, record: dict) -> None:
        atomic_write_json(self._path_for(str(record["id"])), record)

    # -- per-branch 跨进程锁 ---------------------------------------------------

    @contextlib.contextmanager
    def branch_lock(self, branch: str, *, timeout: float = 15.0) -> Iterator[None]:
        """同分支读改写串行：复用 core 跨进程 OS 文件锁（§14.2.1）。

        字节范围 OS 锁随持有进程死亡自动释放，无陈旧接管需求；等待有界，
        超时包装为 LedgerError（§14.1 一切等待有界、可见）。
        """
        branch = branch.strip()
        if not branch:
            raise LedgerError("invalid_branch:empty")
        self.locks_dir.mkdir(parents=True, exist_ok=True)
        sidecar = self.locks_dir / f"{BRANCH_LOCK_PREFIX}{branch_slug(branch)}.lock"
        try:
            with cross_process_file_lock(self.directory, lock_path=sidecar, timeout=timeout):
                yield
        except TimeoutError as exc:
            raise LedgerError(f"branch_lock_timeout:{branch}") from exc

    # -- 生命周期操作 --------------------------------------------------------

    def register(
        self,
        *,
        branch: str,
        sha: str,
        base: str = "main",
        title: str = "",
        grade: str = "show",
        evidence: str = "",
    ) -> tuple[dict, str]:
        """登记 LMR；同 branch 新 SHA 顶替旧记录并作废旧 reviews（§13.2）。

        返回 (record, action)，action ∈ {created, refreshed}。
        """
        if grade not in GRADES:
            raise LedgerError(f"invalid_grade:{grade}")
        sha = validate_sha(sha)
        branch = branch.strip()
        if not branch:
            raise LedgerError("invalid_branch:empty")
        now = utcnow()
        with self.branch_lock(branch):
            record_id = make_record_id(branch, sha)
            existing = self._read_optional(record_id)
            if existing is not None and existing.get("state") != STATE_SUPERSEDED:
                existing.update(
                    base=base, title=title, grade=grade, evidence=evidence, updated=now
                )
                self.save(existing)
                return existing, "refreshed"
            for record in self.list_records():
                if (
                    record.get("branch") == branch
                    and record.get("id") != record_id
                    and record.get("state") != STATE_SUPERSEDED
                ):
                    self._supersede(record, record_id, now)
            record = _new_record(branch, sha, base, title, grade, evidence, now)
            self.save(record)
            return record, "created"

    def invalidate(self, branch: str, new_sha: str) -> tuple[str, bool]:
        """按 branch + 新 SHA 作废当前记录的 reviews（顶替准备），不建新记录。"""
        sha = validate_sha(new_sha)
        branch = branch.strip()
        now = utcnow()
        new_id = make_record_id(branch, sha)
        changed = False
        with self.branch_lock(branch):
            for record in self.list_records():
                if (
                    record.get("branch") == branch
                    and record.get("id") != new_id
                    and record.get("state") != STATE_SUPERSEDED
                ):
                    self._supersede(record, new_id, now)
                    changed = True
        return new_id, changed

    def transition(
        self, record_id: str, to_state: str, *, reason: str | None = None
    ) -> dict:
        branch = str(self.get(record_id).get("branch") or "")
        with self.branch_lock(branch):
            record = self.get(record_id)  # 锁内重读，防并发顶替/流转竞态
            from_state = str(record.get("state"))
            allowed = TRANSITIONS.get(from_state, frozenset())
            if to_state not in allowed:
                raise LedgerError(f"invalid_transition:{from_state}->{to_state}")
            record["state"] = to_state
            record["updated"] = utcnow()
            if to_state == STATE_ESCALATED:
                record["escalatedReason"] = reason or "unspecified"
            elif from_state == STATE_ESCALATED:
                record["escalatedReason"] = None
            if to_state == STATE_MERGED:
                record["publishState"] = PUBLISH_PENDING
            if to_state == STATE_PENDING_REVIEW:
                record["retryCount"] = 0
            self.save(record)
            return record

    def append_review(self, record_id: str, review: dict) -> dict:
        branch = str(self.get(record_id).get("branch") or "")
        with self.branch_lock(branch):
            record = self.get(record_id)  # 锁内重读
            record.setdefault("reviews", []).append(review)
            record["updated"] = utcnow()
            self.save(record)
            return record

    def set_retry_count(self, record_id: str, count: int) -> dict:
        branch = str(self.get(record_id).get("branch") or "")
        with self.branch_lock(branch):
            record = self.get(record_id)  # 锁内重读
            record["retryCount"] = int(count)
            record["updated"] = utcnow()
            self.save(record)
            return record

    # -- 内部 ---------------------------------------------------------------

    def _read_optional(self, record_id: str) -> dict | None:
        try:
            return self.get(record_id)
        except LedgerError:
            return None

    def _supersede(self, record: dict, superseded_by: str, now: str) -> None:
        record["state"] = STATE_SUPERSEDED
        record["reviews"] = []
        record["escalatedReason"] = None
        record["supersededBy"] = superseded_by
        record["updated"] = now
        self.save(record)


# ---------------------------------------------------------------------------
# 展示格式化
# ---------------------------------------------------------------------------


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _age(ts_value: object, now: datetime) -> float:
    start = parse_ts(ts_value)
    if start is None:
        return 0.0
    return max(0.0, now.timestamp() - start)


def format_record_line(record: dict) -> str:
    return (
        f"{record.get('id')}\t{record.get('state')}\t{record.get('grade')}"
        f"\t{record.get('branch')}\t{str(record.get('sha'))[:8]}"
        f"\t{record.get('updated')}"
    )


def format_status(
    records: Sequence[dict],
    *,
    now: datetime | None = None,
    ledger_label: str = "",
) -> str:
    """§14.2.6：一屏看全队列——各状态计数 + escalated/pending_publish 明细 + 等待时长。"""
    current = now or datetime.now(timezone.utc)
    counts: dict[str, int] = {state: 0 for state in TRANSITIONS}
    for record in records:
        state = str(record.get("state") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    counts_text = " ".join(f"{state}={counts[state]}" for state in counts)
    header = f"LMR status: {len(records)} records"
    if ledger_label:
        header += f" (ledger={ledger_label})"
    lines = [header, f"counts: {counts_text}"]

    escalated = [r for r in records if r.get("state") == STATE_ESCALATED]
    lines.append(f"escalated ({len(escalated)}):")
    for record in escalated:
        reason = record.get("escalatedReason") or "unspecified"
        waiting = format_duration(_age(record.get("updated"), current))
        lines.append(f"  - {record.get('id')} reason={reason} waiting={waiting}")

    publishing = [
        r
        for r in records
        if r.get("publishState") == PUBLISH_PENDING and r.get("state") == STATE_MERGED
    ]
    lines.append(f"pending_publish ({len(publishing)}):")
    for record in publishing:
        lines.append(
            f"  - {record.get('id')} branch={record.get('branch')}"
            f" sha={str(record.get('sha'))[:8]}"
        )

    waiting = [
        r for r in records if r.get("state") in (STATE_PENDING_REVIEW, STATE_IN_REVIEW)
    ]
    lines.append(f"waiting ({len(waiting)}):")
    for record in waiting:
        is_pending = record.get("state") == STATE_PENDING_REVIEW
        base_ts = record.get("created") if is_pending else record.get("updated")
        lines.append(
            f"  - {record.get('id')} state={record.get('state')}"
            f" wait={format_duration(_age(base_ts, current))}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _emit(text: str) -> None:
    stream = sys.stdout
    if stream is not None:  # pythonw 下 stdout 为 None，静默降级
        stream.write(text + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lmr", description="LMR ledger CLI (docs/agents/pr-integration-workflow.md §12-14)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register", help="登记一条 LMR")
    register.add_argument("--branch", required=True)
    register.add_argument("--sha", required=True)
    register.add_argument("--base", default="main")
    register.add_argument("--title", default="")
    register.add_argument("--grade", choices=GRADES, required=True)
    register.add_argument("--evidence", default="")

    sub.add_parser("list", help="列出全部记录（每行一条）")

    show = sub.add_parser("show", help="查看单条记录 JSON")
    show.add_argument("record_id")

    transition = sub.add_parser("transition", help="状态流转")
    transition.add_argument("record_id")
    transition.add_argument("--to", required=True, choices=sorted(TRANSITIONS))
    transition.add_argument("--reason", default=None)

    invalidate = sub.add_parser("invalidate", help="按 branch + 新 SHA 作废旧 reviews")
    invalidate.add_argument("--branch", required=True)
    invalidate.add_argument("--new-sha", required=True)

    sub.add_parser("status", help="一屏汇总：状态计数 + escalated/pending_publish 明细")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "register":
            ledger = Ledger()
            record, action = ledger.register(
                branch=args.branch,
                sha=args.sha,
                base=args.base,
                title=args.title,
                grade=args.grade,
                evidence=args.evidence,
            )
            _emit(f"registered {record['id']} action={action} state={record['state']}")
        elif args.command == "list":
            ledger = Ledger()
            for record in ledger.list_records():
                _emit(format_record_line(record))
        elif args.command == "show":
            _emit(json.dumps(Ledger().get(args.record_id), ensure_ascii=False, indent=2))
        elif args.command == "transition":
            record = Ledger().transition(args.record_id, args.to, reason=args.reason)
            _emit(f"transitioned {record['id']} -> {record['state']}")
        elif args.command == "invalidate":
            ledger = Ledger()
            new_id, changed = ledger.invalidate(args.branch, args.new_sha)
            _emit(f"invalidate {new_id} superseded={changed}")
        elif args.command == "status":
            ledger = Ledger()
            _emit(format_status(ledger.list_records(), ledger_label=str(ledger.directory)))
    except LedgerError as exc:
        stream = sys.stderr
        if stream is not None:
            stream.write(f"lmr: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
