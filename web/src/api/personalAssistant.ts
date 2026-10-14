import { fetchJson } from "./client";
import type { PersonalAssistantResponse, PersonalAssistantOverview } from "./types/personalAssistant";

export function fetchPersonalAssistant(options?: { signal?: AbortSignal }): Promise<PersonalAssistantResponse> {
  return fetchJson("/api/personal-assistant", { signal: options?.signal });
}

export function createPersonalAssistant(displayName?: string): Promise<PersonalAssistantResponse> {
  return fetchJson("/api/personal-assistant", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(displayName ? { displayName } : {}),
  });
}

export function fetchPersonalAssistantOverview(options?: { signal?: AbortSignal }): Promise<PersonalAssistantOverview> {
  return fetchJson("/api/personal-assistant/overview", { signal: options?.signal });
}
