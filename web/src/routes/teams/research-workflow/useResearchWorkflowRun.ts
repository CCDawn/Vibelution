/**
 * Full WorkflowRun read-model owner (canvas + inspector + agents + timeline).
 * Does not let canvas projection wipe bindingSnapshots/handoffs/events.
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

export function useResearchWorkflowRun(runId: string): UseResearchWorkflowRunResult {
  const [projection, setProjection] = useState<WorkflowCanvasProjection | null>(null);
  const [run, setRun] = useState<WorkflowRunRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastSequence, setLastSequence] = useState(0);
  const seqRef = useRef(0);

  const applyRun = useCallback((record: WorkflowRunRecord) => {
    setRun(record);
    const events = Array.isArray(record.events) ? record.events : [];
    const maxSeq = events.reduce((max, evt) => Math.max(max, Number(evt.sequence) || 0), 0);
    if (maxSeq > seqRef.current) {
      seqRef.current = maxSeq;
      setLastSequence(maxSeq);
    }
  }, []);

  const refresh = useCallback(async () => {
    if (!runId) {
      const def = await fetchResearchWorkflowDefinition();
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
      return;
    }
    const [record, canvas, eventsPayload] = await Promise.all([
      fetchResearchWorkflowRun(runId),
      fetchResearchWorkflowCanvas(runId),
      fetchResearchWorkflowEvents(runId, seqRef.current),
    ]);
    // Full record is authoritative for bindings/handoffs/events/langGraph.
    const merged: WorkflowRunRecord = {
      ...record,
      // Keep the higher-fidelity fields if events snapshot carries them
      ...(eventsPayload.snapshot
        ? {
            bindingSnapshots:
              (eventsPayload.snapshot.bindingSnapshots as WorkflowRunRecord["bindingSnapshots"])
              || record.bindingSnapshots,
            handoffs:
              (eventsPayload.snapshot.handoffs as WorkflowRunRecord["handoffs"]) || record.handoffs,
            humanTasks:
              (eventsPayload.snapshot.humanTasks as WorkflowRunRecord["humanTasks"])
              || record.humanTasks,
            langGraph:
              (eventsPayload.snapshot.langGraph as WorkflowRunRecord["langGraph"]) || record.langGraph,
            runtimeCurrentNodeIds:
              (eventsPayload.snapshot.runtimeCurrentNodeIds as string[])
              || record.runtimeCurrentNodeIds,
            status: String(eventsPayload.snapshot.status || record.status),
          }
        : {}),
      events: [
        ...(record.events || []),
        ...((eventsPayload.events || []) as Array<Record<string, unknown>>),
      ],
    };
    applyRun(merged);
    setProjection({
      definition: canvas.definition,
      run: {
        ...canvas.run,
        runId,
        status: (merged.status as WorkflowCanvasProjection["run"]["status"]) || canvas.run.status,
        runtimeCurrentNodeIds: merged.runtimeCurrentNodeIds || canvas.run.runtimeCurrentNodeIds,
        pendingHumanTasks: (merged.humanTasks || [])
          .filter((t) => String(t.status) === "pending")
          .map((t) => ({
            taskId: String(t.taskId || ""),
            nodeId: String(t.nodeId || ""),
            status: String(t.status || ""),
            prompt: String(t.prompt || ""),
          })),
      },
    });
  }, [runId, applyRun]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setError(null);
        await refresh();
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  // Lightweight SSE substitute: poll events afterSequence while a run is active.
  useEffect(() => {
    if (!runId) return;
    const status = run?.status || "";
    if (!["waiting_human", "running", "queued"].includes(status)) return;
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const payload = await fetchResearchWorkflowEvents(runId, seqRef.current);
          if ((payload.events || []).length > 0 || payload.snapshot) {
            await refresh();
          }
        } catch {
          // keep last good snapshot
        }
      })();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [runId, run?.status, refresh]);

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
        applyRun(created);
        return created;
      } finally {
        setBusy(false);
      }
    },
    [applyRun],
  );

  const resolveHuman = useCallback(
    async (taskId: string, accept: boolean) => {
      if (!runId) throw new Error("no run");
      setBusy(true);
      setError(null);
      try {
        const next = await resolveResearchWorkflowHumanTask(runId, taskId, { accept });
        applyRun(next);
        await refresh();
        return next;
      } finally {
        setBusy(false);
      }
    },
    [runId, applyRun, refresh],
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
