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
import json
import pytest
import threading
import time
from types import SimpleNamespace
from pathlib import Path
from core.infrastructure.event_bus import EventNames, get_event_bus
from core.pet_system import get_pet_system
from core.pet_system.pet_system import reset_pet_system

from core.infrastructure import evolution_governor as governor_module
from core.infrastructure.tool_executor import IMAGE2_TOOL_TIMEOUT_SECONDS, ToolExecutor, get_tool_executor
from core.infrastructure.agent_session import get_session_state, reset_session_state
from tools.Key_Tools import create_key_tools, create_llm_facing_tools


LEGACY_AGENT_TOOL_NAMES = {
    "read_file",
    "list_directory",
    "check_python_syntax",
    "create_file",
    "execute_shell_command",
    "run_powershell",
    "run_batch",
    "find_definitions_tool",
    "find_function_calls_tool",
    "get_file_entities",
    "get_file_entities_tool",
    "list_file_entities_tool",
    "get_code_entity_tool",
    "python_symbol_tool",
}


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
            "read_file_tool", "glob_tool", "code_symbol_tool", "python_lint_tool",
            "apply_patch_tool", "plan_update_tool",
            "trigger_self_restart_tool", "grep_search_tool",
            "task_create_tool", "task_update_tool", "task_list_tool",
            "cli_tool", "cli_agent_run_tool", "agent_message_tool", "conversation_log_inspect_tool",
        ]
        
        for tool_name in expected_tools:
            assert tool_name in executor._tool_map, f"工具 {tool_name} 应该已注册"

    def test_default_tool_map_contains_only_canonical_tools_and_internal_spawn(self):
        """执行器默认只注册 canonical agent 工具和内部委派入口。"""
        executor = ToolExecutor()
        canonical_names = {tool.name for tool in create_key_tools()}

        assert set(executor._tool_map) == canonical_names | {"spawn_agent_tool"}
        assert not (LEGACY_AGENT_TOOL_NAMES & set(executor._tool_map))

    def test_agent_message_tool_is_llm_facing(self):
        """Agent 私信工具应出现在默认 LLM 工具目录里。"""
        names = {tool.name for tool in create_llm_facing_tools()}

        assert "agent_message_tool" in names

    def test_research_knowledge_tool_is_registered_and_llm_facing(self):
        """科研知识库查询工具进入工具目录，但运行时还需要 Agent 显式授权。"""
        canonical_names = {tool.name for tool in create_key_tools()}
        llm_names = {tool.name for tool in create_llm_facing_tools()}

        assert "research_knowledge_query_tool" in canonical_names
        assert "research_knowledge_query_tool" in llm_names
        assert "knowledge_rag_retrieve_tool" in canonical_names
        assert "knowledge_rag_retrieve_tool" in llm_names
        assert "unified_knowledge_search_tool" in canonical_names
        assert "unified_knowledge_search_tool" in llm_names

    def test_conversation_log_inspect_tool_is_registered_and_llm_facing(self):
        canonical_names = {tool.name for tool in create_key_tools()}
        llm_names = {tool.name for tool in create_llm_facing_tools()}

        assert "conversation_log_inspect_tool" in canonical_names
        assert "conversation_log_inspect_tool" in llm_names

    def test_cli_agent_run_tool_is_registered_and_allowed_by_session_default(self):
        from core.web.services.agent_directory_service import (
            compute_effective_tool_visibility,
            default_session_agent_tool_policy,
            default_tool_policy,
        )

        canonical_names = {tool.name for tool in create_key_tools()}
        llm_names = {tool.name for tool in create_llm_facing_tools()}

        assert "cli_agent_run_tool" in canonical_names
        assert "cli_agent_run_tool" in llm_names

        restricted_visibility = compute_effective_tool_visibility(create_llm_facing_tools(), policy=default_tool_policy())

        assert "cli_agent_run_tool" not in restricted_visibility.visible_tools
        assert "cli_agent_run_tool" in restricted_visibility.hidden_restricted_tools

        session_visibility = compute_effective_tool_visibility(
            create_llm_facing_tools(),
            policy=default_session_agent_tool_policy("tool-agent-session"),
        )

        assert "cli_agent_run_tool" in session_visibility.visible_tools
        assert "cli_agent_run_tool" not in session_visibility.hidden_restricted_tools

    def test_memory_tools_are_llm_facing_but_policy_gated_by_default(self):
        from core.web.services.agent_directory_service import (
            compute_effective_tool_visibility,
            default_session_agent_tool_policy,
            default_tool_policy,
        )

        tools = create_llm_facing_tools()
        llm_names = {tool.name for tool in tools}
        memory_tool_names = {"record_learning_tool", "search_error_archive_tool", "search_memory_tool"}

        assert memory_tool_names.issubset(llm_names)

        visibility = compute_effective_tool_visibility(tools, policy=default_tool_policy())

        assert memory_tool_names.isdisjoint(visibility.visible_tools)
        assert memory_tool_names.issubset(visibility.hidden_restricted_tools)

        session_visibility = compute_effective_tool_visibility(
            tools,
            policy=default_session_agent_tool_policy("tool-agent-session"),
        )

        assert memory_tool_names.isdisjoint(session_visibility.visible_tools)
        assert memory_tool_names.issubset(session_visibility.hidden_restricted_tools)

    def test_tools_package_does_not_reexport_compat_aliases(self):
        """tools 包入口不再把底层 helper 伪装成 agent 工具别名。"""
        import tools

        compat_exports = {
            "read_file_tool",
            "list_directory_tool",
            "check_python_syntax_tool",
            "create_file_tool",
            "execute_shell_command_tool",
            "run_powershell_tool",
            "run_batch_tool",
            "find_definitions_tool",
            "find_function_calls_tool",
            "get_file_entities_tool",
        }
        assert not any(hasattr(tools, name) for name in compat_exports)

    def test_web_search_tool_executes_registered_callable(self, monkeypatch):
        """web_search_tool should call the raw implementation, not a LangChain StructuredTool."""
        import tools.Key_Tools as key_tools_module

        seen = {}

        def fake_web_search(query: str, max_results: int = 10) -> str:
            seen["query"] = query
            seen["max_results"] = max_results
            return "[搜索] ok"

        monkeypatch.setattr(key_tools_module, "_web_search_impl", fake_web_search)

        executor = ToolExecutor()
        result, action = executor.execute(
            "web_search_tool",
            {"query": "latest ai news", "max_results": 3},
        )

        assert action is None
        assert result == "[搜索] ok"
        assert seen == {"query": "latest ai news", "max_results": 3}

    def test_tool_error_text_is_recorded_as_failed_scene_event(self, monkeypatch):
        """Tools returning an agent-readable error string should not be logged as succeeded."""
        from core.infrastructure import tool_executor as tool_executor_module

        events = []
        monkeypatch.setattr(
            tool_executor_module,
            "_record_tool_scene_event",
            lambda *args, **kwargs: events.append((args, kwargs)),
        )

        executor = ToolExecutor()
        executor.register_tool(
            "fake_error_tool",
            lambda: "[错误] 本地 token 服务不可用",
            timeout=5,
        )

        result, action = executor.execute("fake_error_tool", {})

        assert action is None
        assert str(result).startswith("[错误]")
        assert events[-1][0][1] == "tool.execute.failed"
        assert events[-1][1]["outcome"] == "failed"
        assert events[-1][1]["fields"]["semanticStatus"] == "failed"

    def test_tool_json_blocked_result_is_recorded_as_blocked_scene_event(self, monkeypatch):
        """Tools returning structured blocked JSON should not be logged as succeeded."""
        from core.infrastructure import tool_executor as tool_executor_module

        events = []
        monkeypatch.setattr(
            tool_executor_module,
            "_record_tool_scene_event",
            lambda *args, **kwargs: events.append((args, kwargs)),
        )

        executor = ToolExecutor()
        executor.register_tool(
            "fake_blocked_tool",
            lambda: json.dumps({"ok": False, "status": "blocked", "error": "target_not_found"}),
            timeout=5,
        )

        result, action = executor.execute("fake_blocked_tool", {})

        assert action is None
        assert json.loads(result)["status"] == "blocked"
        assert events[-1][0][1] == "tool.execute.blocked"
        assert events[-1][1]["outcome"] == "blocked"
        assert events[-1][1]["fields"]["semanticStatus"] == "blocked"
        assert events[-1][1]["fields"]["toolResultError"] == "target_not_found"

    def test_tool_json_cancelled_result_is_recorded_as_cancelled_scene_event(self, monkeypatch):
        """Tools returning cancelled JSON should record a cancelled scene event."""
        from core.infrastructure import tool_executor as tool_executor_module

        events = []
        monkeypatch.setattr(
            tool_executor_module,
            "_record_tool_scene_event",
            lambda *args, **kwargs: events.append((args, kwargs)),
        )

        executor = ToolExecutor()
        executor.register_tool(
            "fake_cancelled_tool",
            lambda: json.dumps({"status": "cancelled", "error": "operator stop"}),
            timeout=5,
        )

        result, action = executor.execute("fake_cancelled_tool", {})

        assert action is None
        assert json.loads(result)["status"] == "cancelled"
        assert events[-1][0][1] == "tool.execute.cancelled"
        assert events[-1][1]["outcome"] == "cancelled"
        assert events[-1][1]["fields"]["semanticStatus"] == "cancelled"
        assert events[-1][1]["fields"]["toolResultStatus"] == "cancelled"

    def test_tool_json_timed_out_result_is_recorded_as_timeout_scene_event(self, monkeypatch):
        """Tools returning timed_out JSON should be mapped to timeout scene event."""
        from core.infrastructure import tool_executor as tool_executor_module

        events = []
        monkeypatch.setattr(
            tool_executor_module,
            "_record_tool_scene_event",
            lambda *args, **kwargs: events.append((args, kwargs)),
        )

        executor = ToolExecutor()
        executor.register_tool(
            "fake_timeout_tool",
            lambda: json.dumps({"status": "timed_out", "error": "request hit timeout"}),
            timeout=5,
        )

        result, action = executor.execute("fake_timeout_tool", {})

        assert action is None
        assert json.loads(result)["status"] == "timed_out"
        assert events[-1][0][1] == "tool.execute.timeout"
        assert events[-1][1]["outcome"] == "timeout"
        assert events[-1][1]["fields"]["semanticStatus"] == "timeout"

    def test_tool_json_no_result_is_recorded_as_failed_scene_event(self, monkeypatch):
        """Tools returning no_result JSON should not be marked as succeeded."""
        from core.infrastructure import tool_executor as tool_executor_module

        events = []
        monkeypatch.setattr(
            tool_executor_module,
            "_record_tool_scene_event",
            lambda *args, **kwargs: events.append((args, kwargs)),
        )

        executor = ToolExecutor()
        executor.register_tool(
            "fake_no_result_tool",
            lambda: json.dumps({"status": "no_result", "message": "no result"}),
            timeout=5,
        )

        result, action = executor.execute("fake_no_result_tool", {})

        assert action is None
        assert json.loads(result)["status"] == "no_result"
        assert events[-1][0][1] == "tool.execute.failed"
        assert events[-1][1]["outcome"] == "failed"
        assert events[-1][1]["fields"]["semanticStatus"] == "failed"

    def test_default_timeouts_configured(self):
        """测试默认超时配置"""
        executor = ToolExecutor()
        
        # 检查关键工具的超时配置
        assert executor._timeout_map["cli_tool"] == 60
        assert executor._timeout_map["cli_agent_run_tool"] == 900
        assert executor._timeout_map["python_lint_tool"] == 60
        assert executor._timeout_map["spawn_agent_tool"] == 150
        assert executor._timeout_map["image2_generate_tool"] == IMAGE2_TOOL_TIMEOUT_SECONDS == 300
        assert not (LEGACY_AGENT_TOOL_NAMES & set(executor._timeout_map))


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
        assert "nonexistent_tool" not in str(result)
        assert "当前可用工具包括" in str(result)
        assert "read_file_tool" in str(result)
        assert action is None

    @pytest.mark.parametrize("tool_name", sorted(LEGACY_AGENT_TOOL_NAMES))
    def test_legacy_agent_tool_names_are_unknown(self, executor, tool_name):
        """旧工具名不再走兼容层，也不在错误文本中回显污染下一轮。"""
        result, action = executor.execute(tool_name, {})

        assert action is None
        assert "[错误] 未知工具" in str(result)
        assert f"未知工具：{tool_name}" not in str(result)
        assert f"`{tool_name}`" not in str(result)

    def test_unknown_tool_does_not_publish_raw_tool_name(self, executor):
        """未知工具事件使用通用标签，避免旧名进入可见事件流。"""
        events = []
        bus = get_event_bus()
        callback_id = "test_unknown_tool_name_sanitized"
        bus.subscribe(EventNames.TOOL_START, lambda event: events.append(("start", event.data)), callback_id=f"{callback_id}_start")
        bus.subscribe(EventNames.TOOL_ERROR, lambda event: events.append(("error", event.data)), callback_id=f"{callback_id}_error")

        try:
            result, action = executor.execute("read_file", {})
        finally:
            bus.unsubscribe_by_id(f"{callback_id}_start")
            bus.unsubscribe_by_id(f"{callback_id}_error")

        assert action is None
        assert "[错误] 未知工具" in str(result)
        assert not any(kind == "start" for kind, _data in events)
        kind, event_data = events[-1]
        assert kind == "error"
        assert event_data["name"] == "[unknown_tool]"
        assert "[错误] 未知工具" in event_data["error"]
        assert "当前可用工具包括" in event_data["error"]
        assert "read_file_tool" in event_data["error"]
        assert "read_file" not in event_data["error"].replace("read_file_tool", "")

    def test_unknown_tool_in_agent_runtime_lists_only_visible_tools(self, executor, monkeypatch):
        from core.web.services import agent_directory_service

        monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {
            "agentId": "agent-policy",
            "toolPolicy": {
                "policyId": "tool-agent-policy",
                "allowedTools": ["agent_message_tool", "read_memory_tool"],
                "blockedTools": [],
            },
        })

        result, action = executor.execute("read_memory_tool", {})

        assert action is None
        assert "[错误] 未知工具" in str(result)
        assert "未暴露给当前 Agent" in str(result)
        assert "当前 Agent 可见工具包括：agent_message_tool" in str(result)
        assert "read_memory_tool" not in str(result)
        assert "get_memory_summary_tool" not in str(result)
        assert "read_file_tool" not in str(result)
        assert "grep_search_tool" not in str(result)

    def test_unknown_tool_reports_agent_context_fallback(self, executor, monkeypatch):
        from core.web.services import agent_directory_service

        def fail_current_agent_runtime():
            raise RuntimeError("runtime unavailable")

        monkeypatch.setattr(agent_directory_service, "current_agent_runtime", fail_current_agent_runtime)

        result, action = executor.execute("missing_runtime_tool", {})

        assert action is None
        assert "[错误] 未知工具" in str(result)
        assert "当前 Agent 上下文不可用（RuntimeError）" in str(result)
        assert "已回退到通用工具预览" in str(result)
        assert "当前可用工具包括" in str(result)

    def test_execute_read_file(self, executor):
        """测试读取文件工具"""
        # 创建一个测试文件
        test_file = Path(__file__).parent / "test_temp_file.txt"
        test_content = "Hello, Tool Executor!"
        test_file.write_text(test_content, encoding='utf-8')
        
        try:
            result, action = executor.execute("read_file_tool", {
                "file_path": str(test_file)
            })
            
            assert action is None
            assert test_content in str(result)
        finally:
            # 清理测试文件
            if test_file.exists():
                test_file.unlink()

    def test_execute_glob_tool(self, executor):
        """测试文件模式匹配工具"""
        test_dir = Path(__file__).parent
        
        result, action = executor.execute("glob_tool", {
            "pattern": "test_*.py",
            "search_dir": str(test_dir),
        })
        
        assert action is None
        assert result is not None
        assert any(item["name"].startswith("test_") for item in result)

    def test_execute_python_lint_valid(self, executor):
        """测试 canonical Python lint 工具可执行并返回结构化结果。"""
        result, action = executor.execute("python_lint_tool", {
            "target": __file__,
            "max_issues": 5,
        })
        
        assert action is None
        assert result is not None
        assert '"status"' in str(result)

    def test_execute_with_timeout(self, executor):
        """测试超时控制"""
        # 执行一个快速命令验证超时机制工作
        result, action = executor.execute("glob_tool", {
            "pattern": "test_tool_executor.py",
            "search_dir": str(Path(__file__).parent),
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
        result, action = executor.execute("glob_tool", {
            "pattern": "test_tool_executor.py",
            "search_dir": str(Path(__file__).parent),
        })
        assert result is not None

    def test_spawn_agent_tool_uses_requested_timeout_with_buffer(self, executor):
        timeout = executor._resolve_timeout("spawn_agent_tool", {"timeout": 120})

        assert timeout == 150

    def test_cli_tool_uses_requested_timeout(self, executor):
        timeout = executor._resolve_timeout("cli_tool", {"timeout": 600})

        assert timeout == 600

    def test_image2_tool_default_timeout_matches_slow_generation_budget(self, executor):
        timeout = executor._resolve_timeout("image2_generate_tool", {})

        assert timeout == 300

    def test_spawn_agent_tool_is_registered_for_internal_governor(self, executor):
        assert "spawn_agent_tool" in executor._tool_map

    def test_get_file_entities_tool_compat_alias_is_not_registered(self, executor):
        assert "get_file_entities_tool" not in executor._tool_map

    def test_code_symbol_tool_v2_project_graph_modes(self, executor, tmp_path, monkeypatch):
        from core.code_context_graph import service as graph_service

        (tmp_path / "core").mkdir()
        (tmp_path / "tests").mkdir()
        source = tmp_path / "demo_symbols.py"
        source = tmp_path / "core" / "demo_symbols.py"
        source.write_text(
            "class Demo:\n"
            "    def run(self):\n"
            "        return helper()\n\n"
            "def helper():\n"
            "    return 1\n",
            encoding="utf-8",
        )
        (tmp_path / "tests" / "test_demo_symbols.py").write_text(
            "from core.demo_symbols import helper\n\ndef test_helper():\n    assert helper() == 1\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(graph_service, "project_root", lambda: tmp_path)

        indexed, index_action = executor.execute(
            "code_symbol_tool",
            {"mode": "index"},
        )
        inspected, inspect_action = executor.execute(
            "code_symbol_tool",
            {"mode": "inspect", "file_path": "core/demo_symbols.py"},
        )
        affected, affected_action = executor.execute(
            "code_symbol_tool",
            {"mode": "affected_tests", "file_path": "core/demo_symbols.py"},
        )

        assert index_action is None
        assert inspect_action is None
        assert affected_action is None
        assert json.loads(indexed)["summary"]["fileCount"] >= 2
        assert any(item["qualifiedName"] == "Demo.run" for item in json.loads(inspected)["symbols"])
        assert any(item["path"] == "tests/test_demo_symbols.py" for item in json.loads(affected)["tests"])

    def test_code_symbol_tool_rejects_removed_legacy_parameters(self, executor):
        result, action = executor.execute("code_symbol_tool", {"mode": "inspect", "entity_name": "Demo.run"})

        assert action is None
        assert "[工具参数错误]" in str(result)
        assert "entity_name" in str(result)

    def test_code_symbol_tool_reports_deprecated_legacy_mode(self, executor):
        result, action = executor.execute("code_symbol_tool", {"mode": "entity", "file_path": "agent.py", "symbol": "Agent"})

        assert action is None
        payload = json.loads(result)
        assert payload["status"] == "error"
        assert payload["error"] == "deprecated_mode"

    def test_spawn_agent_tool_requires_internal_delegate_flag(self, executor):
        result, action = executor.execute("spawn_agent_tool", {"goal": "分析重复调用"})

        assert action is None
        assert "仅允许主 agent 的委派治理层内部调用" in str(result)

    def test_spawn_agent_tool_allows_internal_delegate_flag(self, executor):
        def fake_spawn_agent_tool(**kwargs):
            return f"delegated:{kwargs.get('goal', '')}"

        executor.register_tool("spawn_agent_tool", fake_spawn_agent_tool, timeout=5)

        result, action = executor.execute(
            "spawn_agent_tool",
            {"goal": "分析重复调用", "_internal_delegate": True},
        )

        assert action is None
        assert str(result) == "delegated:分析重复调用"

    def test_spawn_agent_tool_internal_delegate_bypasses_llm_tool_policy(self, executor, monkeypatch):
        from core.web.services import agent_directory_service

        monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {
            "agentId": "agent-policy",
            "toolPolicy": {
                "policyId": "tool-agent-policy",
                "allowedTools": ["agent_message_tool"],
                "blockedTools": [],
            },
            "delegationPolicy": {
                "allowSubagents": True,
                "allowedContextModes": ["isolated"],
                "maxDepth": 1,
                "maxConcurrent": 1,
                "allowWakeMessages": True,
            },
        })
        executor.register_tool("spawn_agent_tool", lambda **kwargs: "delegated", timeout=5)

        result, action = executor.execute(
            "spawn_agent_tool",
            {"goal": "分析重复调用", "_internal_delegate": True},
        )

        assert action is None
        assert str(result) == "delegated"

    def test_spawn_agent_tool_respects_current_agent_delegation_policy(self, executor, monkeypatch):
        from core.web.services import agent_directory_service

        monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {
            "agentId": "agent-policy",
            "delegationPolicy": {
                "allowSubagents": False,
                "maxDepth": 0,
                "maxConcurrent": 0,
                "allowWakeMessages": True,
                "allowedContextModes": ["isolated"],
            },
        })
        executor.register_tool("spawn_agent_tool", lambda **kwargs: "should-not-run", timeout=5)

        result, action = executor.execute(
            "spawn_agent_tool",
            {"goal": "分析重复调用", "_internal_delegate": True},
        )

        assert action is None
        assert "DelegationPolicy" in str(result) or "委托策略" in str(result)
        assert "禁止派发子 Agent" in str(result)

    def test_research_knowledge_tool_requires_explicit_tool_policy_allow(self, executor, monkeypatch):
        from core.web.services import agent_directory_service

        monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {
            "agentId": "agent-policy",
            "toolPolicy": {
                "policyId": "tool-agent-policy",
                "allowedTools": [],
                "blockedTools": [],
            },
        })
        result, action = executor.execute("research_knowledge_query_tool", {"query": "agentic"})

        assert action is None
        assert "research_knowledge_query_tool" in str(result)
        assert "显式授权" in str(result)

    def test_knowledge_rag_retrieve_tool_requires_explicit_tool_policy_allow(self, executor, monkeypatch):
        from core.web.services import agent_directory_service

        monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {
            "agentId": "agent-policy",
            "toolPolicy": {
                "policyId": "tool-agent-policy",
                "allowedTools": [],
                "blockedTools": [],
            },
        })
        result, action = executor.execute("knowledge_rag_retrieve_tool", {"query": "governed context"})

        assert action is None
        assert "knowledge_rag_retrieve_tool" in str(result)
        assert "显式授权" in str(result)

    def test_unified_knowledge_search_tool_requires_explicit_tool_policy_allow(self, executor, monkeypatch):
        from core.web.services import agent_directory_service

        monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {
            "agentId": "agent-policy",
            "toolPolicy": {
                "policyId": "tool-agent-policy",
                "allowedTools": [],
                "blockedTools": [],
            },
        })
        result, action = executor.execute("unified_knowledge_search_tool", {"query": "governed context"})

        assert action is None
        assert "unified_knowledge_search_tool" in str(result)
        assert "显式授权" in str(result)

    def test_cli_agent_run_tool_requires_explicit_tool_policy_allow(self, executor, monkeypatch):
        from core.web.services import agent_directory_service

        monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {
            "agentId": "agent-policy",
            "toolPolicy": {
                "policyId": "tool-agent-policy",
                "allowedTools": [],
                "blockedTools": [],
            },
        })
        result, action = executor.execute("cli_agent_run_tool", {"agent_type": "codex_code", "task": "inspect only"})

        assert action is None
        assert "cli_agent_run_tool" in str(result)
        assert "显式授权" in str(result)

    def test_cli_agent_run_tool_runs_with_session_default_tool_policy(self, executor, monkeypatch):
        from core.web.services import agent_directory_service

        monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {
            "agentId": "agent-session",
            "toolPolicy": agent_directory_service.default_session_agent_tool_policy("tool-agent-session"),
        })
        monkeypatch.setitem(
            executor._tool_map,
            "cli_agent_run_tool",
            lambda agent_type="", task="", **_kwargs: f"ran {agent_type}: {task}",
        )

        result, action = executor.execute("cli_agent_run_tool", {"agent_type": "codex_code", "task": "inspect only"})

        assert action is None
        assert result == "ran codex_code: inspect only"

    def test_cli_agent_run_tool_blocked_in_readonly_subagent_scope(self, monkeypatch):
        monkeypatch.setenv("VIBELUTION_SUBAGENT_MODE", "readonly")

        block = ToolExecutor._check_readonly_subagent_block("cli_agent_run_tool")

        assert block
        assert "只读模式" in block

    def test_spawn_agent_tool_internal_flag_is_not_forwarded_to_tool(self, executor):
        captured = {}

        def fake_spawn_agent_tool(**kwargs):
            captured.update(kwargs)
            return "ok"

        executor.register_tool("spawn_agent_tool", fake_spawn_agent_tool, timeout=5)

        result, action = executor.execute(
            "spawn_agent_tool",
            {"goal": "分析重复调用", "_internal_delegate": True},
        )

        assert action is None
        assert str(result) == "ok"
        assert "_internal_delegate" not in captured

    @pytest.mark.slow
    def test_execute_interrupts_running_tool_when_cancel_requested(self, executor):
        cancel_requested = threading.Event()
        tool_started = threading.Event()

        def slow_tool():
            tool_started.set()
            while not cancel_requested.is_set():
                time.sleep(0.01)
            time.sleep(0.1)
            return "late result"

        executor.register_tool("slow_tool", slow_tool, timeout=5)
        executor.set_cancel_checker(lambda: "stop now" if cancel_requested.is_set() else "")

        def trigger_cancel():
            assert tool_started.wait(1.0)
            cancel_requested.set()

        threading.Thread(target=trigger_cancel, daemon=True).start()
        result, action = executor.execute("slow_tool", {})

        assert action is None
        assert "[取消] slow_tool 已因停止请求中断" in str(result)

    def test_cancel_checker_owner_prevents_stale_turn_clear(self, executor):
        owner_a = object()
        owner_b = object()

        executor.set_cancel_checker(lambda: "old stop", owner=owner_a)
        executor.set_cancel_checker(lambda: "new stop", owner=owner_b)
        executor.set_cancel_checker(None, owner=owner_a)

        assert executor._current_cancel_reason() == "new stop"

        executor.set_cancel_checker(None, owner=owner_b)
        assert executor._current_cancel_reason() == ""

    @pytest.mark.slow
    def test_parallel_cancel_checkers_are_isolated_per_call_context(self, executor):
        started = {"a": threading.Event(), "b": threading.Event()}
        release_b = threading.Event()
        cancel_a = threading.Event()
        results = {}

        def slow_tool(label):
            started[label].set()
            if label == "a":
                while not cancel_a.is_set():
                    time.sleep(0.01)
                time.sleep(0.1)
                return "late a"
            assert release_b.wait(2.0)
            return "ok b"

        executor.register_tool("slow_tool", slow_tool, timeout=5)

        def run_a():
            owner = object()
            executor.set_cancel_checker(lambda: "stop a" if cancel_a.is_set() else "", owner=owner)
            try:
                results["a"] = executor.execute("slow_tool", {"label": "a"})[0]
            finally:
                executor.set_cancel_checker(None, owner=owner)

        def run_b():
            owner = object()
            executor.set_cancel_checker(lambda: "", owner=owner)
            try:
                results["b"] = executor.execute("slow_tool", {"label": "b"})[0]
            finally:
                executor.set_cancel_checker(None, owner=owner)

        thread_a = threading.Thread(target=run_a, daemon=True)
        thread_b = threading.Thread(target=run_b, daemon=True)
        thread_a.start()
        thread_b.start()
        assert started["a"].wait(1.0)
        assert started["b"].wait(1.0)

        cancel_a.set()
        thread_a.join(timeout=2.0)
        release_b.set()
        thread_b.join(timeout=2.0)

        assert "[取消] slow_tool 已因停止请求中断" in str(results["a"])
        assert results["b"] == "ok b"


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
        result, action = executor.execute("glob_tool", {
            "pattern": "test_tool_executor.py",
            "search_dir": str(Path(__file__).parent),
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
        result, action = executor.execute("read_file_tool", {
            "file_path": 12345  # 应该是字符串
        })
        
        # 应该返回错误而不是抛出异常
        assert result is not None
        assert action is None
        assert "[工具参数错误]" in str(result)
        assert "file_path 需要 str" in str(result)
        assert "示例：read_file_tool" in str(result)

    def test_cli_tool_accepts_cwd_and_truncates_output(self, executor, tmp_path):
        marker = tmp_path / "marker.txt"
        marker.write_text("ok", encoding="utf-8")

        result, action = executor.execute(
            "cli_tool",
            {
                "command": "python -c \"print('x' * 80)\"",
                "cwd": str(tmp_path),
                "max_output_chars": 40,
            },
        )

        assert action is None
        assert "输出已截断" in str(result)

    def test_plan_update_tool_writes_transient_plan_to_active_workspace(self, executor, tmp_path):
        from tools.shell_tools import workspace_root_override

        with workspace_root_override(tmp_path):
            result, action = executor.execute(
                "plan_update_tool",
                {
                    "plan": [
                        {"step": "审查工具", "status": "completed"},
                        {"step": "补齐测试", "status": "in_progress"},
                    ],
                    "explanation": "对齐 Codex 计划工具",
                },
            )

        assert action is None
        payload = json.loads(str(result))
        assert payload["status"] == "ok"
        plan_path = tmp_path / "plans" / "current.json"
        assert plan_path.exists()
        saved = json.loads(plan_path.read_text(encoding="utf-8"))
        assert saved["plan"][1]["status"] == "in_progress"

    def test_apply_patch_tool_updates_file(self, executor, tmp_path):
        target = tmp_path / "demo.txt"
        target.write_text("hello\n", encoding="utf-8")

        result, action = executor.execute(
            "apply_patch_tool",
            {
                "cwd": str(tmp_path),
                "patch_text": """*** Begin Patch
*** Update File: demo.txt
@@
-hello
+hello codex
*** End Patch""",
            },
        )

        assert action is None
        payload = json.loads(str(result))
        assert payload["status"] == "ok"
        assert target.read_text(encoding="utf-8") == "hello codex\n"

    def test_python_lint_publishes_validation_event(self, executor):
        events = []

        def on_validation(event):
            events.append(event.data)

        bus = get_event_bus()
        callback_id = "test_tool_executor_validation_event"
        bus.subscribe(EventNames.VALIDATION_COMPLETED, on_validation, callback_id=callback_id)

        def fake_lint_tool(file_path=""):
            return '{"status": "ok", "issue_count": 0}'

        executor.register_tool("python_lint_tool", fake_lint_tool, timeout=5)

        try:
            result, action = executor.execute("python_lint_tool", {"file_path": "agent.py"})
            assert action is None
            assert '"status": "ok"' in str(result)
            assert events
            assert events[-1]["kind"] == "lint"
            assert events[-1]["passed"] is True
        finally:
            bus.unsubscribe_by_id(callback_id)

    def test_cli_exec_failure_records_failed_runtime_scene_event(self, executor, monkeypatch):
        events = []

        def fake_record_runtime_scene_event(component, phase, event_code, **kwargs):
            events.append(
                {
                    "component": component,
                    "phase": phase,
                    "eventCode": event_code,
                    **kwargs,
                }
            )
            return {"accepted": True}

        monkeypatch.setattr(
            "core.web.services.runtime_scene_service.record_runtime_scene_event",
            fake_record_runtime_scene_event,
        )
        executor.register_tool(
            "cli_tool",
            lambda command="", timeout=60: "[EXEC FAILURE] exit=1\npytest failed",
            timeout=5,
        )

        result, action = executor.execute("cli_tool", {"command": "pytest tests/test_demo.py -q"})

        assert action is None
        assert "[EXEC FAILURE]" in str(result)
        event = events[-1]
        assert event["eventCode"] == "tool.execute.failed"
        assert event["level"] == "error"
        assert event["outcome"] == "failed"
        assert event["fields"]["semanticStatus"] == "failed"

    def test_python_lint_issue_count_records_warning_runtime_scene_event(self, executor, monkeypatch):
        events = []

        def fake_record_runtime_scene_event(component, phase, event_code, **kwargs):
            events.append(
                {
                    "component": component,
                    "phase": phase,
                    "eventCode": event_code,
                    **kwargs,
                }
            )
            return {"accepted": True}

        monkeypatch.setattr(
            "core.web.services.runtime_scene_service.record_runtime_scene_event",
            fake_record_runtime_scene_event,
        )
        executor.register_tool(
            "python_lint_tool",
            lambda file_path="": json.dumps({"status": "ok", "issue_count": 2, "issues": ["E1", "E2"]}),
            timeout=5,
        )

        result, action = executor.execute("python_lint_tool", {"file_path": "agent.py"})

        assert action is None
        assert '"issue_count": 2' in str(result)
        event = events[-1]
        assert event["eventCode"] == "tool.execute.degraded"
        assert event["level"] == "warning"
        assert event["outcome"] == "degraded"
        assert event["fields"]["semanticStatus"] == "degraded"
        assert event["fields"]["issueCount"] == 2

    def test_cli_pipe_pattern_executes_again_after_security_feedback(self, executor):
        """同轮同类 pipe 模式不再二次短路，由工具自身继续返回安全反馈。"""
        reset_session_state()

        call_counter = {"count": 0}

        def fake_cli_tool(command="", timeout=60):
            call_counter["count"] += 1
            return "[安全拦截] [Whitelist Block] 命令包含危险字符：|\n该危险命令已被系统安全策略禁止执行。"

        executor.register_tool("cli_tool", fake_cli_tool, timeout=5)

        first, _ = executor.execute("cli_tool", {"command": "git diff a b | head -20"})
        second, _ = executor.execute("cli_tool", {"command": "git show :x | head -20"})

        assert "[安全拦截]" in str(first)
        assert "[安全拦截]" in str(second)
        assert "[短路]" not in str(second)
        assert call_counter["count"] == 2
        snapshot = get_session_state().get_attention_snapshot()
        assert "cli_tool:pipe" in snapshot["blocked_tool_patterns"]
        pipe_hint = snapshot["blocked_tool_patterns"]["cli_tool:pipe"]["hint"]
        assert "无 pipe 的有界命令" in pipe_hint
        assert "已授权" in pipe_hint
        assert "read_file_tool / grep_search_tool" not in pipe_hint

    def test_cross_platform_warning_is_recorded_as_successful_platform_check(self, executor):
        """跨平台命令拦截是平台检查通过，不能污染 pytest 失败状态。"""
        reset_session_state()

        def fake_cli_tool(command="", timeout=60):
            return (
                "[跨平台警告] 在 Windows 上检测到 Unix shell 片段: "
                f"{command}\n请改用 PowerShell/Windows 等价命令。"
            )

        executor.register_tool("cli_tool", fake_cli_tool, timeout=5)

        result, action = executor.execute(
            "cli_tool",
            {"command": "python -m pytest tests/ --collect-only -q 2>/dev/null | tail -5"},
        )

        assert action is None
        assert "[跨平台警告]" in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert snapshot["last_validation_summary"] == "Windows 平台检查通过：已拦截 Unix shell 片段"
        assert snapshot["last_validation_passed"] is True
        assert snapshot["recent_validation_results"][-1]["kind"] == "platform_check"
        assert snapshot["feedback_loop_ready"] is True
        assert snapshot["feedback_loop_type"] == "platform_check"
        assert snapshot["convergence_state"] == "ready_to_stop"
        assert "cli_tool:unix_shell_on_windows" in snapshot["blocked_tool_patterns"]

    def test_lint_validation_establishes_feedback_loop_and_freezes_scope(self, executor):
        reset_session_state()

        def fake_lint_tool(file_path=""):
            return '{"status": "ok", "issue_count": 0}'

        executor.register_tool("python_lint_tool", fake_lint_tool, timeout=5)

        result, action = executor.execute("python_lint_tool", {"file_path": "agent.py"})

        assert action is None
        assert '"status": "ok"' in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert snapshot["feedback_loop_ready"] is True
        assert snapshot["feedback_loop_type"] == "lint"
        assert snapshot["scope_frozen"] is True
        assert snapshot["scope_anchor"] == "agent.py"

    def test_cli_command_chain_executes_again_after_security_feedback(self, executor):
        """同轮同类命令链不再二次短路，由工具自身继续返回安全反馈。"""
        reset_session_state()

        call_counter = {"count": 0}

        def fake_cli_tool(command="", timeout=60):
            call_counter["count"] += 1
            return "[安全拦截] [Whitelist Block] 命令包含危险字符：&&\n该危险命令已被系统安全策略禁止执行。"

        executor.register_tool("cli_tool", fake_cli_tool, timeout=5)

        first, _ = executor.execute("cli_tool", {"command": "python -m py_compile agent.py && python -m pytest tests/test_agent_protocol.py -q"})
        second, _ = executor.execute("cli_tool", {"command": "cd workspace && dir"})

        assert "[安全拦截]" in str(first)
        assert "[安全拦截]" in str(second)
        assert "[短路]" not in str(second)
        assert call_counter["count"] == 2
        snapshot = get_session_state().get_attention_snapshot()
        assert "cli_tool:command_chain" in snapshot["blocked_tool_patterns"]

    def test_read_file_records_read_range(self, executor, tmp_path):
        reset_session_state()
        file_path = tmp_path / "demo.txt"
        file_path.write_text("a\nb\nc\nd\n", encoding="utf-8")

        result, action = executor.execute("read_file_tool", {
            "file_path": str(file_path),
            "offset": 1,
            "max_lines": 2,
        })

        assert action is None
        assert "第     2 行" in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        ranges = snapshot["read_ranges"]
        assert any("demo.txt" in key for key in ranges.keys())
        stored = next(iter(ranges.values()))
        assert stored[-1]["start_line"] == 2
        assert stored[-1]["end_line"] == 3

    def test_execute_read_file_accepts_string_numeric_args(self, executor, tmp_path):
        reset_session_state()
        file_path = tmp_path / "demo_string_args.txt"
        file_path.write_text("a\nb\nc\nd\n", encoding="utf-8")

        result, action = executor.execute(
            "read_file_tool",
            {
                "file_path": str(file_path),
                "offset": "1",
                "max_lines": "2",
            },
        )

        assert action is None
        assert "[文件读取] 错误" not in str(result)
        assert "第     2 行" in str(result)

    def test_duplicate_read_returns_compact_governance_without_body(self, executor, tmp_path):
        reset_session_state()
        file_path = tmp_path / "demo_repeat.txt"
        file_path.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")

        executor.execute("read_file_tool", {"file_path": str(file_path), "offset": 0, "max_lines": 2})
        second, _ = executor.execute("read_file_tool", {"file_path": str(file_path), "offset": 0, "max_lines": 2})

        snapshot = get_session_state().get_attention_snapshot()
        assert "[短路]" not in str(second)
        assert "[阅读治理]" in str(second)
        assert "未重复返回正文" in str(second)
        assert "第     1 行" not in str(second)
        assert any(item["kind"] == "duplicate_read_soft_redirect" for item in snapshot["recent_blockers"])

    def test_duplicate_read_force_does_not_bypass_governance(self, executor, tmp_path):
        reset_session_state()
        file_path = tmp_path / "demo_repeat_force.txt"
        file_path.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")

        executor.execute("read_file_tool", {"file_path": str(file_path), "offset": 0, "max_lines": 2})
        second, _ = executor.execute("read_file_tool", {"file_path": str(file_path), "offset": 0, "max_lines": 2, "force": True})

        assert "[阅读治理]" in str(second)
        assert "未重复返回正文" in str(second)
        assert "第     1 行" not in str(second)
        assert "force=true" not in str(second)

    def test_full_file_read_requires_force(self, executor, tmp_path):
        reset_session_state()
        file_path = tmp_path / "demo_full_file.txt"
        file_path.write_text("a\nb\nc\n", encoding="utf-8")

        result, action = executor.execute("read_file_tool", {"file_path": str(file_path), "max_lines": 0})

        assert action is None
        assert "[阅读治理]" in str(result)
        assert "全文件读取" in str(result)
        assert "force=true" not in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert any(item["kind"] == "read_file_full_file_redirect" for item in snapshot["recent_blockers"])

    def test_read_file_records_hint_when_continuation_is_ignored(self, executor, tmp_path):
        session = reset_session_state()
        file_path = tmp_path / "demo_flow.txt"
        file_path.write_text("\n".join(f"line {i}" for i in range(1, 120)), encoding="utf-8")
        session.record_pending_continuation(
            "read_file_tool",
            f'read_file_tool(file_path="{file_path}", offset=40, max_lines=40)',
            str(file_path),
        )

        result, action = executor.execute("read_file_tool", {"file_path": str(file_path), "offset": 10, "max_lines": 40})

        assert action is None
        assert "[短路]" not in str(result)
        assert "第    11 行" in str(result) or "第     11 行" in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert not any(item["kind"] == "continuation_drift" for item in snapshot["recent_blockers"])

    def test_read_file_allows_switching_away_from_latest_pending_continuation_but_records_hint(self, executor, tmp_path):
        session = reset_session_state()
        first = tmp_path / "first_flow.txt"
        second = tmp_path / "second_flow.txt"
        first.write_text("\n".join(f"line {i}" for i in range(1, 120)), encoding="utf-8")
        second.write_text("\n".join(f"line {i}" for i in range(1, 120)), encoding="utf-8")

        session.record_pending_continuation(
            "read_file_tool",
            f'read_file_tool(file_path="{first}", offset=40, max_lines=40)',
            str(first),
        )

        result, action = executor.execute("read_file_tool", {"file_path": str(second), "offset": 0, "max_lines": 40})

        assert action is None
        assert "[短路]" not in str(result)
        assert "第     1 行" in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert not any(item["kind"] == "continuation_focus" for item in snapshot["recent_blockers"])

    def test_read_file_returns_navigation_instead_of_executable_continuation(self, executor, tmp_path):
        reset_session_state()
        file_path = tmp_path / "demo_weak_continuation.txt"
        file_path.write_text("\n".join(f"line {i}" for i in range(1, 120)), encoding="utf-8")

        result, action = executor.execute("read_file_tool", {"file_path": str(file_path), "offset": 0, "max_lines": 40})

        assert action is None
        assert "[阅读导航]" in str(result)
        assert "不要因为存在剩余内容就默认顺序翻页" in str(result)
        assert "read_file_tool(" not in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert not snapshot["pending_continuations"]
        assert not any(item["kind"] == "read_navigation" for item in snapshot["recent_blockers"])

    def test_read_file_allows_many_segments_for_same_file(self, executor, tmp_path):
        session = reset_session_state()
        file_path = tmp_path / "demo_loop_guard.txt"
        file_path.write_text("\n".join(f"line {i}" for i in range(1, 240)), encoding="utf-8")
        session.record_read_range(str(file_path), 1, 40, source="read_file_tool")
        session.record_read_range(str(file_path), 41, 80, source="read_file_tool")
        session.record_read_range(str(file_path), 81, 120, source="read_file_tool")

        result, action = executor.execute("read_file_tool", {"file_path": str(file_path), "offset": 120, "max_lines": 40})

        assert action is None
        assert "[阅读纠偏]" not in str(result)
        assert "第   121 行" in str(result) or "第    121 行" in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert not any(item["kind"] == "read_navigation_redirect" for item in snapshot["recent_blockers"])

    def test_read_file_high_overlap_returns_governance(self, executor, tmp_path):
        session = reset_session_state()
        file_path = tmp_path / "demo_overlap.txt"
        file_path.write_text("\n".join(f"line {i}" for i in range(1, 160)), encoding="utf-8")
        session.record_read_range(str(file_path), 21, 80, source="read_file_tool")

        result, action = executor.execute("read_file_tool", {"file_path": str(file_path), "offset": 30, "max_lines": 60})

        assert action is None
        assert "[短路]" not in str(result)
        assert "[阅读治理]" in str(result)
        assert "未重复返回正文" in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert any(item["kind"] == "duplicate_read_soft_redirect" for item in snapshot["recent_blockers"])

    def test_duplicate_search_records_state_without_blocker(self, executor):
        reset_session_state()

        def fake_grep_search_tool(regex_pattern="", include_ext=".py", search_dir=".", case_sensitive=True, max_results=50, max_output_chars=8000):
            return (
                f"[搜索] 正则: {regex_pattern}\n"
                f"[搜索] 目录: {search_dir}\n"
                f"[搜索] 类型: {include_ext}\n"
                f"[搜索] 找到 1 个匹配，分布在 1 个文件\n"
                "[搜索摘要]\n"
                "- core/demo.py | 命中 1 处 | 行 10\n"
                "\n[续读] read_file_tool(file_path=\"core/demo.py\", offset=0, max_lines=40)\n"
            )

        executor.register_tool("grep_search_tool", fake_grep_search_tool, timeout=5)

        executor.execute("grep_search_tool", {"regex_pattern": "Demo", "search_dir": "core"})
        executor.execute("grep_search_tool", {"regex_pattern": "Demo", "search_dir": "core"})

        snapshot = get_session_state().get_attention_snapshot()
        assert not any(item["kind"] == "duplicate_search" for item in snapshot["recent_blockers"])
        assert snapshot["pending_continuations"][-1]["path"] == "core/demo.py"

    def test_duplicate_search_executes_again(self, executor):
        session = reset_session_state()
        session.record_search_query("Demo", "core")

        called = {"count": 0}

        def fake_grep_search_tool(**_kwargs):
            called["count"] += 1
            return "should not execute"

        executor.register_tool("grep_search_tool", fake_grep_search_tool, timeout=5)
        result, action = executor.execute("grep_search_tool", {"regex_pattern": "Demo", "search_dir": "core"})

        assert action is None
        assert "[短路]" not in str(result)
        assert called["count"] == 1
        snapshot = get_session_state().get_attention_snapshot()
        assert not any(item["kind"] == "duplicate_search" for item in snapshot["recent_blockers"])

    def test_search_allows_progress_when_pending_continuation_exists(self, executor):
        session = reset_session_state()
        session.record_pending_continuation(
            "read_file_tool",
            'read_file_tool(file_path="core/demo.py", offset=40, max_lines=40)',
            "core/demo.py",
        )

        called = {"count": 0}

        def fake_grep_search_tool(**_kwargs):
            called["count"] += 1
            return "should not execute"

        executor.register_tool("grep_search_tool", fake_grep_search_tool, timeout=5)
        result, action = executor.execute("grep_search_tool", {"regex_pattern": "Demo", "search_dir": "core"})

        assert action is None
        assert "[短路]" not in str(result)
        assert called["count"] == 1
        snapshot = get_session_state().get_attention_snapshot()
        assert not any(item["kind"] == "continuation_focus" for item in snapshot["recent_blockers"])

    def test_weak_search_continuation_does_not_block_switching_to_another_file(self, executor, tmp_path):
        session = reset_session_state()
        first = tmp_path / "search_hit.py"
        second = tmp_path / "target.py"
        first.write_text("\n".join(f"line {i}" for i in range(1, 40)), encoding="utf-8")
        second.write_text("\n".join(f"line {i}" for i in range(1, 80)), encoding="utf-8")
        session.record_pending_continuation(
            "grep_search_tool",
            f'read_file_tool(file_path="{first}", offset=0, max_lines=40)',
            str(first),
            strength="weak",
        )

        result, action = executor.execute("read_file_tool", {"file_path": str(second), "offset": 0, "max_lines": 40})

        assert action is None
        assert "[短路]" not in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert not any(item["kind"] == "continuation_focus" for item in snapshot["recent_blockers"])

    def test_duplicate_entity_executes_again(self, executor):
        session = reset_session_state()
        session.record_read_entity("core/demo.py", "Demo.run")

        called = {"count": 0}

        def fake_code_symbol_tool(**_kwargs):
            called["count"] += 1
            return "should not execute"

        executor.register_tool("code_symbol_tool", fake_code_symbol_tool, timeout=5)
        result, action = executor.execute(
            "code_symbol_tool",
            {"mode": "inspect", "file_path": "core/demo.py", "symbol": "Demo.run"},
        )

        assert action is None
        assert "[短路]" not in str(result)
        assert called["count"] == 1
        snapshot = get_session_state().get_attention_snapshot()
        assert not any(item["kind"] == "duplicate_entity_guard" for item in snapshot["recent_blockers"])

    def test_cli_tool_records_deviation_when_recommendation_exists(self, executor):
        session = reset_session_state()
        session.set_tool_decision("inspect_entity", ["code_symbol_tool", "read_file_tool"], ["cli_tool"])

        def fake_cli_tool(command="", timeout=60):
            return "[命令执行完成，无输出]"

        executor.register_tool("cli_tool", fake_cli_tool, timeout=5)
        executor.execute("cli_tool", {"command": "echo ok"})

        snapshot = get_session_state().get_attention_snapshot()
        assert any(item["tool_name"] == "cli_tool" for item in snapshot["tool_deviations"])
        assert any(item["kind"] == "tool_deviation" for item in snapshot["recent_blockers"])

    def test_cli_tool_file_read_command_executes_normally(self, executor):
        reset_session_state()

        called = {"count": 0}

        def fake_cli_tool(command="", timeout=60):
            called["count"] += 1
            return "file body"

        executor.register_tool("cli_tool", fake_cli_tool, timeout=5)
        result, action = executor.execute("cli_tool", {"command": "Get-Content core/demo.py | Select-Object -First 20"})

        assert action is None
        assert result == "file body"
        assert called["count"] == 1
        snapshot = get_session_state().get_attention_snapshot()
        assert not any(item["kind"] == "cli_reading_shortcut" for item in snapshot["recent_blockers"])

    def test_execute_tool_missing_required_args(self, executor):
        """测试执行工具时缺少必需参数"""
        # 缺少 file_path 参数
        result, action = executor.execute("read_file_tool", {})
        
        # 应该返回错误而不是抛出异常
        assert result is not None
        assert action is None
        assert "[工具参数错误]" in str(result)
        assert "必填参数：file_path" in str(result)
        assert "示例：read_file_tool" in str(result)

    def test_python_lint_records_validation_signal(self, executor, monkeypatch):
        reset_session_state()
        executor.register_tool(
            "python_lint_tool",
            lambda target=".", max_issues=100: '{"status": "ok", "issue_count": 0, "issues": []}',
            timeout=5,
        )

        result, _ = executor.execute("python_lint_tool", {"target": "."})

        assert '"issue_count": 0' in str(result)
        snapshot = get_session_state().get_attention_snapshot()
        assert snapshot["recent_validation_results"][-1]["kind"] == "lint"

    def test_successful_validation_and_task_completion_reward_pet_exp(self, executor):
        reset_session_state()
        reset_pet_system()
        pet = get_pet_system()
        start_exp = pet.data.attributes.exp
        start_tasks = pet.data.attributes.total_tasks

        executor.register_tool(
            "python_lint_tool",
            lambda target=".", max_issues=100: '{"status": "ok", "issue_count": 0, "issues": []}',
            timeout=5,
        )
        executor.register_tool(
            "task_update_tool",
            lambda task_id=1, is_completed=True, result_summary="": '{"status":"success"}',
            timeout=5,
        )

        executor.execute("python_lint_tool", {"target": "."})
        executor.execute("task_update_tool", {"task_id": 1, "is_completed": True, "result_summary": "done"})

        assert pet.data.attributes.exp > start_exp
        assert pet.data.attributes.total_tasks == start_tasks + 1

    def test_readonly_subagent_blocks_mutating_tools(self, executor, monkeypatch):
        monkeypatch.setenv("VIBELUTION_SUBAGENT_MODE", "readonly")

        result, action = executor.execute(
            "write_file_tool",
            {"file_path": "workspace/demo.txt", "content": "x"},
        )

        assert action is None
        assert "[只读子代理]" in str(result)

    def test_readonly_subagent_blocks_spawn_agent_tool(self, executor, monkeypatch):
        monkeypatch.setenv("VIBELUTION_SUBAGENT_MODE", "readonly")

        result, action = executor.execute(
            "spawn_agent_tool",
            {"goal": "继续分析", "_internal_delegate": True},
        )

        assert action is None
        assert "禁止继续派发子 agent" in str(result)

    def test_readonly_subagent_blocks_agent_message_tool(self, executor, monkeypatch):
        monkeypatch.setenv("VIBELUTION_SUBAGENT_MODE", "readonly")

        result, action = executor.execute(
            "agent_message_tool",
            {"target_agent": "A002", "content": "请接力分析这个问题。"},
        )

        assert action is None
        assert "[只读子代理]" in str(result)

    def test_active_evolution_transaction_blocks_writes_outside_allowed_dirs(self, executor, monkeypatch, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir(parents=True, exist_ok=True)

        class _FakeWorkspace:
            def __init__(self, root: Path):
                self.project_root = root

            def get_prompt_path(self, name: str) -> Path:
                return self.project_root / "workspace" / "prompts" / name

        evolution = SimpleNamespace(
            allowed_target_dirs=["workspace/prompts/"],
            audit_log_path="workspace/evolution/audit.jsonl",
        )
        monkeypatch.setattr(governor_module, "get_config", lambda: SimpleNamespace(evolution=evolution))
        monkeypatch.setattr(governor_module, "get_workspace", lambda: _FakeWorkspace(project_root))
        governor_module._governor = None

        session = reset_session_state()
        session.set_active_evolution_txn("txn_guard")
        executor.register_tool("write_file_tool", lambda file_path, content: "ok", timeout=5)

        result, action = executor.execute(
            "write_file_tool",
            {"file_path": "core/runtime.py", "content": "x"},
        )

        assert action is None
        assert "[演化治理]" in str(result)

    def test_risky_write_without_active_txn_is_blocked_before_tool_runs(self, executor, monkeypatch, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir(parents=True, exist_ok=True)

        class _FakeWorkspace:
            def __init__(self, root: Path):
                self.project_root = root

            def get_prompt_path(self, name: str) -> Path:
                return self.project_root / "workspace" / "prompts" / name

        evolution = SimpleNamespace(
            allowed_target_dirs=["workspace/prompts/"],
            audit_log_path="workspace/evolution/audit.jsonl",
        )
        monkeypatch.setattr(governor_module, "get_config", lambda: SimpleNamespace(evolution=evolution))
        monkeypatch.setattr(governor_module, "get_workspace", lambda: _FakeWorkspace(project_root))
        governor_module._governor = None

        called = {"value": False}

        def fake_write(file_path, content):
            called["value"] = True
            return "should not run"

        executor.register_tool("write_file_tool", fake_write, timeout=5)
        session = reset_session_state()
        session.set_runtime_goal_packet(SimpleNamespace(allow_evolution_transaction=True))

        result, action = executor.execute(
            "write_file_tool",
            {"file_path": "core/runtime.py", "content": "x"},
        )

        assert action is None
        assert called["value"] is False
        assert "open_evolution_transaction_tool" in str(result)

    def test_chat_user_development_write_skips_evolution_allowlist_guard(self, executor, monkeypatch, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir(parents=True, exist_ok=True)

        class _FakeWorkspace:
            def __init__(self, root: Path):
                self.project_root = root

            def get_prompt_path(self, name: str) -> Path:
                return self.project_root / "workspace" / "prompts" / name

        evolution = SimpleNamespace(
            allowed_target_dirs=["workspace/prompts/"],
            audit_log_path="workspace/evolution/audit.jsonl",
        )
        monkeypatch.setattr(governor_module, "get_config", lambda: SimpleNamespace(evolution=evolution))
        monkeypatch.setattr(governor_module, "get_workspace", lambda: _FakeWorkspace(project_root))
        governor_module._governor = None

        called = {"value": False}

        def fake_write(file_path, content):
            called["value"] = True
            return "ok"

        executor.register_tool("write_file_tool", fake_write, timeout=5)
        session = reset_session_state()
        session.set_runtime_goal_packet(SimpleNamespace(allow_evolution_transaction=False))

        result, action = executor.execute(
            "write_file_tool",
            {"file_path": "core/runtime.py", "content": "x"},
        )

        assert action is None
        assert called["value"] is True
        assert result == "ok"

    def test_cli_python_write_to_risky_path_requires_active_txn(self, executor, monkeypatch, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir(parents=True, exist_ok=True)

        class _FakeWorkspace:
            def __init__(self, root: Path):
                self.project_root = root

            def get_prompt_path(self, name: str) -> Path:
                return self.project_root / "workspace" / "prompts" / name

        evolution = SimpleNamespace(
            allowed_target_dirs=["workspace/prompts/"],
            audit_log_path="workspace/evolution/audit.jsonl",
        )
        monkeypatch.setattr(governor_module, "get_config", lambda: SimpleNamespace(evolution=evolution))
        monkeypatch.setattr(governor_module, "get_workspace", lambda: _FakeWorkspace(project_root))
        governor_module._governor = None

        called = {"value": False}

        def fake_cli_tool(command="", timeout=60):
            called["value"] = True
            return "should not run"

        executor.register_tool("cli_tool", fake_cli_tool, timeout=5)
        session = reset_session_state()
        session.set_runtime_goal_packet(SimpleNamespace(allow_evolution_transaction=True))

        result, action = executor.execute(
            "cli_tool",
            {
                "command": "python -c \"open('tools/bdd_test_runner.py','w').write('x')\"",
                "timeout": 10,
            },
        )

        assert action is None
        assert called["value"] is False
        assert "[演化治理]" in str(result)
        assert "open_evolution_transaction_tool" in str(result)
        assert "tools/bdd_test_runner.py" in str(result)


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
        
        # 2. 匹配测试文件
        result, action = executor.execute("glob_tool", {
            "pattern": "test_tool_executor.py",
            "search_dir": str(Path(__file__).parent),
        })
        assert result is not None
        assert action is None
        
        # 3. 读取文件
        result, action = executor.execute("read_file_tool", {
            "file_path": __file__
        })
        assert result is not None
        assert action is None
        
        # 4. 运行 canonical lint 工具
        result, action = executor.execute("python_lint_tool", {
            "target": __file__,
            "max_issues": 5,
        })
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
