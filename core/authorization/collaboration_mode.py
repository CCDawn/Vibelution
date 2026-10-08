"""Session collaboration mode as a tool-permission decision.

The mode lives on the session. Plan is a flag on that session: while it is on,
writes are denied. This does not replace ToolPolicy. Tools the policy already
blocked never reach this decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

COLLABORATION_MODES = frozenset({"plan", "build", "edit", "yolo", "auto"})
ENTER_PLAN_MODE_TOOL = "enter_plan_mode_tool"
EXIT_PLAN_MODE_TOOL = "exit_plan_mode_tool"
COLLABORATION_CONTROL_TOOLS = (ENTER_PLAN_MODE_TOOL, EXIT_PLAN_MODE_TOOL)
FILE_EDIT_TOOLS = frozenset({
    "write_file_tool",
    "apply_patch_tool",
    "apply_diff_edit_tool",
})
PLAN_SESSION_CONTROL_TOOLS = frozenset({"todo_write", "plan_update_tool"})
PLAN_MAX_CHARS = 20_000
_COMMAND_PROMPT_TOOLS = frozenset({"Bash", "exec_command", "cli_tool"})


@dataclass(frozen=True, slots=True)
class ToolCapabilityFacts:
    read_only: bool = False
    writes: bool = False
    destructive: bool = False
    network_read: bool = False
    mcp: bool = False


@dataclass(frozen=True, slots=True)
class CollaborationDecision:
    decision: str
    rule_id: str
    reason: str


def default_collaboration_state() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "mode": "build",
        "planEnabled": False,
        "prePlanMode": "build",
    }


def normalize_collaboration_state(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    data = raw if isinstance(raw, Mapping) else {}
    mode = str(data.get("mode") or "build").strip().lower()
    if mode not in COLLABORATION_MODES:
        mode = "build"
    pre_plan_mode = str(data.get("prePlanMode") or "build").strip().lower()
    if pre_plan_mode not in COLLABORATION_MODES or pre_plan_mode == "plan":
        pre_plan_mode = "build"
    plan_enabled = _coerce_bool(data.get("planEnabled")) or mode == "plan"
    return {
        "schemaVersion": 1,
        "mode": mode,
        "planEnabled": plan_enabled,
        "prePlanMode": pre_plan_mode,
    }


def plan_is_enabled(state: Mapping[str, Any] | None) -> bool:
    normalized = normalize_collaboration_state(state)
    return bool(normalized["planEnabled"]) or normalized["mode"] == "plan"


def with_collaboration_controls(policy: Mapping[str, Any] | None) -> dict[str, Any]:
    """Add the plan enter/exit tools to a non-empty runtime policy copy.

    An explicit empty allow-list stays empty. Blocked names stay blocked.
    The persisted ToolPolicy is not this function's input.
    """

    source = dict(policy or {})
    allowed = [name for name in _names(source.get("allowedTools")) if name]
    if not allowed:
        return source
    blocked = set(_names(source.get("blockedTools")))
    added = [
        name
        for name in COLLABORATION_CONTROL_TOOLS
        if name not in allowed and name not in blocked
    ]
    if not added:
        return source
    source["allowedTools"] = [*allowed, *added]
    return source


def capability_for_tool(tool_name: str) -> ToolCapabilityFacts:
    from core.web.services.tool_catalog import (
        _DESTRUCTIVE_RISK_TAGS,
        _EXECUTE_RISK_TAGS,
        _NETWORK_RISK_TAGS,
        _WRITE_RISK_TAGS,
        metadata_for_tool,
    )

    metadata = metadata_for_tool(tool_name)
    capabilities = {str(item).strip() for item in metadata.get("capabilityTags") or []}
    risks = {str(item).strip() for item in metadata.get("riskTags") or []}
    writes = bool(risks & set(_WRITE_RISK_TAGS))
    destructive = bool(risks & (set(_DESTRUCTIVE_RISK_TAGS) | set(_EXECUTE_RISK_TAGS)))
    read_only = "read_only" in capabilities
    network = "network" in capabilities or bool(risks & set(_NETWORK_RISK_TAGS))
    return ToolCapabilityFacts(
        read_only=read_only,
        writes=writes,
        destructive=destructive,
        network_read=network and not read_only and not writes and not destructive,
        mcp="mcp" in capabilities,
    )


def check_collaboration_mode(
    state: Mapping[str, Any] | None,
    tool_name: str,
    *,
    capability: ToolCapabilityFacts | None = None,
    tool_args: Mapping[str, Any] | None = None,
) -> CollaborationDecision:
    normalized = normalize_collaboration_state(state)
    name = str(tool_name or "").strip()
    plan_on = plan_is_enabled(normalized)
    mode = str(normalized["mode"])

    if name == ENTER_PLAN_MODE_TOOL:
        return CollaborationDecision(
            "allow",
            "tool.plan.enter",
            "进入计划模式不需要确认。",
        )
    if name == EXIT_PLAN_MODE_TOOL:
        if not plan_on:
            return CollaborationDecision(
                "deny",
                "mode.plan.exitOnly",
                "当前不在计划模式，不能退出计划。",
            )
        invalid = _exit_plan_input_error(tool_args or {})
        if invalid:
            return CollaborationDecision("deny", "mode.plan.exitInvalid", invalid)
        return CollaborationDecision(
            "ask",
            "plan.exit",
            "退出计划前需要你确认这份计划。",
        )

    if mode == "yolo" and not plan_on:
        return CollaborationDecision(
            "allow",
            "mode.yolo",
            "全放开模式跳过确认。",
        )
    if mode == "auto" and not plan_on:
        return CollaborationDecision(
            "deny",
            "mode.auto.unimplemented",
            "自动模式还没做，工具调用已拒绝。",
        )
    if plan_on:
        return _check_plan_mode(name, capability if capability is not None else capability_for_tool(name))
    if mode == "edit" and name in FILE_EDIT_TOOLS:
        return CollaborationDecision(
            "allow",
            "mode.edit.fileEdit",
            "编辑模式允许直接改工作区文件。",
        )
    return CollaborationDecision("inherit", "mode.build", "")


def entered_plan_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    current = normalize_collaboration_state(state)
    pre_plan_mode = current["prePlanMode"]
    if not plan_is_enabled(current) and current["mode"] != "plan":
        pre_plan_mode = current["mode"]
    return {
        "schemaVersion": 1,
        "mode": current["mode"],
        "planEnabled": True,
        "prePlanMode": pre_plan_mode if pre_plan_mode != "plan" else "build",
    }


def exited_plan_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    current = normalize_collaboration_state(state)
    mode = current["prePlanMode"] if current["mode"] == "plan" else current["mode"]
    if mode == "plan":
        mode = "build"
    return {
        "schemaVersion": 1,
        "mode": mode,
        "planEnabled": False,
        "prePlanMode": current["prePlanMode"] if current["prePlanMode"] != "plan" else "build",
    }


def _check_plan_mode(tool_name: str, capability: ToolCapabilityFacts) -> CollaborationDecision:
    if tool_name in PLAN_SESSION_CONTROL_TOOLS and not capability.destructive:
        return CollaborationDecision(
            "allow",
            "mode.plan.explicitSessionCapability",
            "计划模式允许更新这份计划清单。",
        )
    if capability.read_only and not capability.destructive and not capability.writes:
        return CollaborationDecision(
            "allow",
            "mode.plan.readOnly",
            "计划模式允许只读工具。",
        )
    if capability.network_read:
        return CollaborationDecision(
            "allow",
            "mode.plan.networkRead",
            "计划模式允许不改文件的联网查看。",
        )
    if capability.mcp and not capability.destructive and not capability.writes:
        return CollaborationDecision(
            "allow",
            "mode.plan.mcp",
            "计划模式允许不破坏的外部工具。",
        )
    return CollaborationDecision(
        "deny",
        "mode.plan.nonReadOnly",
        "计划模式只允许查看，这个工具会改东西，已经拒绝。",
    )


def _exit_plan_input_error(tool_args: Mapping[str, Any]) -> str:
    plan = tool_args.get("plan")
    if not isinstance(plan, str) or not plan.strip():
        return "退出计划需要一份计划正文。"
    if len(plan) > PLAN_MAX_CHARS:
        return f"计划正文不能超过 {PLAN_MAX_CHARS} 字。"
    prompts = tool_args.get("allowed_prompts", tool_args.get("allowedPrompts"))
    if prompts is None:
        return ""
    if not isinstance(prompts, list) or len(prompts) > 20:
        return "允许的命令类别必须是不超过 20 条的列表。"
    for index, item in enumerate(prompts, start=1):
        if not isinstance(item, Mapping):
            return f"第 {index} 条命令类别不是对象。"
        tool_name = str(item.get("tool") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if tool_name not in _COMMAND_PROMPT_TOOLS or not prompt:
            return f"第 {index} 条命令类别需要工具名和说明。"
    return ""


def _names(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
