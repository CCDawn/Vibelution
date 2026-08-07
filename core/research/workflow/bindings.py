"""Agent binding resolution: workflow → stage → node → run snapshot."""

from __future__ import annotations

from .definition import build_challenge_cup_workflow_definition, node_by_id
from .models import ActorKind, AgentBindingLayers, RunAgentBindingSnapshot, WorkflowNodeSpec


def resolve_effective_agent_id(
    node: WorkflowNodeSpec,
    layers: AgentBindingLayers,
) -> tuple[str, str]:
    """Return (agentId, resolvedFrom). Empty agentId means unbound."""
    if node.actorKind is not ActorKind.AGENT:
        return "", "not_agent_node"

    node_override = (layers.nodeOverrides.get(node.nodeId) or "").strip()
    if node_override:
        return node_override, "node_override"

    stage_map = layers.stageOverrides.get(node.stageId.value) or {}
    stage_hit = (stage_map.get(node.primaryRoleKey) or "").strip()
    if stage_hit:
        return stage_hit, "stage_override"

    default = (layers.workflowDefaults.get(node.primaryRoleKey) or "").strip()
    if default:
        return default, "workflow_default"

    return "", "unbound"


def build_run_binding_snapshots(
    *,
    run_id: str,
    workflow_version_id: str,
    layers: AgentBindingLayers,
    captured_at: str,
    snapshot_prefix: str = "snap",
) -> list[RunAgentBindingSnapshot]:
    """Materialize run-time snapshots for all agent nodes at run start."""
    definition = build_challenge_cup_workflow_definition()
    snapshots: list[RunAgentBindingSnapshot] = []
    for node in definition.nodes:
        if node.actorKind is not ActorKind.AGENT:
            continue
        agent_id, source = resolve_effective_agent_id(node, layers)
        snapshots.append(
            RunAgentBindingSnapshot(
                snapshotId=f"{snapshot_prefix}:{run_id}:{node.nodeId}",
                workflowId=definition.workflowId,
                workflowVersionId=workflow_version_id,
                runId=run_id,
                nodeId=node.nodeId,
                agentId=agent_id,
                roleKey=node.primaryRoleKey,
                actorKind=node.actorKind,
                resolvedFrom=source,
                capturedAt=captured_at,
            )
        )
    return snapshots


def agent_id_from_run_snapshot(
    snapshots: list[RunAgentBindingSnapshot] | dict[str, RunAgentBindingSnapshot],
    node_id: str,
) -> str:
    """History path: only read snapshot, never live config."""
    if isinstance(snapshots, dict):
        snap = snapshots.get(node_id)
        return snap.agentId if snap else ""
    for snap in snapshots:
        if snap.nodeId == node_id:
            return snap.agentId
    return ""


def node_spec(node_id: str) -> WorkflowNodeSpec | None:
    return node_by_id().get(node_id)
