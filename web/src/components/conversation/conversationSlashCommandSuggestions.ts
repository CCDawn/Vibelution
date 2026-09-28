import type { SkillLibraryItem } from "../../api/types";
import { rankByScore, scoreMatch } from "./conversationFuzzyMatch";

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

/**
 * The composer query arrives with its leading slash stripped, so haystacks
 * lead with the slashless command token too; without it the token's own "/"
 * would push every command match down to the substring tier.
 */
function slashlessToken(value: string): string {
  return String(value || "").replace(/^\/+/, "");
}

function skillHaystack(skill: SkillLibraryItem): string {
  return [
    slashlessToken(skill.command),
    skill.command,
    skill.name,
    skill.directoryName,
    skill.description,
    ...(Array.isArray(skill.aliases) ? skill.aliases : []),
  ]
    .join(" ")
    .toLowerCase();
}

function filterSortedSkills(
  skills: SkillLibraryItem[],
  query: string,
): SkillLibraryItem[] {
  const alphabetical = [...skills].sort((left, right) => left.command.localeCompare(right.command));
  if (!query) {
    // Keep the legacy empty-query fast path: no haystack, no field demands
    // beyond command (partial skill fixtures stay renderable).
    return alphabetical;
  }
  // Tiered ranking (prefix > substring > non-CJK subsequence); equal tiers
  // keep the alphabetical order above.
  return rankByScore(alphabetical, query, skillHaystack);
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
 * Candidates are ranked by tiered match score (see conversationFuzzyMatch);
 * equal scores keep the legacy layout: builtins first in input order, then
 * skills alphabetically. The merged list is capped after ranking.
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
  const ranked: Array<{ suggestion: SlashCommandSuggestion; score: number }> = [];
  for (const builtin of builtins) {
    if (!builtin?.command) {
      continue;
    }
    const haystack = [
      slashlessToken(builtin.command),
      builtin.command,
      ...builtin.aliases,
      builtin.description,
    ]
      .join(" ")
      .toLowerCase();
    const score = scoreMatch(query, haystack);
    if (!Number.isFinite(score)) {
      continue;
    }
    ranked.push({
      score,
      suggestion: {
        key: `builtin:${builtin.id}`,
        command: builtin.command,
        description: builtin.description,
        builtin: true,
        builtinId: builtin.id,
      },
    });
  }
  for (const skill of filterSortedSkills(skills, query)) {
    const score = scoreMatch(query, skillHaystack(skill));
    if (!Number.isFinite(score)) {
      continue;
    }
    ranked.push({
      score,
      suggestion: {
        key: `skill:${skill.command}`,
        command: skill.command,
        description: skill.description?.trim() || skill.name || skill.directoryName,
        builtin: false,
        skill,
      },
    });
  }
  // Stable sort: equal scores keep the insertion order above (builtins first
  // in input order, then skills alphabetically).
  ranked.sort((left, right) => left.score - right.score);
  return ranked.map((entry) => entry.suggestion).slice(0, Math.max(0, limit));
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
