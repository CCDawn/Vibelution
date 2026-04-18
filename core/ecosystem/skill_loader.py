#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SkillLoader - Skill 加载与转换工具

功能：
- 从目录加载 Skill（SKILL.md + impl.py）
- 解析 SKILL.md 元数据
- 转换为 LangChain BaseTool

已集成到 SkillRegistry，此模块提供独立加载接口。
"""

from __future__ import annotations

import os
import json
import importlib
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass

# 复用 SkillRegistry 的数据结构
from core.ecosystem.skill_registry import (
    SkillMeta,
    SkillParam,
    SkillRegistry,
    get_skill_registry,
)


class SkillLoader:
    """
    Skill 独立加载器

    提供轻量级的 Skill 加载接口，不依赖全局单例。
    """

    @staticmethod
    def load_from_directory(skill_path: Path) -> Optional[Dict[str, Any]]:
        """
        从目录加载 Skill

        Args:
            skill_path: Skill 目录路径

        Returns:
            {"meta": SkillMeta, "impl_func": Callable} 或 None
        """
        if not skill_path.is_dir():
            return None

        meta_file = skill_path / "SKILL.md"
        impl_file = skill_path / "impl.py"

        if not meta_file.exists() or not impl_file.exists():
            return None

        # 解析元数据
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                content = f.read()
            meta = SkillLoader._parse_skill_md(content, skill_path.name)
            if meta is None:
                return None
        except Exception:
            return None

        # 加载实现
        try:
            module_name = f"_skill_loader.{skill_path.name}.impl"
            spec = importlib.util.spec_from_file_location(module_name, impl_file)
            if spec is None or spec.loader is None:
                return None

            module = importlib.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 查找 execute 函数
            impl_func = getattr(module, 'execute', None)
            if impl_func is None:
                for attr_name in dir(module):
                    attr = getattr(module, attr_name, None)
                    if callable(attr) and not attr_name.startswith('_'):
                        impl_func = attr
                        break

            if impl_func is None:
                return None

            return {"meta": meta, "impl_func": impl_func}

        except Exception:
            return None

    @staticmethod
    def parse_skill_md(skill_path: Path) -> Optional[SkillMeta]:
        """
        解析 SKILL.md 文件

        Args:
            skill_path: Skill 目录路径

        Returns:
            SkillMeta 或 None
        """
        meta_file = skill_path / "SKILL.md"
        if not meta_file.exists():
            return None

        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                content = f.read()
            return SkillLoader._parse_skill_md(content, skill_path.name)
        except Exception:
            return None

    @staticmethod
    def _parse_skill_md(content: str, default_name: str = "") -> Optional[SkillMeta]:
        """解析 SKILL.md 内容（复用 SkillRegistry 的解析逻辑）"""
        from core.ecosystem.skill_registry import SkillRegistry
        registry = SkillRegistry(skills_dir="/tmp")
        return registry._parse_skill_md(content, default_name)

    @staticmethod
    def create_tool_from_meta(meta: SkillMeta, impl_func: Callable) -> Any:
        """
        从元数据和实现函数创建 LangChain Tool

        Args:
            meta: Skill 元数据
            impl_func: 实现函数

        Returns:
            LangChain StructuredTool
        """
        from langchain_core.tools import StructuredTool

        def execute_func(**kwargs) -> str:
            try:
                result = impl_func(**kwargs)
                if isinstance(result, (dict, list)):
                    return json.dumps(result, ensure_ascii=False, indent=2)
                return str(result)
            except Exception as e:
                return f"[错误] {type(e).__name__}: {e}"

        execute_func.__name__ = meta.name
        execute_func.__doc__ = meta.description

        args_schema = SkillLoader._build_args_schema(meta.parameters)

        return StructuredTool(
            name=f"skill_{meta.name}",
            description=meta.description,
            args_schema=args_schema,
            func=execute_func,
        )

    @staticmethod
    def _build_args_schema(params: List[SkillParam]) -> Optional[type]:
        """构建 Pydantic v2 schema"""
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

        schema_name = ''.join(w.capitalize() for w in (params[0].name.split('_') if params else ['Arg']))
        schema_class = type(f"{schema_name}Schema", (BaseModel,), namespace)
        return schema_class


# ============================================================================
# 快捷函数
# ============================================================================

def load_skill_from_dir(skill_path: Path) -> Optional[Dict[str, Any]]:
    """快捷函数：从目录加载 Skill"""
    return SkillLoader.load_from_directory(skill_path)


def parse_skill_meta(skill_path: Path) -> Optional[SkillMeta]:
    """快捷函数：解析 SKILL.md"""
    return SkillLoader.parse_skill_md(skill_path)


def create_skill_tool(meta: SkillMeta, impl_func: Callable) -> Any:
    """快捷函数：创建 LangChain Tool"""
    return SkillLoader.create_tool_from_meta(meta, impl_func)
