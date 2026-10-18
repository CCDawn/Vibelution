import { fetchJson } from "./client";
import type {
  PersonalAssistantModelResponse,
  PersonalAssistantOverview,
  PersonalAssistantResponse,
  PersonalAssistantSettings,
  PersonalAssistantSettingsResponse,
} from "./types/personalAssistant";

export function fetchPersonalAssistant(options?: { signal?: AbortSignal }): Promise<PersonalAssistantResponse> {
  return fetchJson("/api/personal-assistant", { signal: options?.signal });
}

export function createPersonalAssistant(displayName?: string): Promise<PersonalAssistantResponse> {
  return fetchJson("/api/personal-assistant", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(displayName ? { displayName } : {}),
  });
}

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

/** Rebinds the assistant dialogue model; server validates the whitelist. */
export function updatePersonalAssistantModel(modelId: string): Promise<PersonalAssistantModelResponse> {
  return fetchJson("/api/personal-assistant/settings/model", {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ modelId }),
  });
}

export async function fetchPersonalAssistantOverview(options?: { signal?: AbortSignal }): Promise<PersonalAssistantOverview> {
  const agents = new Map<string, PersonalAssistantOverview["agents"][number]>();
  const sessions = new Map<string, PersonalAssistantOverview["sessions"][number]>();
  const attention = new Map<string, PersonalAssistantOverview["attention"][number]>();
  let offset = 0;
  let revision: string | undefined;
  for (let pageIndex = 0; pageIndex < 100; pageIndex += 1) {
    const path = offset === 0 ? "/api/personal-assistant/overview" : `/api/personal-assistant/overview?offset=${offset}`;
    const page = await fetchJson<PersonalAssistantOverview>(path, { signal: options?.signal });
    if (page.pagination && page.pagination.offset !== offset) throw new Error("平台概览分页位置不匹配，请刷新后重试。");
    if (pageIndex === 0) revision = page.pagination?.revision;
    else if (page.pagination?.revision !== revision) throw new Error("平台概览在分页期间已变化，请刷新后重试。");
    page.agents.forEach(row => agents.set(row.id, row));
    page.sessions.forEach(row => sessions.set(row.id, row));
    page.attention.forEach(row => attention.set(row.id, row));
    const next = page.pagination?.nextOffset;
    if (next === null || next === undefined) {
      // counts.waiting/failed describe native Session approval/error rows.
      // The first-page knowledge/anomaly dock is an additive extension.
      const sessionAttentionCount = [...attention.values()].filter(row => row.kind === "approval" || row.kind === "error").length;
      if (agents.size !== page.counts.agents || sessions.size !== page.counts.sessions
        || sessionAttentionCount !== page.counts.waiting + page.counts.failed) {
        throw new Error("平台概览列表不完整或已变化，请刷新后重试。");
      }
      const { pagination: _pagination, ...overview } = page;
      return { ...overview, agents: [...agents.values()], sessions: [...sessions.values()], attention: [...attention.values()] };
    }
    if (!Number.isSafeInteger(next) || next <= offset) throw new Error("平台概览分页未前进，请刷新后重试。");
    offset = next;
  }
  throw new Error("平台概览超过分页读取上限，未能完整加载。");
}
