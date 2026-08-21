import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  ACTIVE_WORK_STALE_SNAPSHOT_GRACE_MS,
  activeWorkPayloadBlocks,
  listActiveWorkRuns
} from "../src/process/activeWorkGuard.js";

const tempRoots: string[] = [];

afterEach(() => {
  while (tempRoots.length > 0) {
    rmSync(tempRoots.pop() as string, { recursive: true, force: true });
  }
});

function makeWorkspaceRoot(): string {
  const root = mkdtempSync(join(tmpdir(), "vibelution-active-work-"));
  tempRoots.push(root);
  return root;
}

function writeRun(
  workspaceRoot: string,
  runId: string,
  payload: Record<string, unknown>,
  activeRunId: string,
  kind = "chat_turn"
): void {
  const kindDir = join(workspaceRoot, ".runtime", "runtime-manager", "work_runs", kind);
  mkdirSync(join(kindDir, "runs"), { recursive: true });
  writeFileSync(join(kindDir, "index.json"), JSON.stringify({ activeRunId }), "utf8");
  writeFileSync(join(kindDir, "runs", `${runId}.json`), JSON.stringify({
    runKind: "chat_turn",
    runId,
    status: "running",
    ...payload
  }), "utf8");
}

describe("activeWorkGuard", () => {
  it("ignores blocking snapshots older than the six-hour crash-recovery grace", () => {
    const nowMs = Date.parse("2026-08-21T00:00:00.000Z");
    const stale = new Date(nowMs - ACTIVE_WORK_STALE_SNAPSHOT_GRACE_MS - 1).toISOString();
    const fresh = new Date(nowMs - 60 * 60 * 1000).toISOString();

    expect(activeWorkPayloadBlocks({ status: "running", updatedAt: stale }, { nowMs })).toBe(false);
    expect(activeWorkPayloadBlocks({ status: "running", updatedAt: fresh }, { nowMs })).toBe(true);
    expect(activeWorkPayloadBlocks({ status: "running", startedAt: stale }, { nowMs })).toBe(false);
    expect(activeWorkPayloadBlocks({ status: "running", updatedAt: "not-a-timestamp" }, { nowMs })).toBe(true);
  });

  it("keeps the indexed current run blocking while ignoring stale historical runs", () => {
    const workspaceRoot = makeWorkspaceRoot();
    const stale = new Date(Date.now() - ACTIVE_WORK_STALE_SNAPSHOT_GRACE_MS - 1).toISOString();
    writeRun(workspaceRoot, "old-run", { updatedAt: stale }, "current-run");
    writeRun(workspaceRoot, "current-run", { updatedAt: stale }, "current-run");

    expect(listActiveWorkRuns(workspaceRoot)).toEqual([
      { kind: "chat_turn", runId: "current-run", status: "running", sessionId: "" }
    ]);
  });

  it("does not let stale historical supervised worktree runs block lifecycle", () => {
    const workspaceRoot = makeWorkspaceRoot();
    const stale = new Date(Date.now() - ACTIVE_WORK_STALE_SNAPSHOT_GRACE_MS - 1).toISOString();
    const kind = "supervised_worktree_evolution_run";

    writeRun(workspaceRoot, "old-run", { runKind: kind, updatedAt: stale }, "current-run", kind);
    writeRun(workspaceRoot, "current-run", { runKind: kind, updatedAt: stale }, "current-run", kind);

    expect(listActiveWorkRuns(workspaceRoot)).toEqual([
      { kind, runId: "current-run", status: "running", sessionId: "" }
    ]);
  });
});
