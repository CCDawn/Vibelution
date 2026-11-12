import { fetchJson } from "./client";
import type { SkillLibraryDetail, SkillLibraryPayload } from "./types";

export function fetchSkillLibrary(): Promise<SkillLibraryPayload> {
  return fetchJson<SkillLibraryPayload>("/api/skills");
}

export function fetchSkillLibraryDetail(command: string, source = ""): Promise<SkillLibraryDetail> {
  // `source` narrows the lookup to one skill root (codex / agents / other) so
  // same-command skills under different roots stay distinguishable. Omitting
  // it keeps the server's first-match behaviour for existing callers.
  const query = source ? `?source=${encodeURIComponent(source)}` : "";
  return fetchJson<SkillLibraryDetail>(`/api/skills/${encodeURIComponent(command)}${query}`);
}


export type SkillLibrarySource = {
  repo: string;
  ref: string;
  commit: string;
  commitCount: number;
  skills: string[];
  skillCount: number;
  lastImportedAt: string;
};

export type SkillLibrarySourcesPayload = {
  schemaVersion: number;
  sources: SkillLibrarySource[];
};

export function fetchSkillLibrarySources(): Promise<SkillLibrarySourcesPayload> {
  return fetchJson<SkillLibrarySourcesPayload>("/api/skill-library/sources");
}

export function syncSkillLibrary(repo = ""): Promise<{ syncedCount: number }> {
  return fetchJson<{ syncedCount: number }>("/api/skill-library/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo }),
  });
}
