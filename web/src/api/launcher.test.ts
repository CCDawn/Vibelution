import { afterEach, describe, expect, it, vi } from "vitest";

import { resetControlTokenForTests } from "./client";
import {
  cancelRuntimeLifecycleCommand,
  forceStopLauncherBundle,
  getLauncherStatus,
  launcherEndpoint,
  launcherRestartEndpoint,
  reattachLauncherSupervisor,
  resetLauncherControlOriginForTests,
  restartLauncherBundle,
  saveLauncherWorkbenchWindowMode,
  startLauncherBundle,
} from "./launcher";

describe("launcher api helpers", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    resetControlTokenForTests();
    resetLauncherControlOriginForTests();
  });

  it("builds canonical launcher restart endpoints", () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8000/chat",
      },
    });

    expect(launcherEndpoint("status")).toBe("http://127.0.0.1:8765/api/launcher/status");
    expect(launcherRestartEndpoint()).toBe("http://127.0.0.1:8765/api/launcher/restart");
  });

  it("keeps launcher endpoints relative on the Launcher control origin", () => {
    vi.stubGlobal("window", {
      location: {
        href: "http://127.0.0.1:8765/launcher",
      },
    });

    expect(launcherRestartEndpoint()).toBe("/api/launcher/restart");
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
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8765/api/launcher/status");
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
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "test-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ accepted: true, operation: "restart", commandId: "cmd-custom-port" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    await getLauncherStatus();
    const payload = await restartLauncherBundle();

    expect(payload.commandId).toBe("cmd-custom-port");
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "http://127.0.0.1:8765/api/launcher/status",
      "http://127.0.0.1:8899/api/control-token",
      "http://127.0.0.1:8899/api/launcher/restart",
    ]);
  });

  it("starts the bundle through the guarded launcher endpoint", async () => {
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
        json: async () => ({ accepted: true, operation: "start", launcherMode: "standalone_control_plane" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await startLauncherBundle();

    expect(payload.operation).toBe("start");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8765/api/control-token");
    expect(fetchMock.mock.calls[1][0]).toBe("http://127.0.0.1:8765/api/launcher/start");
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(requestInit.method).toBe("POST");
    expect(requestInit.credentials).toBe("include");
    expect((requestInit.headers as Headers).get("X-Vibelution-Control-Token")).toBe("test-token");
  });

  it("restarts the bundle through the guarded launcher endpoint", async () => {
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
        json: async () => ({ accepted: true, operation: "restart", commandId: "cmd-1" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await restartLauncherBundle();

    expect(payload.commandId).toBe("cmd-1");
    expect(fetchMock.mock.calls[1][0]).toBe("http://127.0.0.1:8765/api/launcher/restart");
  });

  it("force closes the bundle through the guarded launcher endpoint", async () => {
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
        json: async () => ({ accepted: true, operation: "force-stop", commandId: "cmd-force" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await forceStopLauncherBundle();

    expect(payload.operation).toBe("force-stop");
    expect(payload.commandId).toBe("cmd-force");
    expect(fetchMock.mock.calls[1][0]).toBe("http://127.0.0.1:8765/api/launcher/force-stop");
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(requestInit.method).toBe("POST");
  });

  it("falls back to the workbench launcher adapter when direct launcher control is unreachable", async () => {
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
          controlToken: "launcher-token",
        }),
      })
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          header: "X-Vibelution-Control-Token",
          controlToken: "workbench-token",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ accepted: true, operation: "restart", commandId: "cmd-fallback" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await restartLauncherBundle();

    expect(payload.commandId).toBe("cmd-fallback");
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "http://127.0.0.1:8765/api/control-token",
      "http://127.0.0.1:8765/api/launcher/restart",
      "/api/control-token",
      "/api/launcher/restart",
    ]);
  });

  it("requests guarded supervisor reattach through the launcher endpoint", async () => {
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
        json: async () => ({ accepted: true, operation: "supervisor_reattach", commandId: "cmd-supervisor" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await reattachLauncherSupervisor();

    expect(payload.operation).toBe("supervisor_reattach");
    expect(payload.commandId).toBe("cmd-supervisor");
    expect(fetchMock.mock.calls[1][0]).toBe("http://127.0.0.1:8765/api/launcher/supervisor/reattach");
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(requestInit.method).toBe("POST");
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
