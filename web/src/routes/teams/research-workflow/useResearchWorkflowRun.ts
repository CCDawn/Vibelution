/** Canonical Run read model: initial HTTP snapshot plus SSE deltas, no polling fallback. */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  createResearchWorkflowRun,
  fetchResearchWorkflowCanvas,
  fetchResearchWorkflowDefinition,
  fetchResearchWorkflowRun,
  resolveResearchWorkflowHumanTask,
  type CreateResearchWorkflowRunInput,
  type WorkflowRunRecord,
} from "../../../api/researchWorkflow";
import type { WorkflowCanvasProjection } from "../../../api/types/researchWorkflow";
import {
  applyEventBatch,
  applyInitialRunEvents,
  emptyEventReadModel,
  type EventReadModelState,
  type WorkflowEventLike,
} from "./researchWorkflowEventReducer";
import {
  useResearchWorkflowStream,
  type ResearchWorkflowStreamState,
} from "./useResearchWorkflowStream";

export type UseResearchWorkflowRunResult = {
  projection: WorkflowCanvasProjection | null;
  run: WorkflowRunRecord | null;
  error: string | null;
  streamState: ResearchWorkflowStreamState;
  busy: boolean;
  lastSequence: number;
  refresh: () => Promise<void>;
  createRun: (input: CreateResearchWorkflowRunInput) => Promise<WorkflowRunRecord>;
  resolveHuman: (
    taskId: string,
    decision: "accept" | "reject" | "revise",
  ) => Promise<WorkflowRunRecord>;
};

export function useResearchWorkflowRun(
  teamId: string,
  runId: string,
): UseResearchWorkflowRunResult {
  const [projection, setProjection] = useState<WorkflowCanvasProjection | null>(null);
  const [run, setRun] = useState<WorkflowRunRecord | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastSequence, setLastSequence] = useState(0);
  const mountedRef = useRef(true);
  const scopeRef = useRef({ teamId, runId });
  const refreshGenerationRef = useRef(0);
  const eventStateRef = useRef<EventReadModelState>(emptyEventReadModel(runId));
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  scopeRef.current = { teamId, runId };

  const refresh = useCallback(async () => {
    const generation = ++refreshGenerationRef.current;
    const scope = { ...scopeRef.current };
    const canonicalTeamId = scope.teamId.trim();
    if (!canonicalTeamId) {
      setProjection(null);
      setRun(null);
      setLoadError("缺少 teamId，无法读取科研流程");
      return;
    }
    try {
      if (!scope.runId) {
        const definition = await fetchResearchWorkflowDefinition();
        if (!mountedRef.current || generation !== refreshGenerationRef.current) return;
        setProjection({
          definition: definition.definition,
          run: {
            runId: null,
            teamId: canonicalTeamId,
            runVersion: null,
            status: null,
            runtimeCurrentNodeIds: [],
            nodeRuns: {},
            pendingHumanTasks: [],
          },
        });
        setRun(null);
        eventStateRef.current = emptyEventReadModel("");
        setLastSequence(0);
        setLoadError(null);
        return;
      }

      const [record, canvas] = await Promise.all([
        fetchResearchWorkflowRun(scope.runId, { teamId: canonicalTeamId }),
        fetchResearchWorkflowCanvas(scope.runId, { teamId: canonicalTeamId }),
      ]);
      if (
        !mountedRef.current ||
        generation !== refreshGenerationRef.current ||
        scopeRef.current.runId !== scope.runId ||
        scopeRef.current.teamId.trim() !== canonicalTeamId
      ) {
        return;
      }
      const eventState = applyInitialRunEvents(
        scope.runId,
        record.events as WorkflowEventLike[] | undefined,
        eventStateRef.current.runId === scope.runId ? eventStateRef.current.events : [],
      );
      eventStateRef.current = eventState;
      setLastSequence(eventState.lastSequence);
      setRun({ ...record, events: eventState.events });
      setProjection({
        definition: canvas.definition,
        run: {
          ...canvas.run,
          runId: record.runId,
          teamId: record.teamId,
          runVersion: record.runVersion,
          status: record.status as WorkflowCanvasProjection["run"]["status"],
          runtimeCurrentNodeIds: record.runtimeCurrentNodeIds ?? [],
          pendingHumanTasks: (record.humanTasks ?? [])
            .filter((task) => String(task.status) === "pending")
            .map((task) => ({
              taskId: String(task.taskId ?? ""),
              nodeId: String(task.nodeId ?? ""),
              status: String(task.status ?? ""),
              prompt: String(task.prompt ?? ""),
            })),
        },
      });
      setLoadError(null);
    } catch (error) {
      if (mountedRef.current && generation === refreshGenerationRef.current) {
        setLoadError(error instanceof Error ? error.message : String(error));
      }
    }
  }, []);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimerRef.current) return;
    refreshTimerRef.current = setTimeout(() => {
      refreshTimerRef.current = null;
      void refresh();
    }, 80);
  }, [refresh]);

  const onStreamDelta = useCallback(
    (event: WorkflowEventLike) => {
      const activeRunId = scopeRef.current.runId;
      if (!activeRunId) return;
      const next = applyEventBatch(eventStateRef.current, {
        runId: activeRunId,
        events: [event],
      });
      eventStateRef.current = next;
      setLastSequence(next.lastSequence);
      setRun((current) =>
        current?.runId === activeRunId ? { ...current, events: next.events } : current,
      );
      scheduleRefresh();
    },
    [scheduleRefresh],
  );

  const onStreamSnapshot = useCallback(
    (cursor: number) => {
      if (cursor > eventStateRef.current.lastSequence) scheduleRefresh();
    },
    [scheduleRefresh],
  );

  const stream = useResearchWorkflowStream({
    teamId,
    runId,
    onDelta: onStreamDelta,
    onSnapshot: onStreamSnapshot,
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, []);

  useEffect(() => {
    eventStateRef.current = emptyEventReadModel(runId);
    setLastSequence(0);
    refreshGenerationRef.current += 1;
    void refresh();
  }, [refresh, runId, teamId]);

  const createRun = useCallback(async (input: CreateResearchWorkflowRunInput) => {
    setBusy(true);
    try {
      return await createResearchWorkflowRun(input);
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  }, []);

  const resolveHuman = useCallback(
    async (taskId: string, decision: "accept" | "reject" | "revise") => {
      const current = run;
      if (!current) throw new Error("当前没有可操作的工作流运行");
      setBusy(true);
      try {
        const updated = await resolveResearchWorkflowHumanTask(current.runId, taskId, {
          teamId: current.teamId,
          expectedRunVersion: current.runVersion,
          idempotencyKey: `human:${current.runId}:${taskId}:${decision}:v${current.runVersion}`,
          decision,
        });
        await refresh();
        return updated;
      } finally {
        if (mountedRef.current) setBusy(false);
      }
    },
    [refresh, run],
  );

  return {
    projection,
    run,
    error: loadError || stream.error,
    streamState: stream.state,
    busy,
    lastSequence,
    refresh,
    createRun,
    resolveHuman,
  };
}
