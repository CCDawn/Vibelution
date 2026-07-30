"""Read-only effective configuration projection for Agent governance surfaces."""

from __future__ import annotations

import copy
from typing import Any

from .agent_directory_service import agent_dialogue_model_id, normalize_delegation_policy, normalize_supervision_policy


_FIELD_ISSUE_PREFIXES = {
    "promptTemplate": ("missing_prompt_template", "missing_prompt_source"),
    "toolPolicy": ("missing_tool_policy", "tool_policy_required"),
    "memoryPolicy": ("missing_memory_policy",),
}


def _field_status(agent: dict[str, Any], key: str, effective_value: Any) -> str:
    if key == "dialogueModel" and not str(effective_value or "").strip():
        return "blocked"
    if key in {"promptTemplate", "toolPolicy", "memoryPolicy"} and not str(effective_value or "").strip():
        return "warning"
    prefixes = _FIELD_ISSUE_PREFIXES.get(key, ())
    relevant = [
        item
        for item in list(agent.get("health") or [])
        if isinstance(item, dict)
        and any(str(item.get("code") or "").strip().startswith(prefix) for prefix in prefixes)
    ]
    if any(str(item.get("severity") or "").strip() == "blocking" for item in relevant):
        return "blocked"
    if relevant:
        return "warning"
    return "ready"


def _configuration_source(kind: str, source_id: str, label: str) -> dict[str, str]:
    return {"kind": kind, "id": source_id, "label": label}


def _field(
    *,
    key: str,
    label: str,
    effective_value: Any,
    source: dict[str, str],
    status: str,
    inheritance_chain: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    chain = list(inheritance_chain or [])
    if not chain:
        chain = [{**source, "value": copy.deepcopy(effective_value), "active": True}]
    return {
        "key": key,
        "label": label,
        "effectiveValue": copy.deepcopy(effective_value),
        "source": source,
        "inheritanceChain": chain,
        "status": status,
    }


def _tool_policy_source_kind(source: dict[str, Any]) -> str:
    kind = str(source.get("kind") or "").strip()
    if kind in {"agent_private_override", "session_default_private", "legacy_wide_private_override"}:
        return "agent"
    if kind in {"system_no_tools", "fixed_role_policy"}:
        return "system"
    if kind == "empty_default_policy":
        return "global"
    return "shared_policy"


def derive_effective_configuration(agent: dict[str, Any]) -> dict[str, Any]:
    """Project already-hydrated Agent data without reading any additional store."""
    agent_id = str(agent.get("agentId") or "").strip()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    dialogue_model_id = agent_dialogue_model_id(agent)
    prompt_template_id = str(agent.get("promptTemplateId") or "").strip()
    tool_policy_id = str(agent.get("toolPolicyId") or "").strip()
    memory_policy_id = str(agent.get("memoryPolicyId") or "").strip()
    compression = agent.get("contextCompressionEffectivePolicy")
    compression = dict(compression) if isinstance(compression, dict) else {}
    delegation = normalize_delegation_policy(metadata.get("delegationPolicy"))
    supervision = normalize_supervision_policy(metadata.get("supervisionPolicy"))

    return {
        "fields": [
            _field(
                key="dialogueModel",
                label="对话模型",
                effective_value=dialogue_model_id,
                source=_configuration_source("agent", agent_id, "Agent 模型绑定"),
                status=_field_status(agent, "dialogueModel", dialogue_model_id),
            ),
            _field(
                key="promptTemplate",
                label="提示词模板",
                effective_value=prompt_template_id,
                source=_configuration_source("agent", agent_id, "Agent 提示词模板"),
                status=_field_status(agent, "promptTemplate", prompt_template_id),
            ),
            _field(
                key="toolPolicy",
                label="工具策略",
                effective_value=tool_policy_id,
                source=_configuration_source("agent", agent_id, "Agent 工具策略"),
                status=_field_status(agent, "toolPolicy", tool_policy_id),
            ),
            _field(
                key="memoryPolicy",
                label="记忆策略",
                effective_value=memory_policy_id,
                source=_configuration_source("agent", agent_id, "Agent 记忆策略"),
                status=_field_status(agent, "memoryPolicy", memory_policy_id),
            ),
            _field(
                key="contextCompression",
                label="上下文压缩",
                effective_value=compression,
                source=_configuration_source("agent", agent_id, "Agent 上下文压缩策略"),
                status=_field_status(agent, "contextCompression", compression),
            ),
            _field(
                key="delegation",
                label="委派策略",
                effective_value=delegation,
                source=_configuration_source("agent", agent_id, "Agent 委派策略"),
                status=_field_status(agent, "delegation", delegation),
            ),
            _field(
                key="supervision",
                label="监督策略",
                effective_value=supervision,
                source=_configuration_source("agent", agent_id, "Agent 监督策略"),
                status=_field_status(agent, "supervision", supervision),
            ),
        ],
    }
