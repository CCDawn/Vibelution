import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  WORKBENCH_BACKEND_OFFLINE_TITLE_SUFFIX,
  WorkbenchBackendWatchdogCore,
  startWorkbenchBackendWatchdog,
  workbenchOriginForWindowUrl,
  type WorkbenchBackendWatchdogLogEvent
} from "../src/windows/workbenchBackendWatchdog.js";

type FakeWindow = {
  id: number;
  url: string;
  title: string;
  destroyed: boolean;
  reloadCount: number;
  getUrl(): string;
  isDestroyed(): boolean;
  reload(): void;
  getTitle(): string;
  setTitle(title: string): void;
};

function makeFakeWindow(id: number, url: string, title = "Vibelution Workbench"): FakeWindow {
  const window: FakeWindow = {
    id,
    url,
    title,
    destroyed: false,
    reloadCount: 0,
    getUrl: () => window.url,
    isDestroyed: () => window.destroyed,
    reload: () => {
      window.reloadCount += 1;
    },
    getTitle: () => window.title,
    setTitle: (next: string) => {
      window.title = next;
    }
  };
  return window;
}

type Harness = {
  handle: ReturnType<typeof startWorkbenchBackendWatchdog>;
  probe: ReturnType<typeof vi.fn>;
  onReload: ReturnType<typeof vi.fn>;
  logs: WorkbenchBackendWatchdogLogEvent[];
  advanceTick(): Promise<void>;
};

function startHarness(input: {
  windows: FakeWindow[];
  script?: Record<string, Array<"healthy" | "dead">>;
  intervalMs?: number;
}): Harness {
  const script = input.script ?? {};
  const probe = vi.fn(async (origin: string): Promise<"healthy" | "dead"> => {
    const queue = script[origin];
    if (queue === undefined) {
      return "healthy";
    }
    return queue.length > 1 ? queue.shift() as "healthy" | "dead" : queue[0];
  });
  const onReload = vi.fn();
  const logs: WorkbenchBackendWatchdogLogEvent[] = [];
  const intervalMs = input.intervalMs ?? 1000;
  const handle = startWorkbenchBackendWatchdog({
    intervalMs,
    listWindows: () =>
      input.windows.map((window) => ({
        id: window.id,
        getUrl: () => window.getUrl(),
        isDestroyed: () => window.isDestroyed(),
        reload: () => window.reload(),
        getTitle: () => window.getTitle(),
        setTitle: (title: string) => window.setTitle(title)
      })),
    probe: (origin) => probe(origin),
    onReload,
    log: (event) => logs.push(event)
  });
  return {
    handle,
    probe,
    onReload,
    logs,
    advanceTick: () => vi.advanceTimersByTimeAsync(intervalMs)
  };
}

describe("workbenchBackendWatchdog pure core", () => {
  it("classifies loopback http(s) window URLs only", () => {
    expect(workbenchOriginForWindowUrl("http://127.0.0.1:8000/workbench")).toBe("http://127.0.0.1:8000");
    expect(workbenchOriginForWindowUrl("http://localhost:8002/app")).toBe("http://localhost:8002");
    expect(workbenchOriginForWindowUrl("https://127.0.0.1:8443/app")).toBe("https://127.0.0.1:8443");
    expect(workbenchOriginForWindowUrl("vibelution-launcher://app/index.html")).toBe("");
    expect(workbenchOriginForWindowUrl("chrome-error://chromewebdata/")).toBe("");
    expect(workbenchOriginForWindowUrl("data:text/html,offline")).toBe("");
    expect(workbenchOriginForWindowUrl("file:///C:/build/index.html")).toBe("");
    expect(workbenchOriginForWindowUrl("https://example.com/app")).toBe("");
    expect(workbenchOriginForWindowUrl("not a url")).toBe("");
  });

  it("degrades only after three consecutive dead probes", () => {
    const core = new WorkbenchBackendWatchdogCore();
    expect(core.record("http://127.0.0.1:8000", "dead")).toEqual([]);
    expect(core.stateOf("http://127.0.0.1:8000")).toBe("healthy");
    expect(core.record("http://127.0.0.1:8000", "dead")).toEqual([]);
    expect(core.stateOf("http://127.0.0.1:8000")).toBe("healthy");
    expect(core.record("http://127.0.0.1:8000", "dead")).toEqual([
      { kind: "degraded", origin: "http://127.0.0.1:8000" }
    ]);
    expect(core.stateOf("http://127.0.0.1:8000")).toBe("degraded");
  });

  it("resets the dead counter after any healthy probe", () => {
    const core = new WorkbenchBackendWatchdogCore();
    core.record("http://127.0.0.1:8000", "dead");
    core.record("http://127.0.0.1:8000", "dead");
    expect(core.record("http://127.0.0.1:8000", "healthy")).toEqual([]);
    core.record("http://127.0.0.1:8000", "dead");
    core.record("http://127.0.0.1:8000", "dead");
    expect(core.stateOf("http://127.0.0.1:8000")).toBe("healthy");
  });

  it("emits one reload-windows action on recovery and returns to the healthy baseline", () => {
    const core = new WorkbenchBackendWatchdogCore();
    core.record("http://127.0.0.1:8000", "dead");
    core.record("http://127.0.0.1:8000", "dead");
    core.record("http://127.0.0.1:8000", "dead");
    expect(core.record("http://127.0.0.1:8000", "healthy")).toEqual([
      { kind: "reload-windows", origin: "http://127.0.0.1:8000" }
    ]);
    expect(core.stateOf("http://127.0.0.1:8000")).toBe("healthy");
    // Fresh baseline: the next outage must cross the threshold again.
    expect(core.record("http://127.0.0.1:8000", "healthy")).toEqual([]);
    core.record("http://127.0.0.1:8000", "dead");
    expect(core.stateOf("http://127.0.0.1:8000")).toBe("healthy");
  });

  it("stays silent while degraded and keeps origins independent", () => {
    const core = new WorkbenchBackendWatchdogCore();
    for (let index = 0; index < 3; index += 1) {
      core.record("http://127.0.0.1:8000", "dead");
      core.record("http://127.0.0.1:8002", "dead");
    }
    expect(core.stateOf("http://127.0.0.1:8000")).toBe("degraded");
    expect(core.stateOf("http://127.0.0.1:8002")).toBe("degraded");
    expect(core.record("http://127.0.0.1:8000", "dead")).toEqual([]);
    expect(core.record("http://127.0.0.1:8000", "healthy")).toEqual([
      { kind: "reload-windows", origin: "http://127.0.0.1:8000" }
    ]);
    expect(core.stateOf("http://127.0.0.1:8002")).toBe("degraded");
  });

  it("reset drops all per-origin state", () => {
    const core = new WorkbenchBackendWatchdogCore();
    core.record("http://127.0.0.1:8000", "dead");
    core.record("http://127.0.0.1:8000", "dead");
    core.reset();
    core.record("http://127.0.0.1:8000", "dead");
    core.record("http://127.0.0.1:8000", "dead");
    expect(core.stateOf("http://127.0.0.1:8000")).toBe("healthy");
    expect(core.record("http://127.0.0.1:8000", "dead")).toEqual([
      { kind: "degraded", origin: "http://127.0.0.1:8000" }
    ]);
  });
});

describe("startWorkbenchBackendWatchdog wiring", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("probes only distinct loopback http(s) origins of live windows", async () => {
    const workbenchA = makeFakeWindow(1, "http://127.0.0.1:8000/workbench");
    const workbenchB = makeFakeWindow(2, "http://127.0.0.1:8000/workbench/other");
    const instanceWindow = makeFakeWindow(3, "http://127.0.0.1:8002/instance/x");
    const launcherWindow = makeFakeWindow(4, "vibelution-launcher://app/index.html");
    const errorWindow = makeFakeWindow(5, "chrome-error://chromewebdata/");
    const dataWindow = makeFakeWindow(6, "data:text/html,offline");
    const externalWindow = makeFakeWindow(7, "https://example.com/app");
    const destroyed = makeFakeWindow(8, "http://127.0.0.1:9000/workbench");
    destroyed.destroyed = true;
    const harness = startHarness({
      windows: [workbenchA, workbenchB, instanceWindow, launcherWindow, errorWindow, dataWindow, externalWindow, destroyed]
    });
    await harness.advanceTick();
    expect(harness.probe).toHaveBeenCalledTimes(2);
    expect(harness.probe).toHaveBeenCalledWith("http://127.0.0.1:8000");
    expect(harness.probe).toHaveBeenCalledWith("http://127.0.0.1:8002");
    expect(workbenchA.title).toBe("Vibelution Workbench");
    harness.handle.dispose();
  });

  it("suffixes titles on degrade and strips plus reloads once on recovery", async () => {
    const workbench = makeFakeWindow(1, "http://127.0.0.1:8000/workbench");
    const harness = startHarness({
      windows: [workbench],
      script: {
        "http://127.0.0.1:8000": ["dead", "dead", "dead", "healthy", "healthy"]
      }
    });
    await harness.advanceTick();
    expect(workbench.title).toBe("Vibelution Workbench");
    await harness.advanceTick();
    expect(workbench.title).toBe("Vibelution Workbench");
    await harness.advanceTick();
    expect(workbench.title).toBe(`Vibelution Workbench${WORKBENCH_BACKEND_OFFLINE_TITLE_SUFFIX}`);
    expect(workbench.reloadCount).toBe(0);
    expect(harness.logs).toContainEqual({ kind: "origin-degraded", origin: "http://127.0.0.1:8000" });
    await harness.advanceTick();
    expect(workbench.title).toBe("Vibelution Workbench");
    expect(workbench.reloadCount).toBe(1);
    expect(harness.onReload).toHaveBeenCalledTimes(1);
    expect(harness.onReload).toHaveBeenCalledWith("http://127.0.0.1:8000");
    expect(harness.logs).toContainEqual({ kind: "origin-recovered", origin: "http://127.0.0.1:8000" });
    // Reload-once: later healthy ticks never reload again.
    await harness.advanceTick();
    expect(workbench.reloadCount).toBe(1);
    expect(harness.onReload).toHaveBeenCalledTimes(1);
    harness.handle.dispose();
  });

  it("reloads only the windows of the recovered origin", async () => {
    const portA = makeFakeWindow(1, "http://127.0.0.1:8000/workbench");
    const portB = makeFakeWindow(2, "http://127.0.0.1:8002/instance/x", "Instance X");
    const harness = startHarness({
      windows: [portA, portB],
      script: {
        "http://127.0.0.1:8000": ["dead", "dead", "dead", "healthy"],
        "http://127.0.0.1:8002": ["dead", "dead", "dead", "dead"]
      }
    });
    for (let tick = 0; tick < 4; tick += 1) {
      await harness.advanceTick();
    }
    expect(portA.title).toBe("Vibelution Workbench");
    expect(portA.reloadCount).toBe(1);
    expect(portB.title).toBe(`Instance X${WORKBENCH_BACKEND_OFFLINE_TITLE_SUFFIX}`);
    expect(portB.reloadCount).toBe(0);
    harness.handle.dispose();
  });

  it("never reloads or retitles while health is steady", async () => {
    const workbench = makeFakeWindow(1, "http://127.0.0.1:8000/workbench");
    const harness = startHarness({ windows: [workbench] });
    for (let tick = 0; tick < 5; tick += 1) {
      await harness.advanceTick();
    }
    expect(workbench.reloadCount).toBe(0);
    expect(workbench.title).toBe("Vibelution Workbench");
    expect(harness.onReload).not.toHaveBeenCalled();
    harness.handle.dispose();
  });

  it("skips windows destroyed between degrade and recovery", async () => {
    const survivor = makeFakeWindow(1, "http://127.0.0.1:8000/workbench");
    const doomed = makeFakeWindow(2, "http://127.0.0.1:8000/workbench", "Doomed");
    const harness = startHarness({
      windows: [survivor, doomed],
      script: {
        "http://127.0.0.1:8000": ["dead", "dead", "dead", "healthy"]
      }
    });
    for (let tick = 0; tick < 3; tick += 1) {
      await harness.advanceTick();
    }
    doomed.destroyed = true;
    await harness.advanceTick();
    expect(survivor.reloadCount).toBe(1);
    expect(doomed.reloadCount).toBe(0);
    expect(doomed.title).toBe(`Doomed${WORKBENCH_BACKEND_OFFLINE_TITLE_SUFFIX}`);
    harness.handle.dispose();
  });

  it("stops ticking after dispose", async () => {
    const workbench = makeFakeWindow(1, "http://127.0.0.1:8000/workbench");
    const harness = startHarness({ windows: [workbench] });
    await harness.advanceTick();
    harness.handle.dispose();
    harness.handle.dispose();
    const calls = harness.probe.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(harness.probe.mock.calls.length).toBe(calls);
    expect(workbench.reloadCount).toBe(0);
  });
});
