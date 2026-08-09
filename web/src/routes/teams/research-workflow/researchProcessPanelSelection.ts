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
