# -*- coding: utf-8 -*-
"""
Evolution Gate - 进化测试门控

在 Agent 代码修改后、触发重启前，运行测试套件验证修改是否引入回归。

功能：
- 运行 pytest 测试套件
- 解析测试结果（通过/失败/超时）
- 返回结构化的测试报告

使用方式：
    from core.evolution.evolution_gate import run_evolution_gate
    result = run_evolution_gate()
    if result["passed"]:
        print("测试通过，可以继续")
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Dict, Any, Optional

from core.logging import debug_logger


# ============================================================================
# 配置常量
# ============================================================================

# 测试目录
DEFAULT_TEST_DIR = "tests/"

# 测试超时（秒）
DEFAULT_TIMEOUT = 120


# ============================================================================
# 核心函数
# ============================================================================

def run_evolution_gate(
    test_dir: str = DEFAULT_TEST_DIR,
    timeout: int = DEFAULT_TIMEOUT,
    project_root: Optional[str] = None,
) -> Dict[str, Any]:
    """
    运行进化测试门控

    在 Agent 代码修改后、触发重启前，运行测试套件验证修改是否引入回归。

    Args:
        test_dir: 测试目录，默认为 "tests/"
        timeout: 测试超时时间（秒），默认为 120 秒
        project_root: 项目根目录，默认为当前文件的上两级目录

    Returns:
        测试结果字典：
        {
            "passed": bool,           # 是否全部通过
            "passed_count": int,       # 通过数
            "failed_count": int,       # 失败数
            "total_count": int,       # 总数
            "failed_modules": list,    # 失败的模块列表
            "output": str,             # 完整输出
        }
    """
    if project_root is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    debug_logger.info("运行进化测试门控...", tag="GATE")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_dir, "-v", "--tb=short", "-q"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=timeout,
        )

        output = result.stdout + result.stderr
        passed_count = output.count(" PASSED")
        failed_count = output.count(" FAILED")
        total_count = passed_count + failed_count

        # 提取失败的模块
        failed_modules = []
        for line in output.split("\n"):
            if "FAILED" in line:
                parts = line.split("::")
                if len(parts) >= 2:
                    failed_modules.append(parts[1].split("::")[0])

        passed = failed_count == 0
        if passed:
            debug_logger.success(f"测试门控通过: {passed_count}/{total_count}", tag="GATE")
        else:
            debug_logger.warning(f"测试门控失败: {failed_count}/{total_count} 失败", tag="GATE")

        return {
            "passed": passed,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "total_count": total_count,
            "failed_modules": list(set(failed_modules)),
            "output": output,
        }

    except subprocess.TimeoutExpired:
        debug_logger.error("测试门控超时 (2分钟)", tag="GATE")
        return {
            "passed": False,
            "passed_count": 0,
            "failed_count": 1,
            "total_count": 0,
            "failed_modules": ["pytest_timeout"],
            "output": "超时"
        }

    except Exception as e:
        debug_logger.error(f"测试门控执行失败: {e}", tag="GATE")
        return {
            "passed": False,
            "passed_count": 0,
            "failed_count": 1,
            "total_count": 0,
            "failed_modules": ["test_runner_error"],
            "output": str(e)
        }


def check_evolution_gate(
    test_dir: str = DEFAULT_TEST_DIR,
    timeout: int = DEFAULT_TIMEOUT,
    project_root: Optional[str] = None,
) -> bool:
    """
    快速检查测试是否通过

    Args:
        test_dir: 测试目录
        timeout: 超时时间
        project_root: 项目根目录

    Returns:
        True if 所有测试通过
    """
    result = run_evolution_gate(test_dir, timeout, project_root)
    return result.get("passed", False)


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    "run_evolution_gate",
    "check_evolution_gate",
    "DEFAULT_TEST_DIR",
    "DEFAULT_TIMEOUT",
]
