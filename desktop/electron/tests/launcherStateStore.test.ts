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

  it("updates status after cleanup timeout and keeps the previous cleanup frame", async () => {
    const store = new LauncherStateStore(async () => ({
      status: { ok: true, value: { projectBundle: { id: "main", observedState: "open", backend: { pid: 9, port: 8000 } } } },
      branchInstances: { ok: true, value: { items: [] } },
      freshness: { ok: true, value: { current: true } },
      cleanup: { ok: false, errorType: "TimeoutError", message: "git timed out stdout=" + "OUT".repeat(80) + " stderr=" + "ERR".repeat(80) },
    }), initial);
    store.updateCleanup({
      classifications: [{ instanceId: "worktree:keep", classification: "healthy", reasons: [], windowOpen: true, listener: ["owned"], ports: [8000] }],
    });

    await store.refresh("file_hint");

    expect(store.snapshot()).toMatchObject({
      freshness: "fresh",
      main: { observedState: "open", pid: 9 },
      cleanup: {
        failedCount: 1,
        classifications: [{ instanceId: "worktree:keep", classification: "healthy" }],
      },
    });
    expect(store.snapshot().staleReason).toBeUndefined();
    expect(store.snapshot().cleanup.reconciliation.reason).not.toMatch(/stdout|stderr|OUT|ERR/);
    expect(store.snapshot().cleanup.reconciliation.reason.length).toBeLessThanOrEqual(180);
  });

  it("keeps the previous status when only status fails and marks the snapshot stale", async () => {
    const store = new LauncherStateStore(async () => ({
      status: { ok: false, errorType: "RuntimeError", message: "status probe failed stdout=SECRET stderr=DUMP" },
      branchInstances: { ok: true, value: { items: [{ id: "worktree:ok", kind: "worktree", runtime: {} }] } },
      freshness: { ok: true, value: { current: true } },
      cleanup: { ok: true, value: { instances: [] } },
    }), initial);

    await store.refresh("file_hint");

    expect(store.snapshot()).toMatchObject({
      freshness: "stale",
      main: { observedState: "closed", pid: 0 },
      instances: [{ id: "worktree:ok" }],
    });
    expect(store.snapshot().staleReason).toBe("status probe failed");
    expect(store.snapshot().staleReason).not.toMatch(/stdout|stderr|SECRET|DUMP/);
  });

  it("projects registry classifications, external conflicts, and worktree dry-run", async () => {
    const store = new LauncherStateStore(async () => ({
      ...initial,
      cleanup: {
        observedAt: "2026-08-19T07:00:00Z",
        instances: [
          { instanceId: "worktree:healthy", classification: "healthy", reasons: ["owned_runtime_active"], windowOpen: true, listener: ["owned"], ports: [8000] },
          { instanceId: "worktree:external", classification: "conflict", reasons: ["external_listener"], windowOpen: false, listener: ["external"], ports: [8765] },
        ],
        removedInstanceIds: ["worktree:orphan"],
        worktreeDryRun: [
          { instanceId: "worktree:dirty", projectRoot: "C:/repo/dirty", branch: "codex/dirty", reason: "branch_cleanup_preview", action: "dry_run_only", dirty: true, mergedToMain: false, risks: ["delete_unmerged"] },
        ],
        orphanCriteria: ["no_electron_window"],
      },
    }), initial);

    await store.refresh("startup");

    expect(store.snapshot().cleanup).toMatchObject({
      lastCompletedAt: "2026-08-19T07:00:00Z",
      cleanedCount: 1,
      skippedCount: 1,
      failedCount: 0,
      removedInstanceIds: ["worktree:orphan"],
      orphanCriteria: ["no_electron_window"],
      portConflicts: [{ instanceId: "worktree:external", classification: "conflict", ports: [8765] }],
      worktreeDryRun: [{ instanceId: "worktree:dirty", action: "dry_run_only" }],
    });
  });

  it("projects nextReconcileAt from a successful cleanup source", async () => {
    const store = new LauncherStateStore(async () => ({
      ...initial,
      cleanup: {
        observedAt: "2026-08-19T06:00:00Z",
        nextReconcileAt: "2026-08-19T06:00:10Z",
        instances: [],
      },
    }), initial);
    await store.refresh("startup");
    expect(store.snapshot().nextReconcileAt).toBe("2026-08-19T06:00:10.000Z");
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
