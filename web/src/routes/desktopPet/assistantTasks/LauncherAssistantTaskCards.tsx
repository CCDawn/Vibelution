import { useEffect, useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getLauncherAssistantDispatches, getLauncherAssistantStatus } from "../../../api/launcherAssistant";
import { VButton, VChip, VStateSurface, VSurface } from "../../../components/vui";
import { projectAssistantDispatchTasks, type AssistantDispatchTask } from "./assistantDispatchTasks";

type Props = {
  lang?: "zh" | "en";
  onReview: (task: AssistantDispatchTask) => void;
  onApproval: (task: AssistantDispatchTask) => void;
};

const PAGE_SIZE = 10;
const COPY = {
  zh: {
    untitled: "助理任务", label: "助理任务", scope: "这里显示助理已派出的任务。",
    states: {
      running: { label: "执行中", progress: "助理正在推进这项任务。", tone: "neutral" },
      stopping: { label: "停止中", progress: "正在停止，结束后会更新状态。", tone: "neutral" },
      waiting_user: { label: "待授权", progress: "任务正在等待授权，请到对话中处理。", tone: "warning" },
      awaiting_verification: { label: "待验收", progress: "执行已结束，还需核对实际结果。", tone: "neutral" },
      failed: { label: "执行失败", progress: "遇到了问题，可请助理分析原因。", tone: "danger" },
      stopped: { label: "已停止", progress: "这项任务已停止。", tone: "neutral" },
      unknown: { label: "状态未知", progress: "暂时无法确认任务进展。", tone: "warning" },
    },
    unknownCached: "暂时无法确认新进展，保留上次记录。", approval: "处理授权", review: "去对话核对",
    details: "详情", hideDetails: "收起详情", summary: "最近一次回执摘要", noSummary: "暂无结果摘要。",
    dispatchId: "派遣编号：", projectId: "项目编号：", nativeTaskId: "原生任务编号：", notBound: "尚未绑定",
    refresh: "刷新", unavailable: "任务状态暂不可用", retained: "保留上次记录，当前状态需重新核对。",
    noReceipts: "暂时无法读取任务，请刷新。", loading: "正在读取任务", invalid: "部分任务暂时无法读取",
    empty: "暂无助理派遣任务", more: "显示更多", showing: (count: number) => `当前显示前 ${count} 项任务。`,
    detailsLabel: (expanded: boolean, title: string) => `${expanded ? "收起" : "查看"}“${title}”详情`,
  },
  en: {
    untitled: "Assistant task", label: "Assistant tasks", scope: "Showing tasks dispatched by your assistant.",
    states: {
      running: { label: "Running", progress: "Your assistant is working on this task.", tone: "neutral" },
      stopping: { label: "Stopping", progress: "Stopping is in progress. The status will update when it ends.", tone: "neutral" },
      waiting_user: { label: "Needs authorization", progress: "The task needs authorization. Handle it in the conversation.", tone: "warning" },
      awaiting_verification: { label: "Awaiting verification", progress: "Execution has ended. The actual result still needs verification.", tone: "neutral" },
      failed: { label: "Execution failed", progress: "A problem occurred. Ask your assistant to investigate.", tone: "danger" },
      stopped: { label: "Stopped", progress: "This task has stopped.", tone: "neutral" },
      unknown: { label: "Unknown", progress: "The current progress cannot be confirmed.", tone: "warning" },
    },
    unknownCached: "The current status cannot be verified. Keeping the latest receipt.", approval: "Handle authorization", review: "Review in chat",
    details: "Details", hideDetails: "Hide details", summary: "Latest receipt summary", noSummary: "No result summary yet.",
    dispatchId: "Dispatch ID: ", projectId: "Project ID: ", nativeTaskId: "Native task ID: ", notBound: "Not bound yet",
    refresh: "Refresh", unavailable: "Task status unavailable", retained: "Keeping the latest receipts. The current status needs to be checked.",
    noReceipts: "No usable receipts received. Please refresh.", loading: "Loading tasks", invalid: "Task receipts unavailable",
    empty: "No assistant dispatch tasks yet", more: "Show more", showing: (count: number) => `Showing the first ${count} receipts.`,
    detailsLabel: (expanded: boolean, title: string) => `${expanded ? "Hide" : "Show"} details for “${title}”`,
  },
} as const;

function TaskCard({ task, onReview, onApproval, lang = "zh" }: Props & { task: AssistantDispatchTask }) {
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  const copy = COPY[lang];
  const title = task.title || copy.untitled;
  const state = copy.states[task.state];
  const reviewable = ["unknown", "failed", "awaiting_verification"].includes(task.state);
  return (
    <VSurface as="article" tone="card" padding="normal" ariaLabel={title} data-task-state={task.state} className="grid gap-2">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <h3 className="min-w-0 flex-1 break-words text-sm font-medium text-[var(--fg-primary)]">{title}</h3>
        <VChip tone={state.tone}>{state.label}</VChip>
      </div>
      <p className="text-xs leading-relaxed text-[var(--fg-secondary)]">
        {task.state === "unknown" && !task.sourceAvailable ? copy.unknownCached : state.progress}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {task.state === "waiting_user" ? <VButton onClick={() => onApproval(task)}>{copy.approval}</VButton> : null}
        {reviewable ? <VButton onClick={() => onReview(task)}>{copy.review}</VButton> : null}
        <VButton variant="ghost" aria-expanded={expanded} aria-controls={detailsId}
          aria-label={copy.detailsLabel(expanded, title)} onClick={() => setExpanded(value => !value)}>
          {expanded ? copy.hideDetails : copy.details}
        </VButton>
      </div>
      {expanded ? <div id={detailsId} className="grid min-w-0 gap-2 border-t border-vui-border-subtle pt-2 text-xs leading-relaxed text-[var(--fg-secondary)]">
        <div>
          <p className="font-medium">{copy.summary}</p>
          <p className="whitespace-pre-wrap break-words">{task.resultSummary || copy.noSummary}</p>
        </div>
        <dl className="grid min-w-0 gap-1 break-all">
          <div><dt className="inline text-[var(--fg-tertiary)]">{copy.dispatchId}</dt><dd className="inline">{task.dispatchId}</dd></div>
          <div><dt className="inline text-[var(--fg-tertiary)]">{copy.projectId}</dt><dd className="inline">{task.projectId || copy.notBound}</dd></div>
          <div><dt className="inline text-[var(--fg-tertiary)]">{copy.nativeTaskId}</dt><dd className="inline">{task.nativeTaskId || copy.notBound}</dd></div>
        </dl>
      </div> : null}
    </VSurface>
  );
}

/** A mounted dialog owns this read-only view; hiding the document suspends its reads. */
export function LauncherAssistantTaskCards({ onReview, onApproval, lang = "zh" }: Props) {
  const copy = COPY[lang];
  const [visible, setVisible] = useState(() => document.visibilityState !== "hidden");
  const [shown, setShown] = useState(PAGE_SIZE);
  const [confirmedIdentity, setConfirmedIdentity] = useState("");
  useEffect(() => {
    const update = () => {
      const next = document.visibilityState !== "hidden";
      setVisible(next);
      if (!next) setConfirmedIdentity("");
    };
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  const status = useQuery({
    queryKey: ["launcher-assistant", "status"],
    queryFn: async ({ signal }) => {
      signal.throwIfAborted();
      const result = await getLauncherAssistantStatus();
      signal.throwIfAborted();
      return result;
    },
    enabled: visible, retry: false, staleTime: 0,
    refetchOnWindowFocus: false, refetchOnReconnect: false,
  });
  const agentId = status.data?.assistant.agentId || "";
  const sessionId = status.data?.assistant.directSessionId || "";
  const identity = JSON.stringify([agentId, sessionId]);
  useEffect(() => {
    // Revalidate once per visible opening. Later shared status refreshes must
    // not toggle enabled and silently retry a failed dispatch read forever.
    if (visible && status.isSuccess && !status.isFetching) setConfirmedIdentity(identity);
  }, [identity, visible, status.isSuccess, status.isFetching]);
  const identityConfirmed = confirmedIdentity === identity && Boolean(agentId && sessionId);
  const reading = visible && status.isSuccess && identityConfirmed;
  const dispatches = useQuery({
    // No unscoped placeholderData: an assistant identity cannot inherit another one's cards.
    queryKey: ["launcher-assistant", "task-cards", agentId, sessionId],
    queryFn: async ({ signal }) => {
      signal.throwIfAborted();
      const result = await getLauncherAssistantDispatches();
      signal.throwIfAborted();
      return result;
    },
    enabled: reading, retry: false, staleTime: 0,
    refetchOnWindowFocus: false, refetchOnReconnect: false, refetchIntervalInBackground: false,
    refetchInterval: query => reading && query.state.status === "success"
      && projectAssistantDispatchTasks(query.state.data ?? []).tasks.some(task => task.shouldPoll) ? 3_000 : false,
  });
  useEffect(() => setShown(PAGE_SIZE), [identity]);
  const unavailable = status.isError || dispatches.isError;
  const loading = !unavailable && (!identityConfirmed || status.isPending || dispatches.isPending);
  const feed = projectAssistantDispatchTasks(identityConfirmed ? dispatches.data ?? [] : [], { sourceAvailable: !unavailable });
  const refreshing = status.isFetching || dispatches.isFetching;
  const refresh = async () => {
    const result = await status.refetch();
    if (result.isSuccess && JSON.stringify([result.data.assistant.agentId, result.data.assistant.directSessionId]) === identity)
      await dispatches.refetch();
  };
  const refreshButton = <VButton isPending={refreshing} onClick={() => { void refresh(); }}>{copy.refresh}</VButton>;

  return (
    <section aria-label={copy.label} className="grid min-w-0 content-start gap-3" data-assistant-task-cards>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-[var(--fg-secondary)]">{copy.scope}</p>
        {refreshButton}
      </div>
      {unavailable ? <VStateSurface density="compact" tone="unavailable" title={copy.unavailable}>
        {feed.tasks.length ? copy.retained : copy.noReceipts}
      </VStateSurface> : loading ? <VStateSurface density="compact" tone="loading" title={copy.loading} /> : null}
      {!loading && !unavailable && !feed.tasks.length ? <VStateSurface density="compact"
        tone={feed.invalidRecords ? "unavailable" : "empty"} title={feed.invalidRecords ? copy.invalid : copy.empty} /> : null}
      {feed.tasks.length ? <div role="list" className="grid min-w-0 gap-3">
        {feed.tasks.slice(0, shown).map(task => <div role="listitem" key={JSON.stringify([identity, task.id])}>
          <TaskCard task={task} onReview={value => { if (identityConfirmed) onReview(value); }}
            onApproval={value => { if (identityConfirmed) onApproval(value); }} lang={lang} />
        </div>)}
      </div> : null}
      {feed.tasks.length > shown ? <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--fg-secondary)]">
        <span>{copy.showing(shown)}</span>
        <VButton variant="ghost" onClick={() => setShown(value => value + PAGE_SIZE)}>{copy.more}</VButton>
      </div> : null}
    </section>
  );
}
