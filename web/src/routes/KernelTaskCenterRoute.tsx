import "../design/route-css/workbench-secondary.tailwind.css";

import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import { getKernelTaskTimeline, listKernelTasks, selectKernelTaskId } from "../api/kernel";
import { queryKeys } from "../api/queryKeys";
import type { KernelDelivery, KernelTask, KernelTimelineItem } from "../api/types";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { VActionGroup, VButton, VIconButton, VListDetailPage, VMetricStrip, VSelect, VStateSurface, VSurface } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";
import styles from "./KernelTaskCenterRoute.styles";

const ALL_STATUS_KEY = "all";
const STATUS_OPTIONS = ["queued", "running", "succeeded", "blocked", "failed", "cancelled"];


const COPY = {
  zh: {
    title: "Kernel Task Center",
    subtitle: "TaskLedger / WorkRun / Outcome",
    taskList: "任务",
    detail: "详情",
    taskChain: "任务链路",
    deliveryResult: "投递结果",
    lifecycleTimeline: "生命周期",
    projectionRefs: "投影引用",
    evidenceRefs: "证据引用",
    refresh: "刷新",
    status: "状态",
    allStatus: "全部状态",
    updated: "更新",
    created: "创建",
    assigned: "目标 Agent",
    outcome: "Outcome",
    workRun: "WorkRun",
    event: "Event",
    wake: "Wake",
    inbox: "Inbox",
    readModel: "Read model",
    factAuthority: "事实权威",
    viewType: "当前视图",
    projectionView: "Read model / Projection",
    directView: "Direct",
    taskHidden: "当前任务不在左侧列表中，可能被状态筛选或数量限制隐藏。",
    noTasks: "暂无 Kernel 任务",
    noMatchingTasks: "没有符合筛选条件的任务",
    loading: "读取中",
    loadFailed: "读取失败",
    noTimeline: "选择一个任务查看链路",
  },
  en: {
    title: "Kernel Task Center",
    subtitle: "TaskLedger / WorkRun / Outcome",
    taskList: "Tasks",
    detail: "Detail",
    taskChain: "Task chain",
    deliveryResult: "Delivery result",
    lifecycleTimeline: "Lifecycle",
    projectionRefs: "Projection refs",
    evidenceRefs: "Evidence refs",
    refresh: "Refresh",
    status: "Status",
    allStatus: "All status",
    updated: "Updated",
    created: "Created",
    assigned: "Target agents",
    outcome: "Outcome",
    workRun: "WorkRun",
    event: "Event",
    wake: "Wake",
    inbox: "Inbox",
    readModel: "Read model",
    factAuthority: "Fact authority",
    viewType: "View",
    projectionView: "Read model / Projection",
    directView: "Direct",
    taskHidden: "This task is not in the left list; it may be hidden by status filtering or list limits.",
    noTasks: "No Kernel tasks",
    noMatchingTasks: "No tasks match this filter",
    loading: "Loading",
    loadFailed: "Load failed",
    noTimeline: "Select a task to inspect the chain",
  },
} as const;

function statusTone(status: string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "succeeded" || normalized === "delivered") {
    return "border-[color-mix(in_srgb,var(--state-success)_30%,transparent)] text-[var(--state-success)]";
  }
  if (normalized === "running" || normalized === "queued") {
    return "border-[color-mix(in_srgb,var(--accent-cool)_30%,transparent)] text-[var(--accent-cool)]";
  }
  if (normalized === "blocked" || normalized === "failed" || normalized === "cancelled") {
    return "border-[color-mix(in_srgb,var(--state-error)_34%,transparent)] text-[var(--state-error)]";
  }
  return "text-vui-fg-secondary";
}

function shortId(value: string) {
  const text = String(value || "").trim();
  if (text.length <= 18) {
    return text || "-";
  }
  return `${text.slice(0, 10)}…${text.slice(-6)}`;
}

function formatTime(value: string) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function describeError(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function KernelTaskCenterRoute() {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTaskId = searchParams.get("taskId") ?? "";
  const [status, setStatus] = useState("");
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
  const taskQuery = useQuery({
    queryKey: queryKeys.kernelTasks(status, 120),
    queryFn: () => listKernelTasks(status, 120),
  });
  const tasks = taskQuery.data?.tasks ?? [];
  const selectedTaskId = useMemo(() => selectKernelTaskId(tasks, requestedTaskId), [requestedTaskId, tasks]);
  const selectedTask = useMemo(
    () => tasks.find((task) => task.taskId === selectedTaskId) ?? null,
    [selectedTaskId, tasks],
  );
  const selectedTaskHiddenFromList = Boolean(
    selectedTaskId && !selectedTask && !taskQuery.isLoading && !taskQuery.isError,
  );

  const timelineQuery = useQuery({
    queryKey: queryKeys.kernelTaskTimeline(selectedTaskId),
    queryFn: () => getKernelTaskTimeline(selectedTaskId),
    enabled: Boolean(selectedTaskId),
  });
  const timeline = timelineQuery.data;
  const statusOptions = useMemo(
    () => [
      { id: ALL_STATUS_KEY, label: copy.allStatus },
      ...STATUS_OPTIONS.map((option) => ({ id: option, label: option })),
    ],
    [copy.allStatus],
  );
  const taskPaneContent = taskQuery.isError ? (
    <VStateSurface className={styles.emptyStateClass} title={copy.loadFailed} tone="error">
      {describeError(taskQuery.error, copy.loadFailed)}
    </VStateSurface>
  ) : taskQuery.isLoading ? (
    <VStateSurface className={styles.emptyStateClass} title={copy.loading} tone="loading">
      {copy.taskList}
    </VStateSurface>
  ) : tasks.length === 0 ? (
    <VStateSurface className={styles.emptyStateClass} title={status ? copy.noMatchingTasks : copy.noTasks} tone="empty">
      {copy.taskList}
    </VStateSurface>
  ) : (
    tasks.map((task) => (
      <TaskRow
        key={task.taskId}
        task={task}
        selected={task.taskId === selectedTaskId}
        onSelect={() => updateSelectedTaskId(task.taskId)}
        copy={copy}
      />
    ))
  );
  const timelinePaneContent = !selectedTaskId ? (
    <VStateSurface className={styles.emptyStateClass} title={copy.noTimeline} tone="empty">
      {copy.detail}
    </VStateSurface>
  ) : timelineQuery.isError ? (
    <VStateSurface className={styles.emptyStateClass} title={copy.loadFailed} tone="error">
      {describeError(timelineQuery.error, copy.loadFailed)}
    </VStateSurface>
  ) : timelineQuery.isLoading || !timeline ? (
    <VStateSurface className={styles.emptyStateClass} title={copy.loading} tone="loading">
      {selectedTaskId}
    </VStateSurface>
  ) : (
    <>
      <div className={styles.detailContentClass}>
        <div className={styles.detailHeaderClass}>
          <div className={styles.detailTitleWrapClass}>
            <p className={styles.eyebrowClass}>{copy.detail}</p>
            <h2 className={styles.detailTitleClass}>{shortId(timeline.taskId)}</h2>
          </div>
          <StatusPill status={timeline.task.status} />
        </div>

        <VMetricStrip
          ariaLabel={copy.detail}
          className={styles.summaryGridClass}
          metrics={[
            { id: "authority", label: copy.factAuthority, value: timeline.readModel.truthSource || "-", tone: "info" },
            { id: "view", label: copy.viewType, value: timeline.readModel.projection ? copy.projectionView : copy.directView },
            { id: "event", label: copy.event, value: shortId(timeline.event.eventId) },
            { id: "work-run", label: copy.workRun, value: shortId(timeline.execution.workRunId) },
            { id: "outcome", label: copy.outcome, value: timeline.outcome.status || "-" },
          ]}
        />

        {selectedTaskHiddenFromList ? <div className={styles.selectionNoticeClass}>{copy.taskHidden}</div> : null}

        <section className={styles.ledgerSectionClass} aria-label={copy.taskChain}>
          <div className={styles.sectionHeaderClass}>
            <h3 className={styles.sectionTitleClass}>{copy.taskChain}</h3>
            <span className={styles.sectionCountClass}>3</span>
          </div>
          <div className={styles.ledgerFlowClass}>
            <LedgerBucket title={copy.deliveryResult} count={timeline.deliveries.length}>
              <div className={styles.deliveryGridClass}>
                {timeline.deliveries.map((delivery) => (
                  <DeliveryRow key={`${delivery.targetAgentId}-${delivery.inboxMessageId}`} delivery={delivery} copy={copy} />
                ))}
              </div>
            </LedgerBucket>
            <LedgerBucket title={copy.projectionRefs} count={timeline.projectionRefs.length}>
              <RefList refs={timeline.projectionRefs} />
            </LedgerBucket>
            <LedgerBucket title={copy.evidenceRefs} count={timeline.runtimeEvidenceRefs.length}>
              <RefList refs={timeline.runtimeEvidenceRefs} className={styles.evidenceRefListClass} />
            </LedgerBucket>
          </div>
        </section>
      </div>

      <section className={styles.lifecycleSectionClass}>
        <div className={styles.sectionHeaderClass}>
          <h3 className={styles.sectionTitleClass}>{copy.lifecycleTimeline}</h3>
          <span className={styles.sectionCountClass}>{timeline.timeline.length}</span>
        </div>
        <div className={styles.lifecycleTimelineClass}>
          {timeline.timeline.map((item, index) => (
            <LifecycleRow key={`${item.kind}-${item.at}-${index}`} item={item} />
          ))}
        </div>
      </section>
    </>
  );

  return (
    <VListDetailPage
      ariaLabel={copy.title}
      className={styles.routeClass}
      headerClassName={styles.headerClass}
      workspaceClassName={styles.workspaceClass}
      columnsClassName=""
      layoutId={WORKBENCH_LAYOUT_IDS.kernelTaskCenter}
      eyebrow="Kernel"
      title={copy.title}
      meta={copy.subtitle}
      actions={(
        <VActionGroup ariaLabel={copy.status} className={styles.headerActionsClass}>
          <div className={styles.statusFilterClass}>
            <span className={styles.statusFilterLabelClass}>{copy.status}</span>
            <VSelect
              aria-label={copy.status}
              selectedKey={status || ALL_STATUS_KEY}
              options={statusOptions}
              placeholder={status || copy.allStatus}
              onSelectionChange={(key) => setStatus(String(key) === ALL_STATUS_KEY ? "" : String(key))}
            />
          </div>
          <VIconButton
            label={copy.refresh}
            className={styles.iconButtonClass}
            icon={<RefreshCw size={16} />}
            onPress={() => {
              taskQuery.refetch();
              if (selectedTaskId) {
                timelineQuery.refetch();
              }
            }}
          />
        </VActionGroup>
      )}
      list={(
        <VSurface as="section" ariaLabel={copy.taskList} className={styles.taskPaneClass} elevation="panel" padding="none" tone="rail">
          <div className={styles.panelHeaderClass}>
            <div>
              <p className={styles.eyebrowClass}>{copy.taskList}</p>
              <strong className={styles.panelCountClass}>{tasks.length}</strong>
            </div>
          </div>
          <div className={styles.taskListClass}>
            {taskPaneContent}
          </div>
        </VSurface>
      )}
      detail={(
        <VSurface as="section" ariaLabel={copy.detail} className={styles.detailPaneClass} elevation="panel" padding="compact" tone="panel">
          {timelinePaneContent}
        </VSurface>
      )}
    />
  );
}

function TaskRow({
  task,
  selected,
  onSelect,
  copy,
}: {
  task: KernelTask;
  selected: boolean;
  onSelect: () => void;
  copy: (typeof COPY)["zh"] | (typeof COPY)["en"];
}) {
  return (
    <VButton
      type="button"
      className={selected ? `${styles.taskRowClass} ${styles.taskRowSelectedClass}` : styles.taskRowClass}
      onClick={onSelect}
    >
      <span className={styles.taskRowTopClass}>
        <strong className={styles.taskRowTitleClass}>{task.goal || shortId(task.taskId)}</strong>
        <StatusPill status={task.status} />
      </span>
      <span className={styles.taskRowMetaClass}>
        <span>{copy.assigned}: {(task.assignedAgentIds ?? []).map(shortId).join(", ") || "-"}</span>
        <span>{copy.updated}: {formatTime(task.updatedAt)}</span>
      </span>
      <code className={styles.monoCodeClass}>{task.taskId}</code>
    </VButton>
  );
}

function DeliveryRow({
  delivery,
  copy,
}: {
  delivery: KernelDelivery;
  copy: (typeof COPY)["zh"] | (typeof COPY)["en"];
}) {
  return (
    <div className={styles.deliveryRowClass}>
      <div className={styles.deliveryRowTopClass}>
        <strong>{shortId(delivery.targetAgentId)}</strong>
        <StatusPill status={delivery.status} />
      </div>
      <span className={styles.mutedLineClass}>{copy.inbox}: {shortId(delivery.inboxMessageId)}</span>
      <span className={styles.mutedLineClass}>{copy.wake}: {delivery.wake?.wakeStatus || "-"}</span>
      {delivery.reason ? <em className={styles.warningLineClass}>{delivery.reason}</em> : null}
    </div>
  );
}

function LedgerBucket({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <section className={styles.ledgerBucketClass}>
      <div className={styles.sectionHeaderClass}>
        <h3 className={styles.sectionTitleClass}>{title}</h3>
        <span className={styles.sectionCountClass}>{count}</span>
      </div>
      {children}
    </section>
  );
}

function LifecycleRow({ item }: { item: KernelTimelineItem }) {
  return (
    <div className={styles.lifecycleRowClass}>
      <span className={`${styles.lifecycleDotClass} ${statusTone(item.status)}`} />
      <div>
        <div className={styles.lifecycleTitleClass}>
          <strong className={styles.lifecycleKindClass}>{item.kind}</strong>
          <StatusPill status={item.status} />
        </div>
        <p className={styles.lifecycleSummaryClass}>{item.summary}</p>
        <span className={styles.mutedLineClass}>{formatTime(item.at)}</span>
        {item.refs.length > 0 ? (
          <div className={styles.chipsClass}>
            {item.refs.map((ref) => (
              <code className={styles.chipCodeClass} key={`${item.kind}-${ref.kind}-${ref.id}`}>{ref.kind}:{shortId(ref.id)}</code>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function RefList({
  refs,
  className = styles.refListClass,
}: {
  refs: Array<Record<string, unknown>>;
  className?: string;
}) {
  if (refs.length === 0) {
    return <div className={styles.emptyInlineClass}>-</div>;
  }
  return (
    <div className={className}>
      {refs.map((ref, index) => {
        const sourceRef = ref.sourceRef && typeof ref.sourceRef === "object"
          ? ref.sourceRef as Record<string, unknown>
          : null;
        const route = String(ref.canonicalEditRoute ?? sourceRef?.canonicalEditRoute ?? "");
        const owner = String(ref.sourceOwner ?? sourceRef?.owner ?? "");
        return (
          <code className={styles.chipCodeClass} key={`${String(ref.kind ?? "ref")}-${String(ref.id ?? index)}`} title={route || owner}>
            {String(ref.kind ?? "ref")}:{shortId(String(ref.id ?? ref.eventCode ?? ref.taskId ?? ""))}
            {owner ? ` -> ${owner}` : ""}
          </code>
        );
      })}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  return <span className={`${styles.statusPillBaseClass} ${statusTone(status)}`}>{status || "unknown"}</span>;
}
