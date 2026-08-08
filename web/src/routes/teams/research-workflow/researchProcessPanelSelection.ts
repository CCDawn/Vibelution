export type ResearchProcessPanel = "node" | "agents" | "team" | "timeline";

export function shouldApplyCanvasNodeSelection({
  nodeId,
  panel,
}: {
  nodeId: string | null;
  panel: ResearchProcessPanel;
}): boolean {
  return nodeId !== null || panel === "node";
}
