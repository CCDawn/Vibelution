import type { CommandOffer, CommandReceipt, WorkflowCommandKind } from "../types/research-workflow/commands";
import { fetchJson, JSON_HEADERS, requireTeamId, requireText } from "./client";

export async function submitResearchWorkflowCommand(options: {
  teamId: string;
  runId: string;
  command: WorkflowCommandKind | string;
  expectedRunVersion: number;
  idempotencyKey: string;
  nodeId?: string | null;
  payload?: Record<string, unknown>;
  signal?: AbortSignal;
}): Promise<CommandReceipt> {
  const teamId = requireTeamId(options.teamId);
  const runId = requireText(options.runId, "runId");
  const nodeId = options.nodeId ? String(options.nodeId).trim() : "";
  const body: Record<string, unknown> = {
    teamId,
    command: options.command,
    expectedRunVersion: options.expectedRunVersion,
    idempotencyKey: requireText(options.idempotencyKey, "idempotencyKey"),
    payload: options.payload ?? {},
  };
  if (nodeId) {
    body.nodeId = nodeId;
  }
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/commands`,
    {
      method: "POST",
      signal: options.signal,
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    },
  );
}

export async function submitResearchWorkflowCommandOffer(options: {
  teamId: string;
  runId: string;
  offer: CommandOffer;
  signal?: AbortSignal;
}): Promise<CommandReceipt> {
  const offer = options.offer;
  if (!offer.available) {
    throw new Error(offer.reasonCode || "command_unavailable");
  }
  return submitResearchWorkflowCommand({
    teamId: options.teamId,
    runId: options.runId,
    command: offer.command,
    expectedRunVersion: offer.expectedRunVersion,
    idempotencyKey: offer.idempotencyKey,
    nodeId: offer.nodeId,
    payload: offer.payload ?? {},
    signal: options.signal,
  });
}
