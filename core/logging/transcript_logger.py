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
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.paths import resolve_workspace_home
from core.logging.safe_payload import summarize_tool_arguments


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

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
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

        # 后台写入线程，避免磁盘 I/O 阻塞主循环
        self._write_queue = queue.Queue()
        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True, name="transcript-writer"
        )
        self._writer_thread.start()

    def _writer_loop(self):
        """后台线程：从队列中取出内容并写入文件"""
        while True:
            filepath, content = self._write_queue.get()
            try:
                if filepath is None:
                    return
                with open(filepath, 'a', encoding='utf-8') as f:
                    f.write(content)
            except Exception:
                pass
            finally:
                self._write_queue.task_done()

    def _enqueue_write(self, content: str):
        """将写入内容放入队列，由后台线程异步写入"""
        self._write_queue.put((self._get_transcript_file(), content))

    def _flush_pending_writes(self):
        """等待所有待处理的写入完成"""
        self._write_queue.join()

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
        escaped_content = self._escape_markdown(content)

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

{self._escape_markdown(thinking)}

</details>

"""

        # 转义并处理回复内容
        escaped_content = self._escape_markdown(content)

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

        # 格式化参数
        args_str = self._format_tool_args(args)

        # 截断结果
        result_str = ""
        if result:
            truncated_result = self._truncate_text(result, 500)
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
{self._escape_markdown(error_msg)}
```

"""
        self._enqueue_write(content_md)

    def write_action(self, action: str, details: str = None):
        """写入特殊动作"""
        details_str = f"\n\n**详情**: {details}" if details else ""

        content_md = f"""

### ⚡ 动作: {action}{details_str}

"""
        self._enqueue_write(content_md)

    def end_session(self, summary: str = None):
        """结束会话记录（等待所有待处理写入完成后写入结束标记）"""
        self._flush_pending_writes()

        summary_str = f"\n\n## 📋 会话总结\n\n{summary}" if summary else ""

        content = f"""

---

## 🏁 会话结束

> 生成时间: {self._timestamp()}
> 对话轮次: {self._current_turn}{summary_str}

"""
        self._enqueue_write(content)
        self._flush_pending_writes()

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


def get_transcript_logger() -> TranscriptLogger:
    """获取全局 TranscriptLogger 实例"""
    global _transcript_logger
    if _transcript_logger is None:
        _transcript_logger = TranscriptLogger()
    return _transcript_logger
