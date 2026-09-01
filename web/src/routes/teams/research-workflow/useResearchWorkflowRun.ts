/**
 * Canonical Run read model: formal snapshot plus SSE deltas, with a bounded
 * low-frequency snapshot poll as a fallback for dropped streams and unknown
 * events (the poll stops once the run reaches a terminal status).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createResearchWorkflowRun,
  fetchResearchWorkflowDefinition,
  type CreateResearchWorkflowRunInput,
  type WorkflowRunRecord,
} from "../../../api/researchWorkflow";
import { submitResearchWorkflowCommand } from "../../../api/research-workflow/commands";
import type { CommandReceipt } from "../../../api/types/research-workflow/commands";
import type { WorkflowCanvasProjection } from "../../../api/types/researchWorkflow";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import type { ResearchWorkflowSnapshot } from "../../../api/types/research-workflow/core";
import {
  snapshotToCanvasProjection,
  snapshotToRunRecord,
} from "./researchWorkflowSnapshotProjection";
import { trackWorkflowHumanGateResolve } from "../challengeCupTelemetry";
import { useResearchWorkflowEventReplay } from "./useResearchWorkflowEventReplay";
import { useResearchWorkflowEventStream } from "./useResearchWorkflowEventStream";
import { useResearchWorkflowSnapshot } from "./useResearchWorkflowSnapshot";

/**
 * Fallback poll interval for the formal snapshot. SSE stays the primary
 * refresh path; this covers dropped streams and event shapes this build
 * cannot interpret, so revision/aggregation state never stays stale.
 */
const SNAPSHOT_FALLBACK_POLL_MS = 30_000;
/** Backend WorkflowRunStatus values after which nothing new can happen. */
const TERMINAL_RUN_STATUSES = new Set(["succeeded", "failed", "cancelled", "superseded"]);

export type UseResearchWorkflowRunResult = {
  projection: WorkflowCanvasProjection | null;
  run: WorkflowRunRecord | null;
  /** Formal snapshot v2 is kept beside the legacy canvas projection. */
  snapshot: ResearchWorkflowSnapshot | null;
  commandOffers: CommandOffer[];
  error: string | null;
  streamState: ReturnType<typeof useResearchWorkflowEventStream>["state"];
  resyncRequired: boolean;
  busy: boolean;
  lastSequence: number;
  refresh: () => Promise<void>;
  createRun: (input: CreateResearchWorkflowRunInput) => Promise<WorkflowRunRecord>;
  resolveHuman: (
    taskId: string,
    decision: "accept" | "reject" | "revise",
  ) => Promise<CommandReceipt>;
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
    if (
      eventState.resyncRequired
      || snapshotState.resyncRequired
      || eventState.lastSequence > snapshotState.lastSequence
    ) {
      scheduleRefresh();
    }
  }, [
    eventState.lastSequence,
    eventState.resyncRequired,
    scheduleRefresh,
    snapshotState.lastSequence,
    snapshotState.resyncRequired,
  ]);

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

  const runStatus = run?.status ?? null;
  useEffect(() => {
    if (!teamId.trim() || !runId.trim()) return;
    if (runStatus && TERMINAL_RUN_STATUSES.has(runStatus)) return;
    const pollTimer = window.setInterval(() => {
      const current = runRef.current;
      if (current && TERMINAL_RUN_STATUSES.has(current.status)) return;
      scheduleRefresh();
    }, SNAPSHOT_FALLBACK_POLL_MS);
    return () => window.clearInterval(pollTimer);
  }, [runId, runStatus, scheduleRefresh, teamId]);

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
      const telemetry = trackWorkflowHumanGateResolve({
        teamId: current.teamId,
        runId: current.runId,
        taskId,
        decision,
        idempotencyKey: `human:${current.runId}:${taskId}:${decision}:v${current.runVersion}`,
      });
      setBusy(true);
      try {
        const receipt = await submitResearchWorkflowCommand({
          teamId: current.teamId,
          runId: current.runId,
          command: "resolve_human_task",
          expectedRunVersion: current.runVersion,
          idempotencyKey: `human:${current.runId}:${taskId}:${decision}:v${current.runVersion}`,
          payload: { taskId, decision },
        });
        telemetry.succeeded();
        await snapshotState.refresh();
        return receipt;
      } catch (reason) {
        telemetry.failed(reason);
        throw reason;
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
    snapshot: snapshotState.snapshot,
    commandOffers: snapshotState.snapshot?.commandOffers ?? [],
    error,
    streamState: stream.state,
    resyncRequired: snapshotState.resyncRequired || eventState.resyncRequired,
    busy,
    lastSequence: Math.max(eventState.lastSequence, snapshotState.lastSequence),
    refresh: snapshotState.refresh,
    createRun,
    resolveHuman,
  };
}
