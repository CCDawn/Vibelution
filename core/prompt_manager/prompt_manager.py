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

import enum
import hashlib
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import fields as dataclass_fields, is_dataclass, replace as dataclass_replace
from pathlib import Path
from typing import Optional, List, Dict, Any

from core.infrastructure.native_runtime import resolve_native_project_root
from core.prompt_manager.types import (
    SystemPrompt,
    SystemPromptSection,
    BuildContext,
    PromptBuildResult,
    as_system_prompt,
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
)
from core.prompt_manager.assembly_resolver import PromptAssemblyContext
from core.prompt_manager.section_cache import SystemPromptCache
from core.prompt_manager.sections import (
    create_default_sections,
    make_memory_section,
    make_runtime_goal_section,
    make_session_child_routing_section,
    make_spec_digest_section,
)
from core.prompt_manager.core_prompt_sources import CORE_PROMPT_NAMES
from core.prompt_manager.builder import (
    get_system_prompt,
    to_string,
    split_sys_prompt_prefix,
)


def drop_runtime_language_constraints(summary: str) -> str:
    """运行时不再把语言偏好作为强制约束跨轮回灌。"""
    text = (summary or "").replace("\r\n", "\n")
    if not text.strip():
        return ""
    lines = text.splitlines()
    filtered: List[str] = []
    skip_language_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### ") or stripped.startswith("## "):
            skip_language_block = "语言纠偏" in stripped
            if skip_language_block:
                continue
        if skip_language_block:
            continue
        if "默认回到中文" in stripped or "语言漂移" in stripped:
            continue
        filtered.append(line)
    return "\n".join(filtered).strip()


def build_state_memory_key(summary: str) -> str:
    """构建用于去噪比较的状态记忆键，忽略低价值抖动。"""
    text = drop_runtime_language_constraints(summary)
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    text = re.sub(r"已拒绝扩散：\s*\d+\s*次", "已拒绝扩散", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_restart_focus_state_memory(allowed_tool_names: tuple[str, ...]) -> str:
    """生成重启闭环轮次的短期状态记忆。"""
    allowed_tools = " / ".join(f"`{name}`" for name in allowed_tool_names)
    return (
        "### 重启闭环纪律\n"
        "- 当前轮处于重启测试模式；不要先调用 `get_git_status_summary_tool` 或 `get_recent_changes_tool`。\n"
        f"- 当前轮实际暴露给模型的工具只保留：{allowed_tools}。\n"
        "- 先使用任务与记忆工具完成闭环：`task_create_tool` / `task_update_tool` / `task_list_tool` / "
        "`get_current_goal_tool` / `get_core_context_tool`。\n"
        "- 一旦任务闭环已完成，立即调用 `trigger_self_restart_tool`，不要先扩散到通用代码感知。"
    )


def compose_state_memory(
    *,
    runtime_summary: str = "",
    carryover_state_memory: str = "",
    restart_focus_state_memory: str = "",
) -> str:
    """组合跨轮次约束与本轮即时约束。"""
    runtime = drop_runtime_language_constraints(runtime_summary)
    carryover = drop_runtime_language_constraints(carryover_state_memory)
    restart_focus = (restart_focus_state_memory or "").strip()

    parts: List[str] = []
    if runtime:
        parts.append(runtime)
    if restart_focus:
        parts.append(restart_focus)
    if carryover:
        parts.append(carryover)

    if not parts:
        return ""

    merged_lines: List[str] = []
    seen_bullets = set()
    for block in parts:
        for raw_line in block.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                if merged_lines and merged_lines[-1] != "":
                    merged_lines.append("")
                continue
            if stripped.startswith("- "):
                if stripped in seen_bullets:
                    continue
                seen_bullets.add(stripped)
            if merged_lines and merged_lines[-1] == "" and stripped.startswith("### "):
                merged_lines.pop()
            merged_lines.append(line)

    while merged_lines and merged_lines[-1] == "":
        merged_lines.pop()

    merged = "\n".join(merged_lines).strip()
    if len(merged) > 1200:
        merged = merged[:1197].rstrip() + "..."
    return merged


# ═══════════════════════════════════════════════════════════════════════════════
# 跨轮稳定段渲染缓存
# ═══════════════════════════════════════════════════════════════════════════════


_UNPROJECTABLE = object()


def _project_cache_input(value: Any, *, depth: int = 0) -> Any:
    """把缓存键输入投影为仅由原语构成的稳定嵌套元组。

    投影必须完整覆盖该输入中影响渲染产物字节的全部字段；任何投影不了
    （任意对象、超深嵌套、不可排序集合元素）的情况返回哨兵，调用方据此
    放弃缓存该段（宁可不缓存，不做错配缓存）。
    """
    if depth > 6:
        return _UNPROJECTABLE
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return _project_cache_input(value.value, depth=depth + 1)
    if is_dataclass(value):
        projected_fields: List[Any] = []
        for field in dataclass_fields(value):
            projected = _project_cache_input(
                getattr(value, field.name, None), depth=depth + 1
            )
            if projected is _UNPROJECTABLE:
                return _UNPROJECTABLE
            projected_fields.append((field.name, projected))
        return (type(value).__name__, tuple(projected_fields))
    if isinstance(value, dict):
        try:
            keys = sorted(value.keys(), key=repr)
        except Exception:
            return _UNPROJECTABLE
        projected_items: List[Any] = []
        for key in keys:
            projected = _project_cache_input(value[key], depth=depth + 1)
            if projected is _UNPROJECTABLE:
                return _UNPROJECTABLE
            projected_items.append((repr(key), projected))
        return tuple(projected_items)
    if isinstance(value, (list, tuple)):
        projected_items = tuple(
            _project_cache_input(item, depth=depth + 1) for item in value
        )
        if any(item is _UNPROJECTABLE for item in projected_items):
            return _UNPROJECTABLE
        return projected_items
    if isinstance(value, (set, frozenset)):
        try:
            ordered = sorted(value, key=repr)
        except Exception:
            return _UNPROJECTABLE
        projected_items = tuple(
            _project_cache_input(item, depth=depth + 1) for item in ordered
        )
        if any(item is _UNPROJECTABLE for item in projected_items):
            return _UNPROJECTABLE
        return projected_items
    return _UNPROJECTABLE


def _fingerprint_digest(projection: Any) -> Optional[str]:
    """把输入投影压缩为指纹摘要；投影不可靠时返回 None（表示禁用缓存）。"""
    if projection is _UNPROJECTABLE:
        return None
    payload = repr(projection).encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


def _identity_stable_for_memo(value: Any, *, depth: int = 0) -> bool:
    """判断输入对象图是否「身份稳定」：图内不含任何可变容器或可变数据类。

    只有身份稳定的图才允许进身份备忘录——frozen dataclass 字段不可重绑、
    tuple/frozenset/原语/Enum 不可变，此后同一根对象必然产出同一投影，
    身份命中即内容命中，杜绝原地变异下的 stale 摘要。含 dict/list/set 或
    非 frozen dataclass 的图一律返回 False，调用方保持全量计算路径。
    """

    if depth > 6:
        return False
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, enum.Enum):
        return True
    if is_dataclass(value):
        params = getattr(type(value), "__dataclass_params__", None)
        if params is None or not getattr(params, "frozen", False):
            return False
        return all(
            _identity_stable_for_memo(getattr(value, field.name, None), depth=depth + 1)
            for field in dataclass_fields(value)
        )
    if isinstance(value, (dict, list, set)):
        return False
    if isinstance(value, (tuple, frozenset)):
        return all(_identity_stable_for_memo(item, depth=depth + 1) for item in value)
    return False


class _SourceFingerprintMemo:
    """源对象身份备忘录：同一未变对象图重复求指纹时跳过投影+repr+sha256 整段。

    复用 ``_IdentityListMemo`` / ``_SeededHistoryFingerprintMemo`` 的身份检查
    约定，适配到单根对象图：

    - 命中=根对象 ``is`` 同一；条目强引用源对象，杜绝 id 复用碰撞；
    - 只有身份稳定（``_identity_stable_for_memo``）的图才入库，冻结图不可
      原地变异，身份命中即字节等价命中；digest 字节等价由构造保证——命中
      返回的正是此前同源全量计算的产物；
    - 对 monkeypatch 敏感：条目记录产出 digest 时的 ``_project_cache_input``
      / ``_fingerprint_digest`` 函数身份，模块属性被替换后一律 miss 重算；
    - LRU 有界；miss 永远走全量计算，只能拿重算换重算。
    """

    def __init__(self, capacity: int = 64):
        self._capacity = max(1, int(capacity))
        self._lock = threading.Lock()
        # key=id(source)；value=(source, digest, proj_fn, digest_fn)
        self._entries: "OrderedDict[int, tuple]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    def digest_for(self, source: Any) -> Optional[str]:
        """``_project_cache_input`` → ``_fingerprint_digest`` 链的免重算入口。"""

        cur_proj = globals().get("_project_cache_input")
        cur_digest = globals().get("_fingerprint_digest")
        key = id(source)
        with self._lock:
            entry = self._entries.get(key)
            if (
                entry is not None
                and entry[0] is source
                and cur_proj is not None
                and entry[2] is cur_proj
                and cur_digest is not None
                and entry[3] is cur_digest
            ):
                self._entries.move_to_end(key)
                self.hits += 1
                return entry[1]
            self.misses += 1
        projection = _project_cache_input(source)
        digest = _fingerprint_digest(projection)
        if digest is not None and _identity_stable_for_memo(source):
            with self._lock:
                self._entries[key] = (source, digest, cur_proj, cur_digest)
                self._entries.move_to_end(key)
                while len(self._entries) > self._capacity:
                    self._entries.popitem(last=False)
        return digest

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "capacity": self._capacity,
                "hits": self.hits,
                "misses": self.misses,
            }


_FINGERPRINT_MEMO_CAPACITY = 64
_FINGERPRINT_MEMO = _SourceFingerprintMemo(capacity=_FINGERPRINT_MEMO_CAPACITY)


def _source_fingerprint_digest(source: Any) -> Optional[str]:
    """带身份备忘录的源对象指纹；输出与全量计算逐字节一致。"""

    return _FINGERPRINT_MEMO.digest_for(source)


class StableSectionRenderCache:
    """跨轮稳定段渲染缓存：键=(section 名, 输入指纹)，值=渲染文本。

    - 线程安全：单锁保护 OrderedDict LRU；值是不可变 ``str``/``None``，
      命中直接返回，不需要拷贝。
    - 有界：超过容量按 LRU 淘汰最旧条目。
    - 失效语义靠键完成：任何影响输出的输入变化都会改变指纹，旧条目自然
      失效；``drop_section``/``clear`` 供显式失效路径使用。
    """

    def __init__(self, capacity: int = 64):
        self._capacity = max(1, int(capacity))
        self._lock = threading.Lock()
        self._entries: "OrderedDict[tuple, Optional[str]]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple) -> tuple[bool, Optional[str]]:
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                self.hits += 1
                return True, self._entries[key]
            self.misses += 1
            return False, None

    def put(self, key: tuple, value: Optional[str]) -> None:
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)

    def drop_section(self, name: str) -> None:
        with self._lock:
            for key in [key for key in self._entries if key[0] == name]:
                self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "capacity": self._capacity,
                "hits": self.hits,
                "misses": self.misses,
            }


# 纳入跨轮指纹缓存的动态章节白名单：compute 的全部输入都有可靠的稳定投影。
# 不收录的章节（如 CODEBASE_MAP / RUNTIME_LOG_INDEX / GIT_MEMORY /
# CONFIG_AWARENESS / ENV_INFO）读取的世界状态缺少廉价完备签名，宁可不缓存。
_STABLE_RENDER_SECTION_NAMES = frozenset(
    {"RUNTIME_GOAL", "INTENT_ALIGNMENT", "SPEC_DIGEST"}
)
_STABLE_RENDER_CACHE_CAPACITY = 64


# ═══════════════════════════════════════════════════════════════════════════════
# 路径解析
# ═══════════════════════════════════════════════════════════════════════════════


def _get_static_root() -> Path:
    return Path(__file__).parent.parent / "core_prompt"


def _get_dynamic_root() -> Path:
    project_root = resolve_native_project_root(_resolve_project_root())
    from core.infrastructure import developer_sandbox

    return developer_sandbox.route_workspace_path(
        project_root,
        "prompt_manager",
        "prompts",
        intent="state",
        seed=True,
    )


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
    _PROTECTED_FLOOR_SECTIONS = [
        "COMMON",
        "SOUL",
        "AGENTS",
        "PROTOCOL_ADAPTER",
        "RUNTIME_GOAL",
        "INTENT_ALIGNMENT",
        "USER_PROFILE",
        "SPEC_DIGEST",
        "MEMORY",
        "GIT_MEMORY",
        "RUNTIME_LOG_INDEX",
        "SESSION_CHILD_ROUTING",
        "SESSION_FILE_REFERENCES",
        "LANGUAGE_AWARENESS",
        "DELEGATION_RULES",
    ]
    _FALLBACK_DEFAULT_SECTIONS = [
        "COMMON",
        "SOUL",
        "AGENTS",
        "PROTOCOL_ADAPTER",
        "RUNTIME_GOAL",
        "USER_PROFILE",
        "SPEC_DIGEST",
        "GIT_MEMORY",
        "RUNTIME_LOG_INDEX",
        "SESSION_CHILD_ROUTING",
        "DELEGATION_RULES",
        "DELEGATION_STATE",
        "MEMORY",
        "LANGUAGE_AWARENESS",
        "CONFIG_AWARENESS",
        "ENV_INFO",
    ]
    _PREFERRED_SECTION_ORDER = [
        "COMMON",
        "SOUL",
        "AGENTS",
        "PROTOCOL_ADAPTER",
        "RUNTIME_GOAL",
        "INTENT_ALIGNMENT",
        "USER_PROFILE",
        "TASK_CHECKLIST",
        "CODEBASE_MAP",
        "GIT_MEMORY",
        "RUNTIME_LOG_INDEX",
        "DELEGATION_RULES",
        "DELEGATION_STATE",
        "CONFIG_AWARENESS",
        "LANGUAGE_AWARENESS",
        "SESSION_CHILD_ROUTING",
        "SESSION_FILE_REFERENCES",
        "GIT_RULES",
        "SPEC_DIGEST",
        "SPEC",
        "MEMORY",
        "ENV_INFO",
    ]
    _OPTIONAL_RELEVANCE_SECTIONS = {"ENV_INFO", "CONFIG_AWARENESS", "GIT_RULES", "SPEC"}
    _HEAVY_SECTIONS = {"CODEBASE_MAP", "SPEC", "ENV_INFO", "CONFIG_AWARENESS", "GIT_RULES"}
    _MODE_HINTS = {
        "orient": "全局定向",
        "delegate": "委派验收",
        "execute": "局部执行",
        "verify": "验证收口",
    }

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

        # 跨轮稳定段渲染缓存（指纹键控，见 StableSectionRenderCache）
        self._stable_render_cache = StableSectionRenderCache(
            capacity=_STABLE_RENDER_CACHE_CAPACITY
        )
        self._registry_generation = 0
        # 最近一次 build 的稳定段缓存命中明细（观测用）
        self.last_build_stable_cache: Dict[str, Any] = {
            "hit_sections": [],
            "miss_sections": [],
            "all_hit": False,
        }

        # 构建上下文（每轮 build 前更新，MEMORY 章节的 compute 从中读取）
        self._build_context = BuildContext()

        # 状态记忆（内存持有，按需落盘）
        self.state_memory: str = ""
        self._last_persisted_state_memory: str = ""

        # 当前目标（内存持有，每次动态生成，不从文件加载）
        self.current_goal: str = ""

        # 从 config.toml 读取默认章节列表
        self._default_sections = self._load_default_sections_from_config()

        from core.logging import debug as _debug_logger
        _debug_logger.info(
            f"[PromptManager] 初始化 - 静态: {self._static_root}, "
            f"workspace={'启用' if enable_workspace else '禁用'}"
        )

        # 注册默认章节（含 MEMORY，其 compute 引用 self._build_context）
        self._register_default_sections()

        if enable_workspace:
            self._load_persisted_state_memory()

        # 最近一次 build 的索引
        self._last_index: List[Dict[str, Any]] = []
        self._last_assembly_manifest: Dict[str, Any] = {}
        self._assembly_manifest_local = threading.local()
        self._protocol_adapter_fingerprint = ""

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
            build_context=self._build_context,
        )
        for s in sections:
            self._sections[s.name] = s

        self._sections["RUNTIME_GOAL"] = make_runtime_goal_section(self._build_context)
        self._sections["SESSION_CHILD_ROUTING"] = make_session_child_routing_section()
        self._sections["SPEC_DIGEST"] = make_spec_digest_section(self._build_context)
        # MEMORY 章节：compute 引用 self._build_context
        self._sections["MEMORY"] = make_memory_section(self._build_context)

        from core.logging import debug as _debug_logger
        _debug_logger.debug(
            f"[PromptManager] 注册默认章节: {list(self._sections.keys())}"
        )

    def register(self, section: SystemPromptSection):
        """注册或覆盖一个章节。"""
        self._sections[section.name] = section
        self._section_cache.invalidate(section.name)
        self._registry_generation += 1
        self._stable_render_cache.drop_section(section.name)
        from core.logging import debug as _debug_logger
        _debug_logger.debug(
            f"[PromptManager] 注册章节: {section.name} "
            f"(priority={section.priority}, cache_break={section.cache_break})"
        )

    def unregister(self, name: str):
        """取消注册一个章节。"""
        if name in self._sections:
            del self._sections[name]
            self._section_cache.invalidate(name)
            self._registry_generation += 1
            self._stable_render_cache.drop_section(name)

    def set_protocol_adapter(
        self,
        section: SystemPromptSection,
        *,
        fingerprint: str,
    ) -> None:
        """Install the resolved required T1 adapter when its route changes."""

        if (
            section.name != "PROTOCOL_ADAPTER"
            or not section.required
            or str(getattr(section.tier, "value", section.tier) or "")
            != "protocol_adapter"
        ):
            raise ValueError("invalid_protocol_adapter_section")
        normalized_fingerprint = str(fingerprint or "").strip()
        if (
            normalized_fingerprint
            and normalized_fingerprint == self._protocol_adapter_fingerprint
            and "PROTOCOL_ADAPTER" in self._sections
        ):
            return
        self.register(section)
        self._protocol_adapter_fingerprint = normalized_fingerprint

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
        frozen_core_sections: Optional[List[str]] = None,
        assembly_context: PromptAssemblyContext | None = None,
    ) -> SystemPrompt:
        """组装系统提示词。

        Args:
            include: 只包含这些章节（None 时使用默认列表或 override）。
            exclude: 排除这些章节（required=True 的无法排除）。
            core_context: 核心记忆。
            current_goal: 当前目标。
            state_memory: 状态记忆（None 时使用 self.state_memory）。
            frozen_core_sections: 已由会话静态快照完整承载的三核心章节。
                只允许 COMMON / SOUL / AGENTS，用于避免同一规则重复注入。

        Returns:
            SystemPrompt — 不可变字符串元组。
        """
        build_started = time.perf_counter()
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
        self._build_context.prompt_mode = self._infer_prompt_mode()

        # 筛选章节
        select_started = time.perf_counter()
        normalized_frozen_core_sections = {
            str(name or "").strip().upper()
            for name in list(frozen_core_sections or [])
            if str(name or "").strip().upper() in CORE_PROMPT_NAMES
        }
        selected = self._select_sections(
            include,
            exclude,
            frozen_core_sections=normalized_frozen_core_sections,
        )
        select_duration_ms = (time.perf_counter() - select_started) * 1000
        all_ordered_sections = self._order_sections(list(self._sections.values()))

        # 跨轮稳定段：对输入可完整投影的动态章节套一层指纹缓存，命中直接
        # 复用上一轮渲染字节（与全量重建逐字节相同，由回归测试钉死）。
        # outcomes 走局部列表随 build 传递，避免并发构建互相串写观测。
        stable_outcomes: List[tuple] = []
        stable_fingerprints = self._stable_section_fingerprints()
        if stable_fingerprints:
            selected = [
                self._wrap_with_stable_render(
                    section, stable_fingerprints, stable_outcomes
                )
                for section in selected
            ]

        # 组装
        render_started = time.perf_counter()
        build_result = get_system_prompt(
            selected,
            self._section_cache,
            all_sections=all_ordered_sections,
            assembly_context=assembly_context,
        )
        sp = build_result.prompt
        self._last_assembly_manifest = build_result.assembly_manifest.to_public_dict()
        self._assembly_manifest_local.value = self._last_assembly_manifest
        render_duration_ms = (time.perf_counter() - render_started) * 1000
        self._finalize_stable_cache_stats(stable_outcomes)

        # 记录索引（复用本次真实构建结果，避免二次 compute）
        self._last_index = [
            {
                "name": result.name,
                "length": len(result.content or ""),
                "cache_break": result.cache_break,
                "cache_prefix": result.cache_prefix,
                "required": result.required,
                "is_empty": result.is_empty,
                "source": result.source or "",
                "duration_ms": round(float(result.duration_ms or 0.0), 3),
            }
            for result in build_result.section_results
        ]
        string_started = time.perf_counter()
        prompt_text = to_string(sp)
        string_duration_ms = (time.perf_counter() - string_started) * 1000
        self._last_build_summary = self._build_summary(
            selected=selected,
            all_sections=all_ordered_sections,
            build_result=build_result,
        )
        self._last_build_summary.update(
            {
                "select_duration_ms": select_duration_ms,
                "render_duration_ms": render_duration_ms,
                "tuple_join_duration_ms": build_result.join_duration_ms,
                "string_join_duration_ms": string_duration_ms,
                "total_duration_ms": (time.perf_counter() - build_started) * 1000,
                "slow_sections": self._slow_section_timings(build_result),
                "stable_render_cache": dict(self.last_build_stable_cache),
            }
        )

        from core.logging import debug as _debug_logger
        _debug_logger.info(
            f"[PromptManager] 构建完成 (sections={len(selected)}, "
            f"len={len(prompt_text)}, "
            f"cache={self._section_cache.stats})"
        )
        self._log_build_summary()
        return sp

    @staticmethod
    def _slow_section_timings(build_result: PromptBuildResult) -> List[Dict[str, Any]]:
        timings = []
        for result in build_result.section_results:
            duration_ms = float(result.duration_ms or 0.0)
            if duration_ms < 5.0:
                continue
            timings.append(
                {
                    "name": result.name,
                    "duration_ms": round(duration_ms, 3),
                    "source": result.source or "",
                    "length": len(result.content or ""),
                }
            )
        timings.sort(key=lambda item: float(item["duration_ms"]), reverse=True)
        return timings[:8]

    # ------------------------------------------------------------------------
    # 跨轮稳定段指纹缓存
    # ------------------------------------------------------------------------

    def _stable_section_fingerprints(self) -> Dict[str, tuple]:
        """为本轮可缓存章节计算输入指纹；拿不到可靠投影的章节直接缺席。

        键覆盖该章节渲染产物的全部输入：
        - RUNTIME_GOAL: 章节注册代数 + runtime_goal_packet 全字段投影
          （render() 是字段纯函数，已核）；
        - INTENT_ALIGNMENT: 注册代数 + intent_alignment_packet 投影
          （dict / dataclass 均按内容投影）；
        - SPEC_DIGEST: 注册代数 + prompt_mode + packet.max_calls_per_turn。
          仅当 packet 带正数预算时才缓存——否则 compute 会走授权层解析链，
          其状态没有廉价完备签名，宁可不缓存。
        """
        fingerprints: Dict[str, tuple] = {}
        generation = self._registry_generation
        ctx = self._build_context

        goal_digest = _source_fingerprint_digest(ctx.runtime_goal_packet)
        if goal_digest is not None:
            fingerprints["RUNTIME_GOAL"] = ("v1", generation, goal_digest)

        intent_digest = _source_fingerprint_digest(ctx.intent_alignment_packet)
        if intent_digest is not None:
            fingerprints["INTENT_ALIGNMENT"] = ("v1", generation, intent_digest)

        packet = ctx.runtime_goal_packet
        packet_max_calls = getattr(packet, "max_calls_per_turn", 0) if packet is not None else 0
        try:
            packet_max_calls = int(packet_max_calls or 0)
        except (TypeError, ValueError):
            packet_max_calls = 0
        if packet is not None and packet_max_calls > 0:
            fingerprints["SPEC_DIGEST"] = (
                "v1",
                generation,
                str(ctx.prompt_mode or ""),
                packet_max_calls,
            )
        return fingerprints

    def _wrap_with_stable_render(
        self,
        section: SystemPromptSection,
        fingerprints: Dict[str, tuple],
        outcomes: List[tuple],
    ) -> SystemPromptSection:
        """给可缓存章节的 compute 套指纹缓存；不在白名单或缺指纹则原样返回。"""
        fingerprint = fingerprints.get(section.name)
        if fingerprint is None or section.name not in _STABLE_RENDER_SECTION_NAMES:
            return section
        cache = self._stable_render_cache
        cache_key = (section.name, fingerprint)

        def compute() -> Optional[str]:
            hit, cached_content = cache.get(cache_key)
            if hit:
                outcomes.append((section.name, True))
                return cached_content
            content = section.compute()
            cache.put(cache_key, content)
            outcomes.append((section.name, False))
            return content

        return dataclass_replace(section, compute=compute)

    def _finalize_stable_cache_stats(self, outcomes: List[tuple]) -> None:
        hit_names: List[str] = []
        miss_names: List[str] = []
        for name, hit in outcomes:
            if hit:
                if name not in hit_names:
                    hit_names.append(name)
            elif name not in miss_names:
                miss_names.append(name)
        self.last_build_stable_cache = {
            "hit_sections": hit_names,
            "miss_sections": miss_names,
            # 热轮第二轮起（输入未变）应为 True：可缓存段全部命中。
            "all_hit": bool(hit_names) and not miss_names,
        }

    def _select_sections(
        self,
        include: Optional[List[str]],
        exclude: Optional[List[str]],
        *,
        frozen_core_sections: set[str] | None = None,
    ) -> List[SystemPromptSection]:
        """根据 include/exclude 规则选择章节。

        优先级：
        1. include 非空 → 直接使用（参数优先）
        2. 使用 _default_sections
        """
        if include is not None:
            effective_include = include
        else:
            effective_include = self._default_sections

        all_sections = list(self._sections.values())

        if effective_include != ["*"]:
            names = set(effective_include)
            all_sections = [s for s in all_sections if s.name in names]

        frozen = set(frozen_core_sections or set())
        if exclude is not None:
            excluded = set(exclude)
            all_sections = [
                s for s in all_sections
                if s.name not in excluded or (s.required and s.name not in frozen)
            ]

        all_sections = self._apply_protected_floor(
            all_sections,
            exclude=exclude,
            frozen_core_sections=frozen,
        )
        ordered = self._order_sections(all_sections)
        return self._prune_optional_sections(
            ordered,
            include=include,
        )

    def _apply_protected_floor(
        self,
        sections: List[SystemPromptSection],
        exclude: Optional[List[str]],
        frozen_core_sections: set[str] | None = None,
    ) -> List[SystemPromptSection]:
        floor_excluded = set(exclude or [])
        frozen = set(frozen_core_sections or set())
        section_map = {s.name: s for s in sections}
        for name in self._PROTECTED_FLOOR_SECTIONS:
            registered = self._sections.get(name)
            required_and_live = bool(registered and registered.required and name not in frozen)
            if name in floor_excluded and not required_and_live:
                continue
            if name not in section_map and registered is not None:
                section_map[name] = registered
        return list(section_map.values())

    def _order_sections(self, sections: List[SystemPromptSection]) -> List[SystemPromptSection]:
        order_map = {name: idx for idx, name in enumerate(self._PREFERRED_SECTION_ORDER)}
        return sorted(
            sections,
            key=lambda s: (order_map.get(s.name, len(order_map)), s.priority, s.name),
        )

    def _prune_optional_sections(
        self,
        sections: List[SystemPromptSection],
        include: Optional[List[str]],
    ) -> List[SystemPromptSection]:
        """按当前任务相关性裁剪高噪声可选 section。

        能力边界（code_context / git 工作流等）不在这里裁决：章节通过
        ``capability_requirements`` 声明依赖，由 Prompt Assembly resolver
        按运行时能力统一裁定（见 assembly_resolver）。
        """
        explicit_names = set(include or [])
        pruned: List[SystemPromptSection] = []
        for section in sections:
            if section.name not in (self._OPTIONAL_RELEVANCE_SECTIONS | {"CODEBASE_MAP"}):
                pruned.append(section)
                continue
            if section.name in explicit_names:
                pruned.append(section)
                continue
            if section.name != "CODEBASE_MAP" and (not section.cache_break or section.cache_prefix):
                pruned.append(section)
                continue
            if self._is_optional_section_relevant(section.name):
                pruned.append(section)
        return pruned

    def _is_optional_section_relevant(self, section_name: str) -> bool:
        goal = (self._build_context.current_goal or "").lower()
        core_context = (self._build_context.core_context or "").lower()
        state_memory = (self._build_context.state_memory or "").lower()
        prompt_mode = (self._build_context.prompt_mode or "orient").lower()
        full_context = "\n".join(part for part in [goal, core_context, state_memory] if part)
        focused_context = "\n".join(part for part in [goal, core_context] if part)

        if section_name == "CODEBASE_MAP":
            if self._is_readonly_log_diagnosis(prompt_mode, goal, core_context):
                try:
                    from core.infrastructure.agent_session import get_session_state
                    snapshot = get_session_state().get_attention_snapshot()
                    modified_paths = snapshot.get("modified_paths") or []
                    if len(modified_paths) >= 3:
                        return True
                except Exception:
                    return False
                return False
            map_keywords = (
                "架构", "全局", "整体", "全貌", "目录", "模块", "调用链", "链路", "结构",
                "入口", "影响面", "地图", "map", "codebase", "slim", "refactor", "重构",
                "orchestration", "prompt", "section", "拼接",
            )
            if any(keyword in full_context for keyword in map_keywords):
                return True
            try:
                from core.infrastructure.agent_session import get_session_state
                snapshot = get_session_state().get_attention_snapshot()
                modified_paths = snapshot.get("modified_paths") or []
                if len(modified_paths) >= 3:
                    return True
                if snapshot.get("active_delegation"):
                    return True
            except Exception:
                return False
            return False

        if section_name == "ENV_INFO":
            env_keywords = (
                "环境", "os", "系统", "python 版本", "解释器", "venv",
                "编码", "端口", "localhost", "环境变量", "依赖",
            )
            return self._context_has_keywords(focused_context, env_keywords)

        if section_name == "CONFIG_AWARENESS":
            config_keywords = (
                "config",
                "config.toml",
                "配置",
                "配置项",
                "provider 配置",
                "model config",
                "model library",
                "模型配置",
                "模型库",
                "api key",
                "api_key",
                "profile 配置",
                "runtime profile",
                "llm.local",
                "本地模型",
            )
            focused_hit = self._context_has_keywords(focused_context, config_keywords)
            if focused_hit:
                return True
            try:
                from config import get_config
                diagnosis = get_config().diagnose_config()
                warnings = diagnosis.get("warnings") or []
                blocking_issues = diagnosis.get("blocking_issues") or []
                filtered_blockers = [
                    issue for issue in blocking_issues
                    if "缺少可用 API Key" not in str(issue)
                ]
                # 配置告警只在定向配置问题时展开；验证模式仅允许真实阻断问题打断降噪。
                if prompt_mode == "verify":
                    return bool(filtered_blockers)
                return False
            except Exception:
                return False

        if section_name == "GIT_RULES":
            if self._is_readonly_log_diagnosis(prompt_mode, goal, core_context):
                try:
                    from core.infrastructure.agent_session import get_session_state
                    snapshot = get_session_state().get_attention_snapshot()
                    modified_paths = snapshot.get("modified_paths") or []
                    if modified_paths or snapshot.get("active_evolution_txn_id") or snapshot.get("dirty_since"):
                        return True
                except Exception:
                    return False
                return False
            git_keywords = ("git", "commit", "提交", "回滚", "diff", "worktree", "事务", "transaction", "重启")
            if self._context_has_keywords(focused_context, git_keywords):
                return True
            try:
                from core.infrastructure.agent_session import get_session_state
                snapshot = get_session_state().get_attention_snapshot()
                modified_paths = snapshot.get("modified_paths") or []
                return bool(
                    modified_paths
                    or snapshot.get("active_evolution_txn_id")
                    or snapshot.get("dirty_since")
                )
            except Exception:
                return False

        return True

    def _optional_section_reason(self, section_name: str) -> Optional[str]:
        goal = (self._build_context.current_goal or "").lower()
        core_context = (self._build_context.core_context or "").lower()
        prompt_mode = (self._build_context.prompt_mode or "orient").lower()

        if self._is_readonly_log_diagnosis(prompt_mode, goal, core_context):
            if section_name in {"GIT_RULES", "SPEC", "CODEBASE_MAP"}:
                return None

        if section_name == "ENV_INFO":
            keywords = (
                "环境", "os", "系统", "python 版本", "解释器", "venv",
                "编码", "端口", "localhost", "环境变量", "依赖",
            )
            for source_name, text in (("goal", goal), ("core", core_context)):
                matched = self._matching_keywords(text, keywords)
                if matched:
                    return f"{source_name}:{'/'.join(matched[:2])}"
            return None

        if section_name == "CONFIG_AWARENESS":
            keywords = (
                "config",
                "config.toml",
                "配置",
                "配置项",
                "provider 配置",
                "model config",
                "model library",
                "模型配置",
                "模型库",
                "api key",
                "api_key",
                "profile 配置",
                "runtime profile",
                "llm.local",
                "本地模型",
            )
            for source_name, text in (("goal", goal), ("core", core_context)):
                matched = self._matching_keywords(text, keywords)
                if matched:
                    return f"{source_name}:{'/'.join(matched[:2])}"
            if prompt_mode == "verify":
                try:
                    from config import get_config
                    diagnosis = get_config().diagnose_config()
                    blockers = [
                        issue for issue in (diagnosis.get("blocking_issues") or [])
                        if "缺少可用 API Key" not in str(issue)
                    ]
                    if blockers:
                        return "verify:blocker"
                except Exception:
                    return None
            return None

        if section_name in {"GIT_RULES", "SPEC", "CODEBASE_MAP"}:
            if section_name == "SPEC" and prompt_mode == "orient":
                return "orient:discipline"
            return "runtime:relevance"

        return None

    @staticmethod
    def _is_readonly_log_diagnosis(prompt_mode: str, goal: str, core_context: str) -> bool:
        text = "\n".join(part for part in [goal or "", core_context or ""] if part).lower()
        if "log_info" not in text and "logs/conversations" not in text:
            return False
        if "conversation_" not in text and "debug_" not in text:
            return False
        readonly_markers = (
            "只做诊断",
            "只做分析",
            "只读",
            "不要修改代码",
            "不要改代码",
            "不修改代码",
            "read-only",
            "do not modify code",
        )
        negated_mutation_markers = (
            "不要修改代码",
            "不要改代码",
            "不修改代码",
            "do not modify code",
        )
        mutate_markers = (
            "修改代码",
            "修复代码",
            "落地修复",
            "实现修复",
            "apply patch",
            "提交",
            "commit",
        )
        has_readonly = any(marker in text for marker in readonly_markers)
        mutation_text = text
        for marker in negated_mutation_markers:
            mutation_text = mutation_text.replace(marker, "")
        has_mutation = any(marker in mutation_text for marker in mutate_markers)
        return has_readonly and not has_mutation

    @staticmethod
    def _matching_keywords(text: str, keywords: tuple[str, ...]) -> List[str]:
        matched: List[str] = []
        lowered = (text or "").lower()
        for keyword in keywords:
            candidate = keyword.lower()
            if re.fullmatch(r"[a-z0-9_ .:+/-]+", candidate):
                pattern = rf"(?<![a-z0-9_]){re.escape(candidate)}(?![a-z0-9_])"
                if re.search(pattern, lowered):
                    matched.append(keyword)
            elif candidate in lowered:
                matched.append(keyword)
        return matched

    @classmethod
    def _context_has_keywords(cls, text: str, keywords: tuple[str, ...]) -> bool:
        return bool(cls._matching_keywords(text, keywords))

    def _infer_prompt_mode(self) -> str:
        """基于当前会话状态推断本轮提示词工作模式。"""
        try:
            from core.infrastructure.agent_session import get_session_state
            snapshot = get_session_state().get_attention_snapshot()
        except Exception:
            snapshot = {}

        if snapshot.get("active_delegation"):
            return "delegate"

        if snapshot.get("last_validation_summary"):
            return "verify"

        if (
            snapshot.get("active_evolution_txn_id")
            or (snapshot.get("modified_paths") or [])
        ):
            return "execute"

        return "orient"

    def _build_summary(
        self,
        *,
        selected: List[SystemPromptSection],
        all_sections: List[SystemPromptSection],
        build_result: PromptBuildResult,
    ) -> Dict[str, Any]:
        selected_names = [section.name for section in selected]
        rendered_names = [result.name for result in build_result.section_results if not result.is_empty]
        omitted_names = [section.name for section in all_sections if section.name not in selected_names]
        omitted_heavy = [name for name in omitted_names if name in self._HEAVY_SECTIONS]
        dynamic_names = [result.name for result in build_result.section_results if result.cache_break and not result.is_empty]
        cache_prefix_names = [result.name for result in build_result.section_results if result.cache_prefix and not result.is_empty]
        inclusion_reasons = {
            name: reason
            for name in rendered_names
            if name in self._OPTIONAL_RELEVANCE_SECTIONS or name == "CODEBASE_MAP"
            for reason in [self._optional_section_reason(name)]
            if reason
        }
        manifest = build_result.assembly_manifest.to_public_dict()
        decision_counts: Dict[str, int] = {}
        for segment in list(manifest.get("segments") or []):
            if not isinstance(segment, dict):
                continue
            decision = str(segment.get("decision") or "unknown")
            decision_counts[decision] = decision_counts.get(decision, 0) + 1
        return {
            "prompt_mode": self._build_context.prompt_mode,
            "selected_sections": selected_names,
            "rendered_sections": rendered_names,
            "omitted_sections": omitted_names,
            "omitted_heavy_sections": omitted_heavy,
            "dynamic_sections": dynamic_names,
            "cache_prefix_sections": cache_prefix_names,
            "optional_inclusion_reasons": inclusion_reasons,
            "content_length": len(to_string(build_result.prompt)),
            "prompt_assembly": {
                "schemaVersion": manifest.get("schemaVersion"),
                "assemblyMode": manifest.get("assemblyMode"),
                "stablePrefixHash": manifest.get("stablePrefixHash"),
                "sessionSnapshotHash": manifest.get("sessionSnapshotHash"),
                "totalEstimatedTokens": manifest.get("totalEstimatedTokens"),
                "budgetTokens": manifest.get("budgetTokens"),
                "decisionCounts": decision_counts,
            },
        }

    def _log_build_summary(self):
        summary = getattr(self, "_last_build_summary", None) or {}
        if not summary:
            return
        message = (
            f"mode={summary.get('prompt_mode', 'unknown')} "
            f"len={summary.get('content_length', 0)} "
            f"rendered={','.join(summary.get('rendered_sections', [])) or '-'} "
            f"omitted_heavy={','.join(summary.get('omitted_heavy_sections', [])) or '-'}"
        )
        message += (
            f" timings_ms=select:{float(summary.get('select_duration_ms') or 0.0):.1f},"
            f"render:{float(summary.get('render_duration_ms') or 0.0):.1f},"
            f"tuple:{float(summary.get('tuple_join_duration_ms') or 0.0):.1f},"
            f"string:{float(summary.get('string_join_duration_ms') or 0.0):.1f},"
            f"total:{float(summary.get('total_duration_ms') or 0.0):.1f}"
        )
        slow_sections = summary.get("slow_sections") or []
        if slow_sections:
            slow_text = ",".join(
                f"{item.get('name')}:{float(item.get('duration_ms') or 0.0):.1f}/{item.get('source') or '-'}"
                for item in slow_sections[:5]
                if isinstance(item, dict)
            )
            if slow_text:
                message += f" slow={slow_text}"
        stable_cache = summary.get("stable_render_cache") or {}
        if stable_cache:
            message += (
                f" stableCache={'hit' if stable_cache.get('all_hit') else 'miss'}"
                f" hits={','.join(stable_cache.get('hit_sections') or []) or '-'}"
                f" misses={','.join(stable_cache.get('miss_sections') or []) or '-'}"
            )
        inclusion_reasons = summary.get("optional_inclusion_reasons") or {}
        if inclusion_reasons:
            reason_text = ",".join(f"{name}:{reason}" for name, reason in inclusion_reasons.items())
            message += f" reasons={reason_text}"
        assembly = summary.get("prompt_assembly") or {}
        if assembly:
            decisions = assembly.get("decisionCounts") or {}
            decision_text = ",".join(
                f"{key}:{decisions[key]}"
                for key in sorted(decisions)
            )
            message += (
                f" assembly={assembly.get('assemblyMode') or '-'}"
                f" tokens={int(assembly.get('totalEstimatedTokens') or 0)}"
                f"/{int(assembly.get('budgetTokens') or 0)}"
                f" decisions={decision_text or '-'}"
            )
        try:
            from core.logging.unified_logger import logger as unified_logger
            unified_logger.log_debug("prompt_build", message, level="INFO")
        except Exception:
            pass
        try:
            from core.logging import debug as _debug_logger
            _debug_logger.info(f"[prompt_build] {message}")
        except Exception:
            pass
        if assembly.get("assemblyMode") != "legacy_observe":
            try:
                from core.web.services.runtime_scene_service import record_runtime_scene_event

                record_runtime_scene_event(
                    "agent_runtime",
                    "prompt_manager",
                    "prompt_build.resolved",
                    message="prompt_build.resolved",
                    outcome="resolved",
                    fields={
                        "promptMode": summary.get("prompt_mode"),
                        "assemblyMode": assembly.get("assemblyMode"),
                        "stablePrefixHash": assembly.get("stablePrefixHash"),
                        "sessionSnapshotHash": assembly.get("sessionSnapshotHash"),
                        "totalEstimatedTokens": int(
                            assembly.get("totalEstimatedTokens") or 0
                        ),
                        "budgetTokens": int(assembly.get("budgetTokens") or 0),
                        "decisionCounts": dict(assembly.get("decisionCounts") or {}),
                        "stableCacheHit": bool(
                            (summary.get("stable_render_cache") or {}).get("all_hit")
                        ),
                    },
                    lifecycle=True,
                )
            except Exception:
                pass

    # ------------------------------------------------------------------------
    # 运行目标包
    # ------------------------------------------------------------------------

    def set_runtime_goal_packet(self, packet: Any) -> None:
        """设置统一 agent 本轮目标包，供 RUNTIME_GOAL 动态章节渲染。"""

        self._build_context.runtime_goal_packet = packet
        self._section_cache.invalidate("RUNTIME_GOAL")

    def get_runtime_goal_packet(self) -> Any:
        return self._build_context.runtime_goal_packet

    def set_intent_alignment_packet(self, packet: Any) -> None:
        """设置意图对齐 packet，供 INTENT_ALIGNMENT 动态章节渲染。"""

        self._build_context.intent_alignment_packet = packet
        self._section_cache.invalidate("INTENT_ALIGNMENT")

    def get_intent_alignment_packet(self) -> Any:
        return self._build_context.intent_alignment_packet

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

        normalized_goal = goal.strip()
        if normalized_goal == (self.current_goal or "").strip():
            return

        self.current_goal = normalized_goal
        self._section_cache.invalidate("MEMORY")
        from core.logging import debug as _debug_logger
        _debug_logger.debug(
            f"[PromptManager] current_goal 更新: {normalized_goal[:80]}"
        )

    def get_current_goal(self) -> str:
        """获取当前目标（内存值）。"""
        return self.current_goal

    def update_state_memory(self, memory_text: str, persist: bool = True):
        """更新状态记忆（内存即时更新，按需落盘），触发缓存失效。"""
        if not memory_text or not memory_text.strip():
            return
        normalized = memory_text.strip()
        current = (self.state_memory or "").strip()
        changed = normalized != current

        if changed:
            self.state_memory = normalized
            self._section_cache.invalidate("MEMORY")
            from core.logging import debug as _debug_logger
            _debug_logger.debug(
                f"[PromptManager] state_memory 更新，长度={len(normalized)}"
            )

        if persist and self._last_persisted_state_memory != normalized:
            self._persist_state_memory(normalized)
            self._last_persisted_state_memory = normalized

    def clear_state_memory(self, persist: bool = True):
        """清空短期状态记忆（内存即时清空，按需落盘），触发缓存失效。"""
        if not self.state_memory:
            if persist and self._last_persisted_state_memory:
                try:
                    state_memory_path = self._dynamic_root / "STATE_MEMORY.md"
                    state_memory_path.write_text("", encoding="utf-8")
                except Exception:
                    pass
                self._last_persisted_state_memory = ""
            return
        self.state_memory = ""
        self._section_cache.invalidate("MEMORY")
        if persist:
            try:
                state_memory_path = self._dynamic_root / "STATE_MEMORY.md"
                state_memory_path.write_text("", encoding="utf-8")
            except Exception:
                pass
            self._last_persisted_state_memory = ""

    def _persist_state_memory(self, memory_text: str):
        try:
            state_memory_path = self._dynamic_root / "STATE_MEMORY.md"
            state_memory_path.write_text(memory_text, encoding="utf-8")
            from core.logging import debug as _debug_logger
            _debug_logger.info(f"[PromptManager] state_memory 已落盘: {state_memory_path}")
        except Exception as e:
            from core.logging import debug as _debug_logger
            _debug_logger.warning(f"[PromptManager] state_memory 落盘失败: {e}")

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
                    self._last_persisted_state_memory = content
                    from core.logging import debug as _debug_logger
                    _debug_logger.info(
                        f"[PromptManager] 从会话恢复 state_memory，长度={len(content)}"
                    )
        except Exception as e:
            from core.logging import debug as _debug_logger
            _debug_logger.warning(f"[PromptManager] 恢复 state_memory 失败: {e}")

    # ------------------------------------------------------------------------
    # 默认配置
    # ------------------------------------------------------------------------

    def _load_default_sections_from_config(self) -> List[str]:
        try:
            from config import get_config
            components = get_config().prompt.default_components
            if components:
                from core.logging import debug as _debug_logger
                _debug_logger.info(f"[PromptManager] 从 config 加载默认章节: {components}")
                return components
        except Exception:
            pass
        return list(self._FALLBACK_DEFAULT_SECTIONS)

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
            from core.logging import debug as _debug_logger
            _debug_logger.info(f"[PromptManager] 自动生成默认模板: workspace/prompts/{name}")
            return False
        except Exception as e:
            from core.logging import debug as _debug_logger
            _debug_logger.warning(f"[PromptManager] 生成 {name} 失败: {e}")
            return False

    def _get_default_template(self, name: str) -> Optional[str]:
        # 这些模板头部只用于文件自描述；运行时 section 元信息仍以 config/registry 为准。
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
                "description: 外部宿主环境与交互偏好，由 Agent 运行时自行维护\n---\n"
            ),
        }
        return templates.get(name)

    # ------------------------------------------------------------------------
    # 缓存管理
    # ------------------------------------------------------------------------

    def invalidate_cache(self, name: Optional[str] = None):
        """清除章节缓存。name 为 None 则清除全部。"""
        self._section_cache.invalidate(name)
        if name:
            self._stable_render_cache.drop_section(name)
        else:
            self._stable_render_cache.clear()
        from core.logging import debug as _debug_logger
        _debug_logger.debug(
            f"[PromptManager] 清除缓存: {name or '全部'}"
        )

    def get_cache_stats(self) -> Dict[str, Any]:
        return self._section_cache.stats

    def _render_subagent_language_awareness(self) -> str:
        """复用主 agent 的语言习惯提示词，避免子 agent 语言规则漂移。"""
        section = self._sections.get("LANGUAGE_AWARENESS")
        if section is None:
            return ""
        try:
            return (section.compute() or "").strip()
        except Exception:
            return ""

    def build_subagent_prompt(
        self,
        *,
        task_type: str,
        goal: str,
        scope: Any = None,
        constraints: Optional[Dict[str, Any]] = None,
        deliverables: Optional[List[str]] = None,
        context_pack: Optional[str] = None,
    ) -> str:
        """构建子 agent 的瘦提示词。"""
        from core.orchestration.subagent_roles import get_subagent_role_spec

        constraints = dict(constraints or {})
        deliverables = list(deliverables or [])

        scope_lines: List[str] = []
        if isinstance(scope, dict):
            for key in sorted(scope.keys()):
                value = scope.get(key)
                if value in (None, "", [], {}):
                    continue
                scope_lines.append(f"- {key}: {value}")
        elif isinstance(scope, (list, tuple, set)):
            for item in scope:
                text = str(item).strip()
                if text:
                    scope_lines.append(f"- {text}")
        elif scope:
            scope_lines.append(f"- {scope}")

        deliverable_lines = deliverables or [
            "status",
            "summary",
            "findings",
            "evidence",
            "recommended_next_action",
            "confidence",
        ]
        example_lines: List[str] = []
        for name in deliverable_lines:
            if name in {"findings", "evidence"}:
                example_lines.append(f'  "{name}": [""]')
            else:
                example_lines.append(f'  "{name}": ""')

        max_steps = constraints.get("max_steps", 6)
        max_output_chars = constraints.get("max_output_chars", 4000)
        stop_rule = constraints.get(
            "stop_rule",
            "证据已足够时立即停止；若证据不足，明确返回缺口，不扩散任务。",
        )
        role_spec = get_subagent_role_spec(task_type or "inspect")
        language_awareness = self._render_subagent_language_awareness()

        parts = [
            "## 子 Agent 基座",
            "- 你是只读专项分析子 agent。",
            "- 你只允许以 `diagnose` / `inspect` / `summarize` 三种固定模式工作。",
            f"- 你的当前系统角色: {role_spec.role_name}。",
            f"- 你的存在目的: {role_spec.system_purpose}",
            "- 你不做最终裁决。",
            "- 你不写文件、不改 prompt、不改 memory、不做 git 操作。",
            "- 你绝不能继续派发新的 agent；证据不足时直接返回缺口，由主 agent 接管。",
            "- 你只在给定 scope 内行动，不扩散任务。",
            "- 只读模式下不要尝试 `cli_tool`、shell、`git diff`、`pytest`、`head` 等命令链路。",
            "- 优先使用当前 ToolPolicy 已授权的结构化只读入口：日志、上下文、搜索、代码图谱或局部读取能力。",
            "- 禁止跳读：若读取结果提示仍有剩余内容，不要默认按 offset 顺序续读；先判断当前目标缺少文本命中、结构信息还是实体上下文，再选择已授权的搜索、代码图谱或局部读取入口。",
            "- 你负责的工作:",
            f"  - {role_spec.owned_work[0]}",
            f"  - {role_spec.owned_work[1]}",
            "- 你不负责的工作:",
            f"  - {role_spec.forbidden_work[0]}",
            f"  - {role_spec.forbidden_work[1]}",
            "",
        ]
        if language_awareness:
            parts.extend([language_awareness, ""])
        parts.extend([
            "## 主 Agent 任务指令",
            f"- 当前唯一目标: {(goal or '').strip()}",
            f"- 当前任务类型: {(task_type or 'inspect').strip()}",
            f"- 最大步数: {max_steps}",
            f"- 最大输出长度: {max_output_chars} 字符",
            "- 停止条件:",
            f"  - {stop_rule}",
        ])
        if scope_lines:
            parts.append("- 当前 scope:")
            parts.extend(f"  {line}" for line in scope_lines)
        if context_pack:
            parts.extend(["", "## 最小上下文", context_pack.strip()])
        parts.extend([
            "",
            "## 输出要求",
            "- 只返回一个 JSON 对象，不要附加解释性前后文。",
            "- 若证据不足，仍返回结构化 JSON，并在 findings/evidence 中说明缺口。",
            f"- 输出形态: {role_spec.return_shape}",
            "- JSON 模板:",
            "{",
            ",\n".join(example_lines),
            "}",
        ])
        return "\n".join(parts).strip()

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
            "prompt_mode": self._build_context.prompt_mode,
            "prompt_mode_label": self._MODE_HINTS.get(self._build_context.prompt_mode, self._build_context.prompt_mode),
            "section_cache": self._section_cache.stats,
            "last_index": self._last_index,
            "last_assembly_manifest": dict(self._last_assembly_manifest),
            "last_build_summary": getattr(self, "_last_build_summary", {}),
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

    def get_last_assembly_manifest(self) -> Dict[str, Any]:
        """Return the latest sanitized Prompt Assembly manifest."""

        thread_manifest = getattr(self._assembly_manifest_local, "value", None)
        if isinstance(thread_manifest, dict):
            return dict(thread_manifest)
        return dict(self._last_assembly_manifest)


# ═══════════════════════════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════════════════════════

_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager
