/**
 * Pure graph enrichment helpers for VWorkflowCanvas public models.
 * Safe for routes and tests — no React Flow, no renderer imports.
 */

import type {
  WorkflowActorKind,
  WorkflowCanvasEdgeInput,
  WorkflowCanvasNodeInput,
  WorkflowEdgePathState,
  WorkflowEdgeSemanticKind,
  WorkflowNodeRunStatus,
  WorkflowNodeVisualKind,
} from "./workflowCanvasTypes";

export function resolveNodeVisualKind(options: {
  nodeId: string;
  actorKind: WorkflowActorKind | string;
  isFirstInWorkflow?: boolean;
  isTerminalPackage?: boolean;
}): WorkflowNodeVisualKind {
  const id = options.nodeId;
  if (id === "iteration_decision") return "decision";
  if (id === "source_finding" || options.isFirstInWorkflow) return "start";
  if (id === "result_package" || options.isTerminalPackage) return "end";
  if (options.actorKind === "human") return "human_gate";
  if (options.actorKind === "system") return "system_task";
  return "agent_task";
}

export function resolveEdgeSemanticKind(options: {
  edgeId: string;
  label: string;
  gateKind: string;
  requiresHumanAccept?: boolean;
  fromNodeId: string;
  toNodeId: string;
}): WorkflowEdgeSemanticKind {
  const id = options.edgeId.toLowerCase();
  const label = options.label.toLowerCase();
  if (id.includes("rerun") || label.includes("重跑") || label.includes("rerun")) return "rerun";
  if (id.includes("rollback") || label.includes("回滚") || label.includes("rollback")) return "rollback";
  if (id.includes("promo") || id.includes("promote") || label.includes("晋升") || label.includes("promote")) {
    return "promote";
  }
  if (id.includes("stop") || label.includes("停止") || label.includes("stop")) return "stop";
  if (id.includes("revise") || label.includes("修订") || label.includes("revise")) return "revise";
  if (options.fromNodeId === "iteration_decision") return "decision_branch";
  if (
    options.requiresHumanAccept
    || options.gateKind === "human"
    || options.gateKind === "knowledge_package"
    || options.gateKind === "frozen_protocol"
    || options.gateKind === "smoke"
    || options.gateKind === "promotion"
  ) {
    return "human_gate";
  }
  return "main";
}

export function edgeLabelAlwaysVisible(kind: WorkflowEdgeSemanticKind, gateKind: string): boolean {
  if (kind !== "main") return true;
  if (gateKind && gateKind !== "auto") return true;
  return false;
}

export function decisionSourceHandle(semanticKind: WorkflowEdgeSemanticKind, edgeId: string): string | undefined {
  if (edgeId.toLowerCase().includes("rerun") || semanticKind === "rerun") return "rerun";
  if (edgeId.toLowerCase().includes("promo") || semanticKind === "promote") return "promote";
  if (edgeId.toLowerCase().includes("rollback") || semanticKind === "rollback") return "rollback";
  if (edgeId.toLowerCase().includes("stop") || semanticKind === "stop") return "stop";
  if (semanticKind === "decision_branch" || semanticKind === "revise") return "branch";
  return undefined;
}

export function resolveEdgePathState(options: {
  sourceStatus: WorkflowNodeRunStatus | undefined;
  targetStatus: WorkflowNodeRunStatus | undefined;
  sourceIsCurrent: boolean;
  targetIsCurrent: boolean;
  semanticKind: WorkflowEdgeSemanticKind;
}): WorkflowEdgePathState {
  const src: WorkflowNodeRunStatus = options.sourceStatus ?? "pending";
  const tgt: WorkflowNodeRunStatus = options.targetStatus ?? "pending";
  const danger = new Set<WorkflowNodeRunStatus>(["failed", "blocked"]);
  const activeish = new Set<WorkflowNodeRunStatus>(["running", "ready"]);
  const attention = new Set<WorkflowNodeRunStatus>(["waiting_human"]);

  if (danger.has(src) || danger.has(tgt)) return "danger";
  if (attention.has(src) || attention.has(tgt)) return "attention";
  if (options.sourceIsCurrent || options.targetIsCurrent || activeish.has(src) || activeish.has(tgt)) {
    return "active";
  }
  if (src === "succeeded" && !new Set<WorkflowNodeRunStatus>(["pending", "skipped", "stale", "cancelled"]).has(tgt)) {
    return "traversed";
  }
  return "idle";
}

export function stageToneFromNodes(
  nodes: Array<{ status: WorkflowNodeRunStatus; isRuntimeCurrent?: boolean }>,
): "idle" | "active" | "done" | "attention" {
  if (
    nodes.some(
      (n) =>
        n.isRuntimeCurrent
        || n.status === "running"
        || n.status === "waiting_human"
        || n.status === "blocked"
        || n.status === "failed",
    )
  ) {
    if (nodes.some((n) => n.status === "waiting_human" || n.status === "blocked" || n.status === "failed")) {
      return "attention";
    }
    return "active";
  }
  if (nodes.length > 0 && nodes.every((n) => n.status === "succeeded" || n.status === "skipped")) {
    return "done";
  }
  return "idle";
}

export function buildEdgePathStates(
  edges: Array<Omit<WorkflowCanvasEdgeInput, "pathState"> & { pathState?: WorkflowEdgePathState }>,
  nodeById: Map<string, WorkflowCanvasNodeInput>,
  runtimeCurrent: Set<string>,
): WorkflowCanvasEdgeInput[] {
  return edges.map((edge) => {
    const source = nodeById.get(edge.fromNodeId);
    const target = nodeById.get(edge.toNodeId);
    const pathState =
      edge.pathState
      ?? resolveEdgePathState({
        sourceStatus: source?.status,
        targetStatus: target?.status,
        sourceIsCurrent: runtimeCurrent.has(edge.fromNodeId),
        targetIsCurrent: runtimeCurrent.has(edge.toNodeId),
        semanticKind: edge.semanticKind,
      });
    return { ...edge, pathState };
  });
}
