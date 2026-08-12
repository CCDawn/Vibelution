import type { CommandOffer, CommandReceipt } from "../types/research-workflow/commands";

function requireTeamId(teamId: string): string {
  const normalized = String(teamId || "").trim();
  if (!normalized) {
    throw new Error("teamId is required");
  }
  return normalized;
}

export async function submitResearchWorkflowCommandOffer(options: {
  teamId: string;
  runId: string;
  offer: CommandOffer;
  signal?: AbortSignal;
}): Promise<CommandReceipt> {
  const teamId = requireTeamId(options.teamId);
  const runId = String(options.runId || "").trim();
  const offer = options.offer;

  if (!offer.available) {
    throw new Error(offer.reasonCode || "command_unavailable");
  }

  const body = {
    teamId,
    command: offer.command,
    expectedRunVersion: offer.expectedRunVersion,
    idempotencyKey: offer.idempotencyKey,
    payload: offer.payload ?? {},
  };

  const nodeId = offer.nodeId ? String(offer.nodeId).trim() : "";
  const url = nodeId
    ? `/api/research/workflow-runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}/commands`
    : `/api/research/workflow-runs/${encodeURIComponent(runId)}/commands`;

  const response = await fetch(url, {
    method: "POST",
    signal: options.signal,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(`command_http_${response.status}`);
  }

  return (await response.json()) as CommandReceipt;
}
