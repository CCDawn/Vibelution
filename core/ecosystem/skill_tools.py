#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skill 管理工具 - Agent 自我扩展接口

提供以下 LangChain Tool：
- install_skill_tool: 安装新 Skill
- update_skill_tool: 更新 Skill
- optimize_skill_tool: 优化 Skill
- uninstall_skill_tool: 删除 Skill
- list_skills_tool: 列举 Skill
- get_skill_info_tool: 获取 Skill 详情
- execute_skill_tool: 执行 Skill
- search_skills_tool: 搜索 Skill
- render_skill_prompt_tool: 生成 Skill 提示词
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool, StructuredTool
from pydantic import BaseModel, Field

from core.ecosystem.skill_registry import (
    SkillMeta,
    SkillParam,
    get_skill_registry,
)


# ============================================================================
# 输入模型
# ============================================================================


class InstallSkillInput(BaseModel):
    """安装 Skill 输入"""
    name: str = Field(description="Skill 名称（英文，推荐 snake_case）")
    description: str = Field(description="Skill 简短描述")
    version: str = Field(default="1.0.0", description="版本号")
    trigger_keywords: str = Field(
        default='[]',
        description='触发关键词列表，JSON 数组格式，如 ["搜索", "查"]'
    )
    parameters: str = Field(
        default="[]",
        description='参数定义，JSON 数组，每项包含 name/type/required/description'
    )
    tags: str = Field(
        default='[]',
        description='标签列表，JSON 数组格式'
    )
    impl_code: str = Field(description="Skill 实现代码（Python），必须包含 execute 函数")
    author: str = Field(default="agent", description="作者")


class UpdateSkillInput(BaseModel):
    """更新 Skill 输入"""
    name: str = Field(description="Skill 名称")
    meta_json: Optional[str] = Field(
        default=None,
        description="更新的元数据（JSON 字符串，可选）"
    )
    impl_code: Optional[str] = Field(
        default=None,
        description="更新的实现代码（Python，可选）"
    )


class OptimizeSkillInput(BaseModel):
    """优化 Skill 输入"""
    name: str = Field(description="Skill 名称")
    new_impl_code: str = Field(description="优化后的实现代码")


class UninstallSkillInput(BaseModel):
    """卸载 Skill 输入"""
    name: str = Field(description="Skill 名称")
    confirm: bool = Field(default=False, description="确认删除")


class ListSkillsInput(BaseModel):
    """列举 Skill 输入"""
    include_disabled: bool = Field(default=False, description="包含已禁用的 Skill")


class GetSkillInfoInput(BaseModel):
    """获取 Skill 详情输入"""
    name: str = Field(description="Skill 名称")


class ExecuteSkillInput(BaseModel):
    """执行 Skill 输入"""
    name: str = Field(description="Skill 名称")
    params_json: str = Field(
        default="{}",
        description="执行参数，JSON 字符串格式"
    )


class SearchSkillsInput(BaseModel):
    """搜索 Skill 输入"""
    keyword: str = Field(description="搜索关键词")


# ============================================================================
# Tool 实现
# ============================================================================


@tool(args_schema=InstallSkillInput)
def install_skill_tool(
    name: str,
    description: str,
    impl_code: str,
    version: str = "1.0.0",
    trigger_keywords: str = "[]",
    parameters: str = "[]",
    tags: str = "[]",
    author: str = "agent",
) -> str:
    """
    安装新 Skill（Agent 自我扩展核心能力）

    在 workspace/skills/{name}/ 目录下创建完整的 Skill。

    **使用场景**：
    - Agent 发现需要新能力时自主创建
    - 用户请求添加新功能

    **参数说明**：
    - name: Skill 名称，英文 snake_case，推荐如 "web_search", "code_review"
    - description: 简短描述，说明这个 Skill 做什么
    - impl_code: Python 实现代码，必须包含 execute 函数

    **impl_code 示例**：
    ```
    def execute(query: str, max_results: int = 5) -> dict:
        return {"query": query, "results": [], "count": 0}
    ```
    """
    registry = get_skill_registry()

    # 解析 JSON 字段
    try:
        trigger_kw = json.loads(trigger_keywords) if trigger_keywords else []
    except (json.JSONDecodeError, ValueError):
        trigger_kw = []

    try:
        params_list = json.loads(parameters) if parameters else []
    except (json.JSONDecodeError, ValueError):
        params_list = []

    try:
        tags_list = json.loads(tags) if tags else []
    except (json.JSONDecodeError, ValueError):
        tags_list = []

    # 构建参数定义
    skill_params = []
    for p in params_list:
        if isinstance(p, dict):
            skill_params.append(SkillParam(
                name=p.get("name", ""),
                type=p.get("type", "string"),
                required=p.get("required", False),
                default=p.get("default"),
                description=p.get("description", ""),
            ))

    # 构建元数据
    meta = SkillMeta(
        name=name,
        description=description,
        version=version,
        trigger_keywords=trigger_kw,
        parameters=skill_params,
        tags=tags_list,
        author=author,
    )

    result = registry.install_skill(meta, impl_code)
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool(args_schema=UpdateSkillInput)
def update_skill_tool(
    name: str,
    meta_json: Optional[str] = None,
    impl_code: Optional[str] = None,
) -> str:
    """
    更新 Skill（元数据或实现）

    **使用场景**：
    - 修改 Skill 描述或参数
    - 改进 Skill 实现逻辑
    - 调整触发关键词

    **至少提供一个要更新的内容**：meta_json 或 impl_code
    """
    registry = get_skill_registry()

    updated_meta = None
    if meta_json:
        try:
            meta_dict = json.loads(meta_json)
            # 保留原 meta，合并更新
            original = registry.get_skill(name)
            if original:
                for k, v in meta_dict.items():
                    if hasattr(original, k):
                        setattr(original, k, v)
                updated_meta = original
        except (json.JSONDecodeError, ValueError):
            return json.dumps({
                "success": False,
                "message": f"meta_json 格式错误: {meta_json}"
            }, ensure_ascii=False, indent=2)

    result = registry.update_skill(name, meta=updated_meta, impl_code=impl_code)
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool(args_schema=OptimizeSkillInput)
def optimize_skill_tool(
    name: str,
    new_impl_code: str,
) -> str:
    """
    优化 Skill 实现

    用于改进 Skill 的性能、效率或代码质量，仅更新实现代码。

    **使用场景**：
    - 优化执行效率
    - 改进错误处理
    - 添加缓存机制
    """
    registry = get_skill_registry()
    result = registry.optimize_skill(name, new_impl_code)
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool(args_schema=UninstallSkillInput)
def uninstall_skill_tool(
    name: str,
    confirm: bool = False,
) -> str:
    """
    卸载（删除）Skill

    **危险操作**：删除后无法恢复！

    必须设置 confirm=True 才能执行删除。
    """
    if not confirm:
        return json.dumps({
            "success": False,
            "message": f"确认删除 Skill '{name}'？请设置 confirm=True"
        }, ensure_ascii=False, indent=2)

    registry = get_skill_registry()
    result = registry.uninstall_skill(name)
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool(args_schema=ListSkillsInput)
def list_skills_tool(
    include_disabled: bool = False,
) -> str:
    """
    列举所有可用的 Skill

    返回 Skill 名称、描述、版本、触发关键词等信息。
    """
    registry = get_skill_registry()

    if include_disabled:
        skills = registry.list_skills()
    else:
        skills = registry.list_enabled_skills()

    result = {
        "count": len(skills),
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "tags": s.tags,
                "trigger_keywords": s.trigger_keywords,
                "author": s.author,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
            for s in skills
        ]
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool(args_schema=GetSkillInfoInput)
def get_skill_info_tool(
    name: str,
) -> str:
    """
    获取指定 Skill 的详细信息

    包括：名称、描述、参数定义、触发关键词、标签等。
    """
    registry = get_skill_registry()
    meta = registry.get_skill(name)

    if meta is None:
        return json.dumps({
            "success": False,
            "message": f"Skill '{name}' 不存在"
        }, ensure_ascii=False, indent=2)

    result = {
        "success": True,
        "skill": meta.to_dict(),
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool(args_schema=ExecuteSkillInput)
def execute_skill_tool(
    name: str,
    params_json: str = "{}",
) -> str:
    """
    执行指定 Skill

    **使用场景**：
    - 测试新安装的 Skill
    - 直接调用 Skill 执行任务

    **params_json 示例**：
    - '{"query": "Python 教程", "max_results": 3}'
    - '{"code": "print(1+1)", "language": "python"}'
    """
    registry = get_skill_registry()

    try:
        params = json.loads(params_json)
    except (json.JSONDecodeError, ValueError):
        return json.dumps({
            "success": False,
            "message": f"params_json 格式错误: {params_json}"
        }, ensure_ascii=False, indent=2)

    result = registry.execute_skill(name, params)
    return json.dumps({
        "success": True,
        "name": name,
        "result": result,
    }, ensure_ascii=False, indent=2)


@tool(args_schema=SearchSkillsInput)
def search_skills_tool(
    keyword: str,
) -> str:
    """
    根据关键词搜索 Skill

    搜索范围：名称、描述、触发关键词、标签
    """
    registry = get_skill_registry()
    results = registry.search_by_keyword(keyword)

    result = {
        "keyword": keyword,
        "count": len(results),
        "skills": [s.to_dict() for s in results],
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def render_skill_prompt_tool(
    skill_names: str = "",
    include_code: bool = False,
) -> str:
    """
    生成 Skill 相关的系统提示词片段

    用于在系统提示词中动态注入 Skill 信息。

    **参数**：
    - skill_names: 要包含的 Skill 名称，逗号分隔，留空表示所有
    - include_code: 是否包含实现代码（不建议开启）
    """
    registry = get_skill_registry()

    names = None
    if skill_names:
        names = [n.strip() for n in skill_names.split(',') if n.strip()]

    prompt = registry.render_skill_prompt(
        skill_names=names,
        include_code=include_code,
    )
    return prompt


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    "install_skill_tool",
    "update_skill_tool",
    "optimize_skill_tool",
    "uninstall_skill_tool",
    "list_skills_tool",
    "get_skill_info_tool",
    "execute_skill_tool",
    "search_skills_tool",
    "render_skill_prompt_tool",
]
