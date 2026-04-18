#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SkillRegistry - OpenClaw 风格 Skill 管理与 Agent 自我扩展系统

核心功能：
- Skill 发现：从 workspace/skills/ 目录扫描所有 Skill
- Skill 加载：将 Skill 元数据（SKILL.md）和实现（impl.py）加载为可执行对象
- Agent 集成：转换为 LangChain BaseTool，绑定到 LLM
- 自我扩展：Agent 可自主创建/修改/优化/删除 Skill

存储位置：workspace/skills/
"""

from __future__ import annotations

import os
import re
import ast
import json
import shutil
import importlib
import inspect
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field, asdict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import threading

# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class SkillParam:
    """Skill 参数定义"""
    name: str
    type: str = "string"
    required: bool = False
    default: Any = None
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "default": self.default,
            "description": self.description,
        }


@dataclass
class SkillMeta:
    """Skill 元数据"""
    name: str
    description: str = ""
    version: str = "1.0.0"
    trigger_keywords: List[str] = field(default_factory=list)
    parameters: List[SkillParam] = field(default_factory=list)
    env_requirements: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    author: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "trigger_keywords": self.trigger_keywords,
            "parameters": [p.to_dict() for p in self.parameters],
            "env_requirements": self.env_requirements,
            "tags": self.tags,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillMeta":
        params = [
            SkillParam(
                name=p.get("name", ""),
                type=p.get("type", "string"),
                required=p.get("required", False),
                default=p.get("default"),
                description=p.get("description", ""),
            )
            for p in data.get("parameters", [])
        ]
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            trigger_keywords=data.get("trigger_keywords", []),
            parameters=params,
            env_requirements=data.get("env_requirements", []),
            tags=data.get("tags", []),
            author=data.get("author", ""),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            enabled=data.get("enabled", True),
            metadata=data.get("metadata", {}),
        )


@dataclass
class LoadedSkill:
    """已加载的 Skill 实例"""
    meta: SkillMeta
    impl_module: Any
    impl_func: Callable
    loaded_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ============================================================================
# SkillRegistry 核心类
# ============================================================================


class SkillRegistry:
    """
    Skill 注册与管理中心

    功能：
    - 发现：扫描 workspace/skills/ 目录
    - 加载：将 SKILL.md + impl.py 转换为可执行对象
    - 集成：转换为 LangChain BaseTool
    - 扩展：Agent 可创建/修改/优化/删除 Skill
    """

    def __init__(self, skills_dir: Optional[str] = None):
        """
        初始化 SkillRegistry

        Args:
            skills_dir: Skill 根目录，默认为 workspace/skills/
        """
        if skills_dir is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            skills_dir = os.path.join(project_root, "workspace", "skills")
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        self._meta_cache: Dict[str, SkillMeta] = {}      # name -> meta
        self._loaded_skills: Dict[str, LoadedSkill] = {}  # name -> LoadedSkill
        self._lock = threading.Lock()

        # 初始化时扫描
        self.discover_skills()

    # =========================================================================
    # 发现与扫描
    # =========================================================================

    def discover_skills(self) -> List[str]:
        """
        发现所有 Skill（扫描 workspace/skills/ 目录）

        Returns:
            发现的 Skill 名称列表
        """
        discovered = []

        if not self.skills_dir.exists():
            return discovered

        for skill_path in self.skills_dir.iterdir():
            if not skill_path.is_dir():
                continue

            skill_name = skill_path.name
            meta = self._load_meta_from_dir(skill_path)

            if meta:
                with self._lock:
                    self._meta_cache[skill_name] = meta
                discovered.append(skill_name)

        return discovered

    def discover_skill(self, name: str) -> Optional[SkillMeta]:
        """
        发现指定 Skill

        Args:
            name: Skill 名称

        Returns:
            SkillMeta 或 None
        """
        # 优先从缓存返回
        if name in self._meta_cache:
            return self._meta_cache[name]

        skill_path = self.skills_dir / name
        if not skill_path.exists():
            return None

        meta = self._load_meta_from_dir(skill_path)
        if meta:
            with self._lock:
                self._meta_cache[name] = meta
            return meta

        return None

    def _load_meta_from_dir(self, skill_path: Path) -> Optional[SkillMeta]:
        """从目录加载 SKILL.md"""
        meta_file = skill_path / "SKILL.md"
        if not meta_file.exists():
            return None

        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                content = f.read()
            return self._parse_skill_md(content, skill_path.name)
        except Exception:
            return None

    def _parse_skill_md(self, content: str, default_name: str = "") -> Optional[SkillMeta]:
        """
        解析 SKILL.md 内容为 SkillMeta

        格式：
            # skill_name

            ## 基本信息
            - name: web_search
            - description: 搜索互联网
            - version: 1.0.0
            - trigger_keywords: ["搜索", "查"]

            ## parameters
            - name: query
              type: string
              required: true
        """
        lines = content.strip().split('\n')
        data: Dict[str, Any] = {"parameters": []}

        # 阶段1: 检测 section 并解析
        in_params_section = False
        params_section_indent = 0
        current_param: Dict[str, Any] = {}

        for line in lines:
            # 计算缩进（不含strip）
            stripped = line.strip()
            indent = len(line) - len(line.lstrip())

            if not stripped:
                continue

            # 处理 ## section headers
            if stripped.startswith('##'):
                # 完成上一个参数
                if current_param and 'name' in current_param:
                    data['parameters'].append(current_param)
                    current_param = {}

                header_content = stripped.lstrip('#').strip().lower()
                in_params_section = header_content == 'parameters'
                if in_params_section:
                    params_section_indent = indent
                continue

            # 跳过 # 注释
            if stripped.startswith('#'):
                continue

            if in_params_section:
                # 在 parameters section 中
                field_indent = indent

                if field_indent <= params_section_indent:
                    # 顶级列表项：- name: xxx
                    if stripped.startswith('- '):
                        # 先保存上一个参数
                        if current_param and 'name' in current_param:
                            data['parameters'].append(current_param)
                            current_param = {}

                        # 解析 - name: xxx
                        item = stripped[1:].strip()
                        if ':' in item:
                            key, _, value = item.partition(':')
                            key = key.strip().lower().replace(' ', '_')
                            value = value.strip().strip('"\'')
                            current_param[key] = value
                else:
                    # 子字段（比 section 更深缩进）
                    if ':' in stripped:
                        key, _, value = stripped.partition(':')
                        key = key.strip().lower().replace(' ', '_')
                        value = value.strip().strip('"\'')

                        if key == 'type':
                            current_param['type'] = value
                        elif key == 'required':
                            current_param['required'] = value.lower() in ('true', 'yes', '1')
                        elif key == 'default':
                            try:
                                current_param['default'] = json.loads(value)
                            except (json.JSONDecodeError, ValueError):
                                current_param['default'] = value.strip('"\'')
                        elif key == 'description':
                            current_param['description'] = value

            # 解析基本信息部分的键值对
            if ':' in stripped:
                if stripped.startswith('- '):
                    item = stripped[1:].strip()
                else:
                    item = stripped

                if ':' in item:
                    key, _, value = item.partition(':')
                    key = key.strip().lower().replace('-', '_')
                    value = value.strip().strip('"\'')

                    if key in ('trigger_keywords', 'tags', 'env_requirements'):
                        try:
                            value = json.loads(value)
                        except (json.JSONDecodeError, ValueError):
                            value = [v.strip().strip('"\'') for v in value.split(',') if v.strip()]
                    data[key] = value

        # 保存最后一个参数
        if current_param and 'name' in current_param:
            data['parameters'].append(current_param)

        # 确保 name
        data.setdefault('name', default_name)

        return SkillMeta.from_dict(data)

    def list_skills(self) -> List[SkillMeta]:
        """列出所有已发现的 Skill"""
        return list(self._meta_cache.values())

    def list_enabled_skills(self) -> List[SkillMeta]:
        """列出所有启用的 Skill"""
        return [m for m in self._meta_cache.values() if m.enabled]

    # =========================================================================
    # 加载与卸载
    # =========================================================================

    def load_skill(self, name: str) -> bool:
        """
        加载指定 Skill

        Args:
            name: Skill 名称

        Returns:
            是否加载成功
        """
        with self._lock:
            if name in self._loaded_skills:
                return True

            skill_path = self.skills_dir / name
            if not skill_path.exists():
                return False

            impl_file = skill_path / "impl.py"
            if not impl_file.exists():
                return False

            meta = self.discover_skill(name)
            if not meta:
                return False

            try:
                # 动态导入 impl.py
                module_name = f"_dynamic_skills.{name}.impl"
                spec = importlib.util.spec_from_file_location(module_name, impl_file)
                if spec is None or spec.loader is None:
                    return False

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # 查找 execute 函数
                impl_func = getattr(module, 'execute', None)
                if impl_func is None:
                    # 尝试查找第一个可调用函数
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name, None)
                        if callable(attr) and not attr_name.startswith('_'):
                            impl_func = attr
                            break

                if impl_func is None:
                    return False

                self._loaded_skills[name] = LoadedSkill(
                    meta=meta,
                    impl_module=module,
                    impl_func=impl_func,
                )
                return True

            except Exception:
                return False

    def unload_skill(self, name: str) -> bool:
        """卸载 Skill"""
        with self._lock:
            if name in self._loaded_skills:
                del self._loaded_skills[name]
                return True
            return False

    def reload_skill(self, name: str) -> bool:
        """重新加载 Skill"""
        self.unload_skill(name)
        return self.load_skill(name)

    # =========================================================================
    # Agent 自我扩展核心能力
    # =========================================================================

    def install_skill(self, meta: SkillMeta, impl_code: str) -> Dict[str, Any]:
        """
        Agent 自我扩展：安装新 Skill

        将 Skill 写入 workspace/skills/{name}/ 目录

        Args:
            meta: Skill 元数据
            impl_code: 实现代码字符串

        Returns:
            {"success": bool, "message": str}
        """
        name = meta.name
        skill_path = self.skills_dir / name

        try:
            # 检查是否已存在
            if skill_path.exists():
                return {
                    "success": False,
                    "message": f"Skill '{name}' 已存在，请使用 update_skill 更新"
                }

            # 创建目录
            skill_path.mkdir(parents=True, exist_ok=True)

            # 写入 SKILL.md
            meta.updated_at = datetime.now().isoformat()
            meta.created_at = datetime.now().isoformat()
            meta_path = skill_path / "SKILL.md"
            with open(meta_path, 'w', encoding='utf-8') as f:
                f.write(self._render_skill_md(meta))

            # 写入 impl.py
            impl_path = skill_path / "impl.py"
            with open(impl_path, 'w', encoding='utf-8') as f:
                f.write(impl_code)

            # 更新缓存
            with self._lock:
                self._meta_cache[name] = meta

            # 尝试加载
            self.load_skill(name)

            return {
                "success": True,
                "message": f"Skill '{name}' 安装成功",
                "path": str(skill_path),
            }

        except Exception as e:
            # 清理失败的目录
            if skill_path.exists():
                shutil.rmtree(skill_path, ignore_errors=True)
            return {
                "success": False,
                "message": f"安装失败: {type(e).__name__}: {e}"
            }

    def update_skill(
        self,
        name: str,
        meta: Optional[SkillMeta] = None,
        impl_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Agent 自我扩展：更新 Skill

        Args:
            name: Skill 名称
            meta: 新元数据（可选）
            impl_code: 新实现代码（可选）

        Returns:
            {"success": bool, "message": str}
        """
        skill_path = self.skills_dir / name
        if not skill_path.exists():
            return {"success": False, "message": f"Skill '{name}' 不存在"}

        try:
            changed = []

            # 更新元数据
            if meta:
                meta.updated_at = datetime.now().isoformat()
                meta_path = skill_path / "SKILL.md"
                with open(meta_path, 'w', encoding='utf-8') as f:
                    f.write(self._render_skill_md(meta))
                with self._lock:
                    self._meta_cache[name] = meta
                changed.append("SKILL.md")

            # 更新实现
            if impl_code:
                impl_path = skill_path / "impl.py"
                with open(impl_path, 'w', encoding='utf-8') as f:
                    f.write(impl_code)
                changed.append("impl.py")

            # 重新加载
            self.reload_skill(name)

            return {
                "success": True,
                "message": f"Skill '{name}' 更新成功，更新了: {', '.join(changed)}",
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"更新失败: {type(e).__name__}: {e}"
            }

    def optimize_skill(self, name: str, new_impl_code: str) -> Dict[str, Any]:
        """
        Agent 自我扩展：优化 Skill 实现

        Args:
            name: Skill 名称
            new_impl_code: 优化后的实现代码

        Returns:
            {"success": bool, "message": str}
        """
        return self.update_skill(name, meta=None, impl_code=new_impl_code)

    def uninstall_skill(self, name: str) -> Dict[str, Any]:
        """
        Agent 自我扩展：删除 Skill

        Args:
            name: Skill 名称

        Returns:
            {"success": bool, "message": str}
        """
        skill_path = self.skills_dir / name
        if not skill_path.exists():
            return {"success": False, "message": f"Skill '{name}' 不存在"}

        try:
            # 卸载
            self.unload_skill(name)

            # 删除目录
            shutil.rmtree(skill_path)

            # 更新缓存
            with self._lock:
                self._meta_cache.pop(name, None)

            return {
                "success": True,
                "message": f"Skill '{name}' 已删除",
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"删除失败: {type(e).__name__}: {e}"
            }

    # =========================================================================
    # LangChain Tool 转换
    # =========================================================================

    def to_langchain_tools(self, skill_names: List[str]) -> List[Any]:
        """
        将指定 Skill 转换为 LangChain BaseTool

        Args:
            skill_names: 要转换的 Skill 名称列表

        Returns:
            LangChain BaseTool 列表
        """
        from langchain_core.tools import BaseTool, tool

        tools = []

        for name in skill_names:
            if name not in self._loaded_skills:
                if not self.load_skill(name):
                    continue

            loaded = self._loaded_skills.get(name)
            if not loaded:
                continue

            meta = loaded.meta
            impl_func = loaded.impl_func

            # 构建工具函数
            tool_func = self._build_tool_func(name, meta, impl_func)
            tools.append(tool_func)

        return tools

    def _build_tool_func(
        self,
        name: str,
        meta: SkillMeta,
        impl_func: Callable,
    ) -> Any:
        """构建 LangChain Tool 函数"""
        from langchain_core.tools import BaseTool, StructuredTool

        # 构建参数schema
        args_schema = self._build_args_schema(meta.parameters)

        def execute_func(**kwargs) -> str:
            try:
                result = impl_func(**kwargs)
                if isinstance(result, (dict, list)):
                    return json.dumps(result, ensure_ascii=False, indent=2)
                return str(result)
            except Exception as e:
                return f"[错误] {type(e).__name__}: {e}"

        # 设置工具名称和描述
        execute_func.__name__ = name
        execute_func.__doc__ = meta.description

        tool = StructuredTool(
            name=f"skill_{name}",
            description=meta.description,
            args_schema=args_schema,
            func=execute_func,
        )

        return tool

    def _build_args_schema(self, params: List[SkillParam]) -> Optional[type]:
        """根据参数定义构建 Pydantic v2 schema"""
        if not params:
            return None

        from pydantic import BaseModel, Field

        type_map = {
            "string": str, "str": str,
            "integer": int, "int": int,
            "float": float, "number": float,
            "boolean": bool, "bool": bool,
            "array": List[Any], "list": List[Any],
            "object": Dict[str, Any], "dict": Dict[str, Any],
        }

        # 构建字段字典（Pydantic v2 语法）
        namespace = {"__annotations__": {}}
        for p in params:
            field_type = type_map.get(p.type.lower(), Any)
            default_val = ...
            if not p.required:
                default_val = p.default if p.default is not None else None

            namespace["__annotations__"][p.name] = field_type
            namespace[p.name] = Field(
                description=p.description,
                default=default_val,
            )

        schema_name = ''.join(w.capitalize() for w in params[0].name.split('_'))
        schema_class = type(f"{schema_name}Schema", (BaseModel,), namespace)

        return schema_class

    def get_skill_tools(self) -> List[Any]:
        """获取所有已加载 Skill 的 LangChain 工具"""
        loaded_names = list(self._loaded_skills.keys())
        return self.to_langchain_tools(loaded_names)

    # =========================================================================
    # 提示词生成
    # =========================================================================

    def render_skill_prompt(
        self,
        skill_names: Optional[List[str]] = None,
        include_code: bool = False,
    ) -> str:
        """
        生成 Skill 相关的系统提示词片段

        Args:
            skill_names: 要包含的 Skill 列表（None = 所有）
            include_code: 是否包含实现代码

        Returns:
            Markdown 格式的提示词片段
        """
        lines = [
            "## 可用扩展 Skill",
            "",
            "Agent 可以通过 Skill 调用扩展能力，使用 XML 格式调用：",
            '```xml',
            '<skill name="skill_name">',
            '  <param name="param_name">参数值</param>',
            '</skill>',
            '```',
            "",
        ]

        if skill_names is None:
            metas = self.list_enabled_skills()
        else:
            metas = [self._meta_cache[n] for n in skill_names if n in self._meta_cache]

        for meta in metas:
            lines.append(f"### {meta.name}")
            lines.append(f"{meta.description}")
            lines.append("")

            if meta.parameters:
                lines.append("**参数**：")
                for p in meta.parameters:
                    req = "必需" if p.required else "可选"
                    default = f" (默认: {p.default})" if p.default is not None else ""
                    lines.append(f"- `{p.name}` ({p.type}) {req}{default}: {p.description}")
                lines.append("")

            if meta.trigger_keywords:
                lines.append(f"**触发词**：{', '.join(meta.trigger_keywords)}")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    # =========================================================================
    # 工具方法
    # =========================================================================

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_skills": len(self._meta_cache),
            "enabled_skills": len([m for m in self._meta_cache.values() if m.enabled]),
            "loaded_skills": len(self._loaded_skills),
            "skills_dir": str(self.skills_dir),
        }

    def search_by_keyword(self, keyword: str) -> List[SkillMeta]:
        """根据关键词搜索 Skill"""
        keyword = keyword.lower()
        results = []
        for meta in self._meta_cache.values():
            if not meta.enabled:
                continue
            if (
                keyword in meta.name.lower()
                or keyword in meta.description.lower()
                or any(keyword in kw.lower() for kw in meta.trigger_keywords)
                or any(keyword in tag.lower() for tag in meta.tags)
            ):
                results.append(meta)
        return results

    def get_skill(self, name: str) -> Optional[SkillMeta]:
        """获取 Skill 元数据"""
        return self._meta_cache.get(name)

    def execute_skill(self, name: str, params: Dict[str, Any]) -> str:
        """
        执行 Skill

        Args:
            name: Skill 名称
            params: 执行参数

        Returns:
            执行结果字符串
        """
        if name not in self._loaded_skills:
            if not self.load_skill(name):
                return f"[错误] Skill '{name}' 加载失败"
            if name not in self._loaded_skills:
                return f"[错误] Skill '{name}' 未找到"

        loaded = self._loaded_skills[name]

        try:
            result = loaded.impl_func(**params)
            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False, indent=2)
            return str(result)
        except Exception as e:
            return f"[错误] {type(e).__name__}: {e}"

    # =========================================================================
    # 内部辅助
    # =========================================================================

    def _render_skill_md(self, meta: SkillMeta) -> str:
        """将 SkillMeta 渲染为 SKILL.md 格式"""
        lines = [
            f"# {meta.name}",
            "",
            f"**描述**: {meta.description}",
            f"**版本**: {meta.version}",
            "",
            f"## 基本信息",
            "",
            f"- name: {meta.name}",
            f"- description: {meta.description}",
            f"- version: {meta.version}",
            f"- author: {meta.author or 'agent'}",
            f"- created_at: \"{meta.created_at}\"",
            f"- updated_at: \"{meta.updated_at}\"",
            "",
            f"- trigger_keywords: {json.dumps(meta.trigger_keywords, ensure_ascii=False)}",
            f"- tags: {json.dumps(meta.tags, ensure_ascii=False)}",
            f"- env_requirements: {json.dumps(meta.env_requirements, ensure_ascii=False)}",
            "",
            f"## parameters",
            "",
        ]

        for p in meta.parameters:
            lines.append(f"- name: {p.name}")
            lines.append(f"  type: {p.type}")
            lines.append(f"  required: {str(p.required).lower()}")
            if p.default is not None:
                lines.append(f"  default: {json.dumps(p.default)}")
            lines.append(f"  description: {p.description}")
            lines.append("")

        return "\n".join(lines)


# ============================================================================
# 全局单例
# ============================================================================

_skill_registry_instance: Optional[SkillRegistry] = None
_skill_registry_lock = threading.Lock()


def get_skill_registry(skills_dir: Optional[str] = None) -> SkillRegistry:
    """
    获取 SkillRegistry 全局单例

    Args:
        skills_dir: 可选，指定 Skill 根目录

    Returns:
        SkillRegistry 单例
    """
    global _skill_registry_instance

    if _skill_registry_instance is None:
        with _skill_registry_lock:
            if _skill_registry_instance is None:
                _skill_registry_instance = SkillRegistry(skills_dir)

    return _skill_registry_instance


def reset_skill_registry() -> None:
    """重置 SkillRegistry 单例（用于测试）"""
    global _skill_registry_instance
    with _skill_registry_lock:
        _skill_registry_instance = None
