import type {
  NodeHandoffRecord,
  WorkflowDefinition,
} from "../../../api/types/researchWorkflow";

export type ResearchCriticalPathItem = {
  nodeId: string;
  label: string;
};

export function buildResearchCriticalPath(
  definition: WorkflowDefinition,
  handoffs: NodeHandoffRecord[],
  runtimeCurrentNodeIds: string[],
): ResearchCriticalPathItem[] {
  const accepted = handoffs.filter((handoff) => handoff.status === "accepted");
  const acceptedIncoming = new Map(
    accepted.map((handoff) => [handoff.toNodeId, handoff]),
  );
  const targetNodeId = runtimeCurrentNodeIds[0] || accepted.at(-1)?.toNodeId || "";
  if (!targetNodeId) return [];

  const nodeIds: string[] = [];
  const visited = new Set<string>();
  let cursor = targetNodeId;
  while (cursor && !visited.has(cursor)) {
    visited.add(cursor);
    nodeIds.unshift(cursor);
    cursor = acceptedIncoming.get(cursor)?.fromNodeId || "";
  }
  const labels = new Map(definition.nodes.map((node) => [node.nodeId, node.label]));
  return nodeIds.map((nodeId) => ({ nodeId, label: labels.get(nodeId) || nodeId }));
}
