# -*- coding: utf-8 -*-
"""
core/prompt_manager/prompt_manager.py — 系统提示词管理器

基于 SystemPromptSection 架构的提示词组装引擎。

职责：
- 章节注册与管理（SystemPromptSection 注册表）
- 参数驱动拼接：build(include=[...], exclude=[...])
- 章节级缓存（静态章节全会话计算一次，动态章节每轮重算）
- 单例全局访问
- 状态记忆持久化
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, List, Dict, Any

from core.prompt_manager.types import (
    SystemPrompt,
    SystemPromptSection,
    BuildContext,
    as_system_prompt,
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
)
from core.prompt_manager.section_cache import SystemPromptCache
from core.prompt_manager.sections import (
    create_default_sections,
    make_memory_section,
)
from core.prompt_manager.builder import (
    get_system_prompt,
    to_string,
    split_sys_prompt_prefix,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 路径解析
# ═══════════════════════════════════════════════════════════════════════════════


def _get_static_root() -> Path:
    return Path(__file__).parent.parent / "core_prompt"


def _get_dynamic_root() -> Path:
    project_root = _resolve_project_root()
    return project_root / "workspace" / "prompts"


def _resolve_project_root() -> Path:
    import sys
    for name, mod in list(sys.modules.items()):
        if name == "agent" and mod and getattr(mod, '__file__', None):
            return Path(mod.__file__).parent.resolve()

    for sp in sys.path:
        p = os.path.join(sp, "agent.py")
        if os.path.exists(p):
            return Path(sp).resolve()

    return Path(__file__).parent.parent.parent.resolve()


# ═══════════════════════════════════════════════════════════════════════════════
# PromptManager
# ═══════════════════════════════════════════════════════════════════════════════


class PromptManager:
    """系统提示词管理器。

    基于 SystemPromptSection 注册表 + 章节级缓存。
    通过 build() 组装 SystemPrompt（字符串元组），
    支持 include/exclude 过滤、LLM 动态切换、状态记忆。
    """

    _DYNAMIC_FILES = {"IDENTITY.md", "USER.md", "DYNAMIC.md", "COMPRESS_SUMMARY.md"}

    def __init__(self, enable_workspace: bool = False):
        self._workspace_enabled = enable_workspace
        self._static_root = _get_static_root()
        self._dynamic_root = _get_dynamic_root()
        self._project_root = _resolve_project_root()

        if enable_workspace:
            self._dynamic_root.mkdir(parents=True, exist_ok=True)
            for fname in self._DYNAMIC_FILES:
                self._ensure_dynamic_file(fname)

        # 章节注册表
        self._sections: Dict[str, SystemPromptSection] = {}

        # 章节级缓存
        self._section_cache = SystemPromptCache()

        # 构建上下文（每轮 build 前更新，MEMORY 章节的 compute 从中读取）
        self._build_context = BuildContext()

        # 状态记忆（内存持有，非文件加载）
        self.state_memory: str = ""

        # 当前目标（内存持有，每次动态生成，不从文件加载）
        self.current_goal: str = ""

        # LLM 动态覆盖
        self._active_sections_override: Optional[List[str]] = None

        # 从 config.toml 读取默认章节列表
        self._default_sections = self._load_default_sections_from_config()

        from core.logging import debug_logger
        debug_logger.info(
            f"[PromptManager] 初始化 - 静态: {self._static_root}, "
            f"workspace={'启用' if enable_workspace else '禁用'}"
        )

        # 注册默认章节（含 MEMORY，其 compute 引用 self._build_context）
        self._register_default_sections()

        if enable_workspace:
            self._load_persisted_state_memory()

        # 最近一次 build 的索引
        self._last_index: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------------
    # 章节注册
    # ------------------------------------------------------------------------

    def _register_default_sections(self):
        """注册所有默认章节。

        静态章节由 config.toml [[prompt.sections]] 驱动；
        动态章节（TASK_CHECKLIST、CODEBASE_MAP、ENV_INFO 等）由代码内置注册。
        """
        # 从 config 读取静态章节定义
        try:
            from config import get_config
            section_configs = get_config().prompt.sections
        except Exception:
            section_configs = []

        sections = create_default_sections(
            self._static_root,
            self._dynamic_root,
            self._project_root,
            enable_workspace=self._workspace_enabled,
            section_configs=section_configs,
        )
        for s in sections:
            self._sections[s.name] = s

        # MEMORY 章节：compute 引用 self._build_context
        self._sections["MEMORY"] = make_memory_section(self._build_context)

        from core.logging import debug_logger
        debug_logger.debug(
            f"[PromptManager] 注册默认章节: {list(self._sections.keys())}"
        )

    def register(self, section: SystemPromptSection):
        """注册或覆盖一个章节。"""
        self._sections[section.name] = section
        self._section_cache.invalidate(section.name)
        from core.logging import debug_logger
        debug_logger.debug(
            f"[PromptManager] 注册章节: {section.name} "
            f"(priority={section.priority}, cache_break={section.cache_break})"
        )

    def unregister(self, name: str):
        """取消注册一个章节。"""
        if name in self._sections:
            del self._sections[name]
            self._section_cache.invalidate(name)

    # ------------------------------------------------------------------------
    # build() — 核心组装入口
    # ------------------------------------------------------------------------

    def build(
        self,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        core_context: Optional[str] = None,
        current_goal: Optional[str] = None,
        state_memory: Optional[str] = None,
    ) -> SystemPrompt:
        """组装系统提示词。

        Args:
            include: 只包含这些章节（None 时使用默认列表或 override）。
            exclude: 排除这些章节（required=True 的无法排除）。
            core_context: 核心记忆。
            current_goal: 当前目标。
            state_memory: 状态记忆（None 时使用 self.state_memory）。

        Returns:
            SystemPrompt — 不可变字符串元组。
        """
        # 更新构建上下文（MEMORY 章节的 compute 从中读取）
        effective_state_memory = (
            state_memory if state_memory is not None else self.state_memory
        )
        effective_current_goal = (
            current_goal if current_goal is not None else self.current_goal
        )
        self._build_context.core_context = core_context
        self._build_context.current_goal = effective_current_goal
        self._build_context.state_memory = effective_state_memory

        # 筛选章节
        selected = self._select_sections(include, exclude)

        # 组装
        sp = get_system_prompt(selected, self._section_cache)

        # 记录索引
        self._last_index = [
            {
                "name": s.name,
                "length": len(s.compute() or ""),
                "cache_break": s.cache_break,
                "required": s.required,
                "is_empty": s.is_empty,
            }
            for s in selected
        ]

        from core.logging import debug_logger
        debug_logger.info(
            f"[PromptManager] 构建完成 (sections={len(selected)}, "
            f"len={len(to_string(sp))}, "
            f"cache={self._section_cache.stats})"
        )
        return sp

    def _select_sections(
        self,
        include: Optional[List[str]],
        exclude: Optional[List[str]],
    ) -> List[SystemPromptSection]:
        """根据 include/exclude 规则选择章节。

        优先级：
        1. include 非空 → 直接使用（参数优先）
        2. _active_sections_override 非空 → 使用 override（LLM 标签驱动）
        3. 使用 _default_sections
        """
        if include is not None:
            effective_include = include
        elif self._active_sections_override is not None:
            effective_include = self._active_sections_override
        else:
            effective_include = self._default_sections

        all_sections = sorted(self._sections.values(), key=lambda s: s.priority)

        if effective_include != ["*"]:
            names = set(effective_include)
            all_sections = [s for s in all_sections if s.name in names]

        if exclude is not None:
            excluded = set(exclude)
            all_sections = [
                s for s in all_sections
                if s.name not in excluded or s.required
            ]

        return all_sections

    # ------------------------------------------------------------------------
    # LLM 动态章节切换
    # ------------------------------------------------------------------------

    def select_components(self, components: List[str]):
        """由 LLM 通过 <active_components> 标签调用，动态切换章节。

        Args:
            components: 要激活的章节名称列表，如 ["SOUL", "SPEC", "MEMORY"]
        """
        if not components:
            from core.logging import debug_logger
            debug_logger.debug("[PromptManager] select_components 收到空列表，重置为默认")
            self._active_sections_override = None
            return

        known = [c for c in components if c in self._sections]
        if known:
            self._active_sections_override = known
            from core.logging import debug_logger
            debug_logger.info(f"[PromptManager] 动态切换章节: {known}")
        else:
            from core.logging import debug_logger
            debug_logger.warning(
                f"[PromptManager] 未知章节: {components}，保持当前不变"
            )

    # ------------------------------------------------------------------------
    # 状态记忆
    # ------------------------------------------------------------------------

    def update_current_goal(self, goal: str):
        """更新当前目标（仅内存，不落盘），触发缓存失效。

        与 state_memory 不同，current_goal 不持久化到文件——
        每次 Agent 苏醒时由 LLM 动态决定，仅存于内存中。
        """
        if not goal or not goal.strip():
            return

        self.current_goal = goal
        self._section_cache.invalidate("MEMORY")
        from core.logging import debug_logger
        debug_logger.debug(
            f"[PromptManager] current_goal 更新: {goal[:80]}"
        )

    def get_current_goal(self) -> str:
        """获取当前目标（内存值）。"""
        return self.current_goal

    def update_state_memory(self, memory_text: str):
        """更新状态记忆（内存 + 落盘），触发缓存失效。"""
        if not memory_text or not memory_text.strip():
            return

        self.state_memory = memory_text
        self._persist_state_memory(memory_text)
        self._section_cache.invalidate("MEMORY")
        from core.logging import debug_logger
        debug_logger.debug(
            f"[PromptManager] state_memory 更新，长度={len(memory_text)}"
        )

    def _persist_state_memory(self, memory_text: str):
        try:
            state_memory_path = self._dynamic_root / "STATE_MEMORY.md"
            state_memory_path.write_text(memory_text, encoding="utf-8")
            from core.logging import debug_logger
            debug_logger.info(f"[PromptManager] state_memory 已落盘: {state_memory_path}")
        except Exception as e:
            from core.logging import debug_logger
            debug_logger.warning(f"[PromptManager] state_memory 落盘失败: {e}")

    def _load_persisted_state_memory(self):
        try:
            state_memory_path = self._dynamic_root / "STATE_MEMORY.md"
            if state_memory_path.exists():
                content = state_memory_path.read_text(encoding="utf-8").strip()
                match = re.match(r'^---\s*\n.*?\n---(\n)?', content, re.DOTALL)
                if match:
                    content = content[match.end():].strip()
                if content:
                    self.state_memory = content
                    from core.logging import debug_logger
                    debug_logger.info(
                        f"[PromptManager] 从会话恢复 state_memory，长度={len(content)}"
                    )
        except Exception as e:
            from core.logging import debug_logger
            debug_logger.warning(f"[PromptManager] 恢复 state_memory 失败: {e}")

    # ------------------------------------------------------------------------
    # 默认配置
    # ------------------------------------------------------------------------

    def _load_default_sections_from_config(self) -> List[str]:
        try:
            from config import get_config
            components = get_config().prompt.default_components
            if components:
                from core.logging import debug_logger
                debug_logger.info(f"[PromptManager] 从 config 加载默认章节: {components}")
                return components
        except Exception:
            pass
        return ["SOUL", "SPEC", "ENV_INFO"]

    # ------------------------------------------------------------------------
    # Workspace 文件管理
    # ------------------------------------------------------------------------

    def _ensure_dynamic_file(self, name: str) -> bool:
        path = self._dynamic_root / name
        if path.exists():
            return True

        default_content = self._get_default_template(name)
        if default_content is None:
            return True

        try:
            path.write_text(default_content, encoding="utf-8")
            from core.logging import debug_logger
            debug_logger.info(f"[PromptManager] 自动生成默认模板: workspace/prompts/{name}")
            return False
        except Exception as e:
            from core.logging import debug_logger
            debug_logger.warning(f"[PromptManager] 生成 {name} 失败: {e}")
            return False

    def _get_default_template(self, name: str) -> Optional[str]:
        templates = {
            "DYNAMIC.md": (
                "---\nname: DYNAMIC\npriority: 40\nrequired: false\n"
                "description: 动态提示词区域，由 Agent 在每个世代开始时动态生成\n---\n"
            ),
            "COMPRESS_SUMMARY.md": (
                "---\nname: MEMORY\npriority: 80\nrequired: false\n"
                "description: 上下文压缩摘要，记录历史对话中的关键信息和结论\n---\n"
            ),
            "IDENTITY.md": (
                "---\nname: IDENTITY\npriority: 50\nrequired: false\n"
                "description: Agent 身份定义，由 Agent 运行时自行维护\n---\n"
            ),
            "USER.md": (
                "---\nname: USER\npriority: 70\nrequired: false\n"
                "description: 用户环境与偏好，由 Agent 运行时自行维护\n---\n"
            ),
        }
        return templates.get(name)

    # ------------------------------------------------------------------------
    # 缓存管理
    # ------------------------------------------------------------------------

    def invalidate_cache(self, name: Optional[str] = None):
        """清除章节缓存。name 为 None 则清除全部。"""
        self._section_cache.invalidate(name)
        from core.logging import debug_logger
        debug_logger.debug(
            f"[PromptManager] 清除缓存: {name or '全部'}"
        )

    def get_cache_stats(self) -> Dict[str, Any]:
        return self._section_cache.stats

    # ------------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        return {
            "static_root": str(self._static_root),
            "dynamic_root": str(self._dynamic_root),
            "registered_sections": list(self._sections.keys()),
            "state_memory_length": len(self.state_memory) if self.state_memory else 0,
            "current_goal": self.current_goal,
            "active_sections_override": self._active_sections_override,
            "section_cache": self._section_cache.stats,
            "last_index": self._last_index,
        }

    def list_sections(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "priority": s.priority,
                "required": s.required,
                "cache_break": s.cache_break,
                "is_empty": s.is_empty,
            }
            for s in sorted(self._sections.values(), key=lambda x: x.priority)
        ]

    def get_last_index(self) -> List[Dict[str, Any]]:
        """返回最近一次 build() 的章节索引。"""
        return self._last_index


# ═══════════════════════════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════════════════════════

_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷函数（向后兼容）
# ═══════════════════════════════════════════════════════════════════════════════


def build_system_prompt(
    core_context: Optional[str] = None,
    current_goal: Optional[str] = None,
) -> str:
    """构建系统提示词字符串（向后兼容）。"""
    sp = get_prompt_manager().build(
        core_context=core_context,
        current_goal=current_goal,
    )
    return to_string(sp)


def build_simple_system_prompt() -> str:
    """简化版系统提示词（向后兼容）。"""
    return build_system_prompt(
        core_context="",
        current_goal="",
    )
