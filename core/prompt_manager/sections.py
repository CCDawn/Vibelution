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
from vibelution_storage import resolve_project_workspace_home

from core.prompt_manager.core_prompt_sources import (
    CORE_PROMPT_NAMES,
    CORE_PROMPT_SPECS,
    core_prompt_path,
    load_core_prompt_bundle,
    strip_prompt_front_matter,
)
from core.prompt_manager.types import SystemPromptSection, BuildContext


def _strip_front_matter(content: str) -> str:
    """移除 Markdown front matter。

    注意：
    - section 的运行时元信息（name/priority/required/description）只来自
      config/registry；
    - 文件头 front matter 仅视为可选文件注释，不参与 section 注册决策。
    """
    return strip_prompt_front_matter(content)


def _build_git_rules_summary(content: str) -> Optional[str]:
    """从 Git 工作流文档提取精简运行时摘要。"""
    body = _strip_front_matter(content)
    if not body:
        return None

    section_map = {
        "## 提交模板": "模板",
        "## 拆提交规则": "拆分",
        "## 高风险改动": "高风险",
        "## 反模式": "反模式",
    }
    wanted = list(section_map.keys())
    current: Optional[str] = None
    buckets: Dict[str, List[str]] = {key: [] for key in wanted}

    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped in section_map:
            current = stripped
            continue
        if stripped.startswith("## "):
            current = None
            continue
        if not current or not stripped:
            continue
        if stripped.startswith(("- ", "* ", "`")) and len(buckets[current]) < 4:
            buckets[current].append(stripped)

    lines = ["## Git 提交规则"]
    for heading in wanted:
        items = buckets.get(heading) or []
        if items:
            lines.append(f"- {section_map[heading]}:")
            for item in items:
                prefix = item[2:] if item.startswith(("- ", "* ")) else item
                lines.append(f"  - {prefix}")

    return "\n".join(lines) if len(lines) > 1 else None


_DEFAULT_GIT_WORKFLOW = """
## 提交模板

- 使用清晰的 Conventional Commit 前缀，例如 `fix:`, `feat:`, `refactor:`, `test:`, `docs:`。
- 第一行说明行为变化和原因，不写泛泛的“update files”。
- 正文只在必要时补充验证、风险或迁移说明。

## 拆提交规则

- 每个提交只覆盖一个明确目标。
- 不把无关重构、格式化和运行产物夹进同一提交。
- 暂存前先检查当前脏区，只 stage 本轮任务文件。

## 高风险改动

- 修改配置、提示词、运行时状态、Git 操作或持久化逻辑时，提交前必须说明验证证据。
- 涉及密钥、权限、回滚或覆盖远端历史时，先确认身份和风险边界。

## 反模式

- 禁止 `git add .` 式夹带提交。
- 禁止提交真实密钥、本地运行产物、缓存、日志和临时文件。
- 禁止在未验证的情况下把修复声明为完成。
""".strip()


def _looks_like_vibelution_project_root(project_root: Path) -> bool:
    try:
        root = Path(project_root)
        return (
            (root / "core" / "prompt_manager" / "sections.py").exists()
            and (root / "core" / "core_prompt" / "COMMON.md").exists()
            and (root / "core" / "core_prompt" / "SOUL.md").exists()
            and (root / "AGENTS.md").exists()
            and (root / "config" / "models.py").exists()
        )
    except Exception:
        return False


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
    """从 Markdown 文件创建章节。

    文件正文会剥离 front matter 后再注入 prompt，避免把文件注释误当成
    section 运行时元信息。
    """

    # 仅静态文件章节在注册时预估空态；动态章节避免固化陈旧 empty 元信息
    empty = False if cache_break else True
    if not cache_break and path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
            body = _strip_front_matter(raw)
            empty = not bool(body)
        except Exception:
            empty = True

    def compute() -> Optional[str]:
        if not path.exists():
            return None
        try:
            content = _strip_front_matter(path.read_text(encoding="utf-8"))
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


def make_runtime_goal_section(ctx: BuildContext) -> SystemPromptSection:
    """当前运行目标包：统一 agent 的入口目标与能力边界。"""

    def compute() -> Optional[str]:
        packet = getattr(ctx, "runtime_goal_packet", None)
        if packet is None:
            return None
        render = getattr(packet, "render", None)
        if callable(render):
            text = render()
        else:
            text = str(packet or "")
        return text.strip() or None

    return SystemPromptSection(
        name="RUNTIME_GOAL",
        compute=compute,
        cache_break=True,
        priority=18,
        description="当前目标、来源、能力边界与完成标准",
        required=True,
    )


def make_user_profile_section() -> SystemPromptSection:
    """用户画像：从公开配置读取，作为 agent 的用户参考上下文。"""

    def _compact(value: Any, limit: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "…"

    def compute() -> Optional[str]:
        try:
            from config.public_config import load_public_config

            public_config = load_public_config()
        except Exception:
            return None

        profile = public_config.get("user_profile", {}) if isinstance(public_config, dict) else {}
        if not isinstance(profile, dict):
            return None

        display_name = _compact(profile.get("display_name"), 80)
        bio = _compact(profile.get("bio"), 280)
        raw_preferences = profile.get("preferences")
        preferences = raw_preferences if isinstance(raw_preferences, list) else []
        preference_lines = [_compact(item, 160) for item in preferences if _compact(item, 160)]

        if not display_name and not bio and not preference_lines:
            return None

        lines = ["## 用户画像", "以下信息来自用户在设置区维护的用户信息，是与用户协作时的参考依据。"]
        if display_name:
            lines.append(f"- 用户显示名: {display_name}")
        if bio:
            lines.append(f"- 用户背景: {bio}")
        if preference_lines:
            lines.append("- 用户偏好:")
            lines.extend(f"  - {item}" for item in preference_lines[:12])
        return "\n".join(lines)

    return SystemPromptSection(
        name="USER_PROFILE",
        compute=compute,
        # 静态章节：compute 只读公开配置的用户画像，无任何逐轮动态依赖，
        # 文本跨轮字节稳定。cache_break=True 的每轮重算只会制造无谓的
        # 前缀漂移风险与重复 IO。语义：设置区编辑在运行时重启后生效。
        cache_break=False,
        cache_prefix=True,
        priority=19,
        description="用户在设置区维护的身份、背景与协作偏好",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 静态章节工厂（cache_break=False）
# ═══════════════════════════════════════════════════════════════════════════════


def make_task_checklist_section() -> SystemPromptSection:
    """任务清单 — 从 TaskManager 动态加载。"""

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
        cache_break=True,
        priority=20,
        description="当前激活的任务清单",
    )


def make_codebase_map_section(
    build_context: BuildContext | None = None,
) -> SystemPromptSection:
    """代码库认知地图 — 读取缓存文件（由 ToolExecutor 钩子自动更新）。"""

    def compute() -> Optional[str]:
        try:
            from core.prompt_manager.codebase_map_builder import get_codebase_map
            return get_codebase_map(
                force_refresh=False,
                current_goal=(
                    build_context.current_goal
                    if build_context is not None
                    else None
                ),
                state_memory=(
                    build_context.state_memory
                    if build_context is not None
                    else None
                ),
            ) or None
        except Exception:
            return None

    return SystemPromptSection(
        name="CODEBASE_MAP",
        compute=compute,
        cache_break=True,
        priority=30,
        description="代码库结构认知地图（按当前 Agent 目标自动更新）",
    )


def make_git_rules_section(project_root: Path) -> SystemPromptSection:
    """Git 提交规则摘要 — 从工作流文档提炼运行时提醒。"""
    workflow_path = resolve_project_workspace_home(project_root) / "prompts" / "GIT_WORKFLOW.md"

    def compute() -> Optional[str]:
        try:
            if workflow_path.exists():
                return _build_git_rules_summary(workflow_path.read_text(encoding="utf-8"))
            if _looks_like_vibelution_project_root(project_root):
                return _build_git_rules_summary(_DEFAULT_GIT_WORKFLOW)
            return None
        except Exception:
            return None

    is_empty = True
    try:
        if workflow_path.exists():
            is_empty = not bool(_build_git_rules_summary(workflow_path.read_text(encoding="utf-8")))
        elif _looks_like_vibelution_project_root(project_root):
            is_empty = not bool(_build_git_rules_summary(_DEFAULT_GIT_WORKFLOW))
    except Exception:
        is_empty = True

    return SystemPromptSection(
        name="GIT_RULES",
        compute=compute,
        cache_break=False,
        priority=38,
        description="Git 提交纪律摘要（从工作流文档提炼）",
        is_empty=is_empty,
    )


def make_reading_rules_section() -> SystemPromptSection:
    """代码与日志阅读规则 — 结构化工具优先，shell 仅作补充。"""

    def compute() -> str:
        return (
            "## 阅读规则\n"
            "- **默认定位**走 `code_symbol_tool` / `grep_search_tool` / `glob_tool`，不要一上来连串 shell 探查。\n"
            "- 需要命令行搜索时用有界 `rg -n \"关键词\" 路径`（无 Unix 管道）；Windows 上 `rg ... | head` 会被拦截。\n"
            "- Windows 读小段用**完整 PowerShell**（如 `Get-Content -LiteralPath \"路径\" | Select-Object -First 80`），"
            "不要假设默认 bash，也不要在 bash 里写 `Select-Object`。\n"
            "- 不要调用 `read_file_tool`，不要整文件粗读；已读范围不重复读。\n"
            "- 同类 shell 失败 1 次后回到结构化工具，禁止换壳重试同一意图。\n"
        )

    return SystemPromptSection(
        name="READING_RULES",
        compute=compute,
        cache_break=False,
        priority=36,
        description="结构化工具优先的有界阅读规则",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 动态章节工厂（cache_break=True）
# ═══════════════════════════════════════════════════════════════════════════════


def make_env_info_section(project_root: Path) -> SystemPromptSection:
    """环境信息 — 时间以 5 分钟粒度稳定，保持缓存友好。"""

    def command_discipline(os_name: str) -> List[str]:
        from tools.shell_tools import shell_command_dialect_guidance

        host_key = {"Windows": "Windows", "macOS": "Darwin", "Linux": "Linux"}.get(os_name, os_name)
        dialect_lines = [
            f"- {line}" if line and not line.startswith("===") else line
            for line in shell_command_dialect_guidance(host_system=host_key).splitlines()
            if line.strip()
        ]
        budget = [
            "- 命令入口: 默认 `cli_tool`/`exec_command`（同一 shell 路由）；定位优先结构化工具。",
            "- 回合预算: 工具调用有额度上限（常见 32 次）；探查失败不得耗尽额度，至少预留 2–3 次给验证。",
            "- 大结果: 输出超过约 4KB 时只保留结论，勿整段回灌。",
        ]
        return [*budget, *dialect_lines]

    def compute() -> Optional[str]:
        now = datetime.now()
        rounded_minute = (now.minute // 5) * 5
        rounded_time = now.replace(minute=rounded_minute, second=0, microsecond=0)
        current_time = rounded_time.strftime("%Y-%m-%d %H:%M")

        import platform
        system_name = platform.system()
        os_name = {"windows": "Windows", "darwin": "macOS", "linux": "Linux"}.get(
            system_name.lower(), system_name
        )

        return "\n".join([
            "## 当前环境",
            f"- 当前时间: {current_time}",
            f"- 操作系统: {os_name} ({platform.version()}) [{platform.machine()}]",
            *command_discipline(os_name),
            f"- 项目根目录: {project_root}",
            "- 静态提示词位置: core/core_prompt/",
            "- 动态提示词位置: workspace/prompts/",
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

        # ── 元认知干预（若已走统一 Turn Status 注入，则不再塞进 MEMORY，避免双写）──
        intervention = ""
        try:
            from core.mental_model_flags import is_mental_model_enabled
            from core.runtime_status_flags import is_runtime_status_inject_enabled

            if is_runtime_status_inject_enabled():
                raise RuntimeError("mental intervention carried by turn status bar")
            if not is_mental_model_enabled():
                raise RuntimeError("mental model disabled for this turn")
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


def make_git_memory_section() -> SystemPromptSection:
    """Git 变化记忆章节 — 仅使用已缓存事实，不主动扫 git。

    实时 worktree 状态由 Agent 主动调用 git 工具刷新；主循环不再每轮自动 scan。
    """

    def compute() -> Optional[str]:
        try:
            from core.infrastructure.git_memory import get_git_memory_service
            return get_git_memory_service().format_prompt_context() or None
        except Exception:
            return None

    return SystemPromptSection(
        name="GIT_MEMORY",
        compute=compute,
        cache_break=True,
        priority=35,
        description="缓存中的 Git 事实（工具刷新后才更新；不隐式 scan）",
    )


def make_runtime_log_index_section() -> SystemPromptSection:
    """运行日志索引章节 — 每轮读取最近 runtime scene 包的轻量索引。"""

    def compute() -> Optional[str]:
        try:
            from core.web.services.runtime_scene_service import build_runtime_scene_prompt_index

            return build_runtime_scene_prompt_index(limit=3) or None
        except Exception:
            return None

    return SystemPromptSection(
        name="RUNTIME_LOG_INDEX",
        compute=compute,
        cache_break=True,
        priority=36,
        description="最近 runtime scene 包索引、状态、问题簇和优先读取路径",
    )


def make_config_awareness_section() -> SystemPromptSection:
    """配置自感知章节 — 每轮读取当前配置身份、风险与建议动作。"""

    def compute() -> Optional[str]:
        try:
            from config import get_config
            return get_config().format_config_awareness_prompt()
        except Exception:
            return None

    return SystemPromptSection(
        name="CONFIG_AWARENESS",
        compute=compute,
        cache_break=True,
        priority=36,
        description="当前配置身份、关键来源、风险提示与建议动作",
    )


def make_delegation_rules_section() -> SystemPromptSection:
    """委派规则章节 — 主脑调度与子代理边界。"""

    def compute() -> Optional[str]:
        try:
            from core.infrastructure.agent_session import get_session_state
            text = get_session_state().render_delegation_static_rules()
            return text if isinstance(text, str) and text.strip() else None
        except Exception:
            return None

    return SystemPromptSection(
        name="DELEGATION_RULES",
        compute=compute,
        # 静态章节：render_delegation_static_rules 返回固定规则文本（无
        # session 状态依赖），逐轮重算不产生任何新信息，只会让每轮构建
        # 多做一次字符串拼接。动态委派状态由 DELEGATION_STATE 负责。
        cache_break=False,
        cache_prefix=True,
        priority=36,
        description="主脑调度、子代理边界、结果回收与失败接管规则",
    )


def make_delegation_state_section() -> SystemPromptSection:
    """委派状态章节 — 当前委派、最近证据和失败状态。"""

    def compute() -> Optional[str]:
        try:
            from core.infrastructure.agent_session import get_session_state
            text = get_session_state().render_delegation_state()
            return text if isinstance(text, str) and text.strip() else None
        except Exception:
            return None

    return SystemPromptSection(
        name="DELEGATION_STATE",
        compute=compute,
        cache_break=True,
        priority=36,
        description="当前委派状态、最近回收证据与失败提示",
    )


def make_language_awareness_section() -> SystemPromptSection:
    """语言自感知章节 — 稳定压制自然语言输出向英文漂移。"""

    def compute() -> str:
        return (
            "## 语言状态\n"
            "- 当前默认表达语言：中文\n"
            "- 除代码、命令、路径、类名、函数名、API 名称、协议字段、必要报错原文外，自然语言说明应使用中文\n"
            "- 若本轮自然语言开始滑向英文，应自行拉回中文\n"
        )

    return SystemPromptSection(
        name="LANGUAGE_AWARENESS",
        compute=compute,
        cache_break=False,
        priority=37,
        description="当前默认语言、保留原文边界与英文漂移自纠偏",
    )


def make_session_child_routing_section() -> SystemPromptSection:
    """会话子任务路由章节 — 指导 Agent 何时拆分子对话。"""

    def compute() -> str:
        return (
            "## 会话子对话路由\n"
            "- 当前会话承载一个主线目标；当用户提出明显独立的新事项、并行事项或会把当前主线搅混的任务时，先把它视为候选子对话。\n"
            "- 若新事项与当前主线关系不确定，先向用户提出一个简短确认问题；只有当前工具集中实际可见 `create_child_session_tool`，且用户明确允许拆分时，才创建同一 Agent 的子对话。\n"
            "- 创建子对话时携带完整 user_request、清晰 task_title、split_reason，以及真正有用的 inherited_facts/relevant_files/relevant_logs/constraints；不要搬运整段无关历史。\n"
            "- 默认 `auto_start=true`，让子对话创建后自动开始；默认 `switch_to_child=false`，子对话在后台推进，不抢走正在看的父会话。\n"
            "- 子对话只做一层；如果当前已经在子对话中又出现新的独立事项，仍创建到 root 会话下，作为兄弟子对话。\n"
            "- 不要为普通追问、同一任务的小步骤、测试验证、实现细节或用户明确要求继续当前主线的内容创建子对话。\n"
            "- 需要汇报多事项状态或避免重复拆分时，只有当前工具集中实际可见 `list_child_sessions_tool`，才查看当前 root 下已有子对话。\n"
        )

    return SystemPromptSection(
        name="SESSION_CHILD_ROUTING",
        compute=compute,
        cache_break=False,
        priority=37,
        description="多事项识别、子对话创建、上下文交接与一层子对话边界",
    )


def make_spec_digest_section(ctx: BuildContext) -> SystemPromptSection:
    """SPEC 运行时摘要层 — 只保留当前模式最关键的硬纪律。"""

    def compute() -> str:
        mode = (ctx.prompt_mode or "orient").strip().lower()
        mode_title = {
            "orient": "定向",
            "diagnose": "诊断",
            "delegate": "委派",
            "execute": "执行",
            "verify": "验证",
        }.get(mode, mode or "运行时")

        packet = getattr(ctx, "runtime_goal_packet", None)
        max_calls = 0
        if packet is not None:
            try:
                max_calls = int(getattr(packet, "max_calls_per_turn", 0) or 0)
            except (TypeError, ValueError):
                max_calls = 0
        if max_calls > 0:
            budget_rule = (
                f"- 本回合工具额度 **{max_calls}** 次（maxCallsPerTurn）；"
                "用尽即停，下一用户消息重新计数；不要为耗尽额度写长报告或继续探查。"
            )
        else:
            budget_rule = (
                "- 工具额度以 Agent 策略为准（常见 32 次）；"
                "用尽即停，下一用户消息重新计数。"
            )
        common = [
            "- 默认中文；代码、命令、路径、协议字段、必要报错可保留原文。",
            "- 同轮同类失败不重复：shell/被拦截失败 **1 次**后立即换 `code_symbol_tool`/`grep_search_tool`，禁止换壳连撞。",
            "- 工具顺序：定位优先结构化工具 → 必要时有界 `rg`/小范围读 → 稳定修改批次后按影响面做最小 lint/compile/test；同一 HEAD、同一命令且相关输入未变化时复用通过结果，不重复执行。",
            budget_rule,
            "- cli_tool/exec_command 共用 shell 方言路由；命令要短、可复现、输出有界（默认约 6KB），大结果只消费结论。",
            "- 记忆读取可用于查历史决策；record_learning 只在形成可复用经验或踩坑规律时写入。",
        ]
        mode_rules = {
            "orient": [
                "- 先看 Git 变化与当前目标，再决定是否需要全局地图或配置上下文。",
                "- 没有明确锚点时先收窄问题，不要把大段规则和全局上下文一起常驻。",
            ],
            "diagnose": [
                "- 先复现，再观测，再读代码，最后推理；没有新增观测时停止长推理。",
                "- 已形成反馈环后优先围绕单一锚点收窄，禁止横向扩散。",
            ],
            "delegate": [
                "- 只把边界清晰、阅读量大的问题委派给只读子 agent。",
                "- 子 agent 只返回结构化证据，最终裁决仍由主 agent 自己做。",
                "- 同轮已有有效委派结果时，禁止重复派发同类问题。",
            ],
            "execute": [
                "- 只在当前冻结范围内做最小修改，不顺手扩改无关路径。",
                "- 修改期只对受影响文件跑最窄反馈测试，失败后只重跑受影响项；完整 selector 计划留给最终 closeout 一次执行，验证不过不提交。",
                "- 高风险业务逻辑尽量留在 core/，不要把实现重新堆回 agent.py。",
            ],
            "verify": [
                "- 优先完成当前验证闭环；验证通过后直接收束，不开新支线。",
                "- 提交前确认修改范围、验证结果和当前脏区一致，不夹带无关变更。",
            ],
        }

        lines = [f"## SPEC 运行时摘要（{mode_title}）", *common, *(mode_rules.get(mode) or mode_rules["orient"])]
        return "\n".join(lines)

    return SystemPromptSection(
        name="SPEC_DIGEST",
        compute=compute,
        cache_break=True,
        priority=60,
        description="当前模式下最关键的运行时规则摘要",
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
    build_context: BuildContext | None = None,
) -> List[SystemPromptSection]:
    """创建默认章节列表（不含 MEMORY，它依赖 BuildContext 在 build 时动态创建）。

    Args:
        section_configs: [[prompt.sections]] 配置列表，每项含 name/path/priority 等属性。
            COMMON / SOUL / AGENTS 是代码保护的必载核心，不受该配置开关控制。
    """

    sections: List[SystemPromptSection] = []

    # ── 三核心静态章节（代码保护，配置不能关闭或覆盖）──

    load_core_prompt_bundle(project_root)
    for spec in CORE_PROMPT_SPECS:
        path = core_prompt_path(project_root, spec)
        sections.append(make_file_section(
            spec.name,
            path,
            priority=spec.priority,
            cache_break=False,
            description=spec.description,
            required=True,
        ))

    for cfg in (section_configs or []):
        if str(getattr(cfg, "name", "") or "").strip().upper() in CORE_PROMPT_NAMES:
            continue
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
    sections.append(make_user_profile_section())
    sections.append(make_codebase_map_section(build_context))
    sections.append(make_git_memory_section())
    sections.append(make_runtime_log_index_section())
    sections.append(make_delegation_rules_section())
    sections.append(make_delegation_state_section())
    sections.append(make_config_awareness_section())
    sections.append(make_language_awareness_section())
    sections.append(make_session_child_routing_section())
    sections.append(make_reading_rules_section())
    sections.append(make_git_rules_section(project_root))

    # ── 动态章节 ──

    sections.append(make_env_info_section(project_root))

    # ── Workspace 章节（仅在启用时注册）──

    if enable_workspace:
        for fname, pri, desc in [
            ("IDENTITY.md", 50, "Agent 身份定义"),
            ("USER.md", 70, "外部宿主环境与交互偏好"),
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
