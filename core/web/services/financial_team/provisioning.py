"""Provision a bounded analyst Team from the current financial assistant."""

from __future__ import annotations

import copy
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.infrastructure.file_lock import cross_process_file_lock
from core.web.services import agent_directory_service as directory
from core.web.services import financial_assistant_service as assistant_service
from core.web.services import session_service, team_service
from core.web.services.session import directory_runtime
from core.web.services.team import role_definition_service

PROFILE_VERSION = 1
TEAM_PURPOSE_PREFIX = "financial-stock-agent-team-v1"
AGENT_MARKER = "financialAnalysisTeam"
# Unified team format identity (docs/standards/unified-team-format.md §2):
# workflow-owned stock research teams are explicit records, not inferred
# customs. The purpose prefix stays the business identity; these fields make
# the team kind/source machine-checkable (kind_helpers.team_is_system_managed).
FINANCIAL_TEAM_KIND = "financial"
FINANCIAL_TEAM_SOURCE = "financial"
FINANCIAL_TEAM_CATEGORY = "股票研究团队"
# Role declarations live in the workspace role file layer (unified format §5);
# builtin content ships under core/web/services/team/role_definitions/*.md.
FINANCIAL_ROLE_KEYS = {
    "market": "financial_market",
    "fundamental": "financial_fundamental",
    "news": "financial_news",
    "bull": "financial_bull",
    "bear": "financial_bear",
}
_LOCK = threading.RLock()


class FinancialTeamError(ValueError):
    """Base error for the financial analysis Team adapter."""


class FinancialTeamNotFoundError(FinancialTeamError):
    pass


class FinancialTeamConflictError(FinancialTeamError):
    pass


_RESTRICTED_MEMORY_ACL_FIELDS = (
    "readSharedGroups",
    "writeSharedGroups",
    "readKnowledgeBaseIds",
    "proposeKnowledgeBaseIds",
    "reviewKnowledgeBaseIds",
    "rateKnowledgeBaseIds",
)


def _native_direct_session_matches_agent(agent_id: str, session_id: str) -> bool:
    """Require an active native transcript and directory row owned by this Agent."""
    normalized_agent_id = str(agent_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_agent_id or not normalized_session_id:
        return False
    try:
        runtime_row = session_service.load_session_chat_state(
            session_service.PROJECT_ROOT,
            normalized_session_id,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    if not isinstance(runtime_row, dict):
        return False
    runtime_agent_id = str(
        runtime_row.get("agent_id") or runtime_row.get("agentId") or ""
    ).strip()
    archive_state = runtime_row.get("archive_state") or runtime_row.get("archiveState")
    archive_state = archive_state if isinstance(archive_state, dict) else {}
    if (
        runtime_agent_id != normalized_agent_id
        or str(
            runtime_row.get("session_kind") or runtime_row.get("sessionKind") or "main"
        )
        .strip()
        .lower()
        != "main"
        or str(archive_state.get("status") or "").strip().lower() == "archived"
        or bool(runtime_row.get("read_only") or runtime_row.get("readOnly"))
    ):
        return False
    store = directory_runtime.get_open_directory_store()
    if store is None:
        return False
    store_project_root = directory_runtime.directory_store_project_root()
    try:
        if (
            store_project_root is None
            or Path(store_project_root).resolve()
            != Path(session_service.PROJECT_ROOT).resolve()
        ):
            return False
    except (OSError, TypeError, ValueError):
        return False
    try:
        directory_row = store.repository.get_session(normalized_session_id)
    except (sqlite3.Error, OSError, RuntimeError, TypeError, ValueError):
        return False
    return bool(
        isinstance(directory_row, dict)
        and str(
            directory_row.get("agentId") or directory_row.get("agent_id") or ""
        ).strip()
        == normalized_agent_id
        and directory_row.get("archivedAtMs") is None
    )


def _native_owner_scoped_synthesis_session_matches_agent(
    agent_id: str, session_id: str, binding_key: str
) -> bool:
    """Require a live Native Session created for this owner's exact financial run."""
    normalized_agent_id = str(agent_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_binding_key = str(binding_key or "").strip()
    if (
        not normalized_agent_id
        or not normalized_session_id
        or not normalized_binding_key
        or not _native_direct_session_matches_agent(
            normalized_agent_id, normalized_session_id
        )
    ):
        return False
    try:
        conversation = session_service.load_session_chat_state(
            session_service.PROJECT_ROOT,
            normalized_session_id,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    if not isinstance(conversation, dict):
        return False
    metadata = conversation.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    conversation_kind = str(
        conversation.get("conversation_index_kind")
        or conversation.get("conversationIndexKind")
        or ""
    ).strip().lower()
    session_role = str(
        conversation.get("session_role") or conversation.get("sessionRole") or ""
    ).strip().lower()
    return bool(
        str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        == normalized_agent_id
        and session_role == "workspace"
        # Existing runs may still point at hidden sessions created before the
        # owner-scoped visible summary was introduced. Keep those bindings
        # recoverable while new runs use the personal Agent index kind.
        and conversation_kind
        in {
            directory.CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
            directory.CONVERSATION_INDEX_KIND_HIDDEN,
        }
        and str(metadata.get("source") or "").strip()
        == "financial_team_synthesis"
        and str(metadata.get("externalTaskId") or "").strip()
        == normalized_binding_key
    )


def _native_session_model_is_executable(agent_id: str, session_id: str) -> bool:
    """Require the session's bound model and context window to pass Native gates."""
    normalized_agent_id = str(agent_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_agent_id or not normalized_session_id:
        return False
    if not _native_direct_session_matches_agent(
        normalized_agent_id, normalized_session_id
    ):
        return False
    try:
        options = session_service.get_session_llm_options(normalized_session_id)
        if (
            not isinstance(options, dict)
            or str(options.get("sessionId") or "").strip()
            != normalized_session_id
        ):
            return False
        model_ref = str(options.get("currentModelId") or "").strip()
        if not model_ref:
            return False
        choices = (
            options.get("choices")
            if isinstance(options.get("choices"), list)
            else []
        )
        candidate = next(
            (
                item
                for item in choices
                if isinstance(item, dict)
                and model_ref
                in {
                    str(item.get("modelRef") or "").strip(),
                    str(item.get("modelId") or "").strip(),
                }
            ),
            None,
        )
        if not isinstance(candidate, dict):
            return False
        if (
            candidate.get("runtimeSelectable") is not True
            or candidate.get("providerHealthy") is not True
            or candidate.get("missingApiKey") is not False
        ):
            return False
        try:
            candidate_context_window = int(candidate.get("contextWindow") or 0)
        except (TypeError, ValueError):
            return False
        if candidate_context_window <= 0:
            return False

        conversation = session_service.load_session_chat_state(
            session_service.PROJECT_ROOT,
            normalized_session_id,
        )
        if not isinstance(conversation, dict):
            return False
        context_limit = session_service._session_context_limit_payload(conversation)
        return (
            isinstance(context_limit, dict)
            and int(context_limit.get("limit") or 0) > 0
        )
    except Exception:  # noqa: BLE001 - readiness is fail-closed on Native lookup errors
        return False


def _role_memory_policy_is_restricted(agent: dict[str, Any]) -> bool:
    policy = agent.get("memoryPolicy")
    if not isinstance(policy, dict):
        return False
    for field in _RESTRICTED_MEMORY_ACL_FIELDS:
        values = policy.get(field)
        if not isinstance(values, list) or any(
            str(value or "").strip() for value in values
        ):
            return False
    return True


ROLE_SPECS: dict[str, dict[str, Any]] = {
    "market": {
        "label": "行情分析",
        "teamRole": "行情分析师",
        "requiredTools": ["financial_market_snapshot_tool"],
        "task": {
            "mission": "分析指定 A 股的公开行情与价格走势。",
            "responsibilities": "查询指定证券代码的最新公开行情和日、周或月 K 线；标明行情时间、来源、复权与单位；数据不可用时明确说明。",
            "preferredTasks": "公开行情、K 线和价格变化分析。",
            "avoidTasks": "不得编造报价、交易信号或下单建议；不得把查询时间当成行情时间。",
            "constraints": "只能研究公开行情；不得声称持有实时分钟数据；不得执行交易。",
            "successCriteria": "结论可追溯到行情来源与报价时间。",
            "deliverables": "行情事实、走势观察和数据限制。",
            "taskTypes": ["financial_research"],
        },
        "expertise": ["A 股公开行情", "K 线与价格走势"],
    },
    "fundamental": {
        "label": "基本面研究",
        "teamRole": "基本面分析师",
        "requiredTools": ["financial_report_query_tool"],
        "task": {
            "mission": "基于可核验的财报数据分析指定 A 股基本面。",
            "responsibilities": "查询指定公司的公开财报数据，标明报告期、单位、来源和缺失字段；只依据工具返回的数据作判断。",
            "preferredTasks": "营收、利润、现金流、偿债能力和财报趋势分析。",
            "avoidTasks": "不得把模型记忆或新闻摘要当作财报事实；不得补造缺失数据或承诺收益。",
            "constraints": "只读取主金融助手已授权工具的子集；证据不足时明确写出，不得访问其他 Agent 的私有知识库。",
            "successCriteria": "基本面结论带有报告期、单位和来源，缺口清楚。",
            "deliverables": "财报数据、趋势判断和证据缺口。",
            "taskTypes": ["financial_research", "risk_review"],
        },
        "expertise": ["A 股财报", "基本面分析"],
    },
    "news": {
        "label": "新闻分析",
        "teamRole": "新闻分析师",
        "requiredTools": ["news_search_tool"],
        "task": {
            "mission": "查找并评估指定 A 股近期公开新闻线索。",
            "responsibilities": "检索近期公开新闻，逐条标明发布时间、来源与链接；区分新闻事实、媒体判断和未证实说法。",
            "preferredTasks": "公司公告线索、行业动态和公开新闻可信度判断。",
            "avoidTasks": "不得把新闻或模型摘要作为财报原始证据，不得隐去过期或质量不足标记。",
            "constraints": "新闻只作参考；搜索结果不足或来源质量低时明确说明，不得写入财报证据库。",
            "successCriteria": "每条线索有来源和时间，并标出可信度限制。",
            "deliverables": "近期新闻线索、影响方向与可信度风险。",
            "taskTypes": ["financial_research", "risk_review"],
        },
        "expertise": ["公开新闻检索", "信息来源核验"],
    },
    "bull": {
        "label": "乐观研究",
        "teamRole": "乐观研究员",
        "requiredTools": [],
        "task": {
            "mission": "基于本轮行情、基本面与新闻分析师的原生完成回答，提出可被证据支持的乐观情景。",
            "responsibilities": "检查正向证据、成立条件、潜在催化和可观察触发条件；逐项指出证据来源与日期，并明确反证和失效条件。",
            "preferredTasks": "独立构建有条件的上行情景并检验其证据质量。",
            "avoidTasks": "不得把材料中的推测升级为事实，不得补造数据、价格目标或收益承诺。",
            "constraints": "只使用本轮提供的三位分析师完成回答及明确标注的公开指标；不调用其他 Agent 私有数据，不假装执行过未提供的工具。",
            "successCriteria": "每条乐观论点都能定位到来源、时间或明确标注为假设，并给出失效条件。",
            "deliverables": "有证据的乐观情景、触发条件、反证和失效条件。",
            "taskTypes": ["financial_research", "risk_review"],
        },
        "expertise": ["情景分析", "证据反证与条件判断"],
    },
    "bear": {
        "label": "审慎研究",
        "teamRole": "审慎研究员",
        "requiredTools": [],
        "task": {
            "mission": "基于本轮行情、基本面与新闻分析师的原生完成回答，检验下行情景和关键脆弱点。",
            "responsibilities": "识别负面证据、数据缺口、来源质量问题和假设风险；逐项指出来源与日期，并说明风险触发与失效条件。",
            "preferredTasks": "独立构建下行情景、证据反驳和风险边界。",
            "avoidTasks": "不得为了唱空而制造事实，不得把未证实说法当成证据，不得给出确定损失预测。",
            "constraints": "只使用本轮提供的三位分析师完成回答及明确标注的公开指标；不调用其他 Agent 私有数据，不假装执行过未提供的工具。",
            "successCriteria": "风险论点能定位到来源、时间或明确标注为假设，并说明其触发和失效条件。",
            "deliverables": "有证据的下行情景、主要风险、触发条件与反证。",
            "taskTypes": ["financial_research", "risk_review"],
        },
        "expertise": ["下行情景", "风险与证据缺口"],
    },
}


def _agent_config(agent_id: str) -> dict[str, Any] | None:
    normalized = str(agent_id or "").strip()
    if not normalized:
        return None
    state = directory.load_state()
    raw = next(
        (
            item
            for item in state.get("agents", [])
            if isinstance(item, dict)
            and str(item.get("agentId") or "").strip() == normalized
        ),
        None,
    )
    if not isinstance(raw, dict):
        return None
    return directory._agent_to_api(raw, include_activity=False)


def _financial_assistant(agent_id: str) -> dict[str, Any]:
    agent = _agent_config(agent_id)
    if not agent:
        raise FinancialTeamNotFoundError("金融助手不存在")
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if metadata.get("financialAssistantProfile") != assistant_service.PROFILE:
        raise FinancialTeamNotFoundError("该 Agent 不是当前项目的金融助手")
    if (
        agent.get("roleKey") != assistant_service.ROLE
        or agent.get("primaryMode") != "general"
    ):
        raise FinancialTeamConflictError(
            "金融助手身份配置已更改，请先核对 Agent 管理中的配置"
        )
    if agent.get("status") != "active":
        raise FinancialTeamConflictError("金融助手已归档，不能运行分析团队")
    if metadata.get("financialAssistantSetup") != "ready":
        raise FinancialTeamConflictError("请先完成炒股智能体初始化")
    direct_session_id = str(agent.get("directSessionId") or "").strip()
    if not _native_direct_session_matches_agent(
        str(agent.get("agentId") or ""), direct_session_id
    ):
        raise FinancialTeamConflictError(
            "金融助手原生会话不存在、已归档或归属不匹配，请先重新完成助手初始化"
        )
    return agent


def _team_purpose(owner_agent_id: str) -> str:
    return f"{TEAM_PURPOSE_PREFIX}:{owner_agent_id}"


def _read_team(team_id: str) -> dict[str, Any] | None:
    """Read the Team index without invoking the public repair-on-read path."""
    normalized = str(team_id or "").strip()
    if not normalized:
        return None
    state = team_service._load_index()
    return next(
        (
            item
            for item in state.get("teams", [])
            if isinstance(item, dict)
            and str(item.get("teamId") or "").strip() == normalized
        ),
        None,
    )


def _find_team(owner_agent_id: str) -> dict[str, Any] | None:
    """Resolve the owner's analysis team by managed identity first.

    Primary: records already flagged ``teamSource``/``teamKind`` financial.
    Legacy fallback: purpose-prefix equality, so pre-backfill records stay
    recognizable during the migration window.
    """

    purpose = _team_purpose(owner_agent_id)
    state = team_service._load_index()
    purpose_matches = [
        item
        for item in state.get("teams", [])
        if isinstance(item, dict)
        and str(item.get("purpose") or "").strip() == purpose
    ]
    matches = [
        item for item in purpose_matches if _team_identity_is_financial(item)
    ] or purpose_matches
    if len(matches) > 1:
        raise FinancialTeamConflictError(
            "检测到多个同源分析团队，请先在 Team 管理中核对"
        )
    return matches[0] if matches else None


def _team_identity_is_financial(team: dict[str, Any]) -> bool:
    return (
        str(team.get("teamSource") or "").strip() == FINANCIAL_TEAM_SOURCE
        or str(team.get("teamKind") or "").strip() == FINANCIAL_TEAM_KIND
    )


def _is_backfill_candidate(team: dict[str, Any]) -> bool:
    purpose = str(team.get("purpose") or "").strip()
    if purpose.startswith(f"{TEAM_PURPOSE_PREFIX}:"):
        return True
    # Partial identity (one flag set, the other missing) also gets healed.
    return _team_identity_is_financial(team)


def backfill_financial_team_identities() -> dict[str, Any]:
    """Idempotent in-place identity backfill for stock research teams.

    Legacy records are recognized by the business purpose prefix; only the
    contract fields ``teamKind``/``teamCategory``/``teamSource`` are filled —
    ``teamId``/``purpose``/``members`` stay untouched. A second run over
    unchanged data writes nothing (``_apply_team_contract`` reports no
    change, so neither the index nor ``updatedAt`` is touched).
    """

    s = team_service
    backfilled: list[str] = []
    with s._TEAM_LOCK:
        state = s._load_index()
        for team in state.get("teams", []):
            if not isinstance(team, dict) or not _is_backfill_candidate(team):
                continue
            if s._apply_team_contract(
                team,
                team_kind=FINANCIAL_TEAM_KIND,
                team_category=FINANCIAL_TEAM_CATEGORY,
                team_source=FINANCIAL_TEAM_SOURCE,
            ):
                team["updatedAt"] = s.utc_now_iso()
                backfilled.append(str(team.get("teamId") or "").strip())
                s._record_team_event(
                    "team.financial_identity_backfilled",
                    team,
                    fields={"purposePrefix": TEAM_PURPOSE_PREFIX},
                )
        if backfilled:
            state["updatedAt"] = s.utc_now_iso()
            s._save_index(state)
    return {"backfilledTeamCount": len(backfilled), "teamIds": backfilled}


def _role_agents(owner_agent_id: str) -> dict[str, dict[str, Any]]:
    all_agents = directory.load_state().get("agents", [])
    result: dict[str, dict[str, Any]] = {}
    for role in ROLE_SPECS:
        matches = []
        for raw in all_agents:
            if not isinstance(raw, dict):
                continue
            metadata = (
                raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
            )
            marker = (
                metadata.get(AGENT_MARKER)
                if isinstance(metadata.get(AGENT_MARKER), dict)
                else {}
            )
            if (
                marker.get("ownerAgentId") == owner_agent_id
                and marker.get("role") == role
            ):
                matches.append(raw)
        if len(matches) > 1:
            raise FinancialTeamConflictError(
                f"检测到多个{ROLE_SPECS[role]['label']} Agent，请先核对配置"
            )
        if matches:
            result[role] = directory._agent_to_api(matches[0], include_activity=False)
    return result


def _tool_names(policy: dict[str, Any], key: str) -> set[str]:
    value = policy.get(key)
    if not isinstance(value, list):
        return set()
    return {str(item).strip() for item in value if str(item or "").strip()}


def _role_tool_policy(owner_policy: dict[str, Any], role: str) -> dict[str, Any]:
    required = set(ROLE_SPECS[role]["requiredTools"])
    allowed_by_owner = _tool_names(owner_policy, "allowedTools")
    blocked_by_owner = _tool_names(owner_policy, "blockedTools")
    if not required.issubset(allowed_by_owner) or required.intersection(
        blocked_by_owner
    ):
        raise FinancialTeamConflictError(
            f"主助手没有授权{ROLE_SPECS[role]['label']}所需的只读工具；团队不会自动扩权"
        )
    allowed = sorted(required.intersection(allowed_by_owner))
    preferred = sorted(
        _tool_names(owner_policy, "preferredTools").intersection(allowed)
    )
    policy = copy.deepcopy(owner_policy)
    policy["allowedTools"] = allowed
    policy["preferredTools"] = preferred or allowed
    policy["blockedTools"] = sorted(blocked_by_owner.intersection(allowed))
    policy["mutationAccess"] = "none"
    return policy


def _expected_role_config(
    owner: dict[str, Any], role: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    owner_policy = (
        owner.get("toolPolicy") if isinstance(owner.get("toolPolicy"), dict) else {}
    )
    return copy.deepcopy(owner.get("llmBindings") or {}), _role_tool_policy(
        owner_policy, role
    )


def _financial_role_definitions() -> dict[str, dict[str, Any]]:
    """Load the financial role declarations through the role file layer.

    Fail closed: a missing or malformed role aborts the operation with a
    locatable conflict instead of materializing a partially declared Agent.
    """

    keys = [FINANCIAL_ROLE_KEYS[role] for role in ROLE_SPECS]
    try:
        definitions = role_definition_service.load_role_definitions(
            keys, project_root=Path(session_service.PROJECT_ROOT)
        )
    except role_definition_service.RoleDefinitionError as exc:
        raise FinancialTeamConflictError(f"金融团队角色定义不可用：{exc}") from exc
    return {role: definitions[index] for index, role in enumerate(ROLE_SPECS)}


def _expected_role_metadata(
    owner: dict[str, Any], role: str, role_definition: dict[str, Any]
) -> dict[str, Any]:
    """Build the managed Agent metadata for one role.

    Persona/task texts come from the role file layer (unified format §5,
    loaded through ``team_format.validate_role_definition``). ``taskTypes``
    stays an Agent-instance-only field fed from the operational spec, and
    ``background`` stays empty so pre-migration role Agents keep comparing
    equal (provisioning stays idempotent for existing deployments).
    """

    spec = ROLE_SPECS[role]
    persona = (
        role_definition.get("personaProfile")
        if isinstance(role_definition.get("personaProfile"), dict)
        else {}
    )
    task = (
        role_definition.get("taskProfile")
        if isinstance(role_definition.get("taskProfile"), dict)
        else {}
    )
    spec_task = spec["task"] if isinstance(spec.get("task"), dict) else {}
    return {
        AGENT_MARKER: {
            "schemaVersion": PROFILE_VERSION,
            "ownerAgentId": str(owner.get("agentId") or ""),
            "role": role,
        },
        "personaProfile": {
            "personality": str(persona.get("personality") or ""),
            "communicationStyle": str(persona.get("communicationStyle") or ""),
            "identityNotes": str(persona.get("identityNotes") or ""),
            "expertise": [
                str(item) for item in list(persona.get("expertise") or [])
            ],
        },
        "taskProfile": {
            **{
                key: str(task.get(key) or "")
                for key in (
                    "mission",
                    "responsibilities",
                    "preferredTasks",
                    "avoidTasks",
                    "successCriteria",
                    "constraints",
                    "deliverables",
                )
            },
            "taskTypes": [
                str(item) for item in list(spec_task.get("taskTypes") or [])
            ],
        },
        "delegationPolicy": {"allowSubagents": False, "allowWakeMessages": False},
    }


def _tool_policy_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    def comparable(value: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(value)
        result.pop("policyId", None)
        result.pop("policyVersion", None)
        for key in ("allowedTools", "preferredTools", "blockedTools"):
            result[key] = sorted(_tool_names(result, key))
        return result

    return comparable(actual) == comparable(expected)


def _role_agent_configuration_is_current(
    owner: dict[str, Any],
    role: str,
    agent: dict[str, Any],
    role_definition: dict[str, Any],
    *,
    expected_team_id: str = "",
    allow_missing_team_marker: bool = False,
) -> bool:
    expected_bindings, expected_policy = _expected_role_config(owner, role)
    actual_policy = (
        agent.get("toolPolicy") if isinstance(agent.get("toolPolicy"), dict) else {}
    )
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    expected_metadata = _expected_role_metadata(owner, role, role_definition)
    actual_marker = (
        metadata.get(AGENT_MARKER)
        if isinstance(metadata.get(AGENT_MARKER), dict)
        else {}
    )
    expected_marker = expected_metadata[AGENT_MARKER]
    marker_team_id = str(actual_marker.get("teamId") or "").strip()
    normalized_team_id = str(expected_team_id or "").strip()
    team_marker_matches = marker_team_id == normalized_team_id or (
        allow_missing_team_marker and not marker_team_id and bool(normalized_team_id)
    )
    expected_persona = directory.normalize_persona_profile(
        expected_metadata["personaProfile"]
    )
    expected_task = directory.normalize_task_profile(expected_metadata["taskProfile"])
    expected_delegation = directory.normalize_delegation_policy(
        expected_metadata["delegationPolicy"]
    )
    return (
        agent.get("status") == "active"
        and agent.get("roleKey") == assistant_service.ROLE
        and agent.get("primaryMode") == "general"
        and agent.get("llmBindings") == expected_bindings
        and all(
            actual_marker.get(key) == value for key, value in expected_marker.items()
        )
        and team_marker_matches
        and agent.get("personaProfile") == expected_persona
        and agent.get("taskProfile") == expected_task
        and directory.normalize_delegation_policy(metadata.get("delegationPolicy"))
        == expected_delegation
        and _tool_policy_matches(actual_policy, expected_policy)
        and _role_memory_policy_is_restricted(agent)
    )


def _role_agent_is_current(
    owner: dict[str, Any],
    role: str,
    agent: dict[str, Any],
    role_definition: dict[str, Any],
    *,
    expected_team_id: str = "",
) -> bool:
    return _role_agent_configuration_is_current(
        owner,
        role,
        agent,
        role_definition,
        expected_team_id=expected_team_id,
    ) and _native_direct_session_matches_agent(
        str(agent.get("agentId") or ""),
        str(agent.get("directSessionId") or ""),
    )


def _project_team(
    owner: dict[str, Any],
    team: dict[str, Any] | None,
    agents: dict[str, dict[str, Any]],
    role_definitions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    owner_id = str(owner.get("agentId") or "").strip()
    owner_metadata = (
        owner.get("metadata") if isinstance(owner.get("metadata"), dict) else {}
    )
    team_marker = (
        owner_metadata.get(AGENT_MARKER)
        if isinstance(owner_metadata.get(AGENT_MARKER), dict)
        else {}
    )
    team_id = str((team or {}).get("teamId") or team_marker.get("teamId") or "").strip()
    team_members = {
        str(member.get("agentId") or "").strip()
        for member in (team or {}).get("members", [])
        if isinstance(member, dict)
    }
    roles = []
    assistant_session_id = str(owner.get("directSessionId") or "").strip()
    assistant_model_ready = _native_session_model_is_executable(
        owner_id, assistant_session_id
    )
    attention = not assistant_model_ready
    for role, spec in ROLE_SPECS.items():
        agent = agents.get(role)
        session_id = str((agent or {}).get("directSessionId") or "").strip()
        ready = bool(
            agent
            and _role_agent_configuration_is_current(
                owner,
                role,
                agent,
                role_definitions[role],
                expected_team_id=team_id,
            )
            and agent.get("agentId") in team_members
            and session_id
            and _native_session_model_is_executable(
                str(agent.get("agentId") or ""), session_id
            )
        )
        attention = attention or bool(agent and not ready)
        roles.append(
            {
                "role": role,
                "label": spec["label"],
                "agentId": str((agent or {}).get("agentId") or ""),
                "sessionId": str((agent or {}).get("directSessionId") or ""),
                "status": "ready"
                if ready
                else ("needs_attention" if agent else "not_created"),
                "allowedTools": sorted(
                    _tool_names((agent or {}).get("toolPolicy") or {}, "allowedTools")
                ),
            }
        )
    is_team_active = bool(team and str(team.get("status") or "active") == "active")
    complete = (
        len(agents) == len(ROLE_SPECS)
        and assistant_model_ready
        and all(role["status"] == "ready" for role in roles)
        and is_team_active
    )
    status = (
        "ready"
        if complete
        else (
            "needs_attention"
            if attention or team_id and not is_team_active
            else "needs_setup"
        )
    )
    return {
        "assistantAgentId": owner_id,
        "assistantSessionId": str(owner.get("directSessionId") or ""),
        "teamId": team_id,
        "status": status,
        "roles": roles,
        "modelBindings": copy.deepcopy(owner.get("llmBindings") or {}),
        "assistantConfigRevision": int(owner.get("configRevision") or 0),
    }


def get_financial_team(assistant_agent_id: str) -> dict[str, Any]:
    """Read setup state only. It never provisions Agents or advances a run."""
    owner = _financial_assistant(assistant_agent_id)
    agents = _role_agents(str(owner["agentId"]))
    backfill_financial_team_identities()
    team = _find_team(str(owner["agentId"]))
    return _project_team(owner, team, agents, _financial_role_definitions())


@contextmanager
def _provision_lock(owner: dict[str, Any]) -> Iterator[None]:
    owner_id = str(owner.get("agentId") or "").strip()
    territory = directory.resolve_agent_workspace_territory(owner_id)
    private_root = str(territory.get("privateRoot") or "").strip()
    if not private_root or not directory._is_agent_private_workspace_path(
        private_root, owner_id
    ):
        raise FinancialTeamConflictError("金融助手私有工作区不可用，团队初始化已停止")
    resolved_root = directory._resolve_project_path(private_root)
    lock_path = resolved_root / "artifacts" / "financial-team" / "provision.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with cross_process_file_lock(
        lock_path,
        lock_path=lock_path.with_name(lock_path.name + ".transaction.lock"),
        timeout=30.0,
    ):
        yield


def _new_role_agent(
    owner: dict[str, Any], role: str, role_definition: dict[str, Any]
) -> dict[str, Any]:
    spec = ROLE_SPECS[role]
    bindings, policy = _expected_role_config(owner, role)
    display_name = (
        f"{str(owner.get('displayName') or '炒股智能体').strip()} · {spec['label']}"
    )
    metadata = _expected_role_metadata(owner, role, role_definition)
    agent = directory.create_agent_instance(
        display_name=display_name,
        llm_bindings=bindings,
        primary_mode="general",
        role_key=assistant_service.ROLE,
        prompt_template_id="prompt-chat-default",
        created_by="financial_analysis_team",
        metadata=metadata,
        initial_tool_policy=policy,
    )
    session_service.ensure_agent_direct_session(
        agent_id=str(agent.get("agentId") or ""),
        title=display_name,
        created_by="financial_analysis_team",
    )
    refreshed = _agent_config(str(agent.get("agentId") or ""))
    if not refreshed or not _native_direct_session_matches_agent(
        str(agent.get("agentId") or ""),
        str(refreshed.get("directSessionId") or ""),
    ):
        raise FinancialTeamConflictError(f"{spec['label']}原生会话初始化未通过归属检查")
    return refreshed


def _team_members(agents: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Materialize member rows through the single normalization exit.

    The unified-format member row is the 8-field shape produced by
    ``team_service._normalize_members`` (unified-team-format.md §3); raw
    drafts only carry the binding identity (agentId/role/purpose).
    """

    rows = [
        {
            "agentId": str(agents[role]["agentId"]),
            "role": str(ROLE_SPECS[role]["teamRole"]),
            "purpose": str(ROLE_SPECS[role]["label"]),
        }
        for role in ROLE_SPECS
    ]
    return team_service._normalize_members(rows, require_active=True)


def _append_missing_team_members(
    team_id: str, additions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Append provisioning-owned member rows without the operator PATCH path.

    Financial teams are system-managed, so ``update_team`` rejects operator
    edits; the provisioning workflow still owns this roster repair. The write
    mirrors ``update_team``'s member path: locked index mutation, join guard,
    direct session bootstrap, chat room link and canvas refresh.
    """

    s = team_service
    normalized = s._normalize_members(additions, require_active=True)
    with s._TEAM_LOCK:
        state = s._load_index()
        team = s._find_team(state, team_id)
        if team is None:
            raise FinancialTeamConflictError("股票分析团队不存在，无法补齐成员")
        if str(team.get("status") or "active") != "active":
            raise FinancialTeamConflictError(
                "股票分析团队已归档，请先在 Team 管理中核对"
            )
        existing_ids = {
            str(item.get("agentId") or "").strip()
            for item in list(team.get("members") or [])
            if isinstance(item, dict)
        }
        pending = [
            item
            for item in normalized
            if str(item.get("agentId") or "").strip() not in existing_ids
        ]
        if pending:
            s._ensure_members_can_join_team(pending, state, team_id)
            team["members"] = [*list(team.get("members") or []), *pending]
            now = s.utc_now_iso()
            team["updatedAt"] = now
            state["updatedAt"] = now
            s._save_index(state)
    if not pending:
        return team
    s._ensure_active_member_direct_sessions(team)
    s._ensure_team_chat_room_link(team)
    with s._TEAM_LOCK:
        state = s._load_index()
        stored = s._find_team(state, team_id)
        if stored is not None:
            stored["linkedChatRoomId"] = str(team.get("linkedChatRoomId") or "").strip()
            stored["updatedAt"] = s.utc_now_iso()
            state["updatedAt"] = stored["updatedAt"]
            s._save_index(state)
            team = stored
    s._sync_team_canvas_membership(team)
    s._record_team_event(
        "team.financial_members_repaired",
        team,
        fields={"addedMemberCount": len(pending)},
    )
    return team


def provision_financial_team(assistant_agent_id: str) -> dict[str, Any]:
    """Explicit, idempotent setup. Existing user-edited role Agents fail closed."""
    owner = _financial_assistant(assistant_agent_id)
    with _LOCK, _provision_lock(owner):
        owner = _financial_assistant(assistant_agent_id)
        role_definitions = _financial_role_definitions()
        role_agents = _role_agents(str(owner["agentId"]))
        backfill_financial_team_identities()
        raw_team = _find_team(str(owner["agentId"]))
        expected_team_id = str((raw_team or {}).get("teamId") or "").strip()
        owner_metadata = (
            owner.get("metadata") if isinstance(owner.get("metadata"), dict) else {}
        )
        owner_marker = (
            owner_metadata.get(AGENT_MARKER)
            if isinstance(owner_metadata.get(AGENT_MARKER), dict)
            else {}
        )
        team_marker_incomplete = bool(
            expected_team_id
            and str(owner_marker.get("teamId") or "").strip() != expected_team_id
        )
        for role in ROLE_SPECS:
            if role not in role_agents:
                role_agents[role] = _new_role_agent(
                    owner, role, role_definitions[role]
                )
            elif not _role_agent_configuration_is_current(
                owner,
                role,
                role_agents[role],
                role_definitions[role],
                expected_team_id=expected_team_id,
                allow_missing_team_marker=team_marker_incomplete,
            ):
                raise FinancialTeamConflictError(
                    f"{ROLE_SPECS[role]['label']} Agent 配置已变更，团队不会覆盖人工调整；请在 Agent 管理中核对"
                )
            elif not _native_direct_session_matches_agent(
                str(role_agents[role].get("agentId") or ""),
                str(role_agents[role].get("directSessionId") or ""),
            ):
                if str(role_agents[role].get("directSessionId") or "").strip():
                    raise FinancialTeamConflictError(
                        f"{ROLE_SPECS[role]['label']}原生会话已归档、缺失或归属变化，请先在 Agent 管理中核对"
                    )
                session_service.ensure_agent_direct_session(
                    agent_id=str(role_agents[role].get("agentId") or ""),
                    title=f"{str(owner.get('displayName') or '炒股智能体').strip()} · {ROLE_SPECS[role]['label']}",
                    created_by="financial_analysis_team",
                )
                refreshed = _agent_config(str(role_agents[role].get("agentId") or ""))
                if (
                    not refreshed
                    or not _role_agent_configuration_is_current(
                        owner,
                        role,
                        refreshed,
                        role_definitions[role],
                        expected_team_id=expected_team_id,
                        allow_missing_team_marker=team_marker_incomplete,
                    )
                    or not _native_direct_session_matches_agent(
                        str(refreshed.get("agentId") or ""),
                        str(refreshed.get("directSessionId") or ""),
                    )
                ):
                    raise FinancialTeamConflictError(
                        f"{ROLE_SPECS[role]['label']}原生会话中断恢复失败，请核对配置"
                    )
                role_agents[role] = refreshed

        purpose = _team_purpose(str(owner["agentId"]))
        members = _team_members(role_agents)
        if raw_team is None:
            team = team_service.create_team(
                name=f"{str(owner.get('displayName') or '炒股智能体').strip()} · 分析团队",
                description="由真实原生 Agent 和各自原生 Session 组成的股票研究团队。",
                purpose=purpose,
                members=members,
                team_kind=FINANCIAL_TEAM_KIND,
                team_category=FINANCIAL_TEAM_CATEGORY,
                team_source=FINANCIAL_TEAM_SOURCE,
            )
        else:
            team_id = str(raw_team.get("teamId") or "").strip()
            team = team_service.get_team(team_id)
            if str(team.get("status") or "active") != "active":
                raise FinancialTeamConflictError(
                    "股票分析团队已归档，请先在 Team 管理中核对"
                )
            current_members = (
                team.get("members") if isinstance(team.get("members"), list) else []
            )
            current_ids = {
                str(item.get("agentId") or "").strip()
                for item in current_members
                if isinstance(item, dict)
            }
            expected_ids = {str(item["agentId"]) for item in members}
            if current_ids - expected_ids:
                raise FinancialTeamConflictError(
                    "股票分析团队包含未登记的额外成员，初始化不会移除或覆盖他们"
                )
            if current_ids != expected_ids:
                # Workflow-owned roster repair: the operator PATCH lock
                # (team_is_system_managed) must not block the provisioning
                # workflow from re-adding its own members, so this append goes
                # through the locked direct write instead of update_team.
                team = _append_missing_team_members(
                    team_id,
                    [
                        item
                        for item in members
                        if item["agentId"] not in current_ids
                    ],
                )

        team_id = str(team.get("teamId") or "").strip()
        if not team_id:
            raise FinancialTeamConflictError("分析团队创建后没有返回有效 Team ID")
        for role in ROLE_SPECS:
            agent = (
                _agent_config(str(role_agents[role]["agentId"])) or role_agents[role]
            )
            metadata = (
                agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
            )
            marker = (
                metadata.get(AGENT_MARKER)
                if isinstance(metadata.get(AGENT_MARKER), dict)
                else {}
            )
            updated = {**metadata, AGENT_MARKER: {**marker, "teamId": team_id}}
            if updated != metadata:
                directory.update_agent_instance(
                    str(agent["agentId"]),
                    metadata=updated,
                    expected_updated_at=str(agent.get("updatedAt") or ""),
                    expected_config_revision=int(agent.get("configRevision") or 0),
                )
        owner = _agent_config(str(owner["agentId"])) or owner
        owner_metadata = (
            owner.get("metadata") if isinstance(owner.get("metadata"), dict) else {}
        )
        existing_marker = (
            owner_metadata.get(AGENT_MARKER)
            if isinstance(owner_metadata.get(AGENT_MARKER), dict)
            else {}
        )
        marker = {"schemaVersion": PROFILE_VERSION, "teamId": team_id}
        if existing_marker != marker:
            directory.update_agent_instance(
                str(owner["agentId"]),
                metadata={**owner_metadata, AGENT_MARKER: marker},
                expected_updated_at=str(owner.get("updatedAt") or ""),
                expected_config_revision=int(owner.get("configRevision") or 0),
            )

        return get_financial_team(str(owner["agentId"]))
