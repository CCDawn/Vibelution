import { describe, expect, it, vi } from "vitest";

import type { LauncherStatus } from "../api/types";
import {
  applyBeforeUnloadProjectCloseGuard,
  buildProjectWindowCloseBlockedTelemetry,
  clearControlledProjectLifecycleOperation,
  hasRecentControlledProjectLifecycleOperation,
  markControlledProjectLifecycleOperation,
  projectWindowCloseGuardMessage,
  shouldBlockProjectWindowClose,
  shouldBlockWorkbenchWindowClose,
} from "./projectCloseGuard";

function makeCookieDocument() {
  const store = new Map<string, string>();
  return {
    get cookie() {
      return [...store.entries()].map(([key, value]) => `${key}=${value}`).join("; ");
    },
    set cookie(value: string) {
      const [pair, ...directives] = value.split(";").map((item) => item.trim());
      const separator = pair.indexOf("=");
      const name = separator >= 0 ? pair.slice(0, separator) : pair;
      const cookieValue = separator >= 0 ? pair.slice(separator + 1) : "";
      const maxAge = directives.find((item) => item.toLowerCase().startsWith("max-age="))?.slice("max-age=".length);
      if (maxAge === "0") {
        store.delete(name);
        return;
      }
      store.set(name, cookieValue);
    },
  };
}

function makeLauncherStatus(overrides: Partial<LauncherStatus["projectBundle"]> = {}): LauncherStatus {
  const projectBundle: LauncherStatus["projectBundle"] = {
    schemaVersion: 1,
    id: "vibelution",
    mode: "bundled",
    desiredState: "open",
    observedState: "open",
    phase: "running",
    overallState: "ready",
    statusLine: "Workbench is running.",
    url: "http://127.0.0.1:8000",
    lastReason: "",
    failureMessage: "",
    lastOperation: {
      reason: "",
      source: "",
      transitionAt: "",
    },
    components: [],
    backend: {
      pid: 123,
      alive: true,
      healthy: true,
      port: 8000,
      portListening: true,
      portOwnerPid: 123,
      portConflict: false,
    },
    frontend: {
      mode: "bundled_static_dist",
      distReady: true,
      orphaned: false,
    },
    browser: {
      managed: true,
      windowPid: 456,
      alive: true,
    },
    ...overrides,
  };

  return {
    launcher: {
      mode: "control",
      phase: "running",
      stableControlPlane: true,
      controlPlane: {
        independent: true,
        adapter: "launcher",
        nextPhase: "",
        url: "http://127.0.0.1:8765/launcher",
        port: 8765,
      },
      message: "",
    },
    projectBundle,
    lifecycleProof: {
      overallState: projectBundle.overallState,
      overallLabel: projectBundle.overallState,
      summary: projectBundle.statusLine,
      verifiedAt: "",
      desiredState: projectBundle.desiredState,
      observedState: projectBundle.observedState,
      phase: projectBundle.phase,
      browserManaged: projectBundle.browser.managed,
      projectRootMatches: true,
      components: [],
      activeWorkRuns: {
        count: 0,
        kinds: [],
        items: [],
      },
      residualProcesses: {
        count: 0,
        items: [],
      },
    },
    runtimeManager: {
      running: true,
      runtimeState: "running",
      managerPid: 789,
      stateVersion: 1,
    },
  } as LauncherStatus;
}

describe("project close guard", () => {
  it("blocks Launcher window closing while the project backend or browser is running", () => {
    expect(shouldBlockProjectWindowClose(makeLauncherStatus())).toBe(true);
  });

  it("blocks partial project states even when the managed browser is already missing", () => {
    expect(
      shouldBlockProjectWindowClose(
        makeLauncherStatus({
          observedState: "partial",
          overallState: "partial",
          browser: {
            managed: true,
            windowPid: 0,
            alive: false,
          },
        }),
      ),
    ).toBe(true);
  });

  it("allows closing after the project is proven closed", () => {
    expect(
      shouldBlockProjectWindowClose(
        makeLauncherStatus({
          desiredState: "closed",
          observedState: "closed",
          phase: "closed",
          overallState: "closed",
          backend: {
            pid: 0,
            alive: false,
            healthy: false,
            port: 8000,
            portListening: false,
            portOwnerPid: 0,
            portConflict: false,
          },
          browser: {
            managed: true,
            windowPid: 0,
            alive: false,
          },
        }),
      ),
    ).toBe(false);
  });

  it("allows controlled lifecycle operations to proceed without a close prompt", () => {
    expect(shouldBlockProjectWindowClose(makeLauncherStatus(), { lifecycleOperationInFlight: true })).toBe(false);
  });

  it("keeps workbench direct window closes blocked outside controlled actions", () => {
    expect(
      shouldBlockWorkbenchWindowClose({
        shutdownRequested: false,
        restartRequested: false,
        runtimeControllerState: "managed",
      }),
    ).toBe(true);
    expect(
      shouldBlockWorkbenchWindowClose({
        shutdownRequested: true,
        restartRequested: false,
        runtimeControllerState: "managed",
      }),
    ).toBe(false);
    expect(
      shouldBlockWorkbenchWindowClose({
        shutdownRequested: false,
        restartRequested: true,
        runtimeControllerState: "managed",
      }),
    ).toBe(false);
    expect(
      shouldBlockWorkbenchWindowClose({
        frontendRefreshRequested: true,
        shutdownRequested: false,
        restartRequested: false,
        runtimeControllerState: "managed",
      }),
    ).toBe(false);
  });

  it("shares short-lived controlled lifecycle intent with the workbench window", () => {
    const documentLike = makeCookieDocument();

    markControlledProjectLifecycleOperation("stop", documentLike, 1_000);

    expect(hasRecentControlledProjectLifecycleOperation(documentLike, 2_000)).toBe(true);
    expect(
      shouldBlockWorkbenchWindowClose({
        controlledLifecycleOperationInFlight: hasRecentControlledProjectLifecycleOperation(documentLike, 2_000),
        shutdownRequested: false,
        restartRequested: false,
        runtimeControllerState: "managed",
      }),
    ).toBe(false);
    expect(hasRecentControlledProjectLifecycleOperation(documentLike, 123_001)).toBe(false);

    clearControlledProjectLifecycleOperation(documentLike);

    expect(hasRecentControlledProjectLifecycleOperation(documentLike, 2_500)).toBe(false);
  });

  it("does not treat Launcher start as a controlled close operation", () => {
    const documentLike = makeCookieDocument();

    markControlledProjectLifecycleOperation("start", documentLike, 1_000);

    expect(hasRecentControlledProjectLifecycleOperation(documentLike, 2_000)).toBe(false);
  });

  it("arms a browser beforeunload confirmation", () => {
    const event = {
      preventDefault: vi.fn(),
      returnValue: "",
    } as unknown as BeforeUnloadEvent;

    expect(applyBeforeUnloadProjectCloseGuard(event, "Stop the project first.")).toBe("Stop the project first.");
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(event.returnValue).toBe("Stop the project first.");
  });

  it("builds bounded telemetry for blocked close attempts", () => {
    expect(buildProjectWindowCloseBlockedTelemetry({ surface: "launcher", status: makeLauncherStatus() })).toMatchObject({
      phase: "lifecycle",
      eventCode: "launcher.window_close.blocked_project_running",
      level: "warning",
      fields: {
        guard: "project_running_close_guard",
        surface: "launcher",
        overallState: "ready",
        backendAlive: true,
        browserAlive: true,
      },
    });
    expect(projectWindowCloseGuardMessage("zh", "launcher")).toContain("请先点击");
    expect(projectWindowCloseGuardMessage("en", "workbench")).toContain("power menu");
  });
});
