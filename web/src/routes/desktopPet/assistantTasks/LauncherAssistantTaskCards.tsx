import { useEffect, useRef, useState, type ReactNode } from "react";
import { useInfiniteQuery, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { getLauncherAssistantDispatches, getLauncherAssistantStatus, getLauncherAssistantTeamRuns } from "../../../api/launcherAssistant";
import { projectAssistantDispatchTasks, type AssistantDispatchTask } from "./assistantDispatchTasks";
import { projectAssistantTeamRunTasks, retainAssistantTeamRunDisplay, type AssistantTask, type AssistantTeamRunObservationPage } from "./assistantTeamRunTasks";
import { assistantTaskErrorProbeInterval } from "./assistantTaskProbes";
import { taskCleanupTargets, taskGroup, taskTime, useAssistantTaskCleanup } from "./assistantTaskCleanup";
import { LauncherTaskCleanupDialog } from "./LauncherTaskCleanupDialog";
import { LauncherAssistantTaskDetail } from "./LauncherAssistantTaskDetail";
import { LauncherTaskContext, type TaskReviewRequest } from "./LauncherTaskContext";
import { LauncherAssistantTaskSidebar } from "./LauncherAssistantTaskSidebar";
import { readLauncherAssistantTaskSource } from "../launcherAssistantTaskReads";

const PAGE_SIZE=10;
type Props={lang?:"zh"|"en";routePath?:string;children?:ReactNode;onReview?:(task:AssistantTask)=>void;onApproval?:(task:AssistantDispatchTask)=>void;onOpenConversation?:()=>void};

/** One Launcher owner for identity-scoped reads, selection and guarded cleanup.
 * Desktop/mobile navigation share this provider; native stores remain authoritative. */
export function LauncherAssistantTaskCards({onReview,onApproval,onOpenConversation,children,routePath,lang="zh"}:Props){
 const [selection,setSelection]=useState<{id:string;identity:string}|null>(null);
 const [reviewRequest,setReviewRequest]=useState<TaskReviewRequest|null>(null);
 const returnFocus=useRef<HTMLElement|null>(null);
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
  const more = async (group: "attention"|"active"|"ended") => {
    if(!activeView.current.mounted || !activeView.current.canAct || activeView.current.identity!==identity)return;
    const loaded=tasks.filter(task=>taskGroup(task)===group).length;
    if (loaded<=shown && teamRuns.hasNextPage && teamEnabled) await teamRuns.fetchNextPage();
    if (activeView.current.mounted && activeView.current.canAct && activeView.current.identity === identity)
      setShown(value => value + PAGE_SIZE);
  };
  const cleanup = useAssistantTaskCleanup({ agentId, sessionId, identity, canAct: reading, tasks, lang,
    onChanged: () => Promise.allSettled([
      queryClient.invalidateQueries({ queryKey: ["launcher-assistant", "task-cards", agentId, sessionId], exact: true }),
      queryClient.invalidateQueries({ queryKey: teamQueryKey, exact: true }),
    ]),
  });
  const cleanable = tasks.filter(task => (task.kind === "dispatch" ? task.nativeStatus === "succeeded" || task.cleanupPending === true : task.nativeStatus === "completed")
    && taskCleanupTargets(task).length > 0);

 const selected=identityConfirmed && selection?.identity===identity ? tasks.find(task=>task.id===selection.id) : undefined;
 const openTask=(task:AssistantTask,trigger?:HTMLElement)=>{
  if(!activeView.current.mounted || !activeView.current.canAct || activeView.current.identity!==identity)return;
  returnFocus.current=trigger??null;setSelection({id:task.id,identity});
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
 const remove=(task:AssistantTask)=>{if(reading){closeTask();void cleanup.open([task]);}};
 const context={tasks,loading,unavailable,refreshing,teamUnavailable:teamSupported&&teamRuns.isError,
  partial:teamPartial,invalid:feed.invalidRecords,enabled:reading,shown,hasNextPage:teamEnabled&&Boolean(teamRuns.hasNextPage)&&!teamRuns.isError,
  loadingMore:teamRuns.isFetchingNextPage,selectedId:selected?.id??null,cleanableCount:cleanable.length,
  refresh,more,openTask,cleanCompleted:()=>{if(reading)void cleanup.open(cleanable,true);},reviewRequest:identityConfirmed&&reviewRequest?.identity===identity?reviewRequest:null};
 return <LauncherTaskContext.Provider value={context}>
  {children??<LauncherAssistantTaskSidebar lang={lang}/>}
  {selected?<LauncherAssistantTaskDetail key={JSON.stringify([identity,selected.id])} task={selected} lang={lang}
   actionsEnabled={reading} onClose={closeTask} onReview={review} onApproval={approve} onDelete={remove}
   onCloseAutoFocus={event=>{event.preventDefault();requestAnimationFrame(()=>{if(document.querySelector('[role="dialog"][data-state="open"]'))return;
    const prior=returnFocus.current;
    const target=prior?.isConnected&&prior.getClientRects().length?prior:Array.from(document.querySelectorAll<HTMLElement>('button[aria-label="打开功能导航"],button[aria-label="Open navigation"]')).find(node=>node.getClientRects().length);
    target?.focus();});}}/>:null}
  <LauncherTaskCleanupDialog state={cleanup.state} lang={lang} onClose={cleanup.close}
   onConfirm={()=>{void cleanup.execute();}} onRetry={()=>{void cleanup.retry();}}/>
 </LauncherTaskContext.Provider>;
}
