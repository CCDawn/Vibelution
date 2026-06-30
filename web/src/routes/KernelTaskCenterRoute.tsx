import { useQuery } from "@tanstack/react-query";
import { Activity, Boxes, RefreshCw, Router, ShieldCheck } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import { getKernelTaskTimeline, listKernelTasks, selectKernelTaskId } from "../api/kernel";
import { queryKeys } from "../api/queryKeys";
import type { KernelDelivery, KernelTask, KernelTimelineItem } from "../api/types";
import { VButton, VIconButton, VRouteHeader, VSelect } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";

const ALL_STATUS_KEY = "all";
const STATUS_OPTIONS = ["queued", "running", "succeeded", "blocked", "failed", "cancelled"];

const routeClass = "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] bg-[var(--surface-page)]";
const headerClass = "mx-2.5 mt-2 min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-gradient-route-soft),color-mix(in_srgb,var(--surface-panel)_86%,transparent)] shadow-[var(--vui-shadow-hairline)]";
const headerActionsClass = "flex items-center justify-end gap-2 max-[720px]:items-stretch max-[720px]:flex-col";
const statusFilterClass = "flex min-w-[210px] items-center gap-[7px] text-[0.8rem] text-vui-fg-secondary";
const statusFilterLabelClass = "whitespace-nowrap text-[var(--vui-font-xs)] font-bold";
const iconButtonClass = "h-[34px] w-[34px] min-h-[34px] rounded-lg border border-vui-border-soft bg-[var(--surface-card)] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-vui-fg-primary";
const workspaceClass = "grid min-h-0 grid-cols-[minmax(320px,420px)_minmax(0,1fr)] gap-2 px-2.5 pb-2.5 pt-2 max-[1120px]:grid-cols-1 max-[720px]:p-2";
const paneClass = "min-h-0 rounded-lg border border-vui-border-soft bg-[var(--surface-panel)]";
const taskPaneClass = `${paneClass} grid grid-rows-[auto_minmax(0,1fr)]`;
const detailPaneClass = `${paneClass} grid content-start gap-2 overflow-auto p-2`;
const panelHeaderClass = "flex items-center justify-between gap-2 border-b border-vui-border-soft p-2";
const eyebrowClass = "m-0 mb-0.5 text-[var(--vui-font-xs)] font-bold uppercase tracking-[0.08em] text-vui-fg-tertiary";
const panelCountClass = "text-base text-vui-fg-primary";
const taskListClass = "grid min-h-0 content-start gap-[7px] overflow-auto p-2 max-[1120px]:max-h-[min(38vh,320px)]";
const taskRowClass = "grid w-full gap-1.5 rounded-lg border border-vui-border-soft bg-[var(--surface-panel-muted)] p-2 text-left text-vui-fg-primary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-strong)]";
const taskRowSelectedClass = "border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[var(--surface-active-neutral)] shadow-[var(--vui-shadow-inset-accent)]";
const taskRowTopClass = "flex items-center justify-between gap-2";
const taskRowTitleClass = "min-w-0 truncate";
const taskRowMetaClass = "grid gap-[3px] text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const monoCodeClass = "break-words text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const detailHeaderClass = "flex items-center justify-between gap-2 rounded-lg border border-vui-border-soft bg-[var(--surface-card)] p-2";
const detailTitleClass = "m-0 text-base text-vui-fg-primary";
const summaryGridClass = "grid grid-cols-4 gap-2 max-[1120px]:grid-cols-2 max-[720px]:grid-cols-1";
const metricClass = "flex min-w-0 items-center gap-2 rounded-lg border border-vui-border-soft bg-[var(--surface-card-subtle)] p-2";
const metricIconClass = "inline-flex text-[var(--accent-cool)]";
const metricBodyClass = "grid min-w-0 gap-0.5";
const metricLabelClass = "text-[var(--vui-font-xs)] uppercase tracking-[0.06em] text-vui-fg-tertiary";
const metricValueClass = "min-w-0 truncate text-[var(--vui-font-xs)] text-vui-fg-primary";
const selectionNoticeClass = "rounded-lg border border-[color-mix(in_srgb,var(--state-warning)_28%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_8%,transparent)] px-2 py-[7px] text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const sectionClass = "grid gap-[7px] rounded-lg border border-vui-border-soft bg-[var(--surface-card)] p-2";
const sectionHeaderClass = "flex items-center justify-between gap-2";
const sectionTitleClass = "m-0 text-[0.9rem] text-vui-fg-primary";
const sectionCountClass = "text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const deliveryGridClass = "grid gap-1.5";
const deliveryRowClass = "grid gap-1 rounded-lg bg-[var(--surface-card-subtle)] p-[7px]";
const deliveryRowTopClass = "flex items-center justify-between gap-2";
const mutedLineClass = "text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const warningLineClass = "text-[var(--vui-font-xs)] not-italic leading-[1.35] text-[var(--state-warning)]";
const timelineListClass = "grid gap-1.5";
const timelineRowClass = "grid grid-cols-[14px_minmax(0,1fr)] gap-[7px] rounded-lg bg-[var(--surface-card-subtle)] p-2";
const timelineDotClass = "mt-[5px] h-[9px] w-[9px] rounded-full bg-vui-fg-tertiary";
const timelineTitleClass = "flex items-center justify-between gap-2";
const timelineKindClass = "text-[var(--vui-font-xs)] text-vui-fg-primary";
const timelineSummaryClass = "m-0 my-[3px] text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const chipsClass = "mt-[5px] flex flex-wrap gap-[5px]";
const chipCodeClass = "rounded-full border border-vui-border-soft bg-[var(--surface-code)] px-1.5 py-[3px] text-[var(--vui-font-xs)] text-vui-fg-tertiary";
const refListClass = "mt-[5px] flex flex-wrap gap-[5px]";
const emptyInlineClass = "text-[var(--vui-font-xs)] leading-[1.35] text-vui-fg-secondary";
const statusPillBaseClass = "inline-flex min-h-[22px] items-center whitespace-nowrap rounded-full border border-vui-border-soft px-[7px] text-[var(--vui-font-xs)]";
const emptyStateClass = "grid min-h-16 content-start gap-1 rounded-lg border border-dashed border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-card-subtle)_74%,transparent)] p-2.5";
const emptyStateLoadingClass = "border-solid";
const emptyStateErrorClass = "border-[color-mix(in_srgb,var(--state-error)_32%,transparent)]";
const emptyTitleClass = "text-[0.88rem] text-vui-fg-primary";
const emptyDetailClass = "text-[var(--vui-font-xs)] text-vui-fg-secondary";

const COPY = {
  zh: {
    title: "Kernel Task Center",
    subtitle: "TaskLedger / WorkRun / Outcome",
    taskList: "任务",
    detail: "详情",
    deliveries: "投递",
    timeline: "时间线",
    projectionRefs: "投影引用",
    runtimeRefs: "运行证据",
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
    loading: "读取中",
    loadFailed: "读取失败",
    noTimeline: "选择一个任务查看链路",
  },
  en: {
    title: "Kernel Task Center",
    subtitle: "TaskLedger / WorkRun / Outcome",
    taskList: "Tasks",
    detail: "Detail",
    deliveries: "Deliveries",
    timeline: "Timeline",
    projectionRefs: "Projection refs",
    runtimeRefs: "Runtime evidence",
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

  return (
    <div className={routeClass}>
      <VRouteHeader
        className={headerClass}
        eyebrow="Kernel"
        title={copy.title}
        meta={copy.subtitle}
        actions={(
          <div className={headerActionsClass}>
            <div className={statusFilterClass}>
              <span className={statusFilterLabelClass}>{copy.status}</span>
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
              className={iconButtonClass}
              icon={<RefreshCw size={16} />}
              onPress={() => {
                taskQuery.refetch();
                if (selectedTaskId) {
                  timelineQuery.refetch();
                }
              }}
            />
          </div>
        )}
      />

      <main className={workspaceClass}>
        <section className={taskPaneClass} aria-label={copy.taskList}>
          <div className={panelHeaderClass}>
            <div>
              <p className={eyebrowClass}>{copy.taskList}</p>
              <strong className={panelCountClass}>{tasks.length}</strong>
            </div>
          </div>
          <div className={taskListClass}>
            {taskQuery.isError ? (
              <EmptyState label={copy.loadFailed} detail={describeError(taskQuery.error, copy.loadFailed)} tone="error" />
            ) : taskQuery.isLoading ? (
              <EmptyState label={copy.loading} detail={copy.taskList} tone="loading" />
            ) : tasks.length === 0 ? (
              <EmptyState label={copy.noTasks} detail={copy.taskList} />
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
            )}
          </div>
        </section>

        <section className={detailPaneClass} aria-label={copy.detail}>
          {!selectedTaskId ? (
            <EmptyState label={copy.noTimeline} detail={copy.detail} />
          ) : timelineQuery.isError ? (
            <EmptyState label={copy.loadFailed} detail={describeError(timelineQuery.error, copy.loadFailed)} tone="error" />
          ) : timelineQuery.isLoading || !timeline ? (
            <EmptyState label={copy.loading} detail={selectedTaskId} tone="loading" />
          ) : (
            <>
              <div className={detailHeaderClass}>
                <div>
                  <p className={eyebrowClass}>{copy.detail}</p>
                  <h2 className={detailTitleClass}>{shortId(timeline.taskId)}</h2>
                </div>
                <StatusPill status={timeline.task.status} />
              </div>

              <div className={summaryGridClass}>
                <Metric label={copy.factAuthority} value={timeline.readModel.truthSource} icon={<ShieldCheck size={15} />} />
                <Metric
                  label={copy.viewType}
                  value={timeline.readModel.projection ? copy.projectionView : copy.directView}
                  icon={<ShieldCheck size={15} />}
                />
                <Metric label={copy.event} value={shortId(timeline.event.eventId)} icon={<Router size={15} />} />
                <Metric label={copy.workRun} value={shortId(timeline.execution.workRunId)} icon={<Activity size={15} />} />
                <Metric label={copy.outcome} value={timeline.outcome.status || "-"} icon={<Boxes size={15} />} />
              </div>

              {selectedTaskHiddenFromList ? <div className={selectionNoticeClass}>{copy.taskHidden}</div> : null}

              <section className={sectionClass}>
                <div className={sectionHeaderClass}>
                  <h3 className={sectionTitleClass}>{copy.deliveries}</h3>
                  <span className={sectionCountClass}>{timeline.deliveries.length}</span>
                </div>
                <div className={deliveryGridClass}>
                  {timeline.deliveries.map((delivery) => (
                    <DeliveryRow key={`${delivery.targetAgentId}-${delivery.inboxMessageId}`} delivery={delivery} copy={copy} />
                  ))}
                </div>
              </section>

              <section className={sectionClass}>
                <div className={sectionHeaderClass}>
                  <h3 className={sectionTitleClass}>{copy.projectionRefs}</h3>
                  <span className={sectionCountClass}>{timeline.projectionRefs.length}</span>
                </div>
                <RefList refs={timeline.projectionRefs} />
              </section>

              <section className={sectionClass}>
                <div className={sectionHeaderClass}>
                  <h3 className={sectionTitleClass}>{copy.runtimeRefs}</h3>
                  <span className={sectionCountClass}>{timeline.runtimeEvidenceRefs.length}</span>
                </div>
                <RefList refs={timeline.runtimeEvidenceRefs} />
              </section>

              <section className={sectionClass}>
                <div className={sectionHeaderClass}>
                  <h3 className={sectionTitleClass}>{copy.timeline}</h3>
                  <span className={sectionCountClass}>{timeline.timeline.length}</span>
                </div>
                <div className={timelineListClass}>
                  {timeline.timeline.map((item, index) => (
                    <TimelineRow key={`${item.kind}-${item.at}-${index}`} item={item} />
                  ))}
                </div>
              </section>
            </>
          )}
        </section>
      </main>
    </div>
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
      className={selected ? `${taskRowClass} ${taskRowSelectedClass}` : taskRowClass}
      onClick={onSelect}
    >
      <span className={taskRowTopClass}>
        <strong className={taskRowTitleClass}>{task.goal || shortId(task.taskId)}</strong>
        <StatusPill status={task.status} />
      </span>
      <span className={taskRowMetaClass}>
        <span>{copy.assigned}: {(task.assignedAgentIds ?? []).map(shortId).join(", ") || "-"}</span>
        <span>{copy.updated}: {formatTime(task.updatedAt)}</span>
      </span>
      <code className={monoCodeClass}>{task.taskId}</code>
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
    <div className={deliveryRowClass}>
      <div className={deliveryRowTopClass}>
        <strong>{shortId(delivery.targetAgentId)}</strong>
        <StatusPill status={delivery.status} />
      </div>
      <span className={mutedLineClass}>{copy.inbox}: {shortId(delivery.inboxMessageId)}</span>
      <span className={mutedLineClass}>{copy.wake}: {delivery.wake?.wakeStatus || "-"}</span>
      {delivery.reason ? <em className={warningLineClass}>{delivery.reason}</em> : null}
    </div>
  );
}

function TimelineRow({ item }: { item: KernelTimelineItem }) {
  return (
    <div className={timelineRowClass}>
      <span className={`${timelineDotClass} ${statusTone(item.status)}`} />
      <div>
        <div className={timelineTitleClass}>
          <strong className={timelineKindClass}>{item.kind}</strong>
          <StatusPill status={item.status} />
        </div>
        <p className={timelineSummaryClass}>{item.summary}</p>
        <span className={mutedLineClass}>{formatTime(item.at)}</span>
        {item.refs.length > 0 ? (
          <div className={chipsClass}>
            {item.refs.map((ref) => (
              <code className={chipCodeClass} key={`${item.kind}-${ref.kind}-${ref.id}`}>{ref.kind}:{shortId(ref.id)}</code>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function RefList({ refs }: { refs: Array<Record<string, unknown>> }) {
  if (refs.length === 0) {
    return <div className={emptyInlineClass}>-</div>;
  }
  return (
    <div className={refListClass}>
      {refs.map((ref, index) => {
        const sourceRef = ref.sourceRef && typeof ref.sourceRef === "object"
          ? ref.sourceRef as Record<string, unknown>
          : null;
        const route = String(ref.canonicalEditRoute ?? sourceRef?.canonicalEditRoute ?? "");
        const owner = String(ref.sourceOwner ?? sourceRef?.owner ?? "");
        return (
          <code className={chipCodeClass} key={`${String(ref.kind ?? "ref")}-${String(ref.id ?? index)}`} title={route || owner}>
            {String(ref.kind ?? "ref")}:{shortId(String(ref.id ?? ref.eventCode ?? ref.taskId ?? ""))}
            {owner ? ` -> ${owner}` : ""}
          </code>
        );
      })}
    </div>
  );
}

function Metric({ label, value, icon }: { label: string; value: string; icon: ReactNode }) {
  return (
    <div className={metricClass}>
      <span className={metricIconClass}>{icon}</span>
      <div className={metricBodyClass}>
        <small className={metricLabelClass}>{label}</small>
        <strong className={metricValueClass}>{value || "-"}</strong>
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  return <span className={`${statusPillBaseClass} ${statusTone(status)}`}>{status || "unknown"}</span>;
}

function EmptyState({
  label,
  detail,
  tone = "idle",
}: {
  label: string;
  detail: string;
  tone?: "idle" | "loading" | "error";
}) {
  const toneClass = tone === "error" ? emptyStateErrorClass : tone === "loading" ? emptyStateLoadingClass : "";
  return (
    <div className={`${emptyStateClass} ${toneClass}`} data-tone={tone}>
      <strong className={emptyTitleClass}>{label}</strong>
      <span className={emptyDetailClass}>{detail}</span>
    </div>
  );
}
