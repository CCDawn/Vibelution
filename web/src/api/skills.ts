import { fetchJson } from "./client";
import type { SkillLibraryDetail, SkillLibraryPayload } from "./types";

export function fetchSkillLibrary(): Promise<SkillLibraryPayload> {
  return fetchJson<SkillLibraryPayload>("/api/skills");
}

export function fetchSkillLibraryDetail(command: string): Promise<SkillLibraryDetail> {
  return fetchJson<SkillLibraryDetail>(`/api/skills/${encodeURIComponent(command)}`);
}
