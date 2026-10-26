import { describe, expect, it } from "vitest";

import {
  projectVerifiedMainClosedBranches,
  projectVerifiedMainClosedStatus,
  projectPendingMainRetirementBranches,
  projectPendingMainRetirementStatus,
  retainCurrentMainBranch,
} from "../src/state/verifiedMainLifecycleProjection.js";

describe("verified main close projection", () => {
  it("projects pending retirement without clearing any original resource evidence or peers", () => {
    const source = { projectBundle: { backend: { pid: 42, alive: true }, browser: { windowPid: 43 } },
      lifecycleProof: { components: [{ id: "backend", pid: 42 }] } };
    const before = structuredClone(source);
    expect(projectPendingMainRetirementStatus(source)).toMatchObject({ phase: "stopping", desiredState: "closed",
      projectBundle: { phase: "stopping", backend: { pid: 42, alive: true }, browser: { windowPid: 43 } },
      lifecycleProof: { phase: "stopping", components: [{ id: "backend", pid: 42 }] } });
    expect(source).toEqual(before);
    const peer = { id: "peer", current: false, runtime: { lifecycleState: "running" } };
    const branches = projectPendingMainRetirementBranches({ items: [{ id: "main", current: true, pids: { backend: 42 } }, peer] }) as { items: unknown[] };
    expect(branches.items[0]).toMatchObject({ phase: "stopping", startable: false, pids: { backend: 42 } });
    expect(branches.items[1]).toBe(peer);
  });
  it("clones main's status and clears live components while retaining static frontend readiness", () => {
    const source = {
      projectBundle: {
        id: "vibelution-project", desiredState: "open", observedState: "open", phase: "steady",
        backend: { alive: true, healthy: true, portListening: true, port: 8000, pid: 42 },
        browser: { alive: true, windowPid: 43 },
        frontend: { distReady: true },
        components: [
          { id: "backend", state: "running", ok: true, pid: 42 },
          { id: "browser", state: "running", ok: true, pid: 43 },
          { id: "frontend", state: "ready", ok: true, pid: 0 },
        ],
      },
      lifecycleProof: { overallState: "ready", components: [{ id: "workbench_window", state: "running", pid: 43 }] },
      controlPlaneEvidence: { state: { activeCommand: { type: "close" } }, recovery: { active: true } },
    };
    const before = structuredClone(source);
    const closed = projectVerifiedMainClosedStatus(source);
    expect(source).toEqual(before);
    expect(closed).toMatchObject({
      projectBundle: {
        desiredState: "closed", observedState: "closed", phase: "steady",
        backend: { alive: false, healthy: false, portListening: false, port: 8000, pid: 0 },
        browser: { alive: false, windowPid: 0 },
        frontend: { distReady: true },
        components: [
          { id: "backend", state: "stopped", ok: false, pid: 0 },
          { id: "browser", state: "stopped", ok: false, pid: 0 },
          { id: "frontend", state: "ready", ok: true, pid: 0 },
        ],
      },
      lifecycleProof: { overallState: "closed", components: [{ id: "workbench_window", state: "stopped", pid: 0 }] },
      controlPlaneEvidence: { state: { activeCommand: null }, recovery: { active: false } },
    });
  });

  it("closes only the current checkout row and retains peer object identity", () => {
    const peer = { id: "worktree:peer", runtime: { lifecycleState: "running", backend: { alive: true, pid: 77 } } };
    const source = { items: [
      { id: "checkout:current", current: true, alive: true, runtime: {
        lifecycleState: "partial", backend: { alive: true, listening: true, pid: 42 },
        window: { open: false, pid: 0 }, error: { code: "old_error" },
      } }, peer,
    ] };
    const before = structuredClone(source);
    const result = projectVerifiedMainClosedBranches(source) as typeof source;
    expect(source).toEqual(before);
    expect(result.items[0]).toMatchObject({
      alive: false, startable: true, runtime: {
        lifecycleState: "closed", backend: { alive: false, listening: false, pid: 0 },
        window: { open: false, pid: 0 }, error: undefined,
      },
    });
    expect(result.items[1]).toBe(peer);
    const latePeer = { ...peer, runtime: { lifecycleState: "partial", backend: { alive: true, pid: 78 } } };
    const merged = retainCurrentMainBranch(result, { items: [source.items[0], latePeer] }) as typeof source;
    expect(merged.items[0]).toBe(result.items[0]);
    expect(merged.items[1]).toBe(latePeer);
  });
});
