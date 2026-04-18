# -*- coding: utf-8 -*-
"""
core/prompt_builder.py - 动态系统提示词组装器

从 core/core_prompt/ 和 workspace/prompts/ 目录读取 Markdown 文件，
通过 CorePromptManager 双轨加载，动态组装系统提示词。
支持模板变量替换和 docs/tools_manual.md 索引注入。
"""

import os
from datetime import datetime
from typing import Optional, Dict, Any

from core.core_prompt import get_prompt_manager, CorePromptManager


def _load_memory_context() -> Dict[str, Any]:
    """加载记忆上下文"""
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from tools.memory_tools import read_memory_tool

        memory = read_memory_tool()
        return {
            "generation": memory.get("generation", 1),
            "total_generations": memory.get("total_generations", 1),
            "core_context": memory.get("core_context", ""),
            "current_goal": memory.get("current_goal", ""),
        }
    except Exception as e:
        return {
            "generation": 1,
            "total_generations": 1,
            "core_context": "",
            "current_goal": "",
            "error": str(e),
        }


def _load_task_checklist() -> str:
    """加载任务清单（强目标驱动）"""
    try:
        from core.capabilities.task_manager import get_task_manager
        tm = get_task_manager()
        return tm.render_prompt_checklist()
    except Exception:
        return ""


def _load_codebase_map() -> str:
    """
    加载代码库认知地图

    从数据库查询所有已刻印的代码库认知，
    用于注入到 System Prompt 中供 Agent 参考。
    """
    try:
        from core.infrastructure.workspace_manager import get_workspace
        ws = get_workspace()
        return ws.generate_codebase_map()
    except Exception as e:
        return f"[警告: 加载认知地图失败: {e}]"


def _extract_tools_manual_index() -> str:
    """从 tools_manual.md 提取精简索引"""
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tools_manual = os.path.join(project_root, "docs", "tools_manual.md")

        if not os.path.exists(tools_manual):
            return ""

        with open(tools_manual, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        index_lines = ["\n## 工具手册索引 (docs/tools_manual.md)", ""]

        for line in lines:
            if "`" in line and "|" in line:
                parts = line.split("`")
                if len(parts) >= 2:
                    tool_name = parts[1].strip()
                    if tool_name and not tool_name.startswith("#"):
                        index_lines.append(f"- `{tool_name}`")

        return "\n".join(index_lines[:20])

    except Exception:
        return ""


def build_system_prompt(
    generation: Optional[int] = None,
    total_generations: Optional[int] = None,
    core_context: Optional[str] = None,
    current_goal: Optional[str] = None,
) -> str:
    """
    构建动态系统提示词。

    双轨加载策略：
    - SOUL.md / AGENTS.md：优先从 workspace/prompts/ 加载，可被用户覆盖
    - IDENTITY.md / USER.md / DYNAMIC.md：仅从 workspace/prompts/ 加载
    - COMPRESS_SUMMARY.md：仅从 workspace/prompts/ 加载

    Args:
        generation: 当前世代数
        total_generations: 总世代数
        core_context: 跨代核心记忆
        current_goal: 本世代目标

    Returns:
        组装完成的系统提示词字符串
    """
    pm = get_prompt_manager()

    # 如果没有传入记忆，则从 memory_tools 加载
    if generation is None:
        memory_data = _load_memory_context()
        generation = memory_data.get("generation", 1)
        total_generations = memory_data.get("total_generations", 1)
        core_context = memory_data.get("core_context", "")
        current_goal = memory_data.get("current_goal", "")

    # 双轨加载所有提示词
    soul = pm.load_soul()            # workspace 优先，回退 static
    agents = pm.load_agents()         # workspace 优先，回退 static
    identity = pm.load_identity()     # 仅 workspace
    user = pm.load_user()             # 仅 workspace
    dynamic = pm.load_dynamic()       # 仅 workspace
    compress_summary = pm.load_compress_summary()  # 仅 workspace

    # 加载其他辅助内容
    tools_index = _extract_tools_manual_index()
    codebase_map = _load_codebase_map()
    task_checklist = _load_task_checklist()

    # 获取当前时间
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 项目根目录
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 组装完整提示词
    prompt_parts = [
        soul,
        "\n---\n",
    ]

    # 【关键位置】插入任务清单（在 SOUL.md 之后，最显眼）
    if task_checklist:
        prompt_parts.extend([
            "## ⚡ 任务清单 ⚡\n",
            task_checklist,
            "\n\n---\n\n",
        ])

    # 插入代码库认知地图
    if codebase_map:
        prompt_parts.extend([
            codebase_map,
            "\n\n---\n\n",
        ])

    # 继续组装其他部分
    prompt_parts.extend([
        dynamic,
        "\n---\n",
        identity,
        "\n---\n",
        agents,
        "\n---\n",
        user,
    ])

    # 添加记忆上下文
    if core_context or current_goal:
        memory_section = [
            "\n---\n",
            "## 你的记忆与状态\n",
            f"- 当前世代: G{generation}（共{total_generations}代）\n",
        ]
        if core_context:
            memory_section.append(f"- 核心智慧摘要: {core_context}\n")
        if current_goal:
            memory_section.append(f"- 本世代核心目标: {current_goal}\n")
        prompt_parts.extend(memory_section)

    # 添加工具手册索引
    if tools_index:
        prompt_parts.append("\n---\n")
        prompt_parts.append(tools_index)

    # 添加环境信息
    env_section = [
        "\n---\n",
        "## 当前环境\n",
        f"- 当前时间: {current_time}\n",
        f"- 项目根目录: {project_root}\n",
        f"- 静态提示词: core/core_prompt/\n",
        f"- 动态提示词: workspace/prompts/\n",
    ]
    prompt_parts.extend(env_section)

    return "".join(prompt_parts)


def build_simple_system_prompt() -> str:
    """
    简化版系统提示词（不加载记忆，仅用于初始化）。
    用于 Agent 启动时快速生成提示词。
    """
    return build_system_prompt(
        generation=1,
        total_generations=1,
        core_context="",
        current_goal="",
    )


if __name__ == "__main__":
    print(build_system_prompt())
