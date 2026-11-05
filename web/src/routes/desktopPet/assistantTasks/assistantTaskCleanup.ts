import { useEffect, useRef, useState } from "react";
import { cleanupLauncherTasks, type LauncherTaskCleanupResult, type LauncherTaskCleanupScope,
  type LauncherTaskCleanupTarget } from "../../../api/launcherAssistantTaskCleanup";
import type { AssistantTask } from "./assistantTeamRunTasks";
import { displayText, taskDisplayTitle } from "./assistantTaskMetadata";

export const taskCleanupKey = (target: LauncherTaskCleanupTarget) => JSON.stringify([target.kind, target.projectId,
  target.kind === "dispatch" ? target.dispatchId : target.originAction, target.kind === "team_run" ? target.requestId : null]);

export function taskGroup(task: AssistantTask): "attention" | "active" | "ended" {
  if (task.kind === "dispatch" && (task.cleanupPending === true || task.receiptBound && !task.conflictingObservations
    && ["succeeded", "failed", "cancelled", "timed_out"].includes(task.nativeStatus ?? ""))) return "ended";
  return task.state === "running" || task.state === "stopping" ? "active"
    : ["awaiting_verification", "failed", "stopped"].includes(task.state) ? "ended" : "attention";
}

export function taskTime(task: AssistantTask): number {
  // observedAt is a read timestamp, never a task update timestamp.
  return Date.parse(task.updatedAt || task.createdAt || "") || 0;
}

/** Local references ask the host to verify eligibility. They never authorize deletion. */
export function taskCleanupTargets(task: AssistantTask): LauncherTaskCleanupTarget[] {
  if (!task.projectId || task.conflictingObservations
    || ["running", "stopping", "waiting_user", "waiting_input"].includes(task.state)) return [];
  if (task.kind === "dispatch") return [{ kind: "dispatch", projectId: task.projectId, dispatchId: task.dispatchId }];
  return task.sourceRefs.map(reference => ({ kind: "team_run", projectId: task.projectId!, ...reference,
    ...(task.teamId ? { teamId: task.teamId } : {}), ...(task.flowId ? { flowId: task.flowId } : {}),
    ...(task.runId ? { runId: task.runId } : {}) }));
}

export type AssistantCleanupDialogState = {
  identity: string; scope: LauncherTaskCleanupScope; titles: Record<string, string>; bulk: boolean;
  pending: "loading" | "execute" | null; result?: LauncherTaskCleanupResult; error?: string;
  sourceErrors?: AssistantCleanupSourceError[];
};

export type AssistantCleanupSourceError = { source: "dispatch" | "team_run"; message: string };
export type AssistantCleanupCollection = { tasks: AssistantTask[]; sourceErrors?: AssistantCleanupSourceError[] };
type CleanupInput = Pick<AssistantCleanupDialogState, "scope" | "titles" | "sourceErrors">;
type TaskSource = AssistantTask[] | ((signal: AbortSignal) => Promise<AssistantTask[] | AssistantCleanupCollection>);

/** The host owns eligibility, fingerprints and deletion. One lock covers preparation and execution. */
export function useAssistantTaskCleanup(options: {
  agentId: string; sessionId: string; identity: string; canAct: boolean; lang: "zh" | "en"; onChanged: () => Promise<unknown>;
}) {
  const [state, setState] = useState<AssistantCleanupDialogState | null>(null);
  const generation = useRef(0);
  const operation = useRef<AbortController | null>(null);
  const executing = useRef<number | null>(null);
  const retryInput = useRef<((signal: AbortSignal) => Promise<CleanupInput>) | null>(null);
  const current = useRef(options);
  current.current = options;
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => {
    mounted.current = false; generation.current += 1; operation.current?.abort();
  }; }, []);
  const valid = (identity: string) => mounted.current && document.visibilityState !== "hidden"
    && current.current.canAct && current.current.identity === identity;
  const close = () => { generation.current += 1; operation.current?.abort(); executing.current = null; setState(null); };
  const visibleState = state && options.canAct && state.identity === options.identity ? state : null;
  useEffect(() => {
    if (state && (!options.canAct || state.identity !== options.identity)) close();
  }, [options.canAct, options.identity, state]);

  const run = async (input: (signal: AbortSignal) => Promise<CleanupInput>, bulk: boolean) => {
    const context = current.current;
    if (!valid(context.identity) || executing.current !== null) return;
    const token = ++generation.current;
    executing.current = token;
    const controller = new AbortController(); operation.current = controller;
    retryInput.current = input;
    let candidate: AssistantCleanupDialogState = { identity: context.identity, titles: {}, bulk, pending: "loading",
      scope: { agentId: context.agentId, directSessionId: context.sessionId, targets: [] } };
    setState(candidate);
    let attempted = false;
    try {
      const resolved = await input(controller.signal);
      controller.signal.throwIfAborted();
      if (generation.current !== token || !valid(candidate.identity)) return;
      candidate = { ...candidate, ...resolved, pending: "execute" };
      setState(candidate);
      attempted = candidate.scope.targets.length > 0;
      const result: LauncherTaskCleanupResult = attempted
        ? await cleanupLauncherTasks(candidate.scope, { signal: controller.signal })
        : { schemaVersion: 1, releasedBytes: 0, items: [] };
      if (generation.current !== token || !valid(candidate.identity)) return;
      const remaining = new Set(result.items.filter(item => item.status !== "deleted").map(item => item.key));
      const retryScope = { ...candidate.scope, targets: candidate.scope.targets.filter(target => remaining.has(taskCleanupKey(target))) };
      // An unavailable source supplied no deletion candidates. Recollect all
      // sources on retry so its complete authoritative list can be verified.
      // Otherwise retry only the host's unfinished references.
      if (!candidate.sourceErrors?.length) retryInput.current = async () => ({ scope: retryScope, titles: candidate.titles });
      setState({ ...candidate, pending: null, result });
    } catch (error) {
      if (generation.current === token && valid(candidate.identity))
        setState({ ...candidate, pending: null, error: displayText(error instanceof Error ? error.message : String(error)) });
    } finally {
      // Sent host requests may have completed even after visibility or identity loss.
      if (executing.current === token) executing.current = null;
      if (attempted && valid(candidate.identity)) await current.current.onChanged();
    }
  };
  const open = (source: TaskSource, bulk = false) => {
    const context = current.current;
    return run(async signal => {
      const collected = typeof source === "function" ? await source(signal) : source;
      const { tasks, sourceErrors } = Array.isArray(collected) ? { tasks: collected, sourceErrors: [] } : collected;
      const eligible = tasks.filter(task => taskCleanupTargets(task).length > 0);
      const targets = new Map<string, LauncherTaskCleanupTarget>();
      const titles: Record<string, string> = {};
      for (const task of eligible) for (const target of taskCleanupTargets(task)) {
        const key = taskCleanupKey(target);
        // Unknown-state targets always degrade to a verified record-only
        // removal, matching the single-item removals; the host still verifies
        // each one before deleting anything.
        targets.set(key, task.state === "unknown" ? { ...target, localOnly: true } : target);
        titles[key] = taskDisplayTitle(task.title, task.kind === "dispatch" ? task.dispatchId : task.requestId, context.lang);
      }
      return { scope: { agentId: context.agentId, directSessionId: context.sessionId, targets: [...targets.values()] }, titles,
        sourceErrors: sourceErrors?.map(error => ({ ...error, message: displayText(error.message) })) };
    }, bulk);
  };
  return { state: visibleState, busy: Boolean(visibleState?.pending), close, open,
    retry: () => state && retryInput.current ? run(retryInput.current, state.bulk) : Promise.resolve() };
}
