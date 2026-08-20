import { describe, expect, it } from "vitest";

import {
  overlayLauncherWindowTruth,
  type LauncherWindowTruth,
} from "../src/windows/launcherWindowTruthOverlay.js";

const truth = (overrides: Partial<LauncherWindowTruth> = {}): LauncherWindowTruth => ({
  workbench: null,
  instances: [],
  ...overrides,
});

describe("launcher status window truth overlay", () => {
  it("keeps a Python-reported closed bundle from hiding a live BrowserWindow", () => {
    const payload = {
      projectBundle: {
        observedState: "closed",
        lifecycleConsistency: "",
        backend: { alive: true, healthy: true, portListening: true, portConflict: false },
        browser: { managed: false, windowPid: 0, alive: false },
        components: [{ id: "browser", ok: false, state: "closed", pid: 0 }],
      },
    };
    const overlaid = overlayLauncherWindowTruth(
      "status",
      payload,
      truth({ workbench: { open: true, rendererProcessId: 7070 } })
    ) as Record<string, unknown>;
    const bundle = overlaid.projectBundle as Record<string, unknown>;
    expect(bundle.observedState).toBe("open");
    expect(bundle.browser).toMatchObject({ alive: true, managed: true, windowPid: 7070 });
    expect(bundle.components).toEqual([{ id: "browser", ok: true, state: "alive", pid: 7070 }]);
  });

  it("resolves browser_missing partial state when the window is actually open", () => {
    const payload = {
      projectBundle: {
        observedState: "partial",
        lifecycleConsistency: "browser_missing",
        backend: { alive: true, healthy: true, portListening: true, portConflict: false },
        browser: { managed: false, windowPid: 0, alive: false },
        components: [],
      },
    };
    const overlaid = overlayLauncherWindowTruth(
      "status",
      payload,
      truth({ workbench: { open: true, rendererProcessId: 7070 } })
    ) as Record<string, unknown>;
    const bundle = overlaid.projectBundle as Record<string, unknown>;
    expect(bundle.observedState).toBe("open");
    expect(bundle.lifecycleConsistency).toBe("");
  });

  it("downgrades a Python-reported open bundle when the window is gone", () => {
    const payload = {
      projectBundle: {
        observedState: "open",
        lifecycleConsistency: "",
        backend: { alive: true, healthy: true, portListening: true, portConflict: false },
        browser: { managed: true, windowPid: 7070, alive: true },
        components: [{ id: "browser", ok: true, state: "alive", pid: 7070 }],
      },
    };
    const overlaid = overlayLauncherWindowTruth("status", payload, truth()) as Record<string, unknown>;
    const bundle = overlaid.projectBundle as Record<string, unknown>;
    expect(bundle.observedState).toBe("partial");
    expect(bundle.lifecycleConsistency).toBe("browser_missing");
    expect(bundle.browser).toMatchObject({ alive: false, managed: false });
    expect(bundle.components).toEqual([{ id: "browser", ok: false, state: "closed", pid: 0 }]);
  });

  it("keeps a live BrowserWindow partial while the backend is unavailable", () => {
    const payload = {
      projectBundle: {
        observedState: "closed",
        lifecycleConsistency: "",
        backend: { alive: false, healthy: false, portListening: false, portConflict: false },
        browser: { managed: false, windowPid: 0, alive: false },
        components: [{ id: "browser", ok: false, state: "closed", pid: 0 }],
      },
    };
    const overlaid = overlayLauncherWindowTruth(
      "status",
      payload,
      truth({ workbench: { open: true, rendererProcessId: 7070 } })
    ) as Record<string, unknown>;
    const bundle = overlaid.projectBundle as Record<string, unknown>;

    expect(bundle.observedState).toBe("partial");
    expect(bundle.lifecycleConsistency).toBe("backend_missing");
    expect(bundle.browser).toMatchObject({ alive: true, managed: true, windowPid: 7070 });
  });

  it("clears a stale open state when neither backend nor BrowserWindow is live", () => {
    const payload = {
      projectBundle: {
        observedState: "open",
        lifecycleConsistency: "browser_missing",
        backend: { alive: false, healthy: false, portListening: false, portConflict: false },
        browser: { managed: true, windowPid: 7070, alive: true },
        components: [{ id: "browser", ok: true, state: "alive", pid: 7070 }],
      },
    };
    const overlaid = overlayLauncherWindowTruth("status", payload, truth()) as Record<string, unknown>;
    const bundle = overlaid.projectBundle as Record<string, unknown>;

    expect(bundle.observedState).toBe("closed");
    expect(bundle.lifecycleConsistency).toBe("");
    expect(bundle.browser).toMatchObject({ alive: false, managed: false });
  });

  it("leaves non-status payloads untouched", () => {
    const payload = { foo: "bar" };
    expect(overlayLauncherWindowTruth("start", payload, truth({ workbench: { open: true, rendererProcessId: 1 } }))).toBe(
      payload
    );
  });
});

describe("launcher branch-instances window truth overlay", () => {
  it("marks a live current instance window as open and not startable", () => {
    const payload = {
      items: [
        {
          id: "main",
          current: true,
          alive: false,
          startable: true,
          runtime: { window: { open: false, pid: 0 } },
        },
      ],
    };
    const overlaid = overlayLauncherWindowTruth(
      "branch-instances",
      payload,
      truth({ workbench: { open: true, rendererProcessId: 7070 } })
    ) as Record<string, unknown>;
    const item = (overlaid.items as Record<string, unknown>[])[0];
    expect(item.alive).toBe(true);
    expect(item.startable).toBe(false);
    expect((item.runtime as Record<string, unknown>).window).toMatchObject({ open: true, pid: 7070 });
  });

  it("leaves Python window truth alone when Electron has no provider snapshot", () => {
    const payload = {
      items: [
        {
          id: "main",
          current: true,
          alive: true,
          startable: false,
          runtime: { window: { open: true, pid: 7070 } },
        },
      ],
    };
    const overlaid = overlayLauncherWindowTruth("branch-instances", payload, truth()) as Record<string, unknown>;
    const item = (overlaid.items as Record<string, unknown>[])[0];
    expect((item.runtime as Record<string, unknown>).window).toMatchObject({ open: true, pid: 7070 });
  });

  it("keeps the current instance window closed when the provider reports a closed window", () => {
    const payload = {
      items: [
        {
          id: "main",
          current: true,
          alive: true,
          startable: false,
          runtime: { window: { open: true, pid: 7070 } },
        },
      ],
    };
    const overlaid = overlayLauncherWindowTruth(
      "branch-instances",
      payload,
      truth({ workbench: { open: false, rendererProcessId: 0 } })
    ) as Record<string, unknown>;
    const item = (overlaid.items as Record<string, unknown>[])[0];
    expect((item.runtime as Record<string, unknown>).window).toMatchObject({ open: false, pid: 0 });
  });

  it("keeps leftover closing as stopping even when the workbench window is still open", () => {
    const payload = {
      items: [
        {
          id: "main",
          current: true,
          alive: false,
          startable: true,
          runtime: {
            lifecycleState: "stopping",
            phase: "closing",
            observedState: "closed",
            desiredState: "closed",
            registryStatus: "stopping",
            backend: { alive: false, healthy: false, listening: false, portConflict: false },
            frontend: { ready: true },
            window: { open: false, pid: 0 },
          },
        },
      ],
    };
    const overlaid = overlayLauncherWindowTruth(
      "branch-instances",
      payload,
      truth({ workbench: { open: true, rendererProcessId: 7070 } })
    ) as Record<string, unknown>;
    const item = (overlaid.items as Record<string, unknown>[])[0];
    const runtime = item.runtime as Record<string, unknown>;
    expect((runtime.window as Record<string, unknown>).open).toBe(true);
    expect(runtime.lifecycleState).toBe("stopping");
    expect(item.alive).toBe(true);
    expect(item.startable).toBe(false);
  });

  it("applies isolated instance window truth without touching other instances", () => {
    const payload = {
      items: [
        {
          id: "worktree:task",
          current: false,
          alive: false,
          startable: true,
          runtime: { window: { open: false, pid: 0 } },
        },
        {
          id: "worktree:other",
          current: false,
          alive: false,
          startable: true,
          runtime: { window: { open: false, pid: 0 } },
        },
      ],
    };
    const overlaid = overlayLauncherWindowTruth(
      "branch-instances",
      payload,
      truth({ instances: [{ instanceId: "worktree:task", open: true, rendererProcessId: 9090 }] })
    ) as Record<string, unknown>;
    const items = overlaid.items as Record<string, unknown>[];
    expect((items[0].runtime as Record<string, unknown>).window).toMatchObject({ open: true, pid: 9090 });
    expect(items[0].startable).toBe(false);
    expect((items[1].runtime as Record<string, unknown>).window).toMatchObject({ open: false, pid: 0 });
    expect(items[1].startable).toBe(true);
  });

  it("recomputes lifecycleState from Electron window truth instead of a stale starting/open phase", () => {
    const payload = {
      items: [
        {
          id: "main",
          current: true,
          alive: true,
          startable: false,
          runtime: {
            lifecycleState: "starting",
            phase: "opening",
            observedState: "open",
            backend: { alive: true, healthy: true, listening: true, portConflict: false },
            frontend: { ready: true },
            window: { open: false, pid: 0 },
          },
        },
      ],
    };
    const overlaid = overlayLauncherWindowTruth(
      "branch-instances",
      payload,
      truth({ workbench: { open: false, rendererProcessId: 0 } })
    ) as Record<string, unknown>;
    const item = (overlaid.items as Record<string, unknown>[])[0];
    const runtime = item.runtime as Record<string, unknown>;
    expect(runtime.lifecycleState).toBe("partial");
    expect((runtime.window as Record<string, unknown>).open).toBe(false);
    expect(item.alive).toBe(true);
    expect(item.startable).toBe(false);
  });

  it("keeps an in-flight isolated start as starting even when leftover failureMessage is present", () => {
    const payload = {
      items: [
        {
          id: "worktree:task",
          current: false,
          alive: false,
          startable: false,
          runtime: {
            lifecycleState: "error",
            desiredState: "open",
            registryStatus: "starting",
            phase: "starting",
            observedState: "closed",
            backend: { alive: false, healthy: false, listening: false, portConflict: false },
            frontend: { ready: true },
            window: { open: false, pid: 0 },
            error: { code: "runtime_error", message: "上次启动失败" },
          },
        },
      ],
    };
    const overlaid = overlayLauncherWindowTruth(
      "branch-instances",
      payload,
      truth({ instances: [{ instanceId: "worktree:task", open: false, rendererProcessId: 0 }] })
    ) as Record<string, unknown>;
    const item = (overlaid.items as Record<string, unknown>[])[0];
    const runtime = item.runtime as Record<string, unknown>;
    expect(runtime.lifecycleState).toBe("starting");
    expect((runtime.window as Record<string, unknown>).open).toBe(false);
  });

  it("keeps the Python start_supervisor_lost error instead of recomputing back to starting", () => {
    const payload = {
      items: [
        {
          id: "worktree:task",
          current: false,
          alive: false,
          startable: true,
          runtime: {
            lifecycleState: "error",
            desiredState: "open",
            registryStatus: "starting",
            phase: "starting",
            observedState: "closed",
            backend: { alive: false, healthy: false, listening: false, portConflict: false },
            frontend: { ready: true },
            window: { open: false, pid: 0 },
            error: { code: "start_supervisor_lost", message: "启动监督进程已退出且超过启动期限，启动未完成。可直接重试启动。" },
          },
        },
      ],
    };
    const overlaid = overlayLauncherWindowTruth(
      "branch-instances",
      payload,
      truth({ instances: [{ instanceId: "worktree:task", open: false, rendererProcessId: 0 }] })
    ) as Record<string, unknown>;
    const item = (overlaid.items as Record<string, unknown>[])[0];
    const runtime = item.runtime as Record<string, unknown>;
    expect(runtime.lifecycleState).toBe("error");
    expect(item.startable).toBe(true);
  });

  it("keeps a failed leftover without live signals startable", () => {
    const payload = {
      items: [
        {
          id: "worktree:failed",
          current: false,
          alive: false,
          startable: false,
          runtime: {
            lifecycleState: "error",
            desiredState: "closed",
            registryStatus: "failed",
            phase: "failed",
            observedState: "closed",
            backend: { alive: false, healthy: false, listening: false, portConflict: false },
            frontend: { ready: true },
            window: { open: false, pid: 0 },
            error: { code: "registry_failed", message: "该分支上次启动失败。" },
          },
        },
      ],
    };
    const overlaid = overlayLauncherWindowTruth(
      "branch-instances",
      payload,
      truth({ instances: [{ instanceId: "worktree:failed", open: false, rendererProcessId: 0 }] })
    ) as Record<string, unknown>;
    const item = (overlaid.items as Record<string, unknown>[])[0];
    expect((item.runtime as Record<string, unknown>).lifecycleState).toBe("error");
    expect(item.startable).toBe(true);
  });

  it("does not treat missing frontend.ready as running", () => {
    const payload = {
      items: [
        {
          id: "main",
          current: true,
          alive: true,
          startable: false,
          runtime: {
            lifecycleState: "running",
            phase: "steady",
            observedState: "open",
            desiredState: "open",
            registryStatus: "steady",
            backend: { alive: true, healthy: true, listening: true, portConflict: false },
            frontend: {},
            window: { open: false, pid: 0 },
          },
        },
      ],
    };
    const overlaid = overlayLauncherWindowTruth(
      "branch-instances",
      payload,
      truth({ workbench: { open: true, rendererProcessId: 7070 } })
    ) as Record<string, unknown>;
    const item = (overlaid.items as Record<string, unknown>[])[0];
    expect((item.runtime as Record<string, unknown>).lifecycleState).toBe("partial");
    expect(item.startable).toBe(false);
  });
});

describe("retired launcher control port overlay", () => {
  it("clears leftover :8765 fields on a status snapshot", () => {
    const overlaid = overlayLauncherWindowTruth(
      "status",
      {
        launcher: {
          mode: "standalone_control_plane",
          controlPlane: { port: 8765, url: "http://127.0.0.1:8765/launcher", adapter: "runtime_manager", pid: 12 },
        },
        settings: { startup: { launcher: { controlPort: 8765, effectiveControlPort: 8765 } } },
        projectBundle: { observedState: "closed", browser: {}, components: [] },
      },
      truth()
    ) as Record<string, unknown>;
    const launcher = overlaid.launcher as Record<string, unknown>;
    expect(launcher.controlPlane).toMatchObject({ port: 0, url: "", adapter: "electron_main", pid: 0 });
    const settings = overlaid.settings as Record<string, unknown>;
    const startup = settings.startup as Record<string, unknown>;
    expect(startup.launcher).toMatchObject({ controlPort: 0, effectiveControlPort: 0 });
  });

  it("clears leftover :8765 fields on startup settings", () => {
    const overlaid = overlayLauncherWindowTruth(
      "settings/startup",
      { launcher: { controlPort: 8765, effectiveControlPort: 8765 } },
      truth()
    ) as Record<string, unknown>;
    expect(overlaid.launcher).toMatchObject({ controlPort: 0, effectiveControlPort: 0 });
  });
});
