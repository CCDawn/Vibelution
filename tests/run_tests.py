#!/usr/bin/env python3
"""
轻量级测试运行器 - 不依赖 pytest

使用 unittest 模块运行测试，确保在没有 pytest 的环境中也能工作。

使用方法：
    python tests/run_tests.py              # 运行所有测试
    python tests/run_tests.py -v          # 详细输出
"""

import sys
import os
import unittest
from pathlib import Path
from datetime import datetime
from typing import Tuple, Dict, List

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_memory_tests() -> Dict:
    """运行记忆系统测试"""
    from tests.test_memory import (
        TestMemoryBasics,
        TestMemoryWrite,
        TestArchiveSystem,
        TestMemoryIntegration,
    )

    suite = unittest.TestSuite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestMemoryBasics))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestMemoryWrite))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestArchiveSystem))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestMemoryIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return {
        "name": "记忆系统",
        "passed": result.testsRun - len(result.failures) - len(result.errors),
        "failed": len(result.failures),
        "errors": len(result.errors),
        "total": result.testsRun,
        "success": result.wasSuccessful(),
    }


def run_tool_tests() -> Dict:
    """运行工具模块测试"""
    # 工具模块测试已分散到独立测试文件中
    # 通过 pytest 自动发现运行
    return {
        "name": "工具模块",
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "total": 0,
        "success": True,
    }


def run_compression_tests() -> Dict:
    """运行压缩逻辑测试"""
    from tests.test_compression import (
        TestTokenEstimation,
        TestMessagePriority,
        TestTruncation,
        TestSmartCompression,
        TestEnhancedCompressor,
        TestCompressionStats,
        TestPreemptiveCompression,
    )

    suite = unittest.TestSuite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestTokenEstimation))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestMessagePriority))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestTruncation))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSmartCompression))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEnhancedCompressor))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestCompressionStats))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestPreemptiveCompression))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return {
        "name": "压缩逻辑",
        "passed": result.testsRun - len(result.failures) - len(result.errors),
        "failed": len(result.failures),
        "errors": len(result.errors),
        "total": result.testsRun,
        "success": result.wasSuccessful(),
    }


def run_all_tests() -> Tuple[bool, List[Dict]]:
    """运行所有测试"""
    print("="*60)
    print("[TEST] Self-Evolution Sandbox - Lightweight Test Runner")
    print("="*60)
    print(f"项目目录: {PROJECT_ROOT}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    results = []

    test_modules = [
        ("记忆系统", run_memory_tests),
        ("工具模块", run_tool_tests),
        ("压缩逻辑", run_compression_tests),
    ]

    for name, test_func in test_modules:
        print(f"\n{'='*60}")
        print(f"[TEST] Module: {name}")
        print("="*60)

        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            results.append({
                "name": name,
                "success": False,
                "error": str(e),
            })
            print(f"[ERROR] Test execution failed: {e}")

    return results


def print_summary(results: List[Dict]) -> bool:
    """打印测试摘要"""
    print("\n" + "="*60)
    print("[SUMMARY] Test Summary")
    print("="*60)

    total_passed = 0
    total_failed = 0
    total_tests = 0
    all_passed = True

    for result in results:
        name = result.get("name", "Unknown")
        success = result.get("success", False)

        if success:
            passed = result.get("passed", 0)
            failed = result.get("failed", 0)
            total = result.get("total", 0)
            print(f"[OK] {name}: {passed}/{total} passed")
            total_passed += passed
            total_failed += failed
            total_tests += total
        else:
            print(f"[FAIL] {name}: failed")
            error = result.get("error", "Unknown error")
            print(f"   +-> {error}")
            all_passed = False

    print("-"*60)
    print(f"Total: {total_tests} tests, {total_passed} passed, {total_failed} failed")
    print("="*60)

    return all_passed


def check_evolution_ready() -> Tuple[bool, str]:
    """
    检查是否可以安全执行自我进化。

    在 Agent 调用 trigger_self_restart 之前必须调用此函数。

    Returns:
        (can_continue, message): 是否可以继续，以及原因
    """
    results = run_all_tests()
    all_passed = print_summary(results)

    if all_passed:
        return True, "[OK] All tests passed, safe to evolve"
    else:
        failed = [r["name"] for r in results if not r.get("success", False)]
        return False, f"[FAIL] Tests failed, evolution blocked\nFailed modules: {', '.join(failed)}"


if __name__ == "__main__":
    results = run_all_tests()
    all_passed = print_summary(results)

    sys.exit(0 if all_passed else 1)
