import { describe, expect, it } from "vitest";

import type { LauncherBranchInstance } from "../api/launcher";
import panelSource from "./LauncherBranchInstancesPanel.tsx?raw";
import panelStyles from "./LauncherBranchInstancesPanel.styles";
import {
  BRANCH_INSTANCE_PAGE_SIZE,
  canStartInstance,
  canStopInstance,
  cleanupRiskLabels,
  filterBranchInstances,
  formatAttentionReason,
  formatBackendStatus,
  formatFrontendStatus,
  formatGitStatus,
  formatWorkbenchStatus,
  groupBranchInstances,
  instanceRuntimeState,
  instanceStopLabel,
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
  it("renders one primary VDenseTable at a time through VTabs for all/running/attention/startable", () => {
    expect(panelSource).toContain("from \"../components/vui\"");
    expect(panelSource).toContain("<VTabs");
    expect(panelSource).toContain('id: "all"');
    expect(panelSource).toContain('id: "running"');
    expect(panelSource).toContain('id: "attention"');
    expect(panelSource).toContain('id: "startable"');
    expect(panelSource).toContain("value={activeTab}");
    expect(panelSource).toContain("rows={activeRows}");
    expect(panelSource).toContain("grouped.running.length");
    expect(panelSource).toContain("grouped.attention.length");
    expect(panelSource).toContain("grouped.startable.length");
    expect(panelSource).toContain("labels.allHint");
    expect(panelSource).toContain("labels.runningHint");
    expect(panelSource).toContain("labels.attentionHint");
    expect(panelSource).toContain("labels.startableHint");
    expect(panelSource).toContain("LauncherBranchStatusHelp");
    expect(panelSource).toContain("正在运行");
    expect(panelSource).toContain("需要处理");
    expect(panelSource).toContain("可启动");
    expect(panelSource).toContain("停止全部");
    expect(panelSource).toContain("全部关闭");
    expect(panelSource).toContain("<VNativeInput");
    expect(panelSource).toContain("<VToolbar");
    expect(panelSource).toContain("Launcher 控制窗口");
    expect(panelSource).toContain("读取中");
    expect(panelSource).toContain('tone={launcherOnline ? "success" : launcherReading ? "neutral" : "warning"}');
    expect(panelSource).toContain("tone={runtimeTone(state)}");
    expect(panelSource).toContain('<VStatusChip tone="success">{labels.ready}</VStatusChip>');
    expect(panelSource).toContain('variant="primary"');
    expect(panelSource).toContain('variant="danger"');
    expect(panelSource).toContain("resizable");
    expect(panelSource).not.toMatch(/from\s+["']@heroui\/react["']/);
    expect(panelSource).not.toMatch(/renderers\/shadcn/);
    expect(panelSource).not.toMatch(/<button\b/);
    expect(BRANCH_INSTANCE_PAGE_SIZE).toBe(8);
  });

  it("keeps a compact runtime presentation with backend/frontend/workbench/git/actions columns", () => {
    expect(panelSource).toContain("header: copy.branchColumn");
    expect(panelSource).toContain("header: copy.instanceState");
    expect(panelSource).toContain("header: labels.backend");
    expect(panelSource).toContain("header: labels.frontend");
    expect(panelSource).toContain("header: labels.workbench");
    expect(panelSource).toContain("header: labels.git");
    expect(panelSource).toContain("header: labels.actions");
    expect(panelSource).toContain("formatBackendStatus");
    expect(panelSource).toContain("formatFrontendStatus");
    expect(panelSource).toContain("formatWorkbenchStatus");
    expect(panelSource).toContain("formatGitStatus");
    expect(panelSource).toContain("formatAttentionReason");
    expect(panelSource).toContain("instanceRuntimeStateLabel");
    expect(panelSource).toContain("Workbench 窗口");
    expect(panelSource).toContain("启动工作台");
    expect(panelSource).toContain("styles.actionButtons");
    // Compact columns still keep the path inside the branch tooltip, not a wide fill column.
    expect(panelSource).toContain("path || item.displayPath || item.id");
    // Narrow widths: the resizable table scrolls inside its own container so the
    // actions column stays discoverable without page-level horizontal overflow.
    expect(panelStyles.statusTable).toBeTypeOf("string");
    expect(panelStyles.statusTable).toContain("w-full");
    expect(panelStyles.panel).toContain("overflow-hidden");
    expect(panelStyles.panel).toContain("min-w-0");
  });

  it("renders one global empty surface for zero items and a distinct recoverable filtered miss", () => {
    expect(panelSource).toContain("<VEmptyState");
    expect(panelSource).toContain("<VStateSurface");
    expect(panelSource).toContain("labels.globalEmptyTitle");
    expect(panelSource).toContain("labels.globalEmptyHint");
    expect(panelSource).toContain("labels.listLoadingTitle");
    expect(panelSource).toContain("正在读取分支实例");
    expect(panelSource).toContain("Reading branch instances");
    expect(panelSource).toContain("还没有分支实例");
    expect(panelSource).toContain("const hasAnyItems = items.length > 0");
    expect(panelSource).toContain("const showListLoading = listLoading && !hasAnyItems");
    expect(panelSource).toContain("{showListLoading ? (");
    expect(panelSource).toContain('tone="loading"');
    expect(panelSource).toContain("!hasAnyItems ? (");
    expect(panelSource).toContain("labels.filteredEmptyTitle");
    expect(panelSource).toContain("labels.filteredEmptyHint");
    expect(panelSource).toContain("labels.clearSearch");
    expect(panelSource).toContain("onPress={clearSearch}");
    expect(panelSource).toContain('setQuery("")');
    expect(panelSource).toContain("setFilters({})");
    expect(panelSource).toContain("GitBranch");
  });

  it("keeps maintenance cleanup and batch stop/close surfaces intact", () => {
    expect(panelSource).toContain("<details");
    expect(panelSource).toContain("维护与清理");
    expect(panelSource).toContain("<VCheckbox");
    expect(panelSource).toContain("<VConfirmDialog");
    expect(panelSource).toContain("askCleanup");
    expect(panelSource).toContain("askBatchStop");
    expect(panelSource).toContain("cleanupSelected");
    expect(panelSource).toContain("requestBranchInstanceCleanup");
    expect(panelSource).toContain("queryClient.invalidateQueries({ queryKey: queryKeys.launcherBranchInstances() })");
    expect(panelSource).toContain("cleanupMutation");
    expect(panelSource).toContain("pendingIds");
    expect(panelSource).toContain("batchStopIds");
    expect(panelSource).toContain("onStopMany");
  });

  it("keeps live instances running and failed zombies in attention", () => {
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
      "worktree:partial",
      "worktree:startable",
    ]);
    expect(groups.attention.map((item) => item.id)).toEqual(["worktree:failed"]);
    expect(groups.startable).toEqual([]);
    expect(groups.maintenance.map((item) => item.id)).toEqual(["retired:old"]);
    expect(instanceRuntimeState(startable, { instanceId: startable.id, operation: "start" })).toBe("starting");
    expect(canStopInstance(failed)).toBe(true);
    expect(instanceStopLabel(failed, true)).toBe("关闭");
    expect(formatAttentionReason(failed, true)).toBe("上次启动失败");
  });

  it("lets a retired failed leftover close without restart", () => {
    const retiredFailed = instance({
      id: "retired:fix-composer",
      kind: "retired",
      checkedOut: false,
      startable: false,
      startBlockReason: "unsupported_kind",
      runtime: {
        ...instance().runtime,
        lifecycleState: "error",
        error: { code: "registry_failed", message: "上次启动失败" },
      },
    });

    expect(groupBranchInstances([retiredFailed]).attention.map((item) => item.id)).toEqual(["retired:fix-composer"]);
    expect(canStopInstance(retiredFailed)).toBe(true);
    expect(instanceStopLabel(retiredFailed, true)).toBe("关闭");
    expect(canStartInstance(retiredFailed)).toBe(false);
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
    expect(formatFrontendStatus(stopped, true)).toBe("前端已构建");
    expect(formatFrontendStatus(running, true)).toBe("前端已构建");
    expect(formatFrontendStatus(
      instance({
        runtime: {
          ...instance().runtime,
          lifecycleState: "error",
          frontend: { mode: "bundled_static_dist", ready: false },
        },
        startable: false,
      }),
      true,
    )).toBe("前端未构建 · 启动时构建");
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

  it("keeps lifecycle controls fail-closed for a stale Launcher runtime contract", () => {
    const stale = instance({
      alive: true,
      startable: false,
      startBlockReason: "launcher_refresh_required",
      runtime: {
        ...instance().runtime,
        lifecycleState: "partial",
        backend: {
          ...instance().runtime.backend,
          alive: true,
          port: 8002,
          pid: 1200,
        },
      },
    });

    expect(canStartInstance(stale)).toBe(false);
    expect(canStopInstance(stale)).toBe(false);
  });

  it("filters branch instances by query and dirty/unmerged chips", () => {
    const dirty = instance({ id: "worktree:dirty", shortName: "timing", dirty: true, mergedToMain: true });
    const unmerged = instance({ id: "worktree:unmerged", shortName: "composer", dirty: false, mergedToMain: false });
    const clean = instance({ id: "worktree:clean", shortName: "clean", dirty: false, mergedToMain: true });

    expect(filterBranchInstances([dirty, unmerged, clean], "timing").map((item) => item.id)).toEqual(["worktree:dirty"]);
    expect(filterBranchInstances([dirty, unmerged, clean], "", { dirty: true }).map((item) => item.id)).toEqual(["worktree:dirty"]);
    expect(filterBranchInstances([dirty, unmerged, clean], "", { unmerged: true }).map((item) => item.id)).toEqual(["worktree:unmerged"]);
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
