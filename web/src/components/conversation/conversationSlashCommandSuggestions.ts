import type { SkillLibraryItem } from "../../api/types";

const MAX_SLASH_COMMAND_SUGGESTIONS = 8;

/** Client-only builtin commands; the backend slash protocol is untouched. */
export type BuiltinSlashCommandId = "new_session" | "model" | "compress_context";

export type BuiltinSlashCommand = {
  id: BuiltinSlashCommandId;
  command: string;
  aliases: string[];
  description: string;
};

/** One rendered row of the merged suggestion listbox. */
export type SlashCommandSuggestion = {
  key: string;
  command: string;
  description: string;
  builtin: boolean;
  builtinId?: BuiltinSlashCommandId;
  skill?: SkillLibraryItem;
};

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

function matchesSlashQuery(haystack: string, query: string): boolean {
  if (!query) {
    return true;
  }
  return haystack.toLowerCase().includes(query);
}

function filterSortedSkills(
  skills: SkillLibraryItem[],
  query: string,
): SkillLibraryItem[] {
  return [...skills]
    .sort((left, right) => left.command.localeCompare(right.command))
    .filter((skill) => {
      if (!query) {
        // Keep the legacy empty-query fast path: no haystack, no field demands
        // beyond command (partial skill fixtures stay renderable).
        return true;
      }
      const haystack = [
        skill.command,
        skill.name,
        skill.directoryName,
        skill.description,
        ...(Array.isArray(skill.aliases) ? skill.aliases : []),
      ].join(" ");
      return matchesSlashQuery(haystack, query);
    });
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
  return filterSortedSkills(skills, query).slice(0, Math.max(0, limit));
}

/**
 * Builtin commands first (input order), then skills alphabetically; both are
 * filtered by the current leading-slash query and the merged list is capped.
 */
export function mergeSlashCommandSuggestions(
  builtins: BuiltinSlashCommand[],
  skills: SkillLibraryItem[],
  value: string,
  limit = MAX_SLASH_COMMAND_SUGGESTIONS,
): SlashCommandSuggestion[] {
  if (!shouldShowSlashCommandSuggestions(value)) {
    return [];
  }
  const query = composerSlashCommandQuery(value);
  const merged: SlashCommandSuggestion[] = [];
  for (const builtin of builtins) {
    if (!builtin?.command) {
      continue;
    }
    const haystack = [builtin.command, ...builtin.aliases, builtin.description].join(" ");
    if (!matchesSlashQuery(haystack, query)) {
      continue;
    }
    merged.push({
      key: `builtin:${builtin.id}`,
      command: builtin.command,
      description: builtin.description,
      builtin: true,
      builtinId: builtin.id,
    });
  }
  for (const skill of filterSortedSkills(skills, query)) {
    merged.push({
      key: `skill:${skill.command}`,
      command: skill.command,
      description: skill.description?.trim() || skill.name || skill.directoryName,
      builtin: false,
      skill,
    });
  }
  return merged.slice(0, Math.max(0, limit));
}

/** Cycles instead of clamping so ArrowDown/ArrowUp always reach every option. */
export function moveSlashCommandActiveIndex(index: number, delta: number, length: number): number {
  if (length <= 0) {
    return -1;
  }
  const base = index < 0 ? (delta > 0 ? -1 : 0) : index;
  return (base + delta + length) % length;
}

export function insertSlashCommandSuggestion(value: string, command: string): string {
  if (!shouldShowSlashCommandSuggestions(value)) {
    return value;
  }
  const normalized = String(command || "").trim();
  return normalized ? `${normalized} ` : value;
}
