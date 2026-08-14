import { describe, expect, it, vi } from "vitest";

import {
  createLauncherIpcHost,
  LAUNCHER_IPC_HOST_NOT_READY,
  LAUNCHER_IPC_UNSUPPORTED_PATH,
  type LauncherIpcInvokePayload,
} from "../src/protocol/launcherIpcHost.js";

function jsonResponse(payload: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => payload,
    text: async () => (ok ? JSON.stringify(payload) : String(payload)),
    headers: new Headers({ "content-type": "application/json" }),
  } as unknown as Response;
}

function validPayload(overrides: Partial<LauncherIpcInvokePayload> = {}): LauncherIpcInvokePayload {
  return {
    schemaVersion: 1,
    path: "status",
    ...overrides,
  };
}

describe("createLauncherIpcHost", () => {
  it("rejects payloads that are not schemaVersion 1", async () => {
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
    });
    const result = await host.invoke({ schemaVersion: 2, path: "status" } as unknown as LauncherIpcInvokePayload);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("LAUNCHER_IPC_INVALID_PAYLOAD");
    }
  });

  it("rejects paths that escape the /api/launcher control surface", async () => {
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
    });
    for (const path of ["../etc/passwd", "http://evil.example/api/launcher/status", "/api/runtime/summary", "..\\..\\windows\\system32"]) {
      const result = await host.invoke(validPayload({ path }));
      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.error.code).toBe(LAUNCHER_IPC_UNSUPPORTED_PATH);
      }
    }
  });

  it("reports host not ready when the control plane context is unavailable", async () => {
    const host = createLauncherIpcHost({
      resolveContext: async () => null,
    });
    const result = await host.invoke(validPayload());
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe(LAUNCHER_IPC_HOST_NOT_READY);
    }
  });

  it("proxies launcher GET requests through the main-process control plane", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(
      jsonResponse({ launcher: { mode: "standalone_control_plane" } }),
    );
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "status" }));
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.payload).toEqual({ launcher: { mode: "standalone_control_plane" } });
    }
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [resource, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(resource).toBe("http://127.0.0.1:8765/api/launcher/status");
    expect(init.method).toBe("GET");
  });

  it("forwards control token and trigger headers for POST lifecycle commands", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(
      jsonResponse({ accepted: true, operation: "start" }),
    );
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "test-token" }),
      fetchImpl,
    });
    const result = await host.invoke(
      validPayload({
        path: "start",
        init: {
          method: "POST",
          headers: { "X-Vibelution-Launcher-Trigger": "launcher_route_start_button" },
          body: { instanceId: "main" },
        },
      }),
    );
    expect(result.ok).toBe(true);
    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    const headers = new Headers(init.headers as Record<string, string>);
    expect(headers.get("X-Vibelution-Control-Token")).toBe("test-token");
    expect(headers.get("X-Vibelution-Launcher-Trigger")).toBe("launcher_route_start_button");
    expect(JSON.parse(String(init.body))).toEqual({ instanceId: "main" });
  });

  it("surfaces launcher HTTP rejections as structured IPC errors", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(
      jsonResponse({ detail: "active work blocks restart" }, false, 409),
    );
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "restart", init: { method: "POST" } }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("LAUNCHER_IPC_HTTP_409");
      expect(result.error.message).toContain("active work blocks restart");
    }
  });

  it("surfaces launcher network failures as structured IPC errors", async () => {
    const fetchImpl = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "status" }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("LAUNCHER_IPC_NETWORK_ERROR");
    }
  });

  it("overlays the Electron window truth on the status snapshot", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        projectBundle: {
          observedState: "closed",
          lifecycleConsistency: "",
          browser: { managed: false, windowPid: 0, alive: false },
          components: [],
        },
      }),
    );
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
      resolveWindowTruth: () => ({ workbench: { open: true, rendererProcessId: 7070 }, instances: [] }),
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "status" }));
    expect(result.ok).toBe(true);
    if (result.ok) {
      const bundle = (result.payload as Record<string, unknown>).projectBundle as Record<string, unknown>;
      expect(bundle.observedState).toBe("open");
      expect(bundle.browser).toMatchObject({ alive: true, windowPid: 7070 });
    }
  });

  it("overlays the Electron window truth on branch instances", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        items: [
          { id: "main", current: true, alive: false, startable: true, runtime: { window: { open: false, pid: 0 } } },
        ],
      }),
    );
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
      resolveWindowTruth: () => ({ workbench: { open: true, rendererProcessId: 7070 }, instances: [] }),
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "branch-instances" }));
    expect(result.ok).toBe(true);
    if (result.ok) {
      const item = ((result.payload as Record<string, unknown>).items as Record<string, unknown>[])[0];
      expect(item.startable).toBe(false);
      expect((item.runtime as Record<string, unknown>).window).toMatchObject({ open: true, pid: 7070 });
    }
  });
});
