import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { requestBranchInstanceCleanup, type LauncherBranchInstance } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import { VButton, VCheckbox, VConfirmDialog, VDenseTable, VNativeInput, VStatusChip, VToolbar, VTooltip } from "../components/vui";
import type { LauncherOperation } from "../api/types";
import { LauncherBranchStatusHelp } from "./LauncherBranchStatusHelp";
import {
  BRANCH_INSTANCE_PAGE_SIZE,
  canRequestOpenInstance,
  canStopInstance,
  cleanupRiskLabels,
  filterBranchInstances,
  formatAttentionReason,
  formatBackendStatus,
  formatFrontendStatus,
  formatGitStatus,
  formatWorkbenchStatus,
  groupBranchInstances,
  instanceErrorMessage,
  instanceRuntimeState,
  instanceRuntimeStateLabel,
  instanceStopLabel,
  instanceWindowOpen,
  isCleanupEligible,
  paginateItems,
  type InstanceListFilters,
  type InstancePendingOperation,
  type InstanceRuntimeState,
} from "./LauncherBranchInstancesPanel.model";
import styles from "./LauncherBranchInstancesPanel.styles";

type LauncherBranchInstancesCopy = {
  branchInstances: string;
  branchInstancesHint: string;
  branchColumn: string;
  instanceState: string;
  instanceKind: string;
  instancePath: string;
  currentInstance: string;
  legacyCheckout: string;
  retiredCheckout: string;
  notCheckedOut: string;
};

type LauncherBranchInstancesPanelProps = {
  copy: LauncherBranchInstancesCopy;
  items: LauncherBranchInstance[];
  selectedId: string;
  onSelect: (id: string) => void;
  pendingOperation?: InstancePendingOperation;
  launcherTitle?: string;
  launcherOnline?: boolean;
  lifecyclePending?: boolean;
  onLifecycle?: (instanceId: string, operation: Extract<LauncherOperation, "start" | "stop">) => void;
  onStopMany?: (instanceIds: string[]) => void;
};

function isZhCopy(copy: LauncherBranchInstancesCopy): boolean {
  return copy.branchInstances !== "Branch instances";
}

function runtimeTone(state: InstanceRuntimeState): "neutral" | "success" | "warning" {
  if (state === "running") {
    return "success";
  }
  if (state === "partial" || state === "failed") {
    return "warning";
  }
  return "neutral";
}

function SectionPager({
  ariaLabel,
  page,
  pageCount,
  start,
  end,
  total,
  previousLabel,
  nextLabel,
  onPrevious,
  onNext,
}: {
  ariaLabel: string;
  page: number;
  pageCount: number;
  start: number;
  end: number;
  total: number;
  previousLabel: string;
  nextLabel: string;
  onPrevious: () => void;
  onNext: () => void;
}) {
  return (
    <div className={styles.pager} aria-label={ariaLabel}>
      <span className={styles.rangeLabel}>
        {start + (end > start ? 1 : 0)}-{end} / {total}
      </span>
      <VButton type="button" density="compact" variant="secondary" isDisabled={page <= 1} onPress={onPrevious}>
        {previousLabel}
      </VButton>
      <strong>{page}/{pageCount}</strong>
      <VButton type="button" density="compact" variant="secondary" isDisabled={page >= pageCount} onPress={onNext}>
        {nextLabel}
      </VButton>
    </div>
  );
}

export function LauncherBranchInstancesPanel({
  copy,
  items,
  selectedId,
  onSelect,
  pendingOperation,
  launcherTitle,
  launcherOnline = false,
  lifecyclePending = false,
  onLifecycle,
  onStopMany,
}: LauncherBranchInstancesPanelProps) {
  const queryClient = useQueryClient();
  const zh = isZhCopy(copy);
  const labels = zh
    ? {
        running: "正在运行",
        runningHint: "后端或窗口仍活着的实例",
        attention: "需要处理",
        attentionHint: "启动失败或卡住，关闭后回到可启动，不会删除 worktree",
        startable: "可启动",
        startableHint: "已具备 worktree，当前没有运行信号",
        maintenance: "维护与清理",
        controlWindow: "Launcher 控制窗口",
        online: "在线",
        offline: "未连接",
        emptyRunning: "当前没有运行中的分支",
        emptyAttention: "当前没有需要处理的实例",
        emptyStartable: "当前没有可启动的分支",
        cleanup: "清理",
        cleanupSelected: "清理所选",
        cleanupConfirmTitle: "确认清理分支实例",
        cleanupConfirmHint: "只删除本地 worktree 和本地分支，不会删除远端。",
        previous: "上一页",
        next: "下一页",
        selectPage: "选择本页可清理项",
        actions: "操作",
        backend: "后端",
        frontend: "前端",
        frontendMode: "前端模式",
        workbench: "Workbench 窗口",
        git: "Git",
        reason: "原因",
        readiness: "启动准备",
        ready: "可以启动",
        startWorkbench: "启动工作台",
        openWindow: "打开窗口",
        focusWindow: "聚焦窗口",
        retryStart: "重新启动",
        stop: "停止",
        close: "关闭",
        stopAll: "停止全部",
        closeAll: "全部关闭",
        stopConfirmTitle: "确认停止这些工作台",
        closeConfirmTitle: "确认关闭这些实例",
        stopConfirmHint: "会停止后端并关闭窗口，不会删除 worktree 或未提交改动。",
        search: "搜索分支",
        searchPlaceholder: "搜索分支、路径…",
        filterDirty: "未提交",
        filterUnmerged: "未合入",
        noRisk: "无额外风险提示",
        pending: "正在清理所选实例…",
        done: "清理完成",
        failed: "部分实例未能清理",
      }
    : {
        running: "Running",
        runningHint: "Instances whose backend or window is still alive",
        attention: "Needs attention",
        attentionHint: "Failed or stuck instances. Close returns them to Ready to start without deleting the worktree",
        startable: "Ready to start",
        startableHint: "Checked-out worktrees with no active runtime signal",
        maintenance: "Maintenance and cleanup",
        controlWindow: "Launcher control window",
        online: "Online",
        offline: "Disconnected",
        emptyRunning: "No branch is currently running",
        emptyAttention: "No instance needs attention",
        emptyStartable: "No branch is currently ready to start",
        cleanup: "Clean up",
        cleanupSelected: "Clean up selected",
        cleanupConfirmTitle: "Confirm branch cleanup",
        cleanupConfirmHint: "This deletes local worktrees and local branches only. Remotes are not deleted.",
        previous: "Previous",
        next: "Next",
        selectPage: "Select cleanable items on this page",
        actions: "Actions",
        backend: "Backend",
        frontend: "Frontend",
        frontendMode: "Frontend mode",
        workbench: "Workbench window",
        git: "Git",
        reason: "Reason",
        readiness: "Readiness",
        ready: "Ready to start",
        startWorkbench: "Start workbench",
        openWindow: "Open window",
        focusWindow: "Focus window",
        retryStart: "Retry start",
        stop: "Stop",
        close: "Close",
        stopAll: "Stop all",
        closeAll: "Close all",
        stopConfirmTitle: "Confirm stopping these workbenches",
        closeConfirmTitle: "Confirm closing these instances",
        stopConfirmHint: "This stops backends and closes windows. Worktrees and uncommitted changes are kept.",
        search: "Search branches",
        searchPlaceholder: "Search branch or path…",
        filterDirty: "Uncommitted",
        filterUnmerged: "Not merged",
        noRisk: "No extra risk listed",
        pending: "Cleaning selected instances…",
        done: "Cleanup finished",
        failed: "Some instances could not be cleaned",
      };

  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<InstanceListFilters>({});
  const [startablePage, setStartablePage] = useState(1);
  const [maintenancePage, setMaintenancePage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [pendingIds, setPendingIds] = useState<string[] | null>(null);
  const [batchStopIds, setBatchStopIds] = useState<string[] | null>(null);
  const [batchStopKind, setBatchStopKind] = useState<"stop" | "close">("stop");
  const [notice, setNotice] = useState("");
  const [noticeTone, setNoticeTone] = useState<"neutral" | "error">("neutral");

  const visibleItems = useMemo(() => filterBranchInstances(items, query, filters), [filters, items, query]);
  const grouped = useMemo(() => groupBranchInstances(visibleItems, pendingOperation), [pendingOperation, visibleItems]);
  const maintenanceItems = useMemo(() => visibleItems.filter(isCleanupEligible), [visibleItems]);
  const pagedStartable = useMemo(
    () => paginateItems(grouped.startable, startablePage, BRANCH_INSTANCE_PAGE_SIZE),
    [grouped.startable, startablePage],
  );
  const pagedMaintenance = useMemo(
    () => paginateItems(maintenanceItems, maintenancePage, BRANCH_INSTANCE_PAGE_SIZE),
    [maintenanceItems, maintenancePage],
  );

  useEffect(() => {
    if (pagedStartable.page !== startablePage) {
      setStartablePage(pagedStartable.page);
    }
  }, [pagedStartable.page, startablePage]);
  useEffect(() => {
    if (pagedMaintenance.page !== maintenancePage) {
      setMaintenancePage(pagedMaintenance.page);
    }
  }, [maintenancePage, pagedMaintenance.page]);
  useEffect(() => {
    const startableIndex = grouped.startable.findIndex((item) => item.id === selectedId);
    if (startableIndex >= 0) {
      setStartablePage(Math.floor(startableIndex / BRANCH_INSTANCE_PAGE_SIZE) + 1);
    }
    const maintenanceIndex = maintenanceItems.findIndex((item) => item.id === selectedId);
    if (maintenanceIndex >= 0) {
      setMaintenancePage(Math.floor(maintenanceIndex / BRANCH_INSTANCE_PAGE_SIZE) + 1);
    }
  }, [grouped.startable, maintenanceItems, selectedId]);

  const knownIds = useMemo(() => new Set(items.map((item) => item.id)), [items]);
  const cleanupSelected = selectedIds.filter((id) => knownIds.has(id) && maintenanceItems.some((item) => item.id === id));
  const pageEligible = pagedMaintenance.items;
  const pageSelectedCount = pageEligible.filter((item) => cleanupSelected.includes(item.id)).length;
  const allPageSelected = pageEligible.length > 0 && pageSelectedCount === pageEligible.length;
  const pendingItems = pendingIds ? items.filter((item) => pendingIds.includes(item.id)) : [];
  const batchStopItems = batchStopIds ? items.filter((item) => batchStopIds.includes(item.id)) : [];

  const cleanupMutation = useMutation({
    mutationFn: (instanceIds: string[]) => requestBranchInstanceCleanup(instanceIds, true),
    onSuccess: (payload) => {
      const failed = [...payload.failed, ...payload.skipped];
      setNotice(failed.length > 0 ? `${labels.failed}：${failed.map((item) => item.shortName || item.id).join("、")}` : labels.done);
      setNoticeTone(failed.length > 0 ? "error" : "neutral");
      setSelectedIds((current) => current.filter((id) => !payload.cleaned.some((item) => item.id === id)));
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherBranchInstances() });
    },
    onError: (error) => {
      setNotice(error instanceof Error ? error.message : labels.failed);
      setNoticeTone("error");
    },
    onSettled: () => {
      setPendingIds(null);
    },
  });

  const toggleSelected = (item: LauncherBranchInstance, next: boolean) => {
    if (!isCleanupEligible(item)) {
      return;
    }
    setSelectedIds((current) => {
      if (next) {
        return current.includes(item.id) ? current : [...current, item.id];
      }
      return current.filter((id) => id !== item.id);
    });
  };

  const togglePage = (next: boolean) => {
    const pageIds = pageEligible.map((item) => item.id);
    setSelectedIds((current) => {
      if (next) {
        return [...new Set([...current, ...pageIds])];
      }
      return current.filter((id) => !pageIds.includes(id));
    });
  };

  const askCleanup = (ids: string[]) => {
    const eligible = items.filter((item) => ids.includes(item.id) && isCleanupEligible(item)).map((item) => item.id);
    if (eligible.length === 0) {
      return;
    }
    setNotice("");
    setPendingIds(eligible);
  };

  const askBatchStop = (ids: string[], kind: "stop" | "close") => {
    const eligible = items.filter((item) => ids.includes(item.id) && canStopInstance(item, pendingOperation)).map((item) => item.id);
    if (eligible.length === 0) {
      return;
    }
    setBatchStopKind(kind);
    setBatchStopIds(eligible);
  };

  const renderLifecycleActions = (item: LauncherBranchInstance) => {
    const state = instanceRuntimeState(item, pendingOperation);
    const windowOpen = instanceWindowOpen(item);
    const openLabel = state === "failed" ? labels.retryStart : windowOpen ? labels.focusWindow : labels.openWindow;
    return (
      <span className={styles.actionButtons} onClick={(event) => event.stopPropagation()}>
        {canRequestOpenInstance(item, pendingOperation) ? (
          <VButton type="button" variant="primary" density="compact" isDisabled={lifecyclePending} onPress={() => onLifecycle?.(item.id, "start")}>
            {openLabel}
          </VButton>
        ) : null}
        {canStopInstance(item, pendingOperation) ? (
          <VButton type="button" variant="secondary" density="compact" isDisabled={lifecyclePending} onPress={() => onLifecycle?.(item.id, "stop")}>
            {instanceStopLabel(item, zh, pendingOperation)}
          </VButton>
        ) : null}
      </span>
    );
  };

  return (
    <section className={styles.panel} data-vui-region="launcher-branch-instances" aria-label={copy.branchInstances}>
      <div className={styles.panelHeader}>
        <p className={styles.panelEyebrow}>{copy.branchInstances}</p>
        <p className={styles.controlWindow} role="status">
          <span>{labels.controlWindow}</span>
          <strong>{launcherTitle || "-"}</strong>
          <VStatusChip tone={launcherOnline ? "success" : "warning"}>
            {launcherOnline ? labels.online : labels.offline}
          </VStatusChip>
        </p>
      </div>

      <VToolbar ariaLabel={labels.search} className={styles.filterBar}>
        <VNativeInput
          aria-label={labels.search}
          className={styles.searchInput}
          placeholder={labels.searchPlaceholder}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <VButton
          type="button"
          density="compact"
          variant={filters.dirty ? "secondary" : "ghost"}
          onPress={() => setFilters((current) => ({ ...current, dirty: !current.dirty }))}
        >
          {labels.filterDirty}
        </VButton>
        <VButton
          type="button"
          density="compact"
          variant={filters.unmerged ? "secondary" : "ghost"}
          onPress={() => setFilters((current) => ({ ...current, unmerged: !current.unmerged }))}
        >
          {labels.filterUnmerged}
        </VButton>
      </VToolbar>

      <section className={styles.instanceSection} aria-label={labels.running}>
        <div className={styles.sectionHeaderWithPager}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionTitleRow}>
              <h2>{labels.running}</h2>
              <span className={styles.sectionCount}>{grouped.running.length}</span>
            </div>
            <p>{labels.runningHint}</p>
          </div>
          <VButton
            type="button"
            density="compact"
            variant="secondary"
            isDisabled={lifecyclePending || grouped.running.every((item) => !canStopInstance(item, pendingOperation))}
            onPress={() => askBatchStop(grouped.running.map((item) => item.id), "stop")}
          >
            {labels.stopAll}
          </VButton>
        </div>
        <VDenseTable
          ariaLabel={labels.running}
          className={styles.statusTable}
          resizable
          rows={grouped.running}
          emptyText={labels.emptyRunning}
          getRowKey={(item) => item.id}
          onRowClick={(item) => onSelect(item.id)}
          getRowState={(item) => ({
            selected: item.id === selectedId,
            tone: runtimeTone(instanceRuntimeState(item, pendingOperation)),
          })}
          columns={[
            {
              id: "branch",
              header: copy.branchColumn,
              width: 210,
              minWidth: 120,
              render: (item) => (
                <VTooltip content={`${item.shortName || item.branch || item.id} · ${item.branch || item.id} · ${item.path || item.displayPath || item.id}`} width="wide">
                  <span className={styles.branchName}>{item.shortName || item.branch || item.id}</span>
                </VTooltip>
              ),
            },
            {
              id: "state",
              header: copy.instanceState,
              width: 104,
              minWidth: 88,
              render: (item) => {
                const state = instanceRuntimeState(item, pendingOperation);
                return (
                  <LauncherBranchStatusHelp item={item} state={state} isZh={zh} kind="runtime">
                    <VStatusChip tone={runtimeTone(state)}>
                      {instanceRuntimeStateLabel(state, zh)}
                    </VStatusChip>
                  </LauncherBranchStatusHelp>
                );
              },
            },
            {
              id: "backend",
              header: labels.backend,
              width: 132,
              minWidth: 104,
              render: (item) => formatBackendStatus(item, zh),
            },
            {
              id: "frontend",
              header: labels.frontend,
              width: 138,
              minWidth: 112,
              render: (item) => formatFrontendStatus(item, zh),
            },
            {
              id: "workbench",
              header: labels.workbench,
              width: 230,
              minWidth: 160,
              fill: true,
              render: (item) => formatWorkbenchStatus(item, zh),
            },
            {
              id: "git",
              header: labels.git,
              width: 142,
              minWidth: 92,
              render: (item) => {
                const state = instanceRuntimeState(item, pendingOperation);
                return (
                  <LauncherBranchStatusHelp item={item} state={state} isZh={zh} kind="git">
                    <span>{formatGitStatus(item, zh)}</span>
                  </LauncherBranchStatusHelp>
                );
              },
            },
            {
              id: "actions",
              header: labels.actions,
              align: "right",
              width: 188,
              minWidth: 148,
              truncate: false,
              className: styles.actionCell,
              render: renderLifecycleActions,
            },
          ]}
        />
      </section>

      <section className={styles.instanceSection} aria-label={labels.attention}>
        <div className={styles.sectionHeaderWithPager}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionTitleRow}>
              <h2>{labels.attention}</h2>
              <span className={styles.sectionCount}>{grouped.attention.length}</span>
            </div>
            <p>{labels.attentionHint}</p>
          </div>
          <VButton
            type="button"
            density="compact"
            variant="secondary"
            isDisabled={lifecyclePending || grouped.attention.every((item) => !canStopInstance(item, pendingOperation))}
            onPress={() => askBatchStop(grouped.attention.map((item) => item.id), "close")}
          >
            {labels.closeAll}
          </VButton>
        </div>
        <VDenseTable
          ariaLabel={labels.attention}
          className={styles.statusTable}
          resizable
          rows={grouped.attention}
          emptyText={labels.emptyAttention}
          getRowKey={(item) => item.id}
          onRowClick={(item) => onSelect(item.id)}
          getRowState={(item) => ({
            selected: item.id === selectedId,
            tone: "warning",
          })}
          columns={[
            {
              id: "branch",
              header: copy.branchColumn,
              width: 210,
              minWidth: 120,
              render: (item) => (
                <VTooltip content={`${item.shortName || item.branch || item.id} · ${item.branch || item.id} · ${item.path || item.displayPath || item.id}`} width="wide">
                  <span className={styles.branchName}>{item.shortName || item.branch || item.id}</span>
                </VTooltip>
              ),
            },
            {
              id: "state",
              header: copy.instanceState,
              width: 104,
              minWidth: 88,
              render: (item) => {
                const state = instanceRuntimeState(item, pendingOperation);
                const error = instanceErrorMessage(item);
                return (
                  <LauncherBranchStatusHelp item={item} state={state} isZh={zh} kind="runtime">
                    <span>
                      <VStatusChip tone={runtimeTone(state)}>
                        {instanceRuntimeStateLabel(state, zh)}
                      </VStatusChip>
                      {error ? <span className={styles.errorReason}>{error}</span> : null}
                    </span>
                  </LauncherBranchStatusHelp>
                );
              },
            },
            {
              id: "reason",
              header: labels.reason,
              width: 280,
              minWidth: 160,
              fill: true,
              render: (item) => formatAttentionReason(item, zh),
            },
            {
              id: "git",
              header: labels.git,
              width: 142,
              minWidth: 92,
              render: (item) => {
                const state = instanceRuntimeState(item, pendingOperation);
                return (
                  <LauncherBranchStatusHelp item={item} state={state} isZh={zh} kind="git">
                    <span>{formatGitStatus(item, zh)}</span>
                  </LauncherBranchStatusHelp>
                );
              },
            },
            {
              id: "actions",
              header: labels.actions,
              align: "right",
              width: 188,
              minWidth: 148,
              truncate: false,
              className: styles.actionCell,
              render: renderLifecycleActions,
            },
          ]}
        />
      </section>

      <section className={styles.instanceSection} aria-label={labels.startable}>
        <div className={styles.sectionHeaderWithPager}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionTitleRow}>
              <h2>{labels.startable}</h2>
              <span className={styles.sectionCount}>{grouped.startable.length}</span>
            </div>
            <p>{labels.startableHint}</p>
          </div>
          <SectionPager
            ariaLabel={labels.startable}
            page={pagedStartable.page}
            pageCount={pagedStartable.pageCount}
            start={pagedStartable.start}
            end={pagedStartable.end}
            total={grouped.startable.length}
            previousLabel={labels.previous}
            nextLabel={labels.next}
            onPrevious={() => setStartablePage((current) => current - 1)}
            onNext={() => setStartablePage((current) => current + 1)}
          />
        </div>
        <VDenseTable
          ariaLabel={labels.startable}
          className={styles.statusTable}
          resizable
          rows={pagedStartable.items}
          emptyText={labels.emptyStartable}
          getRowKey={(item) => item.id}
          onRowClick={(item) => onSelect(item.id)}
          getRowState={(item) => ({ selected: item.id === selectedId, tone: "neutral" })}
          columns={[
            {
              id: "branch",
              header: copy.branchColumn,
              width: 230,
              minWidth: 120,
              render: (item) => (
                <VTooltip content={`${item.shortName || item.branch || item.id} · ${item.branch || item.id} · ${item.path || item.displayPath || item.id}`} width="wide">
                  <span className={styles.branchName}>{item.shortName || item.branch || item.id}</span>
                </VTooltip>
              ),
            },
            {
              id: "readiness",
              header: labels.readiness,
              width: 112,
              minWidth: 92,
              render: (item) => (
                <LauncherBranchStatusHelp item={item} state="stopped" isZh={zh} kind="runtime">
                  <VStatusChip tone="success">{labels.ready}</VStatusChip>
                </LauncherBranchStatusHelp>
              ),
            },
            {
              id: "frontend",
              header: labels.frontendMode,
              width: 150,
              minWidth: 120,
              render: (item) => formatFrontendStatus(item, zh),
            },
            {
              id: "git",
              header: labels.git,
              width: 160,
              minWidth: 100,
              render: (item) => (
                <LauncherBranchStatusHelp item={item} state="stopped" isZh={zh} kind="git">
                  <span>{formatGitStatus(item, zh)}</span>
                </LauncherBranchStatusHelp>
              ),
            },
            {
              id: "path",
              header: copy.instancePath,
              width: 280,
              minWidth: 140,
              fill: true,
              render: (item) => item.displayPath || "-",
            },
            {
              id: "actions",
              header: labels.actions,
              align: "right",
              width: 142,
              minWidth: 120,
              truncate: false,
              className: styles.actionCell,
              render: (item) => (
                <span className={styles.actionButtons} onClick={(event) => event.stopPropagation()}>
                  <VButton type="button" variant="primary" density="compact" isDisabled={lifecyclePending} onPress={() => onLifecycle?.(item.id, "start")}>
                    {labels.startWorkbench}
                  </VButton>
                </span>
              ),
            },
          ]}
        />
      </section>

      <details className={styles.maintenanceFold}>
        <summary>
          <span>{labels.maintenance}</span>
          <strong>{maintenanceItems.length}</strong>
        </summary>
        <div className={styles.maintenanceBody}>
          <div className={styles.toolbar}>
            <div className={styles.toolbarActions}>
              <VButton
                type="button"
                variant="danger"
                density="compact"
                isDisabled={cleanupSelected.length === 0 || cleanupMutation.isPending}
                onPress={() => askCleanup(cleanupSelected)}
              >
                {labels.cleanupSelected}
                {cleanupSelected.length > 0 ? ` (${cleanupSelected.length})` : ""}
              </VButton>
              {notice ? <span className={noticeTone === "error" ? styles.noticeError : styles.notice}>{notice}</span> : null}
            </div>
            <SectionPager
              ariaLabel={labels.maintenance}
              page={pagedMaintenance.page}
              pageCount={pagedMaintenance.pageCount}
              start={pagedMaintenance.start}
              end={pagedMaintenance.end}
              total={maintenanceItems.length}
              previousLabel={labels.previous}
              nextLabel={labels.next}
              onPrevious={() => setMaintenancePage((current) => current - 1)}
              onNext={() => setMaintenancePage((current) => current + 1)}
            />
          </div>
          <VDenseTable
            ariaLabel={labels.maintenance}
            className={styles.statusTable}
            resizable
            rows={pagedMaintenance.items}
            getRowKey={(item) => item.id}
            onRowClick={(item) => onSelect(item.id)}
            getRowState={(item) => ({ selected: item.id === selectedId, tone: item.dirty ? "warning" : "neutral" })}
            columns={[
              {
                id: "select",
                header: (
                  <VCheckbox
                    aria-label={labels.selectPage}
                    isSelected={allPageSelected}
                    isDisabled={pageEligible.length === 0}
                    onChange={togglePage}
                  />
                ),
                align: "center",
                width: 36,
                minWidth: 36,
                resizable: false,
                truncate: false,
                className: styles.selectCell,
                render: (item) => (
                  <span onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
                    <VCheckbox
                      aria-label={`${labels.cleanup} ${item.shortName || item.branch || item.id}`}
                      isSelected={cleanupSelected.includes(item.id)}
                      onChange={(next) => toggleSelected(item, next)}
                    />
                  </span>
                ),
              },
              {
                id: "branch",
                header: copy.branchColumn,
                width: 240,
                minWidth: 130,
                render: (item) => <span className={styles.branchName}>{item.shortName || item.branch || item.id}</span>,
              },
              {
                id: "state",
                header: copy.instanceState,
                width: 138,
                minWidth: 100,
                render: (item) => {
                  const state = instanceRuntimeState(item, pendingOperation);
                  return (
                    <LauncherBranchStatusHelp item={item} state={state} isZh={zh} kind="runtime">
                      <VStatusChip tone={runtimeTone(state)}>
                        {instanceRuntimeStateLabel(state, zh)}
                      </VStatusChip>
                    </LauncherBranchStatusHelp>
                  );
                },
              },
              {
                id: "git",
                header: labels.git,
                width: 180,
                minWidth: 110,
                render: (item) => {
                  const state = instanceRuntimeState(item, pendingOperation);
                  return (
                    <LauncherBranchStatusHelp item={item} state={state} isZh={zh} kind="git">
                      <span>{formatGitStatus(item, zh)}</span>
                    </LauncherBranchStatusHelp>
                  );
                },
              },
              {
                id: "path",
                header: copy.instancePath,
                width: 320,
                minWidth: 160,
                fill: true,
                render: (item) => item.displayPath || item.path || "-",
              },
              {
                id: "actions",
                header: labels.actions,
                align: "right",
                width: 92,
                minWidth: 76,
                truncate: false,
                className: styles.actionCell,
                render: (item) => (
                  <span className={styles.actionButtons} onClick={(event) => event.stopPropagation()}>
                    <VButton type="button" variant="danger" density="compact" isDisabled={cleanupMutation.isPending} onPress={() => askCleanup([item.id])}>
                      {labels.cleanup}
                    </VButton>
                  </span>
                ),
              },
            ]}
          />
        </div>
      </details>

      <VConfirmDialog
        open={pendingIds !== null}
        onOpenChange={(open) => {
          if (!open && !cleanupMutation.isPending) {
            setPendingIds(null);
          }
        }}
        title={labels.cleanupConfirmTitle}
        description={labels.cleanupConfirmHint}
        tone="danger"
        size="md"
        confirmLabel={labels.cleanup}
        cancelLabel={zh ? "取消" : "Cancel"}
        confirmPending={cleanupMutation.isPending}
        confirmDisabled={pendingItems.length === 0}
        onConfirm={() => {
          if (pendingIds && pendingIds.length > 0) {
            cleanupMutation.mutate(pendingIds);
          }
        }}
      >
        <ul className={styles.confirmList}>
          {pendingItems.map((item) => {
            const risks = cleanupRiskLabels(item, zh);
            return (
              <li key={item.id} className={styles.confirmItem}>
                <p className={styles.confirmName}>{item.shortName || item.branch || item.id}</p>
                <p className={styles.confirmPath}>{item.path || item.displayPath || item.branch || item.id}</p>
                <ul className={styles.confirmRisks}>
                  {(risks.length > 0 ? risks : [labels.noRisk]).map((risk) => (
                    <li key={risk}>{risk}</li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      </VConfirmDialog>

      <VConfirmDialog
        open={batchStopIds !== null}
        onOpenChange={(open) => {
          if (!open && !lifecyclePending) {
            setBatchStopIds(null);
          }
        }}
        title={batchStopKind === "close" ? labels.closeConfirmTitle : labels.stopConfirmTitle}
        description={labels.stopConfirmHint}
        tone="neutral"
        size="md"
        confirmLabel={batchStopKind === "close" ? labels.close : labels.stop}
        cancelLabel={zh ? "取消" : "Cancel"}
        confirmPending={lifecyclePending}
        confirmDisabled={batchStopItems.length === 0}
        onConfirm={() => {
          if (batchStopIds && batchStopIds.length > 0) {
            onStopMany?.(batchStopIds);
            setBatchStopIds(null);
          }
        }}
      >
        <ul className={styles.confirmList}>
          {batchStopItems.map((item) => (
            <li key={item.id} className={styles.confirmItem}>
              <p className={styles.confirmName}>{item.shortName || item.branch || item.id}</p>
              <p className={styles.confirmPath}>{item.path || item.displayPath || item.branch || item.id}</p>
            </li>
          ))}
        </ul>
      </VConfirmDialog>
    </section>
  );
}
