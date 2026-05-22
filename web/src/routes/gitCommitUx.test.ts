import { describe, expect, it } from "vitest";

import type { GitStatusFile } from "../api/types";
import {
  getGitAiDraftBlockReason,
  getGitCommitBlockReason,
  getSelectedGitFiles,
  getStagedFilesOutsideSelection,
} from "./gitCommitUx";

function file(path: string, overrides: Partial<GitStatusFile> = {}): GitStatusFile {
  return {
    path,
    status: " M",
    statusLabel: "modified",
    staged: false,
    unstaged: true,
    untracked: false,
    deleted: false,
    oldPath: "",
    ...overrides,
  };
}

describe("gitCommitUx", () => {
  it("explains why commit is blocked before the request is sent", () => {
    expect(getGitCommitBlockReason(0, "feat: change", false)).toBe("no_selection");
    expect(getGitCommitBlockReason(1, "   ", false)).toBe("empty_message");
    expect(getGitCommitBlockReason(1, "feat: change", false, 1)).toBe("staged_outside_selection");
    expect(getGitCommitBlockReason(1, "feat: change", true)).toBe("committing");
    expect(getGitCommitBlockReason(1, "feat: change", false)).toBeNull();
  });

  it("explains why AI drafting is blocked", () => {
    expect(getGitAiDraftBlockReason(0, false)).toBe("no_selection");
    expect(getGitAiDraftBlockReason(1, true)).toBe("generating");
    expect(getGitAiDraftBlockReason(1, false)).toBeNull();
  });

  it("separates selected commit scope from staged files outside the scope", () => {
    const files = [
      file("selected.ts", { staged: true, unstaged: false }),
      file("outside.ts", { staged: true, unstaged: false }),
      file("draft.ts", { staged: false, unstaged: true }),
    ];

    expect(getSelectedGitFiles(files, ["selected.ts"]).map((item) => item.path)).toEqual(["selected.ts"]);
    expect(getStagedFilesOutsideSelection(files, ["selected.ts"]).map((item) => item.path)).toEqual(["outside.ts"]);
  });
});
