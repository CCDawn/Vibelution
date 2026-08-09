import type { NodeHandoffRecord } from "../../../api/types/researchWorkflow";

export function handoffsForNode(
  handoffs: NodeHandoffRecord[],
  nodeId: string,
): NodeHandoffRecord[] {
  return handoffs.filter(
    (handoff) => handoff.fromNodeId === nodeId || handoff.toNodeId === nodeId,
  );
}
