# -*- coding: utf-8 -*-
"""Agent-facing tools for controlled research organization governance."""

from __future__ import annotations

import json
import re
from typing import Any

from core.chat.chat_task_types import trim_lines


def research_agent_creation_proposal_tool(
    display_name: str,
    role: str = "research_specialist",
    role_key: str = "",
    employee_rank: str = "specialist",
    prompt_template_id: str = "",
    responsibilities: str = "",
    allowed_tools: str = "",
    read_shared_groups: str = "",
    write_shared_groups: str = "",
    communication_targets: str = "",
    report_to: str = "CEO",
    reason: str = "",
) -> str:
    """
    Submit a controlled proposal to create a new research Agent.

    The tool creates a high-risk organization proposal only. Applying the proposal remains
    handled by the existing user-gated research organization proposal path.
    """

    try:
        from core.web.services.agent_directory_service import current_agent_runtime
        from core.web.services.research_organization_service import create_research_org_proposal

        runtime = current_agent_runtime()
        proposer_agent_id = str(runtime.get("agentId") or "").strip()
        if not proposer_agent_id:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "agent_runtime_missing",
                    "message": "当前工具需要在已绑定 AgentInstance 的运行时中调用。",
                }
            )

        normalized_name = trim_lines(str(display_name or ""), max_lines=1).strip()
        if not normalized_name:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "display_name_required",
                    "message": "创建 Agent 提案需要 display_name。",
                }
            )

        normalized_role = trim_lines(str(role or "research_specialist"), max_lines=1).strip() or "research_specialist"
        normalized_role_key = trim_lines(str(role_key or normalized_role), max_lines=1).strip() or normalized_role
        action = {
            "actionType": "create_agent",
            "displayName": normalized_name,
            "role": normalized_role,
            "roleKey": normalized_role_key,
            "employeeRank": trim_lines(str(employee_rank or "specialist"), max_lines=1).strip() or "specialist",
            "promptTemplateId": trim_lines(str(prompt_template_id or ""), max_lines=1).strip(),
            "responsibilities": _parse_lines(responsibilities),
            "allowedTools": _parse_list(allowed_tools) or [
                "agent_message_tool",
                "batch_web_search_tool",
                "paper_search_tool",
                "web_fetch_tool",
            ],
            "readSharedGroups": _parse_list(read_shared_groups) or ["project", "research"],
            "writeSharedGroups": _parse_list(write_shared_groups),
            "communicationTargets": _parse_lines(communication_targets) or ["CEO", "Organization Advisor", "Capability Steward"],
            "reportTo": trim_lines(str(report_to or "CEO"), max_lines=1).strip() or "CEO",
        }
        proposal = create_research_org_proposal(
            {
                "title": f"新增科研 Agent 提案: {normalized_name}",
                "description": trim_lines(reason or f"Agent requested creation of {normalized_name}.", max_lines=8),
                "proposedByAgentId": proposer_agent_id,
                "recommendedByAgentId": proposer_agent_id,
                "actions": [action],
            }
        )
        reused = bool(proposal.get("reused"))
        proposal = proposal["proposal"]
        return _json_result(
            {
                "ok": True,
                "status": "existing_proposal" if reused else "proposal_created",
                "proposalId": proposal.get("proposalId") or "",
                "proposalStatus": proposal.get("status") or "",
                "riskLevel": proposal.get("riskLevel") or "",
                "requiresUserConfirmation": bool(proposal.get("requiresUserConfirmation")),
                "action": action,
                "message": (
                    "已找到同名或同角色的待应用创建提案；请等待用户确认或使用 research_proposal_apply_tool 应用，不要重复创建。"
                    if reused
                    else "新增 Agent 提案已创建；应用后才会生成 Agent，之后再配置工具权限和通信边。"
                ),
            }
        )
    except Exception as exc:
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
            }
        )


def research_proposal_apply_tool(
    proposal_id: str,
    user_confirmed: bool = False,
    reason: str = "",
    confirmation_text: str = "",
    confirmation_turn_id: str = "",
) -> str:
    """
    Apply a user-confirmed research organization proposal.

    This is the missing bridge between a high-risk proposal and the actual Agent/edge
    state change. It refuses to run unless the caller records explicit user confirmation.
    """

    try:
        from core.web.services.agent_directory_service import current_agent_runtime
        from core.web.services.research_organization_service import apply_research_org_proposal

        runtime = current_agent_runtime()
        actor_agent_id = str(runtime.get("agentId") or "").strip()
        if not actor_agent_id:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "agent_runtime_missing",
                    "message": "当前工具需要在已绑定 AgentInstance 的运行时中调用。",
                }
            )
        normalized_proposal_id = trim_lines(str(proposal_id or ""), max_lines=1).strip()
        if not normalized_proposal_id:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "proposal_id_required",
                    "message": "应用科研组织提案需要 proposal_id。",
                }
            )
        normalized_confirmation = trim_lines(str(confirmation_text or reason or ""), max_lines=3).strip()
        if not user_confirmed or not normalized_confirmation:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "user_confirmation_required",
                    "message": "应用科研组织提案必须先得到当前用户明确确认，并提供 confirmation_text 或 reason 作为确认摘要。",
                    "proposalId": normalized_proposal_id,
                    "requires": ["user_confirmed=true", "confirmation_text"],
                }
            )

        applied = apply_research_org_proposal(
            normalized_proposal_id,
            confirmation={
                "source": "research_proposal_apply_tool",
                "actorAgentId": actor_agent_id,
                "text": normalized_confirmation,
                "turnId": trim_lines(str(confirmation_turn_id or ""), max_lines=1).strip(),
            },
        )
        proposal = applied.get("proposal") or {}
        results = [item for item in applied.get("results") or [] if isinstance(item, dict)]
        created_agents = [
            {
                "agentId": str(item.get("agentId") or ""),
                "displayName": str(item.get("displayName") or ""),
            }
            for item in results
            if item.get("actionType") == "create_agent" and item.get("status") == "applied"
        ]
        return _json_result(
            {
                "ok": True,
                "status": str(proposal.get("status") or "applied"),
                "proposalId": str(proposal.get("proposalId") or normalized_proposal_id),
                "resultStatuses": [str(item.get("status") or "") for item in results],
                "createdAgents": created_agents,
                "message": "科研组织提案已应用；若包含 create_agent，现在 Agent 已生成，之后才能配置工具权限和通信边。",
                "reason": trim_lines(str(reason or ""), max_lines=2),
            }
        )
    except FileNotFoundError as exc:
        return _json_result(
            {
                "ok": False,
                "status": "blocked",
                "error": "proposal_not_found",
                "message": trim_lines(str(exc), max_lines=2),
            }
        )
    except Exception as exc:
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
            }
        )


def research_communication_edge_proposal_tool(
    action: str,
    source_agent: str = "",
    target_agent: str = "",
    edge_id: str = "",
    label: str = "",
    allowed_message_types: str = "",
    allowed_intents: str = "",
    wake_strategy: str = "conditional",
    max_forward_depth: int = 1,
    reason: str = "",
) -> str:
    """
    Submit a controlled proposal to create, update, or delete a research communication edge.

    The tool creates a research organization proposal only. Applying the proposal is still
    handled by the existing organization approval/apply path, which keeps communication
    policy changes reviewable and auditable.
    """

    try:
        from core.web.services.agent_directory_service import current_agent_runtime, list_agents
        from core.web.services.research_organization_service import create_research_org_proposal

        runtime = current_agent_runtime()
        proposer_agent_id = str(runtime.get("agentId") or "").strip()
        if not proposer_agent_id:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "agent_runtime_missing",
                    "message": "当前工具需要在已绑定 AgentInstance 的运行时中调用。",
                }
            )

        normalized_action = _normalize_action(action)
        if normalized_action not in {"create", "update", "delete"}:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "unsupported_action",
                    "message": "action 仅支持 create / update / delete。",
                }
            )

        agents = list_agents(include_archived=False)
        source = _resolve_agent(source_agent, agents) if source_agent else {"ok": True, "agent": {}}
        target = _resolve_agent(target_agent, agents) if target_agent else {"ok": True, "agent": {}}
        if not source.get("ok"):
            return _json_result(source)
        if not target.get("ok"):
            return _json_result(target)

        source_id = str(source.get("agent", {}).get("agentId") or "").strip()
        target_id = str(target.get("agent", {}).get("agentId") or "").strip()
        normalized_edge_id = str(edge_id or "").strip()
        if normalized_action != "delete" and (not source_id or not target_id):
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "edge_endpoints_required",
                    "message": "创建或更新通信边需要 source_agent 和 target_agent。",
                }
            )
        if normalized_action == "delete" and not normalized_edge_id:
            if source_id and target_id:
                normalized_edge_id = f"edge-{source_id}-{target_id}"
            else:
                return _json_result(
                    {
                        "ok": False,
                        "status": "blocked",
                        "error": "edge_id_required",
                        "message": "删除通信边需要 edge_id，或同时提供 source_agent 与 target_agent。",
                    }
                )

        proposal_action = _proposal_action(
            normalized_action,
            source_id=source_id,
            target_id=target_id,
            edge_id=normalized_edge_id,
            label=label,
            allowed_message_types=allowed_message_types,
            allowed_intents=allowed_intents,
            wake_strategy=wake_strategy,
            max_forward_depth=max_forward_depth,
        )
        proposal = create_research_org_proposal(
            {
                "title": _proposal_title(normalized_action, source.get("agent", {}), target.get("agent", {}), normalized_edge_id),
                "description": trim_lines(reason or "Agent requested a communication edge governance change.", max_lines=6),
                "proposedByAgentId": proposer_agent_id,
                "recommendedByAgentId": proposer_agent_id,
                "actions": [proposal_action],
            }
        )["proposal"]
        return _json_result(
            {
                "ok": True,
                "status": "proposal_created",
                "proposalId": proposal.get("proposalId") or "",
                "proposalStatus": proposal.get("status") or "",
                "riskLevel": proposal.get("riskLevel") or "",
                "requiresUserConfirmation": bool(proposal.get("requiresUserConfirmation")),
                "action": proposal_action,
                "message": "通信边变更提案已创建；应用后会更新科研组织通信边，并同步 research-team 团队画布线。",
            }
        )
    except Exception as exc:
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
            }
        )


def _normalize_action(action: str) -> str:
    normalized = str(action or "").strip().casefold()
    aliases = {
        "add": "create",
        "create_edge": "create",
        "update_edge": "update",
        "update_communication_edge": "update",
        "remove": "delete",
        "delete_edge": "delete",
        "archive": "delete",
    }
    return aliases.get(normalized, normalized)


def _proposal_action(
    action: str,
    *,
    source_id: str,
    target_id: str,
    edge_id: str,
    label: str,
    allowed_message_types: str,
    allowed_intents: str,
    wake_strategy: str,
    max_forward_depth: int,
) -> dict[str, Any]:
    if action == "delete":
        return {"actionType": "delete_edge", "edgeId": edge_id}
    policy: dict[str, Any] = {
        "allowedMessageTypes": _parse_list(allowed_message_types) or ["notice", "request", "report"],
        "allowedIntents": _parse_list(allowed_intents) or ["proposal", "report", "organization_design"],
        "wakeStrategy": _normalize_wake_strategy(wake_strategy),
        "maxForwardDepth": _bounded_depth(max_forward_depth),
    }
    return {
        "actionType": "create_edge" if action == "create" else "update_communication_edge",
        "edgeId": edge_id,
        "fromAgentId": source_id,
        "toAgentId": target_id,
        "label": trim_lines(label or "组织通信", max_lines=1).strip(),
        "communicationPolicy": policy,
    }


def _proposal_title(action: str, source: dict[str, Any], target: dict[str, Any], edge_id: str) -> str:
    if action == "delete":
        return f"通信边删除提案: {edge_id}"
    source_label = str(source.get("agentCode") or source.get("displayName") or source.get("agentId") or "").strip()
    target_label = str(target.get("agentCode") or target.get("displayName") or target.get("agentId") or "").strip()
    verb = "新增" if action == "create" else "更新"
    return f"通信边{verb}提案: {source_label} -> {target_label}"


def _resolve_agent(target: str, agents: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = str(target or "").strip()
    if not normalized:
        return {
            "ok": False,
            "status": "blocked",
            "error": "target_required",
            "message": "请提供 Agent 的 agentId、代号或唯一名称。",
        }
    labels = _lookup_labels(normalized)
    folded = {item.casefold() for item in labels if item}
    exact_matches = [
        item for item in agents
        if str(item.get("agentId") or "").strip() in labels
        or str(item.get("agentCode") or "").strip().casefold() in folded
    ]
    if len(exact_matches) == 1:
        return {"ok": True, "agent": exact_matches[0]}
    if len(exact_matches) > 1:
        return {
            "ok": False,
            "status": "blocked",
            "error": "ambiguous_agent",
            "message": "Agent 匹配到多个实例，请改用 agentId。",
        }
    name_matches = [item for item in agents if str(item.get("displayName") or "").strip().casefold() in folded]
    if len(name_matches) == 1:
        return {"ok": True, "agent": name_matches[0]}
    if len(name_matches) > 1:
        return {
            "ok": False,
            "status": "blocked",
            "error": "ambiguous_agent_name",
            "message": "Agent 名称不唯一，请改用 agentId 或稳定代号。",
        }
    return {
        "ok": False,
        "status": "blocked",
        "error": "agent_not_found",
        "message": f"未找到 Agent: {normalized}",
    }


def _lookup_labels(value: str) -> list[str]:
    normalized = str(value or "").strip()
    labels = [normalized]
    composite_match = re.match(
        r"^\s*(?P<code>A\d{3,})\s*(?:[·•\-\u2013\u2014:：|/]|[\(（])\s*(?P<name>.+?)\s*[\)）]?\s*$",
        normalized,
        flags=re.IGNORECASE,
    )
    if composite_match:
        labels.extend([str(composite_match.group("code") or "").strip(), str(composite_match.group("name") or "").strip()])
    result: list[str] = []
    seen: set[str] = set()
    for label in labels:
        clean = str(label or "").strip()
        if not clean:
            continue
        folded = clean.casefold()
        if folded in seen:
            continue
        result.append(clean)
        seen.add(folded)
    return result


def _parse_list(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in re.split(r"[,，;；\s\n]+", raw):
        clean = str(item or "").strip()
        if not clean or clean in seen:
            continue
        result.append(clean)
        seen.add(clean)
    return result[:40]


def _parse_lines(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in re.split(r"[\n;；]+", raw):
        clean = trim_lines(str(item or ""), max_lines=1).strip(" -\t")
        if not clean or clean in seen:
            continue
        result.append(clean)
        seen.add(clean)
    return result[:12]


def _normalize_wake_strategy(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized in {"immediate", "mailbox_only", "conditional"}:
        return normalized
    return "conditional"


def _bounded_depth(value: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = 1
    return max(0, min(number, 5))


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
