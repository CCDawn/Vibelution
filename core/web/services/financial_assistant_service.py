"""Financial entry projection and provisioning over the native Agent lifecycle.

No private ledger, market feed, alternate transcript, background trading, or
cross-team authority is created here. Public news is a same-session reference:
the assistant judges credibility and does not file news as report evidence.
Existing Agent configuration owns edits.
"""

from __future__ import annotations

import threading

from core.web.services import agent_directory_service as directory
from core.web.services import session_service
from core.web.services import team_knowledge_service as knowledge
from tools.financial_report_tools import financial_report_availability

PROFILE = "financial_assistant_v1"
ROLE = "financial_advisor"
_PREVIOUS_READ_TOOLS = (
    "financial_report_query_tool",
    "financial_evidence_search_tool",
)
READ_TOOLS = (*_PREVIOUS_READ_TOOLS, "news_search_tool")
READ_POLICY = {
    "allowedTools": list(READ_TOOLS),
    "preferredTools": list(READ_TOOLS),
    "networkAccess": "controlled",
    "mutationAccess": "none",
    "maxCallsPerTurn": 8,
}
_PREVIOUS_TASK_TEXT = {
    "responsibilities": "使用财报工具时明确公司证券代码和报告期，保留来源、页码与版本；证据不足则明确说明。",
    "preferredTasks": "财报检索、来源对照、风险因素梳理和投资需求澄清。",
    "avoidTasks": "不得交易、下单、代管账户、承诺收益；不把新闻或模型摘要当公告或财报原文。",
    "constraints": "行情和新闻委派尚未接入，不声称获得实时分钟行情。个人现金流、持仓、目标、投入意愿和风险承受能力未知时不得猜测；不得把这些私密信息发送给搜索工具或公共知识库。",
    "handoffNotes": "财报专库只收经审核的原始 PDF 证据；待审来源和历史生成答案不能作为财报事实。新闻跨团队委派默认关闭，须独立授权。",
}
_PREVIOUS_EXPERTISE = ["A股财报证据", "个人投资目标澄清", "风险分析"]
_LOCK = threading.RLock()

PERSONA = {
    "personality": "审慎、证据优先，区分已知事实、假设和不确定性。",
    "communicationStyle": "先说明结论和数据时间，再列来源、风险与需要用户确认的信息。",
    "identityNotes": "个人投资研究助手，主要关注 A 股；不代表持牌机构，不承诺收益。",
    "expertise": [*_PREVIOUS_EXPERTISE, "公开新闻真伪判断"],
}
TASK = {
    "mission": "基于可核验财报证据，为用户提供只读投资研究与风险建议。",
    "responsibilities": "使用财报工具时明确公司证券代码和报告期，保留来源、页码与版本；证据不足则明确说明。公开新闻只作参考，须判断来源是否可信并写明依据。",
    "preferredTasks": "财报检索、来源对照、公开新闻参考、风险因素梳理和投资需求澄清。",
    "avoidTasks": "不得交易、下单、代管账户、承诺收益；不把新闻或模型摘要当公告或财报原文，也不得把新闻写入财报库。",
    "constraints": "公开新闻只作参考，须自行判断真伪；搜索结果标为质量不足时不得引用。不声称获得实时分钟行情。个人现金流、持仓、目标、投入意愿和风险承受能力未知时不得猜测；不得把这些私密信息发送给搜索工具或公共知识库。",
    "handoffNotes": "财报专库只收经审核的原始 PDF 证据；待审来源、新闻摘要和历史生成答案不能作为财报事实。新闻跨团队委派保持关闭，只在本会话检索公开新闻。",
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


def _names(policy: dict, key: str) -> set[str]:
    raw = policy.get(key) or []
    if not isinstance(raw, list):
        return set()
    return {str(item) for item in raw if str(item or "").strip()}


def _grant_news_reference(agent: dict) -> bool:
    """Grant same-session news search only when stage-1 defaults are still untouched."""
    if agent.get("status") != "active":
        return False
    if agent.get("roleKey") != ROLE or agent.get("primaryMode") != "general":
        return False
    if (agent.get("metadata") or {}).get("financialAssistantSetup") != "ready":
        return False
    policy = agent.get("toolPolicy") if isinstance(agent.get("toolPolicy"), dict) else {}
    updates: dict = {}
    if (
        _names(policy, "allowedTools") == set(_PREVIOUS_READ_TOOLS)
        and _names(policy, "preferredTools") == set(_PREVIOUS_READ_TOOLS)
        and "news_search_tool" not in _names(policy, "blockedTools")
        and policy.get("networkAccess") == "controlled"
        and policy.get("mutationAccess") == "none"
    ):
        updates["tool_policy"] = {
            "allowedTools": list(READ_TOOLS),
            "preferredTools": list(READ_TOOLS),
            "blockedTools": list(policy.get("blockedTools") or []),
            "readScopes": list(policy.get("readScopes") or []),
            "writeScopes": list(policy.get("writeScopes") or []),
            "allowedCommandKinds": list(policy.get("allowedCommandKinds") or []),
            "blockedCommandPatterns": list(policy.get("blockedCommandPatterns") or []),
            "networkAccess": "controlled",
            "mutationAccess": "none",
            "maxCallsPerTurn": policy.get("maxCallsPerTurn", 8),
            "maxCallsPerTurnByModelFamily": dict(
                policy.get("maxCallsPerTurnByModelFamily") or {}
            ),
            "perToolRules": dict(policy.get("perToolRules") or {}),
        }
    task = agent.get("taskProfile") if isinstance(agent.get("taskProfile"), dict) else {}
    task_changes = {
        key: TASK[key]
        for key, previous in _PREVIOUS_TASK_TEXT.items()
        if task.get(key) == previous
    }
    if task_changes:
        updates["task_profile"] = {**task, **task_changes}
    persona = (
        agent.get("personaProfile") if isinstance(agent.get("personaProfile"), dict) else {}
    )
    if list(persona.get("expertise") or []) == _PREVIOUS_EXPERTISE:
        updates["persona_profile"] = {
            **persona,
            "expertise": list(PERSONA["expertise"]),
        }
    if not updates:
        return False
    directory.update_agent_instance(agent["agentId"], **updates)
    return True


def list_financial_assistants() -> list[dict]:
    """Project assistants. Never create or restore Agents, sessions, or bases.

    An untouched stage-1 tool list gains same-session news search. Cleared or
    customized policies stay as the user left them.
    """
    with _LOCK:
        for agent in _agents():
            _grant_news_reference(agent)
        return [_project(agent) for agent in _agents()]


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
        else:
            _grant_news_reference(agent)
        agent = directory.get_agent(agent["agentId"], include_archived=True)
        return {"created": created, "assistant": _project(agent)}
