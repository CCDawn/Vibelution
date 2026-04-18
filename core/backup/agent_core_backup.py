#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import time
import logging
import traceback
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable

# Windows 控制台编码修复
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# 导入核心模块
# ============================================================================

from config import Config, get_config

# 导入日志模块
from core.logger import (
    DebugLogger,
    debug as _debug_logger,
)
from core.unified_logger import logger

# 导入事件总线
from core.event_bus import EventBus, get_event_bus, EventNames, Event

# 导入状态管理
from core.state import AgentState, get_state_manager

# LangChain 核心组件
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_openai import ChatOpenAI

# 导入工具
from tools import Key_Tools
from tools.token_manager import EnhancedTokenCompressor, estimate_messages_tokens
from tools.memory_tools import (
    get_generation_tool, get_core_context_tool, get_current_goal_tool,
    archive_generation_history, advance_generation,
    _load_memory, clear_generation_task,
    read_dynamic_prompt_tool, update_generation_task_tool, add_insight_to_dynamic_tool,
)
from tools.rebirth_tools import trigger_self_restart_tool

# 导入 CLI UI
from core.cli_ui import get_ui, ui_error

# 导入提示词管理器
from core.capabilities.prompt_manager import build_system_prompt


# ============================================================================
# 工具执行器 - 通过事件总线解耦
# ============================================================================

class ToolExecutor:
    """
    工具执行器

    负责：
    - 管理工具函数映射
    - 通过事件总线解耦工具执行
    - 提供工具超时和重试机制
    """

    def __init__(self):
        self._tool_map: Dict[str, Callable] = {}
        self._timeout_map: Dict[str, int] = {}
        self._retryable_tools: set = set()
        self._event_bus = get_event_bus()
        self._register_default_tools()

    def _register_default_tools(self):
        """注册默认工具映射"""
        from tools import (
            # Shell 工具
            read_file_tool, list_directory_tool, edit_file_tool, create_file_tool,
            check_python_syntax_tool, extract_symbols_tool, backup_project_tool,
            cleanup_test_files_tool, execute_shell_command_tool, run_powershell_tool,
            run_batch_tool, self_test_tool, get_agent_status_tool,
            # 记忆工具
            read_memory_tool, commit_compressed_memory_tool, get_generation_tool,
            get_current_goal_tool, get_core_context_tool, read_generation_archive_tool,
            list_archives_tool, read_dynamic_prompt_tool, update_generation_task_tool,
            add_insight_to_dynamic_tool, record_codebase_insight_tool, get_global_codebase_map_tool,
            # 搜索工具
            grep_search_tool, find_function_calls_tool, find_definitions_tool,
            search_imports_tool, search_and_read_tool,
            # 代码分析工具
            apply_diff_edit_tool, validate_diff_format_tool, preview_diff_tool,
            get_code_entity_tool, list_file_entities_tool, get_file_entities_tool,
            # 任务工具
            set_plan_tool, tick_subtask_tool, modify_task_tool,
            add_task_tool, remove_task_tool, get_task_status_tool, check_restart_block_tool,
            # 重生工具
            trigger_self_restart_tool, enter_hibernation_tool,
            # Token 管理工具
            EnhancedTokenCompressor, truncate_tool_result_tool,
            estimate_tokens_precise_tool, estimate_messages_tokens_tool,
            MessagePriority, format_compression_report_tool,
        )

        # 构建工具映射
        self._tool_map = {
            # Shell 工具
            "read_file": read_file_tool,
            "list_directory": list_directory_tool,
            "edit_file": edit_file_tool,
            "create_file": create_file_tool,
            "check_python_syntax": check_python_syntax_tool,
            "extract_symbols": extract_symbols_tool,
            "backup_project": backup_project_tool,
            "cleanup_test_files": cleanup_test_files_tool,
            "execute_shell_command": execute_shell_command_tool,
            "run_powershell": run_powershell_tool,
            "run_batch": run_batch_tool,
            "self_test": self_test_tool,
            "get_agent_status": get_agent_status_tool,
            # 记忆工具
            "read_memory": read_memory_tool,
            "commit_compressed_memory": commit_compressed_memory_tool,
            "get_generation": get_generation_tool,
            "get_current_goal": get_current_goal_tool,
            "get_core_context": get_core_context_tool,
            "read_generation_archive": read_generation_archive_tool,
            "list_archives": list_archives_tool,
            "read_dynamic_prompt": read_dynamic_prompt_tool,
            "update_generation_task": update_generation_task_tool,
            "add_insight_to_dynamic": add_insight_to_dynamic_tool,
            "record_codebase_insight": record_codebase_insight_tool,
            "get_global_codebase_map": get_global_codebase_map_tool,
            # 搜索工具
            "grep_search": grep_search_tool,
            "find_function_calls": find_function_calls_tool,
            "find_definitions": find_definitions_tool,
            "search_imports": search_imports_tool,
            "search_and_read": search_and_read_tool,
            # 代码分析工具
            "apply_diff_edit": apply_diff_edit_tool,
            "validate_diff_format": validate_diff_format_tool,
            "preview_diff": preview_diff_tool,
            "get_code_entity": get_code_entity_tool,
            "list_file_entities": list_file_entities_tool,
            "get_file_entities": get_file_entities_tool,
            # 任务工具
            "set_plan": set_plan_tool,
            "tick_subtask": tick_subtask_tool,
            "modify_task": modify_task_tool,
            "add_task": add_task_tool,
            "remove_task": remove_task_tool,
            "get_task_status": get_task_status_tool,
            "check_restart_block": check_restart_block_tool,
            # 重生工具
            "trigger_self_restart": trigger_self_restart_tool,
            "enter_hibernation": enter_hibernation_tool,
        }

        # 默认超时配置
        self._timeout_map = {
            "execute_shell_command": 60,
            "run_powershell": 60,
            "run_batch": 60,
            "self_test": 30,
            "check_python_syntax": 10,
            "grep_search": 30,
            "find_function_calls": 30,
            "find_definitions": 30,
            "search_and_read": 30,
            "backup_project": 60,
        }
        self._retryable_tools = {"grep_search", "search_and_read"}

    def register_tool(self, name: str, func: Callable, timeout: int = 30):
        """注册自定义工具"""
        self._tool_map[name] = func
        self._timeout_map[name] = timeout

    def execute(self, tool_name: str, tool_args: dict) -> tuple:
        """
        执行工具

        Returns:
            (result, action): 元组
        """
        from concurrent.futures import ThreadPoolExecutor, TimeoutError

        # 发布工具开始事件
        self._event_bus.publish(EventNames.TOOL_START, {
            "name": tool_name,
            "args": tool_args,
        })

        if tool_name not in self._tool_map:
            return (f"[错误] 未知工具 {tool_name}", None)

        func = self._tool_map[tool_name]
        timeout = self._timeout_map.get(tool_name, 30)

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, **tool_args)
                result = future.result(timeout=timeout)

            # 发布工具成功事件
            self._event_bus.publish(EventNames.TOOL_SUCCESS, {
                "name": tool_name,
                "result": str(result)[:200],
            })

            return (result, None)

        except TimeoutError:
            error_msg = f"[超时] {tool_name} 执行超时 ({timeout}秒)"
            self._event_bus.publish(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": error_msg,
            })
            return (error_msg, None)

        except Exception as e:
            error_msg = f"[错误] {type(e).__name__}: {e}"
            self._event_bus.publish(EventNames.TOOL_ERROR, {
                "name": tool_name,
                "error": error_msg,
            })
            return (error_msg, None)


# 全局工具执行器
_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """获取工具执行器单例"""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor


# ============================================================================
# Self-Evolving Agent 主类
# ============================================================================

class SelfEvolvingAgent:
    """
    自我进化 Agent 主类

    基于 LangChain 框架构建，使用 ReAct 风格的 Agent 架构。
    支持定时苏醒，主动思考优化方向。
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        """初始化 Agent 实例"""
        self.config = config or get_config()
        self.name = self.config.agent.name
        self.logger = logging.getLogger(f"Agent.{self.name}")

        # 获取 API Key
        self.api_key = self.config.get_api_key()
        if not self.api_key:
            raise ValueError(
                "未设置 API Key。\n"
                "请在 config.toml 中配置: [llm] api_key = 'your-api-key'"
            )

        # 创建主要工具
        self.key_tools = Key_Tools.create_key_tools()
        self.key_tool_maps = {tool.name for tool in self.key_tools}

        # 创建 LLM
        llm_kwargs = {
            "model": self.config.llm.model_name,
            "temperature": self.config.llm.temperature,
            "api_key": self.api_key,
        }
        if self.config.llm.api_base:
            llm_kwargs["base_url"] = self.config.llm.api_base
        llm_kwargs["timeout"] = getattr(self.config.llm, 'api_timeout', 120)
        llm_kwargs["request_timeout"] = llm_kwargs["timeout"]

        self.llm = ChatOpenAI(**llm_kwargs)
        self.model_name = self.config.llm.model_name

        # 绑定工具到 LLM
        self.llm_with_tools = self.llm.bind_tools(self.key_tools)

        # 创建压缩用 LLM
        compression_llm_kwargs = {
            "model": self.config.context_compression.compression_model,
            "temperature": 0.3,
            "api_key": self.api_key,
        }
        if self.config.llm.api_base:
            compression_llm_kwargs["base_url"] = self.config.llm.api_base
        compression_llm_kwargs["timeout"] = getattr(self.config.llm, 'api_timeout', 120)
        compression_llm_kwargs["request_timeout"] = compression_llm_kwargs["timeout"]
        self.compression_llm = ChatOpenAI(**compression_llm_kwargs)

        # Token 压缩器
        import os
        summary_prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "workspace", "prompts", "COMPRESS_SUMMARY.md"
        )
        self.token_compressor = EnhancedTokenCompressor(
            token_budget=self.config.context_compression.max_token_limit,
            max_history_pairs=self.config.context_compression.keep_recent_steps,
            compression_llm=self.compression_llm,
            enable_preemptive=True,
            summary_prompt_path=summary_prompt_path,
        )

        # 全局状态
        self.global_recent_actions: List[str] = []
        self.global_consecutive_count = 0
        self._self_modified = False
        self.start_time = datetime.now()

        # 工作区域
        workspace_dir = getattr(self.config.agent, 'workspace', 'workspace')
        project_root = os.path.dirname(os.path.abspath(__file__))
        self.workspace_path = os.path.join(project_root, workspace_dir)
        os.makedirs(self.workspace_path, exist_ok=True)

        # 初始化组件
        self.state_manager = get_state_manager()
        self.event_bus = get_event_bus()
        self.tool_executor = get_tool_executor()
        self._system_prompt_written = False
        self._setup_event_handlers()

    def _setup_event_handlers(self):
        """设置事件处理器"""
        # 可以在这里注册额外的事件处理器
        pass

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        # 始终让 Agent 自主生成任务
        base_prompt = build_system_prompt(
            generation=get_generation_tool(),
            total_generations=_get_total_generations(),
            core_context=get_core_context(),
        )
        
        return base_prompt

    def think_and_act(self, user_prompt: str = None) -> bool:
        """
        苏醒时执行一次思考和行动

        流程：
        1. 构建系统提示词
        2. 调用 LLM 进行推理
        3. 解析并执行工具调用
        4. 返回结果给 LLM 继续推理
        5. 直到 Agent 认为任务完成

        Returns:
            True: 继续运行, False: 触发重启, "hibernated": 休眠后继续
        """
        messages = [SystemMessage(content=self._build_system_prompt())]

        # 自主进化模式：自动生成任务提示
        autonomous_user_prompt = (
            "【自主进化】你是完全自主的进化体，请根据 SOUL.md 的使命指示，"
            "**要求**：每次仅生成一个主要任务。\n\n"
            "首先调用 set_generation_task(task=\"...\") 设定你的任务\n"
            "然后调用 set_plan(task=\"...\") 制定计划并执行\n"
            "每完成一个计划调用 tick_subtask(task=\"...\") 打勾并记录结论摘要\n"
            "所有计划完成后调用 commit_compressed_memory(task=\"...\") 保存记忆\n"
            "最后调用 trigger_self_restart_tool(task=\"...\") 结束本轮\n"
        )

        # 获取轮次编号
        if user_prompt:
            logger.log_user_input(user_prompt)
            current_turn = logger._turn_count
        else:
            current_turn = logger._turn_count + 1
            # 无外部输入时使用自主进化提示
            user_prompt = autonomous_user_prompt

        # 首次对话写入 System Prompt
        if not self._system_prompt_written:
            logger.write_system_prompt(self._build_system_prompt())
            self._system_prompt_written = True

        messages.append(HumanMessage(content=user_prompt))
        logger.start_turn(current_turn)
        logger.log_user_input(user_prompt)

        logger.log_llm_request(messages, model=self.model_name)
        max_iterations = self.config.agent.max_iterations

        try:
            for iteration in range(1, max_iterations + 1):
                # 自动 Token 检查与压缩
                messages = self._check_and_compress(messages, iteration)

                # 第一次循环打印会话开始
                if iteration == 1:
                    _debug_logger.session_start(self.model_name, get_generation_tool())

                # 调用 LLM
                response = self._invoke_llm(messages)
                if response is None:
                    continue

                messages.append(response)

                # 记录 LLM 响应
                logger.log_llm_response(response.content or "")

                # Token 使用
                if hasattr(response, 'usage_metadata') and response.usage_metadata:
                    usage = response.usage_metadata
                    _debug_logger.debug(
                        f"Token: {usage.get('input_tokens', 0)} + {usage.get('output_tokens', 0)}",
                        tag="LLM"
                    )

                # 解析工具调用和思考内容
                tool_calls, thinking_content = self._parse_tool_calls(response)

                # 显示思考过程
                if thinking_content:
                    _debug_logger.llm_thinking(thinking_content)
                    logger.log_llm_intent("thinking", thinking_content[:300])

                # 无工具调用 = 结束
                if not tool_calls:
                    if response.content:
                        _debug_logger.llm_response(response.content, "LLM 最终回复")
                        logger.log_llm_intent("final_response", response.content[:300])
                    return True

                # 执行工具
                for tool_call in tool_calls:
                    result, action = self._execute_tool(tool_call, messages)
                    self._handle_tool_result(tool_call, result, action, messages)

            _debug_logger.turn_end(current_turn, tool_count=len(tool_calls) if tool_calls else 0)
            return True

        except Exception as e:
            _debug_logger.error(f"主循环异常: {type(e).__name__}: {e}", exc_info=True)
            return True

    def _invoke_llm(self, messages: list) -> Optional[Any]:
        """调用 LLM（带超时）"""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

        def invoke():
            return self.llm_with_tools.invoke(messages)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(invoke)
            try:
                llm_timeout = getattr(self.config.llm, 'api_timeout', 300)
                return future.result(timeout=llm_timeout)
            except FuturesTimeoutError:
                _debug_logger.error(f"LLM 调用超时 ({llm_timeout}秒)", tag="LLM")
                logger.log_error("llm_timeout", f"LLM 调用超时 ({llm_timeout}秒)")
                return None
            except Exception as e:
                _debug_logger.error(f"LLM 调用异常: {type(e).__name__}: {e}", tag="LLM")
                logger.log_error("llm_error", f"{type(e).__name__}: {e}")
                return None

    def _parse_tool_calls(self, response: AIMessage) -> tuple[List[Dict], str]:
        """
        解析 LLM 响应中的工具调用和思考内容

        Returns:
            (tool_calls, thinking_content)
        """
        import re
        import json
        import uuid

        tool_calls = getattr(response, 'tool_calls', None) or []
        thinking_content = ""

        # 解析 <thinking> 标签内容
        if response.content:
            thinking_match = re.search(
                r'<thinking>\s*([\s\S]*?)\s*</thinking>',
                response.content
            )
            if thinking_match:
                thinking_content = thinking_match.group(1).strip()

        # 如果没有结构化的 tool_calls，尝试从文本内容中解析
        if not tool_calls and response.content:
            text_tool_calls = re.findall(
                r'<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>',
                response.content
            )

            if text_tool_calls:
                for tc_json in text_tool_calls:
                    try:
                        tc = json.loads(tc_json)
                        # 统一参数格式：同时支持 args 和 arguments
                        if 'arguments' in tc and 'args' not in tc:
                            tc['args'] = tc.pop('arguments')
                        if 'args' not in tc:
                            tc['args'] = {}
                        if 'id' not in tc:
                            tc['id'] = f"call_{uuid.uuid4().hex[:8]}"
                        tool_calls.append(tc)
                    except json.JSONDecodeError:
                        pass

        return tool_calls, thinking_content

    def _check_and_compress(self, messages: list, iteration: int) -> list:
        """检查 Token 预算并在必要时压缩"""
        current_tokens = estimate_messages_tokens(messages)
        max_budget = self.config.context_compression.max_token_limit
        preemptive_threshold = int(max_budget * 0.6)
        forced_threshold = int(max_budget * 0.8)

        if current_tokens > forced_threshold:
            _debug_logger.warning(f"[压缩] Token 过高 ({current_tokens}/{max_budget})，自动压缩", tag="TOKEN")
            messages = self._compress_context(messages)
        elif current_tokens > preemptive_threshold and iteration > 1:
            _debug_logger.info(f"[预压缩] Token 接近阈值 ({current_tokens}/{max_budget})，提前压缩", tag="TOKEN")
            messages = self._compress_context(messages)

        return messages

    def _compress_context(self, messages: list) -> list:
        """压缩对话上下文"""
        old_tokens = estimate_messages_tokens(messages)
        compressed, _ = self.token_compressor.compress(
            messages,
            max_chars=self.config.context_compression.summary_max_chars,
        )
        new_tokens = estimate_messages_tokens(compressed)
        self.logger.info(f"[Token压缩] {old_tokens} -> {new_tokens}")
        logger.log_compression(old_tokens, new_tokens, old_tokens - new_tokens)
        return compressed

    def _execute_tool(self, tool_call: Dict, messages: list) -> tuple:
        """执行工具调用"""
        tool_name = tool_call.get('name', 'unknown')
        # 同时支持 args 和 arguments
        tool_args = tool_call.get('args') or tool_call.get('arguments') or {}

        _debug_logger.tool_start(tool_name, tool_args)
        logger.log_tool_call(tool_name, tool_args, status="called")

        # 特殊工具处理
        if tool_name == "compress_context":
            old_tokens = estimate_messages_tokens(messages)
            messages[:] = self._compress_context(messages)
            new_tokens = estimate_messages_tokens(messages)
            return (f"上下文压缩完成: 节省{old_tokens - new_tokens} Token", None), None

        if tool_name == "trigger_self_restart_tool":
            return self._handle_restart(tool_args, messages)

        if tool_name == "enter_hibernation":
            import re
            duration_match = re.search(r'休眠时长[:：]\s*(\d+)\s*秒', tool_args.get('reason', ''))
            hibernate_duration = int(duration_match.group(1)) if duration_match else self.config.agent.awake_interval
            _debug_logger.info(f"Agent 主动休眠 {hibernate_duration} 秒", tag="HIBERNATE")
            time.sleep(hibernate_duration)
            return (f"休眠 {hibernate_duration} 秒完成", "hibernated")

        # 执行工具
        result, _ = self.tool_executor.execute(tool_name, tool_args)

        if result is not None:
            _debug_logger.tool_result(tool_name, str(result), success=True)
            logger.log_tool_call(tool_name, tool_args, str(result), status="completed")
        else:
            _debug_logger.warning(f"[警告] {tool_name} 返回 None", tag="TOOL")

        # 标记自修改
        if tool_name in ("edit_local_file", "create_new_file"):
            file_path = tool_args.get("file_path", "")
            if "agent.py" in file_path:
                self._self_modified = True
                _debug_logger.success("agent.py 已修改，将触发重启", tag="MODIFY")

        return (result, None)

    def _handle_tool_result(self, tool_call: Dict, result, action, messages: list):
        """处理工具执行结果"""
        if action == "restart":
            logger.log_action("restart", {"tool": tool_call['name']})
        elif action == "skip":
            logger.log_action("skip", {"tool": tool_call['name']})
            messages.append(ToolMessage(content=result, tool_call_id=tool_call['id']))
        elif action == "hibernated":
            logger.log_action("hibernated", {"tool": tool_call['name']})
            messages.append(ToolMessage(content=result, tool_call_id=tool_call['id']))
        else:
            messages.append(ToolMessage(content=result, tool_call_id=tool_call['id']))

    def _handle_restart(self, tool_args: dict, messages: list) -> tuple:
        """处理重启请求"""
        # 任务清单拦截检查
        is_blocked, block_msg = check_restart_block()
        if is_blocked:
            _debug_logger.warning("任务清单未完成，禁止重启", tag="TASK_BLOCK")
            return (block_msg, None)

        # 测试门控
        if self._self_modified:
            test_result = self._run_evolution_gate()
            if not test_result["passed"]:
                error_msg = (
                    f"[TEST GATE FAILED] 测试未通过，禁止进化！\n"
                    f"失败模块: {', '.join(test_result['failed_modules'])}\n"
                    f"通过: {test_result['passed_count']}/{test_result['total_count']}"
                )
                _debug_logger.error("测试门控失败，禁止重启", tag="GATE")
                return (error_msg, None)

        # 世代归档
        current_gen = get_generation_tool()
        intermediate_steps = []
        for msg in messages:
            if hasattr(msg, 'content') and isinstance(msg.content, str):
                if msg.type == "ai" and msg.content:
                    intermediate_steps.append({"type": "thought", "content": msg.content[:500]})
                elif msg.type == "tool":
                    intermediate_steps.append({"type": "tool_call", "name": getattr(msg, 'name', 'unknown'), "content": msg.content[:200]})

        core_wisdom = get_core_context() or "无"
        current_goal = get_current_goal() or "待定"
        archive_generation_history(generation=current_gen, history_data=intermediate_steps, core_wisdom=core_wisdom, next_goal=current_goal)
        new_gen = advance_generation()
        clear_generation_task()

        tool_result = trigger_self_restart_tool(**tool_args)
        tool_result_with_archive = f"{tool_result}\n[世代归档] G{current_gen} -> G{new_gen}"

        self._self_modified = False
        return (tool_result_with_archive, "restart")

    def _run_evolution_gate(self) -> dict:
        """运行进化测试门控"""
        import subprocess

        _debug_logger.info("运行进化测试门控...", tag="GATE")

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "-q"],
                capture_output=True, text=True,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                timeout=120,
            )

            output = result.stdout + result.stderr
            passed_count = output.count(" PASSED")
            failed_count = output.count(" FAILED")
            total_count = passed_count + failed_count

            failed_modules = []
            for line in output.split("\n"):
                if "FAILED" in line:
                    parts = line.split("::")
                    if len(parts) >= 2:
                        failed_modules.append(parts[1].split("::")[0])

            passed = failed_count == 0
            if passed:
                _debug_logger.success(f"测试门控通过: {passed_count}/{total_count}", tag="GATE")
            else:
                _debug_logger.warning(f"测试门控失败: {failed_count}/{total_count} 失败", tag="GATE")

            return {
                "passed": passed,
                "passed_count": passed_count,
                "failed_count": failed_count,
                "total_count": total_count,
                "failed_modules": list(set(failed_modules)),
                "output": output,
            }

        except subprocess.TimeoutExpired:
            _debug_logger.error("测试门控超时 (2分钟)", tag="GATE")
            return {"passed": False, "passed_count": 0, "failed_count": 1, "total_count": 0, "failed_modules": ["pytest_timeout"], "output": "超时"}

        except Exception as e:
            _debug_logger.error(f"测试门控执行失败: {e}", tag="GATE")
            return {"passed": False, "passed_count": 0, "failed_count": 1, "total_count": 0, "failed_modules": ["test_runner_error"], "output": str(e)}

    def run_loop(self, initial_prompt: str = None) -> None:
        """运行 Agent 主循环"""
        bc = get_state_manager()

        _debug_logger.system(f"主循环开始 (awake_interval={self.config.agent.awake_interval}s)", tag=self.name)

        bc.set_state(AgentState.AWAKENING, action="系统初始化中...", generation=get_generation_tool(), current_goal=get_current_goal())

        generation = get_generation_tool()
        logger.start_generation(generation, self._build_system_prompt())
        logger.log_action("会话开始", f"世代: G{generation}, 模型: {self.model_name}")

        last_backup_time = time.time()

        try:
            _debug_logger.kv("记忆状态", f"G{get_generation_tool()} | {get_current_goal()[:50]}")
            print_evolution_time()

            user_input = initial_prompt
            if user_input:
                _debug_logger.system("首次任务已加载，开始执行...", tag="START")
            else:
                _debug_logger.system(f"自主进化模式，awake_interval={self.config.agent.awake_interval}s", tag="AUTO")

            while True:
                bc.set_state(AgentState.THINKING, action="思考并执行任务...")

                # 自动备份
                if self.config.agent.auto_backup:
                    current_time = time.time()
                    if current_time - last_backup_time >= self.config.agent.backup_interval:
                        from tools.shell_tools import backup_project
                        backup_project(f"自动备份 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                        last_backup_time = current_time

                should_continue = self.think_and_act(user_prompt=user_input)
                user_input = None

                if not should_continue:
                    _debug_logger.warning("重启已触发", tag="AGENT")
                    break

                if should_continue == "hibernated":
                    _debug_logger.debug("Agent 已主动休眠完毕，继续执行", tag="WAKE")
                    continue

                _debug_logger.system("执行完成，模型自主决策下一轮进化...", tag="EVOLVE")
                user_input = "【自主进化】任务完成。请分析本轮执行结果和当前代码库状态，自主决定下一个最有价值的行动。"
                time.sleep(2)

        except KeyboardInterrupt:
            _debug_logger.info("收到中断，退出", tag="AGENT")
            logger.end_session({"reason": "keyboard_interrupt"})
        except Exception as e:
            _debug_logger.error(f"主循环异常: {type(e).__name__}: {e}", exc_info=True)
            logger.log_error("main_loop_exception", str(e), traceback.format_exc())
        finally:
            uptime = datetime.now() - self.start_time
            _debug_logger.info(f"运行结束 (运行时长: {uptime})", tag=self.name)
            bc.set_state(AgentState.IDLE, action="系统已关闭")
            logger.end_session({"uptime_seconds": uptime.total_seconds()})


# ============================================================================
# 辅助函数
# ============================================================================

def _get_total_generations() -> int:
    """获取总世代数"""
    memory = _load_memory()
    return memory.get("total_generations", 1)


def print_evolution_time():
    """打印当前系统时间"""
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    _debug_logger.system(f"系统时间: {current_time}", tag="EVOLVE")


def setup_logging(level: str = "INFO", log_format: Optional[str] = None) -> logging.Logger:
    """配置全局日志系统"""
    import os

    # 设置环境变量抑制第三方库调试日志
    os.environ.setdefault("HTTPX_LOG_LEVEL", "warning")
    os.environ.setdefault("LANGCHAIN_VERBOSE", "false")

    if log_format is None:
        log_format = '%(asctime)s | %(levelname)-8s | %(message)s'

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stdout
    )

    # 抑制第三方库的 DEBUG 日志，避免刷屏
    # httpx: HTTP 客户端库，会打印大量请求/响应日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # httpcore: httpx 的底层依赖
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # langchain: 打印工具调用和 Chain 日志
    logging.getLogger("langchain").setLevel(logging.WARNING)
    # openai: OpenAI API 客户端
    logging.getLogger("openai").setLevel(logging.WARNING)
    # anthropic: Anthropic API 客户端
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    # urllib3: HTTP 库
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    # litellm: LLM 调用库
    logging.getLogger("litellm").setLevel(logging.WARNING)
    # langchain_community: LangChain 社区模块
    logging.getLogger("langchain_community").setLevel(logging.WARNING)
    # langchain_openai: LangChain OpenAI 集成
    logging.getLogger("langchain_openai").setLevel(logging.WARNING)

    # 抑制 rich 库的详细日志
    logging.getLogger("rich").setLevel(logging.WARNING)

    return logging.getLogger("SelfEvolvingAgent")


# ============================================================================
# 命令行入口
# ============================================================================

EVOLUTION_TEST_PROMPT = """你的第一次进化测试任务开始：
1. 请使用 `read_local_file` 读取你当前的 `agent.py` 代码。
2. 使用 `edit_local_file` 在 `agent.py` 中添加一个名为 `print_evolution_time()` 的简单函数。
3. 修改完成后，使用 `check_syntax` 检查 `agent.py` 的语法。
4. 确认语法无误后，调用 `trigger_self_restart_tool` 重启你自己。"""


def parse_args():
    """解析命令行参数"""
    import argparse
    parser = argparse.ArgumentParser(description="自我进化 Agent")
    parser.add_argument('-c', '--config', dest='config_path', help='配置文件路径')
    parser.add_argument('--awake-interval', type=int, dest='awake_interval', help='苏醒间隔（秒）')
    parser.add_argument('--model', dest='model_name', help='模型名称')
    parser.add_argument('--temperature', type=float, help='温度参数')
    parser.add_argument('--log-level', dest='log_level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='日志级别')
    parser.add_argument('--name', help='Agent 名称')
    parser.add_argument('--test', action='store_true', help='运行首次进化测试')
    parser.add_argument('--prompt', type=str, default=None, help='初始任务提示')
    parser.add_argument('--auto', action='store_true', help='自动模式（无交互）')
    return parser.parse_args()


def main(initial_prompt: str = None):
    """Agent 主入口函数"""
    ui = get_ui()

    ui.console.clear()
    ui.console.print()
    ui.console.print("[bold cyan]╔══════════════════════════════════════════════════════════╗[/bold cyan]")
    ui.console.print("[bold cyan]║                                                          ║[/bold cyan]")
    ui.console.print("[bold cyan]║[bold white]Self-Evolving Agent[/bold white] - Terminal Edition            ║[/bold cyan]")
    ui.console.print("[bold cyan]║                                                          ║[/bold cyan]")
    ui.console.print("[bold cyan]╚══════════════════════════════════════════════════════════╝[/bold cyan]")
    ui.console.print()

    args = parse_args()

    config = Config(
        config_path=args.config_path,
        **{k: v for k, v in {
            'llm.model_name': args.model_name,
            'llm.temperature': args.temperature,
            'agent.awake_interval': args.awake_interval,
            'agent.name': args.name,
            'log.level': args.log_level,
        }.items() if v is not None}
    )

    setup_logging(level=config.log.level)

    ui.console.print(f"[bold]启动 {config.agent.name}[/bold]")
    ui.console.print(f"  [cyan]Model:[/cyan]   {config.llm.model_name}")
    ui.console.print(f"  [cyan]Awake:[/cyan]   {config.agent.awake_interval}s")
    ui.console.print(f"  [cyan]Backup:[/cyan]   {config.agent.auto_backup}")
    ui.console.print()

    try:
        api_key = config.get_api_key()
        if not api_key:
            ui_error("API Key 未设置!", None)
            sys.exit(1)

        agent = SelfEvolvingAgent(config=config)
        ui.console.print(f"  [green]Key Tools:[/green]   {len(agent.key_tools)} loaded")
        ui.console.print("[dim]─" * 60 + "[/dim]")
        ui.console.print()

        if args.auto or initial_prompt:
            agent.run_loop(initial_prompt=initial_prompt)
        else:
            ui.console.print("[bold yellow]交互模式[/bold yellow] - 输入指令或按 Enter 进入自动模式")
            ui.console.print("[dim]提示: 输入 /help 查看命令，/auto 进入自动模式，/quit 退出[/dim]")
            ui.console.print()

            while True:
                try:
                    user_input = input("[bold cyan]Agent[/bold cyan] > ").strip()

                    if not user_input:
                        ui.console.print("[dim]进入自动模式...[/dim]")
                        agent.run_loop()
                        break
                    elif user_input.lower() in ['/quit', '/exit', '/q']:
                        ui.console.print("[yellow]再见![/yellow]")
                        break
                    elif user_input.lower() in ['/auto', '/a']:
                        ui.console.print("[dim]进入自动模式...[/dim]")
                        agent.run_loop()
                        break
                    elif user_input.lower() in ['/help', '/h', '/?']:
                        ui.console.print("""
[bold cyan]可用命令:[/bold cyan]
  /auto, /a     - 进入自动模式
  /quit, /q     - 退出程序
  /help, /h     - 显示此帮助
  <任意文本>     - 将文本作为任务发送给 Agent
""")
                        continue
                    else:
                        agent.run_loop(initial_prompt=user_input)
                        ui.console.print()
                        ui.console.print("[dim]─" * 60 + "[/dim]")
                        ui.console.print("[yellow]返回交互模式[/yellow]")
                        ui.console.print()

                except KeyboardInterrupt:
                    ui.console.print("\n[yellow]中断，退出...[/yellow]")
                    break
                except EOFError:
                    break

    except Exception as e:
        ui_error(f"启动异常: {type(e).__name__}: {e}", traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    print_evolution_time()
    args = parse_args()

    if args.test:
        _debug_logger.section("首次进化测试模式")
        main(initial_prompt=EVOLUTION_TEST_PROMPT)
    elif args.prompt:
        main(initial_prompt=args.prompt)
    else:
        main()
