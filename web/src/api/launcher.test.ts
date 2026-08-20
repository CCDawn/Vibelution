import { afterEach, describe, expect, it, vi } from "vitest";

import { resetControlTokenForTests } from "./client";
import {
  cancelRuntimeLifecycleCommand,
  forceStopLauncherBundle,
  getLauncherBranchInstances,
  requestBranchInstanceCleanup,
  requestBranchInstanceLifecycle,
  getLauncherStatus,
  getLauncherState,
  onLauncherStateChanged,
  refreshLauncherState,
  getRuntimeSummary,
  isLauncherControlPlaneNotReady,
  launcherEndpoint,
  LauncherControlPlaneNotReadyError,
  reattachLauncherSupervisor,
  restartLauncherBundle,
  requestWorkbenchWindowCloseOnPageHide,
  saveLauncherWorkbenchWindowMode,
  startLauncherBundle,
  stopLauncherBundle,
  updateLauncherStartupSettings,
} from "./launcher";

type LauncherIpcInvokeResult =
  | { ok: true; payload: unknown }
  | { ok: false; error: { code: string; message: string } };

function stubLauncherIpcBridge(invoke: (payload: unknown) => Promise<LauncherIpcInvokeResult>) {
  vi.stubGlobal("window", {
    location: {
      href: "http://127.0.0.1:8765/launcher",
      origin: "http://127.0.0.1:8765",
    },
  });
  vi.stubGlobal("vibelutionLauncher", {
    launcherInvoke: invoke,
  });
}

describe("launcher api helpers", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    resetControlTokenForTests();
  });

  it("builds canonical launcher restart endpoints", () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/chat",
      },
    });

    expect(launcherEndpoint("status")).toBe("/api/launcher/status");
    expect(launcherEndpoint("restart")).toBe("/api/launcher/restart");
  });

  it("keeps launcher endpoints relative on the Launcher control origin", () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8765/launcher",
      },
    });

    expect(launcherEndpoint("restart")).toBe("/api/launcher/restart");
  });

  it("fetches launcher status as a read-only request", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/chat",
        origin: "http://127.0.0.1:8000",
      },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ launcher: { mode: "standalone_control_plane" } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await getLauncherStatus();

    expect(payload.launcher.mode).toBe("standalone_control_plane");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/launcher/status");
  });

  it("keeps published launcher status extras used by tray and control-plane UI", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/chat",
        origin: "http://127.0.0.1:8000",
      },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        launcher: { mode: "standalone_control_plane" },
        overallState: "open",
        observedState: "open",
        controlPlaneEvidence: { customEvidence: true },
        guardianAdapter: { adapterCount: 1, customGuardian: true },
        customTrayField: "keep-me",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await getLauncherStatus();

    expect(payload.overallState).toBe("open");
    expect(payload.observedState).toBe("open");
    expect(payload.controlPlaneEvidence?.customEvidence).toBe(true);
    expect(payload.guardianAdapter?.customGuardian).toBe(true);
    expect((payload as { customTrayField?: string }).customTrayField).toBe("keep-me");
  });

  it("fetches launcher branch instances as a read-only request", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/launcher",
        origin: "http://127.0.0.1:8000",
      },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ schemaVersion: 1, items: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await getLauncherBranchInstances();

    expect(payload.schemaVersion).toBe(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/launcher/branch-instances");
  });

  it("requests cleanup metadata only when the caller opts in", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/launcher",
        origin: "http://127.0.0.1:8000",
      },
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ schemaVersion: 1, items: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await getLauncherBranchInstances({ cleanupMetadata: true });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/launcher/branch-instances?cleanupMetadata=1");
  });

  it("normalizes stale flat branch-instance payloads before the Launcher renders them", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8765/launcher",
        origin: "http://127.0.0.1:8765",
      },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        schemaVersion: 1,
        currentId: "main",
        items: [{
          id: "main",
          kind: "main",
          branch: "main",
          path: "C:/repo",
          displayPath: ".",
          head: "abc123",
          current: true,
          legacy: false,
          dirty: false,
          checkedOut: true,
          alive: true,
          observedState: "open",
          port: 8002,
          pids: { backend: 1200, window: 0, manager: 1300 },
          promotable: false,
          workbenchTitle: "main 台",
        }],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await getLauncherBranchInstances();
    const item = payload.items[0];

    expect(item.runtime.lifecycleState).toBe("partial");
    expect(item.runtime.backend).toMatchObject({ alive: true, healthy: false, listening: false, port: 8002, pid: 1200 });
    expect(item.runtime.window).toMatchObject({ open: false, pid: 0, title: "main 台" });
    expect(item.startable).toBe(false);
    expect(item.startBlockReason).toBe("launcher_refresh_required");
  });

  it("starts a selected branch instance through the guarded launcher endpoint", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/chat",
        origin: "http://127.0.0.1:8000",
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ accepted: true, operation: "start", instanceId: "worktree:task", port: 8001 }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await requestBranchInstanceLifecycle("worktree:task", "start");

    expect(payload.instanceId).toBe("worktree:task");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/launcher/branch-instances/start");
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(requestInit.method).toBe("POST");
    expect(requestInit.body).toBe(JSON.stringify({ instanceId: "worktree:task" }));
  });

  it("confirms selected branch-instance cleanup through the guarded launcher endpoint", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/launcher",
        origin: "http://127.0.0.1:8000",
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          cleaned: [{ id: "branch:codex/task", actions: ["branch_deleted"] }],
          failed: [],
          skipped: [],
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await requestBranchInstanceCleanup(["branch:codex/task"], true);

    expect(payload.ok).toBe(true);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/launcher/branch-instances/cleanup");
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(requestInit.method).toBe("POST");
    expect(requestInit.body).toBe(JSON.stringify({ instanceIds: ["branch:codex/task"], confirm: true }));
  });

  it("fetches the workbench runtime summary directly instead of through launcher control", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: "ready" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await getRuntimeSummary();

    expect(payload.status).toBe("ready");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/runtime/summary");
  });

  it("uses the reported launcher control origin after status discovery", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/chat",
        origin: "http://127.0.0.1:8000",
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          launcher: {
            mode: "standalone_control_plane",
            controlPlane: {
              url: "http://127.0.0.1:8899/launcher",
            },
          },
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    await getLauncherStatus();
    await expect(restartLauncherBundle()).rejects.toBeInstanceOf(LauncherControlPlaneNotReadyError);

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/launcher/status",
    ]);
  });

  it("starts the bundle through the preload IPC bridge", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const invoke = vi.fn().mockResolvedValue({
      ok: true,
      payload: { accepted: true, operation: "start", launcherMode: "standalone_control_plane" },
    });
    stubLauncherIpcBridge(invoke);

    const payload = await startLauncherBundle();

    expect(payload.operation).toBe("start");
    expect(fetchMock).not.toHaveBeenCalled();
    const request = invoke.mock.calls[0][0] as { path: string; init: { method: string } };
    expect(request.path).toBe("start");
    expect(request.init.method).toBe("POST");
  });

  it("restarts the bundle through the preload IPC bridge", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const invoke = vi.fn().mockResolvedValue({
      ok: true,
      payload: { accepted: true, operation: "restart", commandId: "cmd-1" },
    });
    stubLauncherIpcBridge(invoke);

    const payload = await restartLauncherBundle();

    expect(payload.commandId).toBe("cmd-1");
    expect(fetchMock).not.toHaveBeenCalled();
    expect((invoke.mock.calls[0][0] as { path: string }).path).toBe("restart");
  });

  it("force closes the bundle through the preload IPC bridge", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const invoke = vi.fn().mockResolvedValue({
      ok: true,
      payload: { accepted: true, operation: "force-stop", commandId: "cmd-force" },
    });
    stubLauncherIpcBridge(invoke);

    const payload = await forceStopLauncherBundle();

    expect(payload.operation).toBe("force-stop");
    expect(payload.commandId).toBe("cmd-force");
    expect(fetchMock).not.toHaveBeenCalled();
    const request = invoke.mock.calls[0][0] as {
      path: string;
      init: { method: string; headers: Record<string, string> };
    };
    expect(request.path).toBe("force-stop");
    expect(request.init.method).toBe("POST");
    expect(request.init.headers["x-vibelution-launcher-trigger"]).toBe("launcher_route_force_stop_button");
  });

  it("marks stop requests with a launcher trigger header over IPC", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const invoke = vi.fn().mockResolvedValue({
      ok: true,
      payload: { accepted: true, operation: "stop", commandId: "cmd-stop" },
    });
    stubLauncherIpcBridge(invoke);

    const payload = await stopLauncherBundle("app_shell_shutdown_button");

    expect(payload.operation).toBe("stop");
    expect(fetchMock).not.toHaveBeenCalled();
    const request = invoke.mock.calls[0][0] as {
      path: string;
      init: { method: string; headers: Record<string, string> };
    };
    expect(request.path).toBe("stop");
    expect(request.init.method).toBe("POST");
    expect(request.init.headers["x-vibelution-launcher-trigger"]).toBe("app_shell_shutdown_button");
  });

  it("does not HTTP-fetch window close when the preload bridge is absent", () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    expect(requestWorkbenchWindowCloseOnPageHide("stop")).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("queues window close over the preload IPC bridge", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const invoke = vi.fn().mockResolvedValue({ ok: true, payload: { accepted: true } });
    stubLauncherIpcBridge(invoke);

    expect(requestWorkbenchWindowCloseOnPageHide("force-stop")).toBe(true);

    expect(fetchMock).not.toHaveBeenCalled();
    const request = invoke.mock.calls[0][0] as {
      path: string;
      init: { method: string; headers: Record<string, string> };
    };
    expect(request.path).toBe("force-stop");
    expect(request.init.headers["x-vibelution-launcher-trigger"])
      .toBe("app_shell_window_close_confirmed_active_work");
  });

  it("rejects lifecycle commands without a preload bridge instead of falling back to HTTP", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/chat",
        origin: "http://127.0.0.1:8000",
      },
    });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(restartLauncherBundle()).rejects.toBeInstanceOf(LauncherControlPlaneNotReadyError);
    const error = await startLauncherBundle().catch((caught: unknown) => caught);
    expect(isLauncherControlPlaneNotReady(error)).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requests guarded supervisor reattach through the preload IPC bridge", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const invoke = vi.fn().mockResolvedValue({
      ok: true,
      payload: { accepted: true, operation: "supervisor_reattach", commandId: "cmd-supervisor" },
    });
    stubLauncherIpcBridge(invoke);

    const payload = await reattachLauncherSupervisor();

    expect(payload.operation).toBe("supervisor_reattach");
    expect(payload.commandId).toBe("cmd-supervisor");
    expect(fetchMock).not.toHaveBeenCalled();
    const request = invoke.mock.calls[0][0] as { path: string; init: { method: string } };
    expect(request.path).toBe("supervisor/reattach");
    expect(request.init.method).toBe("POST");
  });

  it("saves workbench window mode through the launcher settings endpoint", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8765/launcher",
        origin: "http://127.0.0.1:8765",
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          mode: "windowed",
          setting: { mode: "windowed", effectiveMode: "windowed", envOverride: "", configHash: "hash-next" },
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await saveLauncherWorkbenchWindowMode({ mode: "windowed", baseHash: "hash-current" });

    expect(payload.mode).toBe("windowed");
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/control-token",
      "/api/launcher/settings/workbench-window",
    ]);
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(requestInit.method).toBe("PUT");
    expect((requestInit.headers as Headers).get("Content-Type")).toBe("application/json");
    expect((requestInit.headers as Headers).get("X-Vibelution-Control-Token")).toBe("test-token");
    expect(JSON.parse(String(requestInit.body))).toEqual({ mode: "windowed", baseHash: "hash-current" });
  });

  it("saves startup settings with launcher port and workbench window size", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8765/launcher",
        origin: "http://127.0.0.1:8765",
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          setting: {},
          message: "saved",
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await updateLauncherStartupSettings({
      launcher: {
        controlPort: 8899,
        effectiveControlPort: 8899,
        controlPortEnvOverride: 0,
      },
      runtime: {
        profile: "safe_remote",
        preflightDoctor: true,
        requireVenv: true,
        profileOptions: ["safe_remote"],
      },
      workbench: {
        backendPort: 8000,
        frontendPort: 5173,
        effectiveBackendPort: 8000,
        effectiveFrontendPort: 5173,
        backendPortEnvOverride: 0,
        frontendPortEnvOverride: 0,
        windowMode: "windowed",
        effectiveWindowMode: "windowed",
        windowModeEnvOverride: "",
        windowModeOptions: [],
        windowSize: "1600x900",
        effectiveWindowSize: "1600x900",
        windowSizeEnvOverride: "",
        windowSizeOptions: [{ size: "1600x900", label: { zh: "1600x900", en: "1600x900" } }],
      },
      interface: {
        language: "zh",
        languageOptions: ["zh", "en"],
      },
      configPath: "/path/to/operator/config/config.toml",
      configHash: "hash-current",
      restartRequired: true,
    });

    expect(payload.ok).toBe(true);
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/control-token",
      "/api/launcher/settings/startup",
    ]);
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(requestInit.method).toBe("PUT");
    expect((requestInit.headers as Headers).get("Content-Type")).toBe("application/json");
    expect((requestInit.headers as Headers).get("X-Vibelution-Control-Token")).toBe("test-token");
    expect(JSON.parse(String(requestInit.body))).toEqual({
      launcher: {
        controlPort: 8899,
      },
      runtime: {
        profile: "safe_remote",
        preflightDoctor: true,
        requireVenv: true,
      },
      workbench: {
        backendPort: 8000,
        frontendPort: 5173,
        windowMode: "windowed",
        windowSize: "1600x900",
      },
      interface: {
        language: "zh",
      },
      baseHash: "hash-current",
    });
  });

  it("cancels pending lifecycle commands through the workbench runtime API", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/chat",
        origin: "http://127.0.0.1:8000",
      },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          cancelled: true,
          status: "cancelled",
          commandId: "cmd-queued",
          operation: "restart",
          message: "Lifecycle command was cancelled before execution.",
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await cancelRuntimeLifecycleCommand({
      commandId: "cmd-queued",
      operation: "restart",
      source: "app_shell",
    });

    expect(payload.cancelled).toBe(true);
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/control-token",
      "/api/runtime/lifecycle-command/cancel",
    ]);
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(requestInit.method).toBe("POST");
    expect((requestInit.headers as Headers).get("X-Vibelution-Control-Token")).toBe("test-token");
    expect(JSON.parse(String(requestInit.body))).toEqual({
      commandId: "cmd-queued",
      operation: "restart",
      source: "app_shell",
    });
  });
});

describe("launcher api IPC transport", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    resetControlTokenForTests();
  });

  it("reads launcher status over the preload bridge without touching HTTP", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8765/launcher",
        origin: "http://127.0.0.1:8765",
      },
    });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const invoke = vi.fn().mockResolvedValue({
      ok: true,
      payload: { launcher: { mode: "standalone_control_plane" } },
    });
    stubLauncherIpcBridge(invoke);

    const payload = await getLauncherStatus();

    expect(payload.launcher.mode).toBe("standalone_control_plane");
    expect(invoke).toHaveBeenCalledTimes(1);
    const request = invoke.mock.calls[0][0] as { schemaVersion: number; path: string };
    expect(request.schemaVersion).toBe(1);
    expect(request.path).toBe("status");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reads state snapshots and returns the preload listener disposer", async () => {
    vi.stubGlobal("window", { location: { href: "http://127.0.0.1:8765/launcher" } });
    const snapshot = {
      schemaVersion: 1 as const,
      revision: 3,
      observedAt: "2026-08-19T00:00:00.000Z",
      freshness: "fresh" as const,
      main: { id: "main" },
      instances: [],
      cleanup: { reconciliation: { active: false, reason: "" }, cleanedCount: 0, skippedCount: 0, failedCount: 0 },
    };
    const disposer = vi.fn();
    let stateListener: ((payload: typeof snapshot) => void) | undefined;
    vi.stubGlobal("vibelutionLauncher", {
      launcherInvoke: vi.fn(),
      getLauncherState: vi.fn().mockResolvedValue(snapshot),
      refreshLauncherState: vi.fn().mockResolvedValue({ ...snapshot, revision: 4 }),
      onLauncherStateChanged: vi.fn((listener: (payload: typeof snapshot) => void) => {
        stateListener = listener;
        return disposer;
      }),
    });
    const listener = vi.fn();

    expect(await getLauncherState()).toBe(snapshot);
    expect((await refreshLauncherState()).revision).toBe(4);
    const dispose = onLauncherStateChanged(listener);
    stateListener?.(snapshot);
    expect(listener).toHaveBeenCalledWith(snapshot);
    dispose();
    expect(disposer).toHaveBeenCalledTimes(1);
  });

  it("sends the cleanup-metadata query over the preload bridge", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8765/launcher",
        origin: "http://127.0.0.1:8765",
      },
    });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const invoke = vi.fn().mockResolvedValue({
      ok: true,
      payload: { schemaVersion: 1, items: [] },
    });
    stubLauncherIpcBridge(invoke);

    await getLauncherBranchInstances({ cleanupMetadata: true });

    const request = invoke.mock.calls[0][0] as { path: string };
    expect(request.path).toBe("branch-instances?cleanupMetadata=1");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends lifecycle commands over the preload bridge with headers and body", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8765/launcher",
        origin: "http://127.0.0.1:8765",
      },
    });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const invoke = vi.fn().mockResolvedValue({
      ok: true,
      payload: { accepted: true, operation: "start", commandId: "cmd-ipc" },
    });
    stubLauncherIpcBridge(invoke);

    const payload = await requestBranchInstanceLifecycle("worktree:task", "start", "launcher_route_panel");

    expect(payload.commandId).toBe("cmd-ipc");
    const request = invoke.mock.calls[0][0] as {
      schemaVersion: number;
      path: string;
      init: { method: string; headers: Record<string, string>; body: unknown };
    };
    expect(request.path).toBe("branch-instances/start");
    expect(request.init.method).toBe("POST");
    expect(request.init.headers["x-vibelution-launcher-trigger"]).toBe("launcher_route_panel");
    expect(request.init.body).toEqual({ instanceId: "worktree:task" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("surfaces host-not-ready as a control plane starting error, not a disconnect", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8765/launcher",
        origin: "http://127.0.0.1:8765",
      },
    });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const invoke = vi.fn().mockResolvedValue({
      ok: false,
      error: { code: "LAUNCHER_IPC_HOST_NOT_READY", message: "Launcher IPC control plane host is not ready." },
    });
    stubLauncherIpcBridge(invoke);

    await expect(getLauncherStatus()).rejects.toBeInstanceOf(LauncherControlPlaneNotReadyError);
    const error = await getLauncherStatus().catch((caught: unknown) => caught);
    expect(isLauncherControlPlaneNotReady(error)).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("surfaces launcher proxy rejections from the bridge", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8765/launcher",
        origin: "http://127.0.0.1:8765",
      },
    });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const invoke = vi.fn().mockResolvedValue({
      ok: false,
      error: { code: "LAUNCHER_IPC_HTTP_409", message: "active work blocks restart" },
    });
    stubLauncherIpcBridge(invoke);

    await expect(restartLauncherBundle()).rejects.toThrow("active work blocks restart");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps the HTTP path when the preload bridge is absent", async () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/chat",
        origin: "http://127.0.0.1:8000",
      },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ launcher: { mode: "workbench_adapter" } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await getLauncherStatus();

    expect(payload.launcher.mode).toBe("workbench_adapter");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/launcher/status");
  });
});
