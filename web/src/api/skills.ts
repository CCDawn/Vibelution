import { fetchJson } from "./client";
import type { SkillLibraryPayload } from "./types";

export function fetchSkillLibrary(): Promise<SkillLibraryPayload> {
  return fetchJson<SkillLibraryPayload>("/api/skills");
}
