import type { ConfigWorkspace, GitStatusFile } from "../api/types";
import type { TranslationKey } from "../i18n/dictionary";

export type GitFilter = "all" | "staged" | "unstaged" | "untracked" | "deleted";

export const GIT_FILTERS: GitFilter[] = ["all", "staged", "unstaged", "untracked", "deleted"];

export const GIT_FILTER_LABEL_KEYS = {
  all: "gitFilterAll",
  staged: "gitFilterStaged",
  unstaged: "gitFilterUnstaged",
  untracked: "gitFilterUntracked",
  deleted: "gitFilterDeleted",
} as const satisfies Record<GitFilter, TranslationKey>;

export function gitFilterMatches(file: GitStatusFile, filter: GitFilter) {
  if (filter === "all") {
    return true;
  }
  return Boolean(file[filter]);
}

export function displayGitPath(path: string) {
  return path.replaceAll("\\", "/");
}

export function gitFileName(path: string) {
  return displayGitPath(path).split("/").at(-1) || path;
}

export function formatGitDateTime(value: string, locale: string) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function configuredGitModelId(workspace?: ConfigWorkspace) {
  const gitConfig = workspace?.publicConfig?.git;
  if (!gitConfig || typeof gitConfig !== "object" || Array.isArray(gitConfig)) {
    return "";
  }
  return String((gitConfig as Record<string, unknown>).commit_message_model_ref ?? "").trim();
}
