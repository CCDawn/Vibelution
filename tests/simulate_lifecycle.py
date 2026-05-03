# -*- coding: utf-8 -*-
"""
沙盘生命周期测试 - 验证生命周期防断裂加固

此脚本不调用大模型，用于测试以下场景：
1. 模拟工具调用失败，检查状态机是否正确记录错误
2. 模拟调用 trigger_self_restart，检查 workspace/ 下的数据是否正确保存
3. 验证错误阻止机制是否生效

运行方式: python tests/simulate_lifecycle.py
"""

import os
import sys
import json
import tempfile
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def test_1_cli_error_detection():
    """测试1: CLI 命令错误检测"""
    print("\n" + "=" * 60)
    print("测试1: CLI 命令错误检测")
    print("=" * 60)

    from tools.shell_tools import execute_shell_command

    # 测试失败的命令
    result = execute_shell_command("python -c 'raise ValueError(\"test error\")'")

    has_failure_marker = "[EXEC FAILURE" in result
    print(f"  输入: python -c 'raise ValueError(\"test error\")'")
    print(f"  输出: {result[:80]}...")
    print(f"  [EXEC FAILURE] 标记: {'PASS' if has_failure_marker else 'FAIL'}")

    # 测试成功的命令
    result_ok = execute_shell_command("echo hello")
    has_warning = "[WARNING" in result_ok or "[EXEC FAILURE" in result_ok
    print(f"\n  输入: echo hello")
    print(f"  输出: {result_ok}")
    print(f"  无错误标记: {'PASS' if not has_warning else 'FAIL'}")

    return has_failure_marker


def test_2_memory_save():
    """测试2: 记忆保存功能"""
    print("\n" + "=" * 60)
    print("测试2: 记忆保存功能")
    print("=" * 60)

    from tools.memory_tools import force_save_current_state, _load_memory

    # 保存测试记忆
    test_wisdom = "沙盘测试: 记忆保存功能正常"
    test_goal = "沙盘测试: 验证记忆持久化"

    result = force_save_current_state(
        core_wisdom=test_wisdom,
        next_goal=test_goal,
    )

    print(f"  保存结果: {result}")

    # 验证读取
    memory = _load_memory()
    print(f"  核心智慧: {memory.get('core_wisdom')}")
    print(f"  当前目标: {memory.get('current_goal')}")

    wisdom_ok = test_wisdom in memory.get("core_wisdom", "")
    goal_ok = test_goal in memory.get("current_goal", "")

    print(f"\n  记忆正确保存: {'PASS' if wisdom_ok and goal_ok else 'FAIL'}")

    return wisdom_ok and goal_ok


def test_3_restart_snapshot():
    """测试3: 重启前的强制快照"""
    print("\n" + "=" * 60)
    print("测试3: 重启前的强制快照")
    print("=" * 60)

    from tools.memory_tools import force_save_current_state

    # 模拟重启前的记忆快照
    snapshot_wisdom = "沙盘测试: 重启前快照成功"
    snapshot_goal = "沙盘测试: 验证重启流程"

    result = force_save_current_state(
        core_wisdom=snapshot_wisdom,
        next_goal=snapshot_goal,
        
    )

    print(f"  快照结果: {result}")

    # 检查 workspace/memory/memory.json 是否存在
    ws_memory = PROJECT_ROOT / "workspace" / "memory" / "memory.json"
    exists = ws_memory.exists()
    print(f"\n  记忆索引文件存在: {exists}")
    print(f"  路径: {ws_memory}")

    if exists:
        with open(ws_memory, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"  智慧: {data.get('core_wisdom')}")

        snapshot_ok = snapshot_wisdom in data.get("core_wisdom", "")
        print(f"\n  快照验证: {'PASS' if snapshot_ok else 'FAIL'}")
        return snapshot_ok

    return False


def test_4_workspace_structure():
    """测试5: workspace 结构完整性"""
    print("\n" + "=" * 60)
    print("测试5: workspace 结构完整性")
    print("=" * 60)

    from core.infrastructure.workspace_manager import get_workspace

    ws = get_workspace()

    checks = []

    # 检查目录
    for d in ["memory", "memory/archives", "prompts", "logs"]:
        path = ws.root / d
        exists = path.exists()
        checks.append(("目录 " + d, exists))
        print(f"  workspace/{d}: {'OK' if exists else 'MISSING'}")

    # 检查关键文件（从 workspace/prompts/ 读取）
    for f in ["SOUL.md", "IDENTITY.md", "SPEC.md"]:
        path = ws.get_prompt_path(f)
        exists = path.exists()
        content_ok = path.exists() and len(ws.read_prompt(f)) > 0
        checks.append(("文件 " + f, content_ok))
        print(f"  workspace/prompts/{f}: {'OK' if content_ok else 'MISSING'}")

    # 检查数据库
    db_exists = ws.db_path.exists()
    checks.append(("数据库", db_exists))
    print(f"  workspace/agent_brain.db: {'OK' if db_exists else 'MISSING'}")

    # 检查记忆索引
    mi_exists = ws.memory_index.exists()
    checks.append(("记忆索引", mi_exists))
    print(f"  workspace/memory/memory.json: {'OK' if mi_exists else 'MISSING'}")

    all_ok = all(c[1] for c in checks)
    print(f"\n  结构完整性: {'PASS' if all_ok else 'FAIL'}")

    return all_ok


def main():
    """运行所有测试"""
    print("\n" + "#" * 60)
    print("# 沙盘生命周期测试")
    print("#" * 60)

    results = []

    try:
        results.append(("CLI错误检测", test_1_cli_error_detection()))
    except Exception as e:
        print(f"  [ERROR] {e}")
        results.append(("CLI错误检测", False))

    try:
        results.append(("记忆保存", test_2_memory_save()))
    except Exception as e:
        print(f"  [ERROR] {e}")
        results.append(("记忆保存", False))

    try:
        results.append(("重启快照", test_3_restart_snapshot()))
    except Exception as e:
        print(f"  [ERROR] {e}")
        results.append(("重启快照", False))

    try:
        results.append(("workspace结构", test_4_workspace_structure()))
    except Exception as e:
        print(f"  [ERROR] {e}")
        results.append(("workspace结构", False))

    # 汇总
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {name}: [{status}]")

    print(f"\n  通过: {passed}/{total}")

    if passed == total:
        print("\n  所有测试通过!")
        return 0
    else:
        print(f"\n  有 {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
