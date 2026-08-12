import type {
  ResearchWorkflowNodeDetail,
  ResearchWorkflowSnapshot,
} from "../types/research-workflow/core";

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
  const response = await fetch(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/snapshot?teamId=${encodeURIComponent(teamId)}`,
    { signal: options.signal, headers: { Accept: "application/json" } },
  );
  if (!response.ok) {
    throw new Error(`snapshot_http_${response.status}`);
  }
  return (await response.json()) as ResearchWorkflowSnapshot;
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
  const response = await fetch(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}?teamId=${encodeURIComponent(teamId)}`,
    { signal: options.signal, headers: { Accept: "application/json" } },
  );
  if (!response.ok) {
    throw new Error(`node_detail_http_${response.status}`);
  }
  return (await response.json()) as ResearchWorkflowNodeDetail;
}
