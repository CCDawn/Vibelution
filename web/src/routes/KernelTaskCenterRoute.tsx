import { useQuery } from "@tanstack/react-query";
import { Activity, Boxes, RefreshCw, Router, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { getKernelTaskTimeline, listKernelTasks } from "../api/kernel";
import { queryKeys } from "../api/queryKeys";
import type { KernelDelivery, KernelTask, KernelTimelineItem } from "../api/types";
import { useShellI18n } from "../i18n/useShellI18n";
import styles from "./KernelTaskCenterRoute.module.css";

const STATUS_OPTIONS = ["", "queued", "running", "succeeded", "blocked", "failed", "cancelled"];

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
    truthSource: "事实源",
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
    truthSource: "Truth source",
    noTasks: "No Kernel tasks",
    loading: "Loading",
    loadFailed: "Load failed",
    noTimeline: "Select a task to inspect the chain",
  },
} as const;

function statusTone(status: string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "succeeded" || normalized === "delivered") {
    return styles.toneSuccess;
  }
  if (normalized === "running" || normalized === "queued") {
    return styles.toneActive;
  }
  if (normalized === "blocked" || normalized === "failed" || normalized === "cancelled") {
    return styles.toneError;
  }
  return styles.toneIdle;
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
  const [status, setStatus] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const taskQuery = useQuery({
    queryKey: queryKeys.kernelTasks(status, 120),
    queryFn: () => listKernelTasks(status, 120),
  });
  const tasks = taskQuery.data?.tasks ?? [];
  const selectedTask = useMemo(
    () => tasks.find((task) => task.taskId === selectedTaskId) ?? tasks[0] ?? null,
    [selectedTaskId, tasks],
  );

  useEffect(() => {
    if (!selectedTask) {
      setSelectedTaskId("");
      return;
    }
    if (selectedTask.taskId !== selectedTaskId) {
      setSelectedTaskId(selectedTask.taskId);
    }
  }, [selectedTask, selectedTaskId]);

  const timelineQuery = useQuery({
    queryKey: queryKeys.kernelTaskTimeline(selectedTaskId),
    queryFn: () => getKernelTaskTimeline(selectedTaskId),
    enabled: Boolean(selectedTaskId),
  });
  const timeline = timelineQuery.data;

  return (
    <div className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Kernel</p>
          <h1>{copy.title}</h1>
          <p>{copy.subtitle}</p>
        </div>
        <div className={styles.headerActions}>
          <label className={styles.statusFilter}>
            <span>{copy.status}</span>
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              {STATUS_OPTIONS.map((option) => (
                <option key={option || "all"} value={option}>
                  {option || copy.allStatus}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className={styles.iconButton}
            onClick={() => {
              taskQuery.refetch();
              if (selectedTaskId) {
                timelineQuery.refetch();
              }
            }}
            title={copy.refresh}
            aria-label={copy.refresh}
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </header>

      <main className={styles.workspace}>
        <section className={styles.taskPane} aria-label={copy.taskList}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.eyebrow}>{copy.taskList}</p>
              <strong>{tasks.length}</strong>
            </div>
          </div>
          <div className={styles.taskList}>
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
                  onSelect={() => setSelectedTaskId(task.taskId)}
                  copy={copy}
                />
              ))
            )}
          </div>
        </section>

        <section className={styles.detailPane} aria-label={copy.detail}>
          {!selectedTaskId ? (
            <EmptyState label={copy.noTimeline} detail={copy.detail} />
          ) : timelineQuery.isError ? (
            <EmptyState label={copy.loadFailed} detail={describeError(timelineQuery.error, copy.loadFailed)} tone="error" />
          ) : timelineQuery.isLoading || !timeline ? (
            <EmptyState label={copy.loading} detail={selectedTaskId} tone="loading" />
          ) : (
            <>
              <div className={styles.detailHeader}>
                <div>
                  <p className={styles.eyebrow}>{copy.detail}</p>
                  <h2>{shortId(timeline.taskId)}</h2>
                </div>
                <StatusPill status={timeline.task.status} />
              </div>

              <div className={styles.summaryGrid}>
                <Metric label={copy.truthSource} value={timeline.readModel.truthSource} icon={<ShieldCheck size={15} />} />
                <Metric label={copy.event} value={shortId(timeline.event.eventId)} icon={<Router size={15} />} />
                <Metric label={copy.workRun} value={shortId(timeline.execution.workRunId)} icon={<Activity size={15} />} />
                <Metric label={copy.outcome} value={timeline.outcome.status || "-"} icon={<Boxes size={15} />} />
              </div>

              <section className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h3>{copy.deliveries}</h3>
                  <span>{timeline.deliveries.length}</span>
                </div>
                <div className={styles.deliveryGrid}>
                  {timeline.deliveries.map((delivery) => (
                    <DeliveryRow key={`${delivery.targetAgentId}-${delivery.inboxMessageId}`} delivery={delivery} copy={copy} />
                  ))}
                </div>
              </section>

              <section className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h3>{copy.projectionRefs}</h3>
                  <span>{timeline.projectionRefs.length}</span>
                </div>
                <RefList refs={timeline.projectionRefs} />
              </section>

              <section className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h3>{copy.runtimeRefs}</h3>
                  <span>{timeline.runtimeEvidenceRefs.length}</span>
                </div>
                <RefList refs={timeline.runtimeEvidenceRefs} />
              </section>

              <section className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h3>{copy.timeline}</h3>
                  <span>{timeline.timeline.length}</span>
                </div>
                <div className={styles.timelineList}>
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
    <button
      type="button"
      className={selected ? `${styles.taskRow} ${styles.taskRowSelected}` : styles.taskRow}
      onClick={onSelect}
    >
      <span className={styles.taskRowTop}>
        <strong>{task.goal || shortId(task.taskId)}</strong>
        <StatusPill status={task.status} />
      </span>
      <span className={styles.taskRowMeta}>
        <span>{copy.assigned}: {(task.assignedAgentIds ?? []).map(shortId).join(", ") || "-"}</span>
        <span>{copy.updated}: {formatTime(task.updatedAt)}</span>
      </span>
      <code>{task.taskId}</code>
    </button>
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
    <div className={styles.deliveryRow}>
      <div>
        <strong>{shortId(delivery.targetAgentId)}</strong>
        <StatusPill status={delivery.status} />
      </div>
      <span>{copy.inbox}: {shortId(delivery.inboxMessageId)}</span>
      <span>{copy.wake}: {delivery.wake?.wakeStatus || "-"}</span>
      {delivery.reason ? <em>{delivery.reason}</em> : null}
    </div>
  );
}

function TimelineRow({ item }: { item: KernelTimelineItem }) {
  return (
    <div className={styles.timelineRow}>
      <span className={`${styles.timelineDot} ${statusTone(item.status)}`} />
      <div>
        <div className={styles.timelineTitle}>
          <strong>{item.kind}</strong>
          <StatusPill status={item.status} />
        </div>
        <p>{item.summary}</p>
        <span>{formatTime(item.at)}</span>
        {item.refs.length > 0 ? (
          <div className={styles.refChips}>
            {item.refs.map((ref) => (
              <code key={`${item.kind}-${ref.kind}-${ref.id}`}>{ref.kind}:{shortId(ref.id)}</code>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function RefList({ refs }: { refs: Array<Record<string, string>> }) {
  if (refs.length === 0) {
    return <div className={styles.emptyInline}>-</div>;
  }
  return (
    <div className={styles.refList}>
      {refs.map((ref, index) => (
        <code key={`${ref.kind ?? "ref"}-${ref.id ?? index}`}>
          {ref.kind ?? "ref"}:{shortId(String(ref.id ?? ref.eventCode ?? ref.taskId ?? ""))}
        </code>
      ))}
    </div>
  );
}

function Metric({ label, value, icon }: { label: string; value: string; icon: ReactNode }) {
  return (
    <div className={styles.metric}>
      <span>{icon}</span>
      <div>
        <small>{label}</small>
        <strong>{value || "-"}</strong>
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  return <span className={`${styles.statusPill} ${statusTone(status)}`}>{status || "unknown"}</span>;
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
  return (
    <div className={styles.emptyState} data-tone={tone}>
      <strong>{label}</strong>
      <span>{detail}</span>
    </div>
  );
}
