import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { ScriptTarget, transpileModule } from "typescript";
import { describe, expect, it, vi } from "vitest";
import {
  completeBootstrapWithoutWaitingForTelemetry,
  drainTelemetryWithDeadline,
  scheduleTelemetryWithoutWaiting
} from "../src/process/launcherBootstrap.js";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));

describe("Electron main startup telemetry", () => {
  it("continues to the startup open when tray telemetry never settles", async () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const marker = "void maybeRestoreTrayRestartAllPending();";
    const begin = source.indexOf(marker) + marker.length;
    const end = source.indexOf("const rawUrl = findVibelutionDeepLinkArg", begin);
    expect(begin).toBeGreaterThan(marker.length);
    expect(end).toBeGreaterThan(begin);
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    const record = vi.fn(() => pending);
    let continued = false;
    const startup = runInNewContext(transpileModule(`(async () => { ${source.slice(begin, end)} })()`, {
      compilerOptions: { target: ScriptTarget.ES2022 },
    }).outputText, {
      launcherBootstrap: {},
      deepLinkRegistration: {},
      trayStartedAtMs: 0,
      electronStartupFields: (fields: unknown) => fields,
      electronStageElapsedMs: () => 10,
      recordElectronSupervisorEvent: record,
      scheduleTelemetryWithoutWaiting,
    }).then(() => { continued = true; });
    try {
      await new Promise<void>((resolve) => setImmediate(resolve));
      expect(continued).toBe(true);
      expect(record).toHaveBeenCalledOnce();
    } finally {
      release();
      await startup;
      await new Promise<void>((resolve) => setImmediate(resolve));
    }
    expect(record.mock.calls.map((call) => (call[1] as { eventCode: string }).eventCode)).toEqual([
      "electron.tray.created",
      "electron.launcher.supervisor.started",
      "electron.launcher_service.started",
      "electron.tray.ready",
    ]);
  });

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

  it("bounds terminal telemetry drain when control-plane I/O never settles", async () => {
    vi.useFakeTimers();
    try {
      const recordTelemetry = vi.fn(() => new Promise<void>(() => undefined));
      let completed = false;
      const drain = drainTelemetryWithDeadline(recordTelemetry, 50).then(() => {
        completed = true;
      });

      await vi.advanceTimersByTimeAsync(49);
      expect(recordTelemetry).toHaveBeenCalledTimes(1);
      expect(completed).toBe(false);

      await vi.advanceTimersByTimeAsync(1);
      await drain;
      expect(completed).toBe(true);
    } finally {
      vi.useRealTimers();
    }
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
    expect(source).toContain("await drainTelemetryWithDeadline(");
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
