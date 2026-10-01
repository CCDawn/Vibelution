"""Per-node choice between a designed next station and an agent choice.

Specified mode is the default and is omitted from the canonical definition
payload. Agent mode is legal only on an agent node whose drawn outgoing edges
name at least two existing stations. The agent that just finished the node
writes ``nextNodeId``. An unknown id is asked once more; the second unknown
id, or a station already entered three times, waits for a person.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .models import ActorKind, NodeRouteMode, WorkflowDefinition

AGENT_NEXT_FIELD = "nextNodeId"
MAX_AGENT_NEXT_REJECTIONS = 1
MAX_AGENT_NODE_ENTRIES = 3
_NEXT_NODE_JSON = re.compile(r'"nextNodeId"\s*:\s*"([^"\\]+)"')
_NEXT_NODE_LINE = re.compile(
    r"(?im)^\s*nextNodeId\s*[:：]\s*([A-Za-z0-9_.:\-]+)\s*$"
)


class NodeRouteError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AgentRouteDecision:
    status: str
    next_node_id: str
    code: str
    detail: str


def extract_next_node_id(text: str) -> str:
    """Read the last nextNodeId the agent wrote, from JSON or a final line."""

    raw = str(text or "")
    found = [item.strip() for item in _NEXT_NODE_JSON.findall(raw) if item.strip()]
    if not found:
        found = [item.strip() for item in _NEXT_NODE_LINE.findall(raw) if item.strip()]
    return found[-1] if found else ""


def route_choice_instruction(targets: tuple[str, ...]) -> str:
    """Prompt suffix. Empty unless the designer drew at least two stations."""

    names = tuple(str(item).strip() for item in targets if str(item).strip())
    if len(names) < 2:
        return ""
    joined = "、".join(names)
    return (
        "\n下一步由你从已经画好的站点里选一个："
        f"{joined}。"
        "\n做完本步后，在回答最后单独一行写出 nextNodeId: <站点id>。"
        "不要写出列表以外的站点。"
    )


def agent_route_targets_for_version(version_id: str, node_id: str) -> tuple[str, ...]:
    """Designed stations for an agent-routed node. Specified nodes return empty."""

    version = str(version_id or "").strip()
    node = str(node_id or "").strip()
    if not version or not node:
        return ()
    from .challenge_cup_runtime import resolve_definition_for_version
    from .definition_registry import WorkflowDefinitionRegistryError

    try:
        definition = resolve_definition_for_version(version)
    except WorkflowDefinitionRegistryError:
        return ()
    spec = next((item for item in definition.nodes if item.nodeId == node), None)
    if spec is None or spec.routeMode is not NodeRouteMode.AGENT:
        return ()
    return allowed_targets(definition, node)


def allowed_targets(definition: WorkflowDefinition, node_id: str) -> tuple[str, ...]:
    seen: list[str] = []
    for edge in definition.edges:
        if edge.fromNodeId != node_id or edge.toNodeId in seen:
            continue
        seen.append(edge.toNodeId)
    return tuple(seen)


def validate_definition_routes(definition: WorkflowDefinition) -> None:
    known = {node.nodeId for node in definition.nodes}
    for node in definition.nodes:
        if node.routeMode is NodeRouteMode.SPECIFIED:
            continue
        if node.routeMode is not NodeRouteMode.AGENT:
            raise NodeRouteError(
                f"unknown routeMode on {node.nodeId}",
                code="unknown_route_mode",
            )
        if node.actorKind is not ActorKind.AGENT:
            raise NodeRouteError(
                f"{node.nodeId} can use agent routing only when its actor is an agent",
                code="agent_route_requires_agent",
            )
        targets = allowed_targets(definition, node.nodeId)
        if len(targets) < 2:
            raise NodeRouteError(
                f"{node.nodeId} needs at least two designed next stations",
                code="agent_route_needs_menu",
            )
        missing = [target for target in targets if target not in known]
        if missing:
            joined = ", ".join(missing)
            raise NodeRouteError(
                f"{node.nodeId} points at unknown nodes: {joined}",
                code="agent_route_unknown_target",
            )


def resolve_agent_route(
    *,
    allowed: tuple[str, ...],
    chosen: str,
    prior_rejections: int,
    target_entry_count: int,
) -> AgentRouteDecision:
    """Decide the handoff for one agent-routed node."""

    target = str(chosen or "").strip()
    if target not in allowed:
        detail = "nextNodeId is not one of the designed next stations"
        if int(prior_rejections or 0) >= MAX_AGENT_NEXT_REJECTIONS:
            return AgentRouteDecision("wait_human", "", "agent_next_rejected", detail)
        return AgentRouteDecision("retry", "", "agent_next_rejected", detail)
    if int(target_entry_count or 0) >= MAX_AGENT_NODE_ENTRIES:
        return AgentRouteDecision(
            "wait_human",
            target,
            "agent_next_reentry_cap",
            f"{target} has already been entered {MAX_AGENT_NODE_ENTRIES} times",
        )
    return AgentRouteDecision("follow", target, "", "")


def successors_for_decision(
    successors: tuple[str, ...],
    decision: AgentRouteDecision | None,
) -> tuple[str, ...] | None:
    """Specified mode keeps the caller's successors. A hold returns None."""

    if decision is None:
        return successors
    if decision.status == "follow":
        return (decision.next_node_id,)
    return None


def decision_from_attempts(
    *,
    allowed: tuple[str, ...],
    chosen: str,
    attempts: list[Any],
    node_id: str,
    node_run_id: str,
) -> AgentRouteDecision:
    prior = 0
    entries = 0
    target = str(chosen or "").strip()
    for item in attempts:
        item_node = str(getattr(item, "node_id", "") or "")
        if item_node == node_id and _problem_code(item) == "agent_next_rejected":
            prior += 1
        if (
            target
            and item_node == target
            and str(getattr(item, "node_run_id", "") or "") != node_run_id
            and str(getattr(item, "status", "") or "") == "succeeded"
        ):
            entries += 1
    return resolve_agent_route(
        allowed=allowed,
        chosen=target,
        prior_rejections=prior,
        target_entry_count=entries,
    )


def _problem_code(attempt: Any) -> str:
    raw = getattr(attempt, "problem_json", None) or ""
    if not raw:
        return ""
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return ""
    if isinstance(loaded, dict):
        return str(loaded.get("code") or "")
    return ""
