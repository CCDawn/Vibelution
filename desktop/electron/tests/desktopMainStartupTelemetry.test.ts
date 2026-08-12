import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { completeBootstrapWithoutWaitingForTelemetry } from "../src/process/launcherBootstrap.js";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));

describe("Electron main startup telemetry", () => {
  it("resolves bootstrap without waiting for telemetry I/O", async () => {
    let releaseTelemetry: (() => void) | null = null;
    const telemetryPending = new Promise<void>((resolve) => {
      releaseTelemetry = resolve;
    });
    const recordTelemetry = vi.fn(() => telemetryPending);
    const result = { mode: "attached" as const };

    const bootstrapPromise = Promise.resolve(result).then((resolved) => {
      const completed = completeBootstrapWithoutWaitingForTelemetry(resolved, recordTelemetry);
      expect(recordTelemetry).not.toHaveBeenCalled();
      return completed;
    });

    await expect(bootstrapPromise).resolves.toBe(result);
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(recordTelemetry).toHaveBeenCalledTimes(1);
    releaseTelemetry?.();
    await telemetryPending;
  });

  it("correlates bounded startup stages with the Python startup trace", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain('import { performance } from "node:perf_hooks"');
    expect(source).toContain('VIBELUTION_STARTUP_TRACE_ID');
    expect(source).toContain('eventCode: "electron.startup.control_plane_attached"');
    expect(source).toContain('eventCode: "electron.startup.desktop_session_registered"');
    expect(source).toContain('eventCode: "electron.startup.workbench_window_ready"');
    expect(source).toContain('eventCode: "electron.startup.summary"');
    expect(source).toContain('processElapsedMs: electronStartupElapsedMs()');
    expect(source).toContain('stageDurationMs: electronStageElapsedMs(');
    expect(source).toContain("return completeBootstrapWithoutWaitingForTelemetry(");
    expect(source).toContain("scheduleTelemetryWithoutWaiting(async () => {");
    expect(source).not.toMatch(
      /await recordElectronStartupSummaryOnce\(launcherBootstrap,\s*\{\s*outcome: "succeeded"/u
    );
  });

  it("emits one terminal summary for success or bounded failure without logging command lines", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("let electronStartupSummaryRecorded = false");
    expect(source).toContain("async function recordElectronStartupSummaryOnce(");
    expect(source).toContain('outcome: "succeeded"');
    expect(source).toContain('outcome: "failed"');
    expect(source).toContain("failureStage: electronStartupStage");
    expect(source).not.toContain("startupCommandLine");
    expect(source).not.toContain("startupPrompt");
  });
});
