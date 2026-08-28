import { fetchJson } from "./client";
import type {
  VirtualHumanEpisodicMemory,
  VirtualHumanDiaryEntry,
  VirtualHumanLifeEvent,
  VirtualHumanRelationship,
  VirtualHumanScheduleBundle,
  VirtualHumanSnapshot,
} from "./types";

export function fetchVirtualHumanSnapshot(
  agentId: string,
  options?: { signal?: AbortSignal },
): Promise<VirtualHumanSnapshot> {
  return fetchJson<VirtualHumanSnapshot>(
    `/api/agents/${encodeURIComponent(agentId)}/plugins/virtual-human-life/snapshot`,
    { signal: options?.signal },
  );
}

export function fetchVirtualHumanSchedule(
  agentId: string,
  options?: { localDate?: string; signal?: AbortSignal },
): Promise<VirtualHumanScheduleBundle> {
  const search = new URLSearchParams();
  if (options?.localDate) {
    search.set("localDate", options.localDate);
  }
  const suffix = search.toString();
  const path = `/api/agents/${encodeURIComponent(agentId)}/plugins/virtual-human-life/schedule`;
  return fetchJson<VirtualHumanScheduleBundle>(suffix ? `${path}?${suffix}` : path, {
    signal: options?.signal,
  });
}

export function fetchVirtualHumanEvents(
  agentId: string,
  options?: { localDate?: string; limit?: number; signal?: AbortSignal },
): Promise<VirtualHumanLifeEvent[]> {
  const search = new URLSearchParams();
  if (options?.localDate) {
    search.set("localDate", options.localDate);
  }
  if (options?.limit != null) {
    search.set("limit", String(options.limit));
  }
  const suffix = search.toString();
  const path = `/api/agents/${encodeURIComponent(agentId)}/plugins/virtual-human-life/events`;
  return fetchJson<VirtualHumanLifeEvent[]>(suffix ? `${path}?${suffix}` : path, {
    signal: options?.signal,
  });
}

export function fetchVirtualHumanDiary(
  agentId: string,
  options?: { localDate?: string; limit?: number; signal?: AbortSignal },
): Promise<VirtualHumanDiaryEntry[]> {
  const search = new URLSearchParams();
  if (options?.localDate) {
    search.set("localDate", options.localDate);
  }
  if (options?.limit != null) {
    search.set("limit", String(options.limit));
  }
  const suffix = search.toString();
  const path = `/api/agents/${encodeURIComponent(agentId)}/plugins/virtual-human-life/diary`;
  return fetchJson<VirtualHumanDiaryEntry[]>(suffix ? `${path}?${suffix}` : path, {
    signal: options?.signal,
  });
}

export function fetchVirtualHumanRelationships(
  agentId: string,
  options?: { signal?: AbortSignal },
): Promise<VirtualHumanRelationship[]> {
  return fetchJson<VirtualHumanRelationship[]>(
    `/api/agents/${encodeURIComponent(agentId)}/plugins/virtual-human-life/relationships`,
    { signal: options?.signal },
  );
}

export function fetchVirtualHumanMemories(
  agentId: string,
  options?: { limit?: number; signal?: AbortSignal },
): Promise<VirtualHumanEpisodicMemory[]> {
  const search = new URLSearchParams();
  if (options?.limit != null) {
    search.set("limit", String(options.limit));
  }
  const suffix = search.toString();
  const path = `/api/agents/${encodeURIComponent(agentId)}/plugins/virtual-human-life/memories`;
  return fetchJson<VirtualHumanEpisodicMemory[]>(suffix ? `${path}?${suffix}` : path, {
    signal: options?.signal,
  });
}
