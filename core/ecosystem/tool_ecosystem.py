#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具生态系统 (Tool Ecosystem) - Phase 8 模块

包含：
- DynamicLoader - 动态工具加载
- CompositeTool - 复合工具定义和执行
- PluginManager - 插件管理和热加载

Phase 8.4 模块
"""

from __future__ import annotations

import os
import sys
import json
import importlib
import inspect
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import threading


# ============================================================================
# 数据结构
# ============================================================================

class ToolType(Enum):
    """工具类型"""
    BASIC = "basic"             # 基础工具
    COMPOSITE = "composite"     # 复合工具
    PLUGIN = "plugin"           # 插件工具
    DYNAMIC = "dynamic"          # 动态加载


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    tool_type: ToolType
    function: Optional[Callable] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    category: str = "general"
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompositeToolSpec:
    """复合工具规范"""
    name: str
    description: str
    steps: List["ToolStep"]
    parameters: Dict[str, Any] = field(default_factory=dict)
    output_mapping: Dict[str, str] = field(default_factory=dict)


@dataclass
class ToolStep:
    """工具步骤"""
    tool_name: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    input_mapping: Dict[str, str] = field(default_factory=dict)  # 从前一步输出映射
    condition: Optional[str] = None  # 条件表达式
    retry_on_failure: bool = False
    max_retries: int = 3


@dataclass
class PluginInfo:
    """插件信息"""
    plugin_id: str
    name: str
    version: str
    description: str
    author: str
    entry_point: str
    tools: List[str] = field(default_factory=list)
    enabled: bool = True
    loaded_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionRecord:
    """执行记录"""
    tool_name: str
    success: bool
    duration_seconds: float
    output: Any
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ============================================================================
# 动态工具加载器
# ============================================================================

class DynamicLoader:
    """
    动态工具加载器

    功能：
    - 动态发现和加载工具
    - 工具自动注册
    - 运行时工具刷新
    """

    def __init__(self, project_root: Optional[str] = None):
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        self.project_root = Path(project_root)
        self._tools: Dict[str, ToolDefinition] = {}
        self._lock = threading.Lock()
        self._discovery_paths = [
            self.project_root / "tools",
        ]

    def register_tool(self, tool: ToolDefinition) -> None:
        """注册工具"""
        with self._lock:
            self._tools[tool.name] = tool

    def unregister_tool(self, name: str) -> bool:
        """注销工具"""
        with self._lock:
            if name in self._tools:
                del self._tools[name]
                return True
            return False

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """获取工具"""
        return self._tools.get(name)

    def list_tools(
        self,
        tool_type: Optional[ToolType] = None,
        category: Optional[str] = None,
    ) -> List[ToolDefinition]:
        """列出工具"""
        tools = list(self._tools.values())

        if tool_type:
            tools = [t for t in tools if t.tool_type == tool_type]

        if category:
            tools = [t for t in tools if t.category == category]

        return tools

    def discover_tools(self, reload: bool = False) -> int:
        """
        发现并加载工具

        Args:
            reload: 是否重新加载

        Returns:
            加载的工具数量
        """
        count = 0

        for path in self._discovery_paths:
            if not path.exists():
                continue

            for py_file in path.rglob("*.py"):
                if py_file.name.startswith("_"):
                    continue

                try:
                    tools = self._load_tools_from_file(py_file, reload)
                    count += len(tools)
                except Exception:
                    continue

        return count

    def _load_tools_from_file(
        self,
        file_path: Path,
        reload: bool = False,
    ) -> List[ToolDefinition]:
        """从文件加载工具"""
        tools = []
        module_name = str(file_path.relative_to(self.project_root)).replace(os.sep, ".")[:-3]

        try:
            module = importlib.import_module(module_name)

            # 查找导出的工具
            for name, obj in inspect.getmembers(module):
                if inspect.isfunction(obj) and not name.startswith("_"):
                    tool_def = self._create_tool_definition(name, obj, module_name)
                    if tool_def:
                        with self._lock:
                            self._tools[tool_def.name] = tool_def
                        tools.append(tool_def)

        except Exception:
            pass

        return tools

    def _create_tool_definition(
        self,
        name: str,
        func: Callable,
        module_name: str,
    ) -> Optional[ToolDefinition]:
        """创建工具定义"""
        doc = inspect.getdoc(func) or ""

        return ToolDefinition(
            name=name,
            description=doc.split("\n")[0] if doc else name,
            tool_type=ToolType.DYNAMIC,
            function=func,
            parameters=self._extract_parameters(func),
        )

    def _extract_parameters(self, func: Callable) -> Dict[str, Any]:
        """提取函数参数"""
        try:
            sig = inspect.signature(func)
            return {
                name: {
                    "type": str(p.annotation) if p.annotation != inspect.Parameter.empty else "Any",
                    "default": p.default if p.default != inspect.Parameter.empty else None,
                    "required": p.default == inspect.Parameter.empty,
                }
                for name, p in sig.parameters.items()
            }
        except Exception:
            return {}


# ============================================================================
# 复合工具管理器
# ============================================================================

class CompositeToolManager:
    """
    复合工具管理器

    功能：
    - 定义复合工具
    - 执行复合工具
    - 参数传递和映射
    """

    def __init__(self, tool_executor: Optional[Any] = None):
        self.tool_executor = tool_executor
        self._composite_tools: Dict[str, CompositeToolSpec] = {}
        self._execution_history: List[ExecutionRecord] = []

    def register_composite(
        self,
        spec: CompositeToolSpec,
    ) -> str:
        """注册复合工具"""
        self._composite_tools[spec.name] = spec
        return spec.name

    def get_composite(self, name: str) -> Optional[CompositeToolSpec]:
        """获取复合工具"""
        return self._composite_tools.get(name)

    def list_composites(self) -> List[CompositeToolSpec]:
        """列出所有复合工具"""
        return list(self._composite_tools.values())

    def execute(
        self,
        name: str,
        initial_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        执行复合工具

        Args:
            name: 复合工具名称
            initial_params: 初始参数

        Returns:
            执行结果
        """
        spec = self._composite_tools.get(name)
        if not spec:
            raise ValueError(f"复合工具 '{name}' 不存在")

        # 初始化上下文
        context = {"params": initial_params, "outputs": {}}
        results = []

        for step in spec.steps:
            try:
                result = self._execute_step(step, context)
                context["outputs"][step.tool_name] = result
                results.append(result)

                # 检查条件
                if step.condition and not self._evaluate_condition(step.condition, context):
                    continue

            except Exception as e:
                if step.retry_on_failure:
                    for retry in range(step.max_retries - 1):
                        try:
                            result = self._execute_step(step, context)
                            context["outputs"][step.tool_name] = result
                            break
                        except Exception:
                            continue
                else:
                    raise

        return {
            "success": True,
            "outputs": context["outputs"],
            "results": results,
        }

    def _execute_step(
        self,
        step: ToolStep,
        context: Dict[str, Any],
    ) -> Any:
        """执行单个步骤"""
        # 解析参数
        params = self._resolve_parameters(step.parameters, context)

        # 调用工具执行器
        if self.tool_executor:
            result, _ = self.tool_executor.execute(step.tool_name, params)
            return result

        # 直接调用（如果没有执行器）
        from core.infrastructure.tool_executor import get_tool_executor
        executor = get_tool_executor()
        result, _ = executor.execute(step.tool_name, params)
        return result

    def _resolve_parameters(
        self,
        params: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """解析参数（处理映射）"""
        resolved = {}

        for key, value in params.items():
            if isinstance(value, str) and value.startswith("$"):
                # 引用其他步骤的输出
                resolved[key] = context["outputs"].get(value[1:])
            else:
                resolved[key] = value

        return resolved

    def _evaluate_condition(
        self,
        condition: str,
        context: Dict[str, Any],
    ) -> bool:
        """评估条件"""
        try:
            # 简单的条件评估
            return eval(condition, {"context": context})
        except Exception:
            return False


# ============================================================================
# 插件管理器
# ============================================================================

class PluginManager:
    """
    插件管理器

    功能：
    - 插件发现和加载
    - 插件热加载/卸载
    - 插件生命周期管理
    """

    def __init__(self, plugin_dir: Optional[str] = None):
        if plugin_dir is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            plugin_dir = os.path.join(project_root, "tools", "plugins")

        self.plugin_dir = Path(plugin_dir)
        self.plugin_dir.mkdir(parents=True, exist_ok=True)

        self._plugins: Dict[str, PluginInfo] = {}
        self._loaded_modules: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def discover_plugins(self) -> List[PluginInfo]:
        """发现插件"""
        discovered = []

        if not self.plugin_dir.exists():
            return discovered

        for plugin_path in self.plugin_dir.iterdir():
            if not plugin_path.is_dir():
                continue

            manifest_path = plugin_path / "manifest.json"
            if not manifest_path.exists():
                continue

            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)

                plugin = PluginInfo(
                    plugin_id=manifest.get("id", plugin_path.name),
                    name=manifest.get("name", plugin_path.name),
                    version=manifest.get("version", "1.0.0"),
                    description=manifest.get("description", ""),
                    author=manifest.get("author", ""),
                    entry_point=manifest.get("entry_point", "main"),
                    tools=manifest.get("tools", []),
                    metadata=manifest.get("metadata", {}),
                )

                discovered.append(plugin)

            except Exception:
                continue

        return discovered

    def load_plugin(self, plugin_id: str) -> bool:
        """加载插件"""
        with self._lock:
            # 查找插件
            plugin = None
            for p in self.discover_plugins():
                if p.plugin_id == plugin_id:
                    plugin = p
                    break

            if not plugin:
                return False

            if plugin_id in self._loaded_modules:
                return True  # 已加载

            try:
                # 动态导入插件
                module_name = f"tools.plugins.{plugin_id}.{plugin.entry_point}"
                module = importlib.import_module(module_name)

                self._loaded_modules[plugin_id] = module
                plugin.loaded_at = datetime.now().isoformat()
                plugin.enabled = True

                self._plugins[plugin_id] = plugin
                return True

            except Exception:
                return False

    def unload_plugin(self, plugin_id: str) -> bool:
        """卸载插件"""
        with self._lock:
            if plugin_id in self._loaded_modules:
                del self._loaded_modules[plugin_id]

            if plugin_id in self._plugins:
                self._plugins[plugin_id].enabled = False
                return True

            return False

    def get_plugin(self, plugin_id: str) -> Optional[PluginInfo]:
        """获取插件信息"""
        return self._plugins.get(plugin_id)

    def list_plugins(
        self,
        enabled_only: bool = False,
    ) -> List[PluginInfo]:
        """列出插件"""
        plugins = list(self._plugins.values())

        if enabled_only:
            plugins = [p for p in plugins if p.enabled]

        return plugins

    def reload_plugin(self, plugin_id: str) -> bool:
        """重新加载插件"""
        self.unload_plugin(plugin_id)
        return self.load_plugin(plugin_id)


# ============================================================================
# 工具生态系统整合
# ============================================================================

class ToolEcosystem:
    """
    工具生态系统整合

    整合动态加载、复合工具和插件管理
    """

    def __init__(self, project_root: Optional[str] = None):
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        self.project_root = Path(project_root)

        # 初始化各组件
        self.dynamic_loader = DynamicLoader(project_root)
        self.composite_manager = CompositeToolManager()
        self.plugin_manager = PluginManager()

        # 注册内置复合工具
        self._register_builtin_composites()

    def initialize(self) -> Dict[str, int]:
        """
        初始化生态系统

        Returns:
            初始化统计
        """
        stats = {
            "tools_discovered": 0,
            "composites_registered": 0,
            "plugins_discovered": 0,
        }

        # 发现动态工具
        stats["tools_discovered"] = self.dynamic_loader.discover_tools()

        # 加载插件
        plugins = self.plugin_manager.discover_plugins()
        stats["plugins_discovered"] = len(plugins)
        for plugin in plugins:
            self.plugin_manager.load_plugin(plugin.plugin_id)

        # 统计复合工具
        stats["composites_registered"] = len(self.composite_manager.list_composites())

        return stats

    def _register_builtin_composites(self):
        """注册内置复合工具"""
        # improve_function: 改进函数的完整流程
        self.composite_manager.register_composite(CompositeToolSpec(
            name="improve_function",
            description="改进函数的完整流程",
            steps=[
                ToolStep(
                    tool_name="read_file",
                    parameters={"file_path": "$params.file_path"},
                ),
                ToolStep(
                    tool_name="get_code_entity_tool",
                    parameters={
                        "file_path": "$params.file_path",
                        "entity_name": "$params.function_name",
                    },
                ),
                ToolStep(
                    tool_name="apply_diff_edit",
                    parameters={
                        "file_path": "$params.file_path",
                        "old_code": "$outputs.get_code_entity_tool.code",
                        "new_code": "$params.new_code",
                    },
                ),
                ToolStep(
                    tool_name="check_python_syntax",
                    parameters={"file_path": "$params.file_path"},
                ),
            ],
            parameters={
                "file_path": {"type": "str", "required": True},
                "function_name": {"type": "str", "required": True},
                "new_code": {"type": "str", "required": True},
            },
        ))

    def execute_composite(
        self,
        name: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行复合工具"""
        return self.composite_manager.execute(name, params)

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_tools": len(self.dynamic_loader.list_tools()),
            "dynamic_tools": len(self.dynamic_loader.list_tools(ToolType.DYNAMIC)),
            "composite_tools": len(self.composite_manager.list_composites()),
            "plugins": len(self.plugin_manager.list_plugins()),
            "plugins_enabled": len(self.plugin_manager.list_plugins(enabled_only=True)),
        }


# ============================================================================
# 单例和工具函数
# ============================================================================

_tool_ecosystem_instance: Optional[ToolEcosystem] = None


def get_tool_ecosystem(project_root: Optional[str] = None) -> ToolEcosystem:
    """获取工具生态系统单例"""
    global _tool_ecosystem_instance

    if _tool_ecosystem_instance is None:
        _tool_ecosystem_instance = ToolEcosystem(project_root)
        _tool_ecosystem_instance.initialize()

    return _tool_ecosystem_instance


def reset_tool_ecosystem() -> None:
    """重置工具生态系统单例"""
    global _tool_ecosystem_instance
    _tool_ecosystem_instance = None


# ============================================================================
# 快捷函数
# ============================================================================

def execute_composite_tool(
    name: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    快捷函数：执行复合工具

    Args:
        name: 复合工具名称
        params: 参数

    Returns:
        执行结果
    """
    ecosystem = get_tool_ecosystem()
    return ecosystem.execute_composite(name, params)


def get_tool_statistics() -> Dict[str, Any]:
    """快捷函数：获取工具统计"""
    ecosystem = get_tool_ecosystem()
    return ecosystem.get_statistics()


# ============================================================================
# CompositeTool LangChain Tool 包装（Phase 8.5）
# ============================================================================

from langchain_core.tools import tool
from pydantic import BaseModel, Field
import json


class RegisterCompositeInput(BaseModel):
    """注册复合工具输入"""
    name: str = Field(description="复合工具名称")
    description: str = Field(description="复合工具描述")
    steps_json: str = Field(
        description='步骤列表，JSON 数组格式，每步包含 tool_name 和 parameters'
    )


class ExecuteCompositeInput(BaseModel):
    """执行复合工具输入"""
    name: str = Field(description="复合工具名称")
    params_json: str = Field(
        default="{}",
        description="执行参数，JSON 字符串格式"
    )


@tool(args_schema=RegisterCompositeInput)
def register_composite_tool(
    name: str,
    description: str,
    steps_json: str,
) -> str:
    """
    注册复合工具（流水线）

    将多个基础工具按步骤组合成一个复合工具。

    **steps_json 格式**：
    ```json
    [
        {
            "tool_name": "grep_search",
            "parameters": {"pattern": "$params.query"},
            "input_mapping": {},
            "retry_on_failure": false
        },
        {
            "tool_name": "read_file",
            "parameters": {"file_path": "$outputs.grep_search.result"},
            "input_mapping": {}
        }
    ]
    ```

    **参数引用**：
    - `$params.xxx` - 引用输入参数
    - `$outputs.step_name.xxx` - 引用前一步骤的输出
    """
    try:
        steps = json.loads(steps_json)
    except (json.JSONDecodeError, ValueError) as e:
        return json.dumps({
            "success": False,
            "message": f"steps_json 格式错误: {e}"
        }, ensure_ascii=False, indent=2)

    try:
        from core.ecosystem.tool_ecosystem import (
            ToolStep, CompositeToolSpec, get_tool_ecosystem
        )

        tool_steps = []
        for s in steps:
            step = ToolStep(
                tool_name=s.get("tool_name", ""),
                parameters=s.get("parameters", {}),
                input_mapping=s.get("input_mapping", {}),
                condition=s.get("condition"),
                retry_on_failure=s.get("retry_on_failure", False),
                max_retries=s.get("max_retries", 3),
            )
            tool_steps.append(step)

        spec = CompositeToolSpec(
            name=name,
            description=description,
            steps=tool_steps,
        )

        ecosystem = get_tool_ecosystem()
        ecosystem.composite_manager.register_composite(spec)

        return json.dumps({
            "success": True,
            "message": f"复合工具 '{name}' 注册成功",
            "steps_count": len(tool_steps),
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({
            "success": False,
            "message": f"注册失败: {type(e).__name__}: {e}"
        }, ensure_ascii=False, indent=2)


@tool(args_schema=ExecuteCompositeInput)
def execute_composite_tool_wrapper(
    name: str,
    params_json: str = "{}",
) -> str:
    """
    执行复合工具

    **使用场景**：
    - 批量执行多个工具的流水线
    - 自动化复杂工作流

    **params_json 示例**：
    ```
    {"query": "Python", "limit": 10}
    ```
    """
    try:
        params = json.loads(params_json)
    except (json.JSONDecodeError, ValueError) as e:
        return json.dumps({
            "success": False,
            "message": f"params_json 格式错误: {e}"
        }, ensure_ascii=False, indent=2)

    try:
        from core.ecosystem.tool_ecosystem import get_tool_ecosystem
        ecosystem = get_tool_ecosystem()
        result = ecosystem.execute_composite(name, params)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "message": f"执行失败: {type(e).__name__}: {e}"
        }, ensure_ascii=False, indent=2)
