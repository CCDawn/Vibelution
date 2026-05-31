# -*- coding: utf-8 -*-
"""Agent-facing tools for controlled tool-permission governance."""

from __future__ import annotations

import json
import re
from typing import Any

from core.chat.chat_task_types import trim_lines


def agent_tool_permission_request_tool(
    target_agent: str,
    grant_tools: str = "",
    revoke_tools: str = "",
    block_tools: str = "",
    unblock_tools: str = "",
    reason: str = "",
    apply_mode: str = "auto",
) -> str:
    """
    Submit a controlled ToolPolicy change request for another Agent.

    Governance Agents may auto-apply low-risk changes. High-risk grants stay
    pending for user review. The final state is always stored in the target
    Agent's ToolPolicy.

    Args:
        target_agent: Target Agent id, stable code such as A002, or unique display name.
        grant_tools: Comma/newline separated tools to add to allowedTools.
        revoke_tools: Comma/newline separated tools to remove from allowedTools.
        block_tools: Comma/newline separated tools to add to blockedTools.
        unblock_tools: Comma/newline separated tools to remove from blockedTools.
        reason: Short rationale for the permission change.
        apply_mode: auto or review. auto still keeps high-risk changes pending.

    Returns:
        JSON string describing applied/pending status and review requirement.
    """

    try:
        from core.web.services.agent_directory_service import current_agent_runtime, list_agents
        from core.web.services.agent_tool_governance_service import submit_tool_governance_request

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

        target = _resolve_target_agent(str(target_agent or "").strip(), list_agents(include_archived=False))
        if not target.get("ok"):
            return _json_result(target)
        target_agent_payload = target["agent"]
        target_agent_id = str(target_agent_payload.get("agentId") or "").strip()
        request = submit_tool_governance_request(
            target_agent_id,
            proposed_by_agent_id=proposer_agent_id,
            grant_tools=_parse_tool_list(grant_tools),
            revoke_tools=_parse_tool_list(revoke_tools),
            block_tools=_parse_tool_list(block_tools),
            unblock_tools=_parse_tool_list(unblock_tools),
            reason=reason,
            apply_mode=apply_mode,
        )
        return _json_result(
            {
                "ok": request.get("status") in {"applied", "pending_review"},
                "status": request.get("status") or "",
                "requestId": request.get("requestId") or "",
                "targetAgentId": request.get("targetAgentId") or target_agent_id,
                "targetAgentCode": request.get("targetAgentCode") or target_agent_payload.get("agentCode") or "",
                "requiresApproval": bool(request.get("requiresApproval")),
                "riskLevel": request.get("riskLevel") or "",
                "riskTags": request.get("riskTags") or [],
                "approvalReason": request.get("approvalReason") or "",
                "policyDelta": request.get("policyDelta") or {},
                "message": _status_message(request),
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


def _resolve_target_agent(target: str, agents: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = str(target or "").strip()
    if not normalized:
        return {
            "ok": False,
            "status": "blocked",
            "error": "target_required",
            "message": "请提供目标 Agent 的 agentId、代号或唯一名称。",
        }
    labels = _target_agent_lookup_labels(normalized)
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
            "error": "ambiguous_target",
            "message": "目标 Agent 匹配到多个实例，请改用 agentId。",
        }
    name_matches = [
        item for item in agents
        if str(item.get("displayName") or "").strip().casefold() in folded
    ]
    if len(name_matches) == 1:
        return {"ok": True, "agent": name_matches[0]}
    if len(name_matches) > 1:
        return {
            "ok": False,
            "status": "blocked",
            "error": "ambiguous_target_name",
            "message": "目标名称不唯一，请改用 agentId 或稳定代号。",
        }
    return {
        "ok": False,
        "status": "blocked",
        "error": "target_not_found",
        "message": f"未找到目标 Agent: {normalized}",
    }


def _target_agent_lookup_labels(target: str) -> list[str]:
    normalized = str(target or "").strip()
    if not normalized:
        return []
    labels = [normalized]
    composite_match = re.match(
        r"^\s*(?P<code>A\d{3,})\s*(?:[·•\-\u2013\u2014:：|/]|[\(（])\s*(?P<name>.+?)\s*[\)）]?\s*$",
        normalized,
        flags=re.IGNORECASE,
    )
    if composite_match:
        labels.extend(
            [
                str(composite_match.group("code") or "").strip(),
                str(composite_match.group("name") or "").strip(),
            ]
        )
    unique: list[str] = []
    seen: set[str] = set()
    for label in labels:
        clean = str(label or "").strip()
        if not clean:
            continue
        folded = clean.casefold()
        if folded in seen:
            continue
        unique.append(clean)
        seen.add(folded)
    return unique


def _parse_tool_list(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    items = re.split(r"[,，;；\s\n]+", raw)
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        tool = str(item or "").strip()
        if not tool or tool in seen:
            continue
        seen.add(tool)
        result.append(tool)
    return result[:80]


def _status_message(request: dict[str, Any]) -> str:
    status = str(request.get("status") or "").strip()
    if status == "applied":
        return "工具权限变更已通过治理服务应用到目标 Agent 的 ToolPolicy。"
    if status == "pending_review":
        return "工具权限变更已进入待审批队列，高风险或非授权变更不会自动应用。"
    return "工具权限治理请求已记录。"


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
