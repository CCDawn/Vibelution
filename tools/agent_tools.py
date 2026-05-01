#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent 工具 — 子代理启动

提供 spawn_agent() 函数，通过子进程运行 agent.py 执行指定任务。
"""

from __future__ import annotations

import os
import sys
import json
import subprocess
from pathlib import Path

# 防止递归深度（最多嵌套 2 层）
_MAX_RECURSION_DEPTH = 2


def _get_recursion_depth() -> int:
    """从环境变量获取当前递归深度"""
    try:
        return int(os.environ.get("VIBELUTION_SUBAGENT_DEPTH", "0"))
    except (ValueError, TypeError):
        return 0


def spawn_agent(task: str, timeout: int = 120) -> str:
    """
    启动子 Agent 执行指定任务

    Args:
        task: 要执行的任务描述
        timeout: 超时时间（秒），默认 120

    Returns:
        子 Agent 的输出
    """
    if not task or not task.strip():
        return json.dumps({"status": "error", "code": "MISSING_TASK", "message": "任务描述不能为空"}, ensure_ascii=False)

    depth = _get_recursion_depth()
    if depth >= _MAX_RECURSION_DEPTH:
        return json.dumps({
            "status": "error", "code": "MAX_RECURSION",
            "message": f"已达到最大子代理嵌套深度 ({_MAX_RECURSION_DEPTH})，禁止进一步递归"
        }, ensure_ascii=False)

    agent_path = Path(__file__).parent.parent / "agent.py"
    if not agent_path.exists():
        return json.dumps({"status": "error", "code": "AGENT_NOT_FOUND", "message": f"找不到 agent.py: {agent_path}"}, ensure_ascii=False)

    env = os.environ.copy()
    env["VIBELUTION_SUBAGENT_DEPTH"] = str(depth + 1)

    try:
        result = subprocess.run(
            [sys.executable, str(agent_path), "--prompt", task.strip(), "--auto"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(agent_path.parent),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({
            "status": "timeout",
            "task": task[:100],
            "message": f"子 Agent 执行超时 ({timeout}s)"
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "status": "error", "code": "SPAWN_FAILED",
            "message": f"无法启动子 Agent: {type(e).__name__}: {e}"
        }, ensure_ascii=False)

    output = result.stdout
    if result.stderr:
        output += f"\n\n[stderr]\n{result.stderr[:1000]}"

    if len(output) > 8000:
        output = output[:8000] + "\n\n... [输出截断]"

    return json.dumps({
        "status": "completed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "depth": depth + 1,
        "output": output,
    }, ensure_ascii=False)
