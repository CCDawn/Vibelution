import { useEffect, useRef, useState, type ReactNode } from "react";
import { useInfiniteQuery, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { getLauncherAssistantDispatches, getLauncherAssistantStatus, getLauncherAssistantTeamRuns } from "../../../api/launcherAssistant";
import { projectAssistantDispatchTasks, type AssistantDispatchTask } from "./assistantDispatchTasks";
import { assistantTeamRunPageNeedsRefresh, projectAssistantTeamRunTasks, retainAssistantTeamRunDisplay, type AssistantTask, type AssistantTeamRunObservationPage } from "./assistantTeamRunTasks";
import { assistantTaskErrorProbeInterval } from "./assistantTaskProbes";
import { taskCleanupTargets, taskGroup, taskTime, useAssistantTaskCleanup, type AssistantCleanupCollection, type AssistantCleanupSourceError } from "./assistantTaskCleanup";
import { LauncherTaskCleanupDialog } from "./LauncherTaskCleanupDialog";
import { LauncherAssistantTaskDetail } from "./LauncherAssistantTaskDetail";
import { LauncherTaskContext, usePublishLauncherTaskNotices, type TaskReviewRequest } from "./LauncherTaskContext";
import { LauncherAssistantTaskSidebar } from "./LauncherAssistantTaskSidebar";
import { readLauncherAssistantTaskSource } from "../launcherAssistantTaskReads";
import { launcherNoticeReadFailed } from "../launcherAssistantPageNotices";

const PAGE_SIZE=10;
type Props={lang?:"zh"|"en";routePath?:string;children?:ReactNode;onReview?:(task:AssistantTask)=>void;onApproval?:(task:AssistantDispatchTask)=>void;onOpenConversation?:()=>void};
type TaskFocus = { identity: string; id: string | null; action: "open" | "cleanup"; prior: HTMLElement | null };

/** One Launcher owner for identity-scoped reads, selection and guarded cleanup.
 * Desktop/mobile navigation share this provider; native stores remain authoritative. */
export function LauncherAssistantTaskCards({onReview,onApproval,onOpenConversation,children,routePath,lang="zh"}:Props){
 const [selection,setSelection]=useState<{id:string;identity:string}|null>(null);
 const [reviewRequest,setReviewRequest]=useState<TaskReviewRequest|null>(null);
 const returnFocus=useRef<TaskFocus|null>(null);
 const cleanupFocus=useRef<TaskFocus|null>(null);
 const previousPath=useRef(routePath);
 useEffect(()=>{
  if(previousPath.current?.replace(/\/+$/, "").endsWith("/assistant")&&!routePath?.replace(/\/+$/, "").endsWith("/assistant"))setReviewRequest(null);
  previousPath.current=routePath;
 },[routePath]);
  const queryClient = useQueryClient();
  const [visible, setVisible] = useState(() => document.visibilityState !== "hidden");
  const [shown, setShown] = useState(PAGE_SIZE);
  const [confirmedIdentity, setConfirmedIdentity] = useState("");
  const activeView = useRef({ mounted: false, identity: "", canAct: false });
  // First-failure anchors of the two feed reads. query.state only exposes the
  // LAST error time, while the bounded probe cadence must grow across
  // consecutive failures and reset on any success or identity change. A retry
  // fetch must NOT reset the anchor: react-query optimistically reports a
  // no-data error query as non-error while its retry is in flight.
  const dispatchProbeStartedAt = useRef<number | null>(null);
  const teamProbeStartedAt = useRef<number | null>(null);
  const probeIdentity = useRef("");
  useEffect(() => {
    activeView.current.mounted = true;
    const update = () => {
      const next = document.visibilityState !== "hidden";
      if (!next) {
        // A hidden view discards its reads; that is cancellation, not a source
        // failure. Cancel before the view guard rejects a successful late IPC.
        // The native read still drains through readLauncherAssistantTaskSource.
        const currentIdentity = activeView.current.identity;
        void queryClient.cancelQueries({ predicate: query => query.queryKey[0] === "launcher-assistant"
          && (query.queryKey[1] === "task-cards" || query.queryKey[1] === "team-task-cards")
          && JSON.stringify(query.queryKey.slice(2)) === currentIdentity });
      }
      setVisible(next);
      if (!next) setConfirmedIdentity("");
    };
    document.addEventListener("visibilitychange", update);
    return () => {
      activeView.current.mounted = false;
      document.removeEventListener("visibilitychange", update);
    };
  }, [queryClient]);
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
  // Reset before query observers choose their intervals for the new identity.
  if (probeIdentity.current !== identity) {
    probeIdentity.current = identity;
    dispatchProbeStartedAt.current = null;
    teamProbeStartedAt.current = null;
  }
  useEffect(() => {
    // Revalidate once per visible opening. Later shared status refreshes must
    // not toggle enabled and silently retry a failed dispatch read forever.
    if (visible && status.isSuccess && !status.isFetching) setConfirmedIdentity(identity);
  }, [identity, visible, status.isSuccess, status.isFetching]);
  const identityConfirmed = visible && confirmedIdentity === identity && Boolean(agentId && sessionId);
  const reading = visible && status.isSuccess && identityConfirmed;
  activeView.current.identity = identityConfirmed ? identity : "";
  activeView.current.canAct = reading;
  const canReadSource = () => document.visibilityState !== "hidden" && activeView.current.mounted
    && activeView.current.canAct && activeView.current.identity === identity;
  useEffect(()=>{if(!identityConfirmed){setSelection(null);setReviewRequest(null);}},[identityConfirmed,identity]);
  const teamSupported = identityConfirmed && status.data?.teamRunsVersion === 1;
  const teamEnabled = reading && teamSupported;
  const dispatches = useQuery({
    // No unscoped placeholderData: an assistant identity cannot inherit another one's cards.
    queryKey: ["launcher-assistant", "task-cards", agentId, sessionId],
    queryFn: async ({ signal }) => {
      signal.throwIfAborted();
      const result = await readLauncherAssistantTaskSource(identity, signal, getLauncherAssistantDispatches, canReadSource);
      signal.throwIfAborted();
      return result;
    },
    enabled: reading, retry: false, staleTime: 0,
    refetchOnWindowFocus: false, refetchOnReconnect: false, refetchIntervalInBackground: false,
    // An error keeps a bounded liveness probe (3s→6s→12s, five attempts) so a
    // recovered source is rejoined without manual refresh; the gate on
    // `reading` stops it the moment the page hides or the identity is lost.
    refetchInterval: query => {
      if (!reading) return false;
      if (query.state.status === "error") return assistantTaskErrorProbeInterval(dispatchProbeStartedAt.current, Date.now());
      return query.state.status === "success"
        && projectAssistantDispatchTasks(query.state.data ?? []).tasks.some(task => task.shouldPoll) ? 3_000 : false;
    },
  });
  const teamQueryKey = ["launcher-assistant", "team-task-cards", agentId, sessionId];
  const teamRuns = useInfiniteQuery({
    queryKey: teamQueryKey,
    queryFn: async ({ signal, pageParam }) => {
      signal.throwIfAborted();
      const result = await readLauncherAssistantTaskSource(identity, signal,
        () => getLauncherAssistantTeamRuns({ agentId, directSessionId: sessionId }, pageParam), canReadSource);
      signal.throwIfAborted();
      const previous = queryClient.getQueryData<InfiniteData<AssistantTeamRunObservationPage>>(teamQueryKey);
      return retainAssistantTeamRunDisplay(result, previous?.pages ?? []);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: page => page.nextCursor ?? undefined,
    enabled: teamEnabled, retry: false, staleTime: 0,
    refetchOnWindowFocus: false, refetchOnReconnect: false, refetchIntervalInBackground: false,
    // Same bounded error probe as the dispatch feed, gated on `teamEnabled`.
    refetchInterval: query => {
      if (!teamEnabled) return false;
      if (query.state.status === "error") return assistantTaskErrorProbeInterval(teamProbeStartedAt.current, Date.now());
      return query.state.status === "success"
        && projectAssistantTeamRunTasks(query.state.data?.pages.flatMap(page => page.teamRuns) ?? [])
          .tasks.some(task => task.shouldPoll) ? 3_000 : false;
    },
  });
  useEffect(() => {
    if (dispatches.isSuccess) dispatchProbeStartedAt.current = null;
    else if (dispatches.isError) dispatchProbeStartedAt.current = dispatchProbeStartedAt.current ?? Date.now();
  }, [dispatches.isSuccess, dispatches.isError, identity]);
  useEffect(() => {
    if (teamRuns.isSuccess) teamProbeStartedAt.current = null;
    else if (teamRuns.isError) teamProbeStartedAt.current = teamProbeStartedAt.current ?? Date.now();
  }, [teamRuns.isSuccess, teamRuns.isError, identity]);
  useEffect(() => setShown(PAGE_SIZE), [identity]);
  const unavailable = status.isError || dispatches.isError;
  const loading = !unavailable && (!identityConfirmed || status.isPending || dispatches.isPending
    || (teamEnabled && teamRuns.isPending));
  const feed = projectAssistantDispatchTasks(identityConfirmed ? dispatches.data ?? [] : [], { sourceAvailable: !unavailable });
  const teamPages = teamSupported ? teamRuns.data?.pages ?? [] : [];
  const teamFeed = projectAssistantTeamRunTasks(teamPages.flatMap(page => page.teamRuns), { sourceAvailable: !status.isError && !teamRuns.isError });
  const tasks: AssistantTask[] = [...feed.tasks.map(task => ({ ...task, kind: "dispatch" as const })), ...teamFeed.tasks]
    .sort((left, right) => taskTime(right) - taskTime(left) || left.id.localeCompare(right.id));
  const teamPartial = teamPages.some(assistantTeamRunPageNeedsRefresh)
    || teamFeed.invalidRecords > 0 || teamFeed.tasks.some(task => task.conflictingObservations);
  const historyIncomplete = teamPages.some(page => !page.coverage.historyComplete);
  const legacyUnrecoverable = Math.max(0, ...teamPages.map(page => page.coverage.legacyUnrecoverable));
  const refreshing = status.isFetching || dispatches.isFetching || (teamEnabled && teamRuns.isFetching);
  const refresh = async () => {
    const result = await status.refetch();
    if (result.isSuccess && document.visibilityState !== "hidden" && activeView.current.mounted
      && activeView.current.identity === identity
      && JSON.stringify([result.data.assistant.agentId, result.data.assistant.directSessionId]) === identity) {
      await Promise.allSettled([dispatches.refetch(), ...(result.data.teamRunsVersion === 1 ? [teamRuns.refetch()] : [])]);
    }
  };
  const more = async (group: "attention"|"active"|"ended") => {
    if(!activeView.current.mounted || !activeView.current.canAct || activeView.current.identity!==identity)return;
    const loaded=tasks.filter(task=>taskGroup(task)===group).length;
    if (loaded<=shown && teamRuns.hasNextPage && teamEnabled) await teamRuns.fetchNextPage();
    if (activeView.current.mounted && activeView.current.canAct && activeView.current.identity === identity)
      setShown(value => value + PAGE_SIZE);
  };
  const cleanup = useAssistantTaskCleanup({ agentId, sessionId, identity, canAct: reading, lang,
    onChanged: () => Promise.allSettled([
      queryClient.invalidateQueries({ queryKey: ["launcher-assistant", "task-cards", agentId, sessionId], exact: true }),
      queryClient.invalidateQueries({ queryKey: teamQueryKey, exact: true }),
    ]),
  });
  const cleanable = tasks.filter(task => taskCleanupTargets(task).length > 0);
  const cleanCompleted = () => {
    if (!reading) return;
    cleanupFocus.current = { identity, id: null, action: "cleanup", prior: document.activeElement instanceof HTMLElement ? document.activeElement : null };
    void cleanup.open(async signal => {
      const assertCurrent = () => {
        signal.throwIfAborted();
        if (!canReadSource()) throw new DOMException("Launcher task view changed", "AbortError");
      };
      const collect = async (source: AssistantCleanupSourceError["source"], read: () => Promise<AssistantTask[]>): Promise<AssistantCleanupCollection> => {
        try { return { tasks: await read() }; }
        catch (error) {
          // Identity, hidden and unmount cancellation invalidate every source.
          assertCurrent();
          return { tasks: [], sourceErrors: [{ source, message: error instanceof Error ? error.message : String(error) }] };
        }
      };
      const sources = await Promise.all([
        collect("dispatch", async () => {
          const rows = await readLauncherAssistantTaskSource(identity, signal, getLauncherAssistantDispatches, canReadSource);
          assertCurrent();
          return projectAssistantDispatchTasks(rows).tasks.map(task => ({ ...task, kind: "dispatch" as const }));
        }),
        collect("team_run", async () => {
          if (!teamEnabled) return [];
          const pages: AssistantTeamRunObservationPage[] = [];
          const cursors = new Set<string>();
          let cursor: string | undefined;
          do {
            assertCurrent();
            const page = await readLauncherAssistantTaskSource(identity, signal,
              () => getLauncherAssistantTeamRuns({ agentId, directSessionId: sessionId }, cursor), canReadSource);
            assertCurrent();
            pages.push(page);
            cursor = page.nextCursor ?? undefined;
            if (cursor && cursors.has(cursor)) throw new Error(lang === "zh" ? "任务分页重复，请重试。" : "Task pagination repeated. Please retry.");
            if (cursor) cursors.add(cursor);
          } while (cursor);
          // A later page failure discards this source's entire candidate list.
          return projectAssistantTeamRunTasks(pages.flatMap(page => page.teamRuns)).tasks;
        }),
      ]);
      assertCurrent();
      return { tasks: sources.flatMap(source => source.tasks), sourceErrors: sources.flatMap(source => source.sourceErrors ?? []) };
    }, true);
  };

 const selected=identityConfirmed && selection?.identity===identity ? tasks.find(task=>task.id===selection.id) : undefined;
 const openTask=(task:AssistantTask,trigger?:HTMLElement)=>{
  if(!activeView.current.mounted || !activeView.current.canAct || activeView.current.identity!==identity)return;
  returnFocus.current={identity,id:task.id,action:"open",prior:trigger??null};setSelection({id:task.id,identity});
 };
 const closeTask=()=>setSelection(null);
 const review=(task:AssistantTask)=>{
  if(!activeView.current.canAct || activeView.current.identity!==identity)return;
  setReviewRequest({task,nonce:crypto.randomUUID(),identity});closeTask();onReview?.(task);onOpenConversation?.();
 };
 const approve=(task:AssistantDispatchTask)=>{
  if(!activeView.current.canAct || activeView.current.identity!==identity)return;
  setReviewRequest(null);closeTask();onApproval?.(task);onOpenConversation?.();
 };
 const remove=(task:AssistantTask)=>{if(reading&&!cleanup.busy){
  cleanupFocus.current={identity,id:task.id,action:"cleanup",prior:document.activeElement instanceof HTMLElement?document.activeElement:null};
  closeTask();void cleanup.open([task]);}};
 const restoreFocus=(event:Event,anchor:TaskFocus|null)=>{
  event.preventDefault();
  if(!anchor)return;
  requestAnimationFrame(()=>{
   if(!activeView.current.mounted||!activeView.current.canAct||activeView.current.identity!==anchor.identity
    ||document.visibilityState==="hidden"||document.querySelector('[role="dialog"][data-state="open"]'))return;
   const visible=(node:HTMLElement|null|undefined):node is HTMLElement=>Boolean(node&&node!==document.body&&node!==document.documentElement&&node.isConnected&&node.getClientRects().length
    &&!node.closest('[hidden],[inert],[aria-hidden="true"]')&&!(node instanceof HTMLButtonElement&&node.disabled));
   const rows=Array.from(document.querySelectorAll<HTMLElement>('[data-assistant-task-id]')).filter(row=>row.dataset.assistantTaskId===anchor.id);
   const currentButtons=rows.map(row=>row.querySelector<HTMLElement>(anchor.action==="cleanup"?'[data-assistant-task-cleanup]':'[data-assistant-task-open]'));
   const otherButtons=rows.map(row=>row.querySelector<HTMLElement>('[data-assistant-task-open]'));
   const categories=Array.from(document.querySelectorAll<HTMLElement>('[data-assistant-task-cards] [role="tab"][aria-selected="true"]'));
   const navigation=Array.from(document.querySelectorAll<HTMLElement>('button[aria-label="打开功能导航"],button[aria-label="Open navigation"]'));
   [...currentButtons,...otherButtons,...rows,anchor.prior,...categories,...navigation].find(visible)?.focus();
  });
 };
 const context={identity,tasks,loading,unavailable,refreshing,teamUnavailable:teamSupported&&teamRuns.isError,
  partial:teamPartial,historyIncomplete,legacyUnrecoverable,invalid:feed.invalidRecords,enabled:reading,shown,hasNextPage:teamEnabled&&Boolean(teamRuns.hasNextPage)&&!teamRuns.isError,
  loadingMore:teamRuns.isFetchingNextPage,selectedId:selected?.id??null,cleanableCount:cleanable.length,
  cleanupBusy:cleanup.busy,canCleanCompleted:cleanable.length>0||(teamEnabled&&Boolean(teamRuns.hasNextPage)),
  refresh,more,openTask,remove,cleanCompleted,reviewRequest:identityConfirmed&&reviewRequest?.identity===identity?reviewRequest:null};
 usePublishLauncherTaskNotices({...context,
  unavailable:launcherNoticeReadFailed(status)||launcherNoticeReadFailed(dispatches),
  teamUnavailable:teamSupported&&launcherNoticeReadFailed(teamRuns),
 },lang);
 return <LauncherTaskContext.Provider value={context}>
  {children??<LauncherAssistantTaskSidebar lang={lang}/>}
  {selected?<LauncherAssistantTaskDetail key={JSON.stringify([identity,selected.id])} task={selected} lang={lang}
   actionsEnabled={reading} cleanupBusy={cleanup.busy} onClose={closeTask} onReview={review} onApproval={approve} onDelete={remove}
   onCloseAutoFocus={event=>restoreFocus(event,returnFocus.current)}/>:null}
  <LauncherTaskCleanupDialog state={cleanup.state} lang={lang} onClose={cleanup.close} onRetry={()=>{void cleanup.retry();}}
   onCloseAutoFocus={event=>restoreFocus(event,cleanupFocus.current)}/>
 </LauncherTaskContext.Provider>;
}
