import { describe, expect, it, vi } from "vitest";

import { LauncherStateStore } from "../src/state/launcherStateStore.js";

const initial = {
  status: { projectBundle: { id: "main", observedState: "closed", backend: { pid: 0, port: 8000 } } },
  branchInstances: { items: [] },
};

describe("LauncherStateStore", () => {
  it("retains pending main retirement across window closure and empty observations until verified", async () => {
    const live = { status: { projectBundle: { id: "main", observedState: "open", backend: { pid: 42, port: 8000 } } }, branchInstances: { items: [] } };
    const store = new LauncherStateStore(async () => initial, live);
    const epoch = store.beginMainLifecycle("force-stop");
    expect(store.markMainRetirementPending(epoch)).toBe(true);
    store.updateWindowTruth({ workbench: null, instances: [] });
    await store.refresh("empty_after_window_closed");
    expect(store.snapshot().main).toMatchObject({ phase: "stopping", desiredState: "closed", pid: 42 });
    expect(store.commitVerifiedMainClosed(epoch)).toBe(true);
    expect(store.snapshot().main).toMatchObject({ observedState: "closed", phase: "steady", pid: 0 });
    store.beginMainLifecycle("start");
    expect(store.markMainRetirementPending(epoch)).toBe(false);
    expect(store.commitVerifiedMainClosed(epoch)).toBe(false);
  });

  it("releases only the superseded retirement projection and reads the newer main identity", async () => {
    const newer = { status: { projectBundle: { id: "main", desiredState: "open", observedState: "open", phase: "steady", backend: { pid: 99, port: 8000 } } }, branchInstances: { items: [] } };
    const store = new LauncherStateStore(async () => newer, initial);
    const epoch = store.beginMainLifecycle("force-stop");
    store.markMainRetirementPending(epoch);
    expect(store.releaseMainRetirementPending(epoch)).toBe(true);
    await store.refresh("new_identity");
    expect(store.snapshot().main).toMatchObject({ observedState: "open", phase: "steady", pid: 99 });
    store.beginMainLifecycle("restart");
    expect(store.releaseMainRetirementPending(epoch)).toBe(false);
  });
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

  it("projects unknown quarantine lease fields onto registry classifications", async () => {
    const store = new LauncherStateStore(async () => ({
      ...initial,
      cleanup: {
        observedAt: "2026-08-19T07:00:00Z",
        nextReconcileAt: "2026-08-19T07:00:10Z",
        instances: [
          {
            instanceId: "worktree:legacy",
            classification: "unknown",
            reasons: ["missing_identity_fields"],
            windowOpen: false,
            listener: ["none"],
            ports: [8765],
            portLeaseStatus: "reclaimable",
            firstObservedAt: "2026-08-19T06:59:50Z",
            nextReconcileAt: "2026-08-19T07:00:10Z",
          },
        ],
      },
    }), initial);

    await store.refresh("startup");

    expect(store.snapshot().nextReconcileAt).toBe("2026-08-19T07:00:10.000Z");
    expect(store.snapshot().cleanup.classifications).toEqual([
      {
        instanceId: "worktree:legacy",
        classification: "unknown",
        reasons: ["missing_identity_fields"],
        windowOpen: false,
        listener: ["none"],
        ports: [8765],
        portLeaseStatus: "reclaimable",
        firstObservedAt: "2026-08-19T06:59:50Z",
        nextReconcileAt: "2026-08-19T07:00:10.000Z",
      },
    ]);
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

  it("publishes verified closure immediately and fences an older loader without dropping peer observations", async () => {
    const open = {
      status: { projectBundle: { id: "main", observedState: "open", backend: { pid: 42, port: 8000, alive: true } } },
      branchInstances: { items: [
        { id: "main", current: true, runtime: { lifecycleState: "running", backend: { alive: true, pid: 42 } } },
        { id: "worktree:peer", runtime: { lifecycleState: "running", backend: { alive: true, pid: 77 } } },
      ] },
    };
    let resolveLoad!: (value: typeof open) => void;
    const store = new LauncherStateStore(() => new Promise<typeof open>((resolve) => { resolveLoad = resolve; }), open);
    const pushed: string[] = [];
    store.subscribe((snapshot) => pushed.push(snapshot.main.observedState));
    const epoch = store.beginMainLifecycle("force-stop");
    const pending = store.refresh("during_close");
    store.commitVerifiedMainClosed(epoch);
    expect(store.snapshot().main).toMatchObject({ observedState: "closed", pid: 0 });
    expect(pushed.at(-1)).toBe("closed");
    const late = structuredClone(open);
    late.branchInstances.items[1].runtime.backend.pid = 78;
    resolveLoad(late);
    await pending;
    expect(store.snapshot().main).toMatchObject({ observedState: "closed", pid: 0 });
    expect(store.projectBranchInstances()).toMatchObject({ items: [
      { current: true, runtime: { lifecycleState: "closed", backend: { alive: false, pid: 0 } } },
      { id: "worktree:peer", runtime: { backend: { pid: 78 } } },
    ] });
    expect(open.status.projectBundle.backend.pid).toBe(42);
  });

  it("rejects an old close token after a new start and accepts a new observation of the running backend", async () => {
    const loader = vi.fn(async () => ({
      status: { projectBundle: { id: "main", observedState: "open", backend: { pid: 99, port: 8000 } } },
      branchInstances: { items: [] },
    }));
    const store = new LauncherStateStore(loader, initial);
    const closeEpoch = store.beginMainLifecycle("stop");
    store.commitVerifiedMainClosed(closeEpoch);
    store.beginMainLifecycle("restart");
    await store.refresh("new_start");
    const revision = store.snapshot().revision;
    store.commitVerifiedMainClosed(closeEpoch);
    expect(store.snapshot()).toMatchObject({ revision, main: { observedState: "open", pid: 99 } });
  });

  it("fences a loader that began before a new start without turning window closure into backend retirement", async () => {
    let resolveLoad!: (value: typeof initial) => void;
    const store = new LauncherStateStore(() => new Promise<typeof initial>((resolve) => { resolveLoad = resolve; }), {
      status: { projectBundle: { id: "main", observedState: "open", backend: { pid: 42, port: 8000, alive: true } } },
      branchInstances: { items: [] },
    });
    store.updateWindowTruth({ workbench: { open: false, rendererProcessId: 0 }, instances: [] });
    expect(store.projectStatus()).toMatchObject({ projectBundle: { backend: { alive: true, pid: 42 } } });
    const pending = store.refresh("old_closed_read");
    store.beginMainLifecycle("start");
    resolveLoad(initial);
    await pending;
    expect(store.snapshot().main).toMatchObject({ observedState: "open", pid: 42, window: { open: false } });
    expect(store.snapshot().freshness).toBe("stale");
  });

  it.each(["source failure", "bridge rejection"])("waits for one current-epoch refresh after an obsolete %s", async (failure) => {
    type Sources = { status: unknown; branchInstances: unknown };
    let resolveOld!: (value: Sources) => void;
    let rejectOld!: (error: Error) => void;
    let resolveNew!: (value: Sources) => void;
    const loader = vi.fn()
      .mockImplementationOnce(() => new Promise<Sources>((resolve, reject) => { resolveOld = resolve; rejectOld = reject; }))
      .mockImplementationOnce(() => new Promise<Sources>((resolve) => { resolveNew = resolve; }));
    const store = new LauncherStateStore(loader, initial);
    const published: Array<{ freshness: string; observed: string }> = [];
    store.subscribe((snapshot) => published.push({ freshness: snapshot.freshness, observed: snapshot.main.observedState }));
    const old = store.refresh("before_start");
    store.beginMainLifecycle("start");
    const current = store.refresh("lifecycle_complete");
    expect(current).not.toBe(old);
    for (let index = 0; index < 20; index += 1) {
      expect(store.refresh("file_hint")).toBe(current);
    }
    let currentSettled = false;
    void current.then(() => { currentSettled = true; });
    if (failure === "bridge rejection") rejectOld(new Error("old bridge failed"));
    else resolveOld({ status: { ok: false, errorType: "RuntimeError", message: "old status failed" }, branchInstances: { items: [] } });
    await old;
    await Promise.resolve();
    expect(loader).toHaveBeenCalledTimes(2);
    expect(currentSettled).toBe(false);
    expect(published).not.toContainEqual({ freshness: "fresh", observed: "closed" });
    for (let index = 0; index < 20; index += 1) store.refresh("same_epoch_hint");
    resolveNew({ status: { projectBundle: { id: "main", observedState: "open", backend: { pid: 99, port: 8000 } } }, branchInstances: { items: [] } });
    expect(await current).toMatchObject({ freshness: "fresh", main: { observedState: "open", pid: 99 } });
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("keeps a verified close fresh when an obsolete status result arrives", async () => {
    let resolveOld!: (value: typeof initial) => void;
    const store = new LauncherStateStore(() => new Promise<typeof initial>((resolve) => { resolveOld = resolve; }), initial);
    const old = store.refresh("before_close");
    const epoch = store.beginMainLifecycle("stop");
    expect(store.commitVerifiedMainClosed(epoch)).toBe(true);
    resolveOld(initial);
    await old;
    expect(store.snapshot()).toMatchObject({ freshness: "fresh", main: { observedState: "closed", pid: 0 } });
    store.beginMainLifecycle("start");
    expect(store.snapshot().freshness).toBe("stale");
  });

  it("coalesces several lifecycle changes before the queued read starts", async () => {
    let resolveOld!: (value: typeof initial) => void;
    const open = {
      status: { projectBundle: { id: "main", observedState: "open", backend: { pid: 88, port: 8000 } } },
      branchInstances: { items: [] },
    };
    const loader = vi.fn()
      .mockImplementationOnce(() => new Promise<typeof initial>((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(open);
    const store = new LauncherStateStore(loader, initial);
    const old = store.refresh("before_lifecycle");
    store.beginMainLifecycle("start");
    const queued = store.refresh("start_complete");
    store.beginMainLifecycle("restart");
    expect(store.refresh("restart_complete")).toBe(queued);
    store.beginMainLifecycle("rebuild-and-start");
    expect(store.refresh("rebuild_complete")).toBe(queued);
    resolveOld(initial);
    await old;
    expect(await queued).toMatchObject({ freshness: "fresh", main: { observedState: "open", pid: 88 } });
    expect(loader).toHaveBeenCalledTimes(2);
  });
});
