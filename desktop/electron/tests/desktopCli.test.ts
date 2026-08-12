import { describe, expect, it } from "vitest";
import { applyDesktopCliToEnvironment, parseDesktopCliArgs } from "../src/cli/desktopCli.js";
import { desktopSmokeSummary, desktopSmokeSummaryPath } from "../src/smoke/desktopSmoke.js";
import { desktopWorkbenchCloseCanarySummary, desktopWorkbenchCloseCanarySummaryPath } from "../src/smoke/workbenchCloseCanary.js";

describe("desktop CLI arguments", () => {
  it("does not infer a Workbench-open request from an ordinary duplicate launch", () => {
    expect(parseDesktopCliArgs(["--workspace", "C:/workspace"]).openWorkbench).toBe(false);
  });

  it("maps package smoke arguments onto the existing environment contract", () => {
    const args = parseDesktopCliArgs([
      "--workspace",
      "C:/Users/17533/Desktop/Vibelution",
      "--config",
      "C:/Users/17533/Documents/Vibelution/config/config.toml",
      "--smoke",
      "--open-workbench",
      "--workbench-close-canary"
    ]);

    expect(args).toEqual({
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
      configPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      smoke: true,
      openWorkbench: true,
      workbenchCloseCanary: true
    });
    expect(applyDesktopCliToEnvironment({ NODE_ENV: "production" } as NodeJS.ProcessEnv, args)).toMatchObject({
      NODE_ENV: "production",
      VIBELUTION_WORKSPACE_ROOT: "C:/Users/17533/Desktop/Vibelution",
      VIBELUTION_CONFIG_PATH: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      VIBELUTION_ELECTRON_SMOKE: "1",
      VIBELUTION_ELECTRON_WORKBENCH_CLOSE_CANARY: "1"
    });
  });

  it("keeps smoke summaries redacted and workspace-bound", () => {
    expect(
      desktopSmokeSummary({
        workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
        configPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
        launcherUrl: "http://127.0.0.1:8765/launcher",
        workbenchUrl: "http://127.0.0.1:8000/",
        controlToken: "secret-token",
        packaged: true
      })
    ).toEqual({
      schemaVersion: 1,
      mode: "electron_package_smoke",
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
      operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      packaged: true,
      launcherOrigin: "http://127.0.0.1:8765",
      workbenchOrigin: "http://127.0.0.1:8000",
      controlTokenPresent: true,
      bootstrap: {
        attempted: false,
        parsed: false,
        mode: "",
        launcherBackendPid: 0,
        protocolVersion: 0,
        capabilities: [],
        launcherOrigin: "",
        workbenchOrigin: "",
        errorType: "",
        errorMessage: ""
      },
      shutdown: {
        attempted: false,
        stopPythonLauncher: false,
        stopStatus: "not_requested",
        stoppedPidCount: 0,
        stopError: ""
      }
    });
    expect(desktopSmokeSummaryPath("C:/Users/17533/Desktop/Vibelution").replaceAll("\\", "/")).toBe(
      "C:/Users/17533/Desktop/Vibelution/.runtime/launcher/electron-smoke-summary.json"
    );
  });

  it("records only the acknowledged close transaction for the native Workbench canary", () => {
    expect(
      desktopWorkbenchCloseCanarySummary({
        workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
        configPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
        closeId: "workbench-close-1",
        desktopSessionId: "electron-session-1",
        desktopSessionRevision: 9,
        controlToken: "secret-token"
      })
    ).toEqual({
      schemaVersion: 1,
      mode: "electron_workbench_close_canary",
      phase: "succeeded",
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
      operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      closeId: "workbench-close-1",
      desktopSessionId: "electron-session-1",
      desktopSessionRevision: 9,
      controlTokenPresent: true
    });
    expect(desktopWorkbenchCloseCanarySummaryPath("C:/Users/17533/Desktop/Vibelution").replaceAll("\\", "/")).toBe(
      "C:/Users/17533/Desktop/Vibelution/.runtime/launcher/electron-workbench-close-canary-summary.json"
    );
  });
});
