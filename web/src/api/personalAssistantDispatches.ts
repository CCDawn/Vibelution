import { fetchJson } from "./client";

export const PERSONAL_ASSISTANT_DISPATCH_LIMIT = 50;

/** Closed enum from the dispatch projection; values arrive from the backend. */
export type PersonalAssistantDispatchStatus = "pending" | "consumed" | "revoked";

export type PersonalAssistantDispatchReceipt = {
  messageId: string;
  sourceAgentId: string;
  sourceAgentName: string;
  summary: string;
  status: PersonalAssistantDispatchStatus;
  receivedAt: string;
};

export type PersonalAssistantDispatch = {
  messageId: string;
  threadId: string | null;
  targetAgentId: string;
  targetAgentName: string;
  targetSessionId: string;
  summary: string;
  deliveryStatus: PersonalAssistantDispatchStatus;
  sentAt: string;
  receipts: PersonalAssistantDispatchReceipt[];
};

export type PersonalAssistantDispatchList = {
  assistantAgentId: string;
  dispatches: PersonalAssistantDispatch[];
  unmatchedReceipts: PersonalAssistantDispatchReceipt[];
  generatedAt: string;
};

/** Query key lives beside the transport (teamWorkflowQueryKeys precedent); api/queryKeys.ts stays untouched. */
export function personalAssistantDispatchesQueryKey(agentId: string, limit = PERSONAL_ASSISTANT_DISPATCH_LIMIT) {
  return ["personal-assistant", "dispatches", agentId, limit] as const;
}

export function personalAssistantDispatchesUrl(limit = PERSONAL_ASSISTANT_DISPATCH_LIMIT) {
  const params = new URLSearchParams({ limit: String(limit) });
  return `/api/personal-assistant/dispatches?${params.toString()}`;
}

/** The endpoint is scoped to the singleton personal assistant; agentId only keys the client cache. */
export function fetchPersonalAssistantDispatches(options?: {
  limit?: number;
  signal?: AbortSignal;
}): Promise<PersonalAssistantDispatchList> {
  return fetchJson<PersonalAssistantDispatchList>(personalAssistantDispatchesUrl(options?.limit), {
    signal: options?.signal,
  });
}
