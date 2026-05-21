import { describe, expect, it } from "vitest";

import { buildGitDiffRows } from "./gitDiffRows";

const TEXT = {
  loadingText: "Loading",
  binaryText: "Binary file",
  emptyText: "Empty diff",
};

describe("buildGitDiffRows", () => {
  it("marks unified diff additions and removals without treating file headers as changes", () => {
    const rows = buildGitDiffRows({
      ...TEXT,
      diff: [
        "diff --git a/app.ts b/app.ts",
        "index 111..222 100644",
        "--- a/app.ts",
        "+++ b/app.ts",
        "@@ -3,2 +3,2 @@",
        "-old value",
        "+new value",
        " context",
      ].join("\n"),
    });

    expect(rows.map((row) => row.tone)).toEqual([
      "meta",
      "meta",
      "meta",
      "meta",
      "hunk",
      "removed",
      "added",
      "context",
    ]);
    expect(rows[5]).toMatchObject({ marker: "-", text: "old value", oldLine: 3, newLine: null });
    expect(rows[6]).toMatchObject({ marker: "+", text: "new value", oldLine: null, newLine: 3 });
    expect(rows[7]).toMatchObject({ text: "context", oldLine: 4, newLine: 4 });
  });

  it("renders untracked file content as added lines", () => {
    const rows = buildGitDiffRows({ ...TEXT, content: "first\nsecond" });

    expect(rows).toEqual([
      { id: "content-0", tone: "added", marker: "+", text: "first", oldLine: null, newLine: 1 },
      { id: "content-1", tone: "added", marker: "+", text: "second", oldLine: null, newLine: 2 },
    ]);
  });

  it("uses single informational rows for loading, binary, and empty states", () => {
    expect(buildGitDiffRows({ ...TEXT, loading: true })[0]).toMatchObject({ tone: "empty", text: "Loading" });
    expect(buildGitDiffRows({ ...TEXT, binary: true })[0]).toMatchObject({ tone: "meta", text: "Binary file" });
    expect(buildGitDiffRows(TEXT)[0]).toMatchObject({ tone: "empty", text: "Empty diff" });
  });
});
