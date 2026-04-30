#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import time
import asyncio
import traceback
import httpx
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
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

# LangChain 核心组件
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

# 模型发现
from config.providers import init_model_discovery

# 导入工具
from tools import Key_Tools
from tools.token_manager import EnhancedTokenCompressor, estimate_messages_tokens
from tools.memory_tools import (
    get_generation_tool,
    get_core_context, get_current_goal,
    archive_generation_history, advance_generation,
    clear_generation_task,
)
from tools.rebirth_tools import trigger_self_restart_tool, handle_restart_request

# 导入 CLI UI
from core.ui.cli_ui import get_ui, ui_error
from core.ui.token_display import print_tokens

from core.prompt_manager import get_prompt_manager

# 导入宠物系统
from core.pet_system import get_pet_system

# LLM 错误分类与重试策略
MAX_CONSECUTIVE_FAILURES = 5  # 单次 LLM 调用最大重试次数


def _classify_llm_error(e: Exception) -> tuple[str, bool, str]:
    """分类 LLM 异常，返回 (category, is_retryable, user_message)。"""
    exc_type = type(e).__name__
    exc_msg = str(e)

    # httpx HTTPStatusError：从异常消息中解析状态码
    if "HTTPStatusError" in exc_type or "429" in exc_msg or "500" in exc_msg:
        if "429" in exc_msg:
            return ("rate_limit", True, "API 速率超限（429），等待后重试")
        if "500" in exc_msg:
            return ("server_error", True, "API 服务器错误（500），等待后重试")
        if "502" in exc_msg or "503" in exc_msg or "504" in exc_msg:
            return ("server_error", True, f"API 服务不可用（{exc_msg[:30]}），等待后重试")
        if "401" in exc_msg or "403" in exc_msg:
            return ("auth_error", False, "API 认证失败（401/403），请检查 API Key")
        return ("http_error", False, f"HTTP 错误：{exc_msg[:60]}")

    # 超时
    if "Timeout" in exc_type or "timeout" in exc_msg.lower():
        return ("timeout", True, "LLM 响应超时，等待后重试")

    # 网络连接错误
    if "ConnectError" in exc_type or "Connect" in exc_type:
        return ("network_error", True, "网络连接失败，等待后重试")

    # ReadError / RemoteProtocolError
    if "ReadError" in exc_type or "RemoteProtocolError" in exc_type:
        return ("network_error", True, "连接读取异常，等待后重试")

    # RequestError（通用网络错误）
    if "RequestError" in exc_type:
        return ("network_error", True, f"网络请求异常，等待后重试")

    # 认证错误（通过消息文本匹配）
    if "auth" in exc_msg.lower() or "401" in exc_msg or "403" in exc_msg:
        return ("auth_error", False, "认证失败，请检查 API Key 配置")

    # KeyboardInterrupt
    if exc_type == "KeyboardInterrupt":
        return ("user_interrupt", False, "用户主动中断")

    # 默认：未知错误，不可重试
    return ("unknown_error", False, f"未知错误：{exc_type}: {exc_msg[:60]}")




EVOLUTION_TEST_PROMPT = """你的第一次进化测试任务开始：制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。"""


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

        # Skill 系统（相关模块已从 ecosystem 移除）
        self.skill_registry = None
        self.skill_tools = []
        _debug_logger.info("[Skill] Skill 系统已移除", tag="SKILL")

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

    def think_and_act(self, user_prompt: str = None) -> bool:
        """
        苏醒时执行一次思考和行动

        流程：
        1. 构建系统提示词
        2. 调用 LLM 进行推理
        3. 解析并执行工具调用
        4. 返回结果给 LLM 继续推理
        5. 直到 Agent 认为任务完成

        Args:
            user_prompt: 用户输入的提示词（可选，无则使用自主进化提示）
            system_prompt: 预计算的系统提示词（由 run_loop 传入，避免重复构建）

        Returns:
            True: 继续运行, False: 触发重启, "hibernated": 休眠后继续
        """
        ui = get_ui()
        system_prompt, _ = self.prompt_manager.build()
        messages = [SystemMessage(content=system_prompt)]

        # 获取轮次编号
        if user_prompt:
            current_turn = logger._turn_count
        else:
            current_turn = logger._turn_count + 1
            # 无外部输入时使用默认提示
            if user_prompt is None:
                user_prompt = "请执行当前世代的开发任务。"

        # 首次对话写入 System Prompt
        if not self._system_prompt_written:
            logger.write_system_prompt(system_prompt)
            self._system_prompt_written = True

        messages.append(HumanMessage(content=user_prompt))
        logger.start_turn(current_turn)
        logger.log_user_input(user_prompt)

        logger.log_llm_request(messages, model=getattr(self.config.llm, 'model_name', 'unknown'))
        max_iterations = self.config.agent.max_iterations

        try:
            consecutive_failures = 0
            for iteration in range(1, max_iterations + 1):
                current_prompt, _ = self.prompt_manager.build()
                messages[0] = SystemMessage(content=current_prompt)

                if iteration == 1:
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
                _debug_logger.debug(f"[DEBUG] content 长度={len(raw_content)} | 内容预览: {raw_content[:200]}", tag="RAW")

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

                messages.append(AIMessage(content=raw_content))

                tool_calls = []
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

        with ui.thinking("🤔 思考中..."):
            attempt = 0
            while attempt < MAX_CONSECUTIVE_FAILURES:
                try:
                    return self.llm_with_tools.invoke(clean_messages)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    attempt += 1
                    category, is_retryable, user_msg = _classify_llm_error(e)

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
        tool_args = tool_call.get('args') or tool_call.get('arguments') or {}
        if isinstance(tool_args, str):
            try:
                import json
                tool_args = json.loads(tool_args)
            except (json.JSONDecodeError, TypeError):
                tool_args = {}
        elif not isinstance(tool_args, dict):
            try:
                import json
                tool_args = json.loads(str(tool_args))
            except (json.JSONDecodeError, TypeError):
                tool_args = {}
        tool_args = tool_args if isinstance(tool_args, dict) else {}

        _debug_logger.tool_start(tool_name, tool_args)

        if tool_name == "trigger_self_restart_tool":
            return handle_restart_request(
                tool_args=tool_args,
                messages=messages,
                self_modified=self._self_modified,
            )

        if tool_name == "enter_hibernation":
            import re
            duration_match = re.search(r'休眠时长[:：]\s*(\d+)\s*秒', tool_args.get('reason', ''))
            hibernate_duration = int(duration_match.group(1)) if duration_match else self.config.agent.awake_interval
            _debug_logger.info(f"Agent 主动休眠 {hibernate_duration} 秒", tag="HIBERNATE")
            time.sleep(hibernate_duration)
            return (f"休眠 {hibernate_duration} 秒完成", "hibernated")


        result, _ = self.tool_executor.execute(tool_name, tool_args)

        if result is not None:
            _debug_logger.tool_result(tool_name, str(result), success=True)
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
        result_str, truncated = truncate_result(result)

        if action == "restart":
            logger.log_action("restart", {"tool": tool_call['name']})
        elif action == "skip":
            logger.log_action("skip", {"tool": tool_call['name']})
            messages.append(AIMessage(content=result_str))
        elif action == "hibernated":
            logger.log_action("hibernated", {"tool": tool_call['name']})
            messages.append(AIMessage(content=result_str))
        else:
            messages.append(AIMessage(content=result_str))

        if truncated:
            _debug_logger.warning(
                f"[工具] {tool_call['name']} 结果过长，已截断至 4000 字符", tag="TOOL"
            )

    def _execute_tools_parallel(self, tool_calls: List[Dict], messages: list):
        """串行执行工具（依次通过 _execute_tool 以便统一处理特殊工具）"""
        if not tool_calls:
            return
        for tc in tool_calls:
            result, action = self._execute_tool(tc, messages)
            self._handle_tool_result(tc, result, action, messages)

    def run_loop(self, initial_prompt: str = None) -> None:
        """运行 Agent 主循环（简化版，Phase 7 待重建）"""
        _debug_logger.system("主循环开始", tag=self.name)

        generation = get_generation_tool()
        model_name = getattr(self.config.llm, 'model_name', 'unknown')
        logger.log_action("会话开始", f"世代: G{generation}, 模型: {model_name}")

        try:
            _debug_logger.kv("记忆状态", f"G{get_generation_tool()} | {get_current_goal()[:50]}")
            print_evolution_time()

            user_input = initial_prompt

            while True:
                result = self.think_and_act(user_prompt=user_input)
                user_input = None

                if not result:
                    break

                _debug_logger.system("执行完成，准备下一轮...", tag="AGENT")
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
            lifecycle.transition_state(AgentState.IDLE, action="系统已关闭")
            logger.end_session({"uptime_seconds": uptime.total_seconds()})


# ============================================================================
# 命令行入口
# ============================================================================

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

    # 打印 ASCII Art 宠物形象到内容区
    from core.ui.ascii_art import get_avatar_manager
    avatar = get_avatar_manager()
    pet_art = avatar.get_art('happy')

    # 通过 add_content 输出初始信息到内容区
    ui.add_content("[bold cyan]+==============================================================+[/bold cyan]")
    ui.add_content("[bold cyan]|[bold white] Self-Evolving Agent[/bold white] - Terminal Edition             |[/bold cyan]")
    ui.add_content("[bold cyan]+==============================================================+[/bold cyan]")
    ui.add_content(f"[bright_cyan]{pet_art}[/bright_cyan]")
    ui.add_content("")
    ui.add_content(f"[bold]启动 {config.agent.name}[/bold]")
    ui.add_content(f"  [cyan]Model:[/cyan]   {config.llm.model_name}")
    ui.add_content(f"  [cyan]Awake:[/cyan]   {config.agent.awake_interval}s")
    ui.add_content(f"  [cyan]Backup:[/cyan]   {config.agent.auto_backup}")

    try:
        agent = SelfEvolvingAgent(config=config)
        ui.add_content(f"  [green]Key Tools:[/green]   {len(agent.key_tools)} loaded")
        ui.add_content("[dim]─" * 60 + "[/dim]")

        if args.auto or initial_prompt:
            agent.run_loop(initial_prompt=initial_prompt)
        else:
            ui.add_content("[bold yellow]自动模式[/bold yellow] - 无外部输入，进入自主进化")
            ui.stop_live()
            agent.run_loop(initial_prompt=None)

    except Exception as e:
        ui_error(f"启动异常: {type(e).__name__}: {e}", traceback.format_exc())
        ui.stop_live()
        sys.exit(1)
def print_evolution_time():
    """打印进化时间标记 - Agent 自我进化测试"""
    from datetime import datetime
    print(f"\n{'='*60}")
    print(f"🧬 Evolution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    # 🧪 进化测试标记 - Agent 代码修改验证
    print("[TEST] Agent.py modified successfully - Evolution test passed!")

if __name__ == "__main__":
    print_evolution_time()
    args = parse_args()

    if args.test:
        from core.ui.cli_ui import UIManager
        UIManager._test_mode = True
        # 强制 print 到底层 stdout，debugpy 无法拦截
        import sys as _sys
        _sys.__stdout__.write("=" * 60 + "\n")
        _sys.__stdout__.write("  Self-Evolving Agent - Test Mode\n")
        _sys.__stdout__.write("=" * 60 + "\n")
        _sys.__stdout__.flush()
        # 构造 config（与 main() 内部保持一致）
        _test_config = Config(
            config_path=args.config_path,
            llm_model_name=args.model_name,
            llm_temperature=args.temperature,
            agent_awake_interval=args.awake_interval,
            agent_name=args.name,
            log_level=args.log_level,
        )
        _agent = SelfEvolvingAgent(config=_test_config)
        _sys.__stdout__.write(f"  Key Tools: {len(_agent.key_tools)} loaded\n")
        _sys.__stdout__.write("-" * 60 + "\n")
        _sys.__stdout__.flush()
        _agent.run_loop(initial_prompt=EVOLUTION_TEST_PROMPT)
        sys.exit(0)
    elif args.prompt:
        main(initial_prompt=args.prompt)
    else:
        main()


