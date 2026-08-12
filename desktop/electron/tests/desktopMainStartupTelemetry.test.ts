import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));

describe("Electron main startup telemetry", () => {
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
