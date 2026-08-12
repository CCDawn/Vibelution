/** Canonical Run read model: formal snapshot plus SSE deltas, no polling fallback. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createResearchWorkflowRun,
  fetchResearchWorkflowDefinition,
  resolveResearchWorkflowHumanTask,
  type CreateResearchWorkflowRunInput,
  type WorkflowRunRecord,
} from "../../../api/researchWorkflow";
import type { WorkflowCanvasProjection } from "../../../api/types/researchWorkflow";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import {
  snapshotToCanvasProjection,
  snapshotToRunRecord,
} from "./researchWorkflowSnapshotProjection";
import { useResearchWorkflowEventReplay } from "./useResearchWorkflowEventReplay";
import { useResearchWorkflowEventStream } from "./useResearchWorkflowEventStream";
import { useResearchWorkflowSnapshot } from "./useResearchWorkflowSnapshot";

export type UseResearchWorkflowRunResult = {
  projection: WorkflowCanvasProjection | null;
  run: WorkflowRunRecord | null;
  commandOffers: CommandOffer[];
  error: string | null;
  streamState: ReturnType<typeof useResearchWorkflowEventStream>["state"];
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
  const snapshotState = useResearchWorkflowSnapshot(teamId, runId);
  const replay = useResearchWorkflowEventReplay({
    teamId,
    runId,
    enabled: Boolean(teamId.trim() && runId.trim() && snapshotState.snapshot),
    latestEventSequence: snapshotState.snapshot?.latestEventSequence ?? 0,
  });
  const eventState = replay.model;
  const [definitionProjection, setDefinitionProjection] =
    useState<WorkflowCanvasProjection | null>(null);
  const [definitionError, setDefinitionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const mountedRef = useRef(true);
  const runRef = useRef<WorkflowRunRecord | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimerRef.current) return;
    refreshTimerRef.current = setTimeout(() => {
      refreshTimerRef.current = null;
      void snapshotState.refresh();
    }, 80);
  }, [snapshotState.refresh]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, []);

  useEffect(() => {
    const canonicalTeamId = teamId.trim();
    if (runId.trim() || !canonicalTeamId) {
      setDefinitionProjection(null);
      setDefinitionError(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const definition = await fetchResearchWorkflowDefinition();
        if (cancelled || !mountedRef.current) return;
        setDefinitionProjection({
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
        setDefinitionError(null);
      } catch (reason) {
        if (cancelled || !mountedRef.current) return;
        setDefinitionError(reason instanceof Error ? reason.message : String(reason));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId, teamId]);

  useEffect(() => {
    if (eventState.resyncRequired) {
      scheduleRefresh();
    }
  }, [eventState.resyncRequired, scheduleRefresh]);

  const stream = useResearchWorkflowEventStream({
    teamId,
    runId,
    afterSequence: eventState.lastSequence,
    initialAfterSequence: eventState.lastSequence,
    onEvent: replay.applyStreamEvent,
    enabled: Boolean(teamId.trim() && runId.trim() && replay.ready),
  });

  const projection = useMemo(() => {
    if (snapshotState.snapshot) {
      return snapshotToCanvasProjection(snapshotState.snapshot);
    }
    return definitionProjection;
  }, [definitionProjection, snapshotState.snapshot]);

  const run = useMemo(() => {
    if (!snapshotState.snapshot) return null;
    return snapshotToRunRecord(snapshotState.snapshot, eventState.events);
  }, [eventState.events, snapshotState.snapshot]);

  runRef.current = run;

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
      const current = runRef.current;
      if (!current) throw new Error("当前没有可操作的工作流运行");
      setBusy(true);
      try {
        const updated = await resolveResearchWorkflowHumanTask(current.runId, taskId, {
          teamId: current.teamId,
          expectedRunVersion: current.runVersion,
          idempotencyKey: `human:${current.runId}:${taskId}:${decision}:v${current.runVersion}`,
          decision,
        });
        await snapshotState.refresh();
        return updated;
      } finally {
        if (mountedRef.current) setBusy(false);
      }
    },
    [snapshotState.refresh],
  );

  const error =
    snapshotState.error
    || definitionError
    || replay.error
    || stream.error
    || (eventState.resyncRequired ? "工作流事件序列出现缺口，正在重新同步" : null);

  return {
    projection,
    run,
    commandOffers: snapshotState.snapshot?.commandOffers ?? [],
    error,
    streamState: stream.state,
    busy,
    lastSequence: eventState.lastSequence,
    refresh: snapshotState.refresh,
    createRun,
    resolveHuman,
  };
}
