"""Bounded background commands with real cancellation and tree ownership."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .owned_process import OwnedProcess


def _record_event(code: str, **fields: Any) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event_quietly
        record_runtime_scene_event_quietly("background_tasks", "lifecycle", code,
                                         fields=fields, lifecycle=True,
                                         refresh_package_if_due=False)
    except Exception:
        pass


class _OutputTail:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.data = bytearray()
        self.total = 0
        self.error: str | None = None
        self.lock = threading.Lock()

    def drain(self, pipe: Any) -> None:
        try:
            while chunk := pipe.read(8192):
                with self.lock:
                    self.total += len(chunk)
                    self.data.extend(chunk)
                    if len(self.data) > self.limit:
                        del self.data[:-self.limit]
        except Exception as error:
            self.error = type(error).__name__
        finally:
            try:
                pipe.close()
            except Exception as error:
                self.error = type(error).__name__

    def snapshot(self) -> tuple[str, int, bool]:
        with self.lock:
            text = bytes(self.data).decode("utf-8", errors="replace")
            text = text.encode("utf-8")[-self.limit:].decode("utf-8", errors="ignore")
            return text, self.total, self.total > self.limit


class BackgroundTaskManager:
    def __init__(self, max_workers: int = 4, *, max_pending: int = 64,
                 max_history: int = 128, output_limit_bytes: int = 131072,
                 history_ttl_seconds: float = 3600) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="background-task")
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._closing = False
        self._max_active = max_workers + max(0, max_pending)
        self._max_history = max(1, max_history)
        self._output_limit = max(1, output_limit_bytes)
        self._ttl = max(0.0, history_ttl_seconds)

    def _prune_locked(self) -> None:
        terminal = [(key, value) for key, value in self._tasks.items() if value["end_time"] is not None]
        terminal.sort(key=lambda pair: pair[1]["_ended_monotonic"])
        cutoff = time.monotonic() - self._ttl
        for index, (key, value) in enumerate(terminal):
            if value["_ended_monotonic"] <= cutoff or index < len(terminal) - self._max_history:
                del self._tasks[key]

    def start_task(self, command: str, timeout: int = 300) -> str:
        if not command or not command.strip():
            return json.dumps({"status": "error", "code": "MISSING_COMMAND", "message": "命令不能为空"})
        if len(command.encode("utf-8")) > 65536 or timeout <= 0:
            return json.dumps({"status": "error", "code": "INVALID_TASK", "message": "命令过长或超时时间无效"})
        task_id = uuid.uuid4().hex
        with self._lock:
            self._prune_locked()
            if self._closing:
                return json.dumps({"status": "error", "code": "SHUTTING_DOWN", "message": "后台任务管理器正在关闭"})
            if sum(task["end_time"] is None for task in self._tasks.values()) >= self._max_active:
                return json.dumps({"status": "error", "code": "QUEUE_FULL", "message": "后台任务队列已满"})
            task = self._tasks[task_id] = {
                "id": task_id, "command": command.strip(), "timeout": timeout,
                "status": "running", "start_time": time.time(), "end_time": None,
                "exit_code": None, "output": "", "stderr": "", "cancel_requested": False,
                "cleanup_pending": False, "_cancel": threading.Event(), "_done": threading.Event(),
                "_owner": None, "_readers": [], "_tails": [], "_outcome": "completed",
                "_retire_lock": threading.Lock(),
            }
            task["_future"] = self._executor.submit(self._execute_task, task_id)
            task["_future"].add_done_callback(lambda future: self._future_done(task_id, future))
        _record_event("background_task.started", taskId=task_id)
        return json.dumps({"status": "started", "task_id": task_id, "command": command.strip(),
                           "timeout": timeout, "message": f"后台任务已启动，使用 task_output_tool('{task_id}') 获取结果"}, ensure_ascii=False)

    def _future_done(self, task_id: str, future: Any) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            task.pop("_future", None)
        if future.cancelled():
            self._finish(task_id)

    def _execute_task(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks[task_id]
        if task["_cancel"].is_set():
            self._finish(task_id)
            return
        try:
            deadline = time.monotonic() + task["timeout"]
            command = task["command"]
            # Preserve explicit command syntax, with a hidden owned child tree.
            shell = any(c in command for c in ("|", ">", "<", "&", "$", "`"))
            args = command if shell or os.name == "nt" else shlex.split(command)
            owner = OwnedProcess.spawn(args, shell=shell, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       bufsize=0, cwd=os.getcwd())
            with self._lock:
                task["_owner"] = owner
            tails = [_OutputTail(self._output_limit), _OutputTail(self._output_limit)]
            readers = [threading.Thread(target=tail.drain, args=(pipe,), daemon=True,
                                        name=f"background-output-{task_id[:8]}-{index}")
                       for index, (tail, pipe) in enumerate(zip(tails, (owner.process.stdout, owner.process.stderr)))]
            with self._lock:
                task.update(_owner=owner, _tails=tails, _readers=readers)
            for reader in readers:
                reader.start()
            while owner.process.poll() is None:
                if task["_cancel"].wait(0.03):
                    break
                if time.monotonic() >= deadline:
                    with self._lock:
                        task["_outcome"] = "failed"
                        task["output"] = f"[超时] 任务执行超过 {task['timeout']} 秒"
                    break
            # A root return code alone does not prove command-tree completion.
            if self._retire(task, timeout=5):
                self._finish(task_id)
            else:
                with self._lock:
                    task["cleanup_pending"] = True
                _record_event("background_task.cleanup_pending", taskId=task_id)
        except Exception as error:
            with self._lock:
                task["_outcome"] = "failed"
                task["output"] = f"[错误] {type(error).__name__}"
            if self._retire(task, timeout=5):
                self._finish(task_id)
            else:
                with self._lock:
                    task["cleanup_pending"] = True
                _record_event("background_task.cleanup_pending", taskId=task_id, errorType=type(error).__name__)

    def _retire(self, task: dict[str, Any], *, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        if not task["_retire_lock"].acquire(timeout=max(0.0, timeout)):
            return False
        try:
            owner = task["_owner"]
            if owner is not None and not owner.terminate(timeout=max(0.0, deadline - time.monotonic())):
                return False
            for reader in task["_readers"]:
                if reader.ident is not None:
                    reader.join(timeout=max(0.0, deadline - time.monotonic()))
            if any(reader.is_alive() for reader in task["_readers"]):
                return False
            if owner is not None:
                # All readers have exited, so closing cannot wait on a reader's
                # buffered-I/O lock; also cover failures before thread creation.
                for pipe in (owner.process.stdout, owner.process.stderr):
                    if pipe is not None:
                        pipe.close()
                owner.close(timeout=max(0.0, deadline - time.monotonic()))
                if owner.process.stdin is not None:
                    owner.process.stdin.close()
            if any(tail.error for tail in task["_tails"]):
                with self._lock:
                    task["_outcome"] = "failed"
                    task["output"] = "[错误] 后台输出读取失败"
            return True
        except Exception as error:
            _record_event("background_task.retire_failed", taskId=task["id"], errorType=type(error).__name__)
            return False
        finally:
            task["_retire_lock"].release()

    def _finish(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task["end_time"] is not None:
                return
            owner = task["_owner"]
            if owner is not None:
                task["exit_code"] = owner.process.returncode
            if task["_tails"]:
                stdout, stderr = (tail.snapshot() for tail in task["_tails"])
                if task["_outcome"] != "failed":
                    task["output"] = stdout[0]
                task.update(stderr=stderr[0], stdout_bytes=stdout[1], stderr_bytes=stderr[1],
                            output_truncated=stdout[2], stderr_truncated=stderr[2])
            task["status"] = "cancelled" if task["cancel_requested"] else task["_outcome"]
            task["cleanup_pending"] = False
            task["end_time"] = time.time()
            task["_ended_monotonic"] = time.monotonic()
            task.pop("_future", None)
            task.update(_owner=None, _tails=[], _readers=[])
            task["_done"].set()
            fields = {"taskId": task_id, "status": task["status"],
                      "stdoutBytes": task.get("stdout_bytes", 0), "stderrBytes": task.get("stderr_bytes", 0)}
            self._prune_locked()
        _record_event("background_task.finished", **fields)

    def get_task_output(self, task_id: str) -> str:
        with self._lock:
            self._prune_locked()
            found = self._tasks.get(task_id)
            task = dict(found) if found is not None else None
        if task is None:
            return json.dumps({"status": "error", "code": "NOT_FOUND", "message": "任务不存在或已过期"}, ensure_ascii=False)
        result = {"task_id": task_id, "command": task["command"], "status": task["status"],
                  "elapsed_seconds": round((task["end_time"] or time.time()) - task["start_time"], 1),
                  "exit_code": task["exit_code"], "cancel_requested": task["cancel_requested"],
                  "cleanup_pending": task["cleanup_pending"]}
        if task["status"] == "running":
            result["message"] = "正在停止，等待资源回收" if task["cancel_requested"] else "任务仍在执行中"
        elif task["status"] == "cancelled":
            result["message"] = "任务已被取消，进程树已退出"
        else:
            result.update(output=task["output"], stderr=task["stderr"])
            for name in ("stdout_bytes", "stderr_bytes", "output_truncated", "stderr_truncated"):
                result[name] = task.get(name, 0 if name.endswith("bytes") else False)
        return json.dumps(result, ensure_ascii=False)

    def stop_task(self, task_id: str, *, timeout: float = 5.0) -> str:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return json.dumps({"status": "error", "code": "NOT_FOUND", "message": "任务不存在"}, ensure_ascii=False)
            if task["end_time"] is not None:
                return json.dumps({"status": "error", "code": "NOT_RUNNING", "message": "任务已结束"}, ensure_ascii=False)
            task["cancel_requested"] = True
            task["_cancel"].set()
            future = task.get("_future")
            pending = task["cleanup_pending"]
        _record_event("background_task.cancel_requested", taskId=task_id)
        if future is not None:
            future.cancel()
        if pending and self._retire(task, timeout=max(0.0, deadline - time.monotonic())):
            self._finish(task_id)
        task["_done"].wait(timeout=max(0.0, deadline - time.monotonic()))
        with self._lock:
            cancelled = task["status"] == "cancelled"
        return json.dumps({"status": "cancelled" if cancelled else "running", "task_id": task_id,
                           "cancel_requested": True, "message": "任务已取消" if cancelled else "正在停止，等待资源回收"}, ensure_ascii=False)

    def list_tasks(self) -> str:
        with self._lock:
            self._prune_locked()
            tasks = [{"id": task["id"], "command": task["command"][:80], "status": task["status"],
                      "elapsed": f"{(task['end_time'] or time.time()) - task['start_time']:.0f}s"}
                     for task in self._tasks.values()]
        return json.dumps({"status": "ok" if tasks else "empty", "count": len(tasks), "tasks": tasks}, ensure_ascii=False)

    def shutdown(self, *, timeout: float = 5.0) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            self._closing = True
            tasks = [task for task in self._tasks.values() if task["end_time"] is None]
            for task in tasks:
                task["cancel_requested"] = True
                task["_cancel"].set()
        self._executor.shutdown(wait=False, cancel_futures=True)
        for task in tasks:
            if task["cleanup_pending"] and self._retire(task, timeout=max(0.0, deadline - time.monotonic())):
                self._finish(task["id"])
            task["_done"].wait(timeout=max(0.0, deadline - time.monotonic()))
        remaining = [task["id"] for task in tasks if not task["_done"].is_set()]
        _record_event("background_tasks.shutdown", remainingCount=len(remaining))
        return {"closed": not remaining, "remaining": remaining}


_bg_task_manager: BackgroundTaskManager | None = None
_manager_lock = threading.Lock()
_manager_closing = False


def begin_background_task_lifecycle() -> None:
    global _manager_closing
    with _manager_lock:
        if _manager_closing and _bg_task_manager is not None:
            raise RuntimeError("Previous background tasks are still retiring")
        _manager_closing = False


def get_background_task_manager() -> BackgroundTaskManager:
    global _bg_task_manager
    with _manager_lock:
        if _manager_closing:
            raise RuntimeError("Background task lifecycle is shutting down")
        if _bg_task_manager is None:
            _bg_task_manager = BackgroundTaskManager()
        return _bg_task_manager


def shutdown_background_tasks(*, timeout: float = 5.0) -> dict[str, Any]:
    global _bg_task_manager, _manager_closing
    with _manager_lock:
        _manager_closing = True
        manager = _bg_task_manager
    result = manager.shutdown(timeout=timeout) if manager is not None else {"closed": True, "remaining": []}
    if result["closed"]:
        with _manager_lock:
            if _bg_task_manager is manager:
                _bg_task_manager = None
    return result
