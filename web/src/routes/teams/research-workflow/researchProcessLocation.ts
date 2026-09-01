import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import {
  RESEARCH_PROCESS_INSPECTOR_CLOSED,
  shouldOpenResearchProcessInspector,
  type ResearchProcessPanel,
} from "./researchProcessPanelSelection";

export type ResearchProcessLocation = {
  runId: string;
  selectedNodeId: string | null;
  panel: ResearchProcessPanel;
  questionId: string;
  inspectorOpen: boolean;
};

const PANELS = new Set<ResearchProcessPanel>([
  "node",
  "agents",
  "team",
  "timeline",
  "launch",
  "evidence",
  "progress",
  "question",
  "leaderboard",
]);

export function parseResearchProcessLocation(searchParams: URLSearchParams): ResearchProcessLocation {
  const requestedPanel = searchParams.get("panel") as ResearchProcessPanel | null;
  const panel = requestedPanel && PANELS.has(requestedPanel) ? requestedPanel : "node";
  return {
    runId: searchParams.get("runId")?.trim() ?? "",
    selectedNodeId: searchParams.get("node")?.trim() || null,
    panel,
    questionId: searchParams.get("questionId")?.trim().toUpperCase() ?? "",
    inspectorOpen: shouldOpenResearchProcessInspector({
      panel,
      inspector: searchParams.get("inspector"),
    }),
  };
}

export function patchResearchProcessSearch(options: {
  current: URLSearchParams;
  teamId: string;
  patch: Record<string, string | null | undefined>;
}): URLSearchParams {
  const teamId = options.teamId.trim();
  if (!teamId) throw new Error("teamId 不能为空");
  const next = new URLSearchParams(options.current);
  next.delete("team");
  next.delete("team_id");
  next.set("teamId", teamId);
  next.set("researchView", "workflow");
  next.set("workflowId", CHALLENGE_CUP_WORKFLOW_ID);
  const hasPanelPatch = Object.prototype.hasOwnProperty.call(options.patch, "panel");
  const hasInspectorPatch = Object.prototype.hasOwnProperty.call(options.patch, "inspector");
  for (const [key, value] of Object.entries(options.patch)) {
    if (value === null || value === undefined || value === "") next.delete(key);
    else next.set(key, value);
  }
  // Panel navigation is an explicit request to show the selected inspector.
  // React Flow also reports an empty selection during initialisation; that
  // callback must not undo a user's explicit closed state.
  const requestedPanel = typeof options.patch.panel === "string"
    ? options.patch.panel.trim()
    : "";
  const isCanvasSelectionClear = requestedPanel === "node" && options.patch.node === null;
  if (hasPanelPatch && requestedPanel && !hasInspectorPatch && !isCanvasSelectionClear) {
    next.delete("inspector");
  }
  return next;
}
