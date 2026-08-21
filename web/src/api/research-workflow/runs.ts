import type {
  ResearchWorkflowNodeDetail,
  ResearchWorkflowSnapshot,
} from "../types/research-workflow/core";
import { fetchJson } from "../client";

function requireTeamId(teamId: string): string {
  const normalized = String(teamId || "").trim();
  if (!normalized) {
    throw new Error("teamId is required");
  }
  return normalized;
}

export async function fetchResearchWorkflowSnapshot(options: {
  runId: string;
  teamId: string;
  signal?: AbortSignal;
}): Promise<ResearchWorkflowSnapshot> {
  const teamId = requireTeamId(options.teamId);
  const runId = String(options.runId || "").trim();
  return fetchJson<ResearchWorkflowSnapshot>(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/snapshot?teamId=${encodeURIComponent(teamId)}`,
    { signal: options.signal },
  );
}

export async function fetchResearchWorkflowNodeDetail(options: {
  runId: string;
  nodeId: string;
  teamId: string;
  signal?: AbortSignal;
}): Promise<ResearchWorkflowNodeDetail> {
  const teamId = requireTeamId(options.teamId);
  const runId = String(options.runId || "").trim();
  const nodeId = String(options.nodeId || "").trim();
  return fetchJson<ResearchWorkflowNodeDetail>(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}?teamId=${encodeURIComponent(teamId)}`,
    { signal: options.signal },
  );
}
