import { describe, expect, it, vi } from "vitest";

import { LauncherStateStore } from "../src/state/launcherStateStore.js";

const initial = {
  status: { projectBundle: { id: "main", observedState: "closed", backend: { pid: 0, port: 8000 } } },
  branchInstances: { items: [] },
};

describe("LauncherStateStore", () => {
  it("deduplicates refresh and publishes monotonic refreshing/fresh revisions", async () => {
    let resolveLoad!: (value: typeof initial) => void;
    const loader = vi.fn(() => new Promise<typeof initial>((resolve) => { resolveLoad = resolve; }));
    const store = new LauncherStateStore(loader, initial);
    const revisions: number[] = [];
    const dispose = store.subscribe((snapshot) => revisions.push(snapshot.revision));

    const first = store.refresh("startup");
    const second = store.refresh("duplicate");
    expect(first).toBe(second);
    expect(store.snapshot().freshness).toBe("refreshing");
    resolveLoad({
      status: { projectBundle: { id: "main", observedState: "open", backend: { pid: 42, port: 8000 } } },
      branchInstances: { items: [] },
    });
    await first;

    expect(loader).toHaveBeenCalledTimes(1);
    expect(revisions).toEqual([1, 2]);
    expect(store.snapshot()).toMatchObject({ freshness: "fresh", main: { observedState: "open", pid: 42 } });
    dispose();
  });

  it("keeps the last sources and marks the snapshot stale when refresh fails", async () => {
    const store = new LauncherStateStore(async () => { throw new Error("bridge timed out"); }, initial);
    await store.refresh("file_hint");
    expect(store.snapshot()).toMatchObject({
      freshness: "stale",
      staleReason: "bridge timed out",
      main: { observedState: "closed" },
      cleanup: { reconciliation: { active: false, reason: "file_hint" } },
    });
  });

  it("updates window truth without invoking the loader", () => {
    const loader = vi.fn(async () => initial);
    const store = new LauncherStateStore(loader, {
      ...initial,
      branchInstances: { items: [{ id: "worktree:task", kind: "worktree", runtime: {} }] },
    });
    store.updateWindowTruth({
      workbench: { open: true, rendererProcessId: 101 },
      instances: [{ instanceId: "worktree:task", open: true, rendererProcessId: 202 }],
    });
    expect(loader).not.toHaveBeenCalled();
    expect(store.snapshot().main.window).toEqual({ open: true, rendererProcessId: 101 });
    expect(store.snapshot().instances[0].window).toEqual({ open: true, rendererProcessId: 202 });
  });
});
