# -*- coding: utf-8 -*-
"""
优雅对话渲染器 - 将 LLM 交互生成为精美的 Markdown 文本

特性：
- 使用 HTML <details> 折叠超长内容（System Prompt）
- 醒目的标题和引用块区分不同角色
- 代码块自动高亮语言标签
- 工具调用以列表形式优雅呈现
- 自动清理旧会话文件（保留最近 5 个）
"""

import glob
import hashlib
import json
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from config.paths import resolve_workspace_home
from core.logging.safe_payload import summarize_tool_arguments
from core.logging.value_redaction import redact_sensitive_text


class TranscriptLogger:
    """
    优雅对话渲染器 - 生成精美的 Markdown 对话实录

    排版规范：
    - System Prompt: 使用 <details> 折叠
    - User Input: 引用块 + 标题
    - LLM Response: 正常 Markdown 渲染
    - Tool Calls: 无序列表 + 截断显示
    """

    _instance = None
    _lock = threading.Lock()

    DEFAULT_MAX_PENDING_WRITES = 512
    DEFAULT_MAX_PENDING_BYTES = 8 * 1024 * 1024
    DEFAULT_FLUSH_TIMEOUT_SECONDS = 1.0
    DEFAULT_END_SESSION_FLUSH_TIMEOUT_SECONDS = 0.25

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        *,
        max_pending_writes: int = DEFAULT_MAX_PENDING_WRITES,
        max_pending_bytes: int = DEFAULT_MAX_PENDING_BYTES,
    ):
        if self._initialized:
            return
        self._initialized = True

        self._logs_dir = resolve_workspace_home() / "logs" / "transcripts"
        self._ensure_logs_dir()

        # 当前会话和对话轮次
        self._session_id = None
        self._current_turn = 0
        self._is_first_message = True
        self._system_prompt_written = False

        # 队列容量同时按记录条数和 UTF-8 字节数限制；pending 统计包含正在写入的记录。
        self._max_pending_writes = max(1, int(max_pending_writes))
        self._max_pending_bytes = max(1, int(max_pending_bytes))
        self._write_queue = queue.Queue(maxsize=self._max_pending_writes)
        self._state = threading.Condition(threading.RLock())
        self._writer_thread = None
        self._accepting_writes = False
        self._sentinel_queued = False
        self._pending_writes = 0
        self._pending_bytes = 0
        self._last_accepted_sequence = 0
        self._last_completed_sequence = 0
        self._dropped_writes = 0
        self._dropped_characters = 0
        self._dropped_capacity_writes = 0
        self._dropped_oversized_writes = 0
        self._write_failures = 0
        self.begin()

    @staticmethod
    def _utf8_size_up_to(content: str, limit: int) -> Optional[int]:
        """Return exact UTF-8 size up to limit with only a small temporary encoding buffer."""
        if len(content) > limit:
            return None
        if content.isascii():
            return len(content)

        size = 0
        try:
            for start in range(0, len(content), 8192):
                size += len(content[start : start + 8192].encode("utf-8"))
                if size > limit:
                    return None
        except UnicodeEncodeError:
            return None
        return size

    def begin(self) -> bool:
        """Open the writer for a lifespan; never overlap an unretired writer."""
        with self._state:
            if self._writer_thread is not None and self._writer_thread.is_alive():
                return self._accepting_writes
            if self._pending_writes:
                return False

            self._write_queue = queue.Queue(maxsize=self._max_pending_writes)
            self._sentinel_queued = False
            self._accepting_writes = True
            self._writer_thread = threading.Thread(
                target=self._writer_loop,
                daemon=True,
                name="transcript-writer",
            )
            try:
                self._writer_thread.start()
            except Exception:
                self._writer_thread = None
                self._accepting_writes = False
                raise
            return True

    def _writer_loop(self):
        """后台线程：从队列中取出内容并写入文件"""
        while True:
            item = self._write_queue.get()
            try:
                if item is None:
                    return
                filepath, content, sequence, content_bytes = item
                try:
                    with open(filepath, 'a', encoding='utf-8') as f:
                        f.write(content)
                except Exception:
                    with self._state:
                        self._write_failures += 1
            finally:
                self._write_queue.task_done()
                if item is not None:
                    with self._state:
                        self._pending_writes = max(0, self._pending_writes - 1)
                        self._pending_bytes = max(0, self._pending_bytes - content_bytes)
                        self._last_completed_sequence = sequence
                        self._state.notify_all()

    def _enqueue_write(self, content: str) -> Optional[int]:
        """非阻塞入队；超出容量时拒收并累计不含正文的丢失计数。"""
        if not isinstance(content, str):
            content = str(content)
        content_bytes = self._utf8_size_up_to(content, self._max_pending_bytes)
        with self._state:
            if content_bytes is None:
                self._dropped_writes += 1
                self._dropped_characters += len(content)
                self._dropped_oversized_writes += 1
                return None
            if (
                not self._accepting_writes
                or self._pending_writes >= self._max_pending_writes
                or self._pending_bytes + content_bytes > self._max_pending_bytes
            ):
                self._dropped_writes += 1
                self._dropped_characters += len(content)
                self._dropped_capacity_writes += 1
                return None

            sequence = self._last_accepted_sequence + 1
            item = (self._get_transcript_file(), content, sequence, content_bytes)
            try:
                self._write_queue.put_nowait(item)
            except queue.Full:
                self._dropped_writes += 1
                self._dropped_characters += len(content)
                self._dropped_capacity_writes += 1
                return None

            self._last_accepted_sequence = sequence
            self._pending_writes += 1
            self._pending_bytes += content_bytes
            return sequence

    def _flush_through(self, sequence: int, deadline: float) -> bool:
        with self._state:
            while self._last_completed_sequence < sequence:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._state.wait(remaining)
            return True

    def flush(self, timeout: float = DEFAULT_FLUSH_TIMEOUT_SECONDS) -> bool:
        """Wait a bounded time for accepted write attempts, ignoring later producers."""
        duration = max(0.0, float(timeout))
        deadline = time.monotonic() + duration
        with self._state:
            sequence = self._last_accepted_sequence
        return self._flush_through(sequence, deadline)

    def _flush_pending_writes(
        self, timeout: float = DEFAULT_FLUSH_TIMEOUT_SECONDS
    ) -> bool:
        """Compatibility wrapper for existing callers; never waits without a deadline."""
        return self.flush(timeout)

    def diagnostics(self) -> Dict[str, Any]:
        """Return bounded counters and writer state without exposing transcript contents."""
        with self._state:
            writer_alive = bool(
                self._writer_thread is not None and self._writer_thread.is_alive()
            )
            return {
                "accepting": self._accepting_writes,
                "writer_alive": writer_alive,
                "pending_writes": self._pending_writes,
                "pending_bytes": self._pending_bytes,
                "max_pending_writes": self._max_pending_writes,
                "max_pending_bytes": self._max_pending_bytes,
                "dropped_writes": self._dropped_writes,
                "dropped_characters": self._dropped_characters,
                "dropped_capacity_writes": self._dropped_capacity_writes,
                "dropped_oversized_writes": self._dropped_oversized_writes,
                "write_failures": self._write_failures,
            }

    def shutdown(
        self,
        *,
        deadline: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Stop accepting writes, drain to a monotonic deadline, and join the real writer."""
        if deadline is None:
            duration = self.DEFAULT_FLUSH_TIMEOUT_SECONDS if timeout is None else max(0.0, float(timeout))
            deadline = time.monotonic() + duration

        with self._state:
            self._accepting_writes = False
            target_sequence = self._last_accepted_sequence
            writer = self._writer_thread
            if writer is None:
                return self._shutdown_result(
                    closed=self._pending_writes == 0,
                    drained=self._pending_writes == 0,
                    timed_out=False,
                )

        drained = self._flush_through(target_sequence, deadline)
        # Even if a write failed, retire the thread after it has attempted every accepted item.
        with self._state:
            if not self._sentinel_queued and self._last_completed_sequence >= target_sequence:
                try:
                    self._write_queue.put_nowait(None)
                    self._sentinel_queued = True
                except queue.Full:
                    pass

            while not self._sentinel_queued:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._shutdown_result(
                        closed=False,
                        drained=drained,
                        timed_out=True,
                    )
                self._state.wait(min(remaining, 0.02))
                if self._last_completed_sequence >= target_sequence:
                    try:
                        self._write_queue.put_nowait(None)
                        self._sentinel_queued = True
                    except queue.Full:
                        pass

        remaining = max(0.0, deadline - time.monotonic())
        writer.join(timeout=remaining)
        stopped = not writer.is_alive()
        with self._state:
            return self._shutdown_result(
                closed=stopped,
                drained=drained,
                timed_out=not stopped,
            )

    def _shutdown_result(self, *, closed: bool, drained: bool, timed_out: bool) -> Dict[str, Any]:
        writer_alive = bool(
            self._writer_thread is not None and self._writer_thread.is_alive()
        )
        result = {
            "closed": bool(closed and not writer_alive),
            "drained": bool(drained),
            "timed_out": bool(timed_out),
        }
        result.update(self.diagnostics())
        return result

    def _ensure_logs_dir(self):
        """确保日志目录存在"""
        self._logs_dir.mkdir(parents=True, exist_ok=True)

    def _timestamp(self) -> str:
        """获取格式化的时间戳"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _get_transcript_file(self) -> Path:
        """获取当前会话的 Markdown 记录文件路径"""
        if self._session_id is None:
            self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self._logs_dir / f"transcript_{self._session_id}.md"

    def _generate_header(self) -> str:
        """生成 Markdown 文件头部"""
        header = f"""---
title: "对话实录"
date: "{datetime.now().isoformat()}"
session: {self._session_id}
---

# 📝 对话实录

> _自动生成于 {self._timestamp()}_

"""
        return header

    def _generate_turn_header(self, turn: int, timestamp: str = None) -> str:
        """生成对话轮次标题"""
        ts = timestamp or self._timestamp()
        return f"""

---

## 🔄 第 {turn} 轮对话

> ⏰ {ts}

"""

    def _escape_markdown(self, text: str) -> str:
        """保留模型输出的 Markdown 结构，供 transcript 原样渲染。"""
        if not text:
            return ""
        return str(text)

    def _truncate_text(self, text: str, max_length: int = 500, suffix: str = "...") -> str:
        """截断文本并添加后缀"""
        if not text or len(text) <= max_length:
            return text
        return text[:max_length].rstrip() + suffix

    def _format_tool_args(self, args: Dict[str, Any]) -> str:
        """格式化仅含 keys/shape/length/hash 的工具参数摘要。"""
        return json.dumps(summarize_tool_arguments(args), ensure_ascii=False, indent=2)

    # ==================== 主要 API ====================

    def start_session(self, system_prompt: str = None):
        """开始新的会话记录"""
        if not self.begin():
            raise RuntimeError("TranscriptLogger writer is still retiring")

        with self._state:
            self._session_dropped_writes_at_start = self._dropped_writes
            self._session_write_failures_at_start = self._write_failures

        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_turn = 0
        self._is_first_message = True
        self._system_prompt_written = False

        # 写入文件头
        transcript_file = self._get_transcript_file()
        with open(transcript_file, 'w', encoding='utf-8') as f:
            f.write(self._generate_header())

        # 如果有 System Prompt，写入折叠版本
        if system_prompt:
            self.write_system_prompt(system_prompt)

        # 执行清理
        self.cleanup_old_transcripts()

    def write_system_prompt(self, system_prompt: str):
        """Write a prompt-free diagnostic summary."""
        if self._system_prompt_written:
            return

        self._system_prompt_written = True

        prompt_text = str(system_prompt or "")
        prompt_hash = hashlib.sha256(
            prompt_text.encode("utf-8", errors="ignore")
        ).hexdigest()

        content = f"""

## System Prompt

> [system prompt omitted] chars={len(prompt_text)} sha256={prompt_hash}

"""
        self._enqueue_write(content)

    def start_turn(self, turn: int, timestamp: str = None):
        """开始新的对话轮次"""
        self._current_turn = turn
        self._enqueue_write(self._generate_turn_header(turn, timestamp))

    def write_external_request(self, content: str, timestamp: str = None):
        """写入外部任务输入"""
        ts = timestamp or self._timestamp()
        # value 级脱敏：直连本 logger 的调用方（get_transcript_logger 单例）不经过
        # UnifiedLogger，这里再兜一道；对已脱敏输入幂等。
        escaped_content = self._escape_markdown(redact_sensitive_text(content))

        content_md = f"""### 外部任务输入

> [{ts}] {escaped_content}

"""
        self._enqueue_write(content_md)

    def write_user_input(self, content: str, timestamp: str = None):
        """兼容旧调用：外部输入不再写成用户/宿主指令。"""
        return self.write_external_request(content, timestamp)

    def write_llm_response(self, content: str, thinking: str = None):
        """写入 LLM 回复（异步写入，不阻塞主循环）"""
        # 处理思考过程（如果有）
        thinking_section = ""
        if thinking:
            thinking_section = f"""
<details>
<summary>🤔 模型思考过程</summary>

{self._escape_markdown(redact_sensitive_text(thinking))}

</details>

"""

        # 转义并处理回复内容
        escaped_content = self._escape_markdown(redact_sensitive_text(content))

        content_md = f"""{thinking_section}### 🤖 模型回复

{escaped_content}

"""
        self._enqueue_write(content_md)

    def write_tool_call(self, tool_name: str, args: Dict[str, Any], result: str = None, status: str = "success"):
        """写入工具调用（异步写入，不阻塞主循环）"""
        # 状态图标
        status_icon = {
            "success": "✅",
            "error": "❌",
            "called": "🔧",
            "completed": "✅",
            "skipped": "⏭️",
            "failed": "❌"
        }.get(status, "🔧")

        # 格式化参数（safe_payload shape+hash，无明文；不接 value 脱敏以保契约）
        args_str = self._format_tool_args(args)

        # 截断结果
        result_str = ""
        if result:
            truncated_result = self._truncate_text(redact_sensitive_text(result), 500)
            escaped_result = self._escape_markdown(truncated_result)
            result_str = f"""

    **返回结果**:
    ```
    {escaped_result}
    ```
"""

        content_md = f"""

### 🔧 工具调用: {tool_name} {status_icon}

**参数**:
```json
{args_str}
```{result_str}

"""
        self._enqueue_write(content_md)

    def write_compression(self, before_tokens: int, after_tokens: int, saved_tokens: int):
        """写入上下文压缩记录"""
        ratio = (saved_tokens / before_tokens * 100) if before_tokens > 0 else 0

        content_md = f"""

### 📦 上下文压缩

| 压缩前 | 压缩后 | 节省 |
|--------|--------|------|
| {before_tokens} | {after_tokens} | {ratio:.1f}% ({saved_tokens} tokens) |

"""
        self._enqueue_write(content_md)

    def write_error(self, error_type: str, error_msg: str):
        """写入错误记录"""
        content_md = f"""

### ⚠️ 错误: {error_type}

```
{self._escape_markdown(redact_sensitive_text(error_msg))}
```

"""
        self._enqueue_write(content_md)

    def write_action(self, action: str, details: str = None):
        """写入特殊动作"""
        details_str = f"\n\n**详情**: {redact_sensitive_text(details)}" if details else ""

        content_md = f"""

### ⚡ 动作: {action}{details_str}

"""
        self._enqueue_write(content_md)

    def end_session(self, summary: str = None):
        """记录会话结束，并以固定上限等待已接收内容落盘。"""

        summary_str = f"\n\n## 📋 会话总结\n\n{summary}" if summary else ""

        content = f"""

---

## 🏁 会话结束

> 生成时间: {self._timestamp()}
> 对话轮次: {self._current_turn}{summary_str}

"""
        sequence = self._enqueue_write(content)
        if sequence is None:
            return False
        flushed = self._flush_through(
            sequence,
            time.monotonic() + self.DEFAULT_END_SESSION_FLUSH_TIMEOUT_SECONDS,
        )
        with self._state:
            no_session_loss = (
                self._dropped_writes == getattr(self, "_session_dropped_writes_at_start", 0)
                and self._write_failures == getattr(self, "_session_write_failures_at_start", 0)
            )
        return flushed and no_session_loss

    def cleanup_old_transcripts(self, keep_recent: int = 5):
        """清理旧的 transcript 文件，只保留最近 N 个会话"""
        # 查找所有 transcript 文件
        pattern = str(self._logs_dir / "transcript_*.md")
        files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

        # 删除超出保留数量的文件
        deleted_count = 0
        for file_path in files[keep_recent:]:
            try:
                os.remove(file_path)
                deleted_count += 1
            except Exception:
                pass

        if deleted_count > 0:
            from core.logging import debug as _debug_logger
            _debug_logger.info(f"[TranscriptLogger] 已清理 {deleted_count} 个旧 transcript 文件")

        return deleted_count


# ==================== 全局实例 ====================

# 延迟初始化，避免循环导入
_transcript_logger = None
_transcript_logger_lock = threading.Lock()


def _existing_transcript_logger() -> Optional[TranscriptLogger]:
    """Return an already constructed instance without starting a writer."""
    with _transcript_logger_lock:
        return _transcript_logger or TranscriptLogger._instance


def begin_transcript_logger_lifecycle() -> Dict[str, Any]:
    """Reopen an existing logger after its prior writer has exited; never instantiate one."""
    instance = _existing_transcript_logger()
    if instance is None:
        return {"opened": False, "present": False, "reason": "not_initialized"}

    opened = instance.begin()
    result = {"opened": opened, "present": True}
    result.update(instance.diagnostics())
    if not opened:
        result["reason"] = "writer_still_retiring"
    return result


def shutdown_transcript_logger(*, deadline: float) -> Dict[str, Any]:
    """Retire an existing logger by a monotonic deadline without creating a new owner."""
    instance = _existing_transcript_logger()
    if instance is None:
        return {
            "closed": True,
            "present": False,
            "drained": True,
            "timed_out": False,
            "write_failures": 0,
            "dropped_writes": 0,
            "pending_writes": 0,
            "pending_bytes": 0,
            "writer_alive": False,
            "accepting": False,
        }
    result = instance.shutdown(deadline=deadline)
    result["present"] = True
    return result


def get_transcript_logger() -> TranscriptLogger:
    """获取全局 TranscriptLogger 实例"""
    global _transcript_logger
    with _transcript_logger_lock:
        if _transcript_logger is None:
            _transcript_logger = TranscriptLogger()
        return _transcript_logger
