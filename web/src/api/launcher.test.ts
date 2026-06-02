import { afterEach, describe, expect, it, vi } from "vitest";

import { resetControlTokenForTests } from "./client";
import {
  getLauncherStatus,
  launcherRestartEndpoint,
  reattachLauncherSupervisor,
  restartLauncherBundle,
  startLauncherBundle,
} from "./launcher";

describe("launcher api helpers", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    resetControlTokenForTests();
  });

  it("builds canonical launcher restart endpoints", () => {
    expect(launcherRestartEndpoint()).toBe("/api/launcher/restart");
    expect(launcherRestartEndpoint(true)).toBe("/api/launcher/restart?confirmedActiveWork=true");
  });

  it("fetches launcher status as a read-only request", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ launcher: { mode: "runtime_manager_adapter" } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await getLauncherStatus();

    expect(payload.launcher.mode).toBe("runtime_manager_adapter");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/launcher/status");
  });

  it("starts the bundle through the guarded launcher endpoint", async () => {
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
        json: async () => ({ accepted: true, operation: "start", launcherMode: "runtime_manager_adapter" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await startLauncherBundle();

    expect(payload.operation).toBe("start");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/launcher/start");
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(requestInit.method).toBe("POST");
    expect((requestInit.headers as Headers).get("X-Vibelution-Control-Token")).toBe("test-token");
  });

  it("restarts the bundle with active-work confirmation when requested", async () => {
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

    const payload = await restartLauncherBundle(true);

    expect(payload.commandId).toBe("cmd-1");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/launcher/restart?confirmedActiveWork=true");
  });

  it("requests guarded supervisor reattach through the launcher endpoint", async () => {
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
    expect(fetchMock.mock.calls[1][0]).toBe("/api/launcher/supervisor/reattach");
    const requestInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(requestInit.method).toBe("POST");
  });
});
