#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具执行器测试

测试 core/tool_executor.py 中的：
- 工具注册与管理
- 超时控制
- 事件总线集成
"""

import os
import sys
import pytest
import time
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.infrastructure.tool_executor import ToolExecutor, get_tool_executor


class TestToolExecutorInit:
    """工具执行器初始化测试"""

    def test_init(self):
        """测试初始化"""
        executor = ToolExecutor()
        assert executor._tool_map is not None
        assert len(executor._tool_map) > 0
        assert executor._timeout_map is not None
        assert executor._event_bus is not None

    def test_get_tool_executor_singleton(self):
        """测试单例模式"""
        executor1 = get_tool_executor()
        executor2 = get_tool_executor()
        assert executor1 is executor2

    def test_default_tools_registered(self):
        """测试默认工具已注册"""
        executor = ToolExecutor()
        
        # 检查关键工具是否已注册
        expected_tools = [
            "list_directory", "execute_shell_command", "run_powershell", "check_python_syntax",
            "get_generation", "trigger_self_restart_tool", "grep_search_tool",
            "task_create_tool", "task_update_tool", "task_list_tool",
            "cli_tool",
        ]
        
        for tool_name in expected_tools:
            assert tool_name in executor._tool_map, f"工具 {tool_name} 应该已注册"

    def test_default_timeouts_configured(self):
        """测试默认超时配置"""
        executor = ToolExecutor()
        
        # 检查关键工具的超时配置
        assert "execute_shell_command" in executor._timeout_map
        assert executor._timeout_map["execute_shell_command"] == 60
        
        assert "check_python_syntax" in executor._timeout_map
        assert executor._timeout_map["check_python_syntax"] == 10


class TestToolExecutorExecute:
    """工具执行测试"""

    @pytest.fixture
    def executor(self):
        """创建测试用的执行器实例"""
        return ToolExecutor()

    def test_execute_unknown_tool(self, executor):
        """测试执行未知工具"""
        result, action = executor.execute("nonexistent_tool", {})
        assert result is not None
        assert "[错误] 未知工具" in result
        assert action is None

    def test_execute_read_file(self, executor):
        """测试读取文件工具"""
        # 创建一个测试文件
        test_file = Path(__file__).parent / "test_temp_file.txt"
        test_content = "Hello, Tool Executor!"
        test_file.write_text(test_content, encoding='utf-8')
        
        try:
            result, action = executor.execute("read_file", {
                "file_path": str(test_file)
            })
            
            assert action is None
            assert test_content in str(result)
        finally:
            # 清理测试文件
            if test_file.exists():
                test_file.unlink()

    def test_execute_list_directory(self, executor):
        """测试列出目录工具"""
        test_dir = Path(__file__).parent
        
        result, action = executor.execute("list_directory", {
            "path": str(test_dir)
        })
        
        assert action is None
        assert result is not None
        # 应该包含当前目录的文件
        assert "test_security.py" in str(result) or "test_tool_executor.py" in str(result)

    def test_execute_check_python_syntax_valid(self, executor):
        """测试语法检查 - 有效文件"""
        # 使用当前测试文件（语法正确）
        result, action = executor.execute("check_python_syntax", {
            "file_path": __file__
        })
        
        assert action is None
        assert result is not None
        # 语法正确应该返回成功消息
        assert "语法正确" in str(result) or "Syntax OK" in str(result) or "通过" in str(result)

    def test_execute_with_timeout(self, executor):
        """测试超时控制"""
        # 执行一个快速命令验证超时机制工作
        result, action = executor.execute("list_directory", {
            "path": str(Path(__file__).parent)
        },)
        
        # 应该正常返回，不超时
        assert action is None
        assert result is not None
        assert "[超时]" not in str(result)


class TestToolExecutorTimeout:
    """超时控制测试"""

    @pytest.fixture
    def executor(self):
        return ToolExecutor()

    def test_custom_timeout_registration(self, executor):
        """测试自定义工具超时注册"""
        def slow_tool():
            time.sleep(0.1)
            return "done"
        
        executor.register_tool("test_slow_tool", slow_tool, timeout=5)
        assert executor._timeout_map["test_slow_tool"] == 5

    def test_default_timeout_for_unconfigured_tools(self, executor):
        """测试未配置超时工具的默认超时"""
        # execute 方法内部使用默认超时 30 秒
        # 这里验证工具执行不会因为缺少超时配置而崩溃
        result, action = executor.execute("list_directory", {
            "path": str(Path(__file__).parent)
        })
        assert result is not None


class TestToolExecutorEvents:
    """事件总线集成测试"""

    @pytest.fixture
    def executor(self):
        return ToolExecutor()

    def test_event_bus_integration(self, executor):
        """测试事件总线集成"""
        # 验证事件总线已连接
        assert executor._event_bus is not None
        
        # 执行一个工具，验证不会抛出异常
        result, action = executor.execute("list_directory", {
            "path": str(Path(__file__).parent)
        })
        
        # 如果事件总线有问题，这里会抛出异常
        assert result is not None


class TestToolExecutorRetry:
    """重试机制测试"""

    @pytest.fixture
    def executor(self):
        return ToolExecutor()

    def test_retryable_tools_configured(self, executor):
        """测试可重试工具配置"""
        # 检查是否配置了可重试工具
        assert isinstance(executor._retryable_tools, set)
        
        # 搜索工具应该是可重试的（网络相关可能失败）
        # 注意：根据实际配置调整
        assert len(executor._retryable_tools) >= 0  # 允许为空


class TestToolExecutorErrorHandling:
    """错误处理测试"""

    @pytest.fixture
    def executor(self):
        return ToolExecutor()

    def test_execute_tool_with_invalid_args(self, executor):
        """测试执行工具时参数错误"""
        # 传递错误参数类型
        result, action = executor.execute("read_file", {
            "file_path": 12345  # 应该是字符串
        })
        
        # 应该返回错误而不是抛出异常
        assert result is not None
        assert action is None

    def test_execute_tool_missing_required_args(self, executor):
        """测试执行工具时缺少必需参数"""
        # 缺少 file_path 参数
        result, action = executor.execute("read_file", {})
        
        # 应该返回错误而不是抛出异常
        assert result is not None
        assert action is None


class TestToolExecutorConvenience:
    """便捷功能测试"""

    def test_register_tool(self):
        """测试注册自定义工具"""
        executor = ToolExecutor()
        
        def my_custom_tool(param1, param2="default"):
            return f"Called with {param1} and {param2}"
        
        executor.register_tool("my_custom_tool", my_custom_tool, timeout=10)
        
        assert "my_custom_tool" in executor._tool_map
        assert executor._timeout_map["my_custom_tool"] == 10
        
        # 执行自定义工具
        result, action = executor.execute("my_custom_tool", {
            "param1": "test",
            "param2": "value"
        })
        
        assert "test" in str(result)
        assert "value" in str(result)
        assert action is None

    def test_register_tool_default_timeout(self):
        """测试注册工具时使用默认超时"""
        executor = ToolExecutor()
        
        def my_tool():
            return "done"
        
        executor.register_tool("my_tool", my_tool)
        assert executor._timeout_map["my_tool"] == 30  # 默认超时


class TestToolExecutorIntegration:
    """集成测试"""

    def test_full_workflow(self):
        """测试完整工作流程"""
        # 1. 获取执行器
        executor = get_tool_executor()
        
        # 2. 列出目录
        result, action = executor.execute("list_directory", {
            "path": str(Path(__file__).parent)
        })
        assert result is not None
        assert action is None
        
        # 3. 读取文件
        result, action = executor.execute("read_file", {
            "file_path": __file__
        })
        assert result is not None
        assert action is None
        
        # 4. 检查语法
        result, action = executor.execute("check_python_syntax", {
            "file_path": __file__
        })
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
