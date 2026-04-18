#!/usr/bin/env python3

from __future__ import annotations

import os
import re
import sys
import time
import logging
import traceback
import httpx
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
from core.logging.logger import (
    DebugLogger,
    debug as _debug_logger,
)
from core.logging.unified_logger import logger

# 导入事件总线
from core.infrastructure.event_bus import EventBus, get_event_bus, EventNames, Event

# 导入状态管理
from core.infrastructure.state import AgentState, get_state_manager

# 导入安全模块（新）
from core.infrastructure.security import get_security_validator, SecurityValidator

# LangChain 核心组件
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from openai import OpenAI

# MiniMax OpenAI 兼容适配器（当 provider=minimax 时使用）
class MiniMaxOpenAIAdapter:
    """
    MiniMax OpenAI 兼容 API 适配器。
    使用 OpenAI SDK 调用 MiniMax 的 OpenAI 兼容端点。
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        timeout: httpx.Timeout,
        max_tokens: int = 8192,
        temperature: float = 1.0,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._tools = None
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=httpx.Timeout(
                timeout=timeout.read,
                connect=timeout.connect,
            ),
            http_client=httpx.Client(),
        )

    def bind_tools(self, tools: list) -> "MiniMaxOpenAIAdapter":
        """绑定工具，返回绑定后的实例副本"""
        adapter = MiniMaxOpenAIAdapter(
            model=self.model,
            api_key=self._client.api_key,
            base_url=str(self._client.base_url),
            timeout=httpx.Timeout(
                self._client.timeout.read or 600,
                connect=self._client.timeout.connect or 30,
            ),
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        adapter._tools = [self._convert_tool(t) for t in tools]
        return adapter

    @staticmethod
    def _convert_tool(tool: Any) -> dict:
        """
        将 LangChain BaseTool 转换为 OpenAI 工具格式。
        """
        name = getattr(tool, "name", str(tool))
        description = getattr(tool, "description", "") or ""
        schema = getattr(tool, "args_schema", None)
        if schema is None:
            input_schema = getattr(tool, "input_schema", None)
            schema = input_schema

        parameters = {}
        if schema:
            try:
                if hasattr(schema, "model_fields") and hasattr(schema.model_fields, 'items'):
                    for field_name, field in schema.model_fields.items():
                        ftype = "string"
                        if field.annotation:
                            ann = field.annotation
                            if ann == int or ann == "int":
                                ftype = "integer"
                            elif ann == float or ann == "number":
                                ftype = "number"
                            elif ann == bool:
                                ftype = "boolean"
                            elif ann == list or ann == List:
                                ftype = "array"
                            elif ann == dict or ann == Dict:
                                ftype = "object"
                        desc = ""
                        if hasattr(field, "description") and field.description:
                            desc = field.description
                        parameters[field_name] = {"type": ftype, "description": desc}
                elif hasattr(schema, "schema"):
                    schema_result = schema.schema()
                    props = schema_result.get("properties", {}) if isinstance(schema_result, dict) else {}
                    for fname, fval in props.items():
                        parameters[fname] = {
                            "type": fval.get("type", "string"),
                            "description": fval.get("description", ""),
                        }
            except Exception:
                pass

        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": parameters, "required": list(parameters.keys())},
            },
        }

    def invoke(self, messages) -> "MiniMaxResponse":
        """
        调用 MiniMax API。
        messages 可以是字符串（单次调用）或 List[HumanMessage|AIMessage|ToolMessage]。
        返回一个带 .content 属性的对象，兼容 LangChain 的处理方式。
        """
        if isinstance(messages, str):
            messages = [HumanMessage(content=messages)]

        # 转换消息格式：提取 system，转换 role
        openai_messages = []
        for msg in messages:
            role = getattr(msg, "type", "user") or "user"
            content = getattr(msg, "content", "") or ""

            if role == "system":
                # system message 直接拼入第一个消息的 content 前面
                continue
            elif role == "human":
                role = "user"
            elif role == "ai":
                role = "assistant"

            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif hasattr(block, "type") and block.type == "text":
                        text_parts.append(getattr(block, "text", ""))
                content = "\n".join(text_parts)

            if not content and hasattr(msg, "tool_calls") and msg.tool_calls:
                # assistant message 带 tool_calls 时，保留 tool_calls 但 content 可为空
                pass

            msg_dict = {"role": role, "content": content}

            # 携带 tool_calls
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tc_list = []
                for tc in msg.tool_calls:
                    if isinstance(tc, dict):
                        tc_list.append({
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["args"] if isinstance(tc["args"], str) else tc["args"],
                            },
                        })
                    elif hasattr(tc, "id"):
                        args = getattr(tc, "args", "{}")
                        if isinstance(args, str):
                            args = args
                        else:
                            import json
                            args = json.dumps(args)
                        tc_list.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": getattr(tc, "name", ""),
                                "arguments": args,
                            },
                        })
                if tc_list:
                    msg_dict["tool_calls"] = tc_list

            # 携带 tool_call_id（ToolMessage）
            if hasattr(msg, "tool_call_id") and msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id

            openai_messages.append(msg_dict)

        # 提取 system prompt
        system_prompt = ""
        for msg in messages:
            if getattr(msg, "type", None) == "system":
                content = getattr(msg, "content", "") or ""
                system_prompt = content
                break

        # 构建 API 参数
        api_kwargs = {
            "model": self.model,
            "messages": openai_messages,
            "extra_body": {"reasoning_split": True},
        }
        if system_prompt:
            api_kwargs["messages"] = [{"role": "system", "content": system_prompt}] + openai_messages
        if self.max_tokens:
            api_kwargs["max_tokens"] = self.max_tokens
        if self.temperature > 0:
            api_kwargs["temperature"] = self.temperature
        if self._tools:
            api_kwargs["tools"] = self._tools

        response = self._client.chat.completions.create(**api_kwargs)
        return MiniMaxResponse(response)


class MiniMaxResponse:
    """
    MiniMax OpenAI 响应包装器，提供与 LangChain AIMessage 兼容的接口。
    """

    def __init__(self, raw_response):
        self.raw_response = raw_response
        self.type = "ai"

        choice = raw_response.choices[0]
        message = choice.message

        self.content = message.content or ""

        # reasoning_details 字段（reasoning_split=True 时有）
        self.reasoning_details = []
        if hasattr(message, "reasoning_details") and message.reasoning_details:
            self.reasoning_details = message.reasoning_details

        # tool_calls
        self.tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                self.tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": tc.function.arguments,
                })

        self.usage_metadata = {
            "input_tokens": raw_response.usage.prompt_tokens if hasattr(raw_response.usage, "prompt_tokens") else 0,
            "output_tokens": raw_response.usage.completion_tokens if hasattr(raw_response.usage, "completion_tokens") else 0,
        }

# 导入模型动态发现
from core.infrastructure.model_discovery import ModelDiscovery, DiscoveryStatus

# 导入工具
from tools import Key_Tools
from tools.token_manager import EnhancedTokenCompressor, estimate_messages_tokens
from tools.memory_tools import (
    get_generation_tool, get_core_context_tool, get_current_goal_tool,
    get_core_context, get_current_goal,  # 向后兼容别名
    archive_generation_history, advance_generation,
    _load_memory, clear_generation_task,
    read_dynamic_prompt_tool, update_generation_task_tool, add_insight_to_dynamic_tool,
    check_restart_block,  # 重启拦截检查
)
from tools.rebirth_tools import trigger_self_restart_tool

# 导入 CLI UI
from core.ui.cli_ui import get_ui, ui_error

# 导入提示词构建器
from core.capabilities.prompt_builder import build_system_prompt

# 导入宠物系统
from core.pet_system import get_pet_system


# ============================================================================
# 导入工具执行器（从核心模块解耦）
# ============================================================================
from core.infrastructure.tool_executor import get_tool_executor

# ============================================================================
# 导入 Phase 6 模块（自主决策优化）
# ============================================================================
from core.decision.decision_tree import (
    DecisionTree, DecisionContext, DecisionType,
    get_decision_tree, create_default_decision_tree,
)
from core.decision.priority_optimizer import (
    PriorityOptimizer, Task, PriorityScore,
    get_priority_optimizer,
)
from core.decision.strategy_selector import (
    StrategySelector, Strategy, StrategyType,
    get_strategy_selector, create_default_selector,
)

# ============================================================================
# 导入 Phase 7 模块（模块化重构）
# ============================================================================
from core.orchestration.llm_orchestrator import (
    LLMOrchestrator, LLMConfig, LLMResponse, LLMCallOptions,
    get_llm_orchestrator,
)
from core.infrastructure.tool_registry import (
    ToolRegistry, ToolMetadata, ToolCategory, ToolRegistration,
    get_tool_registry,
)
from core.orchestration.memory_manager import (
    MemoryManager, ShortTermMemory, MidTermMemory, LongTermMemory,
    get_memory_manager, reset_memory_manager,
)
from core.orchestration.task_planner import (
    TaskPlanner, Task as PlannerTask, TaskStatus, TaskPriority,
    get_task_planner,
)


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

        # =========================================================================
        # 本地 Provider 自动切换
        # =========================================================================
        if self.config.llm.provider == "local":
            local_config = self.config.llm_local
            # 自动使用本地配置覆盖 LLM 配置
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

        # =========================================================================
        # 模型动态发现（运行时获取 max_model_len）
        # 仅本地模型需要动态发现，云端 API 提供商已有明确文档
        # =========================================================================
        self.model_info = None
        provider = getattr(self.config.llm, 'provider', '')
        is_local_provider = provider in ('local', 'ollama')
        discovery_enabled = getattr(self.config.llm_discovery, 'enabled', True) and is_local_provider

        if discovery_enabled:
            discovery = ModelDiscovery(
                api_base=self.config.llm.api_base,
                model_name=self.config.llm.model_name,
                timeout=getattr(self.config.llm_discovery, 'timeout', 5),
                enabled=True,
            )
            # 设置 fallback 值
            discovery.set_fallback(
                max_tokens=self.config.llm.max_tokens,
                max_token_limit=getattr(self.config.context_compression, 'max_token_limit', 16000),
            )
            try:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                self.model_info = loop.run_until_complete(discovery.discover())

                if self.model_info.status == DiscoveryStatus.SUCCESS:
                    _debug_logger.success(
                        f"模型发现成功: {self.model_info.model_name}\n"
                        f"  context_window: {self.model_info.max_model_len}\n"
                        f"  建议 max_tokens: {self.model_info.suggested_max_tokens}\n"
                        f"  压缩阈值 max_token_limit: {self.model_info.compression_thresholds.max_token_limit}",
                        tag="MODEL_DISCOVERY"
                    )
                    # 使用动态发现的值
                    effective_max_tokens = self.model_info.suggested_max_tokens
                    effective_max_token_limit = self.model_info.compression_thresholds.max_token_limit
                else:
                    _debug_logger.warning(
                        f"模型发现失败: {self.model_info.error_message or '未知错误'}，使用配置文件的值",
                        tag="MODEL_DISCOVERY"
                    )
                    effective_max_tokens = self.config.llm.max_tokens
                    effective_max_token_limit = getattr(
                        self.config.context_compression, 'max_token_limit', 16000
                    )
            except Exception as e:
                _debug_logger.warning(f"模型发现异常: {e}，使用配置文件的值", tag="MODEL_DISCOVERY")
                effective_max_tokens = self.config.llm.max_tokens
                effective_max_token_limit = getattr(
                    self.config.context_compression, 'max_token_limit', 16000
                )
        else:
            effective_max_tokens = self.config.llm.max_tokens
            effective_max_token_limit = getattr(
                self.config.context_compression, 'max_token_limit', 16000
            )

        # 保存 effective_max_token_limit 供 _check_and_compress 使用
        self._effective_max_token_limit = effective_max_token_limit

        # 创建 LLM（根据 provider 选择实现）
        api_timeout = getattr(self.config.llm, 'api_timeout', 600)
        provider = getattr(self.config.llm, 'provider', 'local')

        if provider == "minimax":
            # MiniMax 使用 OpenAI SDK 兼容接口
            self.llm = MiniMaxOpenAIAdapter(
                model=self.config.llm.model_name,
                api_key=self.api_key or "",
                base_url=self.config.llm.api_base or "https://api.minimaxi.com/v1",
                timeout=httpx.Timeout(api_timeout, connect=30),
                max_tokens=effective_max_tokens,
                temperature=self.config.llm.temperature,
            )
            _debug_logger.info(
                f"[LLM Config] MiniMax Anthropic 模式, model={self.config.llm.model_name}, "
                f"max_tokens={effective_max_tokens}, temperature={self.config.llm.temperature}",
                tag="LLM"
            )
        else:
            # 标准 OpenAI 兼容接口（Ollama, vLLM, DeepSeek, OpenAI 等）
            llm_kwargs = {
                "model": self.config.llm.model_name,
                "temperature": self.config.llm.temperature,
                "api_key": self.api_key,
                "max_tokens": effective_max_tokens,
            }
            if self.config.llm.api_base:
                llm_kwargs["base_url"] = self.config.llm.api_base
            llm_kwargs["timeout"] = httpx.Timeout(api_timeout, connect=30)
            self.llm = ChatOpenAI(**llm_kwargs)
            _debug_logger.info(
                f"[LLM Config] OpenAI 兼容模式, model={self.config.llm.model_name}, "
                f"max_tokens={effective_max_tokens}, base_url={self.config.llm.api_base}",
                tag="LLM"
            )

        self.model_name = self.config.llm.model_name

        # 调试日志：确认 max_tokens
        _debug_logger.info(
            f"[LLM Config] max_tokens={effective_max_tokens}, "
            f"model={self.config.llm.model_name}, "
            f"llm.max_tokens={self.llm.max_tokens}",
            tag="LLM"
        )

        # 绑定工具到 LLM
        self.llm_with_tools = self.llm.bind_tools(self.key_tools)

        # 测试 LLM 连接
        _debug_logger.info("正在测试 LLM 连接...", tag="LLM")
        try:
            test_response = self.llm.invoke("你好，请回复 OK")
            _debug_logger.success(f"LLM 连接测试成功: {test_response.content[:50]}...", tag="LLM")
        except Exception as e:
            _debug_logger.error(f"LLM 连接测试失败: {type(e).__name__}: {e}", tag="LLM")
            raise RuntimeError(f"LLM 连接失败，请检查 API 配置: {e}")

        # 创建压缩用 LLM
        compression_llm_kwargs = {
            "model": self.config.context_compression.compression_model,
            "temperature": 0.3,
            "api_key": self.api_key,
        }
        if self.config.llm.api_base:
            compression_llm_kwargs["base_url"] = self.config.llm.api_base

        compression_llm_kwargs["timeout"] = httpx.Timeout(api_timeout, connect=30)

        self.compression_llm = ChatOpenAI(**compression_llm_kwargs)

        # Token 压缩器（使用动态发现的 max_token_limit）
        import os
        summary_prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "workspace", "prompts", "COMPRESS_SUMMARY.md"
        )
        self.token_compressor = EnhancedTokenCompressor(
            token_budget=effective_max_token_limit,  # 使用动态发现的值
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
        
        # 初始化安全验证器（新）
        self.security_validator = get_security_validator(project_root)
        
        # =========================================================================
        # 初始化 Phase 6 模块（自主决策优化）
        # =========================================================================
        self.decision_tree = get_decision_tree(project_root)
        self.priority_optimizer = get_priority_optimizer(project_root)
        self.strategy_selector = get_strategy_selector(project_root)

        # 如果单例为空，创建默认配置
        if not self.decision_tree._nodes:
            self.decision_tree.load_from_config(create_default_decision_tree().to_config())
        if not self.strategy_selector._strategies:
            default_selector = create_default_selector()
            for s in default_selector._strategies.values():
                self.strategy_selector.add_strategy(s)

        # =========================================================================
        # 初始化 Phase 7 模块（模块化重构）
        # =========================================================================
        # LLM Orchestrator（可选，如果可用则使用）
        try:
            self.llm_orchestrator = get_llm_orchestrator()
        except Exception:
            self.llm_orchestrator = None

        # Tool Registry（可选，如果可用则使用）
        try:
            self.tool_registry = get_tool_registry(project_root)
        except Exception:
            self.tool_registry = None

        # Memory Manager（可选，如果可用则使用）
        try:
            self.memory_manager = get_memory_manager(project_root)
        except Exception:
            self.memory_manager = None

        # Task Planner（可选，如果可用则使用）
        try:
            self.task_planner = get_task_planner(project_root)
        except Exception:
            self.task_planner = None

        # =========================================================================
        # 初始化 Skill 系统（Phase 8.5: Agent 自我扩展）
        # =========================================================================
        try:
            from core.ecosystem.skill_registry import get_skill_registry
            from core.ecosystem.skill_tools import (
                install_skill_tool, update_skill_tool, optimize_skill_tool,
                uninstall_skill_tool, list_skills_tool, get_skill_info_tool,
                execute_skill_tool, search_skills_tool, render_skill_prompt_tool,
            )
            self.skill_registry = get_skill_registry()
            self.skill_tools = [
                install_skill_tool,
                update_skill_tool,
                optimize_skill_tool,
                uninstall_skill_tool,
                list_skills_tool,
                get_skill_info_tool,
                execute_skill_tool,
                search_skills_tool,
                render_skill_prompt_tool,
            ]
            # 绑定 Skill 工具到 LLM
            if hasattr(self, 'llm_with_tools') and self.llm_with_tools:
                self.llm_with_tools = self.llm_with_tools.bind_tools(self.skill_tools)

            # 注册 Skill 工具到 tool_executor（支持 _execute_tool 调用）
            for skill_tool in self.skill_tools:
                tool_name = getattr(skill_tool, 'name', None) or getattr(skill_tool, '__name__', str(skill_tool))
                self.tool_executor.register_tool(tool_name, skill_tool, timeout=60)

            _debug_logger.info(
                f"[Skill] 发现 {self.skill_registry.get_statistics()['total_skills']} 个 Skill，"
                f"{len(self.skill_tools)} 个管理工具已就绪",
                tag="SKILL"
            )
        except Exception as e:
            self.skill_registry = None
            self.skill_tools = []
            _debug_logger.warning(f"[Skill] Skill 系统初始化失败: {e}", tag="SKILL")

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
            # 在开始循环前进行决策
            decision_context = self._build_decision_context(user_prompt)
            decision_result = None
            if hasattr(self, 'decision_tree'):
                decision_result = self.decision_tree.make_decision(decision_context)
                if decision_result and decision_result.selected_action != "no_decision":
                    _debug_logger.debug(
                        f"[决策] {decision_result.selected_action}: {decision_result.reasoning}", tag="DECISION"
                    )

            for iteration in range(1, max_iterations + 1):
                # 自动 Token 检查与压缩
                messages = self._check_and_compress(messages, iteration)

                # 第一次循环打印会话开始
                if iteration == 1:
                    _debug_logger.session_start(self.model_name, get_generation_tool())

                # 动态调整迭代策略
                if decision_result and hasattr(self, 'strategy_selector'):
                    self._apply_strategy_adjustments(decision_result)

                # 打印当前输入 token 数
                current_input_tokens = estimate_messages_tokens(messages)
                try:
                    from rich.console import Console
                    Console(force_terminal=True).print(
                        "[dim]\\[TOKEN] 输入: {} | 迭代: {}/{}[/dim]".format(
                            current_input_tokens, iteration, max_iterations
                        )
                    )
                except Exception:
                    import sys
                    print("[TOKEN] 输入: {} | 迭代: {}/{}".format(
                        current_input_tokens, iteration, max_iterations), file=sys.stderr)

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
                    input_tokens = usage.get('input_tokens', 0)
                    output_tokens = usage.get('output_tokens', 0)

                    # 打印输出 token 数
                    try:
                        from rich.console import Console
                        Console(force_terminal=True).print(
                            "[dim]\\[TOKEN] 输出: {} | 输入: {}[/dim]".format(
                                output_tokens, input_tokens
                            )
                        )
                    except Exception:
                        import sys
                        print("[TOKEN] 输出: {} | 输入: {}".format(
                            output_tokens, input_tokens), file=sys.stderr)

                    # 记录到宠物系统
                    try:
                        pet = get_pet_system()
                        pet.record_tokens(input_tokens, output_tokens)
                        pet.trigger_heartbeat()
                    except Exception:
                        pass

                    _debug_logger.debug(
                        f"Token: {input_tokens} + {output_tokens}",
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

                # Phase 6: 使用优先级优化器排序工具
                if hasattr(self, 'priority_optimizer'):
                    tool_calls = self._optimize_tool_order(tool_calls)

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

        支持三种格式：
        1. 标准 tool_calls (function calling)
        2. <tool_call>{JSON}</tool_call> XML 格式
        3. <skill name="xxx"><param name="yyy">zzz</param></skill> Skill 格式

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
            # 格式1: <tool_call>{JSON}</tool_call>
            text_tool_calls = re.findall(
                r'<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>',
                response.content
            )

            for tc_json in text_tool_calls:
                try:
                    tc = json.loads(tc_json)
                    if 'arguments' in tc and 'args' not in tc:
                        tc['args'] = tc.pop('arguments')
                    if 'args' not in tc:
                        tc['args'] = {}
                    if 'id' not in tc:
                        tc['id'] = f"call_{uuid.uuid4().hex[:8]}"
                    tool_calls.append(tc)
                except json.JSONDecodeError:
                    pass

            # 格式2: <invoke name="xxx"> 或 <skill name="xxx">
            # 支持 <invoke name="tool_name">...</invoke> 和 <skill name="xxx">...</skill>
            skill_patterns = [
                r'<invoke\s+name="([^"]+)"[^>]*>([\s\S]*?)</invoke>',
                r'<skill\s+name="([^"]+)"[^>]*>([\s\S]*?)</skill>',
            ]

            for pattern in skill_patterns:
                for match in re.finditer(pattern, response.content):
                    name = match.group(1)
                    body = match.group(2)

                    # 解析参数
                    args = {}
                    param_matches = re.findall(
                        r'<param\s+name="([^"]+)"[^>]*>([\s\S]*?)</param>',
                        body
                    )
                    for param_name, param_value in param_matches:
                        # 尝试解析 JSON
                        try:
                            args[param_name] = json.loads(param_value.strip())
                        except (json.JSONDecodeError, ValueError):
                            args[param_name] = param_value.strip()

                    # 构建 tool_call
                    tc = {
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                        "name": name,
                        "args": args,
                    }
                    tool_calls.append(tc)

        return tool_calls, thinking_content

    def _check_and_compress(self, messages: list, iteration: int) -> list:
        """检查 Token 预算并在必要时压缩（增强版）"""
        current_tokens = estimate_messages_tokens(messages)

        # 优先使用运行时动态发现的 max_token_limit（来自 model_info）
        max_budget = getattr(self, '_effective_max_token_limit', None)
        if max_budget is None:
            # fallback：从 model_info 或配置文件获取
            if self.model_info and self.model_info.status == DiscoveryStatus.SUCCESS:
                max_budget = self.model_info.compression_thresholds.max_token_limit
            else:
                max_budget = self.config.context_compression.max_token_limit

        # 安全阈值
        preemptive_threshold = int(max_budget * 0.6)
        forced_threshold = int(max_budget * 0.8)
        critical_threshold = int(max_budget * 0.95)  # 紧急压缩阈值 95%

        # 获取压缩计数
        compression_count = getattr(self, '_compression_count', 0)
        max_compressions = getattr(self.config.context_compression, 'max_compressions_per_session', 20)

        # 紧急情况（超过95%）不受压缩次数限制
        is_emergency = current_tokens > critical_threshold

        if compression_count >= max_compressions and not is_emergency:
            _debug_logger.warning(f"[Token] 压缩次数已达上限 ({compression_count}/{max_compressions})，跳过", tag="TOKEN")
            return messages

        # 根据 Token 比例选择压缩级别
        ratio = current_tokens / max_budget if max_budget > 0 else 0

        if current_tokens > critical_threshold:
            # 紧急压缩（不受次数限制）
            _debug_logger.warning(f"[压缩-紧急] Token 危险 ({current_tokens}/{max_budget} = {ratio:.1%})", tag="TOKEN")
            messages = self._compress_context(messages, level="emergency")
        elif current_tokens > forced_threshold:
            # 深度压缩
            level = "deep" if compression_count < 2 else "standard"
            _debug_logger.warning(f"[压缩-{level}] Token 过高 ({current_tokens}/{max_budget} = {ratio:.1%})", tag="TOKEN")
            messages = self._compress_context(messages, level=level)
        elif current_tokens > preemptive_threshold and iteration > 1:
            # 标准压缩
            _debug_logger.info(f"[压缩-标准] Token 接近阈值 ({current_tokens}/{max_budget} = {ratio:.1%})", tag="TOKEN")
            messages = self._compress_context(messages, level="standard")
        elif current_tokens > preemptive_threshold * 0.8 and iteration > 1:
            # 轻度压缩
            _debug_logger.info(f"[压缩-轻度] Token 偏高 ({current_tokens}/{max_budget} = {ratio:.1%})", tag="TOKEN")
            messages = self._compress_context(messages, level="light")
        else:
            # 不需要压缩
            return messages

        # 检查压缩是否有效
        new_tokens = estimate_messages_tokens(messages)
        if new_tokens >= current_tokens:
            _debug_logger.warning(f"[Token] 压缩无效 ({current_tokens} -> {new_tokens})，回退原始", tag="TOKEN")
            return messages

        # 更新压缩计数
        self._compression_count = compression_count + 1
        _debug_logger.info(f"[Token] 压缩完成 ({current_tokens} -> {new_tokens})，节省 {current_tokens - new_tokens} Token", tag="TOKEN")

        return messages

    def _compress_context(self, messages: list, level: str = "standard") -> list:
        """
        压缩对话上下文（增强版）

        Args:
            messages: 消息列表
            level: 压缩级别 ("light", "standard", "deep", "emergency")
        """
        old_tokens = estimate_messages_tokens(messages)

        # 根据压缩级别选择摘要字数
        summary_chars_map = {
            "light": getattr(self.config.context_compression, 'light_summary_chars', 500),
            "standard": getattr(self.config.context_compression, 'standard_summary_chars', 1000),
            "deep": getattr(self.config.context_compression, 'deep_summary_chars', 2000),
            "emergency": 3000,
        }
        summary_chars = summary_chars_map.get(level, 1000)

        # 如果 config 中有 summary_max_chars，也使用它
        if hasattr(self.config.context_compression, 'summary_max_chars') and self.config.context_compression.summary_max_chars:
            summary_chars = self.config.context_compression.summary_max_chars

        try:
            # 尝试使用压缩质量评估
            from tools.compression_quality import get_compression_quality_evaluator
            evaluator = get_compression_quality_evaluator()

            compressed, _ = self.token_compressor.compress(
                messages,
                max_chars=summary_chars,
            )
            new_tokens = estimate_messages_tokens(compressed)

            # 评估压缩质量
            quality_report = evaluator.evaluate(
                messages, compressed, old_tokens, new_tokens
            )

# 记录压缩统计
            self.logger.info(f"[Token压缩-{level}] {old_tokens} -> {new_tokens} (节省 {quality_report.saved_tokens})")

            # 持久化压缩快照（利用新的记忆组件）
            if self.memory_manager is not None:
                try:
                    from core.orchestration.compression_persister import get_compression_persister
                    persister = get_compression_persister()
                    persister.save_snapshot(
                        generation=get_generation_tool(),
                        messages=messages,
                        summary=str(compressed[-1].content)[:500] if compressed else "",
                        before_tokens=old_tokens,
                        after_tokens=new_tokens,
                        level=level,
                        reason=f"compression_{level}",
                        key_decisions=[],
                        tool_stats={},
                    )
                except Exception:
                    pass  # 持久化失败不影响主流程
            logger.log_compression(old_tokens, new_tokens, quality_report.saved_tokens)

            # 保存原始消息用于可能的回退
            self._last_messages = messages

            return compressed

        except ImportError:
            # 如果没有质量评估器，回退到原有逻辑
            compressed, _ = self.token_compressor.compress(
                messages,
                max_chars=summary_chars,
            )
            new_tokens = estimate_messages_tokens(compressed)
            self.logger.info(f"[Token压缩] {old_tokens} -> {new_tokens}")
            logger.log_compression(old_tokens, new_tokens, old_tokens - new_tokens)

            # 持久化压缩快照（利用新的记忆组件）
            if self.memory_manager is not None:
                try:
                    from core.orchestration.compression_persister import get_compression_persister
                    persister = get_compression_persister()
                    persister.save_snapshot(
                        generation=get_generation_tool(),
                        messages=messages,
                        summary=str(compressed[-1].content)[:500] if compressed else "",
                        before_tokens=old_tokens,
                        after_tokens=new_tokens,
                        level=level,
                        reason=f"compression_{level}",
                        key_decisions=[],
                        tool_stats={},
                    )
                except Exception:
                    pass  # 持久化失败不影响主流程
            return compressed

    def _execute_tool(self, tool_call: Dict, messages: list) -> tuple:
        """执行工具调用"""
        tool_name = tool_call.get('name', 'unknown')
        # 同时支持 args 和 arguments
        tool_args = tool_call.get('args') or tool_call.get('arguments') or {}
        # MiniMax 2.7 可能返回 arguments 为 JSON 字符串或 dict，需要处理
        if isinstance(tool_args, str):
            try:
                import json
                tool_args = json.loads(tool_args)
            except (json.JSONDecodeError, TypeError):
                tool_args = {}
        elif not isinstance(tool_args, dict):
            # 如果既不是字符串也不是 dict，尝试转换
            try:
                import json
                tool_args = json.loads(str(tool_args))
            except (json.JSONDecodeError, TypeError):
                tool_args = {}
        # 确保 tool_args 是 dict 类型
        if not isinstance(tool_args, dict):
            tool_args = {}

        _debug_logger.tool_start(tool_name, tool_args)
        logger.log_tool_call(tool_name, tool_args, status="called")

        # Phase 6: 使用策略选择器选择执行策略
        start_time = datetime.now()
        strategy_selection = None
        if hasattr(self, 'strategy_selector'):
            context = self._build_strategy_context(tool_name, tool_args)
            strategy_selection = self.strategy_selector.select(context)
            if strategy_selection and strategy_selection.selected_strategy:
                _debug_logger.debug(
                    f"[策略] 选择策略: {strategy_selection.selected_strategy.name}", tag="STRATEGY"
                )

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

        # =========================================================================
        # Skill 工具处理（Phase 8.5: Agent 自我扩展）
        # =========================================================================
        # 检查是否是 Skill 工具
        if tool_name.startswith("skill_"):
            skill_name = tool_name[6:]  # 去掉 "skill_" 前缀
            # Skill 工具通过 skill_registry 执行
            if hasattr(self, 'skill_registry') and self.skill_registry:
                skill_result = self.skill_registry.execute_skill(skill_name, tool_args)
                return (skill_result, None)
            else:
                return (f"[错误] Skill 系统未初始化", None)

        # 检查是否是 Skill 管理工具（install_skill 等）
        skill_management_tools = {
            "install_skill", "update_skill", "optimize_skill",
            "uninstall_skill", "list_skills", "get_skill_info",
            "execute_skill", "search_skills", "render_skill_prompt",
        }
        if tool_name in skill_management_tools:
            # Skill 管理工具通过 tool_executor 执行
            # 这里直接执行，因为它们已经是 LangChain Tool
            pass  # 继续到下面的 tool_executor.execute

        # 执行工具
        result, _ = self.tool_executor.execute(tool_name, tool_args)

        if result is not None:
            _debug_logger.tool_result(tool_name, str(result), success=True)
            logger.log_tool_call(tool_name, tool_args, str(result), status="completed")
        else:
            _debug_logger.warning(f"[警告] {tool_name} 返回 None", tag="TOOL")

        # Phase 6: 记录策略执行结果
        if strategy_selection and hasattr(self, 'strategy_selector'):
            from core.decision.strategy_selector import StrategyResult
            duration = (datetime.now() - start_time).total_seconds()
            success = result is not None and "error" not in str(result).lower()
            strategy_result = StrategyResult(
                strategy_id=strategy_selection.selected_strategy.strategy_id,
                success=success,
                outcome=result,
                metrics={"duration": duration},
                duration=duration,
            )
            self.strategy_selector.record_result(strategy_result)

        # 标记自修改
        if tool_name in ("edit_local_file", "create_new_file"):
            file_path = tool_args.get("file_path", "")
            if "agent.py" in file_path:
                self._self_modified = True
                _debug_logger.success("agent.py 已修改，将触发重启", tag="MODIFY")

        return (result, None)

    def _build_strategy_context(self, tool_name: str, tool_args: Dict) -> Dict:
        """构建策略选择的上下文"""
        context = {
            "tool_name": tool_name,
            "task_type": self._classify_task_type(tool_name),
            "exploration_mode": getattr(self.config.agent, 'exploration_mode', False),
            "generation": get_generation_tool(),
        }
        return context

    def _classify_task_type(self, tool_name: str) -> str:
        """分类任务类型"""
        task_categories = {
            "code_read": ["read_local_file", "grep_search", "grep_file"],
            "code_write": ["edit_local_file", "create_new_file", "create_file"],
            "code_analysis": ["analyze_code", "get_code_structure", "get_function_structure"],
            "search": ["web_search", "search_code", "grep_search"],
            "memory": ["read_memory", "write_memory", "read_dynamic_prompt"],
            "task": ["set_plan", "set_generation_task", "tick_subtask"],
            "system": ["trigger_self_restart_tool", "compress_context", "enter_hibernation"],
        }
        for category, tools in task_categories.items():
            if tool_name in tools:
                return category
        return "general"

    def _build_decision_context(self, user_prompt: str) -> "DecisionContext":
        """构建决策上下文"""
        from core.decision.decision_tree import DecisionContext
        state = {
            "user_prompt": user_prompt,
            "generation": get_generation_tool(),
            "has_task": bool(get_current_goal()),
            "iteration": 1,
            "exploration_mode": getattr(self.config.agent, 'exploration_mode', False),
        }
        history = self.global_recent_actions[-10:] if hasattr(self, 'global_recent_actions') else []
        return DecisionContext(state=state, history=history)

    def _apply_strategy_adjustments(self, decision_result) -> None:
        """根据决策结果调整策略"""
        if not decision_result:
            return
        action = decision_result.selected_action
        if "探索" in action or "explore" in action.lower():
            if hasattr(self.strategy_selector, '_config'):
                self.strategy_selector._config["exploration_rate"] = 0.4
        elif "利用" in action or "exploit" in action.lower():
            if hasattr(self.strategy_selector, '_config'):
                self.strategy_selector._config["exploration_rate"] = 0.1

    def _optimize_tool_order(self, tool_calls: List[Dict]) -> List[Dict]:
        """使用优先级优化器调整工具执行顺序"""
        if not tool_calls or not hasattr(self, 'priority_optimizer'):
            return tool_calls

        tasks = []
        for i, tc in enumerate(tool_calls):
            tool_name = tc.get('name', 'unknown')
            task_id = f"tool_{i}_{tool_name}"
            task = Task(
                task_id=task_id,
                name=f"{tool_name}",
                description=f"工具调用: {tool_name}",
                priority=0.5,
                estimated_time=0.1,
                metadata={"type": self._classify_task_type(tool_name)},
            )
            self.priority_optimizer.add_task(task)
            tasks.append((tc, task_id))

        # 优化任务顺序
        result = self.priority_optimizer.optimize(context={"tool_count": len(tool_calls)})
        task_order = result.task_order

        # 根据优化结果重新排序
        order_map = {tid: i for i, tid in enumerate(task_order)}
        sorted_calls = sorted(
            tool_calls,
            key=lambda tc: order_map.get(f"tool_{[i for i, (c, tid) in enumerate(tasks) if c == tc][0]}_{tc.get('name')}", 999)
            if any(c == tc for _, tid in tasks for i, (c, tid2) in enumerate(tasks) if tid == tid2)
            else 999
        )
        return sorted_calls

    def _handle_tool_result(self, tool_call: Dict, result, action, messages: list):
        """处理工具执行结果"""
        # 工具结果截断：防止超长输出（如搜索 500 匹配）污染上下文
        MAX_TOOL_RESULT_CHARS = 4000  # ~1000 tokens
        result_str = str(result)
        truncated = False
        if len(result_str) > MAX_TOOL_RESULT_CHARS:
            result_str = (
                result_str[:MAX_TOOL_RESULT_CHARS]
                + f"\n[...结果已截断，原长度 {len(result_str)} 字符...]"
            )
            truncated = True

        if action == "restart":
            logger.log_action("restart", {"tool": tool_call['name']})
        elif action == "skip":
            logger.log_action("skip", {"tool": tool_call['name']})
            messages.append(ToolMessage(content=result_str, tool_call_id=tool_call['id']))
        elif action == "hibernated":
            logger.log_action("hibernated", {"tool": tool_call['name']})
            messages.append(ToolMessage(content=result_str, tool_call_id=tool_call['id']))
        else:
            messages.append(ToolMessage(content=result_str, tool_call_id=tool_call['id']))

        if truncated:
            _debug_logger.warning(
                f"[工具] {tool_call['name']} 结果过长，已截断至 {MAX_TOOL_RESULT_CHARS} 字符", tag="TOOL"
            )

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
    ui.console.print("[bold cyan]+==============================================================+[/bold cyan]")
    ui.console.print("[bold cyan]|                                                              |[/bold cyan]")
    ui.console.print("[bold cyan]|[bold white] Self-Evolving Agent[/bold white] - Terminal Edition             |[/bold cyan]")
    ui.console.print("[bold cyan]|                                                              |[/bold cyan]")
    ui.console.print("[bold cyan]+==============================================================+[/bold cyan]")

    # 打印 ASCII Art 宠物形象
    from core.ui.ascii_art import get_avatar_manager
    avatar = get_avatar_manager()
    pet_art = avatar.get_art('happy')
    ui.console.print(f"[bright_cyan]{pet_art}[/bright_cyan]")
    ui.console.print()

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
