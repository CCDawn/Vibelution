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

  it("keeps the current instance window closed when the provider reports no window", () => {
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
    expect((item.runtime as Record<string, unknown>).window).toMatchObject({ open: false, pid: 0 });
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
    const overlaid = overlayLauncherWindowTruth("branch-instances", payload, truth()) as Record<string, unknown>;
    const item = (overlaid.items as Record<string, unknown>[])[0];
    const runtime = item.runtime as Record<string, unknown>;
    expect(runtime.lifecycleState).toBe("partial");
    expect((runtime.window as Record<string, unknown>).open).toBe(false);
    expect(item.alive).toBe(true);
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
