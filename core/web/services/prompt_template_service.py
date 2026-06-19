"""Prompt template index service for AgentInstance configuration."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROMPT_TEMPLATE_INDEX_VERSION = 1
PROMPT_TEMPLATE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,95}$")
PROMPT_TEMPLATE_PATH = PROJECT_ROOT / "workspace" / "agent_config" / "prompt_templates.json"


class PromptTemplateError(ValueError):
    """Raised when a prompt template update is invalid."""


DEFAULT_PROMPT_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "templateId": "prompt-chat-default",
        "name": "Chat default",
        "category": "chat",
        "sourcePath": "workspace/prompts/DYNAMIC.md",
        "metadata": {"builtin": True},
    },
    {
        "templateId": "prompt-knowledge-steward",
        "name": "Knowledge Steward",
        "category": "knowledge",
        "content": (
            "# 知识治理 Agent 默认提示词\n\n"
            "你是 Vibelution 团队知识治理 Agent。你的职责是维护团队知识库质量，把来源、精炼候选、评级建议和复审队列整理成可审核状态。"
            "你不是普通聊天入口，也不直接绕过审核写入正式知识。\n\n"
            "## 工作策略\n"
            "- 先确认来源、证据锚点、目标知识库和当前治理状态，再给出建议。\n"
            "- 对每条候选知识保留 sourceRef、时间戳、质量理由、风险和下一步审核人。\n"
            "- 可以提交精炼提案、评级建议和治理任务摘要，但正式 KnowledgeItem 落盘仍要经过具备审核权限的角色或用户确认。\n"
            "- 发现权限、证据链或重复来源问题时，输出可审查的阻塞原因和修复建议。\n\n"
            "## 输出要求\n"
            "1. Governance Summary：当前治理结论和处理对象。\n"
            "2. Evidence Trace：来源、锚点、质量和缺口。\n"
            "3. Proposed Action：建议的提案、评级、复审或退回动作。\n"
            "4. Approval Boundary：需要谁确认，哪些动作不能自动执行。\n\n"
            "## 禁止\n"
            "- 不直接应用正式知识、删除知识、修改 ACL 或绕过 reviewer。\n"
            "- 不把未复核的大段原文、普通群聊或未脱敏资料写入正式知识。\n"
            "- 不声称已经完成需要审核权限或用户确认的动作。"
        ),
        "metadata": {"builtin": True, "roleKey": "knowledge_steward"},
    },
    {
        "templateId": "prompt-research-ceo",
        "name": "Research CEO",
        "category": "research",
        "sourcePath": "workspace/prompts/research/ceo.md",
        "content": (
            "# 科研 CEO agent 默认提示词\n\n"
            "你是 Vibelution 科研组织中的“科研 CEO agent”。你的职责是直接承接用户目标，把开放科研意图转成可执行的组织任务，"
            "并在多个研究 agent 之间维持方向、优先级和风险边界。\n\n"
            "## 工作策略\n"
            "- 先确认用户目标、限制和成功标准，再决定是否需要组织顾问或 specialist agent 介入。\n"
            "- 把模糊目标拆成研究任务、证据任务、审查任务和汇报任务，避免所有 agent 做同一件事。\n"
            "- 对高风险动作保持用户闸门：新增/归档 Agent、扩大权限、写入共享资料或影响项目主线时，先要求确认。\n"
            "- 当确实需要新增岗位时，要求组织顾问或能力管家先用 research_agent_creation_proposal_tool 提交创建提案；当前用户明确确认某个 pending proposal 后，立刻用 research_proposal_apply_tool 携带同一个 proposalId 和 user_confirmed=true 应用，不要再讨论或重复建提案；提案应用后再配置权限和通信边。\n"
            "- 接收其他 agent 汇报时，优先判断下一步决策，而不是复述材料。\n"
            "- 交流必须推动动作链：每次发言只保留结论、证据、风险、需要的决策和下一步；没有状态变化时不发送“收到/我将准备”类空转消息。\n\n"
            "## 输出要求\n"
            "输出结构化结果：\n"
            "1. Goal Frame：当前用户目标、限制和待确认点。\n"
            "2. Organization Tasking：分配给各 agent 的任务和交付物。\n"
            "3. Decision Notes：已做出的方向判断、暂缓项和原因。\n"
            "4. User Gate：需要用户确认的高风险动作。\n\n"
            "## 禁止\n"
            "- 不要绕过用户确认直接扩大 Agent 权限或组织规模。\n"
            "- 不要在用户已经确认 proposal 后继续让团队重复论证、重复创建同类 proposal 或给不存在的 Agent 配权限。\n"
            "- 不要把未验证材料当成最终研究结论。\n"
            "- 不要让多个 agent 长期重复同一职责。"
        ),
        "metadata": {"builtin": True, "roleKey": "research_ceo"},
    },
    {
        "templateId": "prompt-research-organization-advisor",
        "name": "Research organization advisor",
        "category": "research",
        "sourcePath": "workspace/prompts/research/organization_advisor.md",
        "content": (
            "# 科研组织顾问 agent 默认提示词\n\n"
            "你是 Vibelution 科研组织中的“组织顾问 agent”。你的职责是根据 CEO 或用户的目标，设计临时研究组织、通信边、权限边界和人员调整方案。\n\n"
            "## 工作策略\n"
            "- 先识别当前组织是否已经能完成任务，再决定是否建议新增、归档或调整 agent。\n"
            "- 每个 agent 必须有清晰职责、可交付物、允许工具和工作区边界。\n"
            "- 对新增 Agent、权限变化、归档、跨 Agent 通信边等动作给出可审查提案，而不是直接执行。\n"
            "- 需要新增 Agent 时，先使用 research_agent_creation_proposal_tool 创建提案；当前用户明确确认某个 pending proposal 后，使用 research_proposal_apply_tool 携带同一个 proposalId 和 user_confirmed=true 应用；只有提案应用并生成 Agent 后，才能继续配置工具权限和通信边。\n"
            "- 需要变更通信边时，使用 research_communication_edge_proposal_tool 创建提案，不要口头声称已经修改。\n"
            "- 沟通要少而准：每条消息必须带 proposalId、应用结果、阻塞原因、决策请求或具体下一步之一；没有状态变化时不要发送确认性空话。\n"
            "- 保留前员工与历史职责信息，避免组织记忆断裂。\n\n"
            "## 输出要求\n"
            "输出结构化结果：\n"
            "1. Organization Diagnosis：现有组织是否覆盖目标。\n"
            "2. Proposed Changes：建议新增/调整/归档的 agent、原因和风险。\n"
            "3. Communication Edges：建议允许哪些消息类型、意图和唤醒策略。\n"
            "4. User Approval Items：必须由用户确认后才能应用的动作。\n\n"
            "## 禁止\n"
            "- 不要提出没有职责边界的 Agent。\n"
            "- 不要在已有同名/同 roleKey pending create_agent proposal 时重复创建；先复用并等待或应用该 proposal。\n"
            "- 不要对尚未生成的 Agent 配置权限或通信边；遇到 agent_not_found/target_not_found 时先回到 proposal apply。\n"
            "- 不要默认授予写权限、网络权限或高风险工具。\n"
            "- 不要删除历史组织信息；归档优先于不可恢复删除。"
        ),
        "metadata": {"builtin": True, "roleKey": "research_organization_advisor"},
    },
    {
        "templateId": "prompt-research-capability-steward",
        "name": "Research capability steward",
        "category": "research",
        "sourcePath": "workspace/prompts/research/capability_steward.md",
        "content": (
            "# 科研能力管家 agent 默认提示词\n\n"
            "你是 Vibelution 科研组织中的“能力管家 agent”。你的职责是统一管理科研 Agent 的提示词、工具权限和记忆策略，"
            "让组织能随任务动态调整能力，同时避免权限过宽、职责重叠和记忆污染。\n\n"
            "## 工作策略\n"
            "- 先判断任务需要哪些能力，再映射到提示词、工具选择、记忆读写组和通信边。\n"
            "- 对每个 Agent 维护最小职责面：工具可以由 Agent 自主选择，但高风险动作必须说明目的、范围和回滚边界。\n"
            "- 权限扩大、共享记忆写入、提示词重写和人员配置变化必须形成可审查建议；当前用户明确确认某个 pending proposal 后，使用 research_proposal_apply_tool 携带同一个 proposalId 和 user_confirmed=true 应用，再继续后续权限和记忆配置。\n"
            "- 若能力缺口需要新增 Agent，先使用 research_agent_creation_proposal_tool 创建提案；不要对不存在的 Agent 调用权限或通信边工具。\n"
            "- 审查沟通边是否允许正确消息类型和意图，发现缺边、错边或唤醒策略不当时及时上报。\n\n"
            "- 沟通要节制：只在发现能力缺口、完成应用、需要决策、遇到阻塞或交付配置方案时发消息；不要发送只表示“收到/准备中”的消息。\n\n"
            "## 输出要求\n"
            "输出结构化结果：\n"
            "1. Capability Map：当前任务需要的能力、对应 Agent 和缺口。\n"
            "2. Prompt Policy：提示词模板建议、需要修改的边界和风险。\n"
            "3. Tool Plan：建议使用的工具、网络/变更访问和原因。\n"
            "4. Memory Policy：可读/可写记忆组、私有记忆边界和污染风险。\n"
            "5. Approval Items：需要 CEO 或用户确认后才能执行的变更。\n\n"
            "## 禁止\n"
            "- 不要直接执行高风险文件写入、Git、重启或长期自动化；先给出目的、范围和回滚边界。\n"
            "- 不要把不存在于工具注册表的工具写进 Agent 提示词或能力方案。\n"
            "- 不要在 proposal 尚未应用前继续提交权限或通信边变更。\n"
            "- 不要把共享记忆当作所有 Agent 都可写的公共草稿区。\n"
            "- 不要绕过 CEO 或用户确认修改核心 Agent 的职责、权限或提示词。"
        ),
        "metadata": {"builtin": True, "roleKey": "research_capability_steward"},
    },
    {
        "templateId": "prompt-research-broad",
        "name": "Research broad search",
        "category": "research",
        "sourcePath": "workspace/prompts/research/broad.md",
        "content": "# 广撒网探索 agent\n\n用于快速展开研究空间、收集候选线索和发现后续深挖方向。",
        "metadata": {"builtin": True, "roleKey": "research_broad"},
    },
    {
        "templateId": "prompt-research-deep",
        "name": "Research deep search",
        "category": "research",
        "sourcePath": "workspace/prompts/research/deep.md",
        "content": "# 深度研究 agent\n\n用于围绕已选线索做细读、证据归纳和风险核查。",
        "metadata": {"builtin": True, "roleKey": "research_deep"},
    },
    {
        "templateId": "prompt-research-review",
        "name": "Research review",
        "category": "research",
        "sourcePath": "workspace/prompts/research/review.md",
        "content": "# 研究审查 agent\n\n用于复核研究结论、寻找证据缺口和提出反例。",
        "metadata": {"builtin": True, "roleKey": "research_review"},
    },
    {
        "templateId": "prompt-research-themes",
        "name": "Research themes",
        "category": "research",
        "sourcePath": "workspace/prompts/research/themes.md",
        "content": "# 主题生成 agent\n\n用于把候选资料聚类成可执行研究主题。",
        "metadata": {"builtin": True, "roleKey": "research_themes"},
    },
    {
        "templateId": "prompt-research-card",
        "name": "Research card",
        "category": "research",
        "sourcePath": "workspace/prompts/research/card.md",
        "content": "# 主题卡 agent\n\n用于把研究主题整理成结构化卡片。",
        "metadata": {"builtin": True, "roleKey": "research_card"},
    },
    {
        "templateId": "prompt-supervised-baseline",
        "name": "Supervised baseline",
        "category": "supervised_evolution",
        "sourcePath": "",
        "content": (
            "# 监督进化基线 Agent\n\n"
            "你是监督进化链路中的基线 Agent。你的职责是按当前稳定策略完成同一 case，提供可复现、可对照的稳定输出。\n\n"
            "## 行为边界\n"
            "- 严格执行输入 prompt，不改评测标准、不替候选优化、不主动扩大任务。\n"
            "- transaction / full_evolution / modify_rollback case 必须先调用 open_evolution_transaction_tool，再执行检查、验证，最后调用 close_evolution_transaction_tool。\n"
            "- 只有证据和验证明确通过时，close_evolution_transaction_tool 才能使用 status=success；否则按失败或阻塞如实关账。\n"
            "- 不 commit、不 publish、不修改监督评测规则。\n\n"
            "## 证据要求\n"
            "- 记录关键文件、命令、测试和工具结果，保证候选和裁决可以复核。\n"
            "- 如果工具或环境不可用，停止扩散并明确标记 TOOL_UNAVAILABLE 或 ENVIRONMENT_UNAVAILABLE。\n\n"
            "## 输出要求\n"
            "输出基线结果、关键依据、验证结果、事务状态和已知限制。"
        ),
        "metadata": {"builtin": True, "roleKey": "baseline"},
    },
    {
        "templateId": "prompt-supervised-candidate",
        "name": "Supervised candidate",
        "category": "supervised_evolution",
        "sourcePath": "",
        "content": (
            "# 监督进化候选 Agent\n\n"
            "你是监督进化链路中的候选 Agent。你的职责是在同一输入、同一工具边界和同一评价规则下尝试更优策略，并接受基线对照评估。\n\n"
            "## 行为边界\n"
            "- 可以改进执行策略，但不得绕过基线对照、不得修改评测规则、不得隐藏失败或不确定性。\n"
            "- transaction / full_evolution / modify_rollback case 必须先调用 open_evolution_transaction_tool，再执行检查、验证，最后调用 close_evolution_transaction_tool。\n"
            "- 只在证据和验证明确通过时关账为 success；如果改进假设失败，按失败或阻塞如实关账。\n"
            "- 不 commit、不 publish；高风险变更只能作为候选建议，不能宣称已被主线采用。\n\n"
            "## 证据要求\n"
            "- 明确说明相对基线的改进假设、收益、风险和验证证据。\n"
            "- 如果工具或环境不可用，停止扩散并明确标记 TOOL_UNAVAILABLE 或 ENVIRONMENT_UNAVAILABLE。\n\n"
            "## 输出要求\n"
            "输出候选结果、采用策略、验证结果、事务状态、相对基线的预期收益和风险。"
        ),
        "metadata": {"builtin": True, "roleKey": "candidate"},
    },
    {
        "templateId": "prompt-supervised-reviewer",
        "name": "Supervised reviewer",
        "category": "supervised_evolution",
        "sourcePath": "",
        "content": (
            "# 监督进化评审 Agent\n\n"
            "你是监督进化链路中的评审 Agent。你的职责是在被调用时按固定评价维度比较基线和候选输出，给出可追溯的质量判断。\n\n"
            "## 行为边界\n"
            "- 只基于监督运行提供的 case、baseline/candidate 轨迹、报告和证据字段判断。\n"
            "- 先引用具体证据，再给评分或结论；区分确定优势、确定劣势、证据不足和不可判定。\n"
            "- 不替候选执行修复，不调用外部 verifier，不修改文件，不替审计 Agent 判断流程完整性。\n"
            "- 如果 baseline/candidate 的事务链路、验证链路或环境状态缺证据，明确标记证据缺口。\n\n"
            "## 输出要求\n"
            "输出评分维度、证据引用、对比结论、风险和是否建议进入审计/裁决。"
        ),
        "metadata": {"builtin": True, "roleKey": "reviewer"},
    },
    {
        "templateId": "prompt-supervised-auditor",
        "name": "Supervised auditor",
        "category": "supervised_evolution",
        "sourcePath": "",
        "content": (
            "# 监督进化审计 Agent\n\n"
            "你是监督进化链路中的审计 Agent。你的职责是在被调用时检查评测流程、输入输出、证据链和标准一致性是否可信。\n\n"
            "## 行为边界\n"
            "- 优先寻找流程污染、标准漂移、证据缺失和不可复现风险。\n"
            "- 核对 transaction.opened / transaction.closed / transaction.status、验证结果、环境预检、工具轨迹和报告路径是否一致。\n"
            "- 不替评审打分，不调用外部 verifier，不修改文件，不在证据不足时建议通过。\n"
            "- 发现阻塞风险时明确阻塞原因、影响范围和需要补齐的证据。\n\n"
            "## 输出要求\n"
            "输出审计结论、流程风险、证据完整性判断、是否允许进入裁决。"
        ),
        "metadata": {"builtin": True, "roleKey": "auditor"},
    },
    {
        "templateId": "prompt-supervised-judge",
        "name": "Supervised judge",
        "category": "supervised_evolution",
        "sourcePath": "",
        "content": (
            "# 监督进化裁决 Agent\n\n"
            "你是监督进化链路中的裁决 Agent。你的职责是只基于监督运行提供的 case、baseline/candidate 轨迹摘要、报告路径和证据字段，形成候选是否可晋升的最终建议。\n\n"
            "## 行为边界\n"
            "- 不调用 spawn_agent_tool，不派发子 Agent，不调用官方 Harbor/Docker verifier，不修改文件。\n"
            "- 尊重评审证据、审计阻塞和事务/环境状态，不绕过用户确认或高风险门禁。\n"
            "- 明确区分 PROMOTE、HOLD、REJECT、ROLLBACK 和 INCONCLUSIVE；证据不足时必须 INCONCLUSIVE 或 HOLD。\n"
            "- 裁决建议不等于已经应用变更。\n\n"
            "## 输出要求\n"
            "必须输出简短分析，并包含一行 `SUPERVISED_AGENT_JUDGMENT: {...}` JSON，字段至少包括 decision、baseline_score、candidate_score、reason、improvement_summary、risks 和 evidence_refs。"
        ),
        "metadata": {"builtin": True, "roleKey": "judge"},
    },
    {
        "templateId": "prompt-self-executor",
        "name": "Self-evolution executor",
        "category": "self_evolution",
        "sourcePath": "",
        "content": (
            "# 自进化执行 Agent\n\n"
            "你是自进化链路中的执行 Agent。你的职责是把已确认的改进目标推进成可验证结果，并保留过程证据。\n\n"
            "## 行为边界\n"
            "- 只执行已确认目标和范围，不主动扩大变更面。\n"
            "- 每一步都围绕可观察结果、验证证据和阻塞点推进。\n"
            "- 不宣称进化成功，最终质量由评审角色判断。\n\n"
            "## 输出要求\n"
            "输出执行结果、变更范围、验证证据、阻塞点和剩余风险。"
        ),
        "metadata": {"builtin": True, "roleKey": "executor"},
    },
    {
        "templateId": "prompt-self-reviewer",
        "name": "Self-evolution reviewer",
        "category": "self_evolution",
        "sourcePath": "",
        "content": (
            "# 自进化评审 Agent\n\n"
            "你是自进化链路中的评审 Agent。你的职责是检查执行结果是否真正满足目标，并优先发现回归、证据不足和边界破坏。\n\n"
            "## 行为边界\n"
            "- findings 优先，按严重性说明问题和证据。\n"
            "- 区分阻塞问题、可接受风险和后续优化项。\n"
            "- 不替执行者补做工作，不替用户批准高风险变化。\n\n"
            "## 输出要求\n"
            "输出通过/退回结论、问题清单、证据、风险和通过条件。"
        ),
        "metadata": {"builtin": True, "roleKey": "reviewer"},
    },
    {
        "templateId": "prompt-self-summarizer",
        "name": "Self-evolution summarizer",
        "category": "self_evolution",
        "sourcePath": "",
        "content": (
            "# 自进化总结 Agent\n\n"
            "你是自进化链路中的总结 Agent。你的职责是把执行和评审过程压缩成可追踪、可复用的记录。\n\n"
            "## 行为边界\n"
            "- 只记录已发生、已验证或明确标注为推断的内容。\n"
            "- 不扩写不存在的结果，不替评审下结论。\n"
            "- 保留目标、决策、证据、风险和后续动作。\n\n"
            "## 输出要求\n"
            "输出简洁总结、关键决策、验证结果、开放问题和记忆更新建议。"
        ),
        "metadata": {"builtin": True, "roleKey": "summarizer"},
    },
)


def list_prompt_templates(*, include_inactive: bool = False) -> dict[str, Any]:
    """Return the prompt template index with lightweight content metadata."""

    payload = repair_prompt_templates()
    templates = [
        _template_to_api(item, include_content=False)
        for item in payload.get("templates") or []
        if include_inactive or str(item.get("status") or "active").strip() != "inactive"
    ]
    templates.sort(key=lambda item: (str(item.get("category") or ""), str(item.get("templateId") or "")))
    return {
        "schemaVersion": PROMPT_TEMPLATE_INDEX_VERSION,
        "path": str(prompt_template_path()),
        "storagePath": _relative_project_path(prompt_template_path()),
        "templates": templates,
        "repairWarnings": list(payload.get("repairWarnings") or []),
    }


def get_prompt_template(template_id: str) -> dict[str, Any] | None:
    """Return one prompt template with resolved content."""

    normalized = _normalize_template_id(template_id)
    for item in repair_prompt_templates().get("templates") or []:
        if str(item.get("templateId") or "").strip() == normalized:
            return _template_to_api(item, include_content=True)
    return None


def build_agent_prompt_template_context(
    template_id: str,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Build the runtime context block for one Agent prompt template."""

    normalized = str(template_id or "").strip()
    if not normalized:
        return {
            "contextBlock": "",
            "promptTemplateId": "",
            "reason": "missing_template_id",
        }
    template = _get_prompt_template_for_project(normalized, project_root=project_root)
    if not template:
        return {
            "contextBlock": "",
            "promptTemplateId": normalized,
            "reason": "missing_template",
        }
    content = str(template.get("content") or "").strip()
    if not content:
        return {
            "contextBlock": "",
            "promptTemplateId": normalized,
            "sourcePath": str(template.get("sourcePath") or "").strip(),
            "sourceExists": bool(template.get("sourceExists")),
            "reason": "empty_template_content",
        }
    return {
        "contextBlock": "\n".join(
            [
                "## Agent Prompt Template",
                f"PromptTemplateId: {normalized}",
                content,
            ]
        ).strip(),
        "promptTemplateId": normalized,
        "sourcePath": str(template.get("sourcePath") or "").strip(),
        "sourceExists": bool(template.get("sourceExists")),
        "reason": "",
    }


def update_prompt_template(
    template_id: str,
    *,
    name: str | None = None,
    category: str | None = None,
    source_path: str | None = None,
    content: str | None = None,
    metadata: dict[str, Any] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Create or update one prompt template record."""

    normalized = _normalize_template_id(template_id)
    payload = repair_prompt_templates()
    templates = list(payload.get("templates") or [])
    index = next((idx for idx, item in enumerate(templates) if item.get("templateId") == normalized), -1)
    if index < 0:
        templates.append(_normalize_template_record({"templateId": normalized, "name": normalized}))
        index = len(templates) - 1
    record = dict(templates[index])
    if name is not None:
        record["name"] = _trim_text(name, max_chars=120) or normalized
    if category is not None:
        record["category"] = _safe_token(category, fallback="general")
    if source_path is not None:
        record["sourcePath"] = _normalize_source_path(source_path)
    if content is not None:
        record["content"] = _trim_content(content, max_chars=80_000)
        _write_template_source_if_configured(record)
    if metadata is not None:
        record["metadata"] = dict(metadata) if isinstance(metadata, dict) else {}
    if status is not None:
        record["status"] = _normalize_status(status)
    record["updatedAt"] = _now()
    templates[index] = _normalize_template_record(record)
    payload["templates"] = templates
    _save_prompt_templates(payload)
    _record_prompt_template_event("prompt_template.updated", normalized, outcome="updated")
    return _template_to_api(templates[index], include_content=True)


def reset_prompt_template(template_id: str) -> dict[str, Any]:
    """Reset a template to its built-in default record when one exists."""

    normalized = _normalize_template_id(template_id)
    default = _default_template_map().get(normalized)
    if not default:
        raise PromptTemplateError(f"Prompt template has no built-in default: {normalized}")
    payload = repair_prompt_templates()
    templates = [item for item in payload.get("templates") or [] if item.get("templateId") != normalized]
    reset_record = _normalize_template_record(copy.deepcopy(default))
    reset_record["updatedAt"] = _now()
    _write_template_source_if_configured(reset_record)
    templates.append(reset_record)
    payload["templates"] = templates
    _save_prompt_templates(payload)
    _record_prompt_template_event("prompt_template.reset", normalized, outcome="reset")
    return _template_to_api(reset_record, include_content=True)


def repair_prompt_templates() -> dict[str, Any]:
    """Load and repair the prompt template index."""

    payload = _load_prompt_templates()
    templates_by_id = _default_template_map()
    changed = False
    for raw in payload.get("templates") or []:
        if not isinstance(raw, dict):
            changed = True
            continue
        try:
            record = _normalize_template_record(raw)
        except PromptTemplateError:
            changed = True
            continue
        existing = templates_by_id.get(record["templateId"])
        if existing:
            merged = copy.deepcopy(existing)
            merged.update(record)
            merged["metadata"] = {
                **dict(existing.get("metadata") or {}),
                **dict(record.get("metadata") or {}),
            }
            if _should_restore_builtin_content(merged, existing):
                merged["content"] = str(existing.get("content") or "")
            templates_by_id[record["templateId"]] = _normalize_template_record(merged)
        else:
            templates_by_id[record["templateId"]] = record
    next_payload = {
        "schemaVersion": PROMPT_TEMPLATE_INDEX_VERSION,
        "updatedAt": str(payload.get("updatedAt") or _now()),
        "templates": list(templates_by_id.values()),
        "repairWarnings": list(payload.get("repairWarnings") or [])[-50:],
    }
    if payload.get("schemaVersion") != PROMPT_TEMPLATE_INDEX_VERSION:
        changed = True
    if _template_signature(payload.get("templates") or []) != _template_signature(next_payload["templates"]):
        changed = True
    if changed or not prompt_template_path().exists():
        next_payload["updatedAt"] = _now()
        for record in next_payload["templates"]:
            _write_template_source_if_missing(record)
        _save_prompt_templates(next_payload)
        _record_prompt_template_event(
            "prompt_template.repaired",
            "",
            outcome="repaired",
            fields={"templateCount": len(next_payload["templates"])},
        )
    return next_payload


def prompt_template_path() -> Path:
    return PROJECT_ROOT / "workspace" / "agent_config" / "prompt_templates.json"


def _get_prompt_template_for_project(template_id: str, *, project_root: Path | None = None) -> dict[str, Any] | None:
    if project_root is None:
        return get_prompt_template(template_id)
    global PROJECT_ROOT
    previous_root = PROJECT_ROOT
    PROJECT_ROOT = Path(project_root)
    try:
        return get_prompt_template(template_id)
    finally:
        PROJECT_ROOT = previous_root


def _load_prompt_templates() -> dict[str, Any]:
    path = prompt_template_path()
    if not path.exists():
        return {"schemaVersion": PROMPT_TEMPLATE_INDEX_VERSION, "templates": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": PROMPT_TEMPLATE_INDEX_VERSION, "templates": []}
    return payload if isinstance(payload, dict) else {"schemaVersion": PROMPT_TEMPLATE_INDEX_VERSION, "templates": []}


def _save_prompt_templates(payload: dict[str, Any]) -> None:
    data = {
        "schemaVersion": PROMPT_TEMPLATE_INDEX_VERSION,
        "updatedAt": _now(),
        "templates": [_normalize_template_record(item) for item in payload.get("templates") or [] if isinstance(item, dict)],
        "repairWarnings": list(payload.get("repairWarnings") or [])[-50:],
    }
    _atomic_write_json(prompt_template_path(), data)


def _template_to_api(record: dict[str, Any], *, include_content: bool) -> dict[str, Any]:
    content = _resolve_template_content(record)
    source_path = str(record.get("sourcePath") or "").strip()
    source_exists = _source_exists(source_path)
    payload = {
        "templateId": str(record.get("templateId") or "").strip(),
        "promptTemplateId": str(record.get("templateId") or "").strip(),
        "name": str(record.get("name") or "").strip(),
        "category": str(record.get("category") or "general").strip(),
        "sourcePath": source_path,
        "sourceExists": source_exists,
        "status": str(record.get("status") or "active").strip(),
        "metadata": dict(record.get("metadata") or {}),
        "contentLength": len(content),
        "contentHash": _content_hash(content),
        "contentPreview": _trim_text(content.replace("\r\n", "\n"), max_chars=240),
        "content": content if include_content else "",
        "createdAt": str(record.get("createdAt") or "").strip(),
        "updatedAt": str(record.get("updatedAt") or "").strip(),
    }
    return payload


def _resolve_template_content(record: dict[str, Any]) -> str:
    if "content" in record:
        return str(record.get("content") or "")
    source_path = str(record.get("sourcePath") or "").strip()
    if not source_path:
        return ""
    try:
        path = _resolve_project_path(source_path)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception:
        _record_prompt_template_event(
            "prompt_template.missing_source",
            str(record.get("templateId") or ""),
            level="warning",
            outcome="missing_source",
            fields={"sourcePath": source_path},
        )
    return ""


def _normalize_template_record(raw: dict[str, Any]) -> dict[str, Any]:
    template_id = _normalize_template_id(raw.get("templateId") or raw.get("id"))
    now = _now()
    record = {
        "templateId": template_id,
        "name": _trim_text(raw.get("name") or template_id, max_chars=120) or template_id,
        "category": _safe_token(raw.get("category") or "general", fallback="general"),
        "sourcePath": _normalize_source_path(raw.get("sourcePath") or ""),
        "status": _normalize_status(raw.get("status") or "active"),
        "metadata": dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {},
        "createdAt": str(raw.get("createdAt") or now).strip(),
        "updatedAt": str(raw.get("updatedAt") or now).strip(),
    }
    if "content" in raw:
        record["content"] = _trim_content(raw.get("content") or "", max_chars=80_000)
    return record


def _should_restore_builtin_content(record: dict[str, Any], default: dict[str, Any]) -> bool:
    if not str(default.get("content") or "").strip():
        return False
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    default_metadata = default.get("metadata") if isinstance(default.get("metadata"), dict) else {}
    if not bool(metadata.get("builtin") or default_metadata.get("builtin")):
        return False
    return not str(record.get("content") or "").strip()


def _write_template_source_if_configured(record: dict[str, Any]) -> None:
    source_path = str(record.get("sourcePath") or "").strip()
    if not source_path:
        return
    path = _resolve_project_path(source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(record.get("content") or ""), encoding="utf-8", newline="\n")


def _write_template_source_if_missing(record: dict[str, Any]) -> None:
    source_path = str(record.get("sourcePath") or "").strip()
    if not source_path or "content" not in record:
        return
    path = _resolve_project_path(source_path)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(record.get("content") or ""), encoding="utf-8", newline="\n")


def _source_exists(source_path: str) -> bool:
    if not source_path:
        return False
    try:
        return _resolve_project_path(source_path).is_file()
    except PromptTemplateError:
        return False


def _content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()


def _normalize_template_id(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized or not PROMPT_TEMPLATE_ID_PATTERN.fullmatch(normalized):
        raise PromptTemplateError("Invalid prompt template id.")
    return normalized


def _normalize_source_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    _resolve_project_path(raw)
    return raw


def _resolve_project_path(value: str) -> Path:
    root = Path(PROJECT_ROOT).resolve()
    candidate = (root / value).resolve()
    if candidate != root and root not in candidate.parents:
        raise PromptTemplateError("Prompt template source path must stay inside the project.")
    return candidate


def _default_template_map() -> dict[str, dict[str, Any]]:
    return {
        str(item["templateId"]): _normalize_template_record(copy.deepcopy(item))
        for item in DEFAULT_PROMPT_TEMPLATES
    }


def _template_signature(templates: list[Any]) -> list[tuple[str, str, str, str]]:
    signature: list[tuple[str, str, str, str]] = []
    for item in templates:
        if isinstance(item, dict):
            signature.append(
                (
                    str(item.get("templateId") or ""),
                    str(item.get("name") or ""),
                    str(item.get("category") or ""),
                    str(item.get("sourcePath") or ""),
                )
            )
    return sorted(signature)


def _safe_token(value: Any, *, fallback: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip().lower()).strip("._-")
    return token or fallback


def _normalize_status(value: Any) -> str:
    normalized = str(value or "active").strip().lower()
    return normalized if normalized in {"active", "inactive"} else "active"


def _trim_text(value: Any, *, max_chars: int) -> str:
    text = str(value or "").strip()
    return text[:max(0, int(max_chars))]


def _trim_content(value: Any, *, max_chars: int) -> str:
    text = str(value or "")
    return text[:max(0, int(max_chars))]


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _relative_project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(PROJECT_ROOT).resolve()).as_posix()
    except ValueError:
        return str(path)


def _record_prompt_template_event(
    event_code: str,
    template_id: str,
    *,
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "agent_configuration",
            "prompt_template",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={"templateId": str(template_id or "").strip(), **dict(fields or {})},
            lifecycle=True,
        )
    except Exception:
        return


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
