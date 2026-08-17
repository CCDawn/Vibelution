import { describe, expect, it } from "vitest";

import {
  captureRunningInstanceIds,
  summarizeTrayRestartAllRestore
} from "../src/tray/trayRestartAllCoordinator.js";

describe("tray restart-all coordinator", () => {
  it("captures only currently running branch instances", () => {
    expect(
      captureRunningInstanceIds([
        { id: "main", label: "main", startable: false, stoppable: true },
        { id: "worktree:a", label: "a", startable: true, stoppable: false },
        { id: "worktree:b", label: "b", startable: false, stoppable: true }
      ])
    ).toEqual(["main", "worktree:b"]);
  });

  it("summarizes restore outcomes for tray notifications", () => {
    expect(
      summarizeTrayRestartAllRestore({
        restored: ["main"],
        failed: [{ instanceId: "worktree:a", message: "timeout" }],
        skipped: []
      })
    ).toContain("已恢复 1 个工作区");
  });
});
