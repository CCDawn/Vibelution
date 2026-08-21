export type ResearchProcessPanel =
  | "node"
  | "agents"
  | "team"
  | "timeline"
  | "launch"
  | "evidence"
  | "progress"
  | "question";

const RESEARCH_PROCESS_TOOL_PANELS: ReadonlySet<ResearchProcessPanel> = new Set([
  "agents",
  "team",
  "timeline",
  "evidence",
  "progress",
  "launch",
]);

export function shouldApplyCanvasNodeSelection({
  nodeId,
  panel,
}: {
  nodeId: string | null;
  panel: ResearchProcessPanel;
}): boolean {
  return nodeId !== null || panel === "node";
}

/**
 * Keep the inspector column mounted. Hiding it lets the canvas eat the
 * right pane and clips toolbar actions against the window edge.
 */
export function shouldShowResearchProcessInspector(_input: {
  panel: ResearchProcessPanel;
  selectedNodeId: string | null;
  nextTarget?: string | null;
}): boolean {
  return true;
}

export type ResearchProcessAutofocusPatch = {
  node: string;
  panel: "node";
};

/**
 * Follow the current task into the node inspector without stealing tool
 * panels, and without fighting a same-task click that only changes the
 * canvas selection ring.
 */
export function resolveResearchProcessAutofocus(input: {
  panel: ResearchProcessPanel;
  selectedNodeId: string | null;
  nextTarget: string | null;
  previousNextTarget: string | null;
}): ResearchProcessAutofocusPatch | null {
  if (RESEARCH_PROCESS_TOOL_PANELS.has(input.panel)) return null;
  if (input.panel !== "node") return null;
  const target = input.nextTarget?.trim() || null;
  if (!target) return null;
  if (input.selectedNodeId === target) return null;
  const targetChanged = input.previousNextTarget !== target;
  const noSelection = !input.selectedNodeId;
  if (!noSelection && !targetChanged) return null;
  return { node: target, panel: "node" };
}
