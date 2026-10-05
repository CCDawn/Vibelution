import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, StopCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

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
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import {
  VActionGroup,
  VButton,
  VConfirmDialog,
  VIconButton,
  VListDetailPage,
  VMetricStrip,
  VNativeButton,
  VRouteLinkButton,
  VSelect,
  VStateSurface,
  VStatusChip,
  VSurface,
} from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import { ChatReadOnlySessionWorkspace } from "../chat/ChatReadOnlySessionWorkspace";
import { fetchSessionDetailWindow } from "../chat/chatSessionDetailHelpers";
import { ProgressiveRegionSkeleton } from "../shared/ProgressiveRegionSkeleton";
import styles from "./AuxConversationsRoute.styles";
import {
  AUX_TASK_KINDS,
  auxTaskKindLabel,
  auxTaskStatusIcon,
  auxTaskStatusLabel,
  auxTaskStatusTone,
  formatRelativeTime,
  formatTaskTimeRange,
  isTerminalRuntimeTask,
} from "./auxTaskPresentation";

/** Foreground poll beat for the task list; hidden pages stop polling. */
export const AUX_TASKS_POLL_MS = 4_000;
/** Ended-directory page size, matching the ZCode directory's 20-per-page. */
export const AUX_ENDED_PAGE_SIZE = 20;
const ALL_KIND_KEY = "all";

const COPY = {
  zh: {
    title: "辅助对话中心",
    taskList: "任务",
    detail: "详情",
    running: "正在运行",
    ended: "已结束",
    kind: "类型",
    allKinds: "全部类型",
    refresh: "刷新",
    noTasks: "暂无辅助任务",
    noRunningTasks: "没有正在运行的任务",
    loading: "读取中",
    loadFailed: "读取失败",
    selectTask: "选择一个任务查看详情",
    loadMore: "再显示 20 个",
    loadingMore: "加载中…",
    loadMoreFailed: "加载更多失败，请重试",
    stopTask: "停止任务",
    stopConfirmTitle: "停止该任务？",
    stopConfirmDescription: "停止后任务将结束运行，已产生的结果保留。",
    stopPending: "停止中…",
    stopFailed: "停止请求失败",
    stoppingHint: "已请求停止，等待任务结束。",
    openInSession: "在会话中打开",
    parentSession: "父会话",
    status: "状态",
    startedAt: "起止",
    outputPath: "输出文件",
    noSummary: "暂无摘要",
    pendingMessages: "待处理消息",
    timeline: "时间线",
    conversationStream: "对话流",
    streamEmpty: "会话暂无消息",
    loadStreamFailed: "读取会话失败",
    userLabel: "用户",
  },
  en: {
    title: "Aux conversations",
    taskList: "Tasks",
    detail: "Detail",
    running: "Running",
    ended: "Ended",
    kind: "Kind",
    allKinds: "All kinds",
    refresh: "Refresh",
    noTasks: "No aux tasks",
    noRunningTasks: "No running tasks",
    loading: "Loading",
    loadFailed: "Load failed",
    selectTask: "Select a task to inspect details",
    loadMore: "Show 20 more",
    loadingMore: "Loading…",
    loadMoreFailed: "Load more failed; retry",
    stopTask: "Stop task",
    stopConfirmTitle: "Stop this task?",
    stopConfirmDescription: "The task will stop running; finished output is kept.",
    stopPending: "Stopping…",
    stopFailed: "Stop request failed",
    stoppingHint: "Stop requested; waiting for the task to end.",
    openInSession: "Open in session",
    parentSession: "Parent session",
    status: "Status",
    startedAt: "Start / end",
    outputPath: "Output path",
    noSummary: "No summary yet",
    pendingMessages: "Pending messages",
    timeline: "Timeline",
    conversationStream: "Conversation stream",
    streamEmpty: "No messages yet",
    loadStreamFailed: "Failed to load conversation",
    userLabel: "User",
  },
} as const;

function shortId(value: string) {
  const text = String(value || "").trim();
  if (!text) {
    return "-";
  }
  if (text.length <= 14) {
    return text;
  }
  return `${text.slice(0, 8)}…${text.slice(-4)}`;
}

function describeError(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function AuxConversationsRoute() {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();
  const [searchParams, setSearchParams] = useSearchParams();

  const [kindFilter, setKindFilter] = useState(ALL_KIND_KEY);
  const kindParam = kindFilter === ALL_KIND_KEY ? "" : kindFilter;
  const listKey = queryKeys.runtimeTasks(kindParam);

  // Ended pagination lives outside the polled query: page-one items refresh
  // with the revision, extras accumulate until the revision changes.
  const [endedExtras, setEndedExtras] = useState<RuntimeTaskCard[]>([]);
  const [endedCursor, setEndedCursor] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState(false);
  const [stopTargetId, setStopTargetId] = useState("");
  // Stop only records the intent: the id stays "requested" until the polled
  // status lands in a terminal bucket, so the UI shows 停止中… meanwhile.
  const [stopRequestedIds, setStopRequestedIds] = useState<readonly string[]>([]);

  const listQuery = useQuery({
    queryKey: listKey,
    queryFn: ({ signal }) =>
      listRuntimeTasksRevisionAware(
        {
          status: "all",
          kind: kindParam || undefined,
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
  const runningTasks = useMemo(() => payload?.running ?? [], [payload]);
  const endedPageItems = useMemo(() => payload?.ended?.items ?? [], [payload]);
  const endedTotal = payload?.ended?.total ?? 0;
  const nextCursor = payload?.ended?.nextCursor ?? "";

  // A new revision means page one changed: reset accumulated ended pages.
  useEffect(() => {
    setEndedExtras([]);
    setEndedCursor(nextCursor);
    setLoadMoreError(false);
  }, [revision, nextCursor]);

  const updateSelectedTaskId = useCallback(
    (taskId: string) => {
      const nextTaskId = String(taskId || "").trim();
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          if (nextTaskId) {
            next.set("taskId", nextTaskId);
          } else {
            next.delete("taskId");
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const requestedTaskId = searchParams.get("taskId") ?? "";
  const listedTasks = useMemo(
    () => [...runningTasks, ...endedPageItems, ...endedExtras],
    [runningTasks, endedPageItems, endedExtras],
  );
  const selectedTaskFromList = useMemo(
    () => listedTasks.find((task) => task.taskId === requestedTaskId) ?? null,
    [listedTasks, requestedTaskId],
  );

  // Detail always loads for the selection: the card fields stay list-fresh,
  // the detail payload only contributes stopInitiator/pending/timeline extras.
  const detailQuery = useQuery({
    queryKey: queryKeys.runtimeTask(requestedTaskId),
    queryFn: () => getRuntimeTask(requestedTaskId),
    enabled: Boolean(requestedTaskId),
  });
  const selectedTask = selectedTaskFromList ?? detailQuery.data ?? null;
  const selectedDetailExtras = detailQuery.data;

  // Liveness from structural signals, never the status string: the running
  // bucket is live, the ended bucket is terminal, and a card only reachable
  // through the detail endpoint falls back to `endedAt` presence.
  const runningTaskIds = useMemo(() => new Set(runningTasks.map((task) => task.taskId)), [runningTasks]);
  const endedTaskIds = useMemo(
    () => new Set([...endedPageItems, ...endedExtras].map((task) => task.taskId)),
    [endedPageItems, endedExtras],
  );
  const selectedIsLive = selectedTask
    ? runningTaskIds.has(selectedTask.taskId)
      ? true
      : endedTaskIds.has(selectedTask.taskId)
        ? false
        : !isTerminalRuntimeTask(selectedTask)
    : false;
  const stopRequestedForSelection = Boolean(selectedTask && stopRequestedIds.includes(selectedTask.taskId));

  // Embedded read-only child-session transcript. Aux keeps its own query key:
  // this window snapshot must never overwrite the /chat live-transcript cache.
  const selectedChildSessionId = String(selectedTask?.childSessionId || "").trim();
  const streamQuery = useQuery({
    queryKey: ["aux-session-detail", selectedChildSessionId],
    queryFn: ({ signal }) =>
      fetchSessionDetailWindow(selectedChildSessionId, { transcriptScope: "window", signal }),
    enabled: Boolean(selectedChildSessionId),
    // Live tasks follow the same 4s foreground beat as the task list; ended
    // tasks take a single snapshot and never refetch.
    refetchInterval: selectedChildSessionId && selectedIsLive
      ? resolvePollingInterval(pageVisible, AUX_TASKS_POLL_MS)
      : false,
    refetchIntervalInBackground: false,
  });

  const stopMutation = useMutation({
    mutationFn: (taskId: string) => stopRuntimeTask(taskId),
    onSuccess: (result) => {
      if (result.accepted) {
        setStopRequestedIds((current) =>
          current.includes(result.taskId) ? current : [...current, result.taskId],
        );
      }
      void queryClient.invalidateQueries({ queryKey: ["runtime-tasks"] });
      setStopTargetId("");
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
        kind: kindParam || undefined,
        cursor: endedCursor,
        limit: AUX_ENDED_PAGE_SIZE,
      });
      setEndedExtras((current) => [...current, ...(page.ended?.items ?? [])]);
      setEndedCursor(page.ended?.nextCursor ?? "");
    } catch {
      setLoadMoreError(true);
    } finally {
      setLoadingMore(false);
    }
  }, [endedCursor, kindParam, loadingMore]);

  const initialLoad = listQuery.isLoading && !payload;
  const kindOptions = useMemo(
    () => [
      { id: ALL_KIND_KEY, label: copy.allKinds },
      ...AUX_TASK_KINDS.map((kind) => ({ id: kind, label: auxTaskKindLabel(kind, lang) })),
    ],
    [copy.allKinds, lang],
  );

  const renderRunningTaskRow = useCallback(
    (task: RuntimeTaskCard) => (
      <TaskRow
        key={task.taskId}
        task={task}
        lang={lang}
        selected={task.taskId === requestedTaskId}
        onSelect={() => updateSelectedTaskId(task.taskId)}
        stopLabel={copy.stopTask}
        onAskStop={() => setStopTargetId(task.taskId)}
      />
    ),
    [copy.stopTask, lang, requestedTaskId, updateSelectedTaskId],
  );

  const renderEndedTaskRow = useCallback(
    (task: RuntimeTaskCard) => (
      <TaskRow
        key={task.taskId}
        task={task}
        lang={lang}
        selected={task.taskId === requestedTaskId}
        onSelect={() => updateSelectedTaskId(task.taskId)}
      />
    ),
    [lang, requestedTaskId, updateSelectedTaskId],
  );

  const runningSection = (
    <section className={styles.taskSectionClass} aria-label={copy.running}>
      <div className={styles.taskSectionHeaderClass}>
        <h3 className={styles.taskSectionTitleClass}>{copy.running} · {runningTasks.length}</h3>
      </div>
      {runningTasks.length === 0 && !initialLoad ? (
        <p className={styles.mutedLineClass}>{copy.noRunningTasks}</p>
      ) : (
        runningTasks.map(renderRunningTaskRow)
      )}
    </section>
  );

  const endedSection = (
    <section className={styles.taskSectionClass} aria-label={copy.ended}>
      <div className={styles.taskSectionHeaderClass}>
        <h3 className={styles.taskSectionTitleClass}>{copy.ended} · {endedTotal}</h3>
      </div>
      {/* An empty ended directory stays silent — only the running section
          carries an empty line (ZCode SubagentDirectorySidePane.tsx:169-200). */}
      {endedPageItems.map(renderEndedTaskRow)}
      {endedExtras.map(renderEndedTaskRow)}
      {endedCursor ? (
        <div className={styles.loadMoreRowClass}>
          <VButton variant="ghost" density="compact" isPending={loadingMore} onPress={() => void loadMoreEnded()}>
            {loadingMore ? copy.loadingMore : copy.loadMore}
          </VButton>
          {loadMoreError ? <span className={styles.mutedLineClass}>{copy.loadMoreFailed}</span> : null}
        </div>
      ) : null}
    </section>
  );

  const listPaneContent = listQuery.isError ? (
    <VStateSurface fill className={styles.emptyStateClass} title={copy.loadFailed} tone="error">
      {describeError(listQuery.error, copy.loadFailed)}
    </VStateSurface>
  ) : initialLoad ? (
    <ProgressiveRegionSkeleton variant="list" label={copy.loading} className={styles.loadingRegionClass} />
  ) : runningTasks.length === 0 && endedPageItems.length === 0 && endedExtras.length === 0 ? (
    <VStateSurface fill className={styles.emptyStateClass} title={copy.noTasks} tone="empty" />
  ) : (
    <>
      {runningSection}
      {endedSection}
    </>
  );

  const stopTargetTask = listedTasks.find((task) => task.taskId === stopTargetId) ?? null;

  // Compact detail head shared by both panel shapes: with the embedded stream
  // it stays fixed on top while only the stream body scrolls.
  const detailHead = selectedTask ? (
    <>
      <div className={styles.detailHeaderClass}>
        <div className={styles.detailTitleWrapClass}>
          <p className={styles.eyebrowClass}>{copy.detail}</p>
          <h2 className={styles.detailTitleClass}>{selectedTask.title || shortId(selectedTask.taskId)}</h2>
        </div>
        <VStatusChip tone={auxTaskStatusTone(selectedTask.status)} className={styles.statusPillBaseClass}>
          {auxTaskStatusLabel(selectedTask.status, lang)}
        </VStatusChip>
      </div>

      <VMetricStrip
        ariaLabel={copy.detail}
        className={styles.summaryGridClass}
        metrics={[
          { id: "kind", label: copy.kind, value: auxTaskKindLabel(selectedTask.kind, lang), tone: "info" },
          { id: "status", label: copy.status, value: auxTaskStatusLabel(selectedTask.status, lang) },
          { id: "range", label: copy.startedAt, value: formatTaskTimeRange(selectedTask.startedAt, selectedTask.endedAt, lang) },
          { id: "parent", label: copy.parentSession, value: shortId(selectedTask.parentSessionId) },
        ]}
      />

      <div className={styles.detailActionsClass}>
        {selectedTask && selectedIsLive ? (
          <VButton
            variant="ghost"
            isPending={stopMutation.isPending}
            onPress={() => setStopTargetId(selectedTask.taskId)}
          >
            <StopCircle size={14} aria-hidden="true" />
            {stopRequestedForSelection ? copy.stopPending : copy.stopTask}
          </VButton>
        ) : null}
        {selectedTask.childSessionId ? (
          <VRouteLinkButton to={childSessionHref(selectedTask.childSessionId)} variant="ghost" density="compact">
            {copy.openInSession}
          </VRouteLinkButton>
        ) : null}
        {stopRequestedForSelection && selectedIsLive ? (
          <span className={styles.mutedLineClass}>{copy.stoppingHint}</span>
        ) : null}
        {stopMutation.isError && selectedTask ? (
          <span className={styles.mutedLineClass}>{describeError(stopMutation.error, copy.stopFailed)}</span>
        ) : null}
      </div>

      <p className={styles.summaryTextClass}>{selectedTask.summary?.trim() || copy.noSummary}</p>
    </>
  ) : null;

  const detailStreamBody = streamQuery.isLoading ? (
    <ProgressiveRegionSkeleton variant="detail" label={copy.loading} className={styles.loadingRegionClass} />
  ) : streamQuery.isError ? (
    <VStateSurface
      fill
      className={styles.emptyStateClass}
      title={copy.loadStreamFailed}
      tone="error"
    >
      {describeError(streamQuery.error, copy.loadStreamFailed)}
    </VStateSurface>
  ) : selectedTask ? (
    <ChatReadOnlySessionWorkspace
      assistant={{ displayName: selectedTask.title || shortId(selectedTask.taskId) }}
      defaultFileContext=""
      detail={streamQuery.data}
      emptyLabel={copy.streamEmpty}
      lang={lang}
      live={selectedIsLive}
      loading={streamQuery.isLoading}
      loadingLabel={copy.loading}
      sessionId={selectedChildSessionId}
      user={{ displayName: copy.userLabel }}
    />
  ) : null;

  const detailPaneContent = initialLoad ? (
    <ProgressiveRegionSkeleton variant="detail" label={copy.loading} className={styles.loadingRegionClass} />
  ) : !selectedTask ? (
    <VStateSurface
      fill
      className={styles.emptyStateClass}
      title={requestedTaskId && detailQuery.isError ? copy.loadFailed : copy.selectTask}
      tone={requestedTaskId && detailQuery.isError ? "error" : "empty"}
    >
      {requestedTaskId && detailQuery.isError ? describeError(detailQuery.error, copy.loadFailed) : null}
    </VStateSurface>
  ) : selectedChildSessionId ? (
    // Child-session tasks embed the real transcript (ZCode subagent-session
    // shape: main transcript renderer + readOnly); the stream area owns the
    // remaining height and scrolls itself so the head never moves.
    <div className={styles.detailStreamLayoutClass}>
      <div className={styles.detailStreamHeadClass}>{detailHead}</div>
      <section className={styles.detailStreamBodyClass} aria-label={copy.conversationStream}>
        {detailStreamBody}
      </section>
    </div>
  ) : (
    <>
      {detailHead}

      {selectedTask.outputPath ? (
        <code className={styles.monoCodeClass}>{copy.outputPath}: {selectedTask.outputPath}</code>
      ) : null}

      {selectedDetailExtras && Number(selectedDetailExtras.pendingMessageCount ?? 0) > 0 ? (
        <p className={styles.mutedLineClass}>
          {copy.pendingMessages}: {selectedDetailExtras.pendingMessageCount}
        </p>
      ) : null}

      {(selectedDetailExtras?.timeline?.length ?? 0) > 0 ? (
        <section className={styles.timelineSectionClass} aria-label={copy.timeline}>
          <div className={styles.taskSectionHeaderClass}>
            <h3 className={styles.taskSectionTitleClass}>{copy.timeline}</h3>
            <span className={styles.taskSectionCountClass}>{selectedDetailExtras!.timeline!.length}</span>
          </div>
          {selectedDetailExtras!.timeline!.map((item, index) => (
            <div className={styles.timelineRowClass} key={`${item.at ?? "at"}-${index}`}>
              <span className={styles.mutedLineClass}>{formatRelativeTime(String(item.at || ""), lang)}</span>
              <span className={styles.timelineLabelClass}>
                {String(item.label || item.status || "-")}
              </span>
            </div>
          ))}
        </section>
      ) : null}
    </>
  );

  return (
    <>
      <VListDetailPage
      ariaLabel={copy.title}
      className={styles.routeClass}
      headerClassName={styles.headerClass}
      workspaceClassName={styles.workspaceClass}
      columnsClassName=""
      layoutId={WORKBENCH_LAYOUT_IDS.auxConversations}
      data-vui-domain-recipe="aux-conversations-workbench"
      title={copy.title}
      actions={initialLoad ? undefined : (
        <VActionGroup ariaLabel={copy.kind} className={styles.headerActionsClass}>
          <div className={styles.kindFilterClass}>
            <span className={styles.kindFilterLabelClass}>{copy.kind}</span>
            <VSelect
              aria-label={copy.kind}
              selectedKey={kindFilter}
              options={kindOptions}
              placeholder={copy.allKinds}
              onSelectionChange={(key) => setKindFilter(String(key) || ALL_KIND_KEY)}
            />
          </div>
          <VIconButton
            label={copy.refresh}
            className={styles.iconButtonClass}
            icon={<RefreshCw size={16} />}
            onPress={() => {
              void listQuery.refetch();
            }}
          />
        </VActionGroup>
      )}
      list={(
        <VSurface as="section" ariaLabel={copy.taskList} className={styles.taskPaneClass} elevation="panel" padding="none" tone="rail">
          <div className={styles.panelHeaderClass}>
            <div>
              <p className={styles.eyebrowClass}>{copy.taskList}</p>
              {initialLoad ? null : (
                <strong className={styles.panelCountClass}>{runningTasks.length + endedTotal}</strong>
              )}
            </div>
          </div>
          <div className={styles.taskListClass}>
            {listPaneContent}
          </div>
        </VSurface>
      )}
      detail={(
        <VSurface as="section" ariaLabel={copy.detail} className={styles.detailPaneClass} elevation="panel" padding="compact" tone="panel">
          {detailPaneContent}
        </VSurface>
      )}
      />
      <VConfirmDialog
        open={Boolean(stopTargetId)}
        onOpenChange={(open) => {
          if (!open) {
            setStopTargetId("");
          }
        }}
        tone="danger"
        title={copy.stopConfirmTitle}
        description={stopTargetTask ? stopTargetTask.title : copy.stopConfirmDescription}
        confirmLabel={copy.stopTask}
        cancelLabel={lang === "zh" ? "取消" : "Cancel"}
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
  onSelect,
  stopLabel,
  onAskStop,
}: {
  task: RuntimeTaskCard;
  lang: "zh" | "en";
  selected: boolean;
  onSelect: () => void;
  /** Present only on running rows; ended rows carry no inline actions. */
  stopLabel?: string;
  onAskStop?: () => void;
}) {
  const { Icon, spin } = auxTaskStatusIcon(task.status);
  // Directory rows never tick seconds: ended rows age from endedAt, live rows
  // from startedAt (ZCode SubagentDirectorySidePane.tsx:72).
  const timestamp = String(task.endedAt || "").trim() || task.startedAt;
  const body = (
    <>
      <span className={styles.taskRowIconClass} aria-hidden="true">
        <Icon size={16} className={spin ? styles.taskRowIconSpinClass : undefined} />
      </span>
      <span className={styles.taskRowMainClass}>
        <span className={styles.taskRowTopClass}>
          <strong className={styles.taskRowTitleClass} title={task.title}>
            {task.title || task.taskId}
          </strong>
          <span className={styles.taskRowStatusWordClass}>{auxTaskStatusLabel(task.status, lang)}</span>
        </span>
        <span className={styles.taskRowMetaClass}>
          <span className={styles.taskRowKindClass}>{auxTaskKindLabel(task.kind, lang)}</span>
          {task.summary?.trim() ? (
            <span className={styles.taskRowSummaryClass} title={task.summary}>
              {task.summary}
            </span>
          ) : null}
        </span>
      </span>
      <span className={styles.taskRowTimeClass}>{formatRelativeTime(timestamp, lang)}</span>
    </>
  );

  if (!onAskStop) {
    return (
      <VNativeButton
        type="button"
        className={selected ? `${styles.taskRowClass} ${styles.taskRowSelectedClass}` : styles.taskRowClass}
        onClick={onSelect}
        aria-pressed={selected}
      >
        {body}
      </VNativeButton>
    );
  }

  // A running row holds both "open detail" and "stop": a whole-row button
  // would nest two buttons, so a transparent sibling overlay takes the select
  // hit while the stop button stays an independent layer that stops
  // propagation (ZCode ConversationStatusPanel.tsx:1410-1443).
  return (
    <div
      className={
        selected ? `${styles.taskRowLiveClass} ${styles.taskRowSelectedClass}` : styles.taskRowLiveClass
      }
    >
      <VNativeButton
        type="button"
        className={styles.taskRowOverlayClass}
        onClick={onSelect}
        aria-pressed={selected}
        aria-label={task.title || task.taskId}
      />
      <div className={styles.taskRowContentClass}>{body}</div>
      <VNativeButton
        type="button"
        className={styles.taskRowStopClass}
        aria-label={stopLabel}
        onClick={(event) => {
          event.stopPropagation();
          onAskStop();
        }}
      >
        <StopCircle size={14} aria-hidden="true" />
      </VNativeButton>
    </div>
  );
}
