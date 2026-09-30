#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具结果 artifact 落盘存储。

P1-f resultBudget 的落盘档：当工具结果超过声明预算且 strategy=artifact 时，
把序列化后的全文写到 workspace 下的 tool-results 目录，模型只拿到
引用 + sha256 + 预览；原全文供审计与恢复按 tool_call_id 检索。

并发契约：文件名由 ``tool_call_id`` + 内容 sha256 派生，read-only 并行批中
不同调用的写入互相隔离；目录创建用进程级锁兜底。
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

from core.logging import debug as _debug_logger

# 可用环境变量覆盖落盘根目录（测试与沙盒场景使用）。
TOOL_RESULT_ARTIFACT_DIR_ENV = "VIBELUTION_TOOL_RESULT_ARTIFACT_DIR"

# workspace 内的默认子目录（走 developer_sandbox 的 workspace 解析）。
_TOOL_RESULT_ARTIFACT_SUBDIR = ("tool-results",)

_ARTIFACT_REF_PREFIX = "tool-result-artifact"

_SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")

_WRITE_DIR_LOCK = threading.Lock()


def compute_tool_result_digest(content: str) -> str:
    """序列化内容的 sha256，与引用占位先例保持同一摘要口径。"""
    return hashlib.sha256(str(content or "").encode("utf-8", errors="replace")).hexdigest()


def resolve_tool_result_artifact_dir(base_dir: Optional[Path | str] = None) -> Path:
    """解析 artifact 落盘根目录：显式参数 > 环境变量 > workspace tool-results。"""
    if base_dir:
        return Path(str(base_dir)).resolve()
    env_dir = str(os.environ.get(TOOL_RESULT_ARTIFACT_DIR_ENV) or "").strip()
    if env_dir:
        return Path(env_dir).resolve()
    # 惰性导入：developer_sandbox 依赖配置与项目身份解析，避免在模块加载期拉起。
    from core.infrastructure.developer_sandbox import (
        PROJECT_ROOT,
        sandboxed_workspace_path,
    )

    resolved = sandboxed_workspace_path(PROJECT_ROOT, *_TOOL_RESULT_ARTIFACT_SUBDIR)
    if resolved is None:
        from core.infrastructure.developer_sandbox import formal_workspace_path

        resolved = formal_workspace_path(PROJECT_ROOT, *_TOOL_RESULT_ARTIFACT_SUBDIR)
    return Path(str(resolved)).resolve()


def _sanitize_filename_part(value: str, *, cap: int) -> str:
    sanitized = _SAFE_FILENAME_CHARS.sub("_", str(value or "").strip())
    sanitized = sanitized.strip("._") or "no-call"
    return sanitized[:cap]


def build_tool_result_artifact_ref(tool_call_id: str, digest: str) -> str:
    """构造与 tool_result_replacement 引用同构的 artifact 引用。"""
    call_part = _sanitize_filename_part(tool_call_id, cap=64)
    return f"{_ARTIFACT_REF_PREFIX}:{call_part}:{str(digest or '')[:16]}"


def write_tool_result_artifact(
    content: str,
    *,
    tool_name: str = "",
    tool_call_id: str = "",
    base_dir: Optional[Path | str] = None,
) -> dict[str, Any]:
    """把工具结果全文落盘，返回引用元数据。

    返回 ``{"path", "sha256", "chars", "artifactRef"}``；任何写失败都抛异常，
    由调用方静默回退到截断档，不把成功的工具调用变成失败。
    """
    text = str(content or "")
    digest = compute_tool_result_digest(text)
    target_dir = resolve_tool_result_artifact_dir(base_dir)
    call_part = _sanitize_filename_part(tool_call_id, cap=64)
    filename = f"{call_part}-{digest[:16]}.txt"
    target_path = target_dir / filename

    with _WRITE_DIR_LOCK:
        target_dir.mkdir(parents=True, exist_ok=True)
        # 并行批下同 call_id 同内容会得到同一文件名；原子写避免读到半截文件。
        temp_path = target_path.with_name(f"{target_path.name}.tmp-{threading.get_ident()}")
        try:
            temp_path.write_text(text, encoding="utf-8")
            os.replace(temp_path, target_path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    artifact_ref = build_tool_result_artifact_ref(tool_call_id, digest)
    _debug_logger.info(
        f"[工具结果落盘] tool={tool_name} call={call_part} chars={len(text)} sha256={digest[:16]}",
        tag="TOOL_RESULT",
    )
    return {
        "path": str(target_path),
        "sha256": digest,
        "chars": len(text),
        "artifactRef": artifact_ref,
    }


def read_tool_result_artifact(path: Path | str) -> str:
    """按落盘路径读回全文（恢复/审计/测试用）。"""
    return Path(str(path)).read_text(encoding="utf-8")


__all__ = [
    "TOOL_RESULT_ARTIFACT_DIR_ENV",
    "build_tool_result_artifact_ref",
    "compute_tool_result_digest",
    "read_tool_result_artifact",
    "resolve_tool_result_artifact_dir",
    "write_tool_result_artifact",
]
