import { describe, expect, it } from "vitest";

import type { ConfigWorkspace, GitStatusFile } from "../api/types";
import {
  configuredGitModelId,
  displayGitPath,
  formatGitDateTime,
  gitFileName,
  gitFilterMatches,
  type GitFilter,
} from "./gitRouteLogic";

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

describe("gitRouteLogic", () => {
  it("matches files against the active git filter", () => {
    const changed = file("changed.ts", { staged: true, unstaged: false });
    const untracked = file("new.ts", { unstaged: false, untracked: true });

    expect(gitFilterMatches(changed, "all")).toBe(true);
    expect(gitFilterMatches(changed, "staged")).toBe(true);
    expect(gitFilterMatches(changed, "untracked")).toBe(false);
    expect(gitFilterMatches(untracked, "untracked")).toBe(true);
  });

  it("keeps git path display stable across Windows and POSIX paths", () => {
    expect(displayGitPath("web\\src\\routes\\GitRoute.tsx")).toBe("web/src/routes/GitRoute.tsx");
    expect(gitFileName("web\\src\\routes\\GitRoute.tsx")).toBe("GitRoute.tsx");
    expect(gitFileName("README.md")).toBe("README.md");
  });

  it("formats valid commit dates and preserves invalid source values", () => {
    expect(formatGitDateTime("", "en-US")).toBe("-");
    expect(formatGitDateTime("not-a-date", "en-US")).toBe("not-a-date");
    expect(formatGitDateTime("2026-05-21T10:00:00+08:00", "en-US")).toContain("05/21");
  });

  it("reads the configured git commit model defensively", () => {
    const workspace = {
      publicConfig: {
        git: {
          commit_message_model_ref: " relay_openai_gpt_5_5 ",
        },
      },
    } as unknown as ConfigWorkspace;

    expect(configuredGitModelId(workspace)).toBe("relay_openai_gpt_5_5");
    expect(configuredGitModelId({ publicConfig: { git: [] } } as unknown as ConfigWorkspace)).toBe("");
    expect(configuredGitModelId(undefined)).toBe("");
  });

  it("keeps filter type names explicit", () => {
    const filters: GitFilter[] = ["all", "staged", "unstaged", "untracked", "deleted"];
    expect(filters).toHaveLength(5);
  });
});
