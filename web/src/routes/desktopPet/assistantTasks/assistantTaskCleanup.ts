import { useEffect, useRef, useState } from "react";
import { executeLauncherTaskCleanup, previewLauncherTaskCleanup, type LauncherTaskCleanupPreview,
  type LauncherTaskCleanupResult, type LauncherTaskCleanupScope, type LauncherTaskCleanupTarget } from "../../../api/launcherAssistantTaskCleanup";
import type { AssistantTask } from "./assistantTeamRunTasks";
import { displayText, taskDisplayTitle } from "./assistantTaskMetadata";

export const taskCleanupKey = (target: LauncherTaskCleanupTarget) => JSON.stringify([target.kind, target.projectId,
  target.kind === "dispatch" ? target.dispatchId : target.originAction, target.kind === "team_run" ? target.requestId : null]);

export function taskGroup(task: AssistantTask): "attention" | "active" | "ended" {
  if (task.kind === "dispatch" && task.cleanupPending) return "attention";
  return task.state === "running" || task.state === "stopping" ? "active"
    : task.state === "awaiting_verification" || task.state === "stopped" ? "ended" : "attention";
}

export function taskTime(task: AssistantTask): number {
  // observedAt is a read timestamp, never a task update timestamp.
  return Date.parse(task.updatedAt || task.createdAt || "") || 0;
}

export function taskCleanupTargets(task: AssistantTask): LauncherTaskCleanupTarget[] {
  if (task.kind === "dispatch" && task.cleanupPending === true && task.projectId && task.nativeTaskId && !task.conflictingObservations)
    return [{ kind: "dispatch", projectId: task.projectId, dispatchId: task.dispatchId }];
  if (!task.sourceAvailable || !task.receiptBound || task.conflictingObservations || !task.projectId
    || task.state === "unknown") return [];
  if (task.kind === "dispatch") return ["succeeded", "failed", "cancelled", "timed_out"].includes(task.nativeStatus || "")
    ? [{ kind: "dispatch", projectId: task.projectId, dispatchId: task.dispatchId }] : [];
  if (!["completed", "failed", "stopped"].includes(task.nativeStatus || "") || !task.teamId || !task.flowId || !task.runId) return [];
  return task.sourceRefs.map(reference => ({ kind: "team_run", projectId: task.projectId!, ...reference,
    teamId: task.teamId!, flowId: task.flowId!, runId: task.runId! }));
}

export type AssistantCleanupDialogState = {
  identity: string; ids: string[]; snapshot: string; scope: LauncherTaskCleanupScope; titles: Record<string, string>; bulk: boolean;
  pending: "preview" | "execute" | null; preview?: LauncherTaskCleanupPreview; result?: LauncherTaskCleanupResult; error?: string;
};

const snapshot = (tasks: AssistantTask[]) => JSON.stringify(tasks.map(task => [task.id, task.nativeStatus, taskCleanupTargets(task)]));

/** Only disclosure state lives here. The host remains the sole deletion authority. */
export function useAssistantTaskCleanup(options: {
  agentId: string; sessionId: string; identity: string; canAct: boolean; tasks: AssistantTask[]; lang: "zh" | "en"; onChanged: () => Promise<unknown>;
}) {
  const [state, setState] = useState<AssistantCleanupDialogState | null>(null);
  const generation = useRef(0);
  const operation = useRef<AbortController | null>(null);
  const executing = useRef<number | null>(null);
  const current = useRef(options);
  current.current = options;
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => {
    mounted.current = false; generation.current += 1; operation.current?.abort();
  }; }, []);
  const selected = (ids: string[]) => ids.map(id => current.current.tasks.find(task => task.id === id)).filter((task): task is AssistantTask => Boolean(task));
  const valid = (candidate: AssistantCleanupDialogState) => mounted.current && current.current.canAct
    && current.current.identity === candidate.identity && snapshot(selected(candidate.ids)) === candidate.snapshot;
  const close = () => { generation.current += 1; operation.current?.abort(); setState(null); };
  // Hide immediately on identity/visibility loss; late replies cannot reopen it.
  const visibleState = state && options.canAct && state.identity === options.identity ? state : null;
  const stale = Boolean(state && !state.result && !state.pending && !valid(state));
  useEffect(() => {
    if (state && (!options.canAct || state.identity !== options.identity || stale)) {
      generation.current += 1; operation.current?.abort(); setState(null);
    }
  }, [options.canAct, options.identity, stale, state]);

  const open = async (tasks: AssistantTask[], bulk = false) => {
    if (!current.current.canAct) return;
    const eligible = tasks.filter(task => taskCleanupTargets(task).length > 0 && (!bulk
      || task.kind === "dispatch" && (task.nativeStatus === "succeeded" || task.cleanupPending === true) || task.kind === "team_run" && task.nativeStatus === "completed"));
    const targets = eligible.flatMap(taskCleanupTargets);
    if (!targets.length) return;
    const token = ++generation.current;
    operation.current?.abort();
    const controller = new AbortController(); operation.current = controller;
    const titles = Object.fromEntries(eligible.flatMap(task => taskCleanupTargets(task).map(target => [taskCleanupKey(target),
      taskDisplayTitle(task.title, task.kind === "dispatch" ? task.dispatchId : task.requestId, current.current.lang)])));
    const candidate: AssistantCleanupDialogState = { identity: current.current.identity, ids: eligible.map(task => task.id), titles,
      snapshot: snapshot(eligible), scope: { agentId: current.current.agentId, directSessionId: current.current.sessionId, targets }, bulk, pending: "preview" };
    setState(candidate);
    try {
      const preview = await previewLauncherTaskCleanup(candidate.scope, { signal: controller.signal });
      if (generation.current === token && valid(candidate)) setState({ ...candidate, pending: null, preview });
      else if (generation.current === token && mounted.current) close();
    } catch (error) {
      if (generation.current === token && valid(candidate)) setState({ ...candidate, pending: null, error: displayText(error instanceof Error ? error.message : String(error)) });
    }
  };
  const execute = async () => {
    if (!state?.preview || state.pending || executing.current === generation.current || !valid(state) || !state.preview.items.some(item => item.status === "ready")) return;
    operation.current?.abort();
    const controller = new AbortController(); operation.current = controller;
    const candidate = state, token = ++generation.current;
    executing.current = token;
    setState({ ...candidate, pending: "execute", error: undefined });
    try {
      const result = await executeLauncherTaskCleanup(candidate.scope, candidate.preview!.fingerprint, { signal: controller.signal });
      if (generation.current === token && mounted.current && current.current.identity === candidate.identity && current.current.canAct)
        setState({ ...candidate, pending: null, preview: undefined, result });
      // Refresh authoritative feeds even if the dialog closed during the operation.
      if (mounted.current && current.current.identity === candidate.identity) await current.current.onChanged();
    } catch (error) {
      if (generation.current === token && valid(candidate)) setState({ ...candidate, pending: null, preview: undefined,
        error: displayText(error instanceof Error ? error.message : String(error)) });
      if (mounted.current && current.current.identity === candidate.identity) await current.current.onChanged();
    } finally { if (executing.current === token) executing.current = null; }
  };
  return { state: visibleState, close, open, execute, retry: () => state ? open(selected(state.ids), state.bulk) : Promise.resolve() };
}
