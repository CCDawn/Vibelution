import { describe, expect, it } from "vitest";
import {
  applyDesktopCliToEnvironment,
  parseDesktopCliArgs,
  parseDesktopLifecycleLaunchMetadata
} from "../src/cli/desktopCli.js";
import { desktopSmokeSummary, desktopSmokeSummaryPath } from "../src/smoke/desktopSmoke.js";
import { desktopWorkbenchCloseCanarySummary, desktopWorkbenchCloseCanarySummaryPath } from "../src/smoke/workbenchCloseCanary.js";

describe("desktop CLI arguments", () => {
  it("does not infer a Workbench-open request from an ordinary duplicate launch", () => {
    expect(parseDesktopCliArgs(["--workspace", "C:/workspace"]).openWorkbench).toBe(false);
    expect(parseDesktopCliArgs(["--workspace", "C:/workspace"]).projectRoot).toBe("");
  });

  it("parses forwarded shim lifecycle commands without confusing them with paths", () => {
    expect(parseDesktopCliArgs(["--project", "C:/repo", "start"]).lifecycleCommand).toBe("start");
    expect(parseDesktopCliArgs(["--project", "C:/repo", "restart"]).lifecycleCommand).toBe("restart");
    expect(parseDesktopCliArgs(["--project", "C:/repo", "rebuild-and-start"]).lifecycleCommand).toBe(
      "rebuild-and-start"
    );
    expect(parseDesktopCliArgs(["--project", "C:/repo"]).lifecycleCommand).toBe("");
    expect(parseDesktopCliArgs(["--workspace", "C:/repo", "toggle"]).lifecycleCommand).toBe("toggle");
  });

  it("keeps ordinary CLI lifecycle launches as operator-originated", () => {
    expect(
      parseDesktopLifecycleLaunchMetadata(["--project", "C:/repo", "stop"], {})
    ).toEqual({
      command: "stop",
      source: "",
      reason: "",
      stopManager: false,
      explicitlyForwarded: false
    });
  });

  it("does not treat empty inherited provenance variables as a forwarded request", () => {
    expect(
      parseDesktopLifecycleLaunchMetadata(["--project", "C:/repo", "stop"], {
        VIBELUTION_LIFECYCLE_SOURCE: "",
        VIBELUTION_LIFECYCLE_REASON: "",
        VIBELUTION_LIFECYCLE_STOP_MANAGER: ""
      })
    ).toMatchObject({
      command: "stop",
      explicitlyForwarded: false
    });
  });

  it("recognizes the explicit Runtime Manager forwarding markers", () => {
    expect(
      parseDesktopLifecycleLaunchMetadata(
        [
          "--project",
          "C:/repo",
          "stop",
          "--lifecycle-source",
          "web_ui",
          "--lifecycle-reason",
          "web_close_button",
          "--lifecycle-stop-manager",
          "1"
        ],
        {}
      )
    ).toEqual({
      command: "stop",
      source: "web_ui",
      reason: "web_close_button",
      stopManager: true,
      explicitlyForwarded: true
    });
  });

  it("does not mistake forwarding marker values for lifecycle commands", () => {
    expect(
      parseDesktopCliArgs(["--lifecycle-source", "stop", "--lifecycle-reason", "restart"])
    ).toMatchObject({ lifecycleCommand: "" });
  });

  it("parses the Runtime Manager window-level close-window intent with its provenance", () => {
    // core/runtime_manager/workbench_controller.py forwards close_workbench
    // without stopManager as the close-window token through the second-instance
    // channel; the desktop parser must recognize it so the desktop lane can
    // route the window-level close transaction.
    expect(parseDesktopCliArgs(["--workspace", "C:/repo", "close-window"]).lifecycleCommand).toBe(
      "close-window"
    );
    expect(
      parseDesktopLifecycleLaunchMetadata(
        [
          "--workspace",
          "C:/repo",
          "close-window",
          "--lifecycle-source",
          "runtime_manager_queue",
          "--lifecycle-reason",
          "browser_missing_auto_close"
        ],
        {}
      )
    ).toEqual({
      command: "close-window",
      source: "runtime_manager_queue",
      reason: "browser_missing_auto_close",
      stopManager: false,
      explicitlyForwarded: true
    });
  });

  it("accepts environment forwarding markers when an older argv path is used", () => {
    expect(
      parseDesktopLifecycleLaunchMetadata(["--project", "C:/repo", "stop"], {
        VIBELUTION_LIFECYCLE_SOURCE: "runtime_manager_daemon",
        VIBELUTION_LIFECYCLE_REASON: "browser_missing_auto_close",
        VIBELUTION_LIFECYCLE_STOP_MANAGER: "0"
      })
    ).toEqual({
      command: "stop",
      source: "runtime_manager_daemon",
      reason: "browser_missing_auto_close",
      stopManager: false,
      explicitlyForwarded: true
    });
  });

  it("keeps --project as a slot apply path and does not treat it as workspace root", () => {
    const args = parseDesktopCliArgs([
      "--workspace",
      "C:/Users/17533/Desktop/Vibelution",
      "--project",
      "C:/Users/17533/Desktop/Vibelution/.worktrees/task"
    ]);
    expect(args.workspaceRoot).toBe("C:/Users/17533/Desktop/Vibelution");
    expect(args.projectRoot).toBe("C:/Users/17533/Desktop/Vibelution/.worktrees/task");
    expect(applyDesktopCliToEnvironment({ NODE_ENV: "production" } as NodeJS.ProcessEnv, args)).toMatchObject({
      NODE_ENV: "production",
      VIBELUTION_WORKSPACE_ROOT: "C:/Users/17533/Desktop/Vibelution"
    });
    expect(
      applyDesktopCliToEnvironment({} as NodeJS.ProcessEnv, parseDesktopCliArgs(["--project", "C:/worktrees/task"]))
        .VIBELUTION_WORKSPACE_ROOT
    ).toBeUndefined();
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
      projectRoot: "",
      configPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      smoke: true,
      openWorkbench: true,
      workbenchCloseCanary: true,
      lifecycleCommand: ""
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
        stopManagedRuntime: false,
        managedRuntimeError: "",
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
