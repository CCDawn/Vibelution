#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent 核心类 (AgentCore) - 模块化 Agent 架构

Phase 4 核心模块

设计原则：
- 单一职责：每个组件只负责一件事
- 依赖注入：通过构造函数注入依赖
- 事件驱动：组件间通过事件总线通信
- 可测试：每个组件都可独立测试
"""

from __future__ import annotations

import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field


# ============================================================================
# Agent 配置
# ============================================================================

@dataclass
class AgentConfig:
    """Agent 配置"""
    name: str = "虾宝"
    workspace: str = "workspace"
    model_name: str = "gpt-4"
    temperature: float = 0.7
    max_retries: int = 3
    timeout: int = 120


@dataclass
class AgentMetrics:
    """Agent 指标"""
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_tokens_used: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    start_time: Optional[datetime] = None
    last_task_time: Optional[datetime] = None
    consecutive_failures: int = 0


@dataclass
class TaskContext:
    """任务上下文"""
    task_id: str
    description: str
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Agent 核心类
# ============================================================================

class AgentCore:
    """
    Agent 核心类

    模块化的 Agent 架构，将主 Agent 类拆分为多个独立组件：

    架构图：
    ```
    AgentCore (协调器)
    ├── LLMProvider (LLM 提供者)
    ├── ToolRegistry (工具注册表)
    ├── MemoryManager (记忆管理)
    ├── EventBus (事件总线)
    ├── StateManager (状态管理)
    └── SecurityValidator (安全验证)
    ```

    使用方式：
        core = AgentCore(config)
        result = await core.execute_task(task)
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        llm_provider: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
        memory_manager: Optional[Any] = None,
    ):
        """
        初始化 Agent 核心

        Args:
            config: Agent 配置
            llm_provider: LLM 提供者
            tool_registry: 工具注册表
            memory_manager: 记忆管理器
        """
        self.config = config or AgentConfig()
        self.logger = logging.getLogger(f"AgentCore.{self.config.name}")

        # 组件
        self.llm_provider = llm_provider
        self.tool_registry = tool_registry
        self.memory_manager = memory_manager

        # 状态
        self._metrics = AgentMetrics(start_time=datetime.now())
        self._current_task: Optional[TaskContext] = None
        self._running = False

        # 事件处理
        self._event_handlers: Dict[str, List[Callable]] = {}

        # 初始化
        self._init_components()

    def _init_components(self) -> None:
        """初始化组件"""
        self.logger.info("初始化 Agent 核心组件...")

        # 初始化 LLM 提供者
        if self.llm_provider is None:
            self.llm_provider = self._create_default_llm_provider()

        # 初始化工具注册表
        if self.tool_registry is None:
            self.tool_registry = self._create_default_tool_registry()

        # 初始化记忆管理器
        if self.memory_manager is None:
            self.memory_manager = self._create_default_memory_manager()

        self.logger.info("Agent 核心组件初始化完成")

    def _create_default_llm_provider(self) -> "LLMProvider":
        """创建默认 LLM 提供者"""
        try:
            from core.llm_provider import get_llm_provider
            return get_llm_provider(self.config)
        except ImportError:
            return LLMProvider(self.config)

    def _create_default_tool_registry(self) -> "ToolRegistry":
        """创建默认工具注册表"""
        try:
            from core.infrastructure.tool_registry import get_tool_registry
            return get_tool_registry()
        except ImportError:
            return ToolRegistry()

    def _create_default_memory_manager(self) -> "MemoryManager":
        """创建默认记忆管理器"""
        try:
            from core.memory_manager_core import get_memory_manager
            return get_memory_manager()
        except ImportError:
            return MemoryManager()

    # =========================================================================
    # 核心接口
    # =========================================================================

    async def execute_task(self, task: TaskContext) -> TaskContext:
        """
        执行任务

        Args:
            task: 任务上下文

        Returns:
            更新后的任务上下文
        """
        self._current_task = task
        self._running = True
        task.status = "running"

        try:
            self.logger.info(f"开始执行任务: {task.description}")
            self._emit_event("task:started", {"task_id": task.task_id})

            # 执行任务逻辑
            result = await self._execute_task_logic(task)

            task.result = result
            task.status = "completed"
            self._metrics.tasks_completed += 1
            self._metrics.last_task_time = datetime.now()

            self._emit_event("task:completed", {
                "task_id": task.task_id,
                "result": result,
            })

            return task

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            self._metrics.tasks_failed += 1
            self._metrics.consecutive_failures += 1

            self._emit_event("task:failed", {
                "task_id": task.task_id,
                "error": str(e),
            })

            self.logger.error(f"任务执行失败: {e}")
            return task

        finally:
            self._running = False
            self._current_task = None

    async def _execute_task_logic(self, task: TaskContext) -> Any:
        """执行任务逻辑"""
        # 模板方法，由子类重写
        raise NotImplementedError("子类必须实现 _execute_task_logic")

    def process_message(self, message: str) -> str:
        """
        处理用户消息

        Args:
            message: 用户消息

        Returns:
            Agent 响应
        """
        self.logger.info(f"处理消息: {message[:50]}...")

        # 创建任务
        task = TaskContext(
            task_id=f"msg_{datetime.now().timestamp()}",
            description=message,
        )

        # 同步执行
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果已经在运行中，创建新任务
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.execute_task(task)
                    )
                    result = future.result()
            else:
                result = loop.run_until_complete(self.execute_task(task))
        except Exception:
            # 兜底：同步执行
            result = asyncio.run(self.execute_task(task))

        if result.status == "completed":
            return str(result.result) if result.result else "任务完成"
        else:
            return f"任务失败: {result.error}"

    # =========================================================================
    # 事件系统
    # =========================================================================

    def on(self, event_name: str, handler: Callable) -> None:
        """
        注册事件处理器

        Args:
            event_name: 事件名称
            handler: 处理函数
        """
        if event_name not in self._event_handlers:
            self._event_handlers[event_name] = []
        self._event_handlers[event_name].append(handler)

    def off(self, event_name: str, handler: Callable) -> None:
        """
        注销事件处理器

        Args:
            event_name: 事件名称
            handler: 处理函数
        """
        if event_name in self._event_handlers:
            self._event_handlers[event_name].remove(handler)

    def _emit_event(self, event_name: str, data: Dict[str, Any]) -> None:
        """发射事件"""
        if event_name in self._event_handlers:
            for handler in self._event_handlers[event_name]:
                try:
                    handler(data)
                except Exception as e:
                    self.logger.error(f"事件处理器执行失败: {e}")

    # =========================================================================
    # 状态管理
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        return {
            "name": self.config.name,
            "running": self._running,
            "current_task": self._current_task.task_id if self._current_task else None,
            "metrics": {
                "tasks_completed": self._metrics.tasks_completed,
                "tasks_failed": self._metrics.tasks_failed,
                "llm_calls": self._metrics.llm_calls,
                "tool_calls": self._metrics.tool_calls,
                "uptime": (datetime.now() - self._metrics.start_time).total_seconds() if self._metrics.start_time else 0,
            },
        }

    def pause(self) -> bool:
        """暂停"""
        if self._running:
            self._emit_event("agent:paused", {})
            return True
        return False

    def resume(self) -> bool:
        """恢复"""
        self._emit_event("agent:resumed", {})
        return True

    def reset_metrics(self) -> None:
        """重置指标"""
        self._metrics = AgentMetrics(start_time=datetime.now())


# ============================================================================
# LLM 提供者
# ============================================================================

class LLMProvider:
    """LLM 提供者"""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.logger = logging.getLogger("LLMProvider")

    async def call(self, messages: List[Any], tools: Optional[List] = None) -> Any:
        """调用 LLM"""
        raise NotImplementedError("子类必须实现 call 方法")

    def get_model_name(self) -> str:
        """获取模型名称"""
        return self.config.model_name


# ============================================================================
# 工具注册表
# ============================================================================

class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: Dict[str, Any] = {}
        self.logger = logging.getLogger("ToolRegistry")

    def register(self, name: str, tool: Any) -> None:
        """注册工具"""
        self._tools[name] = tool
        self.logger.debug(f"注册工具: {name}")

    def unregister(self, name: str) -> None:
        """注销工具"""
        if name in self._tools:
            del self._tools[name]

    def get(self, name: str) -> Optional[Any]:
        """获取工具"""
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """列出所有工具"""
        return list(self._tools.keys())

    def get_by_category(self, category: str) -> List[Any]:
        """按类别获取工具"""
        # 简单的按名称前缀分类
        result = []
        prefix = f"{category}_"
        for name, tool in self._tools.items():
            if name.startswith(prefix) or category in name:
                result.append(tool)
        return result


# ============================================================================
# 记忆管理器
# ============================================================================

class MemoryManager:
    """记忆管理器"""

    def __init__(self):
        self._memory: Dict[str, Any] = {}
        self._history: List[Dict[str, Any]] = []
        self.logger = logging.getLogger("MemoryManager")

    def store(self, key: str, value: Any) -> None:
        """存储记忆"""
        self._memory[key] = value
        self._history.append({
            "action": "store",
            "key": key,
            "timestamp": datetime.now().isoformat(),
        })

    def retrieve(self, key: str, default: Any = None) -> Any:
        """检索记忆"""
        return self._memory.get(key, default)

    def forget(self, key: str) -> None:
        """遗忘记忆"""
        if key in self._memory:
            del self._memory[key]
            self._history.append({
                "action": "forget",
                "key": key,
                "timestamp": datetime.now().isoformat(),
            })

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取历史"""
        return self._history[-limit:]


# ============================================================================
# 全局单例
# ============================================================================

_agent_core: Optional[AgentCore] = None


def get_agent_core(config: Optional[AgentConfig] = None) -> AgentCore:
    """获取 Agent 核心单例"""
    global _agent_core
    if _agent_core is None:
        _agent_core = AgentCore(config)
    return _agent_core


def reset_agent_core() -> None:
    """重置 Agent 核心"""
    global _agent_core
    _agent_core = None
