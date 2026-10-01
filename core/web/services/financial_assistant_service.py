"""Financial entry projection and provisioning over the native Agent lifecycle.

No private ledger, market feed, alternate transcript, background trading, or
cross-team authority is created here. Existing Agent configuration owns edits.
"""

from __future__ import annotations

import threading

from core.web.services import agent_directory_service as directory
from core.web.services import session_service
from core.web.services import team_knowledge_service as knowledge
from tools.financial_report_tools import financial_report_availability

PROFILE = "financial_assistant_v1"
ROLE = "financial_advisor"
READ_TOOLS = ("financial_report_query_tool", "financial_evidence_search_tool")
READ_POLICY = {
    "allowedTools": list(READ_TOOLS),
    "preferredTools": list(READ_TOOLS),
    "networkAccess": "controlled",
    "mutationAccess": "none",
    "maxCallsPerTurn": 8,
}
_LOCK = threading.RLock()

PERSONA = {
    "personality": "审慎、证据优先，区分已知事实、假设和不确定性。",
    "communicationStyle": "先说明结论和数据时间，再列来源、风险与需要用户确认的信息。",
    "identityNotes": "个人投资研究助手，主要关注 A 股；不代表持牌机构，不承诺收益。",
    "expertise": ["A股财报证据", "个人投资目标澄清", "风险分析"],
}
TASK = {
    "mission": "基于可核验财报证据，为用户提供只读投资研究与风险建议。",
    "responsibilities": "使用财报工具时明确公司证券代码和报告期，保留来源、页码与版本；证据不足则明确说明。",
    "preferredTasks": "财报检索、来源对照、风险因素梳理和投资需求澄清。",
    "avoidTasks": "不得交易、下单、代管账户、承诺收益；不把新闻或模型摘要当公告或财报原文。",
    "constraints": "行情和新闻委派尚未接入，不声称获得实时分钟行情。个人现金流、持仓、目标、投入意愿和风险承受能力未知时不得猜测；不得把这些私密信息发送给搜索工具或公共知识库。",
    "handoffNotes": "财报专库只收经审核的原始 PDF 证据；待审来源和历史生成答案不能作为财报事实。新闻跨团队委派默认关闭，须独立授权。",
    "successCriteria": "证据可回链，时间与局限明确，建议不执行交易。",
    "deliverables": "有来源和风险说明的研究答复。",
    "taskTypes": ["financial_research", "risk_review"],
}


def _agents() -> list[dict]:
    return [
        a
        for a in directory.list_agents(include_archived=True, detail="config")
        if (a.get("metadata") or {}).get("financialAssistantProfile") == PROFILE
    ]


def _project(agent: dict) -> dict:
    agent_id = agent["agentId"]
    active = agent.get("status") == "active"
    valid_profile = (
        agent.get("roleKey") == ROLE and agent.get("primaryMode") == "general"
    )
    setup = (agent.get("metadata") or {}).get("financialAssistantSetup", "pending")
    session_id = str(agent.get("directSessionId") or "")
    verified_session = False
    if active and session_id and valid_profile:
        detail = session_service.get_session_detail(
            session_id,
            message_limit=0,
            transcript_scope="none",
            include_secondary=False,
        )
        verified_session = bool(detail and detail.get("agentId") == agent_id)
    base = None
    if active and valid_profile:
        try:
            base = knowledge.get_financial_knowledge_base(agent_id=agent_id)[
                "knowledgeBase"
            ]
        except knowledge.TeamKnowledgeError:
            pass  # Archived/missing evidence must not break the entire entry projection.
    read_ids = (agent.get("memoryPolicy") or {}).get("readKnowledgeBaseIds") or []
    base_id = str((base or {}).get("scopedKnowledgeBaseId") or "")
    can_read = bool(
        base_id and knowledge.knowledge_base_policy_allows(base_id, read_ids)
    )
    configured = any(
        bool((binding or {}).get("modelId"))
        for binding in (agent.get("llmBindings") or {}).values()
        if isinstance(binding, dict)
    )
    return {
        "agentId": agent_id,
        "displayName": agent["displayName"],
        "agentCode": agent.get("agentCode", ""),
        "status": agent.get("status", ""),
        "setupStatus": setup if valid_profile else "profile_changed",
        "directSessionId": session_id if verified_session and setup == "ready" else "",
        "knowledgeBaseId": base_id,
        "knowledgeReadable": can_read,
        "modelStatus": "configured_unverified" if configured else "not_configured",
        "reportStatus": financial_report_availability()["status"],
        "marketDataStatus": "not_connected",
        "newsDelegationStatus": "disabled",
        "privateLedgerStatus": "not_implemented",
        "tradingEnabled": False,
    }


def list_financial_assistants() -> list[dict]:
    """Read-only projection. Never auto-create or restore Agents, sessions, or bases."""
    return [_project(a) for a in _agents()]


def create_financial_assistant(display_name: str = "炒股智能体") -> dict:
    """Explicit, idempotent project-local setup. Resume only our unfinished setup."""
    name = str(display_name or "").strip()
    if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
        raise directory.AgentDirectoryError("请输入 1–80 字的单行名称。")
    with _LOCK:
        matches = _agents()
        if len(matches) > 1:
            raise directory.AgentStateConflictError(
                "多个金融助手需要先在 Agent 管理中核对。"
            )
        created = not matches
        agent = (
            matches[0]
            if matches
            else directory.create_agent_instance(
                display_name=name,
                primary_mode="general",
                role_key=ROLE,
                prompt_template_id="prompt-chat-default",
                created_by="user_financial_assistant",
                initial_tool_policy=READ_POLICY,
                llm_bindings=session_service.default_session_llm_bindings(),
                metadata={
                    "financialAssistantProfile": PROFILE,
                    "financialAssistantSetup": "pending",
                    "personaProfile": PERSONA,
                    "taskProfile": TASK,
                },
            )
        )
        if agent.get("status") != "active":
            raise directory.AgentStateConflictError(
                "金融助手已归档，请在 Agent 管理中确认是否恢复。"
            )
        if agent.get("roleKey") != ROLE or agent.get("primaryMode") != "general":
            raise directory.AgentStateConflictError(
                "金融助手身份配置已更改，请在 Agent 管理中核对。"
            )
        if (agent.get("metadata") or {}).get("financialAssistantSetup") != "ready":
            base = knowledge.get_financial_knowledge_base(
                agent_id=agent["agentId"], create_if_missing=True
            )["knowledgeBase"]
            directory.update_agent_instance(
                agent["agentId"],
                display_name=name,
                persona_profile=PERSONA,
                task_profile=TASK,
                tool_policy={
                    "allowedTools": list(READ_TOOLS),
                    "preferredTools": list(READ_TOOLS),
                    "networkAccess": "controlled",
                    "mutationAccess": "none",
                    "maxCallsPerTurn": 8,
                },
                memory_policy={
                    "readKnowledgeBaseIds": [base["scopedKnowledgeBaseId"]],
                    "proposeKnowledgeBaseIds": [],
                    "reviewKnowledgeBaseIds": [],
                    "rateKnowledgeBaseIds": [],
                    "readSharedGroups": [],
                    "writeSharedGroups": [],
                },
                delegation_policy={"allowSubagents": False, "allowWakeMessages": False},
            )
            session_service.ensure_agent_direct_session(
                agent_id=agent["agentId"], title=name, created_by="financial_assistant"
            )
            directory.update_agent_instance(
                agent["agentId"], metadata={"financialAssistantSetup": "ready"}
            )
        agent = directory.get_agent(agent["agentId"], include_archived=True)
        return {"created": created, "assistant": _project(agent)}
