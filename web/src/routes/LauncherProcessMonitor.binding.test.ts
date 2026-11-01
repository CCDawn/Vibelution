import { describe, expect, it } from "vitest";

import type { LauncherBranchInstance } from "../api/launcher";
import {
  buildAllInstanceMonitorRows,
  listMonitoredInstances,
  resolveLiveInstance,
  resolveProcessMonitorTarget,
} from "./LauncherProcessMonitor.binding";

function instance(overrides: Partial<LauncherBranchInstance> = {}): LauncherBranchInstance {
  return {
    id: "worktree:task",
    kind: "worktree",
    branch: "codex/task",
    path: ".worktrees/task",
    displayPath: ".worktrees/task",
    head: "abc",
    current: false,
    legacy: false,
    dirty: false,
    checkedOut: true,
    alive: false,
    observedState: "idle",
    port: 0,
    pids: { backend: 0, window: 0, manager: 0 },
    promotable: true,
    shortName: "task",
    runtime: {
      lifecycleState: "closed",
      desiredState: "closed",
      observedState: "closed",
      phase: "steady",
      backend: {
        alive: false,
        healthy: false,
        listening: false,
        port: 0,
        portReserved: false,
        portConflict: false,
        pid: 0,
      },
      frontend: { mode: "bundled_static_dist", ready: true },
      window: { open: false, pid: 0, title: "task 台", titleObserved: false },
    },
    startable: true,
    ...overrides,
  };
}

describe("process monitor auto-bind", () => {
  const main = instance({
    id: "main",
    kind: "main",
    branch: "main",
    current: true,
    alive: true,
    observedState: "open",
    port: 8002,
    shortName: "主",
  });
  const abandoned = instance({
    id: "branch:abandoned",
    kind: "local_branch",
    branch: "codex/abandoned",
    checkedOut: false,
    shortName: "abandoned",
  });
  const idleTree = instance({
    id: "worktree:idle",
    branch: "codex/idle",
    shortName: "idle",
  });

  it("binds to the current live instance by default", () => {
    const bound = resolveProcessMonitorTarget([main, abandoned], {
      selectedId: "branch:abandoned",
      currentId: "main",
    });
    expect(bound?.id).toBe("main");
    expect(resolveLiveInstance([main, abandoned], "main")?.id).toBe("main");
  });

  it("keeps the latest started live instance ahead of main", () => {
    const started = instance({ id: "worktree:started", alive: true, port: 8003, shortName: "started" });
    const bound = resolveProcessMonitorTarget([main, started], {
      selectedId: "main",
      currentId: "main",
      lastStartedId: "worktree:started",
    });
    expect(bound?.id).toBe("worktree:started");
  });

  it("only inspects an explicit checked-out row that is not the live project", () => {
    const bound = resolveProcessMonitorTarget([main, idleTree], {
      selectedId: "worktree:idle",
      currentId: "main",
      explicitSelect: true,
    });
    expect(bound?.id).toBe("worktree:idle");
  });

  it("lists every checked-out instance instead of only the selected one", () => {
    const composer = instance({
      id: "worktree:fix-composer-dialog-chrome",
      shortName: "composer",
      alive: true,
      port: 8000,
      pids: { backend: 29300, window: 0, manager: 0 },
      displayPath: ".worktrees/fix-composer-dialog-chrome",
    });
    const apply = instance({
      id: "worktree:slot-data-home-apply",
      shortName: "apply",
      displayPath: ".worktrees/slot-data-home-apply",
    });
    const items = [main, composer, apply, abandoned];
    expect(listMonitoredInstances(items).map((item) => item.shortName)).toEqual(["主", "composer", "apply"]);
    const rows = buildAllInstanceMonitorRows(
      items,
      { isZh: true },
    );
    expect(rows.map((row) => `${row.label}:${row.pid}:${row.port}`)).toEqual([
      "主:-:8002",
      "composer:29300:8000",
      "apply:-:-",
    ]);
  });
  it("uses the same lifecycle facts as the project list and separates backend and window", () => {
    const active = instance({
      id: "main", kind: "main", current: true, alive: true,
      pids: { backend: 12, window: 34, manager: 0 },
      runtime: { ...main.runtime, lifecycleState: "running", backend: { ...main.runtime.backend, alive: true, listening: true, pid: 12 }, window: { ...main.runtime.window, open: true, pid: 34 } },
    });
    const [row] = buildAllInstanceMonitorRows([active], { isZh: true });
    expect(row.status).toBe("正常运行");
    expect(row.detail).toBe("后台运行中 · 窗口已打开");
    expect(row.technical).toContain("window 34");
    const [failed] = buildAllInstanceMonitorRows([active], { isZh: true, queryFailed: true });
    expect(failed.status).toBe("状态未知");
    expect(failed.detail).toContain("上次记录: 后台运行中 · 窗口已打开");
    expect(failed.technical).toContain("window 34");
  });

  it("does not infer an open window from a pid", () => {
    const row = buildAllInstanceMonitorRows([instance({ pids: { backend: 0, window: 34, manager: 0 } })], { isZh: true })[0];
    expect(row.detail).toContain("窗口未打开");
    expect(row.technical).toContain("window 34");
  });

});
