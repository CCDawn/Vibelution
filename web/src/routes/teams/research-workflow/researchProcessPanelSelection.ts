export type ResearchProcessPanel = "node" | "agents" | "team" | "timeline" | "experiment" | "knowledge";

export function shouldApplyCanvasNodeSelection({
  nodeId,
  panel,
}: {
  nodeId: string | null;
  panel: ResearchProcessPanel;
}): boolean {
  return nodeId !== null || panel === "node";
}

export function isStageDrawerPanel(panel: ResearchProcessPanel): boolean {
  return panel === "experiment" || panel === "knowledge";
}
