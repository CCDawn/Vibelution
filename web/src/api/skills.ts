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
