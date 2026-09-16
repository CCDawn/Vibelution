#!/usr/bin/env python3
"""LMR 审查 watcher：单飞锁 + FIFO/aging 串行审查队列 + 可插拔 reviewer 执行器。

设计权威：docs/agents/pr-integration-workflow.md §12.2 / §13 / §14.2。

- 轮询 ledger（默认 10s，env 可配）发现 pending_review 即入内存队列；
  队列可从 ledger 完整恢复（重启安全）。
- 单飞锁（§14.2.2）：``<common-dir>/lmr/locks/review.lock``（PID + 心跳，
  默认 30s 刷新）；后来者发现心跳 >90s（或 PID 已死）判死安全接管。
- FIFO + aging：等待每超 15min 优先级 +1，防长审查连续压队饿死后续。
- 孤儿恢复：扫描发现 in_review/review_timeout 且无存活 review 标记（进程崩溃
  残留）→ 转回 pending_review 重入队，任何记录不会停在无人驱动的状态。
- 单任务审查超时（默认 30min）→ review_timeout，重试 ≤2（指数退避），
  仍失败 → escalated；执行器未配置 → escalated（reason=reviewer_executor_unconfigured，
  §14.4 显式降级，不静默）。
- 执行：为每个任务建临时 worktree ``.worktrees/lmr-review-<id>`` 检出到 LMR SHA，
  调用 ``VIBELUTION_LMR_REVIEWER_CMD``（命令模板，占位符 ``{review_worktree}``
  ``{lmr_json}`` ``{verdict_path}``；模板需给含空格的路径加双引号），执行器向
  verdict_path 写 JSON verdict；审查完清理临时 worktree。
- 全程结构化日志每步一行（enqueued/started/verdict/completed/failed/timeout/
  lock-takeover），写文件不写控制台；进程可用 pythonw 无控制台常驻。
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

try:  # 作为脚本运行时 scripts/ 已在 sys.path；被导入时兜底注入。
    import lmr
except ImportError:  # pragma: no cover - 仅异常 sys.path 下触发
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import lmr

REVIEWER_CMD_ENV = "VIBELUTION_LMR_REVIEWER_CMD"
VERDICTS = ("approve", "rework", "comment")
WORKTREE_PREFIX = "lmr-review-"

CREATE_NO_WINDOW = lmr.CREATE_NO_WINDOW


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass
class WatcherConfig:
    poll_interval: float = 10.0
    review_timeout: float = 1800.0
    max_retries: int = 2
    retry_backoff: float = 30.0
    heartbeat_interval: float = 30.0
    lock_stale_after: float = 90.0
    lock_acquire_timeout: float = 5.0
    aging_interval: float = 900.0
    git_timeout: float = 120.0


_ENV_KEYS = {
    "poll_interval": ("VIBELUTION_LMR_POLL_INTERVAL", 10.0),
    "review_timeout": ("VIBELUTION_LMR_REVIEW_TIMEOUT", 1800.0),
    "heartbeat_interval": ("VIBELUTION_LMR_HEARTBEAT_INTERVAL", 30.0),
    "lock_stale_after": ("VIBELUTION_LMR_LOCK_STALE_AFTER", 90.0),
    "aging_interval": ("VIBELUTION_LMR_AGING_INTERVAL", 900.0),
    "retry_backoff": ("VIBELUTION_LMR_RETRY_BACKOFF", 30.0),
}


def _env_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def load_config_from_env(env: Mapping[str, str] | None = None) -> WatcherConfig:
    source = os.environ if env is None else env
    config = WatcherConfig()
    for attr, (key, default) in _ENV_KEYS.items():
        setattr(config, attr, _env_float(source, key, default))
    raw_retries = source.get("VIBELUTION_LMR_MAX_RETRIES")
    if raw_retries is not None:
        with contextlib.suppress(TypeError, ValueError):
            config.max_retries = max(0, int(raw_retries))
    return config


# ---------------------------------------------------------------------------
# 结构化日志（每步一行 JSON；写文件，无控制台输出，pythonw 安全）
# ---------------------------------------------------------------------------


class EventLog:
    def __init__(self, path: Path | str | None = None, *, max_bytes: int = 5_000_000) -> None:
        self.path = Path(path) if path is not None else None
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        if self.path is not None:
            with contextlib.suppress(OSError):
                self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, **fields: object) -> None:
        if self.path is None:
            return
        payload: dict[str, object] = {"ts": lmr.utcnow(), "event": event}
        payload.update(fields)
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with self._lock:
            try:
                if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                    self.path.replace(self.path.with_name(self.path.name + ".1"))
                with open(self.path, "a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line + "\n")
            except OSError:
                pass  # 日志失败不拖垮 watcher

    def lines(self) -> list[str]:
        if self.path is None:
            return []
        try:
            return self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []


# ---------------------------------------------------------------------------
# 跨进程辅助
# ---------------------------------------------------------------------------


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(process_query_limited, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == still_active
            return False
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def split_command(template: str) -> list[str]:
    """按空白切分命令模板；双引号成组（引号本身剥除），反斜杠保持字面。

    不经 shell，避免 cmd/sh 引号歧义；Windows 路径可安全传递。
    """
    tokens: list[str] = []
    current: list[str] = []
    in_quotes = False
    for char in template:
        if char == '"':
            in_quotes = not in_quotes
        elif char in " \t" and not in_quotes:
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


# ---------------------------------------------------------------------------
# 单飞锁（§14.2.2）
# ---------------------------------------------------------------------------


class ReviewLock:
    """PID + 心跳锁文件；心跳 >stale_after 或 PID 已死时安全接管。"""

    def __init__(
        self,
        path: Path | str,
        *,
        heartbeat_interval: float = 30.0,
        stale_after: float = 90.0,
        log: EventLog | None = None,
    ) -> None:
        self.path = Path(path)
        self.heartbeat_interval = heartbeat_interval
        self.stale_after = stale_after
        self.log = log
        self._held = False
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    @property
    def held(self) -> bool:
        return self._held

    def _payload(self) -> dict:
        return {"pid": os.getpid(), "ts": lmr.utcnow()}

    def acquire(self, *, timeout: float = 5.0) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._try_takeover():
                    continue
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.05)
                continue
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self._payload(), handle)
            self._held = True
            self._start_heartbeat()
            return True

    def _try_takeover(self) -> bool:
        try:
            info = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        if not isinstance(info, dict):
            info = {}
        ts = lmr.parse_ts(info.get("ts"))
        pid = int(info.get("pid") or 0)
        now = time.time()
        stale_by_age = ts is None or (now - ts) > self.stale_after
        dead_pid = pid > 0 and not pid_alive(pid)
        if not (stale_by_age or dead_pid):
            return False
        if self.log is not None:
            self.log.emit(
                "lock-takeover",
                stale_pid=pid,
                stale_age=round(now - ts, 1) if ts is not None else None,
                new_pid=os.getpid(),
            )
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            return False
        return True

    def _start_heartbeat(self) -> None:
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="lmr-lock-heartbeat", daemon=True
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(self.heartbeat_interval):
            with contextlib.suppress(OSError):
                self.refresh()

    def refresh(self) -> None:
        if not self._held:
            return
        tmp = self.path.with_name(self.path.name + ".hb")
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(self._payload(), handle)
        os.replace(tmp, self.path)

    def release(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=2.0)
            self._heartbeat_thread = None
        if self._held:
            with contextlib.suppress(OSError):
                self.path.unlink(missing_ok=True)
            self._held = False


# ---------------------------------------------------------------------------
# 队列：FIFO + aging
# ---------------------------------------------------------------------------


@dataclass
class QueueItem:
    lmr_id: str
    seq: int
    enqueued_at: float


class ReviewQueue:
    """FIFO 队列 + aging：等待每超 aging_interval 秒，有效优先级 +1。"""

    def __init__(self, *, aging_interval: float = 900.0) -> None:
        self.aging_interval = max(1.0, float(aging_interval))
        self._items: list[QueueItem] = []
        self._ids: set[str] = set()
        self._next_seq = 1
        self._lock = threading.Lock()

    def push(
        self, lmr_id: str, *, seq: int | None = None, enqueued_at: float | None = None
    ) -> bool:
        with self._lock:
            if lmr_id in self._ids:
                return False
            resolved_seq = self._next_seq if seq is None else int(seq)
            self._next_seq = max(self._next_seq, resolved_seq + 1)
            self._ids.add(lmr_id)
            self._items.append(
                QueueItem(
                    lmr_id=lmr_id,
                    seq=resolved_seq,
                    enqueued_at=time.monotonic() if enqueued_at is None else enqueued_at,
                )
            )
            return True

    def pop(self, *, now: float | None = None) -> QueueItem | None:
        with self._lock:
            if not self._items:
                return None
            current = time.monotonic() if now is None else now

            def rank(item: QueueItem) -> tuple[int, int]:
                waited = max(0.0, current - item.enqueued_at)
                return (item.seq - int(waited // self.aging_interval), item.seq)

            best = min(self._items, key=rank)
            self._items.remove(best)
            self._ids.discard(best.lmr_id)
            return best

    def ids(self) -> set[str]:
        with self._lock:
            return set(self._ids)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


# ---------------------------------------------------------------------------
# 可插拔 reviewer 执行器
# ---------------------------------------------------------------------------


class ExecutorError(RuntimeError):
    """执行器失败（非零退出、verdict 缺失或非法）。"""


class ExecutorTimeout(ExecutorError):
    """执行器超时。"""


def render_command(template: str, values: Mapping[str, object]) -> str:
    rendered = template
    for key, value in values.items():
        text = str(value).replace("\\", "/")
        rendered = rendered.replace("{" + key + "}", text)
    return rendered


class ReviewExecutor:
    """调用外部 reviewer 命令并读取 verdict JSON。"""

    def __init__(self, cmd_template: str, *, timeout: float) -> None:
        self.cmd_template = cmd_template
        self.timeout = timeout

    def run(self, *, review_worktree: Path, lmr_json: Path, verdict_path: Path) -> dict:
        rendered = render_command(
            self.cmd_template,
            {
                "review_worktree": review_worktree,
                "lmr_json": lmr_json,
                "verdict_path": verdict_path,
            },
        )
        tokens = split_command(rendered)
        if not tokens:
            raise ExecutorError("empty_command")
        try:
            completed = subprocess.run(
                tokens,
                cwd=str(review_worktree),
                timeout=self.timeout,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExecutorTimeout(f"reviewer_timeout:{self.timeout}s") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise ExecutorError(f"reviewer_spawn_failed:{exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[:200]
            raise ExecutorError(f"reviewer_exit_{completed.returncode}:{detail}")
        return self._read_verdict(verdict_path)

    @staticmethod
    def _read_verdict(verdict_path: Path) -> dict:
        try:
            raw = verdict_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ExecutorError("verdict_missing") from exc
        except OSError as exc:
            raise ExecutorError(f"verdict_unreadable:{exc}") from exc
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise ExecutorError("verdict_unparseable") from exc
        verdict = str(payload.get("verdict", "")).strip().lower()
        if verdict not in VERDICTS:
            raise ExecutorError(f"invalid_verdict:{verdict}")
        findings = payload.get("findings") or []
        if not isinstance(findings, list):
            findings = []
        return {
            "verdict": verdict,
            "findings": findings,
            "evidence_section": str(payload.get("evidence_section") or ""),
        }


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------


@dataclass
class LmrWatcher:
    root: Path
    config: WatcherConfig = field(default_factory=WatcherConfig)
    log: EventLog | None = None
    ledger: lmr.Ledger | None = None
    lock: ReviewLock | None = None
    queue: ReviewQueue | None = None
    executor: ReviewExecutor | None = None
    worktree_root: Path | None = None
    env: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        source_env = os.environ if self.env is None else self.env
        self.ledger = self.ledger or lmr.Ledger(lmr.ledger_dir_for(self.root))
        locks_dir = self.ledger.locks_dir
        self.lock = self.lock or ReviewLock(
            locks_dir / "review.lock",
            heartbeat_interval=self.config.heartbeat_interval,
            stale_after=self.config.lock_stale_after,
            log=self.log,
        )
        self.queue = self.queue or ReviewQueue(aging_interval=self.config.aging_interval)
        if self.executor is None:
            cmd = (source_env.get(REVIEWER_CMD_ENV) or "").strip()
            if cmd:
                self.executor = ReviewExecutor(cmd, timeout=self.config.review_timeout)
        if self.worktree_root is None:
            self.worktree_root = lmr.main_worktree_root(self.root) / ".worktrees"

    # -- 轮询 ---------------------------------------------------------------

    def poll(self) -> list[str]:
        """ledger -> 队列（按 created 排序；重复登记/已入队去重）。"""
        assert self.ledger is not None and self.queue is not None
        self._recover_orphans()
        pending = [
            r for r in self.ledger.list_records() if r.get("state") == lmr.STATE_PENDING_REVIEW
        ]
        pending.sort(key=lambda r: (str(r.get("created") or ""), str(r.get("id"))))
        enqueued: list[str] = []
        for record in pending:
            if self.queue.push(str(record["id"])):
                if self.log is not None:
                    self.log.emit(
                        "enqueued",
                        id=record.get("id"),
                        branch=record.get("branch"),
                        sha=record.get("sha"),
                    )
                enqueued.append(str(record["id"]))
        return enqueued

    def run_once(self) -> str:
        """单次循环：轮询 + 至多处理一个任务。返回结果标签。"""
        assert self.lock is not None and self.queue is not None
        self.poll()
        if len(self.queue) == 0:
            return "idle"
        if not self.lock.acquire(timeout=self.config.lock_acquire_timeout):
            if self.log is not None:
                self.log.emit("lock-busy")
            return "lock-busy"
        item = self.queue.pop()
        if item is None:
            self.lock.release()
            return "idle"
        try:
            return self._process(item)
        except Exception as exc:  # noqa: BLE001 - watcher 循环绝不因单任务崩溃
            if self.log is not None:
                self.log.emit("failed", id=item.lmr_id, error=f"unexpected:{exc}")
            return "error"
        finally:
            self.lock.release()

    def run_forever(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001 - 常驻进程兜底
                if self.log is not None:
                    self.log.emit("failed", error=f"loop:{exc}")
            time.sleep(self.config.poll_interval)

    # -- 孤儿恢复与 review 标记 ------------------------------------------------

    def _marker_path(self, lmr_id: str) -> Path:
        assert self.ledger is not None
        return self.ledger.locks_dir / f"reviewing-{lmr_id}.lock"

    def _marker_alive(self, lmr_id: str) -> bool:
        """标记存活 = 持有进程仍活着（处理可长达分钟级，不做心跳超时）。"""
        try:
            info = json.loads(self._marker_path(lmr_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        pid = int(info.get("pid") or 0) if isinstance(info, dict) else 0
        return pid > 0 and pid_alive(pid)

    def _acquire_review_marker(self, lmr_id: str) -> bool:
        """写 per-task 标记；死进程残留标记安全接管（与单飞锁同语义）。"""
        assert self.ledger is not None
        self.ledger.locks_dir.mkdir(parents=True, exist_ok=True)
        path = self._marker_path(lmr_id)
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    info = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    info = {}
                pid = int(info.get("pid") or 0) if isinstance(info, dict) else 0
                if pid > 0 and pid_alive(pid):
                    return False
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    return False
                continue
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"pid": os.getpid(), "ts": lmr.utcnow()}, handle)
            return True

    def _release_review_marker(self, lmr_id: str) -> None:
        with contextlib.suppress(OSError):
            self._marker_path(lmr_id).unlink(missing_ok=True)

    def _recover_orphans(self) -> list[str]:
        """崩溃恢复：无存活标记的 in_review/review_timeout 记录重置入队（§14.1）。

        任何记录不得停在无人驱动的中间态；并发下已被顶替/流转的记录交给下一轮。
        """
        assert self.ledger is not None
        recovered: list[str] = []
        for record in self.ledger.list_records():
            state = record.get("state")
            if state not in (lmr.STATE_IN_REVIEW, lmr.STATE_REVIEW_TIMEOUT):
                continue
            lmr_id = str(record["id"])
            if self._marker_alive(lmr_id):
                continue
            try:
                self.ledger.transition(lmr_id, lmr.STATE_PENDING_REVIEW)
            except lmr.LedgerError:
                continue
            if self.log is not None:
                self.log.emit("orphan-recovered", id=lmr_id, previous=state)
            recovered.append(lmr_id)
        return recovered

    # -- 单任务处理 ----------------------------------------------------------

    def _process(self, item: QueueItem) -> str:
        assert self.ledger is not None
        marker_held = False
        try:
            try:
                record = self.ledger.get(item.lmr_id)
            except lmr.LedgerError:
                if self.log is not None:
                    self.log.emit("skipped", id=item.lmr_id, reason="record-missing")
                return "missing"
            if record.get("state") != lmr.STATE_PENDING_REVIEW:
                if self.log is not None:
                    self.log.emit(
                        "skipped", id=item.lmr_id, reason=f"state:{record.get('state')}"
                    )
                return "skipped"
            if not self._acquire_review_marker(item.lmr_id):
                if self.log is not None:
                    self.log.emit(
                        "skipped", id=item.lmr_id, reason="review-in-progress-elsewhere"
                    )
                return "skipped"
            marker_held = True
            self.ledger.transition(item.lmr_id, lmr.STATE_IN_REVIEW)
            if self.log is not None:
                self.log.emit("started", id=item.lmr_id, sha=record.get("sha"))
            if self.executor is None:
                # §14.4：reviewer 执行器未配置 → 显式 escalated，不静默。
                self.ledger.transition(
                    item.lmr_id, lmr.STATE_ESCALATED, reason="reviewer_executor_unconfigured"
                )
                if self.log is not None:
                    self.log.emit(
                        "failed", id=item.lmr_id, reason="reviewer_executor_unconfigured"
                    )
                return "escalated"
            return self._run_review(item.lmr_id, record)
        finally:
            if marker_held:
                self._release_review_marker(item.lmr_id)

    def _run_review(self, lmr_id: str, record: dict) -> str:
        """执行审查（含超时重试升级）；调用方持有 review 标记。"""
        assert self.executor is not None and self.ledger is not None
        worktree: Path | None = None
        snapshot: Path | None = None
        verdict_path: Path | None = None
        try:
            worktree = self._create_worktree(record)
            snapshot = self._write_snapshot(record)
            verdict_path = _temp_json_path("lmr-verdict")
            attempts = max(1, self.config.max_retries + 1)
            for attempt in range(1, attempts + 1):
                try:
                    verdict = self.executor.run(
                        review_worktree=worktree,
                        lmr_json=snapshot,
                        verdict_path=verdict_path,
                    )
                except ExecutorTimeout:
                    outcome = self._handle_timeout(lmr_id, attempt, attempts)
                    if outcome is not None:
                        return outcome
                    self._sleep_backoff(attempt)
                    continue
                except ExecutorError as exc:
                    if self.log is not None:
                        self.log.emit(
                            "failed", id=lmr_id, attempt=attempt, error=str(exc)[:200]
                        )
                    if attempt < attempts:
                        self._sleep_backoff(attempt)
                        continue
                    reason = f"review_executor_failed:{str(exc)[:120]}"
                    self.ledger.transition(lmr_id, lmr.STATE_ESCALATED, reason=reason)
                    return "escalated"
                self._apply_verdict(lmr_id, verdict)
                return "reviewed"
            return "exhausted"  # pragma: no cover - 循环必经 return
        finally:
            if worktree is not None:
                self._cleanup_worktree(worktree)
            for path in (snapshot, verdict_path):
                if path is not None:
                    with contextlib.suppress(OSError):
                        Path(path).unlink(missing_ok=True)

    def _handle_timeout(self, lmr_id: str, attempt: int, attempts: int) -> str | None:
        if self.log is not None:
            self.log.emit("timeout", id=lmr_id, attempt=attempt)
        self.ledger.transition(lmr_id, lmr.STATE_REVIEW_TIMEOUT)
        self.ledger.set_retry_count(lmr_id, attempt - 1)
        if attempt < attempts:
            self.ledger.transition(lmr_id, lmr.STATE_IN_REVIEW)
            return None
        self.ledger.transition(
            lmr_id, lmr.STATE_ESCALATED, reason="review_timeout_retries_exhausted"
        )
        if self.log is not None:
            self.log.emit("failed", id=lmr_id, reason="review_timeout_retries_exhausted")
        return "escalated"

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self.config.retry_backoff * (2 ** (attempt - 1))
        if delay > 0:
            time.sleep(delay)

    def _apply_verdict(self, lmr_id: str, verdict: dict) -> None:
        assert self.ledger is not None
        record = self.ledger.get(lmr_id)
        if record.get("state") != lmr.STATE_IN_REVIEW:
            # 审查期间被新 push 顶替/人工流转：丢弃过期 verdict（§12.2 失效重审）。
            if self.log is not None:
                self.log.emit("skipped", id=lmr_id, reason=f"state-changed:{record.get('state')}")
            return
        entry = {
            "verdict": verdict["verdict"],
            "findings": verdict.get("findings", []),
            "evidence_section": verdict.get("evidence_section", ""),
            "sha": record.get("sha"),
            "ts": lmr.utcnow(),
        }
        self.ledger.append_review(lmr_id, entry)
        if self.log is not None:
            self.log.emit(
                "verdict", id=lmr_id, verdict=verdict["verdict"], findings=len(entry["findings"])
            )
        target = {"approve": lmr.STATE_APPROVED, "rework": lmr.STATE_REWORK}.get(
            verdict["verdict"]
        )
        if target is not None:
            self.ledger.transition(lmr_id, target)
        if self.log is not None:
            self.log.emit("completed", id=lmr_id, state=self.ledger.get(lmr_id)["state"])

    # -- 审查 worktree 管理（§12.3）------------------------------------------

    def _create_worktree(self, record: dict) -> Path:
        assert self.worktree_root is not None
        base = Path(self.worktree_root)
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{WORKTREE_PREFIX}{record['id']}"
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        lmr.run_git(["worktree", "prune"], cwd=self.root, timeout=self.config.git_timeout)
        lmr.run_git(
            ["worktree", "add", "--detach", path.as_posix(), str(record["sha"])],
            cwd=self.root,
            timeout=self.config.git_timeout,
        )
        return path

    def _cleanup_worktree(self, path: Path) -> None:
        try:
            lmr.run_git(
                ["worktree", "remove", "--force", path.as_posix()],
                cwd=self.root,
                timeout=self.config.git_timeout,
            )
        except lmr.LedgerError:
            shutil.rmtree(path, ignore_errors=True)
            with contextlib.suppress(lmr.LedgerError):
                lmr.run_git(
                    ["worktree", "prune"], cwd=self.root, timeout=self.config.git_timeout
                )
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        if self.log is not None:
            self.log.emit("worktree-cleaned", path=str(path))

    def _write_snapshot(self, record: dict) -> Path:
        path = _temp_json_path("lmr-snapshot")
        lmr.atomic_write_json(Path(path), record)
        return Path(path)


def _temp_json_path(prefix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix=prefix + "-", suffix=".json")
    os.close(fd)
    return Path(name)


# ---------------------------------------------------------------------------
# 入口（pythonw 无控制台常驻）
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        root = Path.cwd()
        config = load_config_from_env()
        log = EventLog(lmr.ledger_dir_for(root) / "watch.log")
        watcher = LmrWatcher(root=root, config=config, log=log)
        log.emit(
            "watcher-start",
            pid=os.getpid(),
            poll_interval=config.poll_interval,
            reviewer_configured=bool(watcher.executor),
        )
        watcher.run_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    except lmr.LedgerError as exc:
        stream = sys.stderr
        if stream is not None:
            stream.write(f"lmr_watch: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
