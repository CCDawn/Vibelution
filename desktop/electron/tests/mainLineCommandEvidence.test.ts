import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  MAIN_LINE_SETTLEMENT_EVENT_CODE,
  mainLineCommandResultPath,
  recordMainLineCommandSettlement,
} from "../src/lifecycle/mainLine/commandEvidence.js";
import type { MainLineQueuedCommand } from "../src/lifecycle/mainLine/commandQueue.js";

function restartCommand(commandId: string): MainLineQueuedCommand {
  return { commandId, type: "restart", operation: "restart", noBrowser: true };
}

function makeRuntimeTree(): { root: string; runtimeManagerDir: string } {
  const root = mkdtempSync(join(tmpdir(), "vibelution-main-line-evidence-"));
  const runtimeManagerDir = join(root, ".runtime", "runtime-manager");
  mkdirSync(runtimeManagerDir, { recursive: true });
  // The daemon state fingerprint gates evidence writes.
  writeFileSync(join(runtimeManagerDir, "state.json"), "{}", "utf8");
  return { root, runtimeManagerDir };
}

describe("mainLineCommandEvidence", () => {
  it("records a rejected restart settlement in results/ and the supervisor fallback", async () => {
    const { root, runtimeManagerDir } = makeRuntimeTree();
    try {
      const startedAtMs = Date.parse("2026-08-20T10:00:00Z");
      const record = await recordMainLineCommandSettlement({
        workspaceRoot: root,
        runtimeManagerDir,
        command: restartCommand("cmd_20260820T100000Z_aabbccdd"),
        result: {
          schemaVersion: 1,
          accepted: false,
          operation: "restart",
          code: "active_work_blocked",
          message: "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。"
        },
        startedAtMs,
        settledAtMs: startedAtMs + 120
      });
      expect(record).toMatchObject({
        source: "electron_main",
        commandId: "cmd_20260820T100000Z_aabbccdd",
        operation: "restart",
        accepted: false,
        ok: false,
        completed: true,
        code: "active_work_blocked"
      });
      const resultPath = mainLineCommandResultPath(runtimeManagerDir, "cmd_20260820T100000Z_aabbccdd");
      expect(existsSync(resultPath)).toBe(true);
      const persisted = JSON.parse(readFileSync(resultPath, "utf8"));
      expect(persisted).toMatchObject({ source: "electron_main", code: "active_work_blocked", runMs: 120 });

      const fallbackPath = join(root, ".runtime", "launcher", "electron-supervisor-events.jsonl");
      const fallback = readFileSync(fallbackPath, "utf8").trim().split("\n").map((line) => JSON.parse(line));
      expect(fallback.at(-1)).toMatchObject({ eventCode: MAIN_LINE_SETTLEMENT_EVENT_CODE });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("records a failed execution with the error type and timeout marker", async () => {
    const { root, runtimeManagerDir } = makeRuntimeTree();
    try {
      const startedAtMs = Date.parse("2026-08-20T10:00:00Z");
      const record = await recordMainLineCommandSettlement({
        workspaceRoot: root,
        runtimeManagerDir,
        command: restartCommand("cmd_20260820T100001Z_eeff0011"),
        error: new Error("main-line restart command exceeded its deadline"),
        timedOut: true,
        startedAtMs,
        settledAtMs: startedAtMs + 900_000
      });
      expect(record).toMatchObject({
        accepted: false,
        completed: false,
        timedOut: true,
        errorType: "Error"
      });
      const persisted = JSON.parse(
        readFileSync(mainLineCommandResultPath(runtimeManagerDir, "cmd_20260820T100001Z_eeff0011"), "utf8")
      );
      expect(persisted.timedOut).toBe(true);
      expect(persisted.message).toContain("exceeded its deadline");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("never overwrites an existing result for the same commandId", async () => {
    const { root, runtimeManagerDir } = makeRuntimeTree();
    try {
      const resultPath = mainLineCommandResultPath(runtimeManagerDir, "cmd_20260820T100002Z_22222222");
      const daemonAck = { commandId: "cmd_20260820T100002Z_22222222", ok: true, code: "handed_off_to_electron" };
      const { writeFileSync } = await import("node:fs");
      mkdirSync(join(runtimeManagerDir, "results"), { recursive: true });
      writeFileSync(resultPath, JSON.stringify(daemonAck), "utf8");
      await recordMainLineCommandSettlement({
        workspaceRoot: root,
        runtimeManagerDir,
        command: restartCommand("cmd_20260820T100002Z_22222222"),
        result: { schemaVersion: 1, accepted: true, operation: "restart" },
        startedAtMs: 0,
        settledAtMs: 10
      });
      expect(JSON.parse(readFileSync(resultPath, "utf8"))).toEqual(daemonAck);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("skips every write when the runtime-manager surface does not exist", async () => {
    const root = mkdtempSync(join(tmpdir(), "vibelution-main-line-evidence-missing-"));
    try {
      const runtimeManagerDir = join(root, "does", "not", "exist");
      const record = await recordMainLineCommandSettlement({
        workspaceRoot: root,
        runtimeManagerDir,
        command: restartCommand("cmd_20260820T100003Z_33333333"),
        result: { schemaVersion: 1, accepted: true, operation: "restart" },
        startedAtMs: 0,
        settledAtMs: 10
      });
      expect(record).toBeNull();
      expect(existsSync(runtimeManagerDir)).toBe(false);
      expect(existsSync(join(root, ".runtime"))).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
