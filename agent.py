#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import time
import asyncio
import traceback
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

import httpx

# Windows 控制台编码修复
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# 导入配置
# ============================================================================
from config import Config, get_config

# ============================================================================
# 导入日志模块
# ============================================================================
from core.logging.logger import debug as _debug_logger
from core.logging.unified_logger import logger
from core.logging.setup import setup_logging, print_evolution_time as _print_evolution_time_core

# ============================================================================
# 导入核心模块（Core First）
# ============================================================================
from core.infrastructure.state import AgentState, get_state_manager
from core.infrastructure.event_bus import get_event_bus
from core.infrastructure.tool_result import truncate_result
from core.infrastructure.security import get_security_validator
from core.infrastructure.agent_session import get_session_state
from core.infrastructure.tool_executor import get_tool_executor
from core.infrastructure.llm_utils import (
    classify_llm_error, build_system_message, parse_tool_args, MAX_CONSECUTIVE_FAILURES,
)
from core.infrastructure.cli_utils import parse_args

# LangChain 核心组件
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

# 模型发现
from config.providers import init_model_discovery

# 导入工具
from tools import Key_Tools
from tools.token_manager import EnhancedTokenCompressor, estimate_messages_tokens
from tools.memory_tools import (
    get_core_context, get_current_goal,
)
from tools.rebirth_tools import trigger_self_restart_tool, handle_restart_request

# 导入 CLI UI
from core.ui.cli_ui import get_ui, ui_error
from core.ui.token_display import print_tokens

from core.prompt_manager import get_prompt_manager, to_string, split_sys_prompt_prefix
from core.infrastructure.mental_model import get_mental_model

# 导入宠物系统
from core.pet_system import get_pet_system

# 进化测试提示
EVOLUTION_TEST_PROMPT = "制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。"


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

        # API Key 检查
        self.api_key = self.config.get_api_key()
        if not self.api_key:
            raise ValueError(
                "未设置 API Key。\n"
                "请在 config.toml 中配置: [llm] api_key = 'your-api-key'"
            )

        # 本地 Provider 自动切换
        if self.config.llm.provider == "local":
            local_config = self.config.llm_local
            self.config.llm.api_base = local_config.url
            self.config.llm.model_name = local_config.model
            if local_config.require_api_key:
                self.config.llm.api_key = local_config.api_key or "dummy"
            else:
                self.config.llm.api_key = "not-required"
            _debug_logger.info(
                f"[Local Provider] URL: {local_config.url}, Model: {local_config.model}",
                tag="LLM"
            )

        # 创建主要工具
        self.key_tools = Key_Tools.create_key_tools()
        self.key_tool_maps = {tool.name for tool in self.key_tools}

        # 模型动态发现
        self._effective_max_token_limit = self._init_model_discovery()
        # LLM 初始化（使用工厂）
        self._init_llm()
        # Token 压缩器
        self._init_token_compressor()
        # Prompt 管理器
        self.prompt_manager = get_prompt_manager()

        # 全局状态
        self.global_recent_actions = []
        self.global_consecutive_count = 0
        self._self_modified = False
        self.start_time = datetime.now()

        # 工作区域
        workspace_dir = getattr(self.config.agent, 'workspace', 'workspace')
        project_root = os.path.dirname(os.path.abspath(__file__))
        self.workspace_path = os.path.join(project_root, workspace_dir)
        os.makedirs(self.workspace_path, exist_ok=True)

        # 核心组件
        self.state_manager = get_state_manager()
        self.event_bus = get_event_bus()
        self.tool_executor = get_tool_executor()
        self.security_validator = get_security_validator(project_root)

        # 心智模型（元认知引擎 — 必须在 EventBus 之后初始化）
        self.mental_model = get_mental_model(workspace_root=self.workspace_path)

        self._system_prompt_written = False

    def _init_model_discovery(self):
        """模型动态发现，返回 effective_max_token_limit"""
        self.model_info = None
        self._effective_max_token_limit = init_model_discovery(
            self.config,
            debug_logger=_debug_logger,
        )
        self.config.context_compression.max_token_limit = self._effective_max_token_limit
        return self._effective_max_token_limit

    def _init_llm(self):
        """初始化 LLM（ChatOpenAI 绑定工具）"""
        llm = ChatOpenAI(
            model=self.config.llm.model_name,
            temperature=self.config.llm.temperature,
            openai_api_key=self.config.llm.api_key,
            openai_api_base=self.config.llm.api_base,
            max_tokens=self.config.llm.max_tokens,
            timeout=self.config.llm.api_timeout,
        )
        self.llm_with_tools = llm.bind_tools(self.key_tools)

    def _init_token_compressor(self):
        """初始化 Token 压缩器"""
        self.token_compressor = EnhancedTokenCompressor(
            token_budget=self._effective_max_token_limit,
            compression_llm=ChatOpenAI(
                model=self.config.llm.model_name,
                temperature=self.config.llm.temperature,
                openai_api_key=self.config.llm.api_key,
                openai_api_base=self.config.llm.api_base,
                timeout=self.config.llm.api_timeout,
            ),
        )

    def think_and_act(self, user_prompt: str = None) -> bool:
        """苏醒时执行一次思考和行动。

        Returns:
            True: 继续运行, False: 触发重启, "hibernated": 休眠后继续
        """
        ui = get_ui()
        sp = self.prompt_manager.build()
        messages = [build_system_message(sp)]
        self._cached_system_prompt = to_string(sp)

        current_turn = logger._turn_count if user_prompt else logger._turn_count + 1
        if user_prompt is None:
            user_prompt = "开始自主进化，没有外部输入。用中文思考。"

        if not self._system_prompt_written:
            logger.write_system_prompt(self._cached_system_prompt)
            self._system_prompt_written = True

        messages.append(HumanMessage(content=user_prompt))
        logger.start_turn(current_turn)
        logger.log_user_input(user_prompt)
        logger.log_llm_request(messages, model=getattr(self.config.llm, 'model_name', 'unknown'))
        max_iterations = self.config.agent.max_iterations

        try:
            consecutive_failures = 0
            for iteration in range(1, max_iterations + 1):
                current_sp = self.prompt_manager.build()
                current_prompt = to_string(current_sp)
                if current_prompt != self._cached_system_prompt:
                    messages[0] = build_system_message(current_sp)
                    self._cached_system_prompt = current_prompt
                response = self._invoke_llm(messages)
                if response is None:
                    consecutive_failures += 1
                    ui.add_log(
                        f"LLM 调用失败（第 {consecutive_failures} 次连续失败）", "ERROR"
                    )
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        ui.add_log(
                            f"连续失败达到 {MAX_CONSECUTIVE_FAILURES} 次，停止运行。",
                            "ERROR",
                        )
                        break
                    continue
                # 成功后重置计数器
                consecutive_failures = 0

                # 调试：打印原始 content 长度和前 200 字符
                raw_content = response.content or ""
                _debug_logger.debug(f"[DEBUG] content 长度={len(raw_content)}", tag="RAW")

                # 记录 LLM 响应
                logger.log_llm_response(raw_content)

                # Token 使用统计
                if hasattr(response, 'usage_metadata') and response.usage_metadata:
                    usage = response.usage_metadata
                    input_tokens = usage.get('input_tokens', 0)
                    output_tokens = usage.get('output_tokens', 0)

                    # 打印输出 token 数
                    print_tokens(input_tokens, output_tokens)

                    # 记录到宠物系统
                    try:
                        pet = get_pet_system()
                        pet.record_tokens(input_tokens, output_tokens)
                        pet.trigger_heartbeat()
                    except Exception:
                        pass

                # 输出思考内容到 UI
                if raw_content.strip():
                    ui.add_content("[dim]... thinking ...[/dim]")
                    preview = raw_content[:200] + ("..." if len(raw_content) > 200 else "")
                    ui.add_content(f"[dim]{preview}[/dim]")

                messages.append(AIMessage(content=raw_content))

                tool_calls = getattr(response, 'tool_calls', []) or []
                self._execute_tools_parallel(tool_calls, messages)

            _debug_logger.turn_end(current_turn, tool_count=len(tool_calls) if tool_calls else 0)
            return True

        except Exception as e:
            _debug_logger.error(f"主循环异常: {type(e).__name__}: {e}", exc_info=True)
            return True

    def _invoke_llm(self, messages: list) -> Optional[Any]:
        """调用 LLM（带错误分类、自动重试）"""
        ui = get_ui()
        clean_messages = []
        for msg in messages:
            if isinstance(msg, AIMessage):
                clean_msg = AIMessage(content=msg.content or "")
                clean_messages.append(clean_msg)
            elif isinstance(msg, SystemMessage):
                # OpenAI API 只允许一个 SystemMessage（且必须在最前），
                # 将多余的 SystemMessage 转为 HumanMessage 保留其内容
                clean_messages.append(HumanMessage(content=msg.content or ""))
            else:
                clean_messages.append(msg)

        with ui.thinking("?? 思考中..."):
            attempt = 0
            while attempt < MAX_CONSECUTIVE_FAILURES:
                try:
                    return self.llm_with_tools.invoke(clean_messages)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    attempt += 1
                    category, is_retryable, user_msg = classify_llm_error(e)

                    _debug_logger.error(
                        f"LLM 调用失败 [{attempt}/{MAX_CONSECUTIVE_FAILURES}] {category}: {user_msg}",
                        tag="LLM",
                    )
                    logger.log_error("llm_error", f"{category}: {user_msg}")

                    if not is_retryable:
                        return None

                    if attempt < MAX_CONSECUTIVE_FAILURES:
                        wait = min(2 ** attempt, 30)
                        ui.add_log(f"等待 {wait}s 后重试（第 {attempt} 次）...", "WARN")
                        time.sleep(wait)

            _debug_logger.error(
                f"LLM 连续 {MAX_CONSECUTIVE_FAILURES} 次调用失败", tag="LLM"
            )
            ui.add_log(
                f"LLM 连续 {MAX_CONSECUTIVE_FAILURES} 次调用失败，请检查网络和 API 配置。",
                "ERROR",
            )
            return None

    def _execute_tool(self, tool_call: Dict, messages: list) -> tuple:
        """执行工具调用"""
        tool_name = tool_call.get('name', 'unknown')
        tool_args = parse_tool_args(
            tool_call.get('args') or tool_call.get('arguments') or {}
        )

        _debug_logger.tool_start(tool_name, tool_args)

        if tool_name == "trigger_self_restart_tool":
            return handle_restart_request(
                tool_args=tool_args,
                messages=messages,
                self_modified=self._self_modified,
            )

        result, _ = self.tool_executor.execute(tool_name, tool_args)

        if result is not None:
            _debug_logger.tool_result(tool_name, str(result), success=True)
        else:
            _debug_logger.warning(f"[警告] {tool_name} 返回 None", tag="TOOL")

        return (result, None)

    def _handle_tool_result(self, tool_call: Dict, result, action, messages: list):
        """处理工具执行结果"""
        result_str, truncated = truncate_result(result)
        if action in ("restart", "skip", "hibernated"):
            logger.log_action(action, {"tool": tool_call['name']})
        messages.append(AIMessage(content=result_str))
        if truncated:
            _debug_logger.warning(f"[工具] {tool_call['name']} 结果过长，已截断", tag="TOOL")

    def _execute_tools_parallel(self, tool_calls: List[Dict], messages: list):
        """串行执行工具（依次通过 _execute_tool 以便统一处理特殊工具）"""
        if not tool_calls:
            return
        for tc in tool_calls:
            result, action = self._execute_tool(tc, messages)
            self._handle_tool_result(tc, result, action, messages)

    def run_loop(self, initial_prompt: str = None) -> None:
        _debug_logger.system("主循环开始", tag=self.name)

        model_name = getattr(self.config.llm, 'model_name', 'unknown')
        logger.log_action("会话开始", f"模型: {model_name}")
        get_state_manager().set_state(AgentState.AWAKENING, action="主循环启动")

        try:
            _debug_logger.kv("记忆状态", f"{get_current_goal()[:50]}")
            _print_evolution_time_core()

            user_input = initial_prompt

            while True:
                result = self.think_and_act(user_prompt=user_input)
                user_input = None

                if not result:
                    break

                _debug_logger.system("执行完成，准备下一轮...", tag="AGENT")

                # 检查 Cron 到期任务
                try:
                    from core.infrastructure.cron_scheduler import get_cron_scheduler
                    from core.infrastructure.background_tasks import get_background_task_manager
                    sched = get_cron_scheduler()
                    due_jobs = sched.get_due_jobs()
                    if due_jobs:
                        mgr = get_background_task_manager()
                        for job in due_jobs:
                            mgr.start_task(command=job["command"], timeout=300)
                            _debug_logger.info(f"Cron 触发: {job['name']} ({job['id']})", tag="CRON")
                except Exception:
                    pass

                time.sleep(2)

        except KeyboardInterrupt:
            _debug_logger.info("收到中断，退出", tag="AGENT")
        except Exception as e:
            _debug_logger.error(f"主循环异常: {type(e).__name__}: {e}", exc_info=True)
            logger.log_error("main_loop_exception", str(e), traceback.format_exc())
        finally:
            uptime = datetime.now() - self.start_time
            _debug_logger.info(f"运行结束 (运行时长: {uptime})", tag=self.name)
            get_state_manager().set_state(AgentState.IDLE, action="系统已关闭")
            logger.end_session({"uptime_seconds": uptime.total_seconds()})


# ============================================================================
# 命令行入口
# ============================================================================

def main(initial_prompt: str = None):
    """Agent 主入口函数"""
    ui = get_ui()

    # 清除控制台并启动 Live 显示（Claude Code 风格三段式布局）
    ui.console.clear()

    # 启动 Live 显示 - 三段式布局（顶部状态栏 + 中间内容区 + 底部日志栏）
    ui.start_live()

    # 初始化配置
    args = parse_args()

    # 构建配置参数（支持下划线格式 kwargs）
    config_kwargs = {}
    if args.model_name is not None:
        config_kwargs['llm_model_name'] = args.model_name
    if args.temperature is not None:
        config_kwargs['llm_temperature'] = args.temperature
    if args.awake_interval is not None:
        config_kwargs['agent_awake_interval'] = args.awake_interval
    if args.name is not None:
        config_kwargs['agent_name'] = args.name
    if args.log_level is not None:
        config_kwargs['log_level'] = args.log_level

    config = Config(config_path=args.config_path, **config_kwargs)

    setup_logging(level=config.log.level)

    # 启动信息
    ui.print_header(config.llm.model_name)

    try:
        agent = SelfEvolvingAgent(config=config)
        ui.add_content(f"[dim]Tools:[/dim] {len(agent.key_tools)} loaded  [dim]Awake:[/dim] {config.agent.awake_interval}s")
        ui.add_content("")

        if args.auto or initial_prompt:
            agent.run_loop(initial_prompt=initial_prompt)
        else:
            ui.add_content("[bold yellow]自动模式[/bold yellow] - 无外部输入，进入自主进化")
            agent.run_loop(initial_prompt=None)

    except Exception as e:
        ui_error(f"启动异常: {type(e).__name__}: {e}", traceback.format_exc())
        ui.stop_live()
        sys.exit(1)


if __name__ == "__main__":
    _print_evolution_time_core()
    args = parse_args()

    if args.test:
        from core.ui.cli_ui import UIManager
        UIManager._test_mode = True
        sys.__stdout__.write("=" * 60 + "\n  Self-Evolving Agent - Test Mode\n" + "=" * 60 + "\n")
        sys.__stdout__.flush()
        _test_config = Config(
            config_path=args.config_path,
            llm_model_name=args.model_name,
            llm_temperature=args.temperature,
            agent_awake_interval=args.awake_interval,
            agent_name=args.name,
            log_level=args.log_level,
        )
        _agent = SelfEvolvingAgent(config=_test_config)
        sys.__stdout__.write(f"  Key Tools: {len(_agent.key_tools)} loaded\n" + "-" * 60 + "\n")
        sys.__stdout__.flush()
        _agent.run_loop(initial_prompt=EVOLUTION_TEST_PROMPT)
        sys.exit(0)
    elif args.prompt:
        main(initial_prompt=args.prompt)
    else:
        main()
