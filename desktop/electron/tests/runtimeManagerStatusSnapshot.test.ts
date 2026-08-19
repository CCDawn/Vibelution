import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { readRuntimeManagerLauncherStatusSummary } from "../src/lifecycle/runtimeManagerStatusSnapshot.js";

describe("readRuntimeManagerLauncherStatusSummary", () => {
  it("maps runtime manager workbench fields into launcher status summary", () => {
    const workspaceRoot = mkdtempSync(join(tmpdir(), "vibelution-rm-status-"));
    const stateDir = join(workspaceRoot, ".runtime", "runtime-manager");
    mkdirSync(stateDir, { recursive: true });
    writeFileSync(
      join(stateDir, "state.json"),
      JSON.stringify({
        runtimeState: "running",
        stateVersion: 42,
        workbench: {
          observedState: "partial",
          lifecycleConsistency: "external_window_owner_pending_ack",
          phase: "closing",
          backendHealthy: false,
          backendPortListening: false
        }
      }),
      "utf8"
    );

    expect(readRuntimeManagerLauncherStatusSummary(workspaceRoot)).toEqual({
      overallState: "ready",
      observedState: "partial",
      lifecycleConsistency: "external_window_owner_pending_ack",
      phase: "closing",
      stateVersion: 42,
      backendHealthy: false,
      backendPortListening: false,
      lifecycleResults: []
    });
  });

  it("reads the expected command file even when more than 32 newer results exist", () => {
    const workspaceRoot = mkdtempSync(join(tmpdir(), "vibelution-rm-status-"));
    const stateDir = join(workspaceRoot, ".runtime", "runtime-manager");
    const resultsDir = join(stateDir, "results");
    mkdirSync(resultsDir, { recursive: true });
    writeFileSync(
      join(stateDir, "state.json"),
      JSON.stringify({
        runtimeState: "running",
        stateVersion: 7,
        workbench: {
          observedState: "partial",
          lifecycleConsistency: "browser_missing",
          phase: "opening",
          backendHealthy: true,
          backendPortListening: true
        }
      }),
      "utf8"
    );
    writeFileSync(
      join(resultsDir, "cmd_2026-01-01T00-00-00_old.json"),
      JSON.stringify({ commandId: "cmd_2026-01-01T00-00-00_old", completed: true, ok: true, generation: 3 }),
      "utf8"
    );
    for (let index = 0; index < 40; index += 1) {
      const commandId = `cmd_2026-08-19T12-${String(index).padStart(2, "0")}-00_noise`;
      writeFileSync(
        join(resultsDir, `${commandId}.json`),
        JSON.stringify({ commandId, completed: true, ok: true }),
        "utf8"
      );
    }

    const summary = readRuntimeManagerLauncherStatusSummary(workspaceRoot, "cmd_2026-01-01T00-00-00_old");
    expect(summary.lifecycleResults[0]).toEqual({
      commandId: "cmd_2026-01-01T00-00-00_old",
      completed: true,
      ok: true,
      generation: 3
    });
    expect(summary.lifecycleResults.some((item) => item.commandId.endsWith("_noise"))).toBe(true);
    expect(summary.lifecycleResults.filter((item) => item.commandId === "cmd_2026-01-01T00-00-00_old")).toHaveLength(1);
  });

  it("does not treat another command completed result as the expected command", () => {
    const workspaceRoot = mkdtempSync(join(tmpdir(), "vibelution-rm-status-"));
    const stateDir = join(workspaceRoot, ".runtime", "runtime-manager");
    const resultsDir = join(stateDir, "results");
    mkdirSync(resultsDir, { recursive: true });
    writeFileSync(join(stateDir, "state.json"), JSON.stringify({ runtimeState: "running", workbench: {} }), "utf8");
    writeFileSync(
      join(resultsDir, "cmd_other.json"),
      JSON.stringify({ commandId: "cmd_other", completed: true, ok: true }),
      "utf8"
    );

    const summary = readRuntimeManagerLauncherStatusSummary(workspaceRoot, "cmd_current");
    expect(summary.lifecycleResults.find((item) => item.commandId === "cmd_current")).toBeUndefined();
    expect(summary.lifecycleResults[0]).toMatchObject({ commandId: "cmd_other", completed: true });
  });
});
