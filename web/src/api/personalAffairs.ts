import { fetchJson } from "./client";
import type {
  PersonalAffairAddRequest,
  PersonalAffairKind,
  PersonalAffairList,
  PersonalAffairMutationResponse,
  PersonalAffairStatus,
} from "./types";

function affairsBase(agentId: string): string {
  return `/api/agents/${encodeURIComponent(agentId)}/plugins/personal-affairs/affairs`;
}

export function fetchPersonalAffairs(
  agentId: string,
  options?: {
    kind?: PersonalAffairKind | "";
    status?: PersonalAffairStatus | "";
    signal?: AbortSignal;
  },
): Promise<PersonalAffairList> {
  const params = new URLSearchParams();
  if (options?.kind) params.set("kind", options.kind);
  if (options?.status) params.set("status", options.status);
  const suffix = params.size ? `?${params.toString()}` : "";
  return fetchJson<PersonalAffairList>(`${affairsBase(agentId)}${suffix}`, {
    signal: options?.signal,
  });
}

export function addPersonalAffair(
  agentId: string,
  payload: PersonalAffairAddRequest,
): Promise<PersonalAffairMutationResponse> {
  return fetchJson<PersonalAffairMutationResponse>(affairsBase(agentId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function postItemAction(
  agentId: string,
  itemId: string,
  action: "complete" | "cancel" | "reopen",
): Promise<PersonalAffairMutationResponse> {
  return fetchJson<PersonalAffairMutationResponse>(
    `${affairsBase(agentId)}/${encodeURIComponent(itemId)}/${action}`,
    { method: "POST" },
  );
}

export function completePersonalAffair(agentId: string, itemId: string): Promise<PersonalAffairMutationResponse> {
  return postItemAction(agentId, itemId, "complete");
}

export function cancelPersonalAffair(agentId: string, itemId: string): Promise<PersonalAffairMutationResponse> {
  return postItemAction(agentId, itemId, "cancel");
}

export function reopenPersonalAffair(agentId: string, itemId: string): Promise<PersonalAffairMutationResponse> {
  return postItemAction(agentId, itemId, "reopen");
}

export function setPersonalAffairDue(
  agentId: string,
  itemId: string,
  dueAt: string,
): Promise<PersonalAffairMutationResponse> {
  return fetchJson<PersonalAffairMutationResponse>(
    `${affairsBase(agentId)}/${encodeURIComponent(itemId)}/due`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dueAt }),
    },
  );
}
