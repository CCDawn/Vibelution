"""
状态管理模块 - 统一管理 Agent 的运行时状态

从 agent.py 中提取的状态管理逻辑，提供：
- AgentState: Agent 状态枚举
- StateManager: 状态管理器
- 状态持久化支持

使用方式:
    from core.state import get_state_manager, AgentState

    state = get_state_manager()
    state.set_state(AgentState.THINKING)
    state.get_state()
"""

from __future__ import annotations

import os
import json
import threading
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum


# ============================================================================
# 状态枚举
# ============================================================================

class AgentState(Enum):
    """Agent 状态枚举"""
    IDLE = "idle"
    AWAKENING = "awakening"
    THINKING = "thinking"
    SEARCHING = "searching"
    CODING = "coding"
    TESTING = "testing"
    COMPRESSING = "compressing"
    HIBERNATING = "hibernating"
    RESTARTING = "restarting"
    PLANNING = "planning"
    ERROR = "error"


# ============================================================================
# 状态记录
# ============================================================================

@dataclass
class StateRecord:
    """状态记录"""
    state: str
    timestamp: str
    action: Optional[str] = None
    iteration_count: Optional[int] = None
    tools_executed: Optional[int] = None
    generation: Optional[int] = None
    current_goal: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# 状态管理器
# ============================================================================

class StateManager:
    """
    Agent 状态管理器

    负责：
    - 跟踪 Agent 的当前状态
    - 记录状态转换历史
    - 管理全局操作历史（防止重复操作）
    - 持久化状态到文件

    特性：
    - 单例模式
    - 线程安全
    - 支持状态历史回溯
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return

        self._initialized = True
        self._state = AgentState.IDLE
        self._previous_state: Optional[AgentState] = None
        self._action: Optional[str] = None
        self._state_history: List[StateRecord] = []
        self._max_history = 100

        # 全局操作历史（跨苏醒周期）
        self._recent_actions: List[str] = []
        self._consecutive_count: int = 0

        # 状态元数据
        self._iteration_count: int = 0
        self._tools_executed: int = 0
        self._generation: int = 1
        self._current_goal: Optional[str] = None

        # 锁
        self._state_lock = threading.Lock()

        # 事件总线（用于状态变更通知）
        try:
            from core.infrastructure.event_bus import get_event_bus, EventNames
            self._event_bus = get_event_bus()
            self._event_names = EventNames
        except ImportError:
            self._event_bus = None
            self._event_names = None

    @property
    def state(self) -> AgentState:
        """获取当前状态"""
        return self._state

    @property
    def previous_state(self) -> Optional[AgentState]:
        """获取前一个状态"""
        return self._previous_state

    def set_state(
        self,
        state: AgentState,
        action: Optional[str] = None,
        iteration_count: Optional[int] = None,
        tools_executed: Optional[int] = None,
        generation: Optional[int] = None,
        current_goal: Optional[str] = None,
        **metadata
    ) -> None:
        """
        设置新状态

        Args:
            state: 新状态
            action: 当前动作描述
            iteration_count: 迭代计数
            tools_executed: 已执行工具数
            generation: 当前世代
            current_goal: 当前目标
            **metadata: 其他元数据
        """
        with self._state_lock:
            self._previous_state = self._state
            self._state = state

            # 更新元数据
            if action is not None:
                self._action = action
            if iteration_count is not None:
                self._iteration_count = iteration_count
            if tools_executed is not None:
                self._tools_executed = tools_executed
            if generation is not None:
                self._generation = generation
            if current_goal is not None:
                self._current_goal = current_goal

            # 记录历史
            record = StateRecord(
                state=state.value,
                timestamp=datetime.now().isoformat(),
                action=self._action,
                iteration_count=self._iteration_count,
                tools_executed=self._tools_executed,
                generation=self._generation,
                current_goal=self._current_goal,
                metadata=metadata,
            )
            self._state_history.append(record)

            # 限制历史长度
            if len(self._state_history) > self._max_history:
                self._state_history.pop(0)

            # 发布状态变更事件
            if self._event_bus is not None:
                self._event_bus.publish(
                    "state:change",
                    data={
                        "previous": self._previous_state.value if self._previous_state else None,
                        "current": state.value,
                        "action": action,
                    },
                    source="StateManager"
                )

    def get_state(self) -> AgentState:
        """获取当前状态"""
        return self._state

    def is_state(self, state: AgentState) -> bool:
        """检查是否是指定状态"""
        return self._state == state

    def is_any_state(self, *states: AgentState) -> bool:
        """检查是否是任意指定状态"""
        return self._state in states

    def get_state_info(self) -> Dict[str, Any]:
        """获取完整的状态信息"""
        return {
            "state": self._state.value,
            "previous_state": self._previous_state.value if self._previous_state else None,
            "action": self._action,
            "iteration_count": self._iteration_count,
            "tools_executed": self._tools_executed,
            "generation": self._generation,
            "current_goal": self._current_goal,
        }

    def get_history(self, limit: int = 10) -> List[StateRecord]:
        """获取状态历史"""
        return self._state_history[-limit:]

    # =========================================================================
    # 全局操作历史管理（防止重复操作）
    # =========================================================================

    def add_recent_action(self, action: str) -> None:
        """
        添加最近执行的操作

        用于跨苏醒周期跟踪，防止 Agent 重复执行相同的操作。
        """
        with self._state_lock:
            if self._recent_actions and self._recent_actions[-1] == action:
                self._consecutive_count += 1
            else:
                self._consecutive_count = 1
                self._recent_actions.append(action)

            # 限制历史长度
            if len(self._recent_actions) > 50:
                self._recent_actions = self._recent_actions[-50:]

    def is_action_recent(self, action: str, threshold: int = 3) -> bool:
        """检查操作是否最近执行过"""
        with self._state_lock:
            if not self._recent_actions:
                return False
            return self._recent_actions[-1] == action and self._consecutive_count >= threshold

    def get_consecutive_count(self) -> int:
        """获取连续执行同一操作的次数"""
        return self._consecutive_count

    def clear_recent_actions(self) -> None:
        """清除最近操作历史"""
        with self._state_lock:
            self._recent_actions.clear()
            self._consecutive_count = 0

    # =========================================================================
    # 世代管理
    # =========================================================================

    def set_generation(self, generation: int) -> None:
        """设置当前世代"""
        with self._state_lock:
            self._generation = generation

    def get_generation(self) -> int:
        """获取当前世代"""
        return self._generation

    def set_current_goal(self, goal: str) -> None:
        """设置当前目标"""
        with self._state_lock:
            self._current_goal = goal

    def get_current_goal(self) -> Optional[str]:
        """获取当前目标"""
        return self._current_goal

    # =========================================================================
    # 计数管理
    # =========================================================================

    def increment_iteration(self) -> None:
        """增加迭代计数"""
        with self._state_lock:
            self._iteration_count += 1

    def increment_tools_executed(self) -> None:
        """增加工具执行计数"""
        with self._state_lock:
            self._tools_executed += 1

    def reset_counters(self) -> None:
        """重置计数器"""
        with self._state_lock:
            self._iteration_count = 0
            self._tools_executed = 0

    # =========================================================================
    # 状态持久化
    # =========================================================================

    def save_state(self, filepath: Optional[str] = None) -> str:
        """
        保存状态到文件

        Args:
            filepath: 文件路径，默认保存到 agent_state.json

        Returns:
            保存的文件路径
        """
        if filepath is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            filepath = os.path.join(project_root, "agent_state.json")

        state_data = {
            "state": self._state.value,
            "generation": self._generation,
            "current_goal": self._current_goal,
            "iteration_count": self._iteration_count,
            "tools_executed": self._tools_executed,
            "recent_actions": self._recent_actions[-10:],  # 只保存最近10个
            "consecutive_count": self._consecutive_count,
            "saved_at": datetime.now().isoformat(),
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)

        return filepath

    def load_state(self, filepath: Optional[str] = None) -> bool:
        """
        从文件加载状态

        Args:
            filepath: 文件路径

        Returns:
            是否成功加载
        """
        if filepath is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            filepath = os.path.join(project_root, "agent_state.json")

        if not os.path.exists(filepath):
            return False

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                state_data = json.load(f)

            self._state = AgentState(state_data.get("state", "idle"))
            self._generation = state_data.get("generation", 1)
            self._current_goal = state_data.get("current_goal")
            self._iteration_count = state_data.get("iteration_count", 0)
            self._tools_executed = state_data.get("tools_executed", 0)
            self._recent_actions = state_data.get("recent_actions", [])
            self._consecutive_count = state_data.get("consecutive_count", 0)

            return True
        except Exception as e:
            from core.logging import debug_logger
            debug_logger.error(f"[StateManager] 加载状态失败: {e}")
            return False

    # =========================================================================
    # 重置
    # =========================================================================

    def reset(self) -> None:
        """重置状态管理器"""
        with self._state_lock:
            self._state = AgentState.IDLE
            self._previous_state = None
            self._action = None
            self._state_history.clear()
            self._iteration_count = 0
            self._tools_executed = 0
            self._recent_actions.clear()
            self._consecutive_count = 0


# ============================================================================
# 全局单例
# ============================================================================

_state_manager: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """获取状态管理器单例"""
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager


# ============================================================================
# 便捷函数
# ============================================================================

def get_current_state() -> AgentState:
    """获取当前状态"""
    return get_state_manager().get_state()
