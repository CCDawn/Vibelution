import { fetchJson } from "./client";
import type {
  PersonalAssistantHumanAttentionResponse,
  PersonalAssistantSettings,
  PersonalAssistantSettingsResponse,
} from "./types/personalAssistant";

export function fetchPersonalAssistantSettings(options?: { signal?: AbortSignal }): Promise<PersonalAssistantSettingsResponse> {
  return fetchJson("/api/personal-assistant/settings", { signal: options?.signal });
}

/** Partial settings patch; only provided keys are updated server-side. */
export function updatePersonalAssistantSettings(payload: {
  displayName?: string;
  preferences?: Partial<PersonalAssistantSettings["preferences"]>;
}): Promise<PersonalAssistantSettingsResponse> {
  return fetchJson("/api/personal-assistant/settings", {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function fetchPersonalAssistantHumanAttention(options?: { signal?: AbortSignal }): Promise<PersonalAssistantHumanAttentionResponse> {
  return fetchJson("/api/personal-assistant/human-attention", { signal: options?.signal });
}
