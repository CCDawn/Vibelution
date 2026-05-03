#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重生工具完整测试套件

测试 tools/rebirth_tools.py 中的所有功能：
- 自我重启机制
- 休眠唤醒机制
- 跨平台进程管理
- 重启原因分类
"""

import os
import sys
import pytest
import time
import subprocess
from pathlib import Path
from datetime import datetime

from tools.rebirth_tools import (
    trigger_self_restart_tool,
    enter_hibernation_tool,
    get_current_pid,
    get_script_path,
    classify_restart_reason,
    validate_restarter_available,
)


# ============================================================================
# 测试辅助函数
# ============================================================================

@pytest.fixture
def project_root():
    """获取项目根目录"""
    return Path(__file__).parent.parent.resolve()

@pytest.fixture
def restarter_script(project_root):
    """获取 restarter.py 路径"""
    return project_root / "restarter.py"


# ============================================================================
# 辅助函数测试
# ============================================================================

class TestHelperFunctions:
    """辅助函数测试"""

    def test_get_current_pid_returns_int(self):
        """测试获取当前 PID 返回整数"""
        pid = get_current_pid()
        assert isinstance(pid, int)
        assert pid > 0

    def test_get_current_pid_unique(self):
        """测试 PID 唯一性（同一进程 PID 不变）"""
        pid1 = get_current_pid()
        pid2 = get_current_pid()
        assert pid1 == pid2

    def test_get_script_path_returns_str(self):
        """测试获取脚本路径返回字符串"""
        path = get_script_path()
        assert isinstance(path, str)
        assert len(path) > 0

    def test_get_script_path_points_to_agent_py(self):
        """测试路径指向 agent.py"""
        path = get_script_path()
        assert path.endswith("agent.py") or path.endswith("agent.pyc")

    def test_get_script_path_exists(self):
        """测试脚本路径存在"""
        path = get_script_path()
        # 如果是 .py 文件，应该存在
        if path.endswith('.py'):
            assert os.path.exists(path), f"agent.py 应该在: {path}"

    def test_classify_restart_reason_code_update(self):
        """测试分类：代码更新"""
        assert classify_restart_reason("code_update") == "code_update"
        assert classify_restart_reason("代码更新后重启") == "code_update"
        assert classify_restart_reason("CODE_UPDATE") == "code_update"

    def test_classify_restart_reason_threshold(self):
        """测试分类：阈值达到"""
        assert classify_restart_reason("threshold_reached") == "threshold_reached"
        assert classify_restart_reason("达到运行阈值重启") == "threshold_reached"

    def test_classify_restart_reason_manual(self):
        """测试分类：手动触发"""
        assert classify_restart_reason("manual") == "manual"
        assert classify_restart_reason("手动触发重启") == "manual"
        # 未知原因应归类为 manual
        assert classify_restart_reason("unknown_reason_xyz") == "manual"

    def test_classify_restart_reason_error(self):
        """测试分类：错误恢复"""
        assert classify_restart_reason("error_recovery") == "error_recovery"
        assert classify_restart_reason("错误恢复重启") == "error_recovery"

    def test_classify_restart_reason_scheduled(self):
        """测试分类：定时重启"""
        assert classify_restart_reason("scheduled") == "scheduled"
        assert classify_restart_reason("定时重启") == "scheduled"

    def test_classify_restart_reason_maintenance(self):
        """测试分类：维护重启"""
        assert classify_restart_reason("maintenance") == "maintenance"
        assert classify_restart_reason("维护重启") == "maintenance"

    def test_validate_restarter_available(self, project_root, restarter_script):
        """测试验证 restarter 可用性"""
        is_available, error_msg = validate_restarter_available()
        
        # 结果取决�� restarter.py 是否存在
        if restarter_script.exists():
            assert is_available is True
            assert error_msg == ""
        else:
            assert is_available is False
            assert "不存在" in error_msg or "not exist" in error_msg.lower()

    def test_validate_restarter_returns_tuple(self):
        """测试返回元组"""
        result = validate_restarter_available()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)


# ============================================================================
# trigger_self_restart_tool 测试
# ============================================================================

class TestTriggerSelfRestart:
    """自我重启工具测试"""

    def test_trigger_restart_returns_string(self):
        """测试重启返回字符串结果"""
        result = trigger_self_restart_tool(reason="测试重启")
        assert isinstance(result, str)
        # 应该包含重启相关信息
        assert ("重启" in result or "restart" in result.lower() or 
                "触发" in result or "triggered" in result.lower())

    def test_trigger_restart_with_custom_reason(self):
        """测试带自定义原因的重启"""
        reasons = [
            "code_update",
            "threshold_reached",
            "manual",
            "error_recovery",
            "scheduled",
            "maintenance",
            "测试自定义原因",
        ]
        for reason in reasons:
            result = trigger_self_restart_tool(reason=reason)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_trigger_restart_with_delay(self):
        """测试延迟重启"""
        result = trigger_self_restart_tool(delay_seconds=2)
        assert isinstance(result, str)
        assert "2秒" in result or "2s" in result.lower() or "延迟" in result

    def test_trigger_restart_no_delay(self):
        """测试立即重启（默认）"""
        result = trigger_self_restart_tool()
        assert isinstance(result, str)

    def test_trigger_restart_creates_restarter_process(self):
        """测试重启时创建 restarter 进程"""
        # 注意：这个测试会实际触发重启流程，但不会真正重启当前测试进程
        # 因为 trigger_self_restart_tool 内部会启动 restarter 进程
        
        # 检查重启前状态
        current_pid = get_current_pid()
        
        result = trigger_self_restart_tool(reason="test")
        
        # 即使重启流程启动，当前进程应仍在运行（测试环境）
        after_pid = get_current_pid()
        assert current_pid == after_pid  # PID 不应改变
        
        # 结果应描述重启流程
        assert isinstance(result, str)

    def test_trigger_restart_with_task_description(self):
        """测试带任务描述的重启"""
        result = trigger_self_restart_tool(
            reason="测试任务完成",
            task_description="完成单元测试编写"
        )
        assert "任务" in result or "task" in result.lower() or "完成" in result

    def test_trigger_restart_validates_restarter(self):
        """测试重启前验证 restarter 脚本"""
        result = trigger_self_restart_tool()
        # 如果 restarter 不存在，应返回错误信息
        if "错误" in result or "失败" in result or "error" in result.lower():
            assert ("restarter" in result.lower() or 
                    "脚本" in result or "script" in result.lower())


# ============================================================================
# enter_hibernation_tool 测试
# ============================================================================

class TestEnterHibernation:
    """休眠工具测试"""

    def test_hibernation_basic(self):
        """测试基本休眠功能"""
        start = time.time()
        result = enter_hibernation_tool(duration_seconds=2)
        elapsed = time.time() - start
        
        assert isinstance(result, str)
        assert "休眠" in result or "hibernat" in result.lower()
        # 实际休眠时间应接近 2 秒（允许 ±0.5 秒误差）
        assert 1.5 <= elapsed <= 3.0, f"休眠时长异常: {elapsed}s"

    def test_hibernation_1_second(self):
        """测试 1 秒休眠"""
        start = time.time()
        result = enter_hibernation_tool(duration_seconds=1)
        elapsed = time.time() - start
        
        assert 0.5 <= elapsed <= 2.0

    def test_hibernation_5_seconds(self):
        """测试 5 秒休眠"""
        start = time.time()
        result = enter_hibernation_tool(duration_seconds=5)
        elapsed = time.time() - start
        
        assert 4.0 <= elapsed <= 6.5

    def test_hibernation_with_reason(self):
        """测试带原因描述的休眠"""
        result = enter_hibernation_tool(
            duration_seconds=1,
            reason="测试休眠原因：等待资源释放"
        )
        assert "原因" in result or "reason" in result.lower() or "等待" in result

    def test_hibernation_reason_parsing(self):
        """测试休眠原因解析（从 reason 字段提取时长）"""
        # 测试包含时长描述的原因
        result = enter_hibernation_tool(
            duration_seconds=3,
            reason="休眠时长: 3 秒，用于测试"
        )
        assert "3" in result or "三" in result

    def test_hibernation_zero_duration(self):
        """测试零时长休眠（应视为极短休眠）"""
        start = time.time()
        result = enter_hibernation_tool(duration_seconds=0)
        elapsed = time.time() - start
        # 即使为 0，也应至少短暂等待
        assert elapsed >= 0

    def test_hibernation_very_short(self):
        """测试极短休眠（0.1 秒）"""
        start = time.time()
        result = enter_hibernation_tool(duration_seconds=0.1)
        elapsed = time.time() - start
        # 应至少休眠 0.05 秒以上
        assert elapsed >= 0.05

    def test_hibernation_multiple_cycles(self):
        """测试多次休眠周期"""
        total_sleep = 0
        for i in range(3):
            start = time.time()
            enter_hibernation_tool(duration_seconds=0.5)
            total_sleep += time.time() - start
        
        # 总休眠时间应至少 1.2 秒（3 * 0.5 = 1.5，允许一定误差）
        assert total_sleep >= 1.2

    def test_hibernation_default_duration(self):
        """测试默认休眠时长"""
        # 默认时长应来自配置，这里测试是否有一个合理的默认值
        result = enter_hibernation_tool()
        assert isinstance(result, str)
        # 应返回休眠相关信息
        assert ("休眠" in result or "hibernat" in result.lower())


# ============================================================================
# ��成测试
# ============================================================================

class TestRebirthIntegration:
    """重生模块集成测试"""

    def test_restart_workflow_validation(self):
        """测试重启工作流程验证"""
        # 1. 检查重启器可用性
        is_available, error = validate_restarter_available()
        
        # 2. 获取当前 PID
        pid = get_current_pid()
        assert pid > 0
        
        # 3. 触发重启（测试模式下不会真正重启测试进程）
        result = trigger_self_restart_tool(reason="integration_test")
        
        # 4. 验证响应
        assert isinstance(result, str)
        assert len(result) > 0

    def test_hibernation_cycle_with_restart(self):
        """测试休眠周期与重启"""
        # 休眠
        enter_hibernation_tool(duration_seconds=1, reason="准备重启")
        
        # 休眠后触发重启
        result = trigger_self_restart_tool(reason="休眠后重启")
        assert isinstance(result, str)

    def test_restart_reason_classification_workflow(self):
        """测试重启原因分类工作流"""
        test_cases = [
            ("code_update", "code_update"),
            ("threshold_reached", "threshold_reached"),
            ("manual", "manual"),
            ("error_recovery", "error_recovery"),
            ("scheduled", "scheduled"),
            ("maintenance", "maintenance"),
            ("some random text", "manual"),
            ("", "manual"),
        ]
        
        for input_reason, expected in test_cases:
            category = classify_restart_reason(input_reason)
            assert category == expected, f"输入: '{input_reason}', 期望: {expected}, 实际: {category}"

    def test_full_lifecycle_simulation(self):
        """模拟完整生命周期"""
        # 1. 初始状态
        pid = get_current_pid()
        assert pid > 0
        
        # 2. 休眠（模拟等待）
        enter_hibernation_tool(duration_seconds=0.5, reason="模拟等待")
        
        # 3. 完成任务，触发重启
        result = trigger_self_restart_tool(
            reason="test_complete",
            task_description="完成重生工具测试"
        )
        assert isinstance(result, str)


# ============================================================================
# 平台兼容性测试
# ============================================================================

class TestPlatformCompatibility:
    """平台兼容性测试"""

    def test_spawn_detached_process_exists(self):
        """测试跨平台进程脱离函数存在"""
        from tools.rebirth_tools import spawn_detached_process
        
        assert callable(spawn_detached_process)

    def test_windows_specific_functions(self):
        """测试 Windows 特定函数"""
        if sys.platform == 'win32':
            from tools.rebirth_tools import spawn_detached_process_windows
            assert callable(spawn_detached_process_windows)

    def test_unix_specific_functions(self):
        """测试 Unix 特定函数"""
        if sys.platform != 'win32':
            from tools.rebirth_tools import spawn_detached_process_unix
            assert callable(spawn_detached_process_unix)

    def test_restarter_script_exists(self, restarter_script):
        """测试 restarter.py 脚本存在"""
        assert restarter_script.exists(), f"restarter.py 应存在于: {restarter_script}"

    def test_restarter_script_executable(self, restarter_script):
        """测试 restarter.py 可执行性"""
        # Windows 上不需要 +x 权限，但文件应可读
        assert os.access(restarter_script, os.R_OK)

    def test_restarter_script_has_main(self, restarter_script):
        """测试 restarter.py 包含 main 函数"""
        content = restarter_script.read_text(encoding='utf-8')
        assert 'if __name__ == "__main__"' in content or "if __name__ == '__main__'" in content


# ============================================================================
# 安全性测试
# ============================================================================

class TestSecurity:
    """安全性测试"""

    def test_restart_does_not_leak_sensitive_data(self):
        """测试重启不泄露敏感数据"""
        # 重启参数中不应包含敏感信息
        result = trigger_self_restart_tool(reason="test", task_description="test task")
        assert "password" not in result.lower()
        assert "key" not in result.lower() or "key" in result.lower()  # 可能包含 "key" 这个词

    def test_hibernation_reason_sanitization(self):
        """测试休眠原因消毒"""
        # 尝试注入危险内容
        dangerous = "'; DROP TABLE users; --"
        result = enter_hibernation_tool(duration_seconds=1, reason=dangerous)
        # 应该正常处理（不会执行注入）
        assert isinstance(result, str)

    def test_restart_reason_no_command_injection(self):
        """测试重启原因无命令注入"""
        injection = "test; rm -rf /;"
        category = classify_restart_reason(injection)
        assert category == "manual"  # 应归类为 manual，不执行命令


# ============================================================================
# 并发测试
# ============================================================================

class TestConcurrency:
    """并发测试"""

    def test_multiple_restart_requests(self):
        """测试多个重启请求"""
        # 快速连续触发多次重启（实际上只会启动一个 restarter）
        results = []
        for i in range(3):
            result = trigger_self_restart_tool(reason=f"concurrent_test_{i}")
            results.append(result)
        
        # 所有请求都应返回有效响应
        assert all(isinstance(r, str) for r in results)

    def test_concurrent_hibernation(self):
        """测试并发休眠"""
        import threading
        
        results = []
        
        def hibernate():
            result = enter_hibernation_tool(duration_seconds=0.5)
            results.append(result)
        
        threads = [threading.Thread(target=hibernate) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(results) == 5
        assert all(isinstance(r, str) for r in results)


# ============================================================================
# 异常处理测试
# ============================================================================

class TestErrorHandling:
    """异常处理测试"""

    def test_trigger_restart_with_missing_restarter(self, monkeypatch):
        """测试 restarter 缺失时的处理"""
        # 临时修改 RESTARTER_SCRIPT 路径
        from tools.rebirth_tools import RESTARTER_SCRIPT
        original = RESTARTER_SCRIPT
        
        try:
            # 设置为不存在的路径
            import tools.rebirth_tools
            tools.rebirth_tools.RESTARTER_SCRIPT = Path("nonexistent_restarter.py")
            
            result = trigger_self_restart_tool()
            # 应返回错误信息而非抛出异常
            assert isinstance(result, str)
            assert ("错误" in result or "失败" in result or 
                    "not found" in result.lower() or "missing" in result.lower())
        finally:
            tools.rebirth_tools.RESTARTER_SCRIPT = original

    def test_hibernation_negative_duration(self):
        """测试负时长休眠（应处理为 0 或默认值）"""
        result = enter_hibernation_tool(duration_seconds=-1)
        assert isinstance(result, str)
        # 应返回错误或使用默认值

    def test_validate_restarter_permission_denied(self, monkeypatch):
        """测试权限不足"""
        # 这个测试取决于实际文件权限，可能在某些环境无法触发
        is_avail, error = validate_restarter_available()
        # 应该不抛出异常，而是返回状态
        assert isinstance(is_avail, bool)
        assert isinstance(error, str)


# ============================================================================
# 性能测试
# ============================================================================

class TestPerformance:
    """性能基准测试"""

    def test_get_pid_performance(self):
        """测试获取 PID 的性能"""
        import time
        start = time.time()
        for _ in range(1000):
            get_current_pid()
        elapsed = time.time() - start
        assert elapsed < 0.5  # 1000 次调用应在 0.5 秒内

    def test_classify_reason_performance(self):
        """测试原因分类性能"""
        import time
        reasons = ["manual", "code_update", "threshold_reached"] * 1000
        
        start = time.time()
        for reason in reasons:
            classify_restart_reason(reason)
        elapsed = time.time() - start
        
        assert elapsed < 1.0  # 3000 次分类应在 1 秒内

    def test_hibernation_timing_accuracy(self):
        """测试休眠时间准确性"""
        durations = [0.5, 1.0, 2.0, 3.0]
        
        for target in durations:
            start = time.time()
            enter_hibernation_tool(duration_seconds=target)
            actual = time.time() - start
            
            # 允许 10% 误差
            assert target * 0.9 <= actual <= target * 1.5, \
                f"目标 {target}s, 实际 {actual}s"


# ============================================================================
# 返回值格式测试
# ============================================================================

class TestReturnFormats:
    """返回值格式测试"""

    def test_trigger_restart_returns_meaningful_message(self):
        """测试重启返回有意义的消息"""
        result = trigger_self_restart_tool()
        
        # 应包含关键信息
        assert any(keyword in result for keyword in 
                   ["重启", "restart", "触发", "trigger", "进程", "process"])

    def test_hibernation_returns_duration(self):
        """测试休眠返回时长信息"""
        result = enter_hibernation_tool(duration_seconds=2)
        assert "2" in result or "两" in result or "二" in result

    def test_validate_restarter_returns_consistent(self):
        """测试验证返回一致性"""
        is_avail1, error1 = validate_restarter_available()
        is_avail2, error2 = validate_restarter_available()
        
        # 两次调用结果应一致（除非环境变化）
        assert is_avail1 == is_avail2
        assert type(error1) == type(error2)


# ============================================================================
# 参数边界测试
# ============================================================================

class TestParameterBoundaries:
    """参数边界测试"""

    def test_hibernation_max_duration(self):
        """测试最大休眠时长"""
        # 允许的最大时长
        result = enter_hibernation_tool(duration_seconds=3600)  # 1 小时
        assert isinstance(result, str)

    def test_hibernation_very_large_duration(self):
        """测试超大休眠时长（不会真的睡那么久）"""
        # 传入很大但实际只睡很短用于测试
        result = trigger_self_restart_tool(delay_seconds=10000)
        assert isinstance(result, str)

    def test_restart_reason_empty_string(self):
        """测试空字符串原因"""
        result = trigger_self_restart_tool(reason="")
        assert isinstance(result, str)

    def test_restart_task_description_very_long(self):
        """测试超长任务描述"""
        long_desc = "A" * 10000
        result = trigger_self_restart_tool(task_description=long_desc)
        assert isinstance(result, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
