import { fetchJson } from "./client";
export { isFetchJsonHttpError } from "./client";
import type {
  FinancialTeam,
  FinancialTeamExecutionPolicy,
  FinancialTeamExecutionStatus,
  FinancialTeamRoleExecution,
  FinancialTeamRun,
  FinancialTeamRunCreateRequest,
  FinancialTeamRunList,
  FinancialTeamSynthesisRecoveryStatus,
  FinancialTeamTurnAttachRequest,
  FinancialTeamRole,
} from "./types/financialTeam";

export type {
  FinancialTeam,
  FinancialTeamExecutionPolicy,
  FinancialTeamExecutionStatus,
  FinancialTeamRoleExecution,
  FinancialTeamRole,
  FinancialTeamRoleMember,
  FinancialTeamRoleStatus,
  FinancialTeamRun,
  FinancialTeamRunCreateRequest,
  FinancialTeamRunList,
  FinancialTeamRunStage,
  FinancialTeamSynthesisRecoveryStatus,
  FinancialTeamTurnAttachRequest,
  FinancialTeamTurnRef,
  FinancialTeamStatus,
} from "./types/financialTeam";

export const financialTeamKeys = {
  detail: (assistantAgentId: string) => ["financial-team", assistantAgentId] as const,
  runs: (assistantAgentId: string) => ["financial-team", assistantAgentId, "runs"] as const,
  run: (assistantAgentId: string, runId: string) => ["financial-team", assistantAgentId, "run", runId] as const,
};

function rootPath(assistantAgentId: string): string {
  return `/api/financial-team/${encodeURIComponent(assistantAgentId)}`;
}

export function fetchFinancialTeam(assistantAgentId: string, options?: { signal?: AbortSignal }): Promise<FinancialTeam> {
  return fetchJson<FinancialTeam>(rootPath(assistantAgentId), { signal: options?.signal });
}

export function provisionFinancialTeam(assistantAgentId: string): Promise<FinancialTeam> {
  return fetchJson<FinancialTeam>(`${rootPath(assistantAgentId)}/provision`, { method: "POST" });
}

export function fetchFinancialTeamRuns(
  assistantAgentId: string,
  options?: { signal?: AbortSignal; limit?: number },
): Promise<FinancialTeamRunList> {
  const query = new URLSearchParams({ limit: String(options?.limit ?? 20) });
  return fetchJson<FinancialTeamRunList>(`${rootPath(assistantAgentId)}/runs?${query}`, { signal: options?.signal });
}

export function createFinancialTeamRun(
  assistantAgentId: string,
  payload: FinancialTeamRunCreateRequest,
  idempotencyKey: string,
): Promise<FinancialTeamRun> {
  return fetchJson<FinancialTeamRun>(`${rootPath(assistantAgentId)}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(payload),
  });
}

export function fetchFinancialTeamRun(
  assistantAgentId: string,
  runId: string,
  options?: { signal?: AbortSignal },
): Promise<FinancialTeamRun> {
  return fetchJson<FinancialTeamRun>(`${rootPath(assistantAgentId)}/runs/${encodeURIComponent(runId)}`, {
    signal: options?.signal,
  });
}

export function recordFinancialTeamTurn(
  assistantAgentId: string,
  runId: string,
  role: FinancialTeamRole | "synthesis",
  payload: FinancialTeamTurnAttachRequest,
): Promise<FinancialTeamRun> {
  return fetchJson<FinancialTeamRun>(`${rootPath(assistantAgentId)}/runs/${encodeURIComponent(runId)}/turns/${role}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** Starts or recovers one exact primary analyst submission behind the server role guard. */
export function submitFinancialTeamPrimaryRole(
  assistantAgentId: string,
  runId: string,
  role: Extract<FinancialTeamRole, "market" | "fundamental" | "news">,
): Promise<FinancialTeamRun> {
  return fetchJson<FinancialTeamRun>(`${rootPath(assistantAgentId)}/runs/${encodeURIComponent(runId)}/analysts/${role}/submit`, {
    method: "POST",
  });
}

/** Server checks each exact analyst turn's final_answer before forwarding it to the assistant Session. */
export function submitFinancialTeamSynthesis(assistantAgentId: string, runId: string): Promise<FinancialTeamRun> {
  return fetchJson<FinancialTeamRun>(`${rootPath(assistantAgentId)}/runs/${encodeURIComponent(runId)}/synthesis`, {
    method: "POST",
  });
}

/** Checks the live transcript, saved reservation and team bindings before showing recovery. */
export function fetchFinancialTeamSynthesisRecoveryStatus(
  assistantAgentId: string,
  runId: string,
  options?: { signal?: AbortSignal },
): Promise<FinancialTeamSynthesisRecoveryStatus> {
  return fetchJson<FinancialTeamSynthesisRecoveryStatus>(
    `${rootPath(assistantAgentId)}/runs/${encodeURIComponent(runId)}/synthesis/recovery`,
    { signal: options?.signal },
  );
}

/** Resumes only the synthesis stage on an existing, re-validated run. */
export function recoverFinancialTeamSynthesis(
  assistantAgentId: string,
  runId: string,
): Promise<FinancialTeamRun> {
  return fetchJson<FinancialTeamRun>(
    `${rootPath(assistantAgentId)}/runs/${encodeURIComponent(runId)}/synthesis/recovery`,
    { method: "POST" },
  );
}

/** Starts two separate native bull/bear Sessions from the same verified analyst evidence. */
export function submitFinancialTeamDebate(assistantAgentId: string, runId: string): Promise<FinancialTeamRun> {
  return fetchJson<FinancialTeamRun>(`${rootPath(assistantAgentId)}/runs/${encodeURIComponent(runId)}/debate`, {
    method: "POST",
  });
}
