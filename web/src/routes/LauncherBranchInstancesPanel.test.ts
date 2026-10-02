import { describe, expect, it } from "vitest";

import type { LauncherBranchInstance } from "../api/launcher";
import panelSource from "./LauncherBranchInstancesPanel.tsx?raw";
import panelStyles from "./LauncherBranchInstancesPanel.styles";
import {
  BRANCH_INSTANCE_PAGE_SIZE,
  canStartInstance,
  canForceStopInstance,
  canStopInstance,
  forceStopTier,
  formatAdmissionReason,
  isAdmissionBlocked,
  cleanupRiskLabels,
  filterBranchInstances,
  formatAttentionReason,
  formatBackendStatus,
  formatFrontendStatus,
  formatGitStatus,
  formatWorkbenchStatus,
  groupBranchInstances,
  canRequestOpenInstance,
  instanceRuntimeState,
  instanceRuntimeStateLabel,
  instanceStopLabel,
  isCleanupEligible,
  overlayCleanupMetadata,
  paginateItems,
  resolveActivePendingOperation,
  acceptLifecycleIntent,
  hasActiveLifecyclePending,
  lifecycleIntentRejectMessage,
  shouldApplyLifecycleMutationFeedback,
  shouldHoldOpenClickGuard,
  settleLifecycleIntentTable,
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
  it("renders a compact branch table with a branch filter and status-driven actions", () => {
    expect(panelSource).toContain("from \"../components/vui\"");
    expect(panelSource).toContain("<VStringSelect");
    expect(panelSource).toContain('value:"all"');
    expect(panelSource).toContain('value:"running"');
    expect(panelSource).toContain('value:"attention"');
    expect(panelSource).toContain('value:"startable"');
    expect(panelSource).not.toContain("<VTabs");
    expect(panelSource).toContain("rows={activeRows}");
    expect(panelSource).toContain('activeTab === "running" ? grouped.running');
    expect(panelSource).toContain('activeTab === "attention" ? grouped.attention');
    expect(panelSource).toContain(": grouped.startable");
    expect(panelSource).toContain("LauncherBranchStatusHelp");
    expect(panelSource).toContain("正在运行");
    expect(panelSource).toContain("需要处理");
    expect(panelSource).toContain("可启动");
    expect(panelSource).toContain("<VNativeInput");
    expect(panelSource).toContain("<VActionGroup");
    expect(panelSource).toContain('aria-label={zh ? "更多操作" : "More actions"}');
    expect(panelSource).toContain('{ id: "details"');
    expect(panelSource).toContain('{ id: "cleanup"');
    // A failed cleanup-metadata read must surface an error with a retry, not
    // an endless loading state on the confirm dialog.
    expect(panelSource).toContain("cleanupConfirmMetadataFailed");
    expect(panelSource).toContain("cleanupMetadataQuery.refetch()");
    // Stop stays a row-level control, never an overflow item.
    expect(panelSource).toMatch(/\{showStop \? \(\s*<VButton[\s\S]{0,400}?askBatchStop\(\[item\.id\], "stop"\)/);
    // Force-stop is tiered by verified process liveness: the inline button
    // renders for the danger/secondary tiers with the variant (and tooltip)
    // keyed off the tier, while a backend-verified dead spawn leaves the row
    // and enters the overflow menu.
    expect(panelSource).toMatch(/\{showForceStop \? \(\s*<VButton[\s\S]{0,400}?variant=\{forceStopTierValue === "danger" \? "danger" : "secondary"\}[\s\S]{0,400}?setForceStopId\(item\.id\)/);
    expect(panelSource).toContain('title={forceStopTierValue === "danger" ? labels.forceStopHint : labels.forceStopStaleHint}');
    expect(panelSource).not.toContain('{ id: "stop"');
    expect(panelSource).toContain('{ id: "force-stop"');
    // The menu route exists only for the verified-dead tier; danger/secondary
    // rows keep their inline button and never grow an overflow entry.
    expect(panelSource).toMatch(/forceStopMenuOnly \? \[\{ id: "force-stop"[\s\S]{0,200}?setForceStopId\(item\.id\)/);
    expect(panelSource).toContain("resizable");
    expect(panelSource).not.toMatch(/from\s+["']@heroui\/react["']/);
    expect(panelSource).not.toMatch(/renderers\/shadcn/);
    expect(panelSource).not.toMatch(/<button\b/);
    expect(BRANCH_INSTANCE_PAGE_SIZE).toBe(8);
  });

  it("keeps runtime and window status together, with Git and secondary actions in their own columns", () => {
    expect(panelSource).toContain("header: copy.branchColumn");
    expect(panelSource).toContain("header: copy.instanceState");
    expect(panelSource).not.toContain("header: labels.backend");
    expect(panelSource).not.toContain("header: labels.frontend");
    expect(panelSource).toContain("header: labels.git");
    expect(panelSource).not.toContain("formatBackendStatus");
    expect(panelSource).not.toContain("formatFrontendStatus");
    expect(panelSource).toContain("formatGitStatus");
    const stateIndex = panelSource.indexOf('id: "state"');
    const gitIndex = panelSource.indexOf('id: "git"', stateIndex);
    expect(stateIndex).toBeGreaterThan(-1);
    expect(gitIndex).toBeGreaterThan(stateIndex);
    expect(panelSource.slice(stateIndex, gitIndex)).toContain("instanceWindowOpen(item)");
    // Single-line state cell: the window hint rides the same line and only
    // appears when it contradicts a running backend (row otherwise grows tall).
    expect(panelSource.slice(stateIndex, gitIndex)).toContain('state === "running" && !instanceWindowOpen(item)');
    expect(panelStyles.runtimeStack).toContain("flex");
    expect(panelStyles.runtimeStack).not.toContain("grid");
    expect(panelSource).toContain("<VDropdownMenu aria-label={zh ? \"更多操作\" : \"More actions\"}");
    // Compact columns still keep the path inside the branch tooltip, not a wide fill column.
    expect(panelSource).toContain("path || item.displayPath || item.id");
    // Narrow widths: the resizable table scrolls inside its own container so the
    // actions column stays discoverable without page-level horizontal overflow.
    expect(panelStyles.statusTable).toBeTypeOf("string");
    expect(panelStyles.statusTable).toContain("w-full");
    expect(panelStyles.panel).toContain("overflow-hidden");
    expect(panelStyles.panel).toContain("min-w-0");
    expect(panelStyles.panelBody).toContain("min-w-0");
    expect(panelStyles.tabBody).toContain("min-w-0");
    expect(panelSource).toContain('id: "branch"');
    expect(panelSource).toMatch(/id: "branch"[\s\S]{0,180}?fill: true/);
    expect(panelSource).not.toContain('id: "workbench"');
    expect(panelStyles.actionCell).not.toContain("sticky");
    expect(panelStyles.statusTable).not.toContain("overflow-auto");
  });

  it("keeps search, branch selector, and secondary filters in one responsive control row", () => {
    const filterRowIndex = panelSource.indexOf('<div className={styles.filterRow}>');

    expect(filterRowIndex).toBeGreaterThan(-1);
    expect(panelSource.indexOf("<VNativeInput", filterRowIndex)).toBeGreaterThan(filterRowIndex);
    expect(panelSource.indexOf("<VStringSelect", filterRowIndex)).toBeGreaterThan(filterRowIndex);
    expect(panelSource.indexOf("<VDropdownMenu", filterRowIndex)).toBeGreaterThan(filterRowIndex);
    expect(panelSource.indexOf("<VTabs", filterRowIndex)).toBe(-1);
    expect(panelStyles.filterRow).toContain("flex-wrap");
    expect(panelStyles.filterRow).toContain("items-center");
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
    expect(panelSource).toContain("const showListLoading = (listLoading && !hasAnyItems) || waitingUnmergedMetadata");
    expect(panelSource).toContain("const filteredEmpty = hasAnyItems && visibleItems.length === 0 && !waitingUnmergedMetadata");
    expect(panelSource).toContain("showListLoading ? <VStateSurface");
    expect(panelSource).toContain('tone="loading"');
    expect(panelSource).toContain(": !hasAnyItems ? <VEmptyState");
    expect(panelSource).toContain("labels.filteredEmptyTitle");
    expect(panelSource).toContain("labels.filteredEmptyHint");
    expect(panelSource).toContain("labels.clearSearch");
    expect(panelSource).toContain("onPress={clearSearch}");
    expect(panelSource).toContain('setQuery("")');
    expect(panelSource).toContain("setFilters({})");
    expect(panelSource).toContain("GitBranch");
  });

  it("keeps integrated cleanup and batch stop/close surfaces intact", () => {
    expect(panelSource).not.toContain("maintenanceFold");
    expect(panelSource).not.toContain("maintenanceBody");
    expect(panelSource).not.toContain("维护与清理");
    expect(panelSource).toContain("<VCheckbox");
    expect(panelSource).toContain("<VConfirmDialog");
    expect(panelSource).toContain("askCleanup");
    expect(panelSource).toContain("askBatchStop");
    expect(panelSource).toContain("cleanupSelected");
    expect(panelSource).toContain("requestBranchInstanceCleanup");
    expect(panelSource).toContain("queryClient.invalidateQueries({ queryKey: [\"launcher\", \"branch-instances\"] })");
    expect(panelSource).toContain("getLauncherBranchInstances({ cleanupMetadata: true })");
    expect(panelSource).toContain("cleanupMutation");
    expect(panelSource).toContain("pendingIds");
    expect(panelSource).toContain("batchStopIds");
    expect(panelSource).toContain("onStopMany");
    expect(panelSource).toContain("const batchStopPending = batchStopItems.some((item) => instanceRuntimeState(item, pendingOperation) === \"stopping\")");
    expect(panelSource).toContain("confirmPending={batchStopPending}");
    expect(panelSource).toContain("batchStopItems.filter((item) => canStopInstance(item, pendingOperation))");
    expect(panelSource).not.toContain("confirmPending={lifecyclePending}");
    expect(panelSource).toContain("confirmDisabled={lifecyclePending || !items.some((item) => item.id === forceStopId && canForceStopInstance(item))}");
    expect(panelSource).toContain("needsCleanupMetadata");
    expect(panelSource).toContain("overlayCleanupMetadata");
    expect(panelSource).toContain("waitingCleanupConfirmMetadata");
  });

  it("keeps cleanup selection in the active branch list without pagination", () => {
    expect(panelSource).toContain("...grouped.maintenance]");
    expect(panelSource).toContain("columns={[selectColumn, ...primaryColumns]}");
    expect(panelSource).toContain("isCleanupEligible(item) ? (");
    expect(panelSource).toContain("labels.cleanupSelected");
    expect(panelSource).toContain("pageEligible = activeRows.filter(isCleanupEligible)");
    expect(panelSource).not.toContain("pageCount");
    expect(panelSource).not.toContain("pagedAll");
    expect(panelStyles.selectCell).toContain("w-9");
  });

  it("overlays cleanup metadata onto fast list rows by id", () => {
    const base = instance({ id: "worktree:task" });
    const [row] = overlayCleanupMetadata(
      [base],
      [instance({
        id: "worktree:task",
        mergedToMain: false,
        cleanupEligible: true,
        cleanupRisks: ["delete_unmerged"],
      })],
    );
    expect(row.mergedToMain).toBe(false);
    expect(row.cleanupEligible).toBe(true);
    expect(row.cleanupRisks).toEqual(["delete_unmerged"]);
    expect(overlayCleanupMetadata([base], null)).toEqual([base]);
  });

  it("disables start and shows remaining cooldown time while admission is blocked", () => {
    const cooled = instance({
      startable: true,
      startBlockReason: "crash_loop_backoff",
      admissionRetryAfterMs: 20_000,
      admissionMessage: "连续启动失败，冷却中，请 20 秒后再试。",
    });
    expect(isAdmissionBlocked(cooled)).toBe(true);
    expect(canStartInstance(cooled)).toBe(false);
    expect(formatAdmissionReason(cooled, true)).toContain("20 秒");
  });

  it("hides unmerged rows until cleanup metadata marks them unmerged", () => {
    const unknown = instance({ id: "worktree:task" });
    const unmerged = instance({ id: "worktree:task", mergedToMain: false });
    expect(filterBranchInstances([unknown], "", { unmerged: true })).toEqual([]);
    expect(filterBranchInstances([unmerged], "", { unmerged: true }).map((item) => item.id)).toEqual(["worktree:task"]);
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
    expect(instanceRuntimeStateLabel("starting", true)).toBe("正在启动");
    expect(canRequestOpenInstance(startable, { instanceId: startable.id, operation: "start" })).toBe(false);
    expect(canStopInstance(startable, { instanceId: startable.id, operation: "start" })).toBe(true);
    expect(canStopInstance(failed)).toBe(true);
    expect(instanceStopLabel(failed, true)).toBe("关闭");
    expect(formatAttentionReason(failed, true)).toBe("上次启动失败");
  });

  it("keeps an accepted start pending until the instance leaves closed", () => {
    const startable = instance({ id: "main", kind: "main", branch: "main", current: true });
    const pending = {
      instanceId: startable.id,
      operation: "start" as const,
      baselineLifecycleState: "closed" as const,
    };

    expect(resolveActivePendingOperation(pending, [startable])).toEqual(pending);
    expect(instanceRuntimeState(startable, pending)).toBe("starting");
    expect(canRequestOpenInstance(startable, pending)).toBe(false);
    expect(resolveActivePendingOperation(pending, [{
      ...startable,
      runtime: { ...startable.runtime, lifecycleState: "starting" },
    }])).toBeUndefined();
    expect(resolveActivePendingOperation(pending, [{
      ...startable,
      runtime: { ...startable.runtime, lifecycleState: "running" },
    }])).toBeUndefined();
    expect(canStopInstance(startable, pending)).toBe(true);
    expect(canStartInstance(startable, pending)).toBe(false);
  });

  it("does not freeze start pending on 正在启动 when the instance is already partial", () => {
    const partial = instance({
      id: "main",
      kind: "main",
      branch: "main",
      current: true,
      runtime: { ...instance().runtime, lifecycleState: "partial" },
    });
    const accepted = acceptLifecycleIntent({}, {
      instanceId: partial.id,
      operation: "start",
      requestId: "open-window",
      baselineLifecycleState: "partial",
    });
    const settled = settleLifecycleIntentTable(accepted.table, [partial]);

    expect(settled).toEqual({});
    expect(instanceRuntimeState(partial, settled)).toBe("partial");
    expect(canRequestOpenInstance(partial, settled)).toBe(true);
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

  it("keeps unknown leftover diagnostic-only and still lets stop cancel an in-flight start", () => {
    const unknownLeftover = instance({
      id: "worktree:legacy",
      startable: false,
      runtime: {
        ...instance().runtime,
        lifecycleState: "error",
        registryClassification: "unknown",
        portLeaseStatus: "reclaimable",
        firstObservedAt: "2026-08-19T06:00:00Z",
        nextReconcileAt: "2026-08-19T06:00:10Z",
        error: { code: "missing_identity", message: "缺少进程身份字段" },
      },
    });
    const unknownStarting = instance({
      id: "worktree:legacy-start",
      runtime: {
        ...instance().runtime,
        registryClassification: "unknown",
      },
    });

    expect(canStopInstance(unknownLeftover)).toBe(false);
    expect(formatAttentionReason(unknownLeftover, true)).toContain("身份未知，仅可诊断");
    expect(formatAttentionReason(unknownLeftover, true)).toContain("端口租约 reclaimable");
    expect(canStopInstance(unknownStarting, { instanceId: unknownStarting.id, operation: "start" })).toBe(true);
  });

  it("tiers force-stop presentation by verified process liveness", () => {
    const stale = instance({
      alive: false,
      runtime: {
        ...instance().runtime,
        lifecycleState: "stopping",
        backend: {
          ...instance().runtime.backend,
          alive: false,
          listening: false,
          port: 0,
        },
      },
    });
    const stoppedUnverified = instance({
      alive: false,
      runtime: { ...instance().runtime, lifecycleState: "closed" },
    });
    const verifiedDead = instance({
      alive: false,
      runtime: { ...instance().runtime, lifecycleState: "closed", spawnIdentityStatus: "dead" },
    });
    const verifiedMatch = instance({
      alive: false,
      runtime: { ...instance().runtime, lifecycleState: "closed", spawnIdentityStatus: "match" },
    });
    const suspiciousMismatch = instance({
      alive: false,
      runtime: { ...instance().runtime, lifecycleState: "closed", spawnIdentityStatus: "mismatch" },
    });
    const current = instance({ current: true, id: "main", kind: "main", branch: "main" });

    // Reachability is unchanged: any non-current row can still reach the
    // force-stop confirm dialog, whatever its tier.
    expect(canForceStopInstance(stale)).toBe(true);
    expect(canForceStopInstance(stoppedUnverified)).toBe(true);
    expect(canForceStopInstance(verifiedDead)).toBe(true);
    expect(canForceStopInstance(current)).toBe(false);
    // Presentation tiers: live signals (runtime or a verified match) keep the
    // red row button; a stopped row without a verified identity softens to
    // secondary because the recorded state may be stale; a backend-verified
    // dead spawn collapses into the overflow menu.
    expect(forceStopTier(stale)).toBe("danger");
    expect(forceStopTier(verifiedMatch)).toBe("danger");
    expect(forceStopTier(stoppedUnverified)).toBe("secondary");
    expect(forceStopTier(suspiciousMismatch)).toBe("secondary");
    expect(forceStopTier(verifiedDead)).toBe("menu");
  });

  it("keeps a force-stop exit for the current/main row while its lifecycle is stuck in error", () => {
    const currentError = instance({
      current: true,
      id: "main",
      kind: "main",
      branch: "main",
      runtime: {
        ...instance().runtime,
        lifecycleState: "error",
        error: { code: "runtime_error", message: "launch failed" },
      },
    });
    const currentRunning = instance({ current: true, id: "main", kind: "main", branch: "main" });

    expect(canForceStopInstance(currentError)).toBe(true);
    expect(canForceStopInstance(currentRunning)).toBe(false);
  });

  it("lets an unknown missing-worktree leftover close without cleanup", () => {
    const missing = instance({
      id: "retired:agent-config-focused-implementation",
      kind: "retired",
      checkedOut: false,
      startable: false,
      startBlockReason: "unsupported_kind",
      runtime: {
        ...instance().runtime,
        lifecycleState: "error",
        registryClassification: "unknown",
        error: { code: "runtime_error", message: "worktree_path_missing" },
      },
    });

    expect(canStopInstance(missing)).toBe(true);
    expect(instanceStopLabel(missing, true)).toBe("关闭");
    expect(canRequestOpenInstance(missing)).toBe(false);
    expect(canStartInstance(missing)).toBe(false);
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

  it("keeps main and live rows visible when git hygiene filters are on", () => {
    const main = instance({
      id: "main",
      kind: "main",
      branch: "main",
      shortName: "main",
      mergedToMain: true,
      runtime: {
        ...instance().runtime,
        lifecycleState: "running",
        window: { open: true, pid: 42, title: "main 台", titleObserved: true },
      },
    });
    const runningMerged = instance({
      id: "worktree:live",
      mergedToMain: true,
      runtime: {
        ...instance().runtime,
        lifecycleState: "running",
        backend: { ...instance().runtime.backend, alive: true, listening: true, pid: 88 },
      },
    });
    const startingMerged = instance({
      id: "worktree:starting",
      mergedToMain: true,
      runtime: { ...instance().runtime, lifecycleState: "starting" },
    });
    const stoppedMerged = instance({ id: "worktree:merged", mergedToMain: true });
    const unmerged = instance({ id: "worktree:unmerged", mergedToMain: false });

    expect(
      filterBranchInstances(
        [main, runningMerged, startingMerged, stoppedMerged, unmerged],
        "",
        { unmerged: true },
      ).map((item) => item.id),
    ).toEqual(["main", "worktree:live", "worktree:starting", "worktree:unmerged"]);
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

  it("lets stop supersede an in-flight start without blocking a different instance", () => {
    const startable = instance({ id: "worktree:one" });
    const other = instance({ id: "worktree:two" });
    const restarting = instance({
      id: "worktree:restart",
      runtime: { ...instance().runtime, lifecycleState: "running" },
      startable: false,
    });
    let table = acceptLifecycleIntent({}, {
      instanceId: startable.id,
      operation: "start",
      requestId: "req-start-1",
      baselineLifecycleState: "closed",
    });
    expect(table.accepted).toBe(true);
    expect(canStopInstance(startable, table.table)).toBe(true);
    expect(canStartInstance(other, table.table)).toBe(true);

    const duplicateStart = acceptLifecycleIntent(table.table, {
      instanceId: startable.id,
      operation: "start",
      requestId: "req-start-1b",
    });
    expect(duplicateStart.accepted).toBe(false);
    expect(duplicateStart.reason).toBe("duplicate");

    const otherStart = acceptLifecycleIntent(table.table, {
      instanceId: other.id,
      operation: "start",
      requestId: "req-start-2",
      baselineLifecycleState: "closed",
    });
    expect(otherStart.accepted).toBe(true);

    const stop = acceptLifecycleIntent(otherStart.table, {
      instanceId: startable.id,
      operation: "stop",
      requestId: "req-stop-1",
      baselineLifecycleState: "closed",
    });
    expect(stop.accepted).toBe(true);
    expect(stop.intent?.localRevision).toBe(2);
    expect(instanceRuntimeState(startable, stop.table)).toBe("stopping");
    expect(instanceRuntimeState(other, stop.table)).toBe("starting");
    expect(shouldApplyLifecycleMutationFeedback(stop.table, {
      instanceId: startable.id,
      requestId: "req-start-1",
      localRevision: 1,
    })).toBe(false);
    expect(shouldApplyLifecycleMutationFeedback(stop.table, {
      instanceId: startable.id,
      requestId: "req-stop-1",
      localRevision: 2,
    })).toBe(true);

    const blockedStart = acceptLifecycleIntent(stop.table, {
      instanceId: startable.id,
      operation: "start",
      requestId: "req-start-late",
    });
    expect(blockedStart.accepted).toBe(false);
    expect(blockedStart.reason).toBe("blocked");

    const restartStop = acceptLifecycleIntent({}, {
      instanceId: restarting.id,
      operation: "restart",
      requestId: "req-restart-1",
      baselineLifecycleState: "running",
    });
    const restartThenStop = acceptLifecycleIntent(restartStop.table, {
      instanceId: restarting.id,
      operation: "stop",
      requestId: "req-stop-restart",
      baselineLifecycleState: "running",
    });
    expect(canStopInstance(restarting, restartStop.table)).toBe(true);
    expect(restartThenStop.accepted).toBe(true);
    expect(instanceRuntimeState(restarting, restartThenStop.table)).toBe("stopping");
    expect(canStopInstance(restarting, restartThenStop.table)).toBe(false);
  });

  it("keeps a stop intent through a late start success or error after the row is already closed", () => {
    const startable = instance({ id: "main", kind: "main", branch: "main", current: true });
    const started = acceptLifecycleIntent({}, {
      instanceId: startable.id,
      operation: "start",
      requestId: "start-old",
      baselineLifecycleState: "closed",
    });
    const stopped = acceptLifecycleIntent(started.table, {
      instanceId: startable.id,
      operation: "stop",
      requestId: "stop-now",
      baselineLifecycleState: "closed",
    });
    const lateStart = {
      instanceId: startable.id,
      requestId: "start-old",
      localRevision: started.intent?.localRevision,
    };

    expect(shouldApplyLifecycleMutationFeedback(stopped.table, lateStart)).toBe(false);
    expect(shouldApplyLifecycleMutationFeedback(stopped.table, {
      instanceId: startable.id,
      requestId: "stop-now",
      localRevision: stopped.intent?.localRevision,
    })).toBe(true);
    expect(settleLifecycleIntentTable(stopped.table, [startable])).toEqual(stopped.table);
    expect(instanceRuntimeState(startable, stopped.table)).toBe("stopping");
  });

  it("does not globally disable stop while a start is in flight", () => {
    expect(panelSource).toContain("const startBusy");
    expect(panelSource).toContain("const stopBusy");
    expect(panelSource).toContain("isDisabled={startBusy || stopBusy || admissionBlocked}");
    expect(panelSource).toContain("isDisabled={stopBusy}\n            isPending={stopBusy}");
    expect(panelSource).not.toContain("disabled: lifecyclePending || inFlight");
    expect(panelSource).not.toContain("isDisabled={lifecyclePending || startBusy || stopBusy}");
    expect(panelSource).toContain("if (startBusy || admissionBlocked || openClickGuardsRef.current.has(item.id))");
    expect(panelSource).not.toContain("if (clickGuardRef.current || startBusy)");
    expect(panelSource).not.toContain("if (clickGuardRef.current || lifecyclePending || inFlight)");
  });

  it("keeps Stop available as a row-level control while a start is in flight", () => {
    const startable = instance({ id: "worktree:startable", shortName: "startable" });
    expect(panelSource).toContain("const showOpen = canRequestOpenInstance(item, pendingOperation) || startBusy || stopBusy");
    expect(panelSource).toContain("const showStop = canStopInstance(item, pendingOperation) || stopBusy");
    expect(panelSource).toContain("{instanceStopLabel(item, zh, pendingOperation)}\n          </VButton>");
    expect(panelSource).toContain("isPending={startBusy || stopBusy}");
    expect(panelSource).toContain("<VActionGroup");
    expect(canStopInstance(startable, { instanceId: startable.id, operation: "start" })).toBe(true);
  });

  it("releases the Open window click guard when the row is not actually starting", () => {
    expect(shouldHoldOpenClickGuard("starting")).toBe(true);
    expect(shouldHoldOpenClickGuard("restarting")).toBe(true);
    expect(shouldHoldOpenClickGuard("stopping")).toBe(true);
    expect(shouldHoldOpenClickGuard("stopped")).toBe(false);
    expect(shouldHoldOpenClickGuard("failed")).toBe(false);
    expect(shouldHoldOpenClickGuard("running")).toBe(false);
    expect(panelSource).toContain("shouldHoldOpenClickGuard(instanceRuntimeState(item, pendingOperation))");
    expect(panelSource).not.toContain("if (!lifecyclePending && !hasActiveLifecyclePending(pendingOperation))");
    expect(panelSource).toContain("openClickGuardsRef.current.delete(item.id)");
  });

  it("treats an empty intent table as not pending so Open window can retry after a rejected start", () => {
    const startable = instance({ id: "main", kind: "main", branch: "main", current: true });
    expect(hasActiveLifecyclePending(undefined)).toBe(false);
    expect(hasActiveLifecyclePending({})).toBe(false);
    expect(hasActiveLifecyclePending({
      instanceId: startable.id,
      operation: "start",
      baselineLifecycleState: "closed",
    })).toBe(true);
    const started = acceptLifecycleIntent({}, {
      instanceId: startable.id,
      operation: "start",
      requestId: "req-start-guard",
      baselineLifecycleState: "closed",
    });
    expect(started.accepted).toBe(true);
    expect(hasActiveLifecyclePending(started.table)).toBe(true);
    expect(hasActiveLifecyclePending(settleLifecycleIntentTable({}, [startable]))).toBe(false);
    expect(lifecycleIntentRejectMessage("duplicate", true)).toBe("启动已在进行中");
    expect(lifecycleIntentRejectMessage("blocked", false)).toBe("Wait for the current operation to finish before starting");
    expect(panelSource).toContain("shouldHoldOpenClickGuard");
    expect(panelSource).toContain("outcome.accepted === false");
    expect(panelSource).toContain("lifecycleIntentRejectMessage");
  });

  it("turns the start control into a disabled Building state while the frontend build gates the start", () => {
    const building = instance({
      id: "worktree:building",
      shortName: "building",
      runtime: {
        ...instance().runtime,
        lifecycleState: "building",
        phase: "building",
        observedState: "building",
      },
    });
    expect(instanceRuntimeState(building)).toBe("building");
    // The start IPC blocks for the whole frontend build, so the accepted
    // start intent stays active while the payload already reports building;
    // payload truth must win over the optimistic starting label or the whole
    // build window renders as 正在启动 again.
    const startIntent = { instanceId: "worktree:building", operation: "start" as const };
    expect(instanceRuntimeState(building, startIntent)).toBe("building");
    expect(
      instanceRuntimeState(building, { instanceId: "worktree:building", operation: "restart" as const })
    ).toBe("building");
    // The disabled pending button contract is keyed off this state: the row
    // above with a live start intent renders isPending + 构建中… through it.
    expect(instanceRuntimeStateLabel("building", true)).toBe("构建中");
    expect(instanceRuntimeStateLabel("building", false)).toBe("Building");
    expect(shouldHoldOpenClickGuard("building")).toBe(true);
    expect(canRequestOpenInstance(building)).toBe(false);
    expect(canStartInstance(building)).toBe(false);
    expect(groupBranchInstances([building]).running.map((item) => item.id)).toEqual(["worktree:building"]);
    expect(groupBranchInstances([building]).attention).toEqual([]);
    // The primary control stays visible but disabled with a pending spinner;
    // the long build explanation is carried by its tooltip, not inline text.
    expect(panelSource).toContain("const showOpen = canRequestOpenInstance(item, pendingOperation) || startBusy || stopBusy");
    expect(panelSource).toContain("isPending={startBusy || stopBusy}");
    expect(panelSource).toContain("isDisabled={startBusy || stopBusy || admissionBlocked}");
    expect(panelSource).toContain("{startBusy || stopBusy ? instanceRuntimeStateLabel(state, zh) : openLabel}");
    expect(panelSource).toContain("title={building ? labels.buildingHint : undefined}");
    expect(panelSource).toContain('building: "构建中…"');
    expect(panelSource).toContain('building: "Building…"');
    expect(panelSource).toContain("buildingHint: \"前端代码有更新，正在构建新版本，约需几分钟。\"");
    expect(panelSource).toContain("buildingHint: \"The frontend has updates and a new build is running. This takes a few minutes.\"");
    // Build state keeps the row out of attention and out of cleanup.
    expect(panelSource).toContain("disabled: cleanupMutation.isPending || building || startingOrRestarting || stopBusy");
  });

  it("keeps the optimistic starting label for a starting payload with a start intent", () => {
    // Regression: only the building payload overrides the pending intent; a
    // payload that already started keeps the existing optimistic semantics.
    const starting = instance({
      id: "worktree:starting",
      shortName: "starting",
      runtime: {
        ...instance().runtime,
        lifecycleState: "starting",
        phase: "opening",
        observedState: "starting",
      },
    });
    expect(instanceRuntimeState(starting, { instanceId: "worktree:starting", operation: "start" })).toBe("starting");
    expect(instanceRuntimeState(starting)).toBe("starting");
    expect(instanceRuntimeStateLabel("starting", true)).toBe("正在启动");
  });
});
