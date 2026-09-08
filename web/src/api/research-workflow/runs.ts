import type {
  ResearchWorkflowNodeDetail,
  ResearchWorkflowSnapshot,
} from "../types/research-workflow/core";
import { fetchJson } from "../client";
import { JSON_HEADERS } from "./client";

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

export type EvidenceGraphMissingLinkWaiverAudit = {
  by: string;
  at: string;
  justification: string;
};

export type EvidenceGraphMissingLinkWaiveResponse = {
  status: "waived" | "already_waived" | string;
  alreadyWaived: boolean;
  teamId: string;
  runId: string;
  sourceCollectionRunId: string;
  waiverCount: number;
  missingLinkCount: number;
  graphCandidateIds: string[];
  waiver: EvidenceGraphMissingLinkWaiverAudit;
};

/**
 * Confirm a human waiver for one evidence-graph missing link (缺陷⑪).
 *
 * 误触防护在服务端闭合：``confirmed`` 必须显式为 true 且理由 ≥8 字符，
 * 缺失会被 428 拒绝；豁免只登记人工接受，缺口本身保留。
 */
export async function waiveEvidenceGraphMissingLink(options: {
  runId: string;
  teamId?: string;
  sourceCandidateId: string;
  targetCandidateId: string;
  relation: string;
  justification: string;
  confirmed: boolean;
  signal?: AbortSignal;
}): Promise<EvidenceGraphMissingLinkWaiveResponse> {
  const runId = String(options.runId || "").trim();
  if (!runId) {
    throw new Error("runId is required");
  }
  return fetchJson<EvidenceGraphMissingLinkWaiveResponse>(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/evidence-graph/missing-links/waive`,
    {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({
        teamId: String(options.teamId || "").trim(),
        sourceCandidateId: String(options.sourceCandidateId || "").trim(),
        targetCandidateId: String(options.targetCandidateId || "").trim(),
        relation: String(options.relation || "").trim(),
        justification: String(options.justification || ""),
        confirmed: Boolean(options.confirmed),
      }),
      signal: options.signal,
    },
  );
}
