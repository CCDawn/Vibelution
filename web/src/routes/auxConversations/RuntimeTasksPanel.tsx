import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, RefreshCw, StopCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  childSessionHref,
  getRuntimeTask,
  listRuntimeTasks,
  listRuntimeTasksRevisionAware,
  stopRuntimeTask,
  type RuntimeTaskCard,
  type RuntimeTaskListPayload,
} from "../../api/runtimeTasks";
import { queryKeys } from "../../api/queryKeys";
import { resolvePollingInterval, usePageVisibility } from "../../app/pollingPolicy";
import type { ActiveWorkIndicator, ActiveWorkIndicatorItem, SystemStatusTone } from "../../app/systemStatus";
import {
  VButton,
  VConfirmDialog,
  VEmbeddedPanel,
  VIconButton,
  VNativeButton,
  VRouteLinkButton,
  VStateSurface,
  VStatusChip,
  type VStatusTone,
  VTabs,
  type VTabsItem,
} from "../../components/vui";
import { ChatReadOnlySessionWorkspace } from "../chat/ChatReadOnlySessionWorkspace";
import { fetchSessionDetailWindow } from "../chat/chatSessionDetailHelpers";
import { ProgressiveRegionSkeleton } from "../shared/ProgressiveRegionSkeleton";
import {
  auxTaskKindLabel,
  auxTaskStatusIcon,
  auxTaskStatusLabel,
  auxTaskStatusTone,
  formatRelativeTime,
  formatTaskTimeRange,
  isTerminalRuntimeTask,
} from "./auxTaskPresentation";
import { styles } from "./RuntimeTasksPanel.styles";
import {
  activeWorkSessionIdentity,
  deduplicateRuntimeTasksByActiveWork,
  isRuntimeTaskAwaitingStopConfirmation,
} from "./runtimeTasksPanelModel";

type PanelScope = "project" | "session";
type PanelFilter = "running" | "all";
const AUX_TASKS_POLL_MS = 4_000;
const AUX_ENDED_PAGE_SIZE = 20;

export type RuntimeTasksPanelProps = {
  lang: "zh" | "en";
  activeSessionId?: string | null;
  activeWork?: ActiveWorkIndicator | null;
  onOpenSession?: (sessionId: string) => void;
  /** Open the full task center; the selected task id is supplied from detail. */
  onExpand?: (taskId?: string) => void;
};

const COPY = {
  zh: {
    title: "任务",
    projectScope: "当前项目",
    sessionScope: "当前会话",
    needSession: "打开一个会话后可按会话筛选",
    running: "运行中",
    all: "全部",
    activeWork: "进行中的工作",
    backgroundTasks: "辅助任务",
    staleFailures: "最近异常",
    detail: "任务详情",
    back: "任务列表",
    expand: "完整中心",
    refresh: "刷新任务",
    loading: "读取任务…",
    loadFailed: "任务读取失败",
    refreshFailed: "刷新失败，正在显示上次读取的内容",
    retry: "重试",
    noTasks: "当前范围暂无任务",
    noRuntimeTasks: "暂无辅助任务",
    noRunningTasks: "没有正在运行的辅助任务",
    selectTask: "选择一个辅助任务查看详情",
    startedAt: "开始时间",
    parentSession: "父会话",
    status: "状态",
    kind: "类型",
    summary: "摘要",
    noSummary: "暂无摘要",
    outputPath: "输出文件",
    pendingMessages: "待处理消息",
    timeline: "任务进度",
    transcript: "会话记录",
    transcriptEmpty: "会话暂无消息",
    transcriptFailed: "读取会话记录失败",
    openSession: "打开会话",
    openDestination: "打开",
    stop: "停止",
    stopping: "停止中…",
    stopHint: "已请求停止，等待任务列表确认结束。",
    stopFailed: "停止请求失败",
    stopRejected: "停止请求未被接受",
    stopConfirmTitle: "停止该任务？",
    stopConfirmDescription: "任务结束后，已产生的结果仍会保留。",
    cancel: "取消",
    loadMore: "再显示 20 个",
    loadingMore: "加载中…",
    loadMoreFailed: "加载更多失败，请重试",
  },
  en: {
    title: "Tasks",
    projectScope: "This project",
    sessionScope: "This session",
    needSession: "Open a session to filter by session",
    running: "Running",
    all: "All",
    activeWork: "Active work",
    backgroundTasks: "Auxiliary tasks",
    staleFailures: "Recent failures",
    detail: "Task details",
    back: "Task list",
    expand: "Full center",
    refresh: "Refresh tasks",
    loading: "Loading tasks…",
    loadFailed: "Could not load tasks",
    refreshFailed: "Refresh failed. Showing the last loaded data.",
    retry: "Retry",
    noTasks: "No tasks in this scope",
    noRuntimeTasks: "No auxiliary tasks",
    noRunningTasks: "No running auxiliary tasks",
    selectTask: "Select an auxiliary task to inspect it",
    startedAt: "Started",
    parentSession: "Parent session",
    status: "Status",
    kind: "Kind",
    summary: "Summary",
    noSummary: "No summary yet",
    outputPath: "Output file",
    pendingMessages: "Pending messages",
    timeline: "Task progress",
    transcript: "Session transcript",
    transcriptEmpty: "No session messages yet",
    transcriptFailed: "Could not load the transcript",
    openSession: "Open session",
    openDestination: "Open",
    stop: "Stop",
    stopping: "Stopping…",
    stopHint: "Stop requested. Waiting for the task list to confirm completion.",
    stopFailed: "Stop request failed",
    stopRejected: "The stop request was not accepted",
    stopConfirmTitle: "Stop this task?",
    stopConfirmDescription: "Completed output will be kept after the task ends.",
    cancel: "Cancel",
    loadMore: "Show 20 more",
    loadingMore: "Loading…",
    loadMoreFailed: "Could not load more tasks. Retry.",
  },
} as const;

const STATUS_LABELS: Record<string, { zh: string; en: string }> = {
  running: { zh: "运行中", en: "Running" },
  answering: { zh: "回答中", en: "Answering" },
  tooling: { zh: "执行工具", en: "Using tools" },
  queued: { zh: "排队中", en: "Queued" },
  paused: { zh: "已暂停", en: "Paused" },
  pause_requested: { zh: "等待暂停", en: "Pause requested" },
  pausing: { zh: "暂停中", en: "Pausing" },
  stopping: { zh: "停止中", en: "Stopping" },
  failed: { zh: "失败", en: "Failed" },
  failed_provider: { zh: "调用失败", en: "Provider failed" },
  failed_runtime: { zh: "运行失败", en: "Runtime failed" },
};

function statusText(status: string, lang: "zh" | "en") {
  const normalized = String(status || "").trim().toLowerCase();
  return STATUS_LABELS[normalized]?.[lang] || normalized.replaceAll("_", " ") || "-";
}

function activeWorkTone(tone: SystemStatusTone): VStatusTone {
  switch (tone) {
    case "running":
      return "accent";
    case "failed":
      return "danger";
    case "caution":
      return "warning";
    default:
      return "neutral";
  }
}

function describeError(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function uniqueTasks(tasks: RuntimeTaskCard[]) {
  const byId = new Map<string, RuntimeTaskCard>();
  for (const task of tasks) {
    if (task.taskId && !byId.has(task.taskId)) {
      byId.set(task.taskId, task);
    }
  }
  return [...byId.values()];
}

export function RuntimeTasksPanel({
  lang,
  activeSessionId,
  activeWork,
  onOpenSession,
  onExpand,
}: RuntimeTasksPanelProps) {
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();
  const normalizedActiveSessionId = String(activeSessionId || "").trim();

  const [scope, setScope] = useState<PanelScope>("project");
  const [filter, setFilter] = useState<PanelFilter>("running");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [stopTargetId, setStopTargetId] = useState("");
  const [stopRequestedIds, setStopRequestedIds] = useState<readonly string[]>([]);
  const [stopRejectedId, setStopRejectedId] = useState("");
  const [endedExtras, setEndedExtras] = useState<RuntimeTaskCard[]>([]);
  const [endedCursor, setEndedCursor] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState(false);

  const effectiveScope: PanelScope = scope === "session" && normalizedActiveSessionId ? "session" : "project";
  const parentSessionId = effectiveScope === "session" ? normalizedActiveSessionId : "";
  const listKey = queryKeys.runtimeTasks("", parentSessionId);

  const listQuery = useQuery({
    queryKey: listKey,
    queryFn: ({ signal }) => listRuntimeTasksRevisionAware(
      {
        status: "all",
        parentSessionId: parentSessionId || undefined,
        limit: AUX_ENDED_PAGE_SIZE,
      },
      queryClient.getQueryData<RuntimeTaskListPayload>(listKey),
      signal,
    ),
    refetchInterval: resolvePollingInterval(pageVisible, AUX_TASKS_POLL_MS),
    refetchIntervalInBackground: false,
  });

  const payload = listQuery.data;
  const revision = payload ? String(payload.revision) : "";
  const runningTasks = payload?.running ?? [];
  const endedPageItems = payload?.ended?.items ?? [];
  const endedTotal = payload?.ended?.total ?? 0;
  const nextCursor = payload?.ended?.nextCursor ?? "";

  useEffect(() => {
    setSelectedTaskId("");
    setStopRejectedId("");
  }, [effectiveScope, normalizedActiveSessionId, filter]);

  useEffect(() => {
    setEndedExtras([]);
    setEndedCursor(nextCursor);
    setLoadMoreError(false);
  }, [parentSessionId, revision, nextCursor]);

  const allPageTasks = useMemo(
    () => uniqueTasks([...runningTasks, ...endedPageItems, ...endedExtras]),
    [runningTasks, endedPageItems, endedExtras],
  );
  const runningTaskIds = useMemo(() => new Set(runningTasks.map((task) => task.taskId)), [runningTasks]);
  const terminalTaskIds = useMemo(
    () => new Set([...endedPageItems, ...endedExtras].map((task) => task.taskId)),
    [endedPageItems, endedExtras],
  );

  const visibleActiveWork = useMemo(() => {
    const items = activeWork?.items ?? [];
    if (effectiveScope === "project") {
      return items;
    }
    return items.filter((item) => activeWorkSessionIdentity(item) === normalizedActiveSessionId);
  }, [activeWork?.items, effectiveScope, normalizedActiveSessionId]);
  const visibleStaleFailures = useMemo(() => {
    if (filter !== "all") {
      return [];
    }
    const items = activeWork?.staleFailures ?? [];
    if (effectiveScope === "project") {
      return items;
    }
    return items.filter((item) => activeWorkSessionIdentity(item) === normalizedActiveSessionId);
  }, [activeWork?.staleFailures, effectiveScope, filter, normalizedActiveSessionId]);

  const dedupeWork = useMemo(
    () => [...visibleActiveWork, ...visibleStaleFailures],
    [visibleActiveWork, visibleStaleFailures],
  );
  const visibleTasks = useMemo(() => {
    const source = filter === "running" ? runningTasks : allPageTasks;
    return deduplicateRuntimeTasksByActiveWork(source, dedupeWork);
  }, [allPageTasks, dedupeWork, filter, runningTasks]);

  const selectedTaskFromList = useMemo(
    () => allPageTasks.find((task) => task.taskId === selectedTaskId) ?? null,
    [allPageTasks, selectedTaskId],
  );
  const detailQuery = useQuery({
    queryKey: queryKeys.runtimeTask(selectedTaskId),
    queryFn: () => getRuntimeTask(selectedTaskId),
    enabled: Boolean(selectedTaskId),
  });
  const selectedTask = selectedTaskFromList ?? detailQuery.data ?? null;
  const selectedIsLive = selectedTask
    ? runningTaskIds.has(selectedTask.taskId)
      ? true
      : terminalTaskIds.has(selectedTask.taskId)
        ? false
        : !isTerminalRuntimeTask(selectedTask)
    : false;
  const stopPendingForSelection = Boolean(
    selectedTask
    && selectedIsLive
    && isRuntimeTaskAwaitingStopConfirmation(selectedTask.taskId, stopRequestedIds, terminalTaskIds),
  );

  useEffect(() => {
    if (!terminalTaskIds.size) {
      return;
    }
    setStopRequestedIds((current) => current.filter((taskId) => !terminalTaskIds.has(taskId)));
  }, [terminalTaskIds]);

  const selectedChildSessionId = String(selectedTask?.childSessionId || "").trim();
  const streamQuery = useQuery({
    queryKey: ["aux-session-detail", selectedChildSessionId],
    queryFn: ({ signal }) => fetchSessionDetailWindow(selectedChildSessionId, {
      transcriptScope: "window",
      includeSecondary: false,
      signal,
    }),
    enabled: Boolean(selectedChildSessionId),
    refetchInterval: selectedChildSessionId && selectedIsLive
      ? resolvePollingInterval(pageVisible, AUX_TASKS_POLL_MS)
      : false,
    refetchIntervalInBackground: false,
  });

  const stopMutation = useMutation({
    mutationFn: (taskId: string) => stopRuntimeTask(taskId),
    onSuccess: (result) => {
      if (result.accepted) {
        setStopRequestedIds((current) => current.includes(result.taskId)
          ? current
          : [...current, result.taskId]);
        setStopRejectedId("");
      } else {
        setStopRejectedId(result.taskId || stopTargetId);
      }
      void queryClient.invalidateQueries({ queryKey: ["runtime-tasks"] });
      if (result.accepted) {
        setStopTargetId("");
      }
    },
  });

  const loadMoreEnded = useCallback(async () => {
    if (!endedCursor || loadingMore) {
      return;
    }
    setLoadingMore(true);
    setLoadMoreError(false);
    try {
      const page = await listRuntimeTasks({
        status: "ended",
        parentSessionId: parentSessionId || undefined,
        cursor: endedCursor,
        limit: AUX_ENDED_PAGE_SIZE,
      });
      setEndedExtras((current) => uniqueTasks([...current, ...(page.ended?.items ?? [])]));
      setEndedCursor(page.ended?.nextCursor ?? "");
    } catch {
      setLoadMoreError(true);
    } finally {
      setLoadingMore(false);
    }
  }, [endedCursor, loadingMore, parentSessionId]);

  const initialLoad = listQuery.isLoading && !payload;
  const workSessionScopeAvailable = Boolean(normalizedActiveSessionId);
  const scopeItems: VTabsItem[] = [
    { id: "project", label: copy.projectScope },
    { id: "session", label: copy.sessionScope, disabled: !workSessionScopeAvailable, title: workSessionScopeAvailable ? undefined : copy.needSession },
  ];
  const filterItems: VTabsItem[] = [
    { id: "running", label: copy.running },
    { id: "all", label: copy.all },
  ];

  const taskCount = filter === "running" ? runningTasks.length : runningTasks.length + endedTotal;
  const taskListError = listQuery.isError && !payload;
  const taskRows = listQuery.isError && !payload ? (
    <VStateSurface
      fill
      density="compact"
      className={styles.stateSurface}
      title={copy.loadFailed}
      tone="error"
      actions={<VButton density="compact" variant="secondary" onPress={() => void listQuery.refetch()}>{copy.retry}</VButton>}
    >
      {describeError(listQuery.error, copy.loadFailed)}
    </VStateSurface>
  ) : initialLoad ? (
    <ProgressiveRegionSkeleton variant="list" label={copy.loading} />
  ) : (
    <>
      {listQuery.isError ? (
        <VStateSurface
          density="compact"
          className={styles.compactError}
          title={copy.refreshFailed}
          tone="error"
          actions={<VButton density="compact" variant="ghost" onPress={() => void listQuery.refetch()}>{copy.retry}</VButton>}
        >
          {describeError(listQuery.error, copy.loadFailed)}
        </VStateSurface>
      ) : null}
      {visibleTasks.length ? (
        <section className={styles.section} aria-label={copy.backgroundTasks}>
          <div className={styles.sectionHeader}>
            <h3 className={styles.sectionTitle}>{copy.backgroundTasks}</h3>
            <span className={styles.count}>{taskCount}</span>
          </div>
          <div className={styles.section} role="list">
            {visibleTasks.map((task) => (
              <TaskRow
                key={task.taskId}
                task={task}
                lang={lang}
                selected={task.taskId === selectedTaskId}
                stopPending={isRuntimeTaskAwaitingStopConfirmation(task.taskId, stopRequestedIds, terminalTaskIds)}
                onSelect={() => setSelectedTaskId(task.taskId)}
              />
            ))}
          </div>
          {filter === "all" && endedCursor ? (
            <div className={styles.loadMore}>
              <VButton density="compact" variant="ghost" isPending={loadingMore} onPress={() => void loadMoreEnded()}>
                {loadingMore ? copy.loadingMore : copy.loadMore}
              </VButton>
              {loadMoreError ? <p className={styles.muted}>{copy.loadMoreFailed}</p> : null}
            </div>
          ) : null}
        </section>
      ) : null}
      {!visibleTasks.length ? (
        <VStateSurface
          density="compact"
          className={styles.compactError}
          title={filter === "running" ? copy.noRunningTasks : copy.noRuntimeTasks}
          tone="empty"
        />
      ) : null}
    </>
  );

  const activeWorkBlock = visibleActiveWork.length ? (
    <section className={styles.section} aria-label={copy.activeWork}>
      <div className={styles.sectionHeader}>
        <h3 className={styles.sectionTitle}>{copy.activeWork}</h3>
        <span className={styles.count}>{visibleActiveWork.length}</span>
      </div>
      <div className={styles.section} role="list">
        {visibleActiveWork.map((item, index) => (
          <ActiveWorkRow key={`${item.kind}-${item.runId || item.status}-${index}`} item={item} lang={lang} copy={copy} />
        ))}
      </div>
    </section>
  ) : null;

  const staleWorkBlock = visibleStaleFailures.length ? (
    <section className={styles.section} aria-label={copy.staleFailures}>
      <div className={styles.sectionHeader}>
        <h3 className={styles.sectionTitle}>{copy.staleFailures}</h3>
        <span className={styles.count}>{visibleStaleFailures.length}</span>
      </div>
      <div className={styles.section} role="list">
        {visibleStaleFailures.map((item, index) => (
          <ActiveWorkRow key={`${item.kind}-${item.runId || item.status}-${index}`} item={item} lang={lang} copy={copy} stale />
        ))}
      </div>
    </section>
  ) : null;

  const showEmptyPanel = !initialLoad
    && !taskListError
    && !activeWorkBlock
    && !staleWorkBlock
    && !visibleTasks.length;

  const detailErrorWithoutCard = Boolean(selectedTaskId && detailQuery.isError && !selectedTask);
  const selectedDetailsError = detailQuery.isError && Boolean(selectedTask);
  const selectedStopError = stopRejectedId === selectedTaskId && stopRejectedId
    ? copy.stopRejected
    : stopMutation.isError && stopTargetId === selectedTaskId
      ? describeError(stopMutation.error, copy.stopFailed)
      : "";

  const renderTaskDetail = selectedTaskId ? (
    <div className={styles.detail}>
      <div className={styles.detailToolbar}>
        <VButton variant="ghost" density="compact" onPress={() => setSelectedTaskId("")}>
          <ArrowLeft size={14} aria-hidden="true" />
          {copy.back}
        </VButton>
        {onExpand ? (
          <VButton variant="ghost" density="compact" onPress={() => onExpand(selectedTaskId)}>
            {copy.expand}
            <ExternalLink size={13} aria-hidden="true" />
          </VButton>
        ) : null}
      </div>
      <div className={styles.detailScroll}>
        {detailQuery.isLoading && !selectedTask ? (
          <ProgressiveRegionSkeleton variant="detail" label={copy.loading} />
        ) : detailErrorWithoutCard ? (
          <VStateSurface
            fill
            density="compact"
            className={styles.stateSurface}
            title={copy.loadFailed}
            tone="error"
            actions={(
              <>
                <VButton density="compact" variant="secondary" onPress={() => void detailQuery.refetch()}>{copy.retry}</VButton>
                <VButton density="compact" variant="ghost" onPress={() => setSelectedTaskId("")}>{copy.back}</VButton>
              </>
            )}
          >
            {describeError(detailQuery.error, copy.loadFailed)}
          </VStateSurface>
        ) : selectedTask ? (
          <>
            <header className={styles.detailHeader}>
              <div className={styles.detailTitleRow}>
                <h2 className={styles.detailTitle}>{selectedTask.title || selectedTask.taskId}</h2>
                <VStatusChip tone={auxTaskStatusTone(stopPendingForSelection ? "stopping" : selectedTask.status)}>
                  {auxTaskStatusLabel(stopPendingForSelection ? "stopping" : selectedTask.status, lang)}
                </VStatusChip>
              </div>
              <p className={styles.detailMeta}>
                {auxTaskKindLabel(selectedTask.kind, lang)} · {copy.startedAt}: {formatTaskTimeRange(selectedTask.startedAt, selectedTask.endedAt, lang)}
              </p>
              <p className={styles.detailMeta}>{copy.parentSession}: {selectedTask.parentSessionId || "-"}</p>
              {selectedTask.summary?.trim() ? <p className={styles.detailMeta}>{selectedTask.summary}</p> : null}
              <div className={styles.detailActions}>
                {selectedIsLive ? (
                  <VButton
                    density="compact"
                    variant="ghost"
                    isDisabled={stopPendingForSelection || stopMutation.isPending}
                    onPress={() => {
                      setStopRejectedId("");
                      setStopTargetId(selectedTask.taskId);
                    }}
                  >
                    <StopCircle size={14} aria-hidden="true" />
                    {stopPendingForSelection ? copy.stopping : copy.stop}
                  </VButton>
                ) : null}
                {(selectedTask.childSessionId || selectedTask.parentSessionId) ? (
                  onOpenSession ? (
                    <VButton
                      density="compact"
                      variant="ghost"
                      onPress={() => onOpenSession(selectedChildSessionId || selectedTask.parentSessionId)}
                    >
                      {copy.openSession}
                    </VButton>
                  ) : (
                    <VRouteLinkButton
                      to={childSessionHref(selectedChildSessionId || selectedTask.parentSessionId)}
                      density="compact"
                      variant="ghost"
                    >
                      {copy.openSession}
                    </VRouteLinkButton>
                  )
                ) : null}
              </div>
              {stopPendingForSelection ? <p className={styles.muted}>{copy.stopHint}</p> : null}
              {selectedStopError ? <p role="alert" className={styles.muted}>{selectedStopError}</p> : null}
            </header>

            {selectedDetailsError ? (
              <VStateSurface
                density="compact"
                className={styles.compactError}
                title={copy.loadFailed}
                tone="error"
                actions={<VButton density="compact" variant="ghost" onPress={() => void detailQuery.refetch()}>{copy.retry}</VButton>}
              >
                {describeError(detailQuery.error, copy.loadFailed)}
              </VStateSurface>
            ) : null}

            {selectedChildSessionId ? (
              <section className={styles.section} aria-label={copy.transcript}>
                <div className={styles.sectionHeader}><h3 className={styles.sectionTitle}>{copy.transcript}</h3></div>
                <div className={styles.transcript}>
                  {streamQuery.isLoading && !streamQuery.data ? (
                    <ProgressiveRegionSkeleton variant="detail" label={copy.loading} />
                  ) : streamQuery.isError && !streamQuery.data ? (
                    <VStateSurface
                      fill
                      density="compact"
                      className={styles.stateSurface}
                      title={copy.transcriptFailed}
                      tone="error"
                      actions={<VButton density="compact" variant="secondary" onPress={() => void streamQuery.refetch()}>{copy.retry}</VButton>}
                    >
                      {describeError(streamQuery.error, copy.transcriptFailed)}
                    </VStateSurface>
                  ) : (
                    <ChatReadOnlySessionWorkspace
                      assistant={{ displayName: selectedTask.title || selectedTask.taskId }}
                      defaultFileContext=""
                      detail={streamQuery.data}
                      emptyLabel={copy.transcriptEmpty}
                      lang={lang}
                      live={selectedIsLive}
                      loading={streamQuery.isLoading}
                      loadingLabel={copy.loading}
                      sessionId={selectedChildSessionId}
                      user={{ displayName: lang === "zh" ? "用户" : "User" }}
                    />
                  )}
                </div>
              </section>
            ) : (
              <>
                <section className={styles.detailSection} aria-label={copy.summary}>
                  <h3 className={styles.sectionTitle}>{copy.summary}</h3>
                  <p className={styles.muted}>{selectedTask.summary?.trim() || copy.noSummary}</p>
                  {selectedTask.outputPath ? <p className={styles.muted}>{copy.outputPath}: {selectedTask.outputPath}</p> : null}
                </section>
                {selectedDetailsError ? null : (
                  <>
                    {detailQuery.isLoading && !detailQuery.data ? (
                      <ProgressiveRegionSkeleton variant="detail" label={copy.loading} />
                    ) : null}
                    {Number(detailQuery.data?.pendingMessageCount ?? 0) > 0 ? (
                      <p className={styles.muted}>{copy.pendingMessages}: {detailQuery.data?.pendingMessageCount}</p>
                    ) : null}
                    {(detailQuery.data?.timeline?.length ?? 0) ? (
                      <section className={styles.detailSection} aria-label={copy.timeline}>
                        <h3 className={styles.sectionTitle}>{copy.timeline}</h3>
                        {detailQuery.data!.timeline!.map((item, index) => (
                          <p className={styles.detailMeta} key={`${item.at ?? "at"}-${index}`}>
                            {formatRelativeTime(String(item.at || ""), lang)} · {String(item.label || item.status || "-")}
                          </p>
                        ))}
                      </section>
                    ) : null}
                  </>
                )}
              </>
            )}
          </>
        ) : (
          <VStateSurface fill density="compact" className={styles.stateSurface} title={copy.selectTask} tone="empty" />
        )}
      </div>
    </div>
  ) : (
    <>
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <h2 className={styles.title}>{copy.title}</h2>
          <div className={styles.headerActions}>
            {onExpand ? (
              <VButton variant="ghost" density="compact" onPress={() => onExpand()}>
                {copy.expand}
              </VButton>
            ) : null}
            <VIconButton
              label={copy.refresh}
              icon={<RefreshCw size={14} />}
              isDisabled={listQuery.isFetching}
              className={styles.refreshButton}
              onPress={() => void listQuery.refetch()}
            />
          </div>
        </div>
        <div className={styles.filters}>
          <VTabs
            aria-label={copy.projectScope}
            items={scopeItems}
            value={effectiveScope}
            onValueChange={(next) => {
              if (next === "project" || (next === "session" && workSessionScopeAvailable)) {
                setScope(next);
              }
            }}
            className={styles.filterTabs}
            listClassName={styles.filterTabList}
            triggerClassName={styles.filterTabTrigger}
          />
          <VTabs
            aria-label={copy.all}
            items={filterItems}
            value={filter}
            onValueChange={(next) => {
              if (next === "running" || next === "all") {
                setFilter(next);
              }
            }}
            className={styles.filterTabs}
            listClassName={styles.filterTabList}
            triggerClassName={styles.filterTabTrigger}
          />
        </div>
      </header>
      <div className={styles.content}>
        {activeWorkBlock}
        {staleWorkBlock}
        {taskRows}
        {showEmptyPanel ? (
          <VStateSurface fill density="compact" className={styles.stateSurface} title={copy.noTasks} tone="empty" />
        ) : null}
      </div>
    </>
  );

  const stopTargetTask = allPageTasks.find((task) => task.taskId === stopTargetId) ?? selectedTask;

  return (
    <>
      <VEmbeddedPanel
        ariaLabel={copy.title}
        className={styles.root}
        data-vui-product="runtime-tasks-panel"
      >
        {renderTaskDetail}
      </VEmbeddedPanel>
      <VConfirmDialog
        open={Boolean(stopTargetId)}
        onOpenChange={(open) => {
          if (!open && !stopMutation.isPending) {
            setStopTargetId("");
          }
        }}
        tone="danger"
        title={copy.stopConfirmTitle}
        description={stopTargetTask?.title || copy.stopConfirmDescription}
        confirmLabel={copy.stop}
        cancelLabel={copy.cancel}
        confirmPending={stopMutation.isPending}
        onConfirm={() => {
          if (stopTargetId) {
            stopMutation.mutate(stopTargetId);
          }
        }}
      />
    </>
  );
}

function TaskRow({
  task,
  lang,
  selected,
  stopPending,
  onSelect,
}: {
  task: RuntimeTaskCard;
  lang: "zh" | "en";
  selected: boolean;
  stopPending: boolean;
  onSelect: () => void;
}) {
  const { Icon, spin } = auxTaskStatusIcon(stopPending ? "stopping" : task.status);
  const timestamp = String(task.endedAt || "").trim() || task.startedAt;
  return (
    <VNativeButton
      className={`${styles.taskRow} ${selected ? styles.selectedTaskRow : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
      role="listitem"
    >
      <span className={styles.rowIcon} aria-hidden="true">
        <Icon size={15} className={spin ? styles.rowIconSpin : undefined} />
      </span>
      <span className={styles.taskMain}>
        <span className={styles.taskTop}>
          <strong className={styles.taskName} title={task.title}>{task.title || task.taskId}</strong>
          <span className={styles.statusText}>{
            stopPending ? (lang === "zh" ? "停止中" : "Stopping") : auxTaskStatusLabel(task.status, lang)
          }</span>
        </span>
        <span className={styles.taskMeta}>
          <span>{auxTaskKindLabel(task.kind, lang)}</span>
          {task.summary?.trim() ? <span className={styles.taskSummary} title={task.summary}>{task.summary}</span> : null}
        </span>
      </span>
      <span className={styles.timestamp}>{formatRelativeTime(timestamp, lang)}</span>
    </VNativeButton>
  );
}

function ActiveWorkRow({
  item,
  lang,
  copy,
  stale = false,
}: {
  item: ActiveWorkIndicatorItem;
  lang: "zh" | "en";
  copy: typeof COPY["zh"] | typeof COPY["en"];
  stale?: boolean;
}) {
  const sessionId = activeWorkSessionIdentity(item);
  return (
    <article className={stale ? styles.staleRow : styles.workRow} role="listitem">
      <div className={styles.workCopy}>
        <div className={styles.titleRow}>
          <h4 className={styles.workTitle}>{item.label}</h4>
          <VStatusChip tone={activeWorkTone(item.tone)}>{statusText(item.status, lang)}</VStatusChip>
        </div>
        {item.summary ? <p className={styles.workSummary} title={item.fullSummary || item.summary}>{item.summary}</p> : null}
      </div>
      <div className={styles.workActions}>
        {item.href ? (
          <VRouteLinkButton to={item.href} variant="ghost" density="compact" className={styles.workOpenLink}>
            {sessionId ? (lang === "zh" ? "会话" : "Session") : copy.openDestination}
          </VRouteLinkButton>
        ) : null}
      </div>
    </article>
  );
}
