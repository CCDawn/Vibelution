import { mkdtempSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  appendSupervisorEventFallback,
  supervisorEventFallbackPath
} from "../src/lifecycle/supervisorEventFallback.js";

const tempDirs: string[] = [];

function makeWorkspaceRoot(): string {
  const dir = mkdtempSync(join(tmpdir(), "supervisor-fallback-"));
  tempDirs.push(dir);
  return dir;
}

afterEach(() => {
  while (tempDirs.length > 0) {
    const dir = tempDirs.pop() as string;
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("supervisorEventFallback", () => {
  it("appends a timestamped JSON line under the workspace runtime dir", () => {
    const workspaceRoot = makeWorkspaceRoot();
    const fixedDate = new Date("2026-08-20T06:03:44.000Z");

    const recorded = appendSupervisorEventFallback(
      workspaceRoot,
      { eventCode: "electron.workbench_close.failed", message: "boom", fields: { closeId: "c1" } },
      () => fixedDate,
    );

    expect(recorded).toBe(true);
    const target = supervisorEventFallbackPath(workspaceRoot);
    expect(target).toBe(join(workspaceRoot, ".runtime", "launcher", "electron-supervisor-events.jsonl"));
    const lines = readFileSync(target, "utf8").trim().split("\n");
    expect(lines).toHaveLength(1);
    expect(JSON.parse(lines[0])).toEqual({
      at: fixedDate.toISOString(),
      eventCode: "electron.workbench_close.failed",
      message: "boom",
      fields: { closeId: "c1" }
    });
  });

  it("rotates the fallback file once it exceeds the size cap", () => {
    const workspaceRoot = makeWorkspaceRoot();
    const target = supervisorEventFallbackPath(workspaceRoot);
    mkdirSync(dirname(target), { recursive: true });
    const oversized = "x".repeat(8 * 1024 * 1024 + 1);
    writeFileSync(target, oversized, "utf8");

    const recorded = appendSupervisorEventFallback(
      workspaceRoot,
      { eventCode: "electron.deep_link.accepted", message: "after rotate" },
    );

    expect(recorded).toBe(true);
    expect(statSync(`${target}.1`).size).toBe(oversized.length);
    expect(readFileSync(target, "utf8")).toContain("after rotate");
  });

  it("reports failure instead of throwing when the workspace root is not writable", () => {
    const recorded = appendSupervisorEventFallback(
      join(makeWorkspaceRoot(), "missing-root\0invalid"),
      { eventCode: "electron.workbench_close.failed", message: "unwritable" },
    );
    expect(recorded).toBe(false);
  });
});
