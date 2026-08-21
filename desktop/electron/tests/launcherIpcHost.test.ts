import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { resetAdmissionCacheForTests } from "../src/lifecycle/instanceAdmissionStore.js";
import { AdmissionDeniedError } from "../src/lifecycle/instanceAdmissionControl.js";
import {
  createLauncherIpcHost,
  LAUNCHER_IPC_HOST_NOT_READY,
  LAUNCHER_IPC_UNSUPPORTED_PATH,
  type LauncherIpcInvokePayload,
} from "../src/protocol/launcherIpcHost.js";

afterEach(() => {
  resetAdmissionCacheForTests();
});

async function tempAdmissionPath(): Promise<string> {
  return join(await mkdtemp(join(tmpdir(), "vibe-ipc-admission-")), "instance-admission.json");
}

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

  it("reports host not ready when leftover HTTP paths have no control-plane context", async () => {
    const host = createLauncherIpcHost({
      resolveContext: async () => null,
    });
    const result = await host.invoke(validPayload({ path: "supervisor" }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe(LAUNCHER_IPC_HOST_NOT_READY);
    }
  });

  it("returns a local status snapshot without waiting for the CLI orchestrator", async () => {
    const fetchImpl = vi.fn();
    const orchestrate = vi.fn().mockImplementation(() => new Promise(() => undefined));
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8002", controlToken: "t" }),
      resolveWindowTruth: () => ({ workbench: { open: true, rendererProcessId: 7070 }, instances: [] }),
      resolveLocalStatus: () => ({
        launcher: { mode: "standalone_control_plane", controlPlane: { port: 8765, url: "http://127.0.0.1:8765/launcher" } },
        projectBundle: {
          observedState: "closed",
          lifecycleConsistency: "",
          browser: { managed: false, windowPid: 0, alive: false },
          components: [],
        },
      }),
      orchestrateLauncherApi: orchestrate,
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "status" }));
    expect(result.ok).toBe(true);
    if (result.ok) {
      const bundle = (result.payload as Record<string, unknown>).projectBundle as Record<string, unknown>;
      expect(bundle.observedState).toBe("partial");
      expect(bundle.lifecycleConsistency).toBe("backend_missing");
    }
    expect(orchestrate).not.toHaveBeenCalled();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("serves status through the local CLI orchestrator without fetching the workbench", async () => {
    const fetchImpl = vi.fn();
    const resolveContext = vi.fn().mockResolvedValue({ launcherOrigin: "http://127.0.0.1:8002", controlToken: "t" });
    const orchestrate = vi.fn().mockResolvedValue({
      launcher: { mode: "standalone_control_plane", controlPlane: { port: 8765, url: "http://127.0.0.1:8765/launcher" } },
      projectBundle: {
        observedState: "closed",
        lifecycleConsistency: "",
        backend: { alive: true, healthy: true, portListening: true, portConflict: false },
        browser: { managed: false, windowPid: 0, alive: false },
        components: [],
      },
    });
    const host = createLauncherIpcHost({
      resolveContext,
      resolveWindowTruth: () => ({ workbench: { open: true, rendererProcessId: 7070 }, instances: [] }),
      orchestrateLauncherApi: orchestrate,
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "status" }));
    expect(result.ok).toBe(true);
    if (result.ok) {
      const payload = result.payload as Record<string, unknown>;
      const launcher = payload.launcher as Record<string, unknown>;
      const controlPlane = launcher.controlPlane as Record<string, unknown>;
      expect(controlPlane.port).toBe(0);
      expect(controlPlane.adapter).toBe("electron_main");
      const bundle = payload.projectBundle as Record<string, unknown>;
      expect(bundle.observedState).toBe("open");
      expect(bundle.browser).toMatchObject({ alive: true, windowPid: 7070 });
    }
    expect(orchestrate).toHaveBeenCalledTimes(1);
    expect(orchestrate.mock.calls[0][0]).toBe("status");
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(resolveContext).not.toHaveBeenCalled();
  });

  it("proxies leftover launcher GET requests through the main-process HTTP fallback", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(
      jsonResponse({ supervisor: { alive: false } }),
    );
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8002", controlToken: "t" }),
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "supervisor" }));
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.payload).toEqual({ supervisor: { alive: false } });
    }
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [resource, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(resource).toBe("http://127.0.0.1:8002/api/launcher/supervisor");
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

  it("surfaces leftover HTTP rejections as structured IPC errors", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(
      jsonResponse({ detail: "active work blocks restart" }, false, 409),
    );
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8002", controlToken: "t" }),
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "supervisor", init: { method: "POST" } }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("LAUNCHER_IPC_HTTP_409");
      expect(result.error.message).toContain("active work blocks restart");
    }
  });

  it("surfaces leftover HTTP network failures as structured IPC errors", async () => {
    const fetchImpl = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8002", controlToken: "t" }),
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "supervisor" }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("LAUNCHER_IPC_NETWORK_ERROR");
    }
  });

  it("does not throw when leftover HTTP context resolution fails", async () => {
    const host = createLauncherIpcHost({
      resolveContext: async () => {
        throw new TypeError("fetch failed");
      },
    });
    const result = await host.invoke(validPayload({ path: "supervisor" }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("LAUNCHER_IPC_NETWORK_ERROR");
      expect(result.error.message).toContain("fetch failed");
    }
  });

  it("overlays the Electron window truth on a locally served status snapshot", async () => {
    const fetchImpl = vi.fn();
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8002", controlToken: "t" }),
      resolveWindowTruth: () => ({ workbench: { open: true, rendererProcessId: 7070 }, instances: [] }),
      resolveLocalStatus: () => ({
        projectBundle: {
          observedState: "closed",
          lifecycleConsistency: "",
          backend: { alive: true, healthy: true, portListening: true, portConflict: false },
          browser: { managed: false, windowPid: 0, alive: false },
          components: [],
        },
      }),
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "status" }));
    expect(result.ok).toBe(true);
    if (result.ok) {
      const bundle = (result.payload as Record<string, unknown>).projectBundle as Record<string, unknown>;
      expect(bundle.observedState).toBe("open");
      expect(bundle.browser).toMatchObject({ alive: true, windowPid: 7070 });
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("overlays the Electron window truth on locally served branch instances", async () => {
    const fetchImpl = vi.fn();
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8002", controlToken: "t" }),
      resolveWindowTruth: () => ({ workbench: { open: true, rendererProcessId: 7070 }, instances: [] }),
      resolveLocalBranchInstances: () => ({
        items: [
          { id: "main", current: true, alive: false, startable: true, runtime: { window: { open: false, pid: 0 } } },
        ],
      }),
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "branch-instances" }));
    expect(result.ok).toBe(true);
    if (result.ok) {
      const item = ((result.payload as Record<string, unknown>).items as Record<string, unknown>[])[0];
      expect(item.startable).toBe(false);
      expect((item.runtime as Record<string, unknown>).window).toMatchObject({ open: true, pid: 7070 });
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("loads cleanup metadata through one python api orchestrator instead of the memory snapshot", async () => {
    const fetchImpl = vi.fn();
    const resolveLocalBranchInstances = vi.fn().mockReturnValue({ items: [] });
    const orchestrateLauncherApi = vi.fn().mockResolvedValue({
      items: [
        { id: "main", current: true, alive: false, startable: true, runtime: { window: { open: false, pid: 0 } } },
      ],
    });
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8002", controlToken: "t" }),
      resolveWindowTruth: () => ({ workbench: { open: true, rendererProcessId: 7070 }, instances: [] }),
      resolveLocalBranchInstances,
      orchestrateLauncherApi,
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "branch-instances?cleanupMetadata=1" }));
    expect(result.ok).toBe(true);
    expect(resolveLocalBranchInstances).not.toHaveBeenCalled();
    expect(orchestrateLauncherApi).toHaveBeenCalledTimes(1);
    expect(orchestrateLauncherApi.mock.calls[0][0]).toBe("branch-instances?cleanupMetadata=1");
    if (result.ok) {
      const item = ((result.payload as Record<string, unknown>).items as Record<string, unknown>[])[0];
      expect(item.startable).toBe(false);
      expect((item.runtime as Record<string, unknown>).window).toMatchObject({ open: true, pid: 7070 });
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("routes lifecycle commands through the main orchestrator instead of the Python proxy", async () => {
    const fetchImpl = vi.fn();
    const orchestrate = vi.fn().mockResolvedValue({
      schemaVersion: 1,
      accepted: true,
      operation: "start",
      commandId: "cmd-orch",
      message: "ok",
    });
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
      orchestrateLifecycle: orchestrate,
      fetchImpl,
      admissionStorePath: await tempAdmissionPath(),
    });
    const result = await host.invoke(
      validPayload({
        path: "start",
        init: {
          method: "POST",
          headers: { "x-vibelution-launcher-trigger": "launcher_route_start_button" },
        },
      })
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.payload).toMatchObject({ accepted: true, commandId: "cmd-orch" });
    }
    expect(orchestrate).toHaveBeenCalledTimes(1);
    expect(orchestrate.mock.calls[0][0]).toBe("start");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("surfaces orchestrator rejections as structured lifecycle errors", async () => {
    const fetchImpl = vi.fn();
    const orchestrate = vi.fn().mockRejectedValue(new Error("active work blocks restart"));
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
      orchestrateLifecycle: orchestrate,
      fetchImpl,
      admissionStorePath: await tempAdmissionPath(),
    });
    const result = await host.invoke(validPayload({ path: "restart", init: { method: "POST" } }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("LAUNCHER_IPC_LIFECYCLE_ERROR");
      expect(result.error.message).toContain("active work blocks restart");
    }
  });

  it("preserves the rejected lifecycle operation when admission throws", async () => {
    const fetchImpl = vi.fn();
    const denied = new AdmissionDeniedError({
      instanceId: "main",
      code: "rate_limited",
      retryAfterMs: 1000,
      message: "启动过于频繁，请 1 秒后再试。",
      eventName: "launcher.admission.rate_limited"
    });
    const orchestrate = vi.fn().mockRejectedValue(denied);
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
      orchestrateLifecycle: orchestrate,
      fetchImpl,
      admissionStorePath: await tempAdmissionPath()
    });

    const result = await host.invoke(validPayload({ path: "restart", init: { method: "POST" } }));

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.payload).toMatchObject({
        accepted: false,
        operation: "restart",
        instanceId: "main",
        code: "rate_limited"
      });
    }
    expect(orchestrate).toHaveBeenCalledTimes(1);
  });

  it("routes branch-instance lifecycle commands through the main orchestrator", async () => {
    const fetchImpl = vi.fn();
    const orchestrate = vi.fn().mockResolvedValue({
      schemaVersion: 1,
      accepted: true,
      operation: "start",
      instanceId: "worktree:task",
      port: 8002,
    });
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
      orchestrateBranchInstance: orchestrate,
      fetchImpl,
    });
    const result = await host.invoke(
      validPayload({
        path: "branch-instances/start",
        init: { method: "POST", body: { instanceId: "worktree:task" } },
      })
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.payload).toMatchObject({ accepted: true, instanceId: "worktree:task" });
    }
    expect(orchestrate).toHaveBeenCalledTimes(1);
    expect(orchestrate.mock.calls[0][0]).toBe("start");
    const payload = orchestrate.mock.calls[0][1] as LauncherIpcInvokePayload;
    expect((payload.init?.body as Record<string, unknown>).instanceId).toBe("worktree:task");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("routes settings and maintenance calls through the launcher api orchestrator", async () => {
    const fetchImpl = vi.fn();
    const orchestrate = vi.fn().mockResolvedValue({ ok: true, mode: "windowed" });
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
      orchestrateLauncherApi: orchestrate,
      fetchImpl,
    });
    const result = await host.invoke(
      validPayload({
        path: "settings/workbench-window",
        init: { method: "PUT", body: { mode: "windowed" } },
      })
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.payload).toMatchObject({ ok: true, mode: "windowed" });
    }
    expect(orchestrate).toHaveBeenCalledTimes(1);
    expect(orchestrate.mock.calls[0][0]).toBe("settings/workbench-window");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("surfaces launcher api orchestrator rejections", async () => {
    const fetchImpl = vi.fn();
    const orchestrate = vi.fn().mockRejectedValue(new Error("active work blocks reset"));
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
      orchestrateLauncherApi: orchestrate,
      fetchImpl,
    });
    const result = await host.invoke(validPayload({ path: "maintenance/reset/apply", init: { method: "POST" } }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.message).toContain("active work blocks reset");
    }
  });

  it("rejects a main-row start storm without calling the orchestrator after burst", async () => {
    const orchestrate = vi.fn().mockResolvedValue({ schemaVersion: 1, accepted: true, operation: "restart" });
    const host = createLauncherIpcHost({
      resolveContext: async () => ({ launcherOrigin: "http://127.0.0.1:8765", controlToken: "t" }),
      orchestrateLifecycle: orchestrate,
      fetchImpl: vi.fn(),
      admissionStorePath: await tempAdmissionPath(),
    });
    const results = [];
    for (let index = 0; index < 10; index += 1) {
      results.push(await host.invoke(validPayload({ path: "restart", init: { method: "POST" } })));
    }
    expect(orchestrate).toHaveBeenCalledTimes(3);
    const denied = results.slice(3);
    expect(denied.every((item) => item.ok && (item.payload as { accepted?: boolean }).accepted === false)).toBe(true);
    expect((denied[0]?.payload as { code?: string }).code).toBe("rate_limited");
  });
});
