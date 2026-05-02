# -*- coding: utf-8 -*-
"""系统提示词章节工厂函数

为每个提示词章节提供工厂函数，返回 SystemPromptSection。
静态章节 cache_break=False（全会话计算一次），
动态章节 cache_break=True（每轮重新计算）。
"""

from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

from core.prompt_manager.types import SystemPromptSection, BuildContext


# ═══════════════════════════════════════════════════════════════════════════════
# 通用文件章节工厂
# ═══════════════════════════════════════════════════════════════════════════════


def make_file_section(
    name: str,
    path: Path,
    priority: int = 50,
    cache_break: bool = False,
    description: str = "",
    required: bool = False,
) -> SystemPromptSection:
    """从 Markdown 文件创建章节，自动跳过 YAML front matter。"""

    # 预检内容是否为空（注册时检测一次）
    empty = True
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8").strip()
            match = re.match(r'^---\s*\n.*?\n---(\n)?', raw, re.DOTALL)
            body = raw[match.end():].strip() if match else raw
            empty = not bool(body)
        except Exception:
            empty = True

    def compute() -> Optional[str]:
        if not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8").strip()
            match = re.match(r'^---\s*\n.*?\n---(\n)?', content, re.DOTALL)
            if match:
                content = content[match.end():].strip()
            return content or None
        except Exception:
            return None

    return SystemPromptSection(
        name=name,
        compute=compute,
        cache_break=cache_break,
        priority=priority,
        description=description,
        required=required,
        is_empty=empty,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 静态章节工厂（cache_break=False）
# ═══════════════════════════════════════════════════════════════════════════════


def make_spec_section(project_root: Path) -> SystemPromptSection:
    """SPEC_Agent.md — 开发规范与编码约束。"""
    spec_path = project_root / "core" / "requirement" / "SPEC" / "SPEC_Agent.md"

    def compute() -> Optional[str]:
        if spec_path.exists():
            try:
                return spec_path.read_text(encoding="utf-8").strip() or None
            except Exception:
                return None
        return None

    return SystemPromptSection(
        name="SPEC",
        compute=compute,
        cache_break=False,
        priority=65,
        description="开发规范与编码约束",
    )


def make_task_checklist_section() -> SystemPromptSection:
    """任务清单 — 从 TaskPlanner 动态加载。"""

    def compute() -> Optional[str]:
        try:
            from core.orchestration.task_planner import get_task_manager
            tm = get_task_manager()
            return tm.get_active_tasks() or None
        except Exception:
            return None

    return SystemPromptSection(
        name="TASK_CHECKLIST",
        compute=compute,
        cache_break=False,
        priority=20,
        description="当前激活的任务清单",
    )


def make_codebase_map_section() -> SystemPromptSection:
    """代码库认知地图 — AST 扫描结果。"""

    def compute() -> Optional[str]:
        try:
            from tools.codebase_analyzer import CodebaseAnalyzer
            analyzer = CodebaseAnalyzer()
            analyzer.scan_project()
            return analyzer.format_as_markdown() or None
        except Exception:
            try:
                from core.prompt_manager.codebase_map_builder import get_codebase_map
                return get_codebase_map(force_refresh=True) or None
            except Exception:
                return None

    return SystemPromptSection(
        name="CODEBASE_MAP",
        compute=compute,
        cache_break=False,
        priority=30,
        description="代码库结构认知地图",
    )


def make_tools_index_section(project_root: Path) -> SystemPromptSection:
    """工具索引 — 从 tools_manual.md 提取精简列表。"""

    def compute() -> Optional[str]:
        try:
            tools_manual = project_root / "docs" / "tools_manual.md"
            if not tools_manual.exists():
                return None
            content = tools_manual.read_text(encoding="utf-8")
            lines = content.split("\n")
            index_lines = ["\n## 工具手册索引", ""]
            for line in lines:
                if "`" in line and "|" in line:
                    parts = line.split("`")
                    if len(parts) >= 2:
                        tool_name = parts[1].strip()
                        if tool_name and not tool_name.startswith("#"):
                            index_lines.append(f"- `{tool_name}`")
            result = "\n".join(index_lines[:20])
            return result or None
        except Exception:
            return None

    return SystemPromptSection(
        name="TOOLS_INDEX",
        compute=compute,
        cache_break=False,
        priority=90,
        description="工具手册索引",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 动态章节工厂（cache_break=True）
# ═══════════════════════════════════════════════════════════════════════════════


def make_env_info_section(project_root: Path) -> SystemPromptSection:
    """环境信息 — 时间以 5 分钟粒度稳定，保持缓存友好。"""

    def compute() -> Optional[str]:
        now = datetime.now()
        rounded_minute = (now.minute // 5) * 5
        rounded_time = now.replace(minute=rounded_minute, second=0, microsecond=0)
        current_time = rounded_time.strftime("%Y-%m-%d %H:%M")

        import platform
        os_name = {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}.get(
            platform.system(), platform.system()
        )

        return "\n".join([
            "## 当前环境",
            f"- 当前时间: {current_time}",
            f"- 操作系统: {os_name} ({platform.version()}) [{platform.machine()}]",
            f"- 项目根目录: {project_root}",
            f"- 静态提示词位置: core/core_prompt/",
            f"- 动态提示词位置: workspace/prompts/",
        ])

    return SystemPromptSection(
        name="ENV_INFO",
        compute=compute,
        cache_break=True,
        priority=100,
        description="系统环境信息",
    )


def make_memory_section(ctx: BuildContext) -> SystemPromptSection:
    """记忆章节 — 参数驱动，每轮重新计算。"""

    def compute() -> Optional[str]:
        generation = ctx.generation
        total_generations = ctx.total_generations
        core_context = ctx.core_context
        current_goal = ctx.current_goal
        state_memory = ctx.state_memory

        if generation is None:
            memory_data = _load_memory_from_tools()
            generation = memory_data.get("generation", 1)
            total_generations = memory_data.get("total_generations", 1)
            if core_context is None:
                core_context = memory_data.get("core_context", "")
            if current_goal is None:
                current_goal = memory_data.get("current_goal", "")

        if not core_context and not current_goal and not state_memory:
            return None

        lines = [
            "## 你的记忆与状态",
            f"- 当前世代: G{generation}（共{total_generations}代）",
        ]
        if core_context:
            lines.append(f"- 核心智慧摘要: {core_context}")
        if current_goal:
            lines.append(f"- 本世代核心目标: {current_goal}")
        if state_memory:
            lines.append(f"- 状态记忆:\n{state_memory}")

        return "\n".join(lines)

    return SystemPromptSection(
        name="MEMORY",
        compute=compute,
        cache_break=True,
        priority=80,
        description="Agent 记忆与状态",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 默认章节列表创建
# ═══════════════════════════════════════════════════════════════════════════════


def create_default_sections(
    static_root: Path,
    dynamic_root: Path,
    project_root: Path,
    enable_workspace: bool = False,
) -> List[SystemPromptSection]:
    """创建默认章节列表（不含 MEMORY，它依赖 BuildContext 在 build 时动态创建）。"""

    sections: List[SystemPromptSection] = []

    # ── 静态章节 ──

    soul_path = static_root / "SOUL.md"
    if soul_path.exists():
        sections.append(make_file_section(
            "SOUL", soul_path, priority=10, required=True,
            description="身份使命与铁律",
        ))

    agents_path = static_root / "AGENTS.md"
    if agents_path.exists():
        sections.append(make_file_section(
            "AGENTS", agents_path, priority=60, required=True,
            description="SOP 操作规范",
        ))

    sections.append(make_spec_section(project_root))
    sections.append(make_task_checklist_section())
    sections.append(make_codebase_map_section())
    sections.append(make_tools_index_section(project_root))

    # ── 动态章节 ──

    sections.append(make_env_info_section(project_root))

    # ── Workspace 章节（仅在启用时注册）──

    if enable_workspace:
        for fname, pri, desc in [
            ("IDENTITY.md", 50, "Agent 身份定义"),
            ("USER.md", 70, "用户环境与偏好"),
            ("DYNAMIC.md", 40, "动态提示词区域"),
        ]:
            fpath = dynamic_root / fname
            name = fname.replace(".md", "")
            if fpath.exists():
                sections.append(make_file_section(
                    name, fpath, priority=pri, cache_break=True, description=desc,
                ))
            else:
                sections.append(SystemPromptSection(
                    name=name, compute=lambda: None, cache_break=True,
                    priority=pri, description=f"{desc}（空）", is_empty=True,
                ))

    return sections


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════════════════════


def _load_memory_from_tools() -> Dict[str, Any]:
    """从 memory_tools 加载记忆数据（fallback）。"""
    try:
        from tools.memory_tools import read_memory_tool
        import json as _json
        raw = read_memory_tool()
        if isinstance(raw, str):
            data = _json.loads(raw)
        else:
            data = raw
        return {
            "generation": data.get("current_generation") or data.get("generation", 1),
            "total_generations": data.get("total_generations", 1),
            "core_context": data.get("core_wisdom") or data.get("core_context", ""),
            "current_goal": data.get("current_goal", ""),
        }
    except Exception:
        return {
            "generation": 1,
            "total_generations": 1,
            "core_context": "",
            "current_goal": "",
        }
