import { GitBranch, Ellipsis, Search } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getLauncherBranchInstances, requestBranchInstanceCleanup, type LauncherBranchInstance } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import { VActionGroup, VButton, VCheckbox, VConfirmDialog, VDenseTable, VEmptyState, VNativeInput, VStateSurface, VStringSelect, VDropdownMenu, VTooltip, type VDenseTableColumn } from "../components/vui";
import type { LauncherOperation } from "../api/types";
import { LauncherBranchStatusHelp } from "./LauncherBranchStatusHelp";
import {
  canRequestOpenInstance,
  canForceStopInstance,
  canStopInstance,
  cleanupRiskLabels,
  filterBranchInstances,
  formatAdmissionReason,
  formatGitStatus,
  groupBranchInstances,
  instanceRuntimeState,
  instanceRuntimeStateLabel,
  instanceStopLabel,
  instanceWindowOpen,
  isAdmissionBlocked,
  isCleanupEligible,
  overlayCleanupMetadata,
  lifecycleIntentRejectMessage,
  summarizeLifecycleFeedback,
  shouldHoldOpenClickGuard,
  type InstanceListFilters,
  type LifecyclePendingInput,
  type LifecycleRequestOutcome,
} from "./LauncherBranchInstancesPanel.model";
import styles from "./LauncherBranchInstancesPanel.styles";
import { LauncherBranchDetailPanel, launcherBranchDisplayName } from "./LauncherBranchDetailPanel";

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
  headerAction?: ReactNode;
  items: LauncherBranchInstance[];
  selectedId: string;
  onSelect: (id: string) => void;
  pendingOperation?: LifecyclePendingInput;
  launcherTitle?: string;
  launcherOnline?: boolean;
  launcherReading?: boolean;
  listLoading?: boolean;
  listError?: string;
  lifecyclePending?: boolean;
  onLifecycle?: (
    instanceId: string,
    operation: Extract<LauncherOperation, "start" | "stop" | "force-stop">,
  ) => LifecycleRequestOutcome | void;
  onStopMany?: (instanceIds: string[]) => void;
  rowFeedback?: {
    instanceId: string;
    tone: "error" | "info";
    message: string;
  } | null;
};

type BranchTableTab = "all" | "running" | "attention" | "startable" | "retired";

function isZhCopy(copy: LauncherBranchInstancesCopy): boolean {
  return !/^Branch/.test(copy.branchInstances);
}

export function LauncherBranchInstancesPanel({
  copy,
  headerAction,
  items,
  onSelect,
  pendingOperation,
  launcherTitle,
  launcherOnline = false,
  launcherReading = false,
  listLoading = false,
  listError,
  lifecyclePending = false,
  onLifecycle,
  onStopMany,
  rowFeedback = null,
}: LauncherBranchInstancesPanelProps) {
  const queryClient = useQueryClient();
  const zh = isZhCopy(copy);
  const labels = zh
    ? {
        all: "全部",
        allHint: "已打开的分支实例",
        running: "正在运行",
        runningHint: "后端或窗口仍活着的实例",
        attention: "需要处理",
        attentionHint: "启动失败或卡住，关闭后回到可启动，不会删除 worktree",
        startable: "可启动",
        startableHint: "已具备 worktree，当前没有运行信号",
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
        selectPage: "选择当前列表可清理项",
        actions: "操作",
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
        forceStop: "强制停止",
        forceStopHint: "普通停止无法收口时使用",
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
        building: "构建中…",
        buildingHint: "前端代码有更新，正在构建新版本，约需几分钟。",
      }
    : {
        all: "All",
        allHint: "Checked-out branch instances",
        running: "Running",
        runningHint: "Instances whose backend or window is still alive",
        attention: "Needs attention",
        attentionHint: "Failed or stuck instances. Close returns them to Ready to start without deleting the worktree",
        startable: "Ready to start",
        startableHint: "Checked-out worktrees with no active runtime signal",
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
        selectPage: "Select cleanable items in this list",
        actions: "Actions",
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
        forceStop: "Force stop",
        forceStopHint: "Use when normal Stop cannot settle",
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
        building: "Building…",
        buildingHint: "The frontend has updates and a new build is running. This takes a few minutes.",
      };

  const [activeTab, setActiveTab] = useState<BranchTableTab>("all");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<InstanceListFilters>({});
  const [detailId, setDetailId] = useState<string | null>(null);
  const [forceStopId, setForceStopId] = useState<string | null>(null);
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
    () => [...grouped.running, ...grouped.attention, ...grouped.startable, ...grouped.maintenance]
      .filter((item) => item.kind !== "retired")
      .sort((a, b) => Number(b.current || b.kind === "main") - Number(a.current || a.kind === "main")),
    [grouped],
  );
  const eligibleItems = useMemo(() => visibleItems.filter(isCleanupEligible), [visibleItems]);
  const activeRows = activeTab === "all" ? allItems : activeTab === "running" ? grouped.running : activeTab === "attention" ? grouped.attention : activeTab === "retired" ? visibleItems.filter((item) => item.kind === "retired") : grouped.startable;
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
  const knownIds = useMemo(() => new Set(items.map((item) => item.id)), [items]);
  const cleanupSelected = selectedIds.filter((id) => knownIds.has(id) && eligibleItems.some((item) => item.id === id));
  const pageEligible = activeRows.filter(isCleanupEligible);
  const pageSelectedCount = pageEligible.filter((item) => cleanupSelected.includes(item.id)).length;
  const allPageSelected = pageEligible.length > 0 && pageSelectedCount === pageEligible.length;
  const pendingItems = pendingIds ? annotatedItems.filter((item) => pendingIds.includes(item.id)) : [];
  const batchStopItems = batchStopIds ? annotatedItems.filter((item) => batchStopIds.includes(item.id)) : [];
  const batchStopPending = batchStopItems.some((item) => instanceRuntimeState(item, pendingOperation) === "stopping");

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
    setActiveTab("all");
  };

  const renderLifecycleActions = (item: LauncherBranchInstance) => {
    const state = instanceRuntimeState(item, pendingOperation);
    const windowOpen = instanceWindowOpen(item);
    const startBusy = shouldHoldOpenClickGuard(state);
    const stopBusy = state === "stopping";
    const building = state === "building";
    const startingOrRestarting = state === "starting" || state === "restarting";
    const openLabel = state === "failed" ? labels.retryStart : windowOpen ? labels.focusWindow : labels.openWindow;
    const admissionBlocked = isAdmissionBlocked(item);
    // While a frontend build gates the start, the primary control stays
    // visible but disabled with a pending spinner so the wait reads as
    // progress instead of a frozen button.
    const showOpen = canRequestOpenInstance(item, pendingOperation) || startBusy || stopBusy;
    const showStop = canStopInstance(item, pendingOperation) || stopBusy;
    const showForceStop = canForceStopInstance(item);
    const requestOpen = () => {
      if (startBusy || admissionBlocked || openClickGuardsRef.current.has(item.id)) {
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
    const feedback = rowFeedback?.instanceId === item.id ? rowFeedback : null;
    return (
      <div className={styles.actionStack}>
      <VActionGroup
        ariaLabel={labels.actions}
        aria-busy={building || startingOrRestarting || stopBusy || undefined}
        className={styles.actionButtons}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.stopPropagation()}
      >
        {showOpen ? (
          <VButton
            type="button"
            variant="secondary"
            density="compact"
            isDisabled={startBusy || stopBusy || admissionBlocked}
            isPending={startBusy || stopBusy}
            title={building ? labels.buildingHint : undefined}
            onPress={requestOpen}
          >
            {startBusy || stopBusy ? instanceRuntimeStateLabel(state, zh) : openLabel}
          </VButton>
        ) : null}
        {showOpen && !building && admissionBlocked ? (
          <span className={styles.errorReason}>{formatAdmissionReason(item, zh)}</span>
        ) : null}
        {showOpen && !building && openReject?.id === item.id ? (
          <span className={styles.errorReason}>{lifecycleIntentRejectMessage(openReject.reason, zh)}</span>
        ) : null}
        {/* Lifecycle controls stay on the row: stop must be reachable without opening the overflow menu. */}
        {showStop ? (
          <VButton
            type="button"
            variant="secondary"
            density="compact"
            isDisabled={stopBusy}
            isPending={stopBusy}
            onPress={() => askBatchStop([item.id], "stop")}
          >
            {instanceStopLabel(item, zh, pendingOperation)}
          </VButton>
        ) : null}
        {showForceStop ? (
          <VButton
            type="button"
            variant="danger"
            density="compact"
            title={labels.forceStopHint}
            isDisabled={lifecyclePending}
            onPress={() => setForceStopId(item.id)}
          >
            {labels.forceStop}
          </VButton>
        ) : null}
        <VDropdownMenu aria-label={zh ? "更多操作" : "More actions"} align="end"
          trigger={<VButton isIconOnly variant="ghost" aria-label={`${launcherBranchDisplayName(item)} ${zh ? "更多操作" : "More actions"}`} icon={<Ellipsis size={16} />} />}
          items={[
            { id: "details", label: zh ? "查看详情" : "View details", onSelect: () => { onSelect(item.id); setDetailId(item.id); } },
            ...(isCleanupEligible(item) ? [{ id: "cleanup", label: labels.cleanup, danger: true, disabled: cleanupMutation.isPending || building || startingOrRestarting || stopBusy, onSelect: () => askCleanup([item.id]) }] : []),
          ]} />
      </VActionGroup>
      {feedback ? (
        <span
          className={feedback.tone === "error" ? styles.rowFeedbackError : styles.rowFeedback}
          title={feedback.message}
        >
          {summarizeLifecycleFeedback(feedback.message)}
        </span>
      ) : null}
      </div>
    );
  };

  const hasAnyItems = items.length > 0;
  const showListLoading = (listLoading && !hasAnyItems) || waitingUnmergedMetadata;
  const filteredEmpty = hasAnyItems && visibleItems.length === 0 && !waitingUnmergedMetadata;
  const activeHint = zh ? "工作区分支列表" : "Workspace branches";
  const tabEmptyText = labels.filteredEmptyTitle;
  const detailItem = annotatedItems.find((item) => item.id === detailId);
  const forceStopItem = items.find((item) => item.id === forceStopId);
  const primaryColumns: VDenseTableColumn<LauncherBranchInstance>[] = [
    {
      id: "branch",
      header: copy.branchColumn,
      width: 180,
      minWidth: 110,
      fill: true,
      render: (item: LauncherBranchInstance) => (
        <VTooltip content={`${item.shortName || item.branch || item.id} · ${item.branch || item.id} · ${item.path || item.displayPath || item.id}`} width="wide">
          <span className={styles.branchName}>{launcherBranchDisplayName(item)}{item.current ? <small className={styles.currentMarker}>{zh ? "当前" : "Current"}</small> : null}</span>
        </VTooltip>
      ),
    },
    {
      id: "state",
      header: copy.instanceState,
      width: 176,
      minWidth: 150,
      render: (item: LauncherBranchInstance) => {
        const state = instanceRuntimeState(item, pendingOperation);
        return <div className={styles.runtimeStack}>
          <LauncherBranchStatusHelp item={item} state={state} isZh={zh} kind="runtime">
            <span className={state === "running" ? styles.runtimeRunning : state === "failed" ? styles.runtimeFailed : styles.runtimeOther}>{instanceRuntimeStateLabel(state, zh)}</span>
          </LauncherBranchStatusHelp>
          {state === "running" && !instanceWindowOpen(item) ? (
            // The window hint only adds information when it contradicts a live
            // backend; every other case is already conveyed by the row actions.
            <span className={styles.windowState}>{zh ? "窗口未打开" : "Window closed"}</span>
          ) : null}
        </div>;
      },
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
      header: "",
      align: "right",
      width: 320,
      minWidth: 250,
      truncate: false,
      className: styles.actionCell,
      render: renderLifecycleActions,
    },
  ];

  const selectColumn: VDenseTableColumn<LauncherBranchInstance> = {
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
    render: (item: LauncherBranchInstance) =>
      isCleanupEligible(item) ? (
        <span onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
          <VCheckbox
            aria-label={`${labels.cleanup} ${item.shortName || item.branch || item.id}`}
            isSelected={cleanupSelected.includes(item.id)}
            onChange={(next) => toggleSelected(item, next)}
          />
        </span>
      ) : null,
  };

  return (
    <section className={styles.panel} data-vui-region="launcher-branch-instances" aria-label={copy.branchInstances}>
      {detailItem ? <LauncherBranchDetailPanel item={detailItem} zh={zh} pending={pendingOperation} actions={renderLifecycleActions(detailItem)} onBack={() => setDetailId(null)} /> : <>
      <header className={styles.panelHeader}>
        <div><h1 className={styles.heading}>{zh ? "分支" : "Branches"}</h1><p className={styles.description}>{zh ? "管理工作区，打开窗口，继续工作。" : "Manage workspaces and continue your work."}</p></div>
        <div className={styles.panelHeaderActions}>{launcherReading || !launcherOnline ? <span role="status" className={styles.connectionStatus}>{launcherReading ? labels.reading : labels.offline}</span> : null}{headerAction}</div>
      </header>
      <div className={styles.filterRow}>
        <div className={styles.searchField}><Search size={15} aria-hidden="true" className={styles.searchIcon} /><VNativeInput aria-label={labels.search} className={styles.searchInput} placeholder={labels.searchPlaceholder} value={query} onChange={(event) => setQuery(event.target.value)} /></div>
        <VStringSelect ariaLabel={zh ? "分支筛选" : "Branch filter"} value={activeTab} className={styles.filterSelect} onValueChange={(value) => setActiveTab(value as BranchTableTab)}
          options={[{value:"all",label:zh ? "可用工作区" : "Available"},{value:"running",label:labels.running},{value:"attention",label:labels.attention},{value:"startable",label:labels.startable},{value:"retired",label:zh ? "已退役" : "Retired"}]} />
        <VDropdownMenu aria-label={zh ? "更多筛选" : "More filters"} align="end" trigger={<VButton variant="ghost">{zh ? "筛选" : "Filters"}{filters.dirty || filters.unmerged ? " •" : ""}</VButton>} items={[
          { id: "dirty", label: `${filters.dirty ? "✓ " : ""}${labels.filterDirty}`, onSelect: () => setFilters((current) => ({...current, dirty: !current.dirty})) },
          { id: "unmerged", label: `${filters.unmerged ? "✓ " : ""}${labels.filterUnmerged}`, onSelect: () => setFilters((current) => ({...current, unmerged: !current.unmerged})) },
          { id: "clear", label: labels.clearSearch, onSelect: clearSearch },
        ]} />
        {cleanupSelected.length > 0 ? <VButton variant="danger" isDisabled={cleanupMutation.isPending} onPress={() => askCleanup(cleanupSelected)}>{labels.cleanupSelected} ({cleanupSelected.length})</VButton> : null}
        {activeTab === "running" || activeTab === "attention" ? <VButton variant="secondary" isDisabled={activeRows.every((item) => !canStopInstance(item, pendingOperation))} onPress={() => askBatchStop(activeRows.map((item) => item.id), activeTab === "running" ? "stop" : "close")}>{activeTab === "running" ? labels.stopAll : labels.closeAll}</VButton> : null}
      </div>
      {notice ? <p role="status" className={noticeTone === "error" ? styles.noticeError : styles.notice}>{notice}</p> : null}
      {listError && hasAnyItems ? <VStateSurface tone="error" className={styles.listError} title={listError} /> : null}
      {listError && !hasAnyItems ? <VStateSurface tone="error" className={styles.globalEmpty} title={listError} /> : showListLoading ? <VStateSurface className={styles.globalEmpty} tone="loading" title={labels.listLoadingTitle} skeletonLines={3} /> : !hasAnyItems ? <VEmptyState className={styles.globalEmpty} title={labels.globalEmptyTitle} icon={<GitBranch size={18} />}>{labels.globalEmptyHint}</VEmptyState> : filteredEmpty || activeRows.length === 0 ? <VEmptyState className={styles.globalEmpty} title={labels.filteredEmptyTitle} actions={<VButton variant="secondary" onPress={clearSearch}>{labels.clearSearch}</VButton>}>{labels.filteredEmptyHint}</VEmptyState> : (
        <div className={styles.tabBody}>
          <div className={styles.desktopList}><VDenseTable ariaLabel={activeHint} className={styles.statusTable} resizable rows={activeRows} emptyText={tabEmptyText} getRowKey={(item) => item.id}
            onRowClick={(item) => { onSelect(item.id); setDetailId(item.id); }}
            getRowState={(item) => ({selected: cleanupSelected.includes(item.id)})}
            columns={[selectColumn, ...primaryColumns]} /></div>
          <div className={styles.mobileList} role="list" aria-label={activeHint}>{activeRows.map((item) => <div key={item.id} role="listitem" className={styles.mobileRow}>
            <VButton variant="ghost" className={styles.mobileBranchButton} onPress={() => { onSelect(item.id); setDetailId(item.id); }}><span className={styles.mobileBranchName}>{launcherBranchDisplayName(item)}{item.current ? (zh ? " · 当前" : " · Current") : ""}</span></VButton>
            <div className={styles.mobileActions}>{primaryColumns[1].render(item)}{renderLifecycleActions(item)}</div>
          </div>)}</div>
        </div>
      )}
      <div className={styles.listFooter}><span>{(!hasAnyItems && listError) || showListLoading ? "—" : activeRows.length} {zh ? "个工作区" : "workspaces"}</span><span>{zh ? "退役记录保留在筛选中" : "Retired workspaces remain in filters"}</span></div>
      </>}
      <VConfirmDialog open={forceStopId !== null} onOpenChange={(open) => { if (!open) setForceStopId(null); }} title={labels.forceStop} description={`${forceStopItem ? launcherBranchDisplayName(forceStopItem) : ""} · ${labels.forceStopHint}`} tone="danger" confirmLabel={labels.forceStop} cancelLabel={zh ? "取消" : "Cancel"} confirmDisabled={lifecyclePending || !items.some((item) => item.id === forceStopId && canForceStopInstance(item))} onConfirm={() => { if (lifecyclePending) return; const item = items.find((entry) => entry.id === forceStopId); if (item && canForceStopInstance(item)) onLifecycle?.(item.id, "force-stop"); setForceStopId(null); }} />
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
          if (!open && !batchStopPending) {
            setBatchStopIds(null);
          }
        }}
        title={batchStopKind === "close" ? labels.closeConfirmTitle : labels.stopConfirmTitle}
        description={labels.stopConfirmHint}
        tone="neutral"
        size="md"
        confirmLabel={batchStopKind === "close" ? labels.close : labels.stop}
        cancelLabel={zh ? "取消" : "Cancel"}
        confirmPending={batchStopPending}
        confirmDisabled={batchStopItems.length === 0}
        onConfirm={() => {
          const eligible = batchStopItems.filter((item) => canStopInstance(item, pendingOperation)).map((item) => item.id);
          if (eligible.length > 0) {
            onStopMany?.(eligible);
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
