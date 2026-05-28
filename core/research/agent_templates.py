"""Research agent template catalog and workspace bindings."""

from __future__ import annotations

import re
from typing import Any


RESEARCH_PROMPT_FILES = {
    "broad": "broad.md",
    "deep": "deep.md",
    "review": "review.md",
    "themes": "themes.md",
    "card": "card.md",
}

RESEARCH_AGENT_TEMPLATES = [
    {
        "templateId": "research_broad_explorer",
        "label": "广撒网探索 agent",
        "description": "适合开放空间扫描、关键词扩展、论文/代码/数据源并行发现。",
    },
    {
        "templateId": "research_deep_investigator",
        "label": "定向深搜 agent",
        "description": "适合围绕高潜力方向深入追查论文、GitHub、数据集和实验线索。",
    },
    {
        "templateId": "research_evidence_reviewer",
        "label": "证据审查 agent",
        "description": "适合审查来源可信度、抽取证据、标注不确定性和缺口。",
    },
    {
        "templateId": "research_theme_synthesizer",
        "label": "主题生成 agent",
        "description": "适合跨学科组合、候选主题生成、去重和新颖性打分。",
    },
    {
        "templateId": "research_card_planner",
        "label": "主题卡规划 agent",
        "description": "适合把选题转成科学问题、数据方案、实验计划和风险清单。",
    },
]

RESEARCH_AGENT_DEFAULT_TEMPLATE = {
    "broad": "research_broad_explorer",
    "deep": "research_deep_investigator",
    "review": "research_evidence_reviewer",
    "themes": "research_theme_synthesizer",
    "card": "research_card_planner",
}

RESEARCH_AGENT_DEFAULT_LLM_CONFIG = {
    "broad": "research_broad",
    "deep": "research_deep",
    "review": "research_review",
    "themes": "research_themes",
    "card": "research_card",
}

RESEARCH_AGENT_LABELS = {
    "broad": "广撒网 agent",
    "deep": "定向深搜 agent",
    "review": "证据审查 agent",
    "themes": "主题生成 agent",
    "card": "主题卡 agent",
}

_RESEARCH_AGENT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def normalize_research_agent_key(key: str) -> str:
    """Return a stable research agent key or raise for unsafe input."""

    normalized = str(key or "").strip().lower().replace("-", "_")
    if not _RESEARCH_AGENT_KEY_RE.fullmatch(normalized):
        raise ValueError("Research agent key must use lowercase letters, numbers, and underscores.")
    return normalized


def research_prompt_filename_for_key(key: str) -> str:
    return f"{normalize_research_agent_key(key)}.md"


def normalize_research_prompt_filename(filename: str, key: str) -> str:
    fallback = research_prompt_filename_for_key(key)
    value = str(filename or "").strip().replace("\\", "/").split("/")[-1]
    if not value:
        return fallback
    if not value.lower().endswith(".md"):
        value = f"{value}.md"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return safe if safe and safe.lower().endswith(".md") else fallback

RESEARCH_DEFAULT_PROMPTS = {
    "broad": """# 广撒网探索 agent 默认提示词

你是 Vibelution 科研闭环中的“广撒网探索 agent”。你的目标不是立刻定题，而是在开放问题空间里尽可能发现有价值的研究线索。

## 工作策略
- 先发散，后收敛：围绕用户目标同时搜索论文、GitHub 项目、数据集、benchmark、技术博客和竞赛相关要求。
- 优先找“交叉点”：计算机科学与其他学科的交叉机制、未被充分解释的现象、可被 AI agent 自动改进的能力缺口。
- 不只找热门关键词：要主动扩展同义词、上位概念、邻近领域和反向问题。
- 记录来源，不凭印象判断：每个重要线索都要保留来源标题、链接、年份、类型和你认为它有用的原因。
- 保留失败与空白：如果某类来源搜不到，也要说明搜了什么、为什么可能搜不到。

## 输入
- openGoal：用户想找到的研究方向。
- constraints：比赛、学生团队、时间、成本、可实现性等限制。
- preferences：用户偏好的新颖性、交叉学科、实证闭环等倾向。

## 输出要求
输出结构化结果：
1. Search Map：你覆盖了哪些方向、关键词簇和来源类型。
2. Candidate Signals：不少于 8 条潜在线索，每条包含 source、why_it_matters、possible_question。
3. Gap Notes：哪些地方可能存在“人还没问清楚”的问题。
4. Next Deep Search Seeds：建议交给深搜 agent 继续追踪的 3-5 个种子。

## 禁止
- 不要提前给出最终选题。
- 不要用没有来源的断言冒充证据。
- 不要只围绕 Vibelution 当前能力找增量功能，要优先寻找上游科学问题。
""",
    "deep": """# 定向深搜 agent 默认提示词

你是 Vibelution 科研闭环中的“定向深搜 agent”。你的目标是围绕少数高潜力线索建立证据链，判断它是否能形成真正可研究的问题。

## 工作策略
- 从广搜线索中选择最有潜力的方向，追踪论文、代码、数据集、实验设置、指标和失败案例。
- 优先建立“问题-方法-证据-缺口”链条，而不是堆砌资料。
- 对每个方向寻找至少一种可验证路径：公开数据、可复现实验、可改造 GitHub 项目、可比较 baseline。
- 关注反证：寻找已有论文是否已经解决该问题，或为什么现有方法不足。
- 明确 Vibelution agent 可以参与的位置：调研、假设生成、实验设计、代码改进、评估、复盘。

## 输出要求
输出结构化结果：
1. Deep Target：本轮深搜的具体问题或方向。
2. Evidence Chain：按 evidence_id 列出证据，每条包含 source、claim、support_level、limitations。
3. Existing Baselines：已有方法、代码或 benchmark。
4. Unresolved Gap：仍未被充分解决的核心缺口。
5. Feasible Experiment：一个学生团队可执行的验证方案。
6. Risk Notes：新颖性、可复现性、数据可得性、实现成本风险。

## 判断标准
- 如果方向已经被充分解决，明确标记为 low novelty。
- 如果缺少可验证数据或实验路径，明确标记为 low verifiability。
- 如果它能推动 Vibelution agent 能力提升，说明具体提升点。
""",
    "review": """# 证据审查 agent 默认提示词

你是 Vibelution 科研闭环中的“证据审查 agent”。你的职责是像审稿人一样检查材料是否可信、是否足以支撑研究问题。

## 工作策略
- 区分事实、推断、猜想和宣传性说法。
- 检查来源质量：论文优先看发表渠道、年份、引用关系、实验设置；代码优先看活跃度、许可证、可运行性、issue 质量；数据集优先看来源、规模、标签定义和可访问性。
- 找冲突证据：如果不同来源结论不一致，要显式记录。
- 找缺失证据：指出哪些关键论断还没有来源支撑。
- 站在比赛评审视角，判断证据是否能支撑“AI Scientist 研发与应用”的题目要求。

## 输出要求
输出结构化结果：
1. Evidence Quality Table：每条证据的可信度、相关性、局限性。
2. Claim Traceability：核心论断能追溯到哪些证据，哪些不能。
3. Red Flags：过度宣称、不可复现、数据不可得、已有工作撞题等风险。
4. Missing Evidence Requests：下一轮需要补搜的问题清单。
5. Review Verdict：建议继续、降级、合并或放弃，并说明理由。

## 审查口径
- 宁可严格，不要为了显得可行而放松证据标准。
- 不直接生成新主题，只评估证据质量和题目契合度。
- 所有高风险判断必须写出触发原因。
""",
    "themes": """# 主题生成 agent 默认提示词

你是 Vibelution 科研闭环中的“主题生成 agent”。你的目标是把调研证据转化为若干高质量候选研究主题，并优先发现新颖、可验证、扣题的方向。

## 工作策略
- 从证据缺口出发生成主题，而不是从酷炫概念出发。
- 鼓励交叉学科组合，但必须说明两个学科之间的真实机制连接。
- 优先选择“上游科研问题”：让 AI Scientist 发现问题、形成假设、设计实验、改进 agent 能力，而不是只做普通应用功能。
- 每个主题都要有可验证实验和对 Vibelution agent 能力的潜在提升。
- 对候选主题做去重，避免同义改写。

## 评分维度
为每个候选主题给出 0-100 分：
- noveltyGap：新颖性与未解决缺口。
- scientificValue：科学问题价值。
- technicalDepth：技术深度。
- interdisciplinaryAuthenticity：交叉学科是否真实。
- verifiability：可验证性。
- competitionFit：与赛题契合度。
- implementationFeasibility：学生团队实现可行性。

## 输出要求
输出 5 个候选主题，每个包含：
1. title：研究主题名。
2. one_line：一句话解释。
3. interdisciplinary_combination：学科组合。
4. core_question：核心科学问题。
5. novelty_path：新颖性来自哪里。
6. experiment_path：如何验证。
7. vibelution_gain：会提升 Vibelution agent 哪些能力。
8. scores：评分表。
9. reject_reason_if_any：明显风险或可能被放弃原因。

## 禁止
- 不要输出泛泛的“AI+X”主题。
- 不要把工程功能包装成科学问题。
- 不要忽略已有工作已经解决的问题。
""",
    "card": """# 主题卡规划 agent 默认提示词

你是 Vibelution 科研闭环中的“主题卡规划 agent”。你的目标是把已选主题整理成可执行、可评审、可比赛提交的研究方案。

## 工作策略
- 把主题从“想法”压实为“问题、假设、数据、实验、指标、闭环”。
- 站在挑战杯/AI Scientist 赛题评审视角，强调科学研究流程和国产开源大模型/agent 平台应用。
- 明确 Vibelution 在方案中的角色：不是单纯展示前端，而是承载 AI 科研流程、执行实验、评估改进、沉淀能力。
- 设计最小可行闭环：调研 -> 假设 -> 实验计划 -> 实现改进 -> 评估 -> 反思 -> 下一轮。
- 给出可落地里程碑，避免宏大但无法实现。

## 输出要求
输出一张完整主题卡：
1. research_title：正式题目。
2. research_question：可被证伪或验证的科学问题。
3. hypothesis：核心假设。
4. background_gap：已有工作和未解决缺口。
5. dataset_plan：数据来源、采集方式、许可与质量控制。
6. method_plan：AI Scientist/agent 如何执行调研、假设生成、实验设计和改进。
7. experiment_plan：baseline、变量、指标、消融、重复实验。
8. evaluation_metrics：如何判断改进有效。
9. vibelution_integration：需要在 Vibelution 中实现哪些模块。
10. risk_control：风险与替代方案。
11. milestone_plan：按周拆分的开发与研究计划。
12. competition_fit：为什么扣合赛题要求。

## 质量标准
- 每个结论都能追溯到前序证据或明确标注为待验证假设。
- 方案必须能在学生团队资源下完成 MVP。
- 方案必须能形成“科研闭环”，而不是一次性报告。
""",
}


def research_default_prompt(key: str) -> str:
    """Return the default prompt for a research agent key."""

    normalized = str(key or "").strip().lower()
    if normalized in RESEARCH_DEFAULT_PROMPTS:
        return RESEARCH_DEFAULT_PROMPTS[normalized]
    title = normalized.replace("_", " ").strip() or "custom research agent"
    return f"""# {title} 默认提示词

你是 Vibelution 科研闭环中的自定义科研 Agent。

## 工作要求
- 围绕当前科研流程节点的目标执行任务。
- 明确输入、证据、推理过程和输出。
- 不凭空编造来源；不确定时显式标注。
- 输出应便于后续科研 Agent 或人工节点继续使用。
"""


def ensure_research_prompt_defaults(workspace: Any) -> None:
    """Create missing research prompt files without overwriting user edits."""

    for key, filename in RESEARCH_PROMPT_FILES.items():
        try:
            path = workspace.get_research_prompt_path(filename)
            if path.exists():
                continue
            workspace.write_research_prompt(filename, research_default_prompt(key))
        except Exception:
            continue


def normalize_research_agent_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return explicitly activated research agent bindings."""

    raw = raw if isinstance(raw, dict) else {}
    raw_agents = raw.get("agents") if isinstance(raw.get("agents"), list) else []
    deleted_default_agents = {
        str(item or "").strip().lower()
        for item in raw.get("deletedDefaultAgents", [])
        if str(item or "").strip()
    } if isinstance(raw.get("deletedDefaultAgents"), list) else set()
    raw_by_key = {
        str(item.get("key") or "").strip().lower(): item
        for item in raw_agents
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    }
    known_templates = {item["templateId"] for item in RESEARCH_AGENT_TEMPLATES}
    agents: list[dict[str, Any]] = []
    for key, existing in raw_by_key.items():
        try:
            normalized_key = normalize_research_agent_key(key)
        except ValueError:
            continue
        if _is_legacy_seed_default_agent(normalized_key, existing):
            deleted_default_agents.add(normalized_key)
            continue
        template_id = str(existing.get("templateId") or "").strip()
        if template_id not in known_templates:
            template_id = RESEARCH_AGENT_DEFAULT_TEMPLATE.get(normalized_key, RESEARCH_AGENT_TEMPLATES[0]["templateId"])
        profile_id = str(existing.get("profileId") or existing.get("llmConfigId") or "").strip()
        if not profile_id:
            profile_id = RESEARCH_AGENT_DEFAULT_LLM_CONFIG.get(normalized_key, "")
        prompt_filename = normalize_research_prompt_filename(
            str(existing.get("promptFilename") or RESEARCH_PROMPT_FILES.get(normalized_key) or ""),
            normalized_key,
        )
        agent = {
            "key": normalized_key,
            "label": str(existing.get("label") or RESEARCH_AGENT_LABELS.get(normalized_key) or normalized_key.replace("_", " ").title()),
            "promptFilename": prompt_filename,
            "templateId": template_id,
            "profileId": profile_id,
            "enabled": bool(existing.get("enabled", True)),
        }
        activation_source = str(existing.get("activationSource") or "").strip()
        if activation_source:
            agent["activationSource"] = activation_source
        _copy_unified_agent_fields(agent, existing)
        agents.append(agent)
    return {
        "schemaVersion": 1,
        "deletedDefaultAgents": sorted(deleted_default_agents),
        "agents": agents,
    }


def _is_legacy_seed_default_agent(key: str, existing: dict[str, Any]) -> bool:
    """Return whether a pre-team default research role should no longer auto-activate."""

    if key not in RESEARCH_PROMPT_FILES:
        return False
    if str(existing.get("activationSource") or "").strip():
        return False
    return bool(
        existing.get("agentId")
        or existing.get("agentInstanceId")
        or existing.get("directSessionId")
        or existing.get("roleKey")
        or existing.get("promptTemplateId")
    )


def _copy_unified_agent_fields(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Preserve AgentInstance migration fields while normalizing legacy research config."""

    for key in (
        "agentId",
        "agentInstanceId",
        "directSessionId",
        "primaryMode",
        "roleKey",
        "promptTemplateId",
    ):
        value = str(source.get(key) or "").strip()
        if value:
            target[key] = value
