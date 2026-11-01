# -*- coding: utf-8 -*-
"""角色级模型面预算棘轮（role-level model-face budget ratchet）。

灵感来自 deepseek dsh-superagent 的 ``model-surface.spec.ts``：把「一次模型
调用实际可见的全部字节面」钉进测试，防止提示词面 / 工具面 / 技能面在无意识
中膨胀。超限即红；要扩预算必须在同一 PR 内上调对应常量，并在注释里写明新的
实测值与依据——与 ``tests/test_agent_governance_docs.py`` 的棘轮写法同构。

=== 模型面组装点清单（交付物之一）===

一、python 侧（模型可见字节的全部组装点）

主组装链（本文件两个角色面的口径来源）：
 1. ``core/prompt_manager/prompt_manager.py`` — ``PromptManager.build()``：
    章节筛选、保护层（``_PROTECTED_FLOOR_SECTIONS``）、可选章节相关性裁剪、
    稳定段渲染缓存。
 2. ``core/prompt_manager/builder.py`` — ``get_system_prompt()``（章节计算/
    排序/动态边界插入）与 ``to_string()``（builder.py:258，全文拼接口径）。
 3. ``core/prompt_manager/sections.py`` — ``create_default_sections()``
    （sections.py:886）：三核心静态章节工厂 + 内置动态章节；
    RUNTIME_GOAL / SPEC_DIGEST / MEMORY 由
    ``PromptManager._register_default_sections`` 在工厂产物上追加注册。
 4. ``core/prompt_manager/core_prompt_sources.py`` — COMMON / SOUL / AGENTS
    三核心源。三核心 5400 token 上限由 ``tests/test_agent_governance_docs.py::
    test_stable_core_keeps_prompt_budget_headroom`` 单独看守；本文件叠加的是
    「角色总量层」，不改动也不重复该棘轮。
 5. ``core/prompt_manager/provider_adapters.py`` — PROTOCOL_ADAPTER 章节
    （自带上限 512 token，超限抛 ``PromptAssemblyBudgetError``）与
    ``build_prompt_assembly_context`` 的预算投影。
 6. ``core/prompt_manager/assembly_contract.py`` — ``estimate_prompt_tokens``
    （assembly_contract.py:69，utf-8 bytes/4 保守估算）与
    ``PromptAssemblyManifest``（每段 chars/estimated_tokens/budget），
    是本文件全部 token 断言的口径。
 7. ``core/llm/client.py`` — ``bind_tools()``/``bound_tools``（client.py:3591 /
    client.py:3628）+ ``_tool_to_schema``（client.py:2906）+
    ``core/llm/schema.py::sanitize_tool_schema``（单工具 description ≤1024
    chars）：每次请求 payload 的 ``tools`` 数组即模型可见的工具面
    （``core/llm/payload_builder.py:1306`` 同口径）。
 8. ``core/chat/skill_registry.py`` — ``build_skill_runtime_context`` /
    ``MAX_SKILL_CONTENT_CHARS=24000``（skill_registry.py:13）：slash 技能
    内容注入本轮对话（session_service 经 runtime_glue 注入）。

二级组装点（各自带独立系统提示词，不属于本文件两个角色面，但同属模型面）：
 9. ``core/web/services/prompt_template_service.py`` —
    ``build_agent_prompt_snapshot`` / ``render_agent_prompt_snapshot_system_block``：
    会话快照（三核心包 + 角色模板，chat 模式再拼 CHAT_AGENT_BASE_PROMPT），
    由 host seed 进静态上下文并令 PromptManager 冻结三核心
    （agent.py ``mark_core_prompt_snapshot_seeded_by_host`` → ``frozen_core_sections``）。
 10. ``core/orchestration/context_engine.py`` — ``build_agent_context`` 与
     static/dynamic/volatile 三段 runtime context block（含研究组织上下文）。
 11. ``core/web/services/team_workflow/llm_review_runners.py`` — 5 个
     review-step system prompts（reflection/pairwise/pareto/metareview/revision）。
 12. 辅助 LLM 调用面：``core/web/services/session/title_generation.py``、
     ``core/web/services/prompt_reflection_service.py``、
     ``core/orchestration/turn_status_bar.py``（turn status 注入）等。

二、web 侧（web/ 前端）无模型面组装，只有渲染；模型可见字节全部由 python 侧产出。

=== 上限取值依据 ===

所有上限 = 当前实测值 × 1.05 后向上取整（token 取整到 50，chars 取整到 100）。
实测基线（pytest + conftest 隔离环境，branch codex/model-face-budget-ratchet
@ f4683d8fb）：
 - default 角色面 6134 tokens；knowledge_steward 角色面 9038 tokens
   （快照块 7832 + 冻结三核心后的 PromptManager 面 1206）；
 - 技能面上界 24000 chars（CJK 最坏情况 utf-8 ≈18000 tokens）；
 - default session agent 工具面 41 个工具 ≈45388 schema chars；
   knowledge_steward 工具面 19 个工具 ≈28844 schema chars。

环境依赖：两个角色面经 PromptManager 真实构建，无网络/活后端依赖；数据根由
conftest 的 ``VIBELUTION_DATA_HOME`` 隔离到 tmp_path，因此 RUNTIME_LOG_INDEX /
USER_PROFILE / GIT_MEMORY 均为空态，章节集与 token 数确定。
"""

from __future__ import annotations

import json
from pathlib import Path

from core.chat.skill_registry import MAX_SKILL_CONTENT_CHARS
from core.llm.client import _tool_to_schema
from core.llm.schema import sanitize_tool_schema
from core.prompt_manager.assembly_contract import estimate_prompt_tokens
from core.prompt_manager.builder import to_string
from core.prompt_manager.core_prompt_sources import CORE_PROMPT_NAMES, load_core_prompt_bundle
from core.prompt_manager.prompt_manager import PromptManager
from core.web.services import prompt_template_service


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ── 角色面常量 ────────────────────────────────────────────────────────────────
# 实测 6134 tokens（PromptManager 默认 build 全文）；×1.05=6440.7 → 6450。
DEFAULT_ROLE_PROMPT_TOKEN_CAP = 6_450
# 实测 9038 tokens（快照块 7832 + 冻结三核心后的 PromptManager 面 1206，
# 含 SESSION_FILE_REFERENCES）；×1.05=9489.9 → 取 9400（+4.0% 余量）。
KNOWLEDGE_STEWARD_ROLE_PROMPT_TOKEN_CAP = 9_400

# 技能面已知上界：MAX_SKILL_CONTENT_CHARS=24000 chars，token 口径按 CJK 最坏
# 情况（每 char 3 utf-8 bytes）估算，即 estimate_prompt_tokens("知" * 24000)。
# 角色总量 = 角色面 + 技能面上界；扩技能预算会同时抬高这两条总量棘轮。
SKILL_FACE_UPPER_BOUND_TOKENS = estimate_prompt_tokens("知" * MAX_SKILL_CONTENT_CHARS)
# 实测 default 6134 + 18000 = 24134；×1.05=25340.7 → 25350。
DEFAULT_ROLE_TOTAL_TOKEN_CAP = 25_350
# 实测 steward 9038 + 18000 = 27038；×1.05=28389.9 → 取 28300（+4.7% 余量）。
KNOWLEDGE_STEWARD_ROLE_TOTAL_TOKEN_CAP = 28_300

# ── 工具面常量（bound_tools 口径：单工具 canonical JSON 字符数求和）──────────
# default session agent 绑定面 = DEFAULT_SESSION_AGENT_ALLOWED_TOOLS ∩ Key_Tools，
# 实测 41 个工具、45388 chars；×1.05=47657.4 → 47700。
DEFAULT_SESSION_AGENT_TOOL_SCHEMA_CHARS_CAP = 47_700
# knowledge_steward 绑定面 = ROLE_TOOL_PROFILES["knowledge_steward"]["allowedTools"]
# ∩ Key_Tools，实测 19 个工具、28844 chars；×1.05=30286.2 → 30300。
KNOWLEDGE_STEWARD_TOOL_SCHEMA_CHARS_CAP = 30_300


def _build_default_role_face() -> str:
    """default 角色面：PromptManager 默认 build 全文（三核心 + 默认章节）。"""
    return to_string(PromptManager().build())


def _build_knowledge_steward_role_face() -> str:
    """knowledge_steward 角色面：角色快照块 + 冻结三核心后的 PromptManager 面。

    组合口径 = 固定角色 web 会话的真实形态：
    - 角色快照（三核心包 + knowledge_steward.md）由 host seed 进静态上下文
      （core/web/services/session/worker.py），因此 PromptManager 侧按
      agent.py ``_excluded_system_prompt_sections_for_turn`` 的 stable-session
      路径排除 RUNTIME_LOG_INDEX 并冻结三核心（frozen_core_sections）；
    - 知识库管理员 primaryMode=general，不拼 CHAT_AGENT_BASE_PROMPT。
    """
    snapshot = prompt_template_service.build_agent_prompt_snapshot(
        "prompt-knowledge-steward",
        agent_id="agent-model-face-budget-probe",
        project_root=PROJECT_ROOT,
    )
    assert snapshot.get("reason") == "", snapshot.get("reason")
    snapshot_block = prompt_template_service.render_agent_prompt_snapshot_system_block(snapshot)
    assert snapshot_block, "knowledge_steward snapshot block must be non-empty"

    # 快照必须真携带三核心（等价 load_core_prompt_bundle 的内容契约），否则
    # 下面的 frozen_core_sections 会让角色面丢掉核心纪律。
    core_bundle = load_core_prompt_bundle(PROJECT_ROOT)
    for name in CORE_PROMPT_NAMES:
        assert f"## Core Prompt: {name}" in snapshot_block, name

    frozen = list(CORE_PROMPT_NAMES)
    pm_face = to_string(
        PromptManager().build(
            exclude=[*frozen, "RUNTIME_LOG_INDEX"],
            frozen_core_sections=frozen,
        )
    )
    return "\n\n".join(part for part in (snapshot_block, pm_face) if part.strip())


def _bound_tools_schema_chars(tool_names: tuple[str, ...], *, profile_label: str) -> tuple[int, int]:
    """按 core/llm/client.py bound_tools 口径累计工具面字符数。

    复用生产序列化链：``_tool_to_schema``（client.py:2906）→
    ``sanitize_tool_schema``（core/llm/schema.py，即 adapter 基类的实现，
    description ≤1024 chars），与 ``payload_builder.py:1306`` 出线字节同口径。
    返回 (解析工具数, canonical JSON 字符总数)。
    """
    from tools.Key_Tools import create_key_tools

    name_map = {tool.name: tool for tool in create_key_tools()}
    missing = [name for name in tool_names if name not in name_map]
    assert not missing, (
        f"{profile_label} policy references tools missing from Key_Tools "
        f"(they would silently drop out of bound_tools): {missing}"
    )
    resolved = [name_map[name] for name in tool_names]
    schemas = [sanitize_tool_schema(_tool_to_schema(tool)) for tool in resolved]
    for schema in schemas:
        assert schema.get("type") == "function"
        assert schema["function"]["name"], profile_label
    total_chars = sum(len(json.dumps(schema, ensure_ascii=False)) for schema in schemas)
    return len(resolved), total_chars


def test_default_role_prompt_face_within_budget() -> None:
    """default 角色面棘轮：三核心 + 默认章节全文不超 6450 tokens。"""
    face = _build_default_role_face()
    tokens = estimate_prompt_tokens(face)
    assert tokens <= DEFAULT_ROLE_PROMPT_TOKEN_CAP, (
        f"default role prompt face grew to {tokens} tokens "
        f"(cap {DEFAULT_ROLE_PROMPT_TOKEN_CAP}, measured baseline 6134). "
        "Raise DEFAULT_ROLE_PROMPT_TOKEN_CAP in the same PR with the new measurement."
    )


def test_knowledge_steward_role_prompt_face_within_budget() -> None:
    """knowledge_steward 角色面棘轮：快照块 + 冻结核心后的运行面 ≤9400 tokens。

    运行面保留 SESSION_FILE_REFERENCES（chat 会话输出约定），只排除
    stable-session 路径的 RUNTIME_LOG_INDEX。
    """
    face = _build_knowledge_steward_role_face()
    tokens = estimate_prompt_tokens(face)
    assert tokens <= KNOWLEDGE_STEWARD_ROLE_PROMPT_TOKEN_CAP, (
        f"knowledge_steward role prompt face grew to {tokens} tokens "
        f"(cap {KNOWLEDGE_STEWARD_ROLE_PROMPT_TOKEN_CAP}, measured baseline 9038). "
        "Raise KNOWLEDGE_STEWARD_ROLE_PROMPT_TOKEN_CAP in the same PR with the new measurement."
    )


def test_role_totals_include_skill_face_upper_bound() -> None:
    """角色总量棘轮：角色面 + 技能面已知上界（MAX_SKILL_CONTENT_CHARS）不超总量。"""
    skill_upper = SKILL_FACE_UPPER_BOUND_TOKENS
    default_total = estimate_prompt_tokens(_build_default_role_face()) + skill_upper
    assert default_total <= DEFAULT_ROLE_TOTAL_TOKEN_CAP, (
        f"default role total (prompt face + skill upper bound) grew to {default_total} tokens "
        f"(cap {DEFAULT_ROLE_TOTAL_TOKEN_CAP}). "
        "Raise DEFAULT_ROLE_TOTAL_TOKEN_CAP in the same PR with the new measurement."
    )
    steward_total = estimate_prompt_tokens(_build_knowledge_steward_role_face()) + skill_upper
    assert steward_total <= KNOWLEDGE_STEWARD_ROLE_TOTAL_TOKEN_CAP, (
        f"knowledge_steward role total (prompt face + skill upper bound) grew to {steward_total} tokens "
        f"(cap {KNOWLEDGE_STEWARD_ROLE_TOTAL_TOKEN_CAP}). "
        "Raise KNOWLEDGE_STEWARD_ROLE_TOTAL_TOKEN_CAP in the same PR with the new measurement."
    )


def test_default_session_agent_tool_surface_within_budget() -> None:
    """default 会话 Agent 工具面棘轮（bound_tools 口径）。

    选型依据：新建会话 Agent 的 ToolPolicy = default_session_agent_tool_policy，
    allowedTools 即 ``DEFAULT_SESSION_AGENT_ALLOWED_TOOLS``；agent.py 将
    ``decision.visible_tools`` 物化为 ``key_tools`` 并 ``bind_tools``，因此这组
    41 个工具就是 default 会话 Agent 每轮真实发给模型的 tools 数组。
    """
    from core.web.services.agent_directory_service import DEFAULT_SESSION_AGENT_ALLOWED_TOOLS

    resolved, total_chars = _bound_tools_schema_chars(
        DEFAULT_SESSION_AGENT_ALLOWED_TOOLS,
        profile_label="default_session_agent",
    )
    assert resolved >= 30, (
        f"default session agent tool surface shrank to {resolved} tools; "
        "profile/registry drift — re-measure before trusting the cap."
    )
    assert total_chars <= DEFAULT_SESSION_AGENT_TOOL_SCHEMA_CHARS_CAP, (
        f"default session agent tool surface grew to {total_chars} schema chars "
        f"({resolved} tools; cap {DEFAULT_SESSION_AGENT_TOOL_SCHEMA_CHARS_CAP}, "
        "measured baseline 45388). Raise DEFAULT_SESSION_AGENT_TOOL_SCHEMA_CHARS_CAP "
        "in the same PR with the new measurement."
    )


def test_knowledge_steward_tool_surface_within_budget() -> None:
    """knowledge_steward 工具面棘轮（bound_tools 口径）。

    选型依据：固定角色工具面由
    ``core/web/services/agent_role_tool_profile_service.ROLE_TOOL_PROFILES``
    单源定义；knowledge_steward profile（19 个 allowedTools）经
    ``build_policy_from_role_profile`` 物化后 bind，代表「固定角色窄工具面」。
    与 default 会话面（41 工具）互补，覆盖宽窄两档工具面预算。
    """
    from core.web.services.agent_role_tool_profile_service import ROLE_TOOL_PROFILES

    steward_tools = tuple(ROLE_TOOL_PROFILES["knowledge_steward"]["allowedTools"])
    resolved, total_chars = _bound_tools_schema_chars(
        steward_tools,
        profile_label="knowledge_steward",
    )
    assert resolved >= 12, (
        f"knowledge_steward tool surface shrank to {resolved} tools; "
        "role profile/registry drift — re-measure before trusting the cap."
    )
    assert total_chars <= KNOWLEDGE_STEWARD_TOOL_SCHEMA_CHARS_CAP, (
        f"knowledge_steward tool surface grew to {total_chars} schema chars "
        f"({resolved} tools; cap {KNOWLEDGE_STEWARD_TOOL_SCHEMA_CHARS_CAP}, "
        "measured baseline 28844). Raise KNOWLEDGE_STEWARD_TOOL_SCHEMA_CHARS_CAP "
        "in the same PR with the new measurement."
    )


# --- 反噬守卫（anti-misuse guard）---------------------------------------
# 本文件的预算常量是 CI 层的测量基准，不是运行时限制。若有产品代码引用
# 这些常量（或 import tests 包）去截断/砍除/门控模型可见内容，就是
# 「预算把 agent 卡死」的失败形态——此守卫必须变红阻止。

_BUDGET_CAP_NAMES = (
    "DEFAULT_ROLE_PROMPT_TOKEN_CAP",
    "KNOWLEDGE_STEWARD_ROLE_PROMPT_TOKEN_CAP",
    "DEFAULT_ROLE_TOTAL_TOKEN_CAP",
    "KNOWLEDGE_STEWARD_ROLE_TOTAL_TOKEN_CAP",
    "DEFAULT_SESSION_AGENT_TOOL_SCHEMA_CHARS_CAP",
    "KNOWLEDGE_STEWARD_TOOL_SCHEMA_CHARS_CAP",
)


def test_budget_caps_stay_test_only() -> None:
    """反噬守卫：预算常量只允许存在于测试层，产品代码零引用。"""
    offenders: list[str] = []
    for root in (PROJECT_ROOT / "core", PROJECT_ROOT / "tools"):
        for path in sorted(root.rglob("*.py")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            referenced = [name for name in _BUDGET_CAP_NAMES if name in text]
            imports_tests = any(
                line.startswith(("import tests", "from tests"))
                for line in text.splitlines()
            )
            if referenced or imports_tests:
                why = referenced or ["imports tests package"]
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {', '.join(why)}")
    assert not offenders, (
        "Product code must not reference the model-face budget caps or import "
        "the tests package — these are CI measurements, never runtime limits. "
        f"Offenders: {offenders}. If a runtime need exists, it needs its own "
        "explicitly designed mechanism, not this ratchet's constants."
    )
