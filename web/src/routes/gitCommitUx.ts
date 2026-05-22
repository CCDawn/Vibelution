import type { GitStatusFile } from "../api/types";

export type GitCommitBlockReason = "no_selection" | "empty_message" | "committing" | null;
export type GitAiDraftBlockReason = "no_selection" | "generating" | null;

export function getGitCommitBlockReason(
  selectedCount: number,
  commitMessage: string,
  committing: boolean,
): GitCommitBlockReason {
  if (committing) {
    return "committing";
  }
  if (selectedCount <= 0) {
    return "no_selection";
  }
  if (!commitMessage.trim()) {
    return "empty_message";
  }
  return null;
}

export function getGitAiDraftBlockReason(selectedCount: number, generating: boolean): GitAiDraftBlockReason {
  if (generating) {
    return "generating";
  }
  if (selectedCount <= 0) {
    return "no_selection";
  }
  return null;
}

export function getSelectedGitFiles(files: GitStatusFile[], selectedPaths: string[]) {
  const selectedSet = new Set(selectedPaths);
  return files.filter((file) => selectedSet.has(file.path));
}

export function getStagedFilesOutsideSelection(files: GitStatusFile[], selectedPaths: string[]) {
  const selectedSet = new Set(selectedPaths);
  return files.filter((file) => file.staged && !selectedSet.has(file.path));
}
