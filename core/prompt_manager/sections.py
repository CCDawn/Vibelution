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
    """代码库认知地图 — 读取缓存文件（由 ToolExecutor 钩子自动更新）。"""

    def compute() -> Optional[str]:
        try:
            from core.prompt_manager.codebase_map_builder import get_codebase_map
            return get_codebase_map(force_refresh=False) or None
        except Exception:
            return None

    return SystemPromptSection(
        name="CODEBASE_MAP",
        compute=compute,
        cache_break=False,
        priority=30,
        description="代码库结构认知地图（自动更新）",
    )


def make_tools_index_section(project_root: Path) -> SystemPromptSection:
    """工具索引 — 从 Key_Tools.create_key_tools() 动态提取已注册工具。"""

    def compute() -> Optional[str]:
        try:
            from tools.Key_Tools import create_key_tools
            tools = create_key_tools()
            if not tools:
                return None
            lines = ["## 工具索引", f"共 {len(tools)} 个已注册工具：", ""]
            for t in tools:
                desc = getattr(t, 'description', '') or ''
                first_line = desc.strip().split('\n')[0].strip()
                if first_line:
                    lines.append(f"- `{t.name}`: {first_line}")
                else:
                    lines.append(f"- `{t.name}`")
            return "\n".join(lines)
        except Exception:
            return None

    return SystemPromptSection(
        name="TOOLS_INDEX",
        compute=compute,
        cache_break=False,
        priority=90,
        description="已注册工具索引（动态生成）",
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
    """记忆章节 — 参数驱动，每轮重新计算。注入元认知干预。"""

    def compute() -> Optional[str]:
        core_context = ctx.core_context
        current_goal = ctx.current_goal
        state_memory = ctx.state_memory

        # ── 元认知干预 ──
        intervention = ""
        try:
            from core.infrastructure.mental_model import get_mental_model
            mm = get_mental_model()
            intervention = mm.get_intervention_for_prompt()
        except Exception:
            pass

        if not core_context and not current_goal and not state_memory and not intervention:
            return None

        lines = [
            "## 你的记忆与状态",
        ]
        if core_context:
            lines.append(f"- 核心智慧摘要: {core_context}")
        if current_goal:
            lines.append(f"- 当前核心目标: {current_goal}")
        if state_memory:
            lines.append(f"- 状态记忆:\n{state_memory}")

        # 元认知干预追加到末尾
        if intervention:
            lines.append(intervention)

        return "\n".join(lines)

    return SystemPromptSection(
        name="MEMORY",
        compute=compute,
        cache_break=True,
        priority=80,
        description="Agent 记忆与状态 + 元认知干预",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 默认章节列表创建
# ═══════════════════════════════════════════════════════════════════════════════


def create_default_sections(
    static_root: Path,
    dynamic_root: Path,
    project_root: Path,
    enable_workspace: bool = False,
    section_configs: Optional[List[Any]] = None,
) -> List[SystemPromptSection]:
    """创建默认章节列表（不含 MEMORY，它依赖 BuildContext 在 build 时动态创建）。

    Args:
        section_configs: [[prompt.sections]] 配置列表，每项含 name/path/priority 等属性。
            静态章节由此驱动；为 None 或空列表时不注册任何静态章节。
    """

    sections: List[SystemPromptSection] = []

    # ── 静态章节（由 config.toml [[prompt.sections]] 驱动）──

    for cfg in (section_configs or []):
        section_path = project_root / cfg.path
        if section_path.exists():
            sections.append(make_file_section(
                cfg.name,
                section_path,
                priority=getattr(cfg, 'priority', 50),
                cache_break=getattr(cfg, 'cache_break', False),
                description=getattr(cfg, 'description', ''),
                required=getattr(cfg, 'required', False),
            ))

    # ── 内置动态章节 ──

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
            # 文件不存在则不注册（不再注册空占位章节）

    return sections


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════════════════════


