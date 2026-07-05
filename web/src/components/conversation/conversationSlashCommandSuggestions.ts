import type { SkillLibraryItem } from "../../api/types";

const MAX_SLASH_COMMAND_SUGGESTIONS = 8;

function leadingSlashToken(value: string): string | null {
  const trimmed = String(value || "").trimStart();
  if (!trimmed.startsWith("/")) {
    return null;
  }
  const first = trimmed.split(/\s+/, 1)[0] ?? "";
  if (first.length !== trimmed.length && trimmed.startsWith(`${first} `)) {
    return null;
  }
  return first;
}

export function shouldShowSlashCommandSuggestions(value: string): boolean {
  return leadingSlashToken(value) !== null;
}

export function composerSlashCommandQuery(value: string): string {
  const token = leadingSlashToken(value);
  return token ? token.replace(/^\/+/, "").trim().toLowerCase() : "";
}

export function filterSlashCommandSuggestions(
  skills: SkillLibraryItem[],
  value: string,
  limit = MAX_SLASH_COMMAND_SUGGESTIONS,
): SkillLibraryItem[] {
  if (!shouldShowSlashCommandSuggestions(value)) {
    return [];
  }
  const query = composerSlashCommandQuery(value);
  return [...skills]
    .sort((left, right) => left.command.localeCompare(right.command))
    .filter((skill) => {
      if (!query) {
        return true;
      }
      const haystack = [
        skill.command,
        skill.name,
        skill.directoryName,
        skill.description,
        ...skill.aliases,
      ].join(" ").toLowerCase();
      return haystack.includes(query);
    })
    .slice(0, Math.max(0, limit));
}

export function insertSlashCommandSuggestion(value: string, command: string): string {
  if (!shouldShowSlashCommandSuggestions(value)) {
    return value;
  }
  const normalized = String(command || "").trim();
  return normalized ? `${normalized} ` : value;
}
