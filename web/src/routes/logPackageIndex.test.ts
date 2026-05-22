import { describe, expect, it } from "vitest";

import type { FileTreeNode } from "../api/types";
import { buildLogPackageIndex, logPackageFilePaths } from "./logPackageIndex";

function file(path: string): FileTreeNode {
  return {
    name: path.split("/").at(-1) ?? path,
    path,
    type: "file",
  };
}

function dir(name: string, children: FileTreeNode[]): FileTreeNode {
  return {
    name,
    path: name,
    type: "directory",
    children,
  };
}

describe("logPackageIndex", () => {
  it("turns top-level directories into user-facing log packages", () => {
    const packages = buildLogPackageIndex([
      dir("harness_reports", [file("harness_reports/harness_20260522.json")]),
      dir("conversations", [file("conversations/session-20260522.jsonl")]),
    ]);

    expect(packages.map((item) => [item.id, item.titleZh, item.fileCount])).toEqual([
      ["conversations", "对话日志", 1],
      ["harness_reports", "测试运行报告", 1],
    ]);
  });

  it("keeps root-level files inside a root log package instead of a directory tree", () => {
    const packages = buildLogPackageIndex([
      file("debug_20260522.log"),
      dir("self_evolution", [file("self_evolution/run.jsonl")]),
    ]);

    expect(packages[0]).toMatchObject({
      id: "__root__",
      titleZh: "根目录日志",
      fileCount: 1,
      files: [{ name: "debug_20260522.log", path: "debug_20260522.log" }],
    });
  });

  it("filters packages by file path and exposes visible file paths for bulk actions", () => {
    const packages = buildLogPackageIndex(
      [
        dir("harness_reports", [file("harness_reports/pass.json"), file("harness_reports/fail.json")]),
        dir("raw", [file("raw/backend.stdout.log")]),
      ],
      "fail",
    );

    expect(packages).toHaveLength(1);
    expect(packages[0].files).toEqual([{ name: "fail.json", path: "harness_reports/fail.json" }]);
    expect(logPackageFilePaths(packages)).toEqual(["harness_reports/fail.json"]);
  });
});
