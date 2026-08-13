import { describe, expect, it } from "vitest";

import type { LauncherBranchInstance } from "../api/launcher";
import panelSource from "./LauncherBranchInstancesPanel.tsx?raw";
import {
  BRANCH_INSTANCE_PAGE_SIZE,
  canStartInstance,
  canStopInstance,
  cleanupRiskLabels,
  formatBackendStatus,
  formatFrontendStatus,
  formatGitStatus,
  formatWorkbenchStatus,
  groupBranchInstances,
  instanceRuntimeState,
  isCleanupEligible,
  paginateItems,
} from "./LauncherBranchInstancesPanel.model";

function instance(overrides: Partial<LauncherBranchInstance> = {}): LauncherBranchInstance {
  return {
    id: "worktree:task",
    kind: "worktree",
    branch: "codex/task",
    path: "C:/repo/.worktrees/task",
    displayPath: ".worktrees/task",
    head: "abc123",
    current: false,
    legacy: false,
    dirty: false,
    checkedOut: true,
    alive: false,
    observedState: "closed",
    port: 0,
    pids: { backend: 0, window: 0, manager: 0 },
    promotable: true,
    shortName: "task",
    workbenchTitle: "task 台",
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
    startBlockReason: "",
    ...overrides,
  };
}

describe("LauncherBranchInstancesPanel contracts", () => {
  it("keeps the two primary sections on VUI primitives", () => {
    expect(panelSource).toContain("from \"../components/vui\"");
    expect(panelSource).toContain("正在运行");
    expect(panelSource).toContain("可启动");
    expect(panelSource).toContain("Launcher 控制窗口");
    expect(panelSource).toContain("Workbench 窗口");
    expect(panelSource).toContain("启动工作台");
    expect(panelSource).toContain("<details");
    expect(panelSource).toContain("维护与清理");
    expect(panelSource).toContain("<VButton");
    expect(panelSource).toContain("<VCheckbox");
    expect(panelSource).toContain("<VConfirmDialog");
    expect(panelSource).toContain("<VDenseTable");
    expect(panelSource).toContain("resizable");
    expect(panelSource).not.toMatch(/from\s+["']@heroui\/react["']/);
    expect(panelSource).not.toMatch(/renderers\/shadcn/);
    expect(panelSource).not.toMatch(/<button\b/);
    expect(BRANCH_INSTANCE_PAGE_SIZE).toBe(8);
  });

  it("keeps active, transitional, partial, and failed instances in the running section", () => {
    const running = instance({
      id: "main",
      kind: "main",
      branch: "main",
      current: true,
      startable: false,
      runtime: {
        ...instance().runtime,
        lifecycleState: "running",
        backend: {
          ...instance().runtime.backend,
          alive: true,
          healthy: true,
          listening: true,
          port: 8002,
          pid: 1200,
        },
        window: { open: true, pid: 1300, title: "main 台", titleObserved: true },
      },
    });
    const partial = instance({
      id: "worktree:partial",
      shortName: "partial",
      startable: false,
      runtime: {
        ...instance().runtime,
        lifecycleState: "partial",
        window: { open: true, pid: 1400, title: "partial 台", titleObserved: true },
      },
    });
    const failed = instance({
      id: "worktree:failed",
      shortName: "failed",
      startable: false,
      runtime: {
        ...instance().runtime,
        lifecycleState: "error",
        error: { code: "registry_failed", message: "上次启动失败" },
      },
    });
    const startable = instance({ id: "worktree:startable", shortName: "startable" });
    const retired = instance({
      id: "retired:old",
      kind: "retired",
      checkedOut: false,
      startable: false,
      startBlockReason: "unsupported_kind",
    });

    const groups = groupBranchInstances(
      [startable, retired, partial, running, failed],
      { instanceId: startable.id, operation: "start" },
    );

    expect(groups.running.map((item) => item.id)).toEqual([
      "main",
      "worktree:failed",
      "worktree:partial",
      "worktree:startable",
    ]);
    expect(groups.startable).toEqual([]);
    expect(groups.maintenance.map((item) => item.id)).toEqual(["retired:old"]);
    expect(instanceRuntimeState(startable, { instanceId: startable.id, operation: "start" })).toBe("starting");
  });

  it("does not present a reserved port as a running backend", () => {
    const stopped = instance({
      port: 8005,
      runtime: {
        ...instance().runtime,
        backend: { ...instance().runtime.backend, port: 8005, portReserved: true },
      },
    });
    const running = instance({
      runtime: {
        ...instance().runtime,
        lifecycleState: "running",
        backend: {
          ...instance().runtime.backend,
          alive: true,
          healthy: true,
          listening: true,
          port: 8002,
          pid: 1200,
        },
      },
      startable: false,
    });

    expect(formatBackendStatus(stopped, true)).toBe("未运行");
    expect(formatBackendStatus(running, true)).toBe("健康 · :8002");
    expect(formatFrontendStatus(stopped, true)).toBe("内置模式 · 已构建");
    expect(formatFrontendStatus(running, true)).toBe("内置资源就绪");
  });

  it("shows the Workbench title, window state, and Git state independently", () => {
    const dirty = instance({
      dirty: true,
      mergedToMain: false,
      runtime: {
        ...instance().runtime,
        lifecycleState: "partial",
        window: { open: true, pid: 2200, title: "实际 task 台", titleObserved: true },
      },
      startable: false,
    });

    expect(formatWorkbenchStatus(dirty, true)).toBe("实际 task 台 · 已打开");
    expect(formatGitStatus(dirty, true)).toBe("有未提交 · 未合入 main");
    expect(canStartInstance(dirty)).toBe(false);
    expect(canStopInstance(dirty)).toBe(true);
  });

  it("pages startable or maintenance lists at 8 rows", () => {
    const items = Array.from({ length: 11 }, (_, index) => instance({ id: `worktree:${index + 1}` }));
    expect(paginateItems(items, 1).items).toHaveLength(8);
    expect(paginateItems(items, 2).items).toHaveLength(3);
    expect(paginateItems(items, 99).page).toBe(2);
  });

  it("never treats main or the current checkout as cleanable", () => {
    expect(isCleanupEligible(instance({ id: "main", kind: "main", branch: "main", current: true }))).toBe(false);
    expect(isCleanupEligible(instance({ id: "worktree:self", current: true, cleanupEligible: false }))).toBe(false);
    expect(isCleanupEligible(instance({ cleanupEligible: true }))).toBe(true);
    expect(isCleanupEligible(instance({ kind: "local_branch", cleanupEligible: undefined }))).toBe(true);
  });

  it("lists cleanup risks for dirty running unmerged instances", () => {
    const labels = cleanupRiskLabels(
      instance({
        dirty: true,
        alive: true,
        mergedToMain: false,
        cleanupRisks: ["discard_dirty", "stop_then_remove", "delete_unmerged"],
      }),
      true,
    );

    expect(labels).toEqual([
      "将丢弃未提交改动",
      "将先停止再拆除运行中的实例",
      "将删除尚未合入 main 的本地提交",
    ]);
  });
});
