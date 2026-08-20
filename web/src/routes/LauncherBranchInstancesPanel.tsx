import { GitBranch, LoaderCircle } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getLauncherBranchInstances, requestBranchInstanceCleanup, type LauncherBranchInstance } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import { VActionGroup, VButton, VCheckbox, VConfirmDialog, VDenseTable, VEmptyState, VNativeInput, VStateSurface, VStatusChip, VTabs, VToolbar, VTooltip, type VDenseTableColumn } from "../components/vui";
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
  instanceRuntimeState,
  instanceRuntimeStateLabel,
  instanceStopLabel,
  instanceWindowOpen,
  isCleanupEligible,
  overlayCleanupMetadata,
  paginateItems,
  lifecycleIntentRejectMessage,
  shouldHoldOpenClickGuard,
  type InstanceListFilters,
  type LifecyclePendingInput,
  type LifecycleRequestOutcome,
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
  pendingOperation?: LifecyclePendingInput;
  launcherTitle?: string;
  launcherOnline?: boolean;
  launcherReading?: boolean;
  listLoading?: boolean;
  lifecyclePending?: boolean;
  onLifecycle?: (
    instanceId: string,
    operation: Extract<LauncherOperation, "start" | "stop">,
  ) => LifecycleRequestOutcome | void;
  onStopMany?: (instanceIds: string[]) => void;
};

type BranchTableTab = "all" | "running" | "attention" | "startable";

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

function TabLabel({ text, count }: { text: string; count: number }) {
  return (
    <span className={styles.tabLabel}>
      <span>{text}</span>
      <strong className={styles.tabCount}>{count}</strong>
    </span>
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
  launcherReading = false,
  listLoading = false,
  lifecyclePending = false,
  onLifecycle,
  onStopMany,
}: LauncherBranchInstancesPanelProps) {
  const queryClient = useQueryClient();
  const zh = isZhCopy(copy);
  const labels = zh
    ? {
        all: "全部",
        allHint: "已打开分支实例的完整列表",
        running: "正在运行",
        runningHint: "后端或窗口仍活着的实例",
        attention: "需要处理",
        attentionHint: "启动失败或卡住，关闭后回到可启动，不会删除 worktree",
        startable: "可启动",
        startableHint: "已具备 worktree，当前没有运行信号",
        maintenance: "维护与清理",
        controlWindow: "Launcher 控制窗口",
        online: "在线",
        reading: "读取中",
        offline: "未连接",
        emptyAll: "当前没有可显示的分支",
        emptyRunning: "当前没有运行中的分支",
        emptyAttention: "当前没有需要处理的实例",
        emptyStartable: "当前没有可启动的分支",
        globalEmptyTitle: "还没有分支实例",
        globalEmptyHint: "检出分支的 worktree 后，实例会出现在这里；分支区的操作只影响本地工作区。",
        listLoadingTitle: "正在读取分支实例",
        filteredEmptyTitle: "没有匹配的分支",
        filteredEmptyHint: "试试清除搜索，或关闭未提交 / 未合入筛选。",
        clearSearch: "清除搜索与筛选",
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
        all: "All",
        allHint: "Full list of checked-out branch instances",
        running: "Running",
        runningHint: "Instances whose backend or window is still alive",
        attention: "Needs attention",
        attentionHint: "Failed or stuck instances. Close returns them to Ready to start without deleting the worktree",
        startable: "Ready to start",
        startableHint: "Checked-out worktrees with no active runtime signal",
        maintenance: "Maintenance and cleanup",
        controlWindow: "Launcher control window",
        online: "Online",
        reading: "Reading",
        offline: "Disconnected",
        emptyAll: "No branches to show",
        emptyRunning: "No branch is currently running",
        emptyAttention: "No instance needs attention",
        emptyStartable: "No branch is currently ready to start",
        globalEmptyTitle: "No branch instances yet",
        globalEmptyHint: "Checked-out branch worktrees appear here. Branch actions only affect the local workspace.",
        listLoadingTitle: "Reading branch instances",
        filteredEmptyTitle: "No matching branches",
        filteredEmptyHint: "Try clearing the search or turning off the Uncommitted / Not merged filters.",
        clearSearch: "Clear search and filters",
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

  const [activeTab, setActiveTab] = useState<BranchTableTab>("all");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<InstanceListFilters>({});
  const [allPage, setAllPage] = useState(1);
  const [startablePage, setStartablePage] = useState(1);
  const [maintenancePage, setMaintenancePage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [pendingIds, setPendingIds] = useState<string[] | null>(null);
  const [batchStopIds, setBatchStopIds] = useState<string[] | null>(null);
  const [batchStopKind, setBatchStopKind] = useState<"stop" | "close">("stop");
  const [notice, setNotice] = useState("");
  const [noticeTone, setNoticeTone] = useState<"neutral" | "error">("neutral");
  const [openReject, setOpenReject] = useState<{ id: string; reason: "duplicate" | "blocked" } | null>(null);
  const openClickGuardsRef = useRef(new Set<string>());
  const needsCleanupMetadata = Boolean(filters.unmerged || (pendingIds && pendingIds.length > 0));
  const cleanupMetadataQuery = useQuery({
    queryKey: queryKeys.launcherBranchInstances(true),
    queryFn: () => getLauncherBranchInstances({ cleanupMetadata: true }),
    enabled: needsCleanupMetadata,
    staleTime: 30_000,
  });
  const waitingUnmergedMetadata = Boolean(filters.unmerged) && cleanupMetadataQuery.isPending;
  const waitingCleanupConfirmMetadata = Boolean(pendingIds?.length) && !cleanupMetadataQuery.isSuccess;
  const annotatedItems = useMemo(
    () => overlayCleanupMetadata(items, cleanupMetadataQuery.data?.items),
    [cleanupMetadataQuery.data?.items, items],
  );

  const visibleItems = useMemo(
    () => filterBranchInstances(annotatedItems, query, filters, pendingOperation),
    [annotatedItems, filters, pendingOperation, query],
  );
  const grouped = useMemo(() => groupBranchInstances(visibleItems, pendingOperation), [pendingOperation, visibleItems]);
  const allItems = useMemo(
    () => [...grouped.running, ...grouped.attention, ...grouped.startable],
    [grouped],
  );
  const maintenanceItems = useMemo(() => visibleItems.filter(isCleanupEligible), [visibleItems]);
  const pagedAll = useMemo(
    () => paginateItems(allItems, allPage, BRANCH_INSTANCE_PAGE_SIZE),
    [allItems, allPage],
  );
  const pagedStartable = useMemo(
    () => paginateItems(grouped.startable, startablePage, BRANCH_INSTANCE_PAGE_SIZE),
    [grouped.startable, startablePage],
  );
  const pagedMaintenance = useMemo(
    () => paginateItems(maintenanceItems, maintenancePage, BRANCH_INSTANCE_PAGE_SIZE),
    [maintenanceItems, maintenancePage],
  );

  useEffect(() => {
    if (pagedAll.page !== allPage) {
      setAllPage(pagedAll.page);
    }
  }, [allPage, pagedAll.page]);
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
    const guards = openClickGuardsRef.current;
    for (const id of [...guards]) {
      const item = annotatedItems.find((candidate) => candidate.id === id);
      if (!item || !shouldHoldOpenClickGuard(instanceRuntimeState(item, pendingOperation))) {
        guards.delete(id);
      }
    }
  }, [annotatedItems, pendingOperation]);
  useEffect(() => {
    if (!openReject) {
      return;
    }
    const item = annotatedItems.find((candidate) => candidate.id === openReject.id);
    if (item && instanceRuntimeState(item, pendingOperation) === "starting") {
      setOpenReject(null);
    }
  }, [annotatedItems, openReject, pendingOperation]);
  useEffect(() => {
    const allIndex = allItems.findIndex((item) => item.id === selectedId);
    if (allIndex >= 0) {
      setAllPage(Math.floor(allIndex / BRANCH_INSTANCE_PAGE_SIZE) + 1);
    }
    const startableIndex = grouped.startable.findIndex((item) => item.id === selectedId);
    if (startableIndex >= 0) {
      setStartablePage(Math.floor(startableIndex / BRANCH_INSTANCE_PAGE_SIZE) + 1);
    }
    const maintenanceIndex = maintenanceItems.findIndex((item) => item.id === selectedId);
    if (maintenanceIndex >= 0) {
      setMaintenancePage(Math.floor(maintenanceIndex / BRANCH_INSTANCE_PAGE_SIZE) + 1);
    }
  }, [allItems, grouped.startable, maintenanceItems, selectedId]);

  const kindById = useMemo(() => {
    const map = new Map<string, "running" | "attention" | "startable">();
    for (const item of grouped.running) {
      map.set(item.id, "running");
    }
    for (const item of grouped.attention) {
      map.set(item.id, "attention");
    }
    for (const item of grouped.startable) {
      map.set(item.id, "startable");
    }
    return map;
  }, [grouped]);

  const knownIds = useMemo(() => new Set(items.map((item) => item.id)), [items]);
  const cleanupSelected = selectedIds.filter((id) => knownIds.has(id) && maintenanceItems.some((item) => item.id === id));
  const pageEligible = pagedMaintenance.items;
  const pageSelectedCount = pageEligible.filter((item) => cleanupSelected.includes(item.id)).length;
  const allPageSelected = pageEligible.length > 0 && pageSelectedCount === pageEligible.length;
  const pendingItems = pendingIds ? annotatedItems.filter((item) => pendingIds.includes(item.id)) : [];
  const batchStopItems = batchStopIds ? annotatedItems.filter((item) => batchStopIds.includes(item.id)) : [];

  const cleanupMutation = useMutation({
    mutationFn: (instanceIds: string[]) => requestBranchInstanceCleanup(instanceIds, true),
    onSuccess: (payload) => {
      const failed = [...payload.failed, ...payload.skipped];
      setNotice(failed.length > 0 ? `${labels.failed}：${failed.map((item) => item.shortName || item.id).join("、")}` : labels.done);
      setNoticeTone(failed.length > 0 ? "error" : "neutral");
      setSelectedIds((current) => current.filter((id) => !payload.cleaned.some((item) => item.id === id)));
      void queryClient.invalidateQueries({ queryKey: ["launcher", "branch-instances"] });
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

  const clearSearch = () => {
    setQuery("");
    setFilters({});
  };

  const renderLifecycleActions = (item: LauncherBranchInstance) => {
    const state = instanceRuntimeState(item, pendingOperation);
    const windowOpen = instanceWindowOpen(item);
    const startBusy = shouldHoldOpenClickGuard(state);
    const stopBusy = state === "stopping";
    const startingOrRestarting = state === "starting" || state === "restarting";
    const openLabel = state === "failed" ? labels.retryStart : windowOpen ? labels.focusWindow : labels.openWindow;
    const showOpen = canRequestOpenInstance(item, pendingOperation);
    const showStop = canStopInstance(item, pendingOperation) || stopBusy;
    const requestOpen = () => {
      if (startBusy || openClickGuardsRef.current.has(item.id)) {
        return;
      }
      openClickGuardsRef.current.add(item.id);
      try {
        const outcome = onLifecycle?.(item.id, "start");
        if (outcome && outcome.accepted === false) {
          openClickGuardsRef.current.delete(item.id);
          setOpenReject({ id: item.id, reason: outcome.reason });
          return;
        }
        setOpenReject((current) => (current?.id === item.id ? null : current));
      } catch (error) {
        openClickGuardsRef.current.delete(item.id);
        throw error;
      }
    };
    return (
      <VActionGroup
        ariaLabel={labels.actions}
        aria-busy={startingOrRestarting || stopBusy || undefined}
        className={styles.actionButtons}
        onClick={(event) => event.stopPropagation()}
      >
        {showOpen ? (
          <VButton
            type="button"
            variant="primary"
            density="compact"
            isDisabled={startBusy}
            onPress={requestOpen}
          >
            {openLabel}
          </VButton>
        ) : null}
        {showOpen && openReject?.id === item.id ? (
          <span className={styles.errorReason}>{lifecycleIntentRejectMessage(openReject.reason, zh)}</span>
        ) : null}
        {showStop ? (
          <VButton
            type="button"
            variant={startingOrRestarting ? "primary" : "secondary"}
            density="compact"
            isDisabled={stopBusy}
            isPending={stopBusy}
            icon={startingOrRestarting ? (
              <LoaderCircle
                size={14}
                strokeWidth={2.25}
                className="animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
            ) : undefined}
            tooltip={startingOrRestarting
              ? (state === "restarting"
                ? (zh ? "正在重启，点击可停止" : "Restarting — click to stop")
                : (zh ? "正在启动，点击可停止" : "Starting — click to stop"))
              : undefined}
            onPress={() => {
              if (stopBusy) {
                return;
              }
              onLifecycle?.(item.id, "stop");
            }}
          >
            {stopBusy ? instanceRuntimeStateLabel(state, zh) : instanceStopLabel(item, zh, pendingOperation)}
          </VButton>
        ) : null}
      </VActionGroup>
    );
  };

  const hasAnyItems = items.length > 0;
  const showListLoading = (listLoading && !hasAnyItems) || waitingUnmergedMetadata;
  const filteredEmpty = hasAnyItems && visibleItems.length === 0 && !waitingUnmergedMetadata;
  const activePager = activeTab === "all" ? pagedAll : activeTab === "startable" ? pagedStartable : null;
  const activeTotal = activeTab === "all"
    ? allItems.length
    : activeTab === "running"
      ? grouped.running.length
      : activeTab === "attention"
        ? grouped.attention.length
        : grouped.startable.length;
  const activeRows = activeTab === "all"
    ? pagedAll.items
    : activeTab === "running"
      ? grouped.running
      : activeTab === "attention"
        ? grouped.attention
        : pagedStartable.items;
  const activeHint = activeTab === "all"
    ? labels.allHint
    : activeTab === "running"
      ? labels.runningHint
      : activeTab === "attention"
        ? labels.attentionHint
        : labels.startableHint;
  const tabEmptyText = activeTab === "all"
    ? labels.emptyAll
    : activeTab === "running"
      ? labels.emptyRunning
      : activeTab === "attention"
        ? labels.emptyAttention
        : labels.emptyStartable;

  const tabItems: Array<{ id: BranchTableTab; label: ReactNode; title: string }> = [
    { id: "all", label: <TabLabel text={labels.all} count={allItems.length} />, title: labels.allHint },
    { id: "running", label: <TabLabel text={labels.running} count={grouped.running.length} />, title: labels.runningHint },
    { id: "attention", label: <TabLabel text={labels.attention} count={grouped.attention.length} />, title: labels.attentionHint },
    { id: "startable", label: <TabLabel text={labels.startable} count={grouped.startable.length} />, title: labels.startableHint },
  ];

  const primaryColumns: VDenseTableColumn<LauncherBranchInstance>[] = [
    {
      id: "branch",
      header: copy.branchColumn,
      width: 180,
      minWidth: 110,
      fill: true,
      render: (item: LauncherBranchInstance) => (
        <VTooltip content={`${item.shortName || item.branch || item.id} · ${item.branch || item.id} · ${item.path || item.displayPath || item.id}`} width="wide">
          <span className={styles.branchName}>{item.shortName || item.branch || item.id}</span>
        </VTooltip>
      ),
    },
    {
      id: "state",
      header: copy.instanceState,
      width: 108,
      minWidth: 92,
      render: (item: LauncherBranchInstance) => {
        const state = instanceRuntimeState(item, pendingOperation);
        const kind = kindById.get(item.id);
        if (kind === "startable" && state === "stopped") {
          return (
            <LauncherBranchStatusHelp item={item} state="stopped" isZh={zh} kind="runtime">
              <VStatusChip tone="success">{labels.ready}</VStatusChip>
            </LauncherBranchStatusHelp>
          );
        }
        if (kind === "attention") {
          return (
            <LauncherBranchStatusHelp item={item} state={state} isZh={zh} kind="runtime">
              <span>
                <VStatusChip tone={runtimeTone(state)}>
                  {instanceRuntimeStateLabel(state, zh)}
                </VStatusChip>
                <span className={styles.errorReason}>{formatAttentionReason(item, zh)}</span>
              </span>
            </LauncherBranchStatusHelp>
          );
        }
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
      width: 118,
      minWidth: 100,
      render: (item: LauncherBranchInstance) => formatBackendStatus(item, zh),
    },
    {
      id: "frontend",
      header: labels.frontend,
      width: 118,
      minWidth: 100,
      render: (item: LauncherBranchInstance) => formatFrontendStatus(item, zh),
    },
    {
      id: "workbench",
      header: labels.workbench,
      width: 200,
      minWidth: 140,
      render: (item: LauncherBranchInstance) => formatWorkbenchStatus(item, zh),
    },
    {
      id: "git",
      header: labels.git,
      width: 116,
      minWidth: 92,
      render: (item: LauncherBranchInstance) => {
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
      width: 170,
      minWidth: 150,
      truncate: false,
      className: styles.actionCell,
      render: renderLifecycleActions,
    },
  ];

  return (
    <section className={styles.panel} data-vui-region="launcher-branch-instances" aria-label={copy.branchInstances}>
      <div className={styles.panelHeader}>
        <p className={styles.panelEyebrow}>{copy.branchInstances}</p>
        <p className={styles.controlWindow} role="status">
          <span>{labels.controlWindow}</span>
          <strong>{launcherTitle || "-"}</strong>
          <VStatusChip tone={launcherOnline ? "success" : launcherReading ? "neutral" : "warning"}>
            {launcherOnline ? labels.online : launcherReading ? labels.reading : labels.offline}
          </VStatusChip>
        </p>
      </div>

      {showListLoading ? (
        <VStateSurface
          className={styles.globalEmpty}
          tone="loading"
          title={labels.listLoadingTitle}
          skeletonLines={3}
        />
      ) : !hasAnyItems ? (
        <VEmptyState
          align="start"
          className={styles.globalEmpty}
          title={labels.globalEmptyTitle}
          icon={<GitBranch size={18} aria-hidden="true" />}
        >
          {labels.globalEmptyHint}
        </VEmptyState>
      ) : (
        <div className={styles.panelBody}>
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

          <VTabs
            density="compact"
            className={styles.tabBar}
            aria-label={copy.branchInstances}
            value={activeTab}
            onValueChange={(value) => setActiveTab(value as BranchTableTab)}
            items={tabItems}
          />

          {filteredEmpty ? (
            <VEmptyState
              align="start"
              className={styles.globalEmpty}
              title={labels.filteredEmptyTitle}
              actions={
                <VButton type="button" density="compact" variant="secondary" onPress={clearSearch}>
                  {labels.clearSearch}
                </VButton>
              }
            >
              {labels.filteredEmptyHint}
            </VEmptyState>
          ) : (
            <div className={styles.tabBody}>
              <div className={styles.tabHeader}>
                <p className={styles.tabHint}>{activeHint}</p>
                <div className={styles.tabHeaderActions}>
                  {activeTab === "running" ? (
                    <VButton
                      type="button"
                      density="compact"
                      variant="secondary"
                      isDisabled={grouped.running.every((item) => !canStopInstance(item, pendingOperation))}
                      onPress={() => askBatchStop(grouped.running.map((item) => item.id), "stop")}
                    >
                      {labels.stopAll}
                    </VButton>
                  ) : null}
                  {activeTab === "attention" ? (
                    <VButton
                      type="button"
                      density="compact"
                      variant="secondary"
                      isDisabled={grouped.attention.every((item) => !canStopInstance(item, pendingOperation))}
                      onPress={() => askBatchStop(grouped.attention.map((item) => item.id), "close")}
                    >
                      {labels.closeAll}
                    </VButton>
                  ) : null}
                  {activePager ? (
                    <SectionPager
                      ariaLabel={activeHint}
                      page={activePager.page}
                      pageCount={activePager.pageCount}
                      start={activePager.start}
                      end={activePager.end}
                      total={activeTotal}
                      previousLabel={labels.previous}
                      nextLabel={labels.next}
                      onPrevious={() => (activeTab === "all" ? setAllPage((current) => current - 1) : setStartablePage((current) => current - 1))}
                      onNext={() => (activeTab === "all" ? setAllPage((current) => current + 1) : setStartablePage((current) => current + 1))}
                    />
                  ) : null}
                </div>
              </div>

              <VDenseTable
                ariaLabel={activeHint}
                className={styles.statusTable}
                resizable
                rows={activeRows}
                emptyText={tabEmptyText}
                getRowKey={(item) => item.id}
                onRowClick={(item) => onSelect(item.id)}
                getRowState={(item) => ({
                  selected: item.id === selectedId,
                  tone: runtimeTone(instanceRuntimeState(item, pendingOperation)),
                })}
                columns={primaryColumns}
              />
            </div>
          )}

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
                    render: (item: LauncherBranchInstance) => (
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
                    render: (item: LauncherBranchInstance) => <span className={styles.branchName}>{item.shortName || item.branch || item.id}</span>,
                  },
                  {
                    id: "state",
                    header: copy.instanceState,
                    width: 138,
                    minWidth: 100,
                    render: (item: LauncherBranchInstance) => {
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
                    render: (item: LauncherBranchInstance) => {
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
                    render: (item: LauncherBranchInstance) => item.displayPath || item.path || "-",
                  },
                  {
                    id: "actions",
                    header: labels.actions,
                    align: "right",
                    width: 92,
                    minWidth: 76,
                    truncate: false,
                    className: styles.actionCell,
                    render: (item: LauncherBranchInstance) => (
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
        </div>
      )}

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
        confirmPending={cleanupMutation.isPending || waitingCleanupConfirmMetadata}
        confirmDisabled={pendingItems.length === 0 || waitingCleanupConfirmMetadata}
        onConfirm={() => {
          if (pendingIds && pendingIds.length > 0) {
            cleanupMutation.mutate(pendingIds);
          }
        }}
      >
        <ul className={styles.confirmList}>
          {waitingCleanupConfirmMetadata ? (
            <li className={styles.confirmItem}>
              <p className={styles.confirmName}>{labels.listLoadingTitle}</p>
            </li>
          ) : (
            pendingItems.map((item) => {
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
          })
          )}
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
