import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  commandTeamFlowRun, listTeamFlowRuns, listTeamFlows, saveTeamFlow, startTeamFlowRun, teamFlowKeys,
} from "../../../api/genericTeamWorkflows";
import type { TeamFlowCommand } from "../../../api/types/genericTeamWorkflow";
import { usePageVisibility } from "../../../app/pollingPolicy";
import { mergeSavedFlows, sameFlowContent, type Flow, type Run } from "./workflowModel";

const errorText = (error: unknown) => error instanceof Error ? error.message : "操作未完成，请重试。";

/** Server queries own saved definitions/runs; drafts never overwrite polling results. */
export function useWorkflowWorkspace(teamId: string) {
  const client = useQueryClient();
  const visible = usePageVisibility();
  const [flows, setFlows] = useState<Flow[]>([]);
  const [flowId, setFlowId] = useState("");
  const [dirtyIds, setDirtyIds] = useState<string[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [pending, setPending] = useState(false);
  const flowsRef = useRef(flows);
  flowsRef.current = flows;
  const definitions = useQuery({
    queryKey: teamFlowKeys.flows(teamId),
    queryFn: ({ signal }) => listTeamFlows(teamId, signal),
    staleTime: 10_000,
  });
  const executions = useQuery({
    queryKey: teamFlowKeys.runs(teamId),
    queryFn: ({ signal }) => listTeamFlowRuns(teamId, signal),
    refetchInterval: query => query.state.data?.runs.some(run => run.status === "running") ? visible ? 1500 : 10_000 : false,
  });
  useEffect(() => {
    if (definitions.data) setFlows(current => mergeSavedFlows(current, definitions.data.flows, dirtyIds));
  }, [definitions.data, dirtyIds]);

  const flow = flows.find(item => item.id === flowId) ?? flows[0];
  const runs = executions.data?.runs ?? [];
  const run = runs.find(item => item.id === runId && item.flow.id === flow?.id);

  function selectFlow(id: string) { setFlowId(id); setRunId(null); setError(""); }
  function editFlow(update: (current: Flow) => Flow) {
    if (!flow) return;
    setFlows(current => current.map(item => item.id === flow.id ? update(item) : item));
    setDirtyIds(current => current.includes(flow.id) ? current : [...current, flow.id]);
  }
  function addFlow(item: Flow) {
    setFlows(current => [...current, item]);
    setDirtyIds(current => [...current, item.id]);
    selectFlow(item.id);
  }
  function receiveRun(item: Run) {
    client.setQueryData<{ teamId: string; runs: Run[] }>(teamFlowKeys.runs(teamId), current => ({
      teamId, runs: [item, ...(current?.runs ?? []).filter(run => run.id !== item.id)],
    }));
    setRunId(item.id);
    void client.invalidateQueries({ queryKey: teamFlowKeys.runs(teamId) });
  }
  async function save(): Promise<Flow | undefined> {
    if (!flow || saving) return;
    if (!dirtyIds.includes(flow.id) && flow.revision > 0) return flow;
    setSaving(true); setError("");
    const snapshot = structuredClone(flow);
    try {
      const saved = await saveTeamFlow(teamId, snapshot);
      const clean = sameFlowContent(flowsRef.current.find(item => item.id === snapshot.id) ?? snapshot, snapshot);
      setFlows(current => current.map(item => item.id === saved.id
        ? sameFlowContent(item, snapshot) ? saved : { ...item, revision: saved.revision, updatedAt: saved.updatedAt }
        : item));
      if (clean) setDirtyIds(current => current.filter(id => id !== saved.id));
      client.setQueryData<{ schemaVersion: number; teamId: string; flows: Flow[] }>(teamFlowKeys.flows(teamId), current => ({
        schemaVersion: 1, teamId, flows: [...(current?.flows ?? []).filter(item => item.id !== saved.id), saved],
      }));
      return saved;
    } catch (failure) { setError(errorText(failure)); return; }
    finally { setSaving(false); }
  }
  async function start(snapshot: Flow, values: Record<string, string>, key: string): Promise<Run | undefined> {
    if (pending) return;
    setPending(true); setError("");
    try { const item = await startTeamFlowRun(teamId, snapshot, values, key); receiveRun(item); return item; }
    catch (failure) { setError(errorText(failure)); return; }
    finally { setPending(false); }
  }
  async function command(action: TeamFlowCommand): Promise<Run | undefined> {
    if (!run || pending) return;
    setPending(true); setError("");
    try { const item = await commandTeamFlowRun(teamId, run, action); receiveRun(item); return item; }
    catch (failure) { setError(errorText(failure)); void executions.refetch(); return; }
    finally { setPending(false); }
  }
  return {
    flows, flow, runs, run, dirty: Boolean(flow && dirtyIds.includes(flow.id)),
    selectFlow, editFlow, addFlow, save, start, command, selectRun: setRunId,
    saving, pending, loading: definitions.isPending, error: error || (definitions.error ? errorText(definitions.error) : "") || (executions.error ? errorText(executions.error) : ""),
    clearError: () => setError(""), reload: () => { void definitions.refetch(); void executions.refetch(); },
  };
}
