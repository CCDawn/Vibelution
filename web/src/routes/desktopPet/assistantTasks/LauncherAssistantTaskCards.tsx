import { useEffect, useId, useRef, useState } from "react";
import { useInfiniteQuery, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { getLauncherAssistantDispatches, getLauncherAssistantStatus, getLauncherAssistantTeamRuns } from "../../../api/launcherAssistant";
import { VButton, VChip, VStateSurface, VSurface } from "../../../components/vui";
import { projectAssistantDispatchTasks, type AssistantDispatchTask } from "./assistantDispatchTasks";
import { projectAssistantTeamRunTasks, retainAssistantTeamRunDisplay, type AssistantTask, type AssistantTeamRunObservationPage } from "./assistantTeamRunTasks";
import styles from "./LauncherAssistantTaskCards.styles";

type Props = {
  lang?: "zh" | "en";
  onReview: (task: AssistantTask) => void;
  onApproval: (task: AssistantDispatchTask) => void;
};

const PAGE_SIZE = 10;
const COPY = {
  zh: {
    untitled: "助理任务", label: "助理任务", scope: "这里显示助理已派出的任务。",
    teamScope: "这里显示助理已派出的任务和关联团队运行。", teamUntitled: "团队运行", teamEmpty: "暂无助理任务",
    states: {
      running: { label: "执行中", progress: "助理正在推进这项任务。", tone: "neutral" },
      stopping: { label: "停止中", progress: "正在停止，结束后会更新状态。", tone: "neutral" },
      waiting_user: { label: "待授权", progress: "任务正在等待授权，请到对话中处理。", tone: "warning" },
      waiting_input: { label: "待输入", progress: "团队正在等待输入，可到对话中核对。", tone: "warning" },
      awaiting_verification: { label: "待验收", progress: "执行已结束，还需核对实际结果。", tone: "neutral" },
      failed: { label: "执行失败", progress: "遇到了问题，可请助理分析原因。", tone: "danger" },
      stopped: { label: "已停止", progress: "这项任务已停止。", tone: "neutral" },
      unknown: { label: "待核对", progress: "暂时无法确认任务进展。", tone: "warning" },
    },
    unknownCached: "暂时无法确认新进展，保留上次记录。", approval: "处理授权", review: "去对话核对",
    details: "详情", hideDetails: "收起详情", summary: "最近一次回执摘要", noSummary: "暂无结果摘要。",
    dispatchId: "派遣编号：", projectId: "项目编号：", nativeTaskId: "原生任务编号：", notBound: "尚未绑定",
    teamId: "团队编号：", flowId: "流程编号：", runId: "运行编号：", requestId: "请求编号：",
    revision: "版本：", observedAt: "读取时间：", teamUnavailable: "团队运行状态暂不可用",
    lastVerified: "以下为上次核验的信息，当前状态待核对。",
    teamPartial: "部分团队运行待核对，可刷新或到对话中查看。", teamHistory: "仅显示已登记的关联，历史记录可能不完整。",
    refresh: "刷新", unavailable: "任务状态暂不可用", retained: "保留上次记录，当前状态需重新核对。",
    noReceipts: "暂时无法读取任务，请刷新。", loading: "正在读取任务", invalid: "部分任务暂时无法读取",
    empty: "暂无助理派遣任务", more: "显示更多", showing: (count: number) => `当前显示前 ${count} 项任务。`,
    detailsLabel: (expanded: boolean, title: string) => `${expanded ? "收起" : "查看"}“${title}”详情`,
  },
  en: {
    untitled: "Assistant task", label: "Assistant tasks", scope: "Showing tasks dispatched by your assistant.",
    teamScope: "Showing assistant dispatches and associated team runs.", teamUntitled: "Team run", teamEmpty: "No assistant tasks yet",
    states: {
      running: { label: "Running", progress: "Your assistant is working on this task.", tone: "neutral" },
      stopping: { label: "Stopping", progress: "Stopping is in progress. The status will update when it ends.", tone: "neutral" },
      waiting_user: { label: "Needs authorization", progress: "The task needs authorization. Handle it in the conversation.", tone: "warning" },
      waiting_input: { label: "Waiting for input", progress: "The team is waiting for input. Review it in the conversation.", tone: "warning" },
      awaiting_verification: { label: "Awaiting verification", progress: "Execution has ended. The actual result still needs verification.", tone: "neutral" },
      failed: { label: "Execution failed", progress: "A problem occurred. Ask your assistant to investigate.", tone: "danger" },
      stopped: { label: "Stopped", progress: "This task has stopped.", tone: "neutral" },
      unknown: { label: "Unknown", progress: "The current progress cannot be confirmed.", tone: "warning" },
    },
    unknownCached: "The current status cannot be verified. Keeping the latest receipt.", approval: "Handle authorization", review: "Review in chat",
    details: "Details", hideDetails: "Hide details", summary: "Latest receipt summary", noSummary: "No result summary yet.",
    dispatchId: "Dispatch ID: ", projectId: "Project ID: ", nativeTaskId: "Native task ID: ", notBound: "Not bound yet",
    teamId: "Team ID: ", flowId: "Flow ID: ", runId: "Run ID: ", requestId: "Request ID: ",
    revision: "Revision: ", observedAt: "Observed at: ", teamUnavailable: "Team run status unavailable",
    lastVerified: "Last verified information. The current status still needs checking.",
    teamPartial: "Some team runs need checking. Refresh or review them in chat.", teamHistory: "Only registered associations are shown. History may be incomplete.",
    refresh: "Refresh", unavailable: "Task status unavailable", retained: "Keeping the latest receipts. The current status needs to be checked.",
    noReceipts: "No usable receipts received. Please refresh.", loading: "Loading tasks", invalid: "Task receipts unavailable",
    empty: "No assistant dispatch tasks yet", more: "Show more", showing: (count: number) => `Showing the first ${count} receipts.`,
    detailsLabel: (expanded: boolean, title: string) => `${expanded ? "Hide" : "Show"} details for “${title}”`,
  },
} as const;

function TaskCard({ task, onReview, onApproval, actionsEnabled, lang = "zh" }: Props & { task: AssistantTask; actionsEnabled: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  const copy = COPY[lang];
  const title = task.title || (task.kind === "team_run" ? copy.teamUntitled : copy.untitled);
  const state = copy.states[task.state];
  const reviewable = ["unknown", "failed", "awaiting_verification", "waiting_input"].includes(task.state);
  const teamDisplay = task.kind === "team_run" ? task.lastKnown ?? task : null;
  return (
    <VSurface as="article" tone="card" padding="normal" ariaLabel={title} data-task-state={task.state} data-task-kind={task.kind} className={styles.card}>
      <div className={styles.heading}>
        <h3 className={styles.title}>{title}</h3>
        <VChip tone={state.tone}>{state.label}</VChip>
      </div>
      <p className={styles.progress}>
        {task.state === "unknown" && !task.sourceAvailable && (task.kind === "dispatch" || task.lastKnown)
          ? copy.unknownCached : state.progress}
      </p>
      <div className={styles.actions}>
        {task.kind === "dispatch" && task.state === "waiting_user" ? <VButton isDisabled={!actionsEnabled} onClick={() => onApproval(task)}>{copy.approval}</VButton> : null}
        {reviewable ? <VButton isDisabled={!actionsEnabled} onClick={() => onReview(task)}>{copy.review}</VButton> : null}
        <VButton variant="ghost" aria-expanded={expanded} aria-controls={detailsId}
          aria-label={copy.detailsLabel(expanded, title)} onClick={() => setExpanded(value => !value)}>
          {expanded ? copy.hideDetails : copy.details}
        </VButton>
      </div>
      {expanded ? <div id={detailsId} className={styles.details}>
        {task.kind === "dispatch" ? <div>
          <p className={styles.summaryHeading}>{copy.summary}</p>
          <p className={styles.summary}>{task.resultSummary || copy.noSummary}</p>
        </div> : null}
        {task.kind === "team_run" && task.lastKnown ? <p>{copy.lastVerified}</p> : null}
        <dl className={styles.references}>
          <div><dt className={styles.referenceLabel}>{copy.projectId}</dt><dd className={styles.referenceValue}>{task.projectId || copy.notBound}</dd></div>
          {task.kind === "dispatch" ? <>
            <div><dt className={styles.referenceLabel}>{copy.dispatchId}</dt><dd className={styles.referenceValue}>{task.dispatchId}</dd></div>
            <div><dt className={styles.referenceLabel}>{copy.nativeTaskId}</dt><dd className={styles.referenceValue}>{task.nativeTaskId || copy.notBound}</dd></div>
          </> : <>
            <div><dt className={styles.referenceLabel}>{copy.requestId}</dt><dd className={styles.referenceValue}>{task.requestId}</dd></div>
            <div><dt className={styles.referenceLabel}>{copy.teamId}</dt><dd className={styles.referenceValue}>{teamDisplay?.teamId || copy.notBound}</dd></div>
            <div><dt className={styles.referenceLabel}>{copy.flowId}</dt><dd className={styles.referenceValue}>{teamDisplay?.flowId || copy.notBound}</dd></div>
            <div><dt className={styles.referenceLabel}>{copy.runId}</dt><dd className={styles.referenceValue}>{teamDisplay?.runId || copy.notBound}</dd></div>
            <div><dt className={styles.referenceLabel}>{copy.revision}</dt><dd className={styles.referenceValue}>{teamDisplay?.revision || copy.notBound}</dd></div>
            <div><dt className={styles.referenceLabel}>{copy.observedAt}</dt><dd className={styles.referenceValue}>{teamDisplay?.observedAt || copy.notBound}</dd></div>
          </>}
        </dl>
      </div> : null}
    </VSurface>
  );
}

/** A mounted dialog owns this read-only view; hiding the document suspends its reads. */
export function LauncherAssistantTaskCards({ onReview, onApproval, lang = "zh" }: Props) {
  const queryClient = useQueryClient();
  const copy = COPY[lang];
  const [visible, setVisible] = useState(() => document.visibilityState !== "hidden");
  const [shown, setShown] = useState(PAGE_SIZE);
  const [confirmedIdentity, setConfirmedIdentity] = useState("");
  const activeView = useRef({ mounted: false, identity: "", canAct: false });
  useEffect(() => {
    activeView.current.mounted = true;
    const update = () => {
      const next = document.visibilityState !== "hidden";
      setVisible(next);
      if (!next) setConfirmedIdentity("");
    };
    document.addEventListener("visibilitychange", update);
    return () => {
      activeView.current.mounted = false;
      document.removeEventListener("visibilitychange", update);
    };
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
  const identityConfirmed = visible && confirmedIdentity === identity && Boolean(agentId && sessionId);
  const reading = visible && status.isSuccess && identityConfirmed;
  activeView.current.identity = identityConfirmed ? identity : "";
  activeView.current.canAct = reading;
  const teamSupported = identityConfirmed && status.data?.teamRunsVersion === 1;
  const teamEnabled = reading && teamSupported;
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
  const teamQueryKey = ["launcher-assistant", "team-task-cards", agentId, sessionId];
  const teamRuns = useInfiniteQuery({
    queryKey: teamQueryKey,
    queryFn: async ({ signal, pageParam }) => {
      signal.throwIfAborted();
      const result = await getLauncherAssistantTeamRuns({ agentId, directSessionId: sessionId }, pageParam);
      signal.throwIfAborted();
      const previous = queryClient.getQueryData<InfiniteData<AssistantTeamRunObservationPage>>(teamQueryKey);
      return retainAssistantTeamRunDisplay(result, previous?.pages ?? []);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: page => page.nextCursor ?? undefined,
    enabled: teamEnabled, retry: false, staleTime: 0,
    refetchOnWindowFocus: false, refetchOnReconnect: false, refetchIntervalInBackground: false,
    refetchInterval: query => teamEnabled && query.state.status === "success"
      && projectAssistantTeamRunTasks(query.state.data?.pages.flatMap(page => page.teamRuns) ?? [])
        .tasks.some(task => task.shouldPoll) ? 3_000 : false,
  });
  useEffect(() => setShown(PAGE_SIZE), [identity]);
  const unavailable = status.isError || dispatches.isError;
  const loading = !unavailable && (!identityConfirmed || status.isPending || dispatches.isPending
    || (teamEnabled && teamRuns.isPending));
  const feed = projectAssistantDispatchTasks(identityConfirmed ? dispatches.data ?? [] : [], { sourceAvailable: !unavailable });
  const teamPages = teamSupported ? teamRuns.data?.pages ?? [] : [];
  const teamFeed = projectAssistantTeamRunTasks(teamPages.flatMap(page => page.teamRuns), { sourceAvailable: !status.isError && !teamRuns.isError });
  const tasks: AssistantTask[] = [...feed.tasks.map(task => ({ ...task, kind: "dispatch" as const })), ...teamFeed.tasks];
  const teamPartial = teamPages.some(page => page.state === "partial" || page.coverage.invalidRecords > 0 || page.coverage.legacyUnrecoverable > 0)
    || teamFeed.invalidRecords > 0;
  const refreshing = status.isFetching || dispatches.isFetching || (teamEnabled && teamRuns.isFetching);
  const refresh = async () => {
    const result = await status.refetch();
    if (result.isSuccess && document.visibilityState !== "hidden" && activeView.current.mounted
      && activeView.current.identity === identity
      && JSON.stringify([result.data.assistant.agentId, result.data.assistant.directSessionId]) === identity) {
      await Promise.allSettled([dispatches.refetch(), ...(result.data.teamRunsVersion === 1 ? [teamRuns.refetch()] : [])]);
    }
  };
  const more = async () => {
    if (tasks.length <= shown && teamRuns.hasNextPage && teamEnabled) await teamRuns.fetchNextPage();
    if (activeView.current.mounted && activeView.current.canAct && activeView.current.identity === identity)
      setShown(value => value + PAGE_SIZE);
  };
  const refreshButton = <VButton isPending={refreshing} onClick={() => { void refresh(); }}>{copy.refresh}</VButton>;

  return (
    <section aria-label={copy.label} className={styles.root} data-assistant-task-cards>
      <div className={styles.toolbar}>
        <p className={styles.scope}>{teamSupported ? copy.teamScope : copy.scope}</p>
        {refreshButton}
      </div>
      {unavailable ? <VStateSurface density="compact" tone="unavailable" title={copy.unavailable}>
        {feed.tasks.length ? copy.retained : copy.noReceipts}
      </VStateSurface> : loading ? <VStateSurface density="compact" tone="loading" title={copy.loading} /> : null}
      {teamSupported && teamRuns.isError ? <VStateSurface density="compact" tone="unavailable" title={copy.teamUnavailable}>
        {teamFeed.tasks.length ? copy.retained : copy.noReceipts}
      </VStateSurface> : teamSupported && teamPartial ? <p className={styles.scope}>{copy.teamPartial}</p> : null}
      {!loading && !unavailable && !tasks.length && !teamPartial && (!teamSupported || (!teamRuns.isPending && !teamRuns.isError)) ? <VStateSurface density="compact"
        tone={feed.invalidRecords ? "unavailable" : "empty"} title={feed.invalidRecords ? copy.invalid : teamSupported ? copy.teamEmpty : copy.empty} /> : null}
      {tasks.length ? <div role="list" className={styles.list}>
        {tasks.slice(0, shown).map(task => <div role="listitem" key={JSON.stringify([identity, task.kind, task.id])}>
          <TaskCard task={task} actionsEnabled={reading} onReview={value => {
            if (activeView.current.mounted && activeView.current.canAct && activeView.current.identity === identity) onReview(value);
          }} onApproval={value => {
            if (activeView.current.mounted && activeView.current.canAct && activeView.current.identity === identity) onApproval(value);
          }} lang={lang} />
        </div>)}
      </div> : null}
      {teamSupported && teamPages.length > 0 ? <p className={styles.scope}>{copy.teamHistory}</p> : null}
      {tasks.length > shown || (teamEnabled && teamRuns.hasNextPage && !teamRuns.isError) ? <div className={styles.more}>
        <span>{copy.showing(Math.min(shown, tasks.length))}</span>
        <VButton variant="ghost" isPending={teamRuns.isFetchingNextPage} onClick={() => { void more(); }}>{copy.more}</VButton>
      </div> : null}
    </section>
  );
}
