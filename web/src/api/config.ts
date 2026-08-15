import { fetchJson } from "./client";
import type { ConfigSummary, ConfigWorkspace } from "./types";

export function fetchPublicConfig(options?: {
  signal?: AbortSignal;
}): Promise<ConfigSummary> {
  return fetchJson<ConfigSummary>("/api/config/public", {
    signal: options?.signal,
  });
}

export function fetchConfigWorkspace(options?: {
  signal?: AbortSignal;
}): Promise<ConfigWorkspace> {
  return fetchJson<ConfigWorkspace>("/api/config/workspace", {
    signal: options?.signal,
  });
}
