import { describe, expect, it } from "vitest";

import {
  captureRunningInstanceIds,
  captureShutdownInstanceIds,
  registryEntriesToShutdownInstanceSnapshots,
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

  it("captures transitional isolated rows for shell shutdown", () => {
    expect(
      captureShutdownInstanceIds([
        {
          id: "worktree:starting",
          observedState: "starting",
          phase: "starting",
          pid: 0,
          port: 0,
          window: { open: false }
        },
        {
          id: "worktree:stopping",
          observedState: "stopping",
          phase: "stopping",
          pid: 8123,
          port: 8001,
          window: { open: false }
        },
        {
          id: "worktree:open",
          observedState: "open",
          phase: "steady",
          pid: 0,
          port: 0,
          window: { open: false }
        },
        {
          id: "worktree:partial",
          observedState: "partial",
          phase: "steady",
          pid: 0,
          port: 0,
          window: { open: true }
        },
        {
          id: "worktree:closed",
          observedState: "closed",
          phase: "steady",
          pid: 0,
          port: 8002,
          window: { open: false }
        }
      ])
    ).toEqual(["worktree:starting", "worktree:stopping", "worktree:open", "worktree:partial"]);
  });

  it("uses the registry to capture live rows when snapshot and HTTP sources are unavailable", () => {
    const registrySnapshots = registryEntriesToShutdownInstanceSnapshots({
      "worktree:running": {
        status: "running",
        phase: "steady",
        spawnPid: 8123,
        port: 8001,
        windowPid: 0
      },
      "worktree:failed": {
        status: "failed",
        phase: "failed",
        spawnPid: 8222,
        port: 8002,
        windowPid: 0
      },
      "worktree:open": {
        status: "steady",
        desiredState: "open",
        phase: "steady",
        spawnPid: 0,
        port: 0,
        windowPid: 0
      },
      "worktree:closed": {
        status: "closed",
        phase: "steady",
        spawnPid: 0,
        port: 8003,
        windowPid: 0
      }
    });

    expect(captureShutdownInstanceIds(registrySnapshots)).toEqual([
      "worktree:running",
      "worktree:failed",
      "worktree:open"
    ]);
  });
});
