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
from core.logging.setup import setup_logging, print_evolution_time

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

# 导入编排模块（Core First）
from core.orchestration.agent_lifecycle import AgentLifecycle, AUTONOMOUS_USER_PROMPT
from core.orchestration.context_compressor import ContextCompressor
from core.orchestration.llm_factory import create_llm, test_llm_connection
from config.providers import init_model_discovery
from core.prompt_manager import get_prompt_manager
from core.orchestration.response_parser import parse_llm_response


# 导入决策模块
from core.decision.decision_tree import DecisionContext, get_decision_tree, create_default_decision_tree
from core.decision.priority_optimizer import Task, get_priority_optimizer
from core.decision.strategy_selector import get_strategy_selector, create_default_selector
from core.decision.task_classifier import classify_task_type
# 导入编排系统
from core.orchestration.plan_orchestrator import get_plan_orchestrator
# 导入宠物系统
from core.pet_system import get_pet_system

# 进化测试提示词
EVOLUTION_TEST_PROMPT = """你的第一次进化测试任务开始：
1. 请使用 `read_local_file` 读取你当前的 `agent.py` 代码。
2. 使用 `edit_local_file` 在 `agent.py` 中添加一个名为 `print_evolution_time()` 的简单函数。
3. 修改完成后，使用 `check_syntax` 检查 `agent.py` 的语法。
4. 确认语法无误后，调用 `trigger_self_restart_tool` 重启你自己。"""


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

        # （决策树、优先级优化、策略选择）
        self.decision_tree = get_decision_tree(project_root)
        self.priority_optimizer = get_priority_optimizer(project_root)
        self.strategy_selector = get_strategy_selector(project_root)
        if not self.decision_tree._nodes:
            self.decision_tree.load_from_config(create_default_decision_tree().to_config())
        if not self.strategy_selector._strategies:
            default_selector = create_default_selector()
            for s in default_selector._strategies.values():
                self.strategy_selector.add_strategy(s)

        # 编排模块（LLM协调、工具注册、记忆管理、任务规划）
        try:
            self.llm_orchestrator = get_llm_orchestrator()
        except Exception:
            self.llm_orchestrator = None
        try:
            self.tool_registry = get_tool_registry(project_root)
        except Exception:
            self.tool_registry = None
        try:
            self.memory_manager = get_memory_manager(project_root)
        except Exception:
            self.memory_manager = None
        try:
            self.task_planner = get_task_planner(project_root)
        except Exception:
            self.task_planner = None

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

    def _init_llm(self):
        """初始化 LLM（使用工厂）"""
        # 本地 Provider 自动切换已在前面完成
        # 使用工厂创建 LLM
        self.llm, self.compression_llm = create_llm(self.config)
        self.model_name = self.config.llm.model_name
        self.llm_with_tools = self.llm.bind_tools(self.key_tools)

        # 测试 LLM 连接
        if not test_llm_connection(self.llm, self.model_name):
            raise RuntimeError("LLM 连接失败，请检查 API 配置")

    def _init_token_compressor(self):
        """初始化 Token 压缩器和上下文压缩管理"""
        import os
        summary_prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "workspace", "prompts", "COMPRESS_SUMMARY.md"
        )
        # compression_llm 已在 _init_llm 中通过 create_llm 创建
        self.token_compressor = EnhancedTokenCompressor(
            token_budget=self._effective_max_token_limit,
            max_history_pairs=self.config.context_compression.keep_recent_steps,
            compression_llm=self.compression_llm,
            enable_preemptive=True,
            summary_prompt_path=summary_prompt_path,
        )

        # 使用 ContextCompressor 管理上下文压缩
        self.context_compressor = ContextCompressor(
            token_compressor=self.token_compressor,
            config=self.config,
            model_info=getattr(self, 'model_info', None),
            effective_max_token_limit=self._effective_max_token_limit,
        )

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
            # 无外部输入时使用自主进化提示
            user_prompt = AUTONOMOUS_USER_PROMPT

        # 首次对话写入 System Prompt
        if not self._system_prompt_written:
            logger.write_system_prompt(system_prompt)
            self._system_prompt_written = True

        messages.append(HumanMessage(content=user_prompt))
        logger.start_turn(current_turn)
        logger.log_user_input(user_prompt)

        logger.log_llm_request(messages, model=self.model_name)
        max_iterations = self.config.agent.max_iterations

        try:
            # 在开始循环前进行决策
            from core.decision.decision_tree import DecisionContext
            decision_context = DecisionContext(
                state={
                    "user_prompt": user_prompt,
                    "generation": get_generation_tool(),
                    "has_task": bool(get_current_goal()),
                    "iteration": 1,
                    "exploration_mode": getattr(self.config.agent, 'exploration_mode', False),
                },
                history=self.global_recent_actions[-10:] if hasattr(self, 'global_recent_actions') else [],
            )
            decision_result = None
            if hasattr(self, 'decision_tree'):
                decision_result = self.decision_tree.make_decision(decision_context)
                if decision_result and decision_result.selected_action != "no_decision":
                    _debug_logger.debug(
                        f"[决策] {decision_result.selected_action}: {decision_result.reasoning}", tag="DECISION"
                    )

            for iteration in range(1, max_iterations + 1):
                # 状态机驱动：每轮迭代前重建 SystemMessage
                # 包含 base_prompt + state_memory + 当前激活的 registry 规则
                current_prompt, _ = self.prompt_manager.build()
                messages[0] = SystemMessage(content=current_prompt)

                # 自动 Token 检查与压缩
                messages = self.context_compressor.check_and_compress(messages, iteration)

                # 第一次循环打印会话开始
                if iteration == 1:
                    _debug_logger.session_start(self.model_name, get_generation_tool())
                    _debug_logger.session_start_log(self.model_name, get_generation_tool())

                # 动态调整迭代策略
                if decision_result and hasattr(self, 'strategy_selector'):
                    action = decision_result.selected_action
                    if "探索" in action or "explore" in action.lower():
                        if hasattr(self.strategy_selector, '_config'):
                            self.strategy_selector._config["exploration_rate"] = 0.4
                    elif "利用" in action or "exploit" in action.lower():
                        if hasattr(self.strategy_selector, '_config'):
                            self.strategy_selector._config["exploration_rate"] = 0.1

                # 调用 LLM
                response = self._invoke_llm(messages)
                if response is None:
                    _debug_logger.error("LLM 调用失败", tag="LLM")
                    continue

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

                # 解析工具调用、状态记忆和规则切换
                parser_result = parse_llm_response(response)
                ui.add_content(parser_result.thinking_content)

                # 解析 <mood> 标签，同步到 pet_system
                if parser_result.mood_content:
                    try:
                        pet = get_pet_system()
                        mood_str = parser_result.mood_content.strip()
                        import re
                        mood_match = re.search(r'"心情"\s*:\s*(\d+)', mood_str)
                        energy_match = re.search(r'"活力"\s*:\s*(\d+)', mood_str)
                        hunger_match = re.search(r'"饱食"\s*:\s*(\d+)', mood_str)
                        if mood_match:
                            pet.data.attributes.mood = int(mood_match.group(1))
                        if energy_match:
                            pet.data.attributes.energy = int(energy_match.group(1))
                        if hunger_match:
                            pet.data.attributes.hunger = int(hunger_match.group(1))
                    except Exception:
                        pass

                # 自动解析 <plan> 标签，存入 TaskPlanner，渲染清单注入提示词
                try:
                    raw_plan = get_plan_orchestrator().extract_plan_tag(parser_result.raw_content or "")
                    if raw_plan:
                        checklist = get_plan_orchestrator().parse_and_store(raw_plan)
                        ui.add_content(f"[系统] 任务清单已生成：\n{checklist}")
                except Exception:
                    pass  # PlanOrchestrator 尚未初始化，静默跳过

                messages.append(AIMessage(content=parser_result.clean_content))

                # # 回写 state_memory（落盘 + 更新 PM 内存缓存）
                # if parser_result.state_memory:
                #     self.prompt_manager.update_state_memory(parser_result.state_memory)

                # # 更新激活规则集（兜底：空则保持不变）
                # if parser_result.active_rules:
                #     self.prompt_manager.update_active_rules(parser_result.active_rules)

                # 动态切换提示词组件拼装（<active_components> 标签驱动）
                if parser_result.active_components:
                    self.prompt_manager.select_components(parser_result.active_components)

                # 显示思考过程
                if parser_result.thinking_content:
                    _debug_logger.llm_thinking(parser_result.thinking_content)
                    logger.log_llm_intent("thinking", parser_result.thinking_content[:300])

                # 使用优先级优化器排序工具
                if hasattr(self, 'priority_optimizer'):
                    tool_calls = self._optimize_tool_order(parser_result.tool_calls)
                else:
                    tool_calls = parser_result.tool_calls

                # 执行工具（并行或单工具）
                self._execute_tools_parallel(tool_calls, messages)

            _debug_logger.turn_end(current_turn, tool_count=len(tool_calls) if tool_calls else 0)
            return True

        except Exception as e:
            _debug_logger.error(f"主循环异常: {type(e).__name__}: {e}", exc_info=True)
            return True

    def _invoke_llm(self, messages: list) -> Optional[Any]:
        """调用 LLM（带超时）"""
        ui = get_ui()
        clean_messages = []
        for msg in messages:
            if isinstance(msg, AIMessage):
                clean_msg = AIMessage(content=msg.content or "")
                clean_messages.append(clean_msg)
            else:
                clean_messages.append(msg)
        with ui.thinking("🤔 思考中..."):
            try:
                return self.llm_with_tools.invoke(clean_messages)
            except Exception as e:
                _debug_logger.error(f"LLM 调用异常: {type(e).__name__}: {e}", tag="LLM")
                logger.log_error("llm_error", f"{type(e).__name__}: {e}")
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

        # 策略选择
        if hasattr(self, 'strategy_selector'):
            context = {
                "tool_name": tool_name,
                "task_type": classify_task_type(tool_name),
                "exploration_mode": getattr(self.config.agent, 'exploration_mode', False),
                "generation": get_generation_tool(),
            }
            strategy_selection = self.strategy_selector.select(context)
            if strategy_selection and strategy_selection.selected_strategy:
                _debug_logger.debug(f"[策略] 选择策略: {strategy_selection.selected_strategy.name}", tag="STRATEGY")

        # 特殊工具处理
        if tool_name == "compress_context":
            old_tokens = estimate_messages_tokens(messages)
            messages[:] = self.context_compressor._compress_context(messages)
            new_tokens = estimate_messages_tokens(messages)
            return (f"上下文压缩完成: 节省{old_tokens - new_tokens} Token", None), None

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

        # Skill 工具
        if tool_name.startswith("skill_"):
            skill_name = tool_name[6:]
            if hasattr(self, 'skill_registry') and self.skill_registry:
                return (self.skill_registry.execute_skill(skill_name, tool_args), None)
            return (f"[错误] Skill 系统未初始化", None)

        # Skill 管理工具通过 tool_executor 执行
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

    def _optimize_tool_order(self, tool_calls: List[Dict]) -> List[Dict]:
        """使用优先级优化器调整工具执行顺序"""
        if not tool_calls or not hasattr(self, 'priority_optimizer'):
            return tool_calls

        # 添加任务到优化器
        task_map = {}
        for i, tc in enumerate(tool_calls):
            tool_name = tc.get('name', 'unknown')
            task_id = f"tool_{i}_{tool_name}"
            task = Task(
                task_id=task_id,
                name=f"{tool_name}",
                description=f"工具调用: {tool_name}",
                priority=0.5,
                estimated_time=0.1,
                metadata={"type": classify_task_type(tool_name)},
            )
            self.priority_optimizer.add_task(task)
            task_map[task_id] = tc

        # 优化顺序
        result = self.priority_optimizer.optimize(context={"tool_count": len(tool_calls)})
        return [task_map[tid] for tid in result.task_order if tid in task_map]

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
        """并行执行多个工具调用"""
        if not tool_calls:
            return
        # 使用 tool_executor 的并行执行
        results = self.tool_executor.execute_parallel(tool_calls)
        # 逐条追加到 messages
        for tc, result, action in results:
            self._handle_tool_result(tc, result, action, messages)

    def run_loop(self, initial_prompt: str = None) -> None:
        """运行 Agent 主循环"""
        lifecycle = AgentLifecycle(self, self.config)

        _debug_logger.system(f"主循环开始 (awake_interval={self.config.agent.awake_interval}s)", tag=self.name)

        lifecycle.transition_state(AgentState.AWAKENING, action="系统初始化中...")

        generation = get_generation_tool()
        logger.log_action("会话开始", f"世代: G{generation}, 模型: {self.model_name}")

        try:
            _debug_logger.kv("记忆状态", f"G{get_generation_tool()} | {get_current_goal()[:50]}")
            print_evolution_time()

            user_input = lifecycle.get_next_prompt(initial_prompt)

            while True:
                lifecycle.transition_state(AgentState.THINKING, action="思考并执行任务...")

                # 自动备份检查
                lifecycle.check_auto_backup()

                # 执行思考-行动
                result = self.think_and_act(user_prompt=user_input)
                user_input = None

                if not lifecycle.should_continue(result):
                    break

                _debug_logger.system("执行完成，模型自主决策下一轮进化...", tag="EVOLVE")
                user_input = lifecycle.get_autonomous_prompt()
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
            ui.add_content("[bold yellow]交互模式[/bold yellow] - 输入指令或按 Enter 进入自动模式")
            ui.add_content("[dim]提示: 输入 /help 查看命令，/auto 进入自动模式，/quit 退出[/dim]")
            ui.stop_live()  # 停止 Live 显示以便 input() 可以正常工作
            run_interactive_mode(agent)

    except Exception as e:
        ui_error(f"启动异常: {type(e).__name__}: {e}", traceback.format_exc())
        ui.stop_live()
        sys.exit(1)


if __name__ == "__main__":
    print_evolution_time()
    args = parse_args()

    if args.test:
        _debug_logger.section("测试模式")
        main(initial_prompt=EVOLUTION_TEST_PROMPT)
    elif args.prompt:
        main(initial_prompt=args.prompt)
    else:
        main()
