/**
 * Full WorkflowRun read-model owner (canvas + inspector + agents + timeline).
 * Event merge/polling live in dedicated modules — this hook only orchestrates.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  createResearchWorkflowRun,
  fetchResearchWorkflowCanvas,
  fetchResearchWorkflowDefinition,
  fetchResearchWorkflowEvents,
  fetchResearchWorkflowRun,
  resolveResearchWorkflowHumanTask,
  type WorkflowRunRecord,
} from "../../../api/researchWorkflow";
import type { WorkflowCanvasProjection } from "../../../api/types/researchWorkflow";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import {
  applyEventBatch,
  applyInitialRunEvents,
  emptyEventReadModel,
  type EventReadModelState,
  type WorkflowEventLike,
} from "./researchWorkflowEventReducer";
import { ResearchWorkflowPollingController } from "./researchWorkflowPollingController";

export type UseResearchWorkflowRunResult = {
  projection: WorkflowCanvasProjection | null;
  run: WorkflowRunRecord | null;
  error: string | null;
  busy: boolean;
  lastSequence: number;
  refresh: () => Promise<void>;
  createRun: (teamId: string) => Promise<WorkflowRunRecord>;
  resolveHuman: (taskId: string, accept: boolean) => Promise<WorkflowRunRecord>;
};

const POLLABLE = new Set(["waiting_human", "running", "queued", "blocked"]);

export function useResearchWorkflowRun(runId: string): UseResearchWorkflowRunResult {
  const [projection, setProjection] = useState<WorkflowCanvasProjection | null>(null);
  const [run, setRun] = useState<WorkflowRunRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastSequence, setLastSequence] = useState(0);

  const mountedRef = useRef(true);
  const runIdRef = useRef(runId);
  const eventStateRef = useRef<EventReadModelState>(emptyEventReadModel(runId));
  const pollRef = useRef<ResearchWorkflowPollingController | null>(null);
  const refreshGenRef = useRef(0);

  runIdRef.current = runId;

  const safeSet = useCallback(<T,>(setter: (value: T) => void, value: T) => {
    if (mountedRef.current) setter(value);
  }, []);

  const applyRunRecord = useCallback(
    (record: WorkflowRunRecord, events: WorkflowEventLike[]) => {
      if (!mountedRef.current) return;
      if (record.runId && runIdRef.current && record.runId !== runIdRef.current) return;
      const withEvents: WorkflowRunRecord = { ...record, events: events as WorkflowRunRecord["events"] };
      setRun(withEvents);
      const maxSeq = eventStateRef.current.lastSequence;
      setLastSequence(maxSeq);
      pollRef.current?.setAfterSequence(maxSeq);
    },
    [],
  );

  const refresh = useCallback(async () => {
    const gen = ++refreshGenRef.current;
    const activeRunId = runIdRef.current;
    if (!activeRunId) {
      const def = await fetchResearchWorkflowDefinition();
      if (!mountedRef.current || gen !== refreshGenRef.current) return;
      setProjection({
        definition: def.definition,
        run: {
          runId: null,
          status: null,
          runtimeCurrentNodeIds: [],
          nodeRuns: {},
          pendingHumanTasks: [],
        },
      });
      setRun(null);
      eventStateRef.current = emptyEventReadModel("");
      setLastSequence(0);
      return;
    }

    const [record, canvas] = await Promise.all([
      fetchResearchWorkflowRun(activeRunId),
      fetchResearchWorkflowCanvas(activeRunId),
    ]);
    if (!mountedRef.current || gen !== refreshGenRef.current || runIdRef.current !== activeRunId) {
      return;
    }

    // Initial / full refresh: record.events is authority; merge any accidental dupes.
    const eventState = applyInitialRunEvents(
      activeRunId,
      (record.events || []) as WorkflowEventLike[],
      [],
    );
    eventStateRef.current = eventState;

    applyRunRecord(record, eventState.events);
    setProjection({
      definition: canvas.definition,
      run: {
        ...canvas.run,
        runId: activeRunId,
        status: (record.status as WorkflowCanvasProjection["run"]["status"]) || canvas.run.status,
        runtimeCurrentNodeIds: record.runtimeCurrentNodeIds || canvas.run.runtimeCurrentNodeIds,
        pendingHumanTasks: (record.humanTasks || [])
          .filter((t) => String(t.status) === "pending")
          .map((t) => ({
            taskId: String(t.taskId || ""),
            nodeId: String(t.nodeId || ""),
            status: String(t.status || ""),
            prompt: String(t.prompt || ""),
          })),
      },
    });
  }, [applyRunRecord]);

  // Mount / unmount + runId change
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    // Reset event cursor when run switches
    eventStateRef.current = emptyEventReadModel(runId);
    setLastSequence(0);
    refreshGenRef.current += 1;
    let cancelled = false;
    (async () => {
      try {
        if (!cancelled) setError(null);
        await refresh();
      } catch (err) {
        if (!cancelled && mountedRef.current) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId, refresh]);

  // Polling controller lifecycle
  useEffect(() => {
    const controller = new ResearchWorkflowPollingController({
      intervalMs: 2500,
      fetchEvents: (id, after) => fetchResearchWorkflowEvents(id, after),
      onEvents: async (id, payload) => {
        if (!mountedRef.current || runIdRef.current !== id) return;
        const next = applyEventBatch(eventStateRef.current, {
          runId: id,
          events: (payload.events || []) as WorkflowEventLike[],
        });
        eventStateRef.current = next;
        setLastSequence(next.lastSequence);
        setRun((prev) => {
          if (!prev || prev.runId !== id) return prev;
          return { ...prev, events: next.events as WorkflowRunRecord["events"] };
        });
      },
      onNeedsRefresh: async (id) => {
        if (!mountedRef.current || runIdRef.current !== id) return;
        // Only re-fetch run + canvas (not blind triple) when new events arrived.
        try {
          const [record, canvas] = await Promise.all([
            fetchResearchWorkflowRun(id),
            fetchResearchWorkflowCanvas(id),
          ]);
          if (!mountedRef.current || runIdRef.current !== id) return;
          // Keep merged events; update other fields from record.
          const events = eventStateRef.current.events;
          applyRunRecord({ ...record, events: events as WorkflowRunRecord["events"] }, events);
          setProjection({
            definition: canvas.definition,
            run: {
              ...canvas.run,
              runId: id,
              status: (record.status as WorkflowCanvasProjection["run"]["status"]) || canvas.run.status,
              runtimeCurrentNodeIds: record.runtimeCurrentNodeIds || canvas.run.runtimeCurrentNodeIds,
              pendingHumanTasks: (record.humanTasks || [])
                .filter((t) => String(t.status) === "pending")
                .map((t) => ({
                  taskId: String(t.taskId || ""),
                  nodeId: String(t.nodeId || ""),
                  status: String(t.status || ""),
                  prompt: String(t.prompt || ""),
                })),
            },
          });
        } catch {
          // keep last good snapshot
        }
      },
    });
    pollRef.current = controller;
    controller.setRun(runId, eventStateRef.current.lastSequence);
    return () => {
      controller.dispose();
      if (pollRef.current === controller) pollRef.current = null;
    };
  }, [runId, applyRunRecord]);

  useEffect(() => {
    const controller = pollRef.current;
    if (!controller || !runId) return;
    const status = run?.status || "";
    if (!POLLABLE.has(status)) {
      controller.stop();
      return;
    }
    controller.setRun(runId, eventStateRef.current.lastSequence);
    controller.start();
    return () => {
      controller.stop();
    };
  }, [runId, run?.status]);

  const createRun = useCallback(
    async (teamId: string) => {
      setBusy(true);
      setError(null);
      try {
        const created = await createResearchWorkflowRun({
          teamId,
          workflowId: CHALLENGE_CUP_WORKFLOW_ID,
          idempotencyKey: `ui-${teamId || "default"}-${Date.now()}`,
        });
        if (mountedRef.current) {
          const events = (created.events || []) as WorkflowEventLike[];
          eventStateRef.current = applyInitialRunEvents(created.runId, events, []);
          applyRunRecord(created, eventStateRef.current.events);
        }
        return created;
      } finally {
        if (mountedRef.current) setBusy(false);
      }
    },
    [applyRunRecord],
  );

  const resolveHuman = useCallback(
    async (taskId: string, accept: boolean) => {
      if (!runId) throw new Error("no run");
      setBusy(true);
      setError(null);
      try {
        const next = await resolveResearchWorkflowHumanTask(runId, taskId, { accept });
        if (mountedRef.current && runIdRef.current === runId) {
          const events = (next.events || []) as WorkflowEventLike[];
          eventStateRef.current = applyInitialRunEvents(runId, events, []);
          applyRunRecord(next, eventStateRef.current.events);
          await refresh();
        }
        return next;
      } finally {
        if (mountedRef.current) setBusy(false);
      }
    },
    [runId, applyRunRecord, refresh],
  );

  return {
    projection,
    run,
    error,
    busy,
    lastSequence,
    refresh,
    createRun,
    resolveHuman,
  };
}
