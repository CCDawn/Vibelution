import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import type { ResearchProcessPanel } from "./researchProcessPanelSelection";

export type ResearchProcessLocation = {
  runId: string;
  selectedNodeId: string | null;
  panel: ResearchProcessPanel;
  questionId: string;
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
]);

export function parseResearchProcessLocation(searchParams: URLSearchParams): ResearchProcessLocation {
  const requestedPanel = searchParams.get("panel") as ResearchProcessPanel | null;
  return {
    runId: searchParams.get("runId")?.trim() ?? "",
    selectedNodeId: searchParams.get("node")?.trim() || null,
    panel: requestedPanel && PANELS.has(requestedPanel) ? requestedPanel : "node",
    questionId: searchParams.get("questionId")?.trim().toUpperCase() ?? "",
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
  for (const [key, value] of Object.entries(options.patch)) {
    if (value === null || value === undefined || value === "") next.delete(key);
    else next.set(key, value);
  }
  return next;
}
