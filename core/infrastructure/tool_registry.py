#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tool Registry (工具注册表)

Phase 7 核心模块

功能：
- 统一的工具注册接口
- 动态工具发现
- 工具元数据管理
- 工具分类和搜索
- 工具使用统计
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
from enum import Enum


# ============================================================================
# 工具定义
# ============================================================================

class ToolCategory(Enum):
    """工具类别"""
    SHELL = "shell"
    MEMORY = "memory"
    CODE_ANALYSIS = "code_analysis"
    SEARCH = "search"
    REBIRTH = "rebirth"
    SYSTEM = "system"
    CUSTOM = "custom"


@dataclass
class ToolMetadata:
    """工具元数据"""
    name: str
    description: str = ""
    category: ToolCategory = ToolCategory.CUSTOM
    parameters: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_duration: float = 0.0
    last_used: Optional[datetime] = None


@dataclass
class ToolRegistration:
    """工具注册信息"""
    name: str
    func: Callable
    metadata: ToolMetadata
    timeout: float = 30.0
    enabled: bool = True


# ============================================================================
# Tool Registry
# ============================================================================

class ToolRegistry:
    """
    工具注册表

    统一管理所有工具：
    - 工具注册和发现
    - 工具元数据管理
    - 工具使用统计
    - 工具分类和搜索

    使用方式：
        registry = ToolRegistry()
        registry.register("my_tool", my_function, metadata)
        result = registry.execute("my_tool", args)
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化工具注册表

        Args:
            project_root: 项目根目录
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 工具存储
        self._tools: Dict[str, ToolRegistration] = {}
        self._categories: Dict[ToolCategory, Set[str]] = defaultdict(set)

        # 统计
        self._stats = {
            "total_registrations": 0,
            "total_executions": 0,
            "total_errors": 0,
        }

        # 加载已有工具
        self._load_default_tools()

    def _load_default_tools(self) -> None:
        """加载默认工具"""
        # 尝试导入并注册 Key_Tools
        try:
            from tools import Key_Tools
            key_tools = Key_Tools.create_key_tools()
            for tool in key_tools:
                metadata = ToolMetadata(
                    name=tool.name,
                    description=tool.description or "",
                    category=ToolCategory.CUSTOM,
                )
                self.register(
                    name=tool.name,
                    func=tool,
                    metadata=metadata,
                    enabled=True,
                )
        except ImportError:
            pass

    def register(
        self,
        name: str,
        func: Callable,
        metadata: Optional[ToolMetadata] = None,
        timeout: float = 30.0,
        enabled: bool = True,
        category: Optional[ToolCategory] = None,
    ) -> bool:
        """
        注册工具

        Args:
            name: 工具名称
            func: 工具函数
            metadata: 工具元数据
            timeout: 超时时间（秒）
            enabled: 是否启用
            category: 工具类别

        Returns:
            是否成功
        """
        if metadata is None:
            metadata = ToolMetadata(name=name, description="")

        if category is not None:
            metadata.category = category

        registration = ToolRegistration(
            name=name,
            func=func,
            metadata=metadata,
            timeout=timeout,
            enabled=enabled,
        )

        self._tools[name] = registration
        self._categories[metadata.category].add(name)
        self._stats["total_registrations"] += 1

        return True

    def unregister(self, name: str) -> bool:
        """
        注销工具

        Args:
            name: 工具名称

        Returns:
            是否成功
        """
        if name not in self._tools:
            return False

        registration = self._tools[name]
        category = registration.metadata.category
        self._categories[category].discard(name)

        del self._tools[name]
        return True

    def get_tool(self, name: str) -> Optional[ToolRegistration]:
        """获取工具"""
        return self._tools.get(name)

    def is_registered(self, name: str) -> bool:
        """检查工具是否已注册"""
        return name in self._tools

    def list_tools(
        self,
        category: Optional[ToolCategory] = None,
        enabled_only: bool = False,
    ) -> List[str]:
        """
        列出工具

        Args:
            category: 类别过滤
            enabled_only: 只返回启用的工具

        Returns:
            工具名称列表
        """
        if category is not None:
            names = list(self._categories.get(category, set()))
        else:
            names = list(self._tools.keys())

        if enabled_only:
            names = [n for n in names if self._tools[n].enabled]

        return names

    def get_tools_by_category(self, category: ToolCategory) -> List[ToolRegistration]:
        """按类别获取工具"""
        names = self._categories.get(category, set())
        return [self._tools[n] for n in names if n in self._tools]

    def search(self, query: str) -> List[str]:
        """
        搜索工具

        Args:
            query: 搜索关键词

        Returns:
            匹配的工具名称列表
        """
        query_lower = query.lower()
        results = []

        for name, reg in self._tools.items():
            metadata = reg.metadata
            if (query_lower in name.lower() or
                query_lower in metadata.description.lower() or
                any(query_lower in tag.lower() for tag in metadata.tags)):
                results.append(name)

        return results

    def execute(
        self,
        name: str,
        args: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """
        执行工具

        Args:
            name: 工具名称
            args: 工具参数

        Returns:
            (结果, 动作)
        """
        if name not in self._tools:
            return (f"工具 '{name}' 未注册", None)

        registration = self._tools[name]

        if not registration.enabled:
            return (f"工具 '{name}' 已禁用", None)

        if args is None:
            args = {}

        import time
        start_time = time.time()

        try:
            result = registration.func(**args)
            duration = time.time() - start_time

            # 更新统计
            registration.metadata.usage_count += 1
            registration.metadata.success_count += 1
            registration.metadata.total_duration += duration
            registration.metadata.last_used = datetime.now()
            self._stats["total_executions"] += 1

            return (result, None)

        except Exception as e:
            duration = time.time() - start_time

            # 更新统计
            registration.metadata.usage_count += 1
            registration.metadata.failure_count += 1
            registration.metadata.total_duration += duration
            registration.metadata.last_used = datetime.now()
            self._stats["total_executions"] += 1
            self._stats["total_errors"] += 1

            return (f"工具执行错误: {type(e).__name__}: {e}", None)

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        tool_stats = []
        for name, reg in self._tools.items():
            metadata = reg.metadata
            success_rate = (
                metadata.success_count / metadata.usage_count
                if metadata.usage_count > 0 else 0
            )
            avg_duration = (
                metadata.total_duration / metadata.usage_count
                if metadata.usage_count > 0 else 0
            )
            tool_stats.append({
                "name": name,
                "category": metadata.category.value,
                "usage_count": metadata.usage_count,
                "success_rate": success_rate,
                "avg_duration": avg_duration,
                "enabled": reg.enabled,
            })

        return {
            **self._stats,
            "total_tools": len(self._tools),
            "tools_by_category": {
                cat.value: len(tools)
                for cat, tools in self._categories.items()
            },
            "tool_details": tool_stats,
        }

    def get_tool_info(self, name: str) -> Optional[Dict[str, Any]]:
        """获取工具详细信息"""
        if name not in self._tools:
            return None

        reg = self._tools[name]
        metadata = reg.metadata

        return {
            "name": metadata.name,
            "description": metadata.description,
            "category": metadata.category.value,
            "tags": metadata.tags,
            "examples": metadata.examples,
            "timeout": reg.timeout,
            "enabled": reg.enabled,
            "usage_count": metadata.usage_count,
            "success_count": metadata.success_count,
            "failure_count": metadata.failure_count,
            "success_rate": (
                metadata.success_count / metadata.usage_count
                if metadata.usage_count > 0 else 0
            ),
            "avg_duration": (
                metadata.total_duration / metadata.usage_count
                if metadata.usage_count > 0 else 0
            ),
            "last_used": metadata.last_used.isoformat() if metadata.last_used else None,
        }

    def enable(self, name: str) -> bool:
        """启用工具"""
        if name not in self._tools:
            return False
        self._tools[name].enabled = True
        return True

    def disable(self, name: str) -> bool:
        """禁用工具"""
        if name not in self._tools:
            return False
        self._tools[name].enabled = False
        return True

    def save_to_file(self, file_path: Optional[str] = None) -> str:
        """保存工具注册表到文件"""
        if file_path is None:
            file_path = str(
                self.project_root / "workspace" / "tools" / "tool_registry.json"
            )

        data = {
            "tools": [
                {
                    "name": reg.name,
                    "category": reg.metadata.category.value,
                    "description": reg.metadata.description,
                    "tags": reg.metadata.tags,
                    "timeout": reg.timeout,
                    "enabled": reg.enabled,
                    "usage_count": reg.metadata.usage_count,
                    "success_count": reg.metadata.success_count,
                    "failure_count": reg.metadata.failure_count,
                }
                for reg in self._tools.values()
            ],
            "stats": self._stats,
        }

        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return file_path

    def load_from_file(self, file_path: str) -> int:
        """从文件加载工具注册表"""
        if not Path(file_path).exists():
            return 0

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        loaded = 0
        for tool_data in data.get("tools", []):
            category = ToolCategory(tool_data.get("category", "custom"))
            metadata = ToolMetadata(
                name=tool_data["name"],
                description=tool_data.get("description", ""),
                category=category,
                tags=tool_data.get("tags", []),
            )
            metadata.usage_count = tool_data.get("usage_count", 0)
            metadata.success_count = tool_data.get("success_count", 0)
            metadata.failure_count = tool_data.get("failure_count", 0)

            # 只加载统计信息，不重新注册
            if tool_data["name"] in self._tools:
                self._tools[tool_data["name"]].metadata.usage_count = metadata.usage_count
                self._tools[tool_data["name"]].metadata.success_count = metadata.success_count
                self._tools[tool_data["name"]].metadata.failure_count = metadata.failure_count
                loaded += 1

        return loaded


# ============================================================================
# 全局单例
# ============================================================================

_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry(project_root: Optional[str] = None) -> ToolRegistry:
    """获取工具注册表单例"""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry(project_root)
    return _tool_registry


def reset_tool_registry() -> None:
    """重置工具注册表"""
    global _tool_registry
    _tool_registry = None
