import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  commandTeamFlowRun, listTeamFlowRuns, saveTeamFlow, startTeamFlowRun, teamFlowKeys,
} from "../../../api/genericTeamWorkflows";
import type { TeamFlowCommand } from "../../../api/types/genericTeamWorkflow";
import { useWorkflowDefinitions } from "./useWorkflowDefinitions";
import { usePageVisibility } from "../../../app/pollingPolicy";
import { isEditableWorkflow, mergeSavedFlows, sameFlowContent, type Flow, type Run } from "./workflowModel";

const errorText = (error: unknown) => error instanceof Error ? error.message : "操作未完成，请重试。";
type Draft = { flows: Flow[]; flowId: string; dirtyIds: string[]; runId: string | null; error: string;
  uncertainSaves: Record<string, { snapshot: Flow; error: string }> };
const EMPTY_DRAFT: Draft = { flows: [], flowId: "", dirtyIds: [], runId: null, error: "", uncertainSaves: {} };
const scopeKey = (teamId: string, kind: "flow" | "run", id: string) => JSON.stringify([teamId, kind, id]);
// Compare every submitted field, including policy, while admitting server defaults.
function sameSubmittedFlow(a: Flow, b: Flow) {
  const content = ({ revision: _revision, updatedAt: _updatedAt, ...flow }: Flow) => ({ ...flow,
    failureRecovery: flow.failureRecovery ?? null,
    steps: flow.steps.map(step => ({ ...step, resultContract: step.resultContract ?? "text",
      researchSource: step.researchSource ?? null, sessionSource: step.sessionSource ?? null })),
  });
  const encode = (flow: Flow) => JSON.stringify(content(flow), (_key, value) =>
    value && typeof value === "object" && !Array.isArray(value)
      ? Object.fromEntries(Object.keys(value).sort().map(key => [key, value[key]])) : value);
  return encode(a) === encode(b);
}

/** Server queries own saved definitions/runs; drafts never overwrite polling results. */
export function useWorkflowWorkspace(teamId: string) {
  const client = useQueryClient();
  const visible = usePageVisibility();
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [uncertainSaveVersion, setUncertainSaveVersion] = useState(0);
  const { flows, flowId, dirtyIds, runId, error } = drafts[teamId] ?? EMPTY_DRAFT;
  const busyRef = useRef(new Map<string, "save" | "start" | "command">());
  const [busy, setBusy] = useState(busyRef.current);
  function updateDraft(update: (current: Draft) => Draft) {
    setDrafts(current => ({ ...current, [teamId]: update(current[teamId] ?? EMPTY_DRAFT) }));
  }
  function occupy(key: string, action: "save" | "start" | "command") {
    if (busyRef.current.has(key)) return false;
    busyRef.current.set(key, action); setBusy(new Map(busyRef.current)); return true;
  }
  function release(key: string) { busyRef.current.delete(key); setBusy(new Map(busyRef.current)); }
  function reconcile() {
    void client.invalidateQueries({ queryKey: teamFlowKeys.flows(teamId) }).catch(() => undefined);
    void client.invalidateQueries({ queryKey: teamFlowKeys.runs(teamId) }).catch(() => undefined);
  }
  const definitions = useWorkflowDefinitions(teamId);
  const executions = useQuery({
    queryKey: teamFlowKeys.runs(teamId),
    queryFn: ({ signal }) => listTeamFlowRuns(teamId, signal),
    refetchInterval: query => query.state.data?.runs.some(run => run.status === "running") ? visible ? 1500 : 10_000 : false,
  });
  useEffect(() => {
    if (definitions.data?.teamId === teamId) {
      const editable = definitions.data.flows.filter(isEditableWorkflow);
      updateDraft(current => {
        const uncertainSaves = { ...current.uncertainSaves };
        let dirtyIds = current.dirtyIds;
        let error = current.error;
        const local = current.flows.filter(isEditableWorkflow).map(flow => {
          const uncertain = uncertainSaves[flow.id];
          const saved = editable.find(item => item.id === flow.id);
          // save_flow advances exactly one revision. Other content is a conflict,
          // never permission to rebase a dirty draft onto another writer's revision.
          if (!uncertain || !saved || flow.revision !== uncertain.snapshot.revision
            || saved.revision !== uncertain.snapshot.revision + 1 || !sameSubmittedFlow(saved, uncertain.snapshot)) return flow;
          delete uncertainSaves[flow.id];
          if (flow.id === current.flowId && error === uncertain.error) error = "";
          if (sameSubmittedFlow(flow, uncertain.snapshot)) {
            dirtyIds = dirtyIds.filter(id => id !== flow.id);
            return saved;
          }
          return { ...flow, revision: saved.revision, updatedAt: saved.updatedAt };
        });
        return { ...current, uncertainSaves, dirtyIds, error,
          flows: mergeSavedFlows(local, editable, dirtyIds),
          flowId: editable.some(item => item.id === current.flowId) || dirtyIds.includes(current.flowId)
            ? current.flowId : editable[0]?.id || "",
        };
      });
    }
  }, [definitions.data, teamId, uncertainSaveVersion]);

  const flow = flows.find(item => item.id === flowId) ?? flows[0];
  const runs = (executions.data?.runs ?? []).filter(item => isEditableWorkflow(item.flow));
  const run = runs.find(item => item.id === runId && item.flow.id === flow?.id);
  const viewKey = JSON.stringify([teamId, flow?.id, runId]);
  const viewRef = useRef({ key: viewKey, generation: 0 });
  if (viewRef.current.key !== viewKey) viewRef.current = { key: viewKey, generation: viewRef.current.generation + 1 };
  const flowScope = scopeKey(teamId, "flow", flow?.id ?? "");
  const saving = busy.get(flowScope) === "save";
  const pending = busy.get(flowScope) === "start" || Boolean(run && busy.has(scopeKey(teamId, "run", run.id)));

  function selectFlow(id: string) { updateDraft(current => ({ ...current, flowId: id, runId: null, error: "" })); }
  function editFlow(update: (current: Flow) => Flow) {
    if (!flow) return;
    updateDraft(current => ({ ...current, flows: current.flows.map(item => item.id === flow.id ? update(item) : item),
      dirtyIds: current.dirtyIds.includes(flow.id) ? current.dirtyIds : [...current.dirtyIds, flow.id] }));
  }
  function addFlow(item: Flow) {
    updateDraft(current => ({ ...current, flows: [...current.flows, item], dirtyIds: [...current.dirtyIds, item.id],
      flowId: item.id, runId: null, error: "" }));
  }
  function receiveRun(item: Run, select: boolean) {
    client.setQueryData<{ teamId: string; runs: Run[] }>(teamFlowKeys.runs(teamId), current => ({
      teamId, runs: [item, ...(current?.runs ?? []).filter(run => run.id !== item.id)],
    }));
    if (select) updateDraft(current => ({ ...current, runId: item.id }));
    void client.invalidateQueries({ queryKey: teamFlowKeys.runs(teamId) }).catch(() => undefined);
  }
  async function save(): Promise<Flow | undefined> {
    if (!flow || busyRef.current.has(flowScope)) return;
    if (!dirtyIds.includes(flow.id) && flow.revision > 0) return flow;
    occupy(flowScope, "save"); updateDraft(current => ({ ...current, error: "" }));
    const generation = viewRef.current.generation;
    const snapshot = structuredClone(flow);
    try {
      const saved = await saveTeamFlow(teamId, snapshot);
      updateDraft(current => {
        const clean = sameFlowContent(current.flows.find(item => item.id === snapshot.id) ?? snapshot, snapshot);
        const uncertainSaves = { ...current.uncertainSaves };
        delete uncertainSaves[saved.id];
        return { ...current, uncertainSaves, flows: current.flows.map(item => item.id === saved.id
          ? sameFlowContent(item, snapshot) ? saved : { ...item, revision: saved.revision, updatedAt: saved.updatedAt }
          : item), dirtyIds: clean ? current.dirtyIds.filter(id => id !== saved.id) : current.dirtyIds };
      });
      client.setQueryData<{ schemaVersion: number; teamId: string; flows: Flow[] }>(teamFlowKeys.flows(teamId), current => ({
        schemaVersion: 1, teamId, flows: [...(current?.flows ?? []).filter(item => item.id !== saved.id), saved],
      }));
      return generation === viewRef.current.generation ? saved : undefined;
    } catch (failure) {
      const uncertain = failure instanceof Error && failure.name === "TeamFlowWriteOutcomeUnknownError";
      updateDraft(current => ({ ...current,
        error: generation === viewRef.current.generation ? errorText(failure) : current.error,
        uncertainSaves: uncertain
          ? { ...current.uncertainSaves, [snapshot.id]: { snapshot, error: errorText(failure) } } : current.uncertainSaves,
      }));
      // A reload may already have read this write before it timed out. Query
      // structural sharing can retain the same data reference on the next read.
      if (uncertain) setUncertainSaveVersion(current => current + 1);
      reconcile();
      return;
    } finally { release(flowScope); }
  }
  async function start(snapshot: Flow, values: Record<string, string>, key: string): Promise<Run | undefined> {
    const scope = scopeKey(teamId, "flow", snapshot.id);
    if (!occupy(scope, "start")) return;
    updateDraft(current => ({ ...current, error: "" }));
    const generation = viewRef.current.generation;
    try {
      const item = await startTeamFlowRun(teamId, snapshot, values, key);
      const current = generation === viewRef.current.generation;
      receiveRun(item, current); return current ? item : undefined;
    } catch (failure) {
      if (generation === viewRef.current.generation) updateDraft(current => ({ ...current, error: errorText(failure) }));
      reconcile();
      return;
    } finally { release(scope); }
  }
  async function command(action: TeamFlowCommand): Promise<Run | undefined> {
    if (!run) return;
    const scope = scopeKey(teamId, "run", run.id);
    if (!occupy(scope, "command")) return;
    updateDraft(current => ({ ...current, error: "" }));
    const generation = viewRef.current.generation;
    try {
      const item = await commandTeamFlowRun(teamId, run, action);
      const current = generation === viewRef.current.generation;
      receiveRun(item, current); return current ? item : undefined;
    } catch (failure) {
      if (generation === viewRef.current.generation) updateDraft(current => ({ ...current, error: errorText(failure) }));
      reconcile(); return;
    } finally { release(scope); }
  }
  return {
    flows, flow, runs, run, dirty: Boolean(flow && dirtyIds.includes(flow.id)),
    selectFlow, editFlow, addFlow, save, start, command,
    selectRun: (id: string | null) => updateDraft(current => ({ ...current, runId: id, error: "" })),
    saving, pending, loading: definitions.isPending || (definitions.isSuccess && !drafts[teamId]), error: error || (definitions.error ? errorText(definitions.error) : "") || (executions.error ? errorText(executions.error) : ""),
    clearError: () => updateDraft(current => ({ ...current, error: "" })), reload: () => { void definitions.refetch(); void executions.refetch(); },
  };
}
