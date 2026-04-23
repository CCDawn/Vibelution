# -*- coding: utf-8 -*-
"""
core/capabilities/prompt_manager.py - 动态系统提示词管理器

支持参数驱动的组件拼接，单例全局访问。

设计原则：
- 参数驱动拼接：build(include=[...], exclude=[...])
- 单例全局访问：get_prompt_manager()
- 核心组件硬编码顺序，扩展组件可插拔
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Callable, Any


def _get_static_root() -> Path:
    """获取 core/core_prompt/ 静态路径（内置模板）"""
    return Path(__file__).parent.parent / "core_prompt"


def _get_dynamic_root() -> Path:
    """获取 workspace/prompts/ 动态路径（用户覆盖层）"""
    project_root = _resolve_project_root()
    return project_root / "workspace" / "prompts"


def _resolve_project_root() -> Path:
    """推断项目根目录"""
    import sys
    for name, mod in list(sys.modules.items()):
        if name == "agent" and mod and getattr(mod, '__file__', None):
            return Path(mod.__file__).parent.resolve()

    for sp in sys.path:
        p = os.path.join(sp, "agent.py")
        if os.path.exists(p):
            return Path(sp).resolve()

    return Path(__file__).parent.parent.parent.resolve()


# ============================================================================
# PromptComponent - 组件定义
# ============================================================================

@dataclass
class PromptComponent:
    """
    单个提示词组件。

    Attributes:
        name:        唯一标识，如 "SOUL", "AGENTS", "TASK_CHECKLIST"
        priority:    优先级（数字越小越靠前，default=50）
        required:    是否必选（True 时 exclude 无法移除）
        load_fn:     加载函数，返回文本内容
        enabled:      是否启用（可动态开关）
    """
    name: str
    priority: int = 50
    required: bool = False
    load_fn: Callable[[], str] = field(default_factory=lambda: lambda: "")
    enabled: bool = True


# ============================================================================
# PromptManager - 核心类
# ============================================================================

class PromptManager:
    """
    动态系统提示词管理器。

    职责：
    - 管理提示词组件注册表（核心硬编码 + 扩展可配）
    - 参数驱动的组件拼接：build(include, exclude, ...)
    - 单例模式全局访问
    - 双轨加载
    - 缓存失效机制
    """

    # 核心只读文件（仅来自 static，不支持 workspace 覆盖）
    _STATIC_ONLY_FILES = {"SOUL.md", "AGENTS.md"}

    # 纯动态文件（仅来自 workspace，不存在时自动生成默认模板）
    _DYNAMIC_FILES = {"IDENTITY.md", "USER.md", "DYNAMIC.md", "COMPRESS_SUMMARY.md"}

    # 状态机增强：规则注册表 + 当前激活规则 + 状态记忆（在 __init__ 中初始化）
    # prompt_registry: Dict[str, str] — 在 __init__ 中初始化为 {}
    # current_active_prompts: List[str]   — 在 __init__ 中初始化为 []
    # state_memory: str                   — 在 __init__ 中初始化为 ""

    def __init__(self):
        self._static_root = _get_static_root()
        self._dynamic_root = _get_dynamic_root()
        self._dynamic_root.mkdir(parents=True, exist_ok=True)

        # 初始化：确保所有动态文件存在（缺失则生成默认模板）
        for fname in self._DYNAMIC_FILES:
            self._ensure_dynamic_file(fname)

        # 组件注册表
        self._components: Dict[str, PromptComponent] = {}

        # 缓存
        self._cache: Dict[str, str] = {}
        self._cache_sources: Dict[str, str] = {}

        # 规则注册表（硬编码，非文件系统扫描）
        self.prompt_registry: Dict[str, str] = {}
        # 当前激活的规则集名称列表
        self.current_active_prompts: List[str] = []
        # 当前状态记忆（从 LLM <state_memory> 标签提取）
        self.state_memory: str = ""

        # LLM 动态覆盖：<active_components> 标签驱动的组件切换
        # 当非 None 时，build() 使用此列表而非默认 include
        self._active_components_override: Optional[List[str]] = None

        from core.logging import debug_logger; debug_logger.info(f"[PromptManager] 初始化 - 静态: {self._static_root}")
        from core.logging import debug_logger; debug_logger.info(f"[PromptManager] 初始化 - 动态: {self._dynamic_root}")

        # 注册所有组件
        self._register_core_components()
        self._register_default_rules()
        self._scan_workspace_prompts()

        # 加载上次会话遗留的 state_memory（如果有）
        self._load_persisted_state_memory()

    # ------------------------------------------------------------------------
    # 组件注册
    # ------------------------------------------------------------------------

    def _register_core_components(self):
        """注册核心组件（硬编码顺序）"""
        self.register(PromptComponent(
            name="SOUL",
            priority=10,
            required=True,
            load_fn=self._load_soul,
        ))
        self.register(PromptComponent(
            name="TASK_CHECKLIST",
            priority=20,
            required=False,
            load_fn=self._load_task_checklist,
        ))
        self.register(PromptComponent(
            name="CODEBASE_MAP",
            priority=30,
            required=False,
            load_fn=self._load_codebase_map,
        ))
        self.register(PromptComponent(
            name="DYNAMIC",
            priority=40,
            required=False,
            load_fn=self._load_dynamic,
        ))
        self.register(PromptComponent(
            name="IDENTITY",
            priority=50,
            required=False,
            load_fn=self._load_identity,
        ))
        self.register(PromptComponent(
            name="AGENTS",
            priority=60,
            required=True,
            load_fn=self._load_agents,
        ))
        self.register(PromptComponent(
            name="SPEC",
            priority=65,
            required=False,
            load_fn=self._load_spec,
        ))
        self.register(PromptComponent(
            name="USER",
            priority=70,
            required=False,
            load_fn=self._load_user,
        ))
        self.register(PromptComponent(
            name="MEMORY",
            priority=80,
            required=False,
            load_fn=self._load_memory_context,
        ))
        self.register(PromptComponent(
            name="TOOLS_INDEX",
            priority=90,
            required=False,
            load_fn=self._load_tools_index,
        ))
        self.register(PromptComponent(
            name="ENV_INFO",
            priority=100,
            required=False,
            load_fn=self._load_env_info,
        ))
        self.register(PromptComponent(
            name="current_rules",
            priority=85,
            required=False,
            load_fn=self._load_current_rules,
        ))

    def register(self, component: PromptComponent):
        """注册或更新组件"""
        self._components[component.name] = component
        from core.logging import debug_logger; debug_logger.debug(f"[PromptManager] 注册组件: {component.name} (priority={component.priority}, required={component.required})")

    def unregister(self, name: str):
        """取消注册组件"""
        if name in self._components:
            del self._components[name]
            from core.logging import debug_logger; debug_logger.debug(f"[PromptManager] 取消注册: {name}")

    def set_enabled(self, name: str, enabled: bool):
        """动态启用/禁用组件"""
        if name in self._components:
            self._components[name].enabled = enabled

    def _scan_workspace_prompts(self):
        """
        动态扫描 workspace/prompts/ 目录，自动将所有 .md 文件注册为组件。
        文件名去掉 .md 作为组件名；已有硬编码组件覆盖同名文件（大小写不敏感）。
        """
        if not self._dynamic_root.exists():
            return
        # 已注册组件名的大写集合，用于去重
        existing_upper = {k.upper() for k in self._components}
        for md_file in sorted(self._dynamic_root.glob("*.md")):
            name = md_file.stem  # e.g. "DYNAMIC", "IDENTITY", "USER"
            if name.upper() in existing_upper:
                continue  # 已有硬编码组件覆盖（大小写不敏感），跳过
            path = md_file

            def make_load(p=path):
                def load():
                    return self._load_from_path(p, p.stem)
                return load

            self.register(PromptComponent(
                name=name,
                priority=50,
                required=False,
                load_fn=make_load(),
            ))
            from core.logging import debug_logger; debug_logger.debug(f"[PromptManager] 动态扫描注册组件: {name} -> {md_file}")

    # ------------------------------------------------------------------------
    # 规则注册表（硬编码，非文件系统扫描）
    # ------------------------------------------------------------------------

    def _register_default_rules(self):
        """注册默认规则集"""
        self.register_rule("base", "")
        self.register_rule("code_review", """## 当前规则：代码审查
- 每次修改前先理解原有逻辑，不要破坏既有行为
- 优先修复明显 bug，再优化性能
- 改动必须有测试覆盖""")
        self.register_rule("creative", """## 当前规则：创意发散
- 不拘泥于现有方案，大胆提出新思路
- 评估可行性时考虑长期维护成本
- 鼓励渐进式创新而非激进重构""")
        self.register_rule("debug", """## 当前规则：调试诊断
- 先复现问题，确认触发条件
- 用最小改动定位根因
- 修改后验证问题确实解决""")
        self.register_rule("planning", """## 当前规则：任务规划
- 分解任务为可验证的子任务
- 每个子任务完成后立即验证
- 记录结论，避免重复探索""")
        self.register_rule("refactor", """## 当前规则：重构优化
- 重构不改变外部行为
- 每次重构后运行测试
- 优先清理技术债务最严重的地方""")
        self.current_active_prompts = ["base"]

    def register_rule(self, name: str, content: str):
        """注册或更新规则"""
        self.prompt_registry[name] = content
        from core.logging import debug_logger; debug_logger.debug(f"[PromptManager] 注册规则: {name}")

    def update_active_rules(self, rules: List[str]):
        """
        更新当前激活的规则集（由 LLM 通过 <active_rules> 标签调用）

        Args:
            rules: 新的激活规则名称列表（如 ["code_review", "debug"]）
        """
        if not rules:
            from core.logging import debug_logger; debug_logger.debug("[PromptManager] active_rules 为空，保持当前规则不变")
            return

        # 只注册已知规则，未知规则名忽略
        known_rules = [r for r in rules if r in self.prompt_registry]
        if known_rules:
            self.current_active_prompts = known_rules
            from core.logging import debug_logger; debug_logger.info(f"[PromptManager] 激活规则切换: {known_rules}")
        else:
            from core.logging import debug_logger; debug_logger.warning(f"[PromptManager] 未知规则: {rules}，保持当前规则不变")

    def _load_current_rules(self) -> str:
        """
        拼接当前激活规则集的文本内容

        Returns:
            拼接后的规则文本（无激活规则时返回空字符串）
        """
        if not self.current_active_prompts:
            return ""

        parts = []
        for name in self.current_active_prompts:
            content = self.prompt_registry.get(name, "")
            if content:
                parts.append(content)

        if not parts:
            return ""

        return "\n\n".join(parts)

    # ------------------------------------------------------------------------
    # 状态记忆持久化
    # ------------------------------------------------------------------------

    def _load_persisted_state_memory(self):
        """从 workspace/prompts/STATE_MEMORY.md 恢复上次会话的状态记忆"""
        try:
            state_memory_path = self._dynamic_root / "STATE_MEMORY.md"
            if state_memory_path.exists():
                content = state_memory_path.read_text(encoding="utf-8").strip()
                if content:
                    self.state_memory = content
                    from core.logging import debug_logger; debug_logger.info(f"[PromptManager] 从会话恢复 state_memory，长度={len(content)}")
        except Exception as e:
            from core.logging import debug_logger; debug_logger.warning(f"[PromptManager] 恢复 state_memory 失败: {e}")

    def update_state_memory(self, memory_text: str):
        """
        更新状态记忆（内存缓存 + 落盘持久化）

        Args:
            memory_text: LLM 通过 <state_memory> 标签回写的状态文本
        """
        if not memory_text or not memory_text.strip():
            return

        self.state_memory = memory_text
        self._persist_state_memory(memory_text)
        from core.logging import debug_logger; debug_logger.debug(f"[PromptManager] state_memory 更新，长度={len(memory_text)}")

    def _persist_state_memory(self, memory_text: str):
        """将 state_memory 落盘到 workspace/prompts/STATE_MEMORY.md"""
        try:
            state_memory_path = self._dynamic_root / "STATE_MEMORY.md"
            state_memory_path.write_text(memory_text, encoding="utf-8")
            from core.logging import debug_logger; debug_logger.info(f"[PromptManager] state_memory 已落盘: {state_memory_path}")
        except Exception as e:
            from core.logging import debug_logger; debug_logger.warning(f"[PromptManager] state_memory 落盘失败: {e}")

    # ------------------------------------------------------------------------
    # build() - 参数驱动拼接
    # ------------------------------------------------------------------------


    def _load_components(
        self,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        generation: Optional[int] = None,
        total_generations: Optional[int] = None,
        core_context: Optional[str] = None,
        current_goal: Optional[str] = None,
        state_memory: Optional[str] = None,
    ) -> tuple[Dict[str, str], List[Dict[str, Any]]]:
        """
        加载并渲染所有组件，返回内容字典和索引列表。

        Returns:
            (content_by_name, index_list)
            content_by_name: { "SOUL": "...", "AGENTS": "...", ... }
            index_list: 每项格式同 build_index
        """
        effective_state_memory = state_memory if state_memory is not None else self.state_memory
        # 传入 None 让 _select_components 内部处理 override 逻辑
        selected = self._select_components(include, exclude)

        content_by_name: Dict[str, str] = {}
        index_list: List[Dict[str, Any]] = []

        for comp in selected:
            try:
                content = comp.load_fn()
                if comp.name == "MEMORY":
                    content = self._render_memory(
                        generation=generation,
                        total_generations=total_generations,
                        core_context=core_context,
                        current_goal=current_goal,
                        state_memory=effective_state_memory,
                    )
                if content and content.strip():
                    content_by_name[comp.name] = content
                    index_list.append({
                        "name": comp.name,
                        "source": self._cache_sources.get(comp.name, "unknown"),
                        "length": len(content),
                        "enabled": comp.enabled,
                        "required": comp.required,
                    })
            except Exception as e:
                from core.logging import debug_logger; debug_logger.warning(f"[PromptManager] 组件 {comp.name} 加载失败: {e}")

        return content_by_name, index_list

    def build(
        self,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        generation: Optional[int] = None,
        total_generations: Optional[int] = None,
        core_context: Optional[str] = None,
        current_goal: Optional[str] = None,
        state_memory: Optional[str] = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """
        构建动态系统提示词，同时返回拼接索引。

        Args:
            include:   只包含这些组件（None 时由 _active_components_override 决定；
                       override 也为 None 则默认 ["SOUL","AGENTS","current_rules"]，MEMORY 不默认注入）
            exclude:   排除这些组件（required=True 的组件无法被排除）
            generation:       当前世代数
            total_generations: 总世代数
            core_context:     跨代核心记忆
            current_goal:     本世代目标
            state_memory:     状态记忆（注入 MEMORY 组件；若为 None 则使用 self.state_memory）

        Returns:
            (组装完成的系统提示词字符串, index_list)
            index_list 每项格式：
            {
                "name": 组件名,
                "source": "static" | "workspace",
                "length": 字符数,
                "enabled": bool,
                "required": bool,
            }
        """
        content_by_name, index_list = self._load_components(
            include=include,
            exclude=exclude,
            generation=generation,
            total_generations=total_generations,
            core_context=core_context,
            current_goal=current_goal,
            state_memory=state_memory,
        )
        selected = self._select_components(include, exclude)
        parts = [content_by_name[c.name] for c in selected if c.name in content_by_name]
        component_index = self._build_component_index()
        prompt = component_index + "\n\n".join(parts)
        return prompt, index_list


    def select_components(self, components: List[str]):
        """
        由 LLM 通过 <active_components> 标签调用，动态切换提示词组件拼装。

        用法：在回复中输出 <active_components>SOUL, AGENTS, MEMORY, current_rules</active_components>
        Agent 即可主动控制本次会话的提示词组件组成。

        Args:
            components: 要激活的组件名称列表，如 ["SOUL", "AGENTS", "MEMORY"]
        """
        if not components:
            from core.logging import debug_logger; debug_logger.debug("[PromptManager] select_components 收到空列表，重置为默认")
            self._active_components_override = None
            return

        # 只注册已知组件，未知组件名忽略
        known = [c for c in components if c in self._components]
        if known:
            self._active_components_override = known
            from core.logging import debug_logger; debug_logger.info(f"[PromptManager] 动态切换组件: {known}")
        else:
            from core.logging import debug_logger; debug_logger.warning(f"[PromptManager] 未知组件: {components}，保持当前组件不变")

    # ------------------------------------------------------------------------
    # _select_components() - 内部组件选择逻辑
    # ------------------------------------------------------------------------

    def _select_components(
        self,
        include: Optional[List[str]],
        exclude: Optional[List[str]],
    ) -> List[PromptComponent]:
        """
        根据 include/exclude 规则 + _active_components_override 选择组件。

        优先级：
        1. 若 include 非空，直接使用 include（参数优先）
        2. 若 _active_components_override 非空，使用 override（LLM 标签驱动）
        3. 否则使用默认 include

        规则：
        - include 非空时，只选指定的组件
        - exclude 非空时，排除指定的组件（required=True 的无法排除）
        - 按 priority 升序排列
        """
        # 确定最终 include 列表
        if include is not None:
            effective_include = include
        elif self._active_components_override is not None:
            effective_include = self._active_components_override
        else:
            effective_include = ["SOUL", "AGENTS", "SPEC", "ENV_INFO", "current_rules"]  # 默认，不再包含 MEMORY

        all_comps = sorted(self._components.values(), key=lambda c: c.priority)

        # 应用 include 过滤
        names = set(effective_include)
        all_comps = [c for c in all_comps if c.name in names]

        # 应用 exclude 过滤（required 组件无法排除）
        if exclude is not None:
            excluded = set(exclude)
            all_comps = [c for c in all_comps if c.name not in excluded or c.required]

        # 只返回启用状态的组件
        return [c for c in all_comps if c.enabled]

    # ------------------------------------------------------------------------
    # 组件加载函数
    # ------------------------------------------------------------------------

    def _load_static_only(self, name: str) -> str:
        """只读加载：仅从 static（core/core_prompt/），不支持 workspace 覆盖"""
        static_path = self._static_root / name
        return self._load_from_path(static_path, name)

    def _ensure_dynamic_file(self, name: str) -> bool:
        """
        确保动态文件存在，不存在则生成默认模板。

        Returns:
            True 表示文件已存在（无需生成），False 表示新生成
        """
        path = self._dynamic_root / name
        if path.exists():
            return True

        default_content = self._get_default_template(name)
        if default_content is None:
            return True  # 无默认模板，无需生成

        try:
            path.write_text(default_content, encoding="utf-8")
            from core.logging import debug_logger; debug_logger.info(f"[PromptManager] 自动生成默认模板: workspace/prompts/{name}")
            return False
        except Exception as e:
            from core.logging import debug_logger; debug_logger.warning(f"[PromptManager] 生成 {name} 失败: {e}")
            return False

    def _get_default_template(self, name: str) -> Optional[str]:
        """获取动态文件的默认模板内容"""
        templates = {
            "IDENTITY.md": """# Agent 身份定义

*定义 Agent 的身份名称、角色定位和专长领域。*

## 基本信息
- **名称**：
- **角色**：
- **专长**：

## 行为准则
-
""",
            "USER.md": """# 用户信息

*记录当前用户的基本信息和任务背景上下文。*

## 用户基本信息
- **用户名**：
- **偏好设置**：

## 当前任务背景

""",
            "DYNAMIC.md": """# 动态提示词区域

*此区域由 Agent 在每个世代开始时动态生成，用于记录当前任务、进度和关键上下文。*

---
""",
            "COMPRESS_SUMMARY.md": """# 上下文压缩摘要

*此文件在上下文压缩时自动更新，记录历史对话中的关键信息和结论摘要。*

---
""",
        }
        return templates.get(name)

    def _load_from_path(self, path: Path, name: str) -> str:
        """从指定路径加载文件"""
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8").strip()
                self._cache_sources[name] = "workspace"
                return content
            except Exception as e:
                return f"[错误: 无法读取 {path}: {e}]"
        else:
            return f"[警告: 找不到 {path}]"

    def _load_soul(self) -> str:
        """加载 SOUL.md（仅 static，只读）"""
        return self._load_static_only("SOUL.md")

    def _load_agents(self) -> str:
        """加载 AGENTS.md（仅 static，只读）"""
        return self._load_static_only("AGENTS.md")

    def _load_spec(self) -> str:
        """加载 SPEC_Agent.md（开发规范，优先级低于 AGENTS）"""
        spec_path = self._static_root.parent / "requirement" / "SPEC" / "SPEC_Agent.md"
        if spec_path.exists():
            try:
                content = spec_path.read_text(encoding="utf-8").strip()
                from core.logging import debug_logger; debug_logger.info(f"[PromptManager] 加载 SPEC from requirement/SPEC/")
                return content
            except Exception as e:
                return f"[警告: 无法读取 {spec_path}: {e}]"
        return ""

    def _load_identity(self) -> str:
        """加载 IDENTITY.md（仅 workspace）"""
        return self._load_from_path(self._dynamic_root / "IDENTITY.md", "IDENTITY.md")

    def _load_user(self) -> str:
        """加载 USER.md（仅 workspace）"""
        return self._load_from_path(self._dynamic_root / "USER.md", "USER.md")

    def _load_dynamic(self) -> str:
        """加载 DYNAMIC.md（仅 workspace）"""
        return self._load_from_path(self._dynamic_root / "DYNAMIC.md", "DYNAMIC.md")

    def _load_compress_summary(self) -> str:
        """加载 COMPRESS_SUMMARY.md（仅 workspace）"""
        return self._load_from_path(self._dynamic_root / "COMPRESS_SUMMARY.md", "COMPRESS_SUMMARY.md")

    def _load_task_checklist(self) -> str:
        """加载任务清单（基于 TaskPlanner）"""
        try:
            from core.orchestration.task_planner import get_task_planner
            planner = get_task_planner()
            return planner.get_current_checklist_markdown()
        except Exception:
            return ""

    def _load_codebase_map(self) -> str:
        """加载代码库认知地图（AST 动态扫描）"""
        try:
            from core.prompt_manager.codebase_map_builder import get_codebase_map
            return get_codebase_map()
        except Exception as e:
            return f"[警告: 加载认知地图失败: {e}]"

    def _load_tools_index(self) -> str:
        """从 tools_manual.md 提取精简索引"""
        try:
            project_root = _resolve_project_root()
            tools_manual = project_root / "docs" / "tools_manual.md"

            if not tools_manual.exists():
                return ""

            content = tools_manual.read_text(encoding="utf-8")
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

    def _load_env_info(self) -> str:
        """加载环境信息"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        project_root = _resolve_project_root()
        import platform
        os_name = {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}.get(platform.system(), platform.system())
        os_version = platform.version()
        os_arch = platform.machine()

        return "\n".join([
            "## 当前环境",
            f"- 当前时间: {current_time}",
            f"- 操作系统: {os_name} ({os_version}) [{os_arch}]",
            f"- 项目根目录: {project_root}",
            f"- 静态提示词位置: core/core_prompt/",
            f"- 动态提示词位置: workspace/prompts/",
        ])

    def _load_memory_context(self) -> str:
        """加载记忆上下文（占位，实际渲染在 _render_memory）"""
        return ""  # 由 _render_memory 处理

    def _extract_component_description(self, path: Path) -> str:
        """
        从文件头部解析组件描述。
        规则：扫描第一条 --- 分隔符之前的所有行，
        找到第一个以 *text* 或 **text** 包裹的非空段落，
        并去掉首尾星号后返回。
        """
        if not path.exists():
            return ""
        try:
            content = path.read_text(encoding="utf-8")
            header = content.split("---", 1)[0]
            import re
            for line in header.splitlines():
                stripped = line.strip()
                for pattern in [r'^\*\*(.+?)\*\*$', r'^\*(.+?)\*$']:
                    m = re.match(pattern, stripped)
                    if m:
                        return m.group(1).strip()
            return ""
        except Exception:
            return ""

    def _build_component_index(self) -> str:
        """
        生成组件索引文本，每次 build 调用时动态扫描生成。
        遍历所有 enabled 组件，自动从对应文件头部解析描述。
        """
        # 硬编码特殊组件的文件路径（无法从 name 推断的）
        CORE_PATH_MAP = {
            "SOUL":           self._static_root / "SOUL.md",
            "AGENTS":         self._static_root / "AGENTS.md",
            "SPEC":           self._static_root.parent / "requirement" / "SPEC" / "SPEC_Agent.md",
            "MEMORY":         self._dynamic_root / "COMPRESS_SUMMARY.md",
        }

        def get_description(comp) -> str:
            if comp.name in CORE_PATH_MAP and CORE_PATH_MAP[comp.name]:
                desc = self._extract_component_description(CORE_PATH_MAP[comp.name])
                if desc:
                    return desc
            # 动态组件：尝试从 workspace/prompts/{name}.md 解析
            dyn_path = self._dynamic_root / f"{comp.name}.md"
            desc = self._extract_component_description(dyn_path)
            if desc:
                return desc
            # 无文件组件 fallback
            fallbacks = {
                "TASK_CHECKLIST": "从 TaskPlanner 内存动态加载",
                "CODEBASE_MAP":   "基于 AST 扫描代码库结构",
                "TOOLS_INDEX":    "从 KeyTools 动态加载",
                "ENV_INFO":       "自动探测系统环境",
                "current_rules":  f"当前激活规则: {', '.join(self.current_active_prompts) or '无'}",
                "STATE_MEMORY":   "跨世代状态记忆，记录上一次会话的进度与结论",
                "SPEC":           "开发规范与编码约束（来自 requirement/SPEC/）",
            }
            return fallbacks.get(comp.name, comp.name)

        enabled = [c for c in self._components.values() if c.enabled]
        lines = ["\n\n---\n\n## 提示词组件索引\n"]
        for i, comp in enumerate(sorted(enabled, key=lambda c: c.priority), 1):
            desc = get_description(comp)
            marker = "（必选）" if comp.required else ""
            lines.append(f"{i}. [{comp.name}] {desc}{marker}\n")
        return "".join(lines)

    def _render_memory(
        self,
        generation: Optional[int],
        total_generations: Optional[int],
        core_context: Optional[str],
        current_goal: Optional[str],
        state_memory: Optional[str] = None,
    ) -> str:
        """渲染记忆上下文"""
        # 如果没有传入记忆，则从 memory_tools 加载
        if generation is None:
            memory_data = self._load_memory_from_tools()
            generation = memory_data.get("generation", 1)
            total_generations = memory_data.get("total_generations", 1)
            # 兼容：新旧字段名；只有未显式传入时才 fallback 到 memory 数据
            if core_context is None:
                core_context = memory_data.get("core_context") or memory_data.get("core_wisdom") or ""
            if current_goal is None:
                current_goal = memory_data.get("current_goal") or ""

        # 优先使用传入的 state_memory，回退到内存缓存
        effective_memory = state_memory if state_memory else self.state_memory

        if not core_context and not current_goal and not effective_memory:
            return ""

        lines = ["## 你的记忆与状态", f"- 当前世代: G{generation}（共{total_generations}代）"]
        if core_context:
            lines.append(f"- 核心智慧摘要: {core_context}")
        if current_goal:
            lines.append(f"- 本世代核心目标: {current_goal}")
        if effective_memory:
            lines.append(f"- 状态记忆:\n{effective_memory}")

        return "\n".join(lines)

    def _load_memory_from_tools(self) -> Dict[str, Any]:
        """从 memory_tools 加载记忆（read_memory_tool 返回 JSON 字符串，需解析）"""
        try:
            from tools.memory_tools import read_memory_tool
            import json as _json
            raw = read_memory_tool()
            # read_memory_tool 返回 JSON 字符串，需解析
            if isinstance(raw, str):
                data = _json.loads(raw)
            else:
                data = raw
            # 兼容新旧字段名
            return {
                "generation": data.get("current_generation") or data.get("generation", 1),
                "total_generations": data.get("total_generations", 1),
                "core_context": data.get("core_wisdom") or data.get("core_context", ""),
                "current_goal": data.get("current_goal", ""),
            }
        except Exception as e:
            return {
                "generation": 1,
                "total_generations": 1,
                "core_context": "",
                "current_goal": "",
                "error": str(e),
            }

    # ------------------------------------------------------------------------
    # 缓存管理
    # ------------------------------------------------------------------------

    def invalidate_cache(self, name: Optional[str] = None):
        """
        清除缓存。

        Args:
            name: 指定清除某个文件的缓存，传 None 则清除全部
        """
        if name:
            keys_to_delete = [k for k in self._cache if k.startswith(f"{name}:")]
            for k in keys_to_delete:
                del self._cache[k]
                if k in self._cache_sources:
                    del self._cache_sources[k]
            from core.logging import debug_logger; debug_logger.debug(f"[PromptManager] 清除缓存: {name}")
        else:
            self._cache.clear()
            self._cache_sources.clear()
            from core.logging import debug_logger; debug_logger.debug("[PromptManager] 清除全部缓存")

    def get_status(self) -> Dict[str, Any]:
        """获取管理器状态（调试用）"""
        return {
            "static_root": str(self._static_root),
            "dynamic_root": str(self._dynamic_root),
            "registered_components": list(self._components.keys()),
            "cached_sources": dict(self._cache_sources),
            "prompt_registry": list(self.prompt_registry.keys()),
            "current_active_prompts": list(self.current_active_prompts),
            "state_memory_length": len(self.state_memory) if self.state_memory else 0,
            "active_components_override": self._active_components_override,
        }

    def list_components(self) -> List[Dict[str, Any]]:
        """列出所有已注册的组件"""
        return [
            {
                "name": c.name,
                "priority": c.priority,
                "required": c.required,
                "enabled": c.enabled,
            }
            for c in sorted(self._components.values(), key=lambda x: x.priority)
        ]


# ============================================================================
# 全局单例
# ============================================================================

_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    """获取全局 PromptManager 单例"""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager


# ============================================================================
# 便捷函数（与旧接口兼容）
# ============================================================================

def build_system_prompt(
    generation: Optional[int] = None,
    total_generations: Optional[int] = None,
    core_context: Optional[str] = None,
    current_goal: Optional[str] = None,
) -> str:
    """构建动态系统提示词（便捷函数，兼容旧接口）"""
    return get_prompt_manager().build(
        generation=generation,
        total_generations=total_generations,
        core_context=core_context,
        current_goal=current_goal,
    )


def build_simple_system_prompt() -> str:
    """简化版系统提示词（便捷函数，兼容旧接口）"""
    return build_system_prompt(
        generation=1,
        total_generations=1,
        core_context="",
        current_goal="",
    )


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    "PromptComponent",
    "PromptManager",
    "get_prompt_manager",
    "build_system_prompt",
    "build_simple_system_prompt",
]
