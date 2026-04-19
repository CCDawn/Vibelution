#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent Session 状态管理模块

职责：
- 管理 Agent Session 级别的状态
- recent_actions: 最近N个动作
- consecutive_count: 连续动作计数
- self_modified: Agent是否自我修改
- start_time: 启动时间

使用方式：
    from core.infrastructure.agent_session import get_session_state, reset_session

    session = get_session_state()
    session.record_action("tool_call", tool_name)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Any


@dataclass
class AgentSessionState:
    """Agent Session 状态"""
    recent_actions: List[str] = field(default_factory=list)
    consecutive_count: int = 0
    _self_modified: bool = False
    start_time: datetime = field(default_factory=datetime.now)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_action(self, action_type: str, action_detail: str = ""):
        """记录一个动作"""
        with self._lock:
            action_str = f"{action_type}:{action_detail}" if action_detail else action_type
            self.recent_actions.append(action_str)
            if len(self.recent_actions) > 50:  # 保留最近50个
                self.recent_actions.pop(0)
            self.consecutive_count += 1

    def reset_consecutive(self):
        """重置连续计数"""
        with self._lock:
            self.consecutive_count = 0

    @property
    def self_modified(self) -> bool:
        """是否自我修改过"""
        return self._self_modified

    @self_modified.setter
    def self_modified(self, value: bool):
        """设置自我修改标志"""
        self._self_modified = value

    def mark_modified(self):
        """标记为已修改"""
        self._self_modified = True

    def clear_modified(self):
        """清除修改标志"""
        self._self_modified = False

    def get_uptime(self) -> float:
        """获取运行时长（秒）"""
        return (datetime.now() - self.start_time).total_seconds()

    def get_recent_history(self, count: int = 10) -> List[str]:
        """获取最近N个动作"""
        with self._lock:
            return self.recent_actions[-count:]


# 单例实例
_agent_session: Optional[AgentSessionState] = None
_session_lock = threading.Lock()


def get_session_state() -> AgentSessionState:
    """获取全局 Session 状态单例"""
    global _agent_session
    if _agent_session is None:
        with _session_lock:
            if _agent_session is None:
                _agent_session = AgentSessionState()
    return _agent_session


def reset_session():
    """重置 Session 状态（用于测试）"""
    global _agent_session
    with _session_lock:
        _agent_session = AgentSessionState()


__all__ = [
    "AgentSessionState",
    "get_session_state",
    "reset_session",
]
