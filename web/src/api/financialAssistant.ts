import { fetchJson } from "./client";

export type FinancialAssistant = {
  agentId: string; agentCode: string; displayName: string; status: string;
  setupStatus: string; directSessionId: string; knowledgeBaseId: string;
  directSessionArchived?: boolean;
  knowledgeReadable: boolean; modelStatus: string; reportStatus: string;
  marketDataStatus: string; newsDelegationStatus: string; privateLedgerStatus: string;
  marketToolStatus?: "assigned" | "upgrade_available" | "not_assigned";
  tradingEnabled: boolean;
};

export function listFinancialAssistants(options?: { signal?: AbortSignal }): Promise<FinancialAssistant[]> {
  return fetchJson<FinancialAssistant[]>("/api/financial-assistants", { signal: options?.signal });
}

export function createFinancialAssistant(): Promise<{ created: boolean; assistant: FinancialAssistant }> {
  return fetchJson("/api/financial-assistants", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ displayName: "炒股智能体" }),
  });
}
