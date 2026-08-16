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
});
