export type ResearchProcessPanel =
  | "node"
  | "agents"
  | "team"
  | "timeline"
  | "launch"
  | "evidence"
  | "progress"
  | "question";

export function shouldApplyCanvasNodeSelection({
  nodeId,
  panel,
}: {
  nodeId: string | null;
  panel: ResearchProcessPanel;
}): boolean {
  return nodeId !== null || panel === "node";
}

/** Node inspector is a real column only when it has a node or a tool panel. */
export function shouldShowResearchProcessInspector({
  panel,
  selectedNodeId,
}: {
  panel: ResearchProcessPanel;
  selectedNodeId: string | null;
}): boolean {
  return panel !== "node" || Boolean(selectedNodeId);
}
